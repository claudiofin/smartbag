#!/usr/bin/env python3
"""Enrolment and recognition: train an embedding, enrol objects, measure it.

⭐ THE SHAPE IS FACE ID's, and that is the whole argument. Recognising an
arbitrary object from three IR frames on a microcontroller NPU is open-set
recognition and is not solved at this power budget. Recognising *your twenty
objects*, after you have shown each one once, is a nearest-neighbour lookup —
a different problem, and a tractable one.

So the embedding is trained once, offline, on objects the product will never
see. Enrolment then stores a prototype per object and recognition is a cosine
comparison. Nothing about the enrolled objects reaches the weights, which is
what makes the measured numbers mean anything.

⛔ WHAT THE NUMBERS DO NOT SAY. The subjects are primitives. A high score here
is evidence that the *pipeline* survives the imaging conditions — 96x96
monochrome, motion-blurred, lit only by four IR LEDs — and no evidence at all
that a wallet can be told from a passport. Read it as a test of the method, not
of the product.

Usage:  python3 ml/classify.py [--epochs 12] [--enrol 5]
"""
import os
import random
import sys

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "dataset")
SEED = 11


def args():
    a = sys.argv[1:]

    def val(n, d):
        return int(a[a.index(n) + 1]) if n in a else d
    return val("--epochs", 40), val("--enrol", 5)


def load():
    """{group: {class name: array of images}}, images as float32 in 0..1."""
    out = {}
    if not os.path.isdir(DATA):
        raise SystemExit(
            "no dataset. Run:\n"
            "  blender -b --python ml/render_dataset.py -- --samples 110")
    for folder in sorted(os.listdir(DATA)):
        if "_" not in folder:
            continue
        group, name = folder.split("_", 1)
        imgs = []
        for f in sorted(os.listdir(os.path.join(DATA, folder))):
            if f.endswith(".png"):
                a = np.asarray(Image.open(os.path.join(DATA, folder, f))
                               .convert("L"), dtype=np.float32) / 255.0
                imgs.append(a)
        if imgs:
            out.setdefault(int(group), {})[name] = np.stack(imgs)
    return out


class Embedder(nn.Module):
    """⚠️ Deliberately small: four conv layers, 32 channels at the widest, and a
    64-dimensional embedding. It is not chosen for accuracy but for the target —
    a few hundred thousand MACs per frame is the scale an MCU NPU can run inside
    the burst budget. A ResNet would score better here and could not run there,
    which would make the measurement worthless."""

    # ⛔ POOLING TO 1x1 THREW AWAY THE ONLY CUE THERE IS. The first version
    # ended in AdaptiveAvgPool2d(1): 32 numbers, no spatial layout. For subjects
    # that differ by SHAPE and nothing else that is close to averaging the
    # answer away, and it showed — 0.67 train accuracy and an embedding so
    # collapsed that unknown objects scored 0.98 against enrolled prototypes.
    # A 3x3 map keeps coarse geometry at a cost of 288 features.
    #
    # ⚠️ The head works on the NORMALISED embedding, so its logits live in
    # [-1, 1] and cross-entropy has almost no gradient to work with. The scale
    # factor is the standard fix (the same trick as CosFace) and it is what
    # makes this train at all.
    LOGIT_SCALE = 16.0

    def __init__(self, n_classes, dim=64):
        super().__init__()
        self.features = nn.Sequential(
            nn.Conv2d(1, 16, 3, stride=2, padding=1), nn.BatchNorm2d(16), nn.ReLU(),
            nn.Conv2d(16, 32, 3, stride=2, padding=1), nn.BatchNorm2d(32), nn.ReLU(),
            nn.Conv2d(32, 48, 3, stride=2, padding=1), nn.BatchNorm2d(48), nn.ReLU(),
            nn.Conv2d(48, 32, 3, stride=1, padding=1), nn.BatchNorm2d(32), nn.ReLU(),
            nn.AdaptiveAvgPool2d(3))
        self.embed = nn.Linear(32 * 9, dim)
        self.head = nn.Linear(dim, n_classes, bias=False)

    def forward(self, x, embedding_only=False):
        z = self.embed(self.features(x).flatten(1))
        z = F.normalize(z, dim=1)
        return z if embedding_only else self.head(z) * self.LOGIT_SCALE


