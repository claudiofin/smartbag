#!/usr/bin/env python3
"""Generate smartbag_core.kicad_pcb: the rigid-flex board that lives in the collar.

⛔ WHAT THIS IS AND ISN'T. This is a **layout mockup**, not a manufacturable
design: the pads are real, the footprints come from the stock KiCad libraries
(so the 3D models resolve and the renders show the actual parts), but the
routing is representative and there is no netlist behind it. It does one job:
show the shape of the board and where the pieces sit.

⭐ WHY IT IS GENERATED rather than drawn by hand in pcbnew: the geometry (rigid
islands, flex tails, 60 GHz patch arrays) is parametric. Change the width of the
insert and the whole outline changes; redrawing that by hand every time is not
reproducible.

Usage:  python3 hardware/generate_pcb.py
"""
import os
import re
import uuid as _uuid

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "smartbag_core.kicad_pcb")


def _footprint_library():
    """Locate KiCad's stock footprint library.

    ⚠️ This used to be one hardcoded macOS path, which made the repo
    unrunnable anywhere else — a poor thing to publish. `KICAD_FOOTPRINT_DIR`
    wins if set; otherwise the usual install locations are tried in order.
    """
    env = os.environ.get("KICAD_FOOTPRINT_DIR")
    candidates = [env] if env else []
    candidates += [
        "/Applications/KiCad/KiCad.app/Contents/SharedSupport/footprints",  # macOS
        "/usr/share/kicad/footprints",                                      # Linux
        "/usr/local/share/kicad/footprints",
        r"C:\Program Files\KiCad\9.0\share\kicad\footprints",          # Windows
    ]
    for c in candidates:
        if c and os.path.isdir(c):
            return c
    raise SystemExit(
        "KiCad footprint library not found. Set KICAD_FOOTPRINT_DIR to the "
        "directory containing the .pretty folders.")


FP_LIB = _footprint_library()

# Board centre on an A3 sheet. The board is 196 mm wide: on A4 the outline would
# run off the paper and pcbnew flags that the moment you open the file.
CX, CY = 210.0, 148.0


def uid():
    return str(_uuid.uuid4())


# ─── Outline (Edge.Cuts) ──────────────────────────────────────────────────────
# ⛔ REDRAWN AFTER THE FIRST 3D RENDER. The first version was a 126x51 mm cross
# with the FSR matrix tail dropping out of the middle. Dropping it into the
# model of the insert showed that it **fits nowhere**: the collar wall is 4 mm
# thick, and a board 51 mm deep either spans the mouth (floating in mid-air) or
# pokes out of the bag. The render wasn't there to make a pretty picture; it was
# there to reject a layout.
#
# ⭐ The right shape is a STRIP: a 96x20 mm central island plus two flex tails
# carrying the radar arrays out to the front corners. It drops into a 20 mm
# front band, and the two antennas end up at the extremes — which is exactly
# where they need to be to light the volume from two separate points instead of
# one.
#
# The FSR matrix no longer has a tail on the board: it gets an FFC connector
# (J4) and a separate flat cable, which is also how it would really be
# assembled (the cable pulls out).
OUTLINE = [
    (-98, -10), (-78, -10), (-78, -4), (-48, -4), (-48, -10),
    (48, -10), (48, -4), (78, -4), (78, -10), (98, -10),
    (98, 10), (78, 10), (78, 4), (48, 4), (48, 10),
    (-48, 10), (-48, 4), (-78, 4), (-78, 10), (-98, 10),
]

