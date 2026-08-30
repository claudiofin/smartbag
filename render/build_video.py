#!/usr/bin/env python3
"""Film assembly: sequence, captions, fades. Then ffmpeg encodes.

⛔ WHY THE CAPTIONS ARE DONE HERE AND NOT IN BLENDER. In the stills the callouts
are 3D geometry pulled in front of the model, and they work because the camera
is still. In motion they would have to be reoriented every frame, the leader
lines would crawl across the surface, and legibility would depend on where the
camera happens to be at that instant. Text composited in 2D is legible by
construction.

⛔ AND WHY NOT FFMPEG'S `drawtext`: the ffmpeg used here is built without
libfreetype (`drawtext` does not appear among its filters). Compositing with PIL
avoids depending on how ffmpeg happens to have been compiled on another machine.

⭐ THE CLOSING SHOT IS THE OPENING PLAYED BACKWARDS. No extra 120 frames get
rendered to close the bag again: the same move read in reverse IS the closing,
and it is also exact — the boolean retraces the same positions.

Usage:  python3 render/build_video.py [film ...] [--width 1600]
"""
import os
import subprocess
import sys

from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
ANIM = os.path.join(HERE, "anim")
MEDIA = os.path.join(os.path.dirname(HERE), "media")
FPS = 24

# ⚠️ macOS system fonts. On another OS, point these at any bold/regular pair.
FONT_BOLD = "/System/Library/Fonts/Supplemental/Arial Bold.ttf"
FONT_REGULAR = "/System/Library/Fonts/Supplemental/Arial.ttf"

# ⭐ TWO FILMS, ONE CHAIN OF FRAMES. `scanning` appears in both: rendered once,
# assembled twice. Each film's closing shot is its own first shot read backwards
# (step −1) — no frames are rendered to close what has already been seen
# opening.
#
# ⚠️ The GLOBAL frame boundaries of each assembly (needed for the captions):
# every caption must finish its fade BEFORE the cut, otherwise it bleeds onto
# the next shot and reads as an encoding glitch.
FILMS = {
    # section:  opening 1–120 · exploded 121–288 · scanning 289–432 · closing 433–552
    "section": {
        "output": "smartbag.mp4",
        # Frame range used for the inline README preview (see `preview` below).
        "preview": (1, 120),
        "sequence": [("opening", 1, 120, 1), ("exploded", 1, 168, 1),
                     ("scanning", 1, 144, 1), ("opening", 120, 1, -1)],
        "captions": [
            (6, 46, "SMARTBAG", "smart insert for a handbag · tagless inventory"),
            (64, 110, "the section opens",
             "3.5 mm leather · removable insert, 225 × 78 × 180 mm"),
            (136, 200, "five layers",
             "collar · walls · FSR floor · power plate · Qi coil"),
            (220, 278, "the board", "196 × 20 mm strip · 2-layer rigid-flex"),
            (300, 358, "96 taxels", "the contents leave their imprint on the floor"),
            (378, 422, "two 60 GHz arrays",
             "2×4 patches, λ₀/2 pitch · no tags on the objects"),
            (452, 538, "the bag stays a bag",
             "the insert slides out and moves to another one"),
        ],
    },
    # sequence:  unzip 1–120 · object_drop 121–264 · scanning 265–408 · closing 409–528
    "sequence": {
        "output": "smartbag_sequence.mp4",
        "preview": (150, 270),
        "sequence": [("unzip", 1, 120, 1), ("object_drop", 1, 144, 1),
                     ("scanning", 1, 144, 1), ("unzip", 120, 1, -1)],
        "captions": [
            (6, 50, "1 · the zip opens",
             "the Hall sensor on the closure wakes the system"),
            # ⚠️ A caption has to be true IN THE INSTANT it appears. The first
            # version said "with the bag closed nothing is powered" over a frame
            # in which the bag was already wide open.
            (74, 110, "until a moment ago: microamps",
             "with the bag shut the system sleeps, no sensor powered"),
            (140, 190, "2 · an object goes in",
             "the ToF sees it cross the mouth and wakes the camera"),
            (214, 254, "3 · the IR camera fires",
             "three frames as the object passes · invisible illuminators"),
            (284, 330, "4 · the radar maps the volume",
             "60 GHz through fabric: where the object landed"),
            (356, 400, "5 · the FSR matrix weighs it",
             "96 taxels: footprint and mass, without a single tag"),
            (430, 510, "recognition without tags",
             "all the hardware is in the insert · the bag is untouched"),
        ],
    },
}

FADE = 8           # frames of fade in/out on each caption


def load_fonts(width):
    k = width / 1600.0
    return (ImageFont.truetype(FONT_BOLD, int(42 * k)),
            ImageFont.truetype(FONT_REGULAR, int(21 * k)), k)


