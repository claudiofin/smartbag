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
import sys
import uuid as _uuid

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import netlist as nl          # noqa: E402
import route as rt            # noqa: E402
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

# ⭐ THE BOM AND THE PLACEMENT NOW LIVE IN netlist.py, next to the pins and the
# nets they belong to. Keeping the coordinates here and the connectivity there
# was how the board and the schematic were free to disagree.


def _inject_nets(text, pad_nets, net_index):
    """Put `(net N "NAME")` inside every pad that the netlist names.

    ⛔ A BALANCED-PAREN SCAN, not a regex. A pad is a multi-line s-expression
    that itself contains parenthesised sub-forms — `(at ...)`, `(size ...)`,
    sometimes `(primitives ...)`. Matching `\(pad .*?\)` non-greedily closes on
    the first inner form and produces a file KiCad refuses to open; matching
    greedily swallows the rest of the footprint. Counting depth is the only way
    that survives a footprint you did not write.
    """
    out, i = [], 0
    while True:
        j = text.find('(pad "', i)
        if j < 0:
            out.append(text[i:])
            break
        number = text[j + 6:text.index('"', j + 6)]
        depth, k = 0, j
        while True:
            if text[k] == "(":
                depth += 1
            elif text[k] == ")":
                depth -= 1
                if depth == 0:
                    break
            k += 1
        net = pad_nets.get(number)
        out.append(text[i:k])
        if net is not None:
            out.append(f'\n\t\t(net {net_index[net]} "{net}")')
        out.append(")")
        i = k + 1
    return "".join(out)


def read_footprint(lib, name, ref, value, x, y, pad_nets=None, net_index=None):
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
    # ⚠️ Reference silk hidden on every part. On a board 20 mm tall the default
    # 1 mm designators of 26 footprints land on each other, on neighbouring pads
    # and over the board edge — silkscreen, not copper, was the source of every
    # remaining DRC warning. The designators are not lost: KiCad footprints also
    # carry them on F.Fab, which is the layer assembly actually reads.
    if True:
        t = re.sub(r'(\(property "Reference" "' + ref + r'"\s*\n\s*\(at [^\n]*\n\s*\(layer "[^"]*"\))',
                   r'\1\n\t\t(hide yes)', t, count=1)
    t = re.sub(r'\(property "Value" "[^"]*"', f'(property "Value" "{value}"', t, count=1)
    if pad_nets:
        t = _inject_nets(t, pad_nets, net_index)
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
    out.append(text(label, cx0 - 2.0, 7.4, "F.SilkS", 0.9, 0.14))
    # Ground frame around the array: it is the patch's reference plane, and
    # without it the antenna has no defined impedance.
    for (a, b, c, d) in [(-2.5, -6.2, 14.0, 0.4), (-2.5, 3.2, 14.0, 0.4)]:
        out.append(copper_rect(cx0 + a, b, c, d, "F.Cu"))
    return out


# ⚠️ Net 0 is KiCad's "no net" and must stay empty. GND is pinned to 1 so the
# ground zones, which are written before the components, can name it.
NET_INDEX = {"": 0, "GND": 1}
for _n in sorted(nl.nets()):
    NET_INDEX.setdefault(_n, len(NET_INDEX))


def _keepouts(margin=0.6):
    """Courtyard of every placed part, in board coordinates, plus a margin.

    ⚠️ The first stitching pass dropped vias on a fixed grid and put seven of
    them inside footprints: 7 hole-clearance violations, 7 mask bridges and 4
    shorts. A via grid has to know where the parts are.
    """
    boxes = []
    for _ref, _v, _s, lib, fp, _pins, x, y in nl.PARTS:
        path = os.path.join(FP_LIB, f"{lib}.pretty", f"{fp}.kicad_mod")
        t = open(path).read()
        pts = [(float(a), float(b))
               for m in re.finditer(
                   r'\(fp_(?:line|rect|poly)\b(.*?)\(layer "F\.CrtYd"', t, re.S)
               for a, b in re.findall(
                   r'\((?:start|end|xy) ([-\d.]+) ([-\d.]+)\)', m.group(1))]
        if not pts:
            pts = [(float(m.group(1)), float(m.group(2)))
                   for m in re.finditer(
                       r'\(pad "[^"]*"[^\n]*\n\s*\(at ([-\d.]+) ([-\d.]+)', t)]
        xs = [q[0] for q in pts] or [0]
        ys = [q[1] for q in pts] or [0]
        boxes.append((x + min(xs) - margin, x + max(xs) + margin,
                      y + min(ys) - margin, y + max(ys) + margin))
    return boxes


def _clear(x, y, boxes):
    return not any(a <= x <= b and c <= y <= d for a, b, c, d in boxes)


def _segment(a, b, width, layer, net):
    return (f'\t(segment (start {CX+a[0]:.4f} {CY+a[1]:.4f})'
            f' (end {CX+b[0]:.4f} {CY+b[1]:.4f}) (width {width})'
            f' (layer "{layer}") (net {net}) (uuid "{uid()}"))')


def _via_at(x, y, net):
    return via(x, y, net)


def route(net_index):
    """Ground stitching plus the signal routing from route.py."""
    out = []
    gnd = net_index["GND"]
    boxes = _keepouts()
    for x in range(-46, 48, 4):
        for y in (-9.3, 9.3):
            if _clear(x, y, boxes):
                out.append(via(x, y, gnd))
    for x in range(-76, -48, 3):
        out += [via(x, -2.6, gnd), via(x, 2.6, gnd)]
    for x in range(51, 79, 3):
        out += [via(x, -2.6, gnd), via(x, 2.6, gnd)]
    for x in range(-94, -78, 4):
        out += [via(x, -7.6, gnd), via(x, 7.6, gnd)]
    for x in range(82, 98, 4):
        out += [via(x, -7.6, gnd), via(x, 7.6, gnd)]

    out += rt.route(nl.PARTS, FP_LIB, net_index, _segment, _via_at,
                    lambda x, y: _clear(x, y, boxes))
    return out


