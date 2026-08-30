#!/usr/bin/env python3
"""Footprints KiCad does not ship, generated from the datasheet's own tables.

⛔ THE ONLY HONEST REASON TO DRAW A FOOTPRINT YOURSELF. Everything else this
board needs — QFN-48 6x6 0.4 mm, QFN-32 5x5 0.5 mm, TSSOP-14/16, SOT-23,
LGA-14, the FFC and JST parts — already exists in KiCad's library and is used
as-is. Drawing one by hand is where wrong boards come from, so exactly one is
drawn here: the Acconeer A121, which has no stock footprint anywhere.

⭐ AND IT IS TRANSCRIBED, NOT INVENTED. The ball map below is the pin table on
pages 8-9 of the A121 datasheet, ball by ball. The geometry — 10 x 10 grid,
0.5 mm pitch, 0.3 mm balls, 5.2 x 5.5 x 0.88 mm body — is section 9. The only
number not in the datasheet is the land diameter, and 0.25 mm NSMD is KiCad's
own convention for a 0.3 mm ball at 0.5 mm pitch rather than a figure of mine.

Usage:  python3 hardware/generate_footprints.py
"""
import os

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "footprints", "SmartBag.pretty")

# ── A121: the pin table, transcribed ─────────────────────────────────────────
# Rows A..K with I skipped, which is the JEDEC convention and the datasheet's.
A121_ROWS = "ABCDEFGHJK"
A121_PITCH = 0.5
A121_BODY = (5.2, 5.5, 0.88)
A121_BALL = 0.30
A121_PAD = 0.25

_GND = ("A3 A4 A5 A6 A7 A8 B2 B9 C1 C10 D2 D9 E1 E2 E9 F2 F9 G1 G10 H2 H9 "
        "J3 J5 J6 J8 K4 K7").split()
A121_BALLS = {b: "GND" for b in _GND}
A121_BALLS.update({
    # ⚠️ Analog0/Analog1/PLL_RF_TEST/CTRL/GPIO1..4 are all "connect to ground"
    # in the datasheet. They are named here rather than folded into GND so the
    # netlist has to say so explicitly — a pad silently renamed to GND is a pad
    # nobody ever checks again.
    "A2": "Analog0", "A9": "CTRL",
    "B1": "Analog1", "B10": "GPIO3",
    "C2": "VRX", "D1": "VRX",
    "C9": "VTX", "D10": "VTX",
    "E10": "PLL_RF_TEST",
    "F1": "GPIO1", "F10": "ENABLE",
    "H1": "GPIO2", "H10": "XOUT",
    "J1": "RESET_N", "J2": "SPI_SS", "J9": "VDIG", "J10": "XIN",
    "K2": "SPI_CLK", "K3": "SPI_MISO", "K5": "GPIO4", "K6": "SPI_MOSI",
    "K8": "INTERRUPT", "K9": "VIO",
})


def a121_position(ball):
    row = A121_ROWS.index(ball[0])
    col = int(ball[1:]) - 1
    x = (col - 4.5) * A121_PITCH
    y = (row - 4.5) * A121_PITCH
    return x, y


def a121():
    bx, by, bz = A121_BODY
    cx, cy = bx / 2 + 0.25, by / 2 + 0.25          # courtyard
    sx, sy = bx / 2, by / 2

    out = ['(footprint "Acconeer_A121_fcCSP50"',
           '\t(version 20241229)',
           '\t(generator "smartbag")',
           '\t(layer "F.Cu")',
           '\t(descr "Acconeer A121 60 GHz pulsed coherent radar, fcCSP50, '
           f'{bx}x{by}x{bz} mm, {A121_PITCH} mm pitch, {A121_BALL} mm balls, '
           'antenna in package. Transcribed from datasheet v1.8 sections 3 and 9.")',
           '\t(tags "acconeer a121 radar 60GHz fcCSP BGA AiP")',
           '\t(attr smd)',
           '\t(property "Reference" "U**" (at 0 -4.2 0) (layer "F.SilkS")'
           ' (uuid "a121-ref") (effects (font (size 1 1) (thickness 0.15))))',
           '\t(property "Value" "A121" (at 0 4.2 0) (layer "F.Fab")'
           ' (uuid "a121-val") (effects (font (size 1 1) (thickness 0.15))))']

    # courtyard
    out.append(f'\t(fp_rect (start {-cx} {-cy}) (end {cx} {cy}) '
               '(stroke (width 0.05) (type solid)) (fill none) '
               '(layer "F.CrtYd") (uuid "a121-crt"))')
    # body on Fab
    out.append(f'\t(fp_rect (start {-sx} {-sy}) (end {sx} {sy}) '
               '(stroke (width 0.1) (type solid)) (fill none) '
               '(layer "F.Fab") (uuid "a121-fab"))')
    # ⭐ Pin-1 marker on BOTH silk and fab. A 50-ball CSP has no visible key and
    # is symmetric to within 0.3 mm; placed 90 degrees out it will reflow, pass
    # continuity, and never work.
    out.append(f'\t(fp_circle (center {-sx - 0.4} {-sy - 0.4}) '
               f'(end {-sx - 0.25} {-sy - 0.4}) (stroke (width 0.15) '
               '(type solid)) (fill solid) (layer "F.SilkS") (uuid "a121-p1s"))')
    out.append(f'\t(fp_poly (pts (xy {-sx} {-sy}) (xy {-sx + 0.7} {-sy}) '
               f'(xy {-sx} {-sy + 0.7})) (stroke (width 0.1) (type solid)) '
               '(fill solid) (layer "F.Fab") (uuid "a121-p1f"))')
    # silkscreen outline, kept clear of the pads
    for a, b in (((-sx, -sy), (-sx, sy)), ((sx, -sy), (sx, sy))):
        out.append(f'\t(fp_line (start {a[0]} {a[1]}) (end {b[0]} {b[1]}) '
                   '(stroke (width 0.12) (type solid)) (layer "F.SilkS") '
                   f'(uuid "a121-s{a[0]}"))')

    for i, (ball, name) in enumerate(sorted(A121_BALLS.items())):
        x, y = a121_position(ball)
        out.append(f'\t(pad "{ball}" smd circle (at {x:.3f} {y:.3f}) '
                   f'(size {A121_PAD} {A121_PAD}) '
                   '(layers "F.Cu" "F.Paste" "F.Mask") '
                   f'(uuid "a121-p{i}"))')
    out.append(f'\t(model "" (offset (xyz 0 0 0)) (scale (xyz 1 1 1)) '
               '(rotate (xyz 0 0 0)))')
    out.append(')')
    return "\n".join(out) + "\n"


def main():
    os.makedirs(OUT, exist_ok=True)
    path = os.path.join(OUT, "Acconeer_A121_fcCSP50.kicad_mod")
    with open(path, "w") as f:
        f.write(a121())
    gnd = sum(1 for v in A121_BALLS.values() if v == "GND")
    print(f"OK  {path}")
    print(f"    {len(A121_BALLS)} balls ({gnd} ground, "
          f"{len(A121_BALLS) - gnd} signal), {A121_PITCH} mm pitch")


if __name__ == "__main__":
    main()