def augment(batch):
    """⭐ Noise and gain jitter, because the real sensor has both. Without them
    the model latches onto absolute brightness, which is the one cue an IR
    camera with variable illuminator duty cycle cannot promise."""
    g = torch.empty(batch.shape[0], 1, 1, 1).uniform_(0.7, 1.4)
    n = torch.randn_like(batch) * 0.03
    return (batch * g + n).clamp(0, 1)


def train_embedding(train, epochs):
    names = sorted(train)
    xs = np.concatenate([train[n] for n in names])
    ys = np.concatenate([np.full(len(train[n]), i) for i, n in enumerate(names)])
    x = torch.from_numpy(xs).unsqueeze(1)
    y = torch.from_numpy(ys).long()

    model = Embedder(len(names))
    opt = torch.optim.Adam(model.parameters(), lr=3e-3)
    sched = torch.optim.lr_scheduler.CosineAnnealingLR(opt, T_max=epochs)
    n = len(x)
    for ep in range(epochs):
        model.train()
        perm = torch.randperm(n)
        total, correct, loss_sum = 0, 0, 0.0
        for i in range(0, n, 64):
            idx = perm[i:i + 64]
            xb, yb = augment(x[idx]), y[idx]
            opt.zero_grad()
            out = model(xb)
            loss = F.cross_entropy(out, yb)
            loss.backward()
            opt.step()
            loss_sum += loss.item() * len(idx)
            correct += (out.argmax(1) == yb).sum().item()
            total += len(idx)
        sched.step()
        if (ep + 1) % 5 == 0 or ep == epochs - 1:
            print(f"   epoch {ep + 1:>2}  loss {loss_sum / total:.3f}  "
                  f"train acc {correct / total:.3f}")
    model.eval()
    return model, names


def embed(model, images):
    with torch.no_grad():
        return model(torch.from_numpy(images).unsqueeze(1),
                     embedding_only=True).numpy()


def enrol(model, held_out, k):
    """One prototype per object: the mean of k enrolment samples.

    ⚠️ k is small on purpose. Enrolment is setup cost, and a product that needs
    fifty views of every object before it works is a product nobody finishes
    setting up.
    """
    protos, rest = {}, {}
    for name, imgs in held_out.items():
        z = embed(model, imgs)
        protos[name] = z[:k].mean(0) / (np.linalg.norm(z[:k].mean(0)) + 1e-9)
        rest[name] = z[k:]
    return protos, rest


def recognise(protos, z, threshold):
    names = list(protos)
    M = np.stack([protos[n] for n in names])
    sims = M @ z
    best = int(np.argmax(sims))
    return (names[best], float(sims[best])) if sims[best] >= threshold \
        else (None, float(sims[best]))


def burst(zs, n):
    """Average n embeddings, the way the device averages its capture burst."""
    idx = np.random.choice(len(zs), size=n, replace=False)
    v = zs[idx].mean(0)
    return v / (np.linalg.norm(v) + 1e-9)


def closed_set(protos, rest, frames):
    """Accuracy with no rejection: the question the ledger actually asks."""
    names = sorted(protos)
    M = np.stack([protos[n] for n in names])
    hits = total = 0
    for n in names:
        zs = rest[n]
        trials = len(zs) if frames == 1 else len(zs) // frames
        for t in range(trials):
            z = zs[t] if frames == 1 else burst(zs, frames)
            hits += names[int(np.argmax(M @ z))] == n
            total += 1
    return hits, total


def calibrate(model, train, k):
    """Pick the rejection threshold without touching the test set.

    ⛔ CALIBRATING ON THE TRAINING OBJECTS DIRECTLY DID NOT WORK, and the reason
    is worth keeping: the training catalogue was built to mirror the enrolled
    one — a bar of leather for a wallet, a thin rod for a lipstick. Those are not
    "unknown objects", they are near-duplicates of the enrolled ones, so the
    95th percentile of their similarity came out at 0.984 and the threshold
    rejected everything, including 96% of the objects it was supposed to accept.

    ⭐ Instead: split the training classes in half, enrol one half as pretend
    users and treat the other half as pretend unknowns, then take the threshold
    that maximises balanced accuracy on that. No test data is involved.
    """
    names = sorted(train)
    half = len(names) // 2
    users, unknowns = names[:half], names[half:]
    protos = {}
    accepts = []
    for n in users:
        z = model_embed(model, train[n])
        p = z[:k].mean(0)
        protos[n] = p / (np.linalg.norm(p) + 1e-9)
        accepts.append(z[k:])
    M = np.stack([protos[n] for n in users])
    pos = np.concatenate([(M @ z.T).max(0) for z in accepts])
    neg = np.concatenate([(M @ model_embed(model, train[n]).T).max(0)
                          for n in unknowns])
    best_t, best_score = 0.0, -1.0
    for t in np.linspace(0.3, 0.99, 140):
        score = 0.5 * (pos >= t).mean() + 0.5 * (neg < t).mean()
        if score > best_score:
            best_t, best_score = float(t), float(score)
    return best_t, best_score