# ─── Placed BOM ───────────────────────────────────────────────────────────────
# (ref, value, library, footprint, x, y)  — x,y local to the board centre.
COMPONENTS = [
    # Compute and sensors on the central rigid island (96 x 20 mm)
    ("U1", "SoC+NPU BLE 5.4", "Package_DFN_QFN",
     "QFN-48-1EP_6x6mm_P0.4mm_EP4.6x4.6mm", -30.0, 0.0),
    ("U2", "mmWave 60GHz TRX", "Package_DFN_QFN",
     "QFN-40-1EP_5x5mm_P0.4mm_EP3.8x3.8mm", -8.0, -1.0),
    ("U3", "PMIC buck-boost", "Package_DFN_QFN",
     "QFN-24-1EP_4x4mm_P0.5mm_EP2.8x2.8mm", 12.5, 5.0),
    ("U4", "6-axis IMU", "Package_LGA", "Bosch_LGA-14_3x2.5mm_P0.5mm", 12.0, -5.5),
    ("U5", "Hall, zip", "Package_TO_SOT_SMD", "SOT-23", -43.5, 6.0),
    ("Y1", "32 MHz", "Crystal", "Crystal_SMD_3225-4Pin_3.2x2.5mm", -42.0, -6.0),
    ("J1", "FFC IR camera + ToF", "Connector_FFC-FPC",
     "Hirose_FH12-10S-0.5SH_1x10-1MP_P0.50mm_Horizontal", -20.0, -7.0),
    ("J4", "FSR matrix 16x6 (96 taxels)", "Connector_FFC-FPC",
     "Hirose_FH12-24S-0.5SH_1x24-1MP_P0.50mm_Horizontal", 32.0, -6.6),
    ("J2", "LiPo 3.7V 2000mAh", "Connector_JST",
     "JST_SH_SM02B-SRSS-TB_1x02-1MP_P1.00mm_Horizontal", 42.0, 6.4),
    ("J3", "Qi RX coil", "Connector_JST",
     "JST_SH_SM02B-SRSS-TB_1x02-1MP_P1.00mm_Horizontal", 28.0, 6.4),
]

# Passives: rails for U1/U2/U3 plus the matching network. Positions chosen to
# stay inside the island and not end up underneath a package.
PASSIVES = [
    ("C1", "100n", -24.5, -6.0), ("C2", "100n", -22.5, -6.0),
    ("C3", "4u7", -24.5, 6.0), ("C4", "1u", -22.5, 6.0),
    ("C5", "100n", -14.0, -7.0), ("C6", "10u", -14.0, 5.0),
    ("C7", "22u", 19.0, 7.5), ("C8", "22u", 21.5, 7.5),
    ("R1", "10k", -36.5, 2.5), ("R2", "10k", -36.5, 0.5),
    ("R3", "0R", 1.0, 2.0), ("R4", "100k", 1.0, 4.0),
]
INDUCTORS = [("L1", "2u2", 5.5, 6.5), ("L2", "1u0", 8.0, 6.5)]


def read_footprint(lib, name, ref, value, x, y):
    """Inline a .kicad_mod into the board file, the way pcbnew does on place.

    ⚠️ .kicad_mod files carry `(version ...)` and `(generator ...)` lines that do
    NOT belong in a board file: leave them in and KiCad still opens the board
    but rejects them on the first save. They get stripped here rather than
    tolerated.
    """
    path = os.path.join(FP_LIB, f"{lib}.pretty", f"{name}.kicad_mod")
    if not os.path.exists(path):
        raise SystemExit(f"missing footprint: {path}")
    with open(path) as f:
        t = f.read()
    t = t.replace(f'(footprint "{name}"', f'(footprint "{lib}:{name}"', 1)
    t = re.sub(r'\n\t\(version \d+\)', '', t, count=1)
    t = re.sub(r'\n\t\(generator "[^"]*"\)', '', t, count=1)
    t = re.sub(r'\n\t\(generator_version "[^"]*"\)', '', t, count=1)
    # The footprint's (at ...) goes right after the layer, plus an instance uuid.
    t = t.replace('\n\t(layer "F.Cu")',
                  f'\n\t(layer "F.Cu")\n\t(uuid "{uid()}")'
                  f'\n\t(at {CX + x:.4f} {CY + y:.4f})', 1)
    t = t.replace('(property "Reference" "REF**"', f'(property "Reference" "{ref}"', 1)
    t = re.sub(r'\(property "Value" "[^"]*"', f'(property "Value" "{value}"', t, count=1)
    return t.rstrip()