def build():
    r = ['(kicad_pcb', '\t(version 20260206)', '\t(generator "smartbag")',
         '\t(generator_version "10.0")',
         '\t(general (thickness 0.6) (legacy_teardrops no))',
         '\t(paper "A3")', '\t(layers',
         '\t\t(0 "F.Cu" signal)', '\t\t(4 "In1.Cu" signal)',
         '\t\t(6 "In2.Cu" signal)', '\t\t(2 "B.Cu" signal)',
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
         ] + [f'\t(net {i} "{n}")' for n, i in sorted(NET_INDEX.items(),
                                                      key=lambda kv: kv[1])]

    # outline
    for i in range(len(OUTLINE)):
        x1, y1 = OUTLINE[i]
        x2, y2 = OUTLINE[(i + 1) % len(OUTLINE)]
        r.append(line(x1, y1, x2, y2, "Edge.Cuts", 0.1))

    # ⛔ FOUR LAYERS, AND TWO INDEPENDENT REASONS FOR IT.
    #
    # 1. Routing. Two layers could not carry this. Everything connected, but
    #    DRC came back with 116 crossings and 165 clearance violations: with one
    #    signal layer the horizontal lanes and the vertical drops share it and
    #    must cross. Four layers give one axis each — verticals on B.Cu,
    #    horizontals on In2.Cu — and crossings become impossible by
    #    construction rather than by luck.
    #
    # 2. RF. The patch needs its reference plane 0.25 mm below it (see rf/).
    #    On a two-layer board that plane is the bottom of a 0.6 mm stack, which
    #    is the geometry the simulation rejected. In1.Cu, poured solid, IS that
    #    reference plane, and the antenna islands keep it 0.25 mm away.
    #
    # ⚠️ In1.Cu is poured and never routed on. A signal crossing the reference
    # plane under a 60 GHz microstrip would undo the thing it is there for.
    r.append(ground_zone("F.Cu", "GND_top"))
    r.append(ground_zone("In1.Cu", "GND_reference"))
    r.append(ground_zone("B.Cu", "GND_bottom"))

    # radar arrays on the end islands
    r += patch_array(-93.5, "A1 60GHz")
    r += patch_array(81.5, "A2 60GHz")

    # components, placed and netted from netlist.py
    for ref, val, _sym, lib, fp, pins, x, y in nl.PARTS:
        r.append(read_footprint(lib, fp, ref, val, x, y,
                                {str(num): net for num, _n, _t, net in pins},
                                NET_INDEX))

    # ── Routing ──────────────────────────────────────────────────────────
    # ⛔ THE DECORATIVE ROUTING IS GONE. Before there was a netlist, this block
    # drew bundles of tracks on net 0 to make the renders look like a circuit.
    # The moment the pads carried real nets, DRC read those tracks for what they
    # were: 40 shorts, 6 clearance violations and 168 solder-mask bridges — one
    # object producing more than half the errors on the board. Tracks that are
    # not connectivity have no business in a board file.
    r += route(NET_INDEX)

    # ── Silkscreen ───────────────────────────────────────────────────────
    # The front only has room for short labels; the title block goes on the
    # back, where there are no components.
    r.append(text("FSR", 24.0, -9.2, "F.SilkS", 0.8, 0.12))
    r.append(text("flex", -70.0, -1.4, "F.SilkS", 0.8, 0.12))
    r.append(text("flex", 60.0, -1.4, "F.SilkS", 0.8, 0.12))

    r.append(text("SMARTBAG CORE  v0.2", 22.0, -6.0, "B.SilkS", 1.6, 0.24))
    r.append(text("tagless inventory - 2L rigid-flex", 22.0, -3.4, "B.SilkS", 1.0, 0.16))
    for i, s_ in enumerate([
        "U1 SoC+NPU   U2 60 GHz radar   U3 PMIC",
        "U4 6-axis IMU   U5 zip Hall   Y1 32 MHz",
        "A1/A2 2x4 patch array, lambda0/2 pitch",
    ]):
        r.append(text(s_, 22.0, -0.6 + i * 1.9, "B.SilkS", 0.9, 0.14))

    # Design notes: comments layer, these never go to fabrication.
    for i, s_ in enumerate([
        "rigid FR4 islands 0.6 mm on 2L polyimide flex",
        "8 mm flex tails: min bend radius 12 mm (10x thickness)",
        "J4: 16 cols + 6 rows = 22 lines on a 24-way FFC",
        "A1/A2 islands: 0.25 mm dielectric under the patches, NOT 0.6",
        "  full-wave sim: 0.25 mm -> -27 dB at 59.9 GHz; 0.6 mm -> -2.5 dB",
    ]):
        r.append(text(s_, -98.0, 16.0 + i * 2.4, "Cmts.User", 1.1, 0.18))

    r.append(')')
    return "\n".join(r) + "\n"


if __name__ == "__main__":
    with open(OUT, "w") as f:
        f.write(build())
    print(f"OK  {OUT}  ({len(nl.PARTS)} components, {len(NET_INDEX) - 1} nets, "
          f"{len(OUTLINE)}-vertex outline)")