def model_embed(model, imgs):
    return embed(model, imgs)


def main():
    epochs, k = args()
    random.seed(SEED)
    np.random.seed(SEED)
    torch.manual_seed(SEED)

    data = load()
    train, held, strangers = data.get(0, {}), data.get(1, {}), data.get(2, {})
    print(f"embedding trained on {len(train)} objects the product never sees: "
          f"{', '.join(sorted(train))}")
    print(f"enrolled and tested: {', '.join(sorted(held))}")
    print(f"never enrolled, must be rejected: {', '.join(sorted(strangers))}\n")

    model, _ = train_embedding(train, epochs)
    protos, rest = enrol(model, held, k)
    names = sorted(protos)
    M = np.stack([protos[n] for n in names])

    print("\n── closed set: which of my enrolled objects is this?")
    print(f"   chance is {1 / len(names):.3f}")
    for frames in (1, 3):
        hits, total = closed_set(protos, rest, frames)
        label = "single frame" if frames == 1 else "3-frame burst, as the device takes"
        print(f"   {label:<38} {hits}/{total} = {hits / total:.3f}")

    print("\n── open set: is this something I know at all?")
    t, cal_score = calibrate(model, train, k)
    print(f"   threshold {t:.3f} (calibrated on held-out training classes, "
          f"balanced accuracy {cal_score:.3f} there)")
    enrolled_sims = np.concatenate([(M @ rest[n].T).max(0) for n in names])
    stranger_sims = np.concatenate(
        [(M @ embed(model, imgs).T).max(0) for imgs in strangers.values()]) \
        if strangers else np.array([])
    acc = (enrolled_sims >= t).mean()
    rej = (stranger_sims < t).mean() if len(stranger_sims) else float("nan")
    print(f"   enrolled objects accepted    {acc:.3f}")
    print(f"   unknown objects rejected     {rej:.3f}")
    print(f"   overlap: enrolled p05 {np.percentile(enrolled_sims, 5):.3f} "
          f"vs unknown p95 {np.percentile(stranger_sims, 95):.3f}")
    if np.percentile(stranger_sims, 95) > np.percentile(enrolled_sims, 5):
        print("   ⛔ the distributions overlap, so no threshold separates them "
              "cleanly.\n      Closed-set recognition works here; "
              "'is this a thing I have never\n      seen' does not. That is the "
              "honest state of this pipeline.")

    # ⛔ THE HONEST FAILURE, MEASURED — AND MEASURED PROPERLY. Enrol one object
    # under two labels, as if you owned two identical lipsticks, and ask which
    # is which. There is no information to answer with.
    #
    # ⚠️ A single split gave 0.284, which looks like the opposite of chance and
    # is not: with five samples per prototype, whichever half happens to land
    # nearer the class centroid attracts most probes. The result is arbitrary,
    # not balanced, and reporting one split would have made that look like a
    # finding. Across splits it swings, and the swing IS the finding.
    twin_src = names[0]
    z_all = rest[twin_src]
    scores = []
    for trial in range(20):
        perm = np.random.permutation(len(z_all))
        a_idx, b_idx, probe_idx = perm[:k], perm[k:2 * k], perm[2 * k:]
        pa, pb = z_all[a_idx].mean(0), z_all[b_idx].mean(0)
        pa /= np.linalg.norm(pa) + 1e-9
        pb /= np.linalg.norm(pb) + 1e-9
        pick_a = ((z_all[probe_idx] @ pa) > (z_all[probe_idx] @ pb)).mean()
        scores.append(float(pick_a))
    lo, hi = min(scores), max(scores)
    print(f"\n── two identical objects ({twin_src} enrolled twice, 20 splits)")
    print(f"   share assigned to the first copy: mean {np.mean(scores):.3f}, "
          f"range {lo:.3f}-{hi:.3f}")
    print("   No threshold and no amount of training fixes this: the two "
          "prototypes\n   describe the same object, so the assignment is "
          "arbitrary by construction.\n   The product's answer has to be "
          "\"there are two of these\", not a guess.")


if __name__ == "__main__":
    main()