def line(x1, y1, x2, y2, layer, width):
    return (f'\t(gr_line (start {CX+x1:.4f} {CY+y1:.4f})'
            f' (end {CX+x2:.4f} {CY+y2:.4f})'
            f' (stroke (width {width}) (type solid)) (layer "{layer}")'
            f' (uuid "{uid()}"))')


def text(s, x, y, layer, size=1.2, thickness=0.2):
    # ⚠️ Text on the back copper side has to be written mirrored, otherwise the
    # silkscreen only reads correctly when you hold the board up to the light.
    justify = "left mirror" if layer.startswith("B.") else "left"
    return (f'\t(gr_text "{s}" (at {CX+x:.4f} {CY+y:.4f} 0) (layer "{layer}")'
            f' (uuid "{uid()}") (effects (font (size {size} {size})'
            f' (thickness {thickness})) (justify {justify})))')


def track(points, width, layer="F.Cu", net=0):
    """Copper polyline. `points` are local coordinates, already ordered."""
    out = []
    for (x1, y1), (x2, y2) in zip(points, points[1:]):
        out.append(f'\t(segment (start {CX+x1:.4f} {CY+y1:.4f})'
                   f' (end {CX+x2:.4f} {CY+y2:.4f}) (width {width})'
                   f' (layer "{layer}") (net {net}) (uuid "{uid()}"))')
    return out


def via(x, y, net=1):
    return (f'\t(via (at {CX+x:.4f} {CY+y:.4f}) (size 0.45) (drill 0.2)'
            f' (layers "F.Cu" "B.Cu") (net {net}) (uuid "{uid()}"))')


def bundle(n, start, end, pitch_start, pitch_end, waypoints):
    """n parallel traces leaving `start` side by side and arriving at `end` side
    by side, routed through the intermediate waypoints.

    ⭐ Worth having because the buses (10 camera lines, 12 for the FSR matrix)
    are what visually fills the board, and drawing them one by one by hand means
    getting the pitch wrong. Here the pitch is a parameter, not a series of
    copied numbers.
    """
    out = []
    for k in range(n):
        a = (start[0] + k * pitch_start[0], start[1] + k * pitch_start[1])
        b = (end[0] + k * pitch_end[0], end[1] + k * pitch_end[1])
        mid = [(qx + k * dx, qy + k * dy) for qx, qy, dx, dy in waypoints]
        out += track([a] + mid + [b], 0.12)
    return out


def copper_rect(x, y, w, h, layer, net=0):
    """Antenna patch: a filled polygon on copper, not a zone.

    ⭐ It has to be a `gr_poly` and not a copper zone because a zone gets filled
    and carved by clearance rules, and at 60 GHz the geometry of the patch **is
    the component**: it cannot depend on how the fill turned out.
    """
    p = [(x, y), (x + w, y), (x + w, y + h), (x, y + h)]
    pts = " ".join(f"(xy {CX+a:.4f} {CY+b:.4f})" for a, b in p)
    return (f'\t(gr_poly (pts {pts}) (stroke (width 0) (type solid))'
            f' (fill solid) (layer "{layer}") (uuid "{uid()}"))')


def ground_zone(layer, name):
    pts = " ".join(f"(xy {CX+x:.4f} {CY+y:.4f})" for x, y in OUTLINE)
    return f'''	(zone
		(net 1)
		(net_name "GND")
		(layers "{layer}")
		(uuid "{uid()}")
		(name "{name}")
		(hatch edge 0.5)
		(connect_pads (clearance 0.2))
		(min_thickness 0.2)
		(filled_areas_thickness no)
		(fill (thermal_gap 0.3) (thermal_bridge_width 0.4))
		(polygon (pts {pts}))
	)'''


