#!/usr/bin/env python3
"""Does the recognition model fit on the processor the parts search left us with?

⛔ THE QUESTION THIS ANSWERS WAS OPENED BY THE BILL OF MATERIALS. The board was
drawn around an invented SoC with an NPU; no real BLE SoC in a QFN has one, so
the processor is an nRF54L15 — a 128 MHz Cortex-M33 — and the whole recognition
pipeline has to run on it. "It probably fits in the settle window" was the claim
made when that part was chosen. This is the arithmetic.

⭐ COUNTED, NOT ESTIMATED. The multiply-accumulates come from the model in
classify.py by running a tensor through it with hooks on every layer, so the
number cannot drift away from the network that was actually measured. The camera
transfer comes from the SPI clock the chosen module actually supports, and the
deadlines come from firmware/smartbag.h. Four files, one budget, no retyping.

⚠️ The MACs-per-cycle figure is the one thing here that is a judgement. A
Cortex-M33 with the DSP extension does two 16-bit MACs per cycle in a single
SMLAD; int8 kernels in CMSIS-NN reach somewhere between one and two effective
MACs per cycle once unpacking and address arithmetic are paid for. Both bounds
are reported, because a budget that quotes only the optimistic one is not a
budget.

Usage:  python3 ml/inference_budget.py
"""
import os
import re
import sys

import torch

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from classify import Embedder          # noqa: E402

CPU_MHZ = 128.0
MAC_PER_CYCLE = (1.0, 2.0)             # pessimistic, optimistic
INPUT = 96                             # classify.py trains on 96x96 grey

# ── the camera, from hardware/bom.py's chosen part ───────────────────────────
CAM_SPI_MHZ = 8.0                      # Arducam Mega maximum, and it is a wall
CAM_MODES = [
    ("96x96 grey", 96 * 96 * 1),
    ("160x120 RGB565", 160 * 120 * 2),
    ("320x240 RGB565", 320 * 240 * 2),
]


def firmware_timing():
    """Deadlines read out of the firmware rather than remembered."""
    h = open(os.path.join(os.path.dirname(HERE), "firmware", "smartbag.h")).read()
    c = open(os.path.join(os.path.dirname(HERE), "firmware", "smartbag.c")).read()
    frames = int(re.search(r"#define SB_CAPTURE_FRAMES (\d+)", h).group(1))
    out = {"frames": frames}
    for key in ("capture_timeout_ms", "settle_ms"):
        m = re.search(r"\." + key + r"\s*=\s*(\d+)", c)
        out[key] = int(m.group(1)) if m else None
    return out


def count_macs(model, size):
    """Multiply-accumulates for one forward pass, by hooking every layer."""
    total = {"macs": 0, "params": 0, "peak_act": 0}
    hooks = []

    def hook(mod, inp, out):
        if isinstance(mod, torch.nn.Conv2d):
            oh, ow = out.shape[2], out.shape[3]
            k = mod.kernel_size[0] * mod.kernel_size[1]
            total["macs"] += oh * ow * mod.out_channels * k * mod.in_channels
        elif isinstance(mod, torch.nn.Linear):
            total["macs"] += mod.in_features * mod.out_features
        total["peak_act"] = max(total["peak_act"], out.numel())

    for m in model.modules():
        if isinstance(m, (torch.nn.Conv2d, torch.nn.Linear)):
            hooks.append(m.register_forward_hook(hook))
    with torch.no_grad():
        model(torch.zeros(1, 1, size, size))
    for h in hooks:
        h.remove()
    total["params"] = sum(p.numel() for p in model.parameters())
    return total


def main():
    fw = firmware_timing()
    model = Embedder(n_classes=5).eval()
    t = count_macs(model, INPUT)

    print("Recognition on a Cortex-M33, because there is no NPU\n")
    print(f"── the model, counted from classify.py at {INPUT}x{INPUT} grey")
    print(f"   {t['macs'] / 1e6:.2f} M multiply-accumulates per frame")
    print(f"   {t['params'] / 1e3:.1f} k parameters "
          f"({t['params'] / 1024:.0f} kB as int8)")
    print(f"   largest activation {t['peak_act'] / 1024:.0f} kB as int8, "
          "so roughly")
    print(f"   {(t['params'] + 2 * t['peak_act']) / 1024:.0f} kB of the "
          "nRF54L15's 256 kB RAM")

    print(f"\n── inference on {CPU_MHZ:.0f} MHz")
    slow = t["macs"] / MAC_PER_CYCLE[0] / (CPU_MHZ * 1e6) * 1000
    fast = t["macs"] / MAC_PER_CYCLE[1] / (CPU_MHZ * 1e6) * 1000
    print(f"   {fast:.0f} ms per frame at {MAC_PER_CYCLE[1]:.0f} MAC/cycle, "
          f"{slow:.0f} ms at {MAC_PER_CYCLE[0]:.0f}")
    print(f"   x{fw['frames']} frames: {fw['frames'] * fast:.0f}..."
          f"{fw['frames'] * slow:.0f} ms")

    print(f"\n── getting the pixels out, over {CAM_SPI_MHZ:.0f} MHz SPI")
    # ⛔ 8 MHz is the camera's ceiling, not the processor's. The radars on the
    # same bus run at 50; the camera is the slow device and it sets this number.
    best = None
    for name, nbytes in CAM_MODES:
        ms = nbytes * 8 / (CAM_SPI_MHZ * 1e6) * 1000
        burst = ms * fw["frames"]
        fits = burst < fw["capture_timeout_ms"]
        print(f"   {name:<16} {nbytes / 1024:>5.0f} kB  {ms:>6.1f} ms/frame  "
              f"{burst:>6.1f} ms for {fw['frames']}  "
              f"{'fits' if fits else '⛔ over'} the "
              f"{fw['capture_timeout_ms']} ms capture timeout")
        if fits and best is None:
            best = (name, burst)

    print()
    total_fast = best[1] + fw["frames"] * fast
    total_slow = best[1] + fw["frames"] * slow
    print(f"── end to end, {best[0]}")
    print(f"   capture {best[1]:.0f} ms + inference "
          f"{fw['frames'] * fast:.0f}...{fw['frames'] * slow:.0f} ms "
          f"= {total_fast:.0f}...{total_slow:.0f} ms")
    print(f"   against a {fw['settle_ms']} ms settle window that the firmware "
          "already waits")

    if total_slow < fw["settle_ms"]:
        print()
        print("   ⭐ IT FITS, AND WITH ROOM. The claim made when the nRF54L15 was")
        print("      chosen — that inference hides inside a window the design")
        print(f"      already had — survives its own arithmetic by "
              f"{fw['settle_ms'] / total_slow:.1f}x at the pessimistic bound.")
        print("      The NPU is not missing. It was never needed at this model")
        print("      size, and the model size was chosen before the processor")
        print("      was, which is the only reason this came out well.")
    else:
        print()
        print("   ⛔ IT DOES NOT FIT. The model has to shrink or the part has to")
        print("      change.")

    print()
    print("⚠️ What this does NOT say: that the accuracy in ml/classify.py "
          "survives")
    print("   int8 quantisation, or that CMSIS-NN reaches these rates on this "
          "silicon.")
    print("   Both are measurable and neither has been measured. What is "
          "settled is")
    print("   that the arithmetic is not the obstacle.")


if __name__ == "__main__":
    main()