def frame_list(sequence):
    """Expand the sequence into the list of files, in assembly order."""
    frames = []
    for folder, a, b, step in sequence:
        for i in range(a, b + step, step):
            f = os.path.join(ANIM, folder, f"f{i:04d}.png")
            if not os.path.exists(f):
                raise SystemExit(f"missing {f} — run tools/render_animation.sh first")
            frames.append(f)
    return frames


def draw_caption(img, title, subtitle, alpha, font_t, font_s, k):
    """Title and subtitle bottom left, against a vertical rule.

    ⚠️ The text is composed on a separate RGBA layer and then blended: drawing
    it straight onto the frame gives no way to fade it, and a caption that pops
    in and out in a film reads as an encoding glitch.
    """
    if alpha <= 0:
        return img
    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    x = int(72 * k)
    y = img.size[1] - int(146 * k)
    a = int(255 * alpha)
    d.rectangle([x - int(18 * k), y + int(6 * k),
                 x - int(15 * k), y + int(74 * k)], fill=(232, 236, 244, a))
    # soft shadow: the render background is light at the bottom left
    for dx, dy in ((2, 2), (1, 1)):
        d.text((x + dx * k, y + dy * k), title, font=font_t,
               fill=(0, 0, 0, int(a * 0.35)))
    d.text((x, y), title, font=font_t, fill=(245, 247, 252, a))
    d.text((x, y + int(52 * k)), subtitle, font=font_s,
           fill=(203, 209, 222, int(a * 0.92)))
    return Image.alpha_composite(img.convert("RGBA"), layer)


def caption_alpha(i, captions):
    for a, b, title, subtitle in captions:
        if a - FADE <= i <= b + FADE:
            if i < a:
                return (i - (a - FADE)) / FADE, title, subtitle
            if i > b:
                return (b + FADE - i) / FADE, title, subtitle
            return 1.0, title, subtitle
    return 0.0, None, None


def build(name, cfg, requested_width):
    frames = frame_list(cfg["sequence"])
    work = os.path.join(ANIM, f"film_{name}")
    os.makedirs(work, exist_ok=True)
    for f in os.listdir(work):
        os.remove(os.path.join(work, f))
    width = requested_width or Image.open(frames[0]).size[0]
    font_t, font_s, k = load_fonts(width)
    n = len(frames)
    print(f"-- {name}: {n} frames · {n / FPS:.1f} s at {FPS} fps")
    for i, path in enumerate(frames, start=1):
        img = Image.open(path).convert("RGBA")
        alpha, title, subtitle = caption_alpha(i, cfg["captions"])
        if title:
            img = draw_caption(img, title, subtitle, alpha, font_t, font_s, k)
        img.convert("RGB").save(os.path.join(work, f"f{i:05d}.png"))
        if i % 120 == 0:
            print(f"   {i}/{n}")
    duration = n / FPS
    os.makedirs(MEDIA, exist_ok=True)
    out = os.path.join(MEDIA, cfg["output"])
    subprocess.run([
        "ffmpeg", "-y", "-loglevel", "error", "-framerate", str(FPS),
        "-i", os.path.join(work, "f%05d.png"),
        "-vf", f"fade=t=in:st=0:d=0.6,fade=t=out:st={duration - 0.8:.2f}:d=0.8,"
               "format=yuv420p",
        "-c:v", "libx264", "-crf", "18", "-preset", "slow",
        "-movflags", "+faststart", out], check=True)
    # ⛔ THE GIF IS A PREVIEW, NOT THE FILM. A full-length GIF of either film
    # came out at 11–14 MB: inline in a README that means every visitor
    # downloads ~25 MB just to load the page. The preview is one shot, at
    # 480 px and 9 fps, and it links to the MP4 — which stays the good copy.
    a, b = cfg["preview"]
    gif = out.replace(".mp4", "_preview.gif")
    subprocess.run([
        "ffmpeg", "-y", "-loglevel", "error", "-framerate", str(FPS),
        "-start_number", str(a), "-i", os.path.join(work, "f%05d.png"),
        "-frames:v", str(b - a + 1),
        "-vf", "fps=9,scale=480:-1:flags=lanczos,split[x][y];"
               "[x]palettegen=max_colors=80[p];[y][p]paletteuse=dither=bayer",
        gif], check=True)
    for f in (out, gif):
        print(f"DONE -> {f} ({os.path.getsize(f) / 1e6:.1f} MB)")


def main():
    a = sys.argv[1:]
    width = int(a[a.index("--width") + 1]) if "--width" in a else 0
    wanted = [x for x in a if x in FILMS] or list(FILMS)
    for name in wanted:
        build(name, FILMS[name], width)


if __name__ == "__main__":
    main()