def patch_array(cx0, label):
    """2x4 array of 60 GHz patches. Patch side 1.2 mm ~ lambda/2 in the substrate
    (lambda0 = 5 mm at 60 GHz, eps_r ~ 3.0 on a low-loss flex laminate); pitch
    2.5 mm = lambda0/2 so the array has no grating lobes."""
    out = []
    for i in range(4):
        for j in range(2):
            out.append(copper_rect(cx0 + i * 2.5, -3.0 + j * 2.5, 1.2, 1.2, "F.Cu"))
            # ⛔ A MASK OPENING, not a cosmetic flourish. Solder mask is a lossy
            # dielectric: over a 60 GHz patch it shifts the resonant frequency
            # and eats gain. On mmWave antennas the copper is left bare (and
            # ENIG finished), which is why it shows up gold in the renders.
            out.append(copper_rect(cx0 + i * 2.5 - 0.1, -3.1 + j * 2.5, 1.4, 1.4,
                                   "F.Mask"))
            # patch feed line, back towards the middle of the island
            out.append(line(cx0 + i * 2.5 + 0.6,
                            -3.0 + j * 2.5 + (1.2 if j == 0 else 0),
                            cx0 + i * 2.5 + 0.6, -0.9 + j * 0.6, "F.Cu", 0.12))
    out.append(text(label, cx0 - 2.0, 7.0, "F.SilkS", 1.1, 0.18))
    # Ground frame around the array: it is the patch's reference plane, and
    # without it the antenna has no defined impedance.
    for (a, b, c, d) in [(-2.5, -6.2, 14.0, 0.4), (-2.5, 3.2, 14.0, 0.4)]:
        out.append(copper_rect(cx0 + a, b, c, d, "F.Cu"))
    return out


def build():
    r = ['(kicad_pcb', '\t(version 20260206)', '\t(generator "smartbag")',
         '\t(generator_version "10.0")',
         '\t(general (thickness 0.6) (legacy_teardrops no))',
         '\t(paper "A3")', '\t(layers',
         '\t\t(0 "F.Cu" signal)', '\t\t(2 "B.Cu" signal)',
         '\t\t(9 "F.Adhes" user "F.Adhesive")', '\t\t(11 "B.Adhes" user "B.Adhesive")',
         '\t\t(13 "F.Paste" user)', '\t\t(15 "B.Paste" user)',
         '\t\t(5 "F.SilkS" user "F.Silkscreen")', '\t\t(7 "B.SilkS" user "B.Silkscreen")',
         '\t\t(1 "F.Mask" user)', '\t\t(3 "B.Mask" user)',
         '\t\t(17 "Dwgs.User" user "User.Drawings")',
         '\t\t(19 "Cmts.User" user "User.Comments")',
         '\t\t(21 "Eco1.User" user "User.Eco1")',
         '\t\t(23 "Eco2.User" user "User.Eco2")',
         '\t\t(25 "Edge.Cuts" user)', '\t\t(27 "Margin" user)',
         '\t\t(31 "F.CrtYd" user "F.Courtyard")', '\t\t(29 "B.CrtYd" user "B.Courtyard")',
         '\t\t(35 "F.Fab" user)', '\t\t(33 "B.Fab" user)',
         '\t)',
         '\t(setup (pad_to_mask_clearance 0))',
         '\t(net 0 "")', '\t(net 1 "GND")', '\t(net 2 "VBAT")', '\t(net 3 "VDD_1V8")']

    # outline
    for i in range(len(OUTLINE)):
        x1, y1 = OUTLINE[i]
        x2, y2 = OUTLINE[(i + 1) % len(OUTLINE)]
        r.append(line(x1, y1, x2, y2, "Edge.Cuts", 0.1))

    # ground pours on both layers
    r.append(ground_zone("F.Cu", "GND_top"))
    r.append(ground_zone("B.Cu", "GND_bottom"))

    # radar arrays on the end islands
    r += patch_array(-93.5, "A1 60GHz")
    r += patch_array(81.5, "A2 60GHz")

    # components
    for ref, val, lib, fp, x, y in COMPONENTS:
        r.append(read_footprint(lib, fp, ref, val, x, y))
    for ref, val, x, y in PASSIVES:
        lib = "Capacitor_SMD" if ref.startswith("C") else "Resistor_SMD"
        fp = "C_0402_1005Metric" if ref.startswith("C") else "R_0402_1005Metric"
        r.append(read_footprint(lib, fp, ref, val, x, y))
    for ref, val, x, y in INDUCTORS:
        r.append(read_footprint("Inductor_SMD", "L_0603_1608Metric", ref, val, x, y))

    # ── Representative routing ───────────────────────────────────────────
    # Data bus U1 -> U2 (radar control and IF)
    r += bundle(8, (-26.6, -2.8), (-10.6, -3.4), (0, 0.5), (0, 0.45),
                [(-20.0, -2.8, 0, 0.5), (-14.0, -3.4, 0, 0.45)])
    # IR camera bus: J1 -> U1
    r += bundle(10, (-22.2, -5.6), (-27.0, -3.6), (0.5, 0), (0.35, 0),
                [(-22.2, -4.6, 0.5, 0), (-27.0, -4.2, 0.35, 0)])
    # FSR matrix bus: J4 -> U1, the full length of the strip
    r += bundle(12, (26.2, -5.2), (-27.2, 1.0), (0.5, 0), (0.4, 0),
                [(26.2, -2.0, 0.5, 0), (16.0, -2.0, 0.4, 0),
                 (-20.0, 1.0, 0.4, 0)])
    # Power: battery and Qi coil into the PMIC, then 1.8 V across to U1
    r += track([(40.5, 5.4), (34.0, 5.4), (34.0, 2.0), (15.0, 2.0)], 0.5)
    r += track([(26.5, 5.4), (24.0, 5.4), (24.0, 3.0), (15.2, 3.0)], 0.5)
    r += track([(10.2, 4.0), (4.0, 4.0), (4.0, 8.0), (-26.0, 8.0),
                (-26.8, 3.2)], 0.4)
    # Microstrip feeds out to the antennas, one per tail.
    r += track([(-5.6, -1.0), (-52.0, -1.0), (-52.0, 0.0), (-82.0, 0.0)], 0.14)
    r += track([(-5.6, 1.0), (52.0, 1.0), (52.0, 0.0), (82.0, 0.0)], 0.14)

    # Ground stitching along the tails: sews the two planes at the flex edges.
    # ⚠️ On flex, vias are the fatigue weak point: they sit on the centreline of
    # the tail, never at the edge where the bend concentrates strain.
    for x in range(-76, -48, 2):
        r += [via(x, -2.6), via(x, 2.6)]
    for x in range(50, 78, 2):
        r += [via(x, -2.6), via(x, 2.6)]

    # ── Silkscreen ───────────────────────────────────────────────────────
    # The front only has room for short labels; the title block goes on the
    # back, where there are no components.
    r.append(text("FSR", 25.0, 8.6, "F.SilkS", 0.9, 0.14))
    r.append(text("flex", -70.0, -1.2, "F.SilkS", 0.9, 0.14))
    r.append(text("flex", 60.0, -1.2, "F.SilkS", 0.9, 0.14))

    r.append(text("SMARTBAG CORE  v0.2", -20.0, -5.5, "B.SilkS", 2.2, 0.36))
    r.append(text("tagless inventory - 2L rigid-flex", -20.0, -2.2, "B.SilkS", 1.2, 0.2))
    for i, s_ in enumerate([
        "U1 SoC+NPU   U2 60 GHz radar   U3 PMIC",
        "U4 6-axis IMU   U5 zip Hall   Y1 32 MHz",
        "A1/A2 2x4 patch array, lambda0/2 pitch",
    ]):
        r.append(text(s_, -20.0, 1.2 + i * 2.2, "B.SilkS", 1.0, 0.16))

    # Design notes: comments layer, these never go to fabrication.
    for i, s_ in enumerate([
        "rigid FR4 islands 0.6 mm on 2L polyimide flex",
        "8 mm flex tails: min bend radius 12 mm (10x thickness)",
        "J4: 16 cols + 6 rows = 22 lines on a 24-way FFC",
    ]):
        r.append(text(s_, -98.0, 16.0 + i * 2.4, "Cmts.User", 1.1, 0.18))

    r.append(')')
    return "\n".join(r) + "\n"


if __name__ == "__main__":
    with open(OUT, "w") as f:
        f.write(build())
    n = len(COMPONENTS) + len(PASSIVES) + len(INDUCTORS)
    print(f"OK  {OUT}  ({n} components, {len(OUTLINE)}-vertex outline)")
