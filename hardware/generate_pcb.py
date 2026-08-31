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
import netlist as nl
import place          # noqa: E402
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

# ⭐ Local footprints win. The A121 has no stock footprint anywhere, so
# hardware/generate_footprints.py writes it into footprints/SmartBag.pretty and
# this resolver looks there first. Everything else still comes from KiCad's own
# library, which is the point: exactly one footprint on this board is drawn by
# hand.
LOCAL_FP = os.path.join(os.path.dirname(os.path.abspath(__file__)), "footprints")


def footprint_path(lib, name):
    local = os.path.join(LOCAL_FP, f"{lib}.pretty", f"{name}.kicad_mod")
    if os.path.exists(local):
        return local
    return os.path.join(FP_LIB, f"{lib}.pretty", f"{name}.kicad_mod")

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
# ⭐ THE FLEX TAILS ARE 14 mm WIDE, NOT 8. They started at 8 because a narrow
# tail looks like the flexible thing it is, and 8 mm turned out to be the
# bottleneck: eight nets have to cross each tail to reach a radar — three SPI
# lines, a chip select, an interrupt, an enable and two supplies — and the
# router could not fit the last two. Widening the tail costs nothing that
# matters. Bend radius is a function of THICKNESS, not width, so a wider tail
# folds exactly as tightly; it just carries more copper across the fold.
# ⚠️ THE CENTRE ISLAND IS 124 mm, UP FROM 94, AND THE ROOM CAME FROM THE ENDS.
# The Qi receiver and its resonant tank — eleven parts that were missing from
# the board entirely — did not fit otherwise. The end islands were the place to
# take it from: each held a radar, a crystal and six capacitors, about 50 mm2 of
# parts in 324 mm2 of board. They are 14 mm now instead of 20.
#
# ⚠️ The flex tails shrank from 30 mm to 22 with them. A tail folds on its
# THICKNESS, not its length; 22 mm is still four times the bend radius.
OUTLINE = [
    (-98, -10), (-84, -10), (-84, -7), (-62, -7), (-62, -10),
    (62, -10), (62, -7), (84, -7), (84, -10), (98, -10),
    (98, 10), (84, 10), (84, 7), (62, 7), (62, 10),
    (-62, 10), (-62, 7), (-84, 7), (-84, 10), (-98, 10),
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


def read_footprint(lib, name, ref, value, x, y, pad_nets=None, net_index=None,
                   angle=0):
    """Inline a .kicad_mod into the board file, the way pcbnew does on place.

    ⚠️ .kicad_mod files carry `(version ...)` and `(generator ...)` lines that do
    NOT belong in a board file: leave them in and KiCad still opens the board
    but rejects them on the first save. They get stripped here rather than
    tolerated.
    """
    path = footprint_path(lib, name)
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
                  f'\n\t(at {CX + x:.4f} {CY + y:.4f}'
                  + (f' {angle}' if angle else '') + ')', 1)
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


def via(x, y, net=1, size=0.25, drill=0.1):
    return (f'\t(via (at {CX+x:.4f} {CY+y:.4f}) (size {size}) (drill {drill})'
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


# ⛔ SOLID PAD CONNECTION, NOT THERMAL RELIEF, and DRC found out why. Thermal
# relief exists so a human with an iron can heat a pad that is tied to a plane;
# this board is 0.4 mm-pitch QFN and 0.5 mm-pitch BGA and will never be hand
# soldered. Worse, relief needs a spoke narrower than the pad, and J1's ground
# fingers are 0.3 mm FFC pads: the spokes could not be drawn at all, so those
# pads connected to nothing and DRC reported them as unrouted ground — which
# reads like a routing failure and was a fill setting.
def ground_zone(layer, name):
    pts = " ".join(f"(xy {CX+x:.4f} {CY+y:.4f})" for x, y in OUTLINE)
    return f'''	(zone
		(net 1)
		(net_name "GND")
		(layers "{layer}")
		(uuid "{uid()}")
		(name "{name}")
		(hatch edge 0.5)
		(connect_pads yes (clearance 0.2))
		(min_thickness 0.2)
		(filled_areas_thickness no)
		(fill (thermal_gap 0.3) (thermal_bridge_width 0.25))
		(polygon (pts {pts}))
	)'''


# ⛔ NO FIDUCIALS MEANT NO ASSEMBLY QUOTE. A placement machine finds the board by
# looking at fiducials, not by trusting the router rail — and this design has two
# 50-ball BGAs at 0.5 mm pitch, which is exactly the regime where nobody will
# take the job without them. The board had none for its whole life, because a
# fiducial connects to nothing and so appears in no netlist and no ERC.
#
# ⭐ THREE GLOBAL, ASYMMETRIC. Three points fix translation, rotation and scale;
# putting them in an L rather than a line is what lets the machine tell which way
# round the board is. And two LOCAL fiducials, one beside each A121, because at
# 0.5 mm pitch the machine wants a reference near the part rather than 90 mm away
# at the other end of a flex strip that has just been through a reflow oven.
FIDUCIALS = [
    (-92.0, -7.5), (92.0, -7.5), (-92.0, 7.5),        # global, in an L
    (-79.5, 6.5), (79.5, 6.5),                        # local, one per BGA
]


def antenna_keepout(x, y, w=7.0, h=2.2):
    """The copper-free window a chip antenna needs, from its own datasheet.

    ⛔ A CHIP ANTENNA WITH GROUND UNDER IT IS NOT AN ANTENNA. The Johanson
    2450AT43F0100's mounting drawing shows a 7.0 x 2.2 mm region with the ground
    plane pulled back on every layer, and the board poured ground over all of it
    — three planes, straight through the radiator — because nothing in the
    generator knew the part was special. It would have reflowed, passed every
    check this project runs, and radiated almost nothing.

    ⚠️ Not oversized either. The plane is the antenna's counterpoise: clearing
    more than the datasheet asks for detunes it in the other direction.

    ⛔ TRACKS ARE ALLOWED THROUGH IT, and the first version forbade them — which
    left the antenna's own feed line unable to reach it. What the datasheet
    clears is the GROUND PLANE under the radiator, not the 50 ohm line that
    drives it. Vias stay forbidden: a via here is a stitch back to the plane
    that was just removed.
    """
    pts = " ".join(f"(xy {CX + px:.4f} {CY + py:.4f})" for px, py in (
        (x - w / 2, y - h / 2), (x + w / 2, y - h / 2),
        (x + w / 2, y + h / 2), (x - w / 2, y + h / 2)))
    return f'''	(zone
		(net 0)
		(net_name "")
		(layers "F.Cu" "In1.Cu" "In2.Cu" "B.Cu")
		(uuid "{uid()}")
		(name "ANT_KEEPOUT")
		(hatch edge 0.5)
		(keepout (tracks allowed) (vias not_allowed) (pads allowed)
			(copperpour not_allowed) (footprints allowed))
		(placement (enabled no) (sheetname ""))
		(fill (thermal_gap 0.3) (thermal_bridge_width 0.25))
		(polygon (pts {pts}))
	)'''


def fiducial_keepout(x, y, side=2.0, layers='"F.Cu" "In1.Cu" "In2.Cu" "B.Cu"'):
    """Keep every layer's copper out of a fiducial's optical window.

    ⛔ THE ROUTER DOES NOT KNOW WHAT A FIDUCIAL IS. It has no net, so Specctra
    carries it as a component with no connections and freerouting treats the
    space above it as free board — which is how a VDD_3V3 track ended up 0.44 mm
    from FID5's pad, a via landed inside FID4's mask opening, and five soldermask
    apertures merged two different nets into one window. A placement camera
    looking for a round copper mark on bare mask would have found a track
    crossing it.

    ⭐ The size is not chosen, it is READ OFF THE FOOTPRINT: 1 mm of bare copper
    with a 0.5 mm mask margin is a 2 mm soldermask opening, and a 2 mm square
    contains that 2 mm circle exactly. Keeping copper out of the window is the
    whole optical requirement — no more, since every millimetre cleared here is
    a millimetre the router cannot use on a board that is already tight.

    ⚠️ Pads stay allowed. A neighbouring part whose pad grazes the window is a
    placement question, and place.py answers it by giving fiducials a 2 mm
    courtyard of their own; making it a keepout violation too would report the
    same problem twice and block routing on the second one.
    """
    h = side / 2
    pts = " ".join(f"(xy {CX + x + dx:.4f} {CY + y + dy:.4f})" for dx, dy in (
        (-h, -h), (h, -h), (h, h), (-h, h)))
    return f'''	(zone
		(net 0)
		(net_name "")
		(layers {layers})
		(uuid "{uid()}")
		(name "FID_KEEPOUT")
		(hatch edge 0.5)
		(keepout (tracks not_allowed) (vias not_allowed) (pads allowed)
			(copperpour not_allowed) (footprints allowed))
		(placement (enabled no) (sheetname ""))
		(fill (thermal_gap 0.3) (thermal_bridge_width 0.25))
		(polygon (pts {pts}))
	)'''


def power_zone(layer, name, net_name, net, x0=-46.5, x1=47.5, y0=-8.5, y1=8.5):
    """A rectangular supply pour over the centre island.

    ⚠️ Priority 1, above the ground pours. Two zones on the same layer with the
    same priority interleave in whatever order they were written, which is not a
    decision anyone made; the higher number wins the overlap explicitly.
    """
    pts = " ".join(f"(xy {CX + x:.4f} {CY + y:.4f})"
                   for x, y in ((x0, y0), (x1, y0), (x1, y1), (x0, y1)))
    return f'''	(zone
		(net {net})
		(net_name "{net_name}")
		(layers "{layer}")
		(uuid "{uid()}")
		(name "{name}")
		(priority 1)
		(hatch edge 0.5)
		(connect_pads yes (clearance 0.2))
		(min_thickness 0.2)
		(filled_areas_thickness no)
		(fill yes (island_removal_mode 0) (thermal_gap 0.3) (thermal_bridge_width 0.25))
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
# ⚠️ The board file has to declare every net it uses, including the ones KiCad's
# schematic invented for no-connect pins. They are real entries in the netlist as
# far as parity is concerned.
for _r, _v, _s, _l, _f, _pins, _x, _y in nl.PARTS:
    for _num, _pname, _et, _net in _pins:
        if _net in nl.SINGLE_PIN_NETS:
            _key = f"unconnected-({_r}-{_pname.replace('/', '{slash}')}-Pad{_num})"
            NET_INDEX.setdefault(_key, len(NET_INDEX))


def _keepouts(settled, margin=0.6):
    """Courtyard of every placed part, in board coordinates, plus a margin.

    ⚠️ The first stitching pass dropped vias on a fixed grid and put seven of
    them inside footprints: 7 hole-clearance violations, 7 mask bridges and 4
    shorts. A via grid has to know where the parts are.

    ⛔ AND IT HAS TO KNOW WHERE THEY ACTUALLY ARE. This read the coordinates out
    of netlist.py, which are the floorplan HINT — place.relax() then moves parts
    by up to 3.9 mm, so every box was protecting the spot a part used to be
    proposed for. The 0.6 mm margin hid it for as long as nothing moved far.
    """
    boxes = []
    for _ref, _v, _sym, lib, fp, _pins, _hx, _hy in nl.PARTS:
        x, y = settled[_ref]
        # ⚠️ A fiducial's library courtyard is barely wider than its 1 mm pad,
        # which would let a stitching via sit inside the 2 mm window a camera
        # reads. Two of them did. Same number as place.FID_COURTYARD.
        if _sym == place.FIDUCIAL_SYMBOL:
            h = place.FID_COURTYARD / 2
            boxes.append((x - h - margin, x + h + margin,
                          y - h - margin, y + h + margin))
            continue
        path = footprint_path(lib, fp)
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


def via_in_pad(net_index, settled):
    """Vias dropped inside the A121's interior balls, before routing.

    ⛔ AN INTERIOR BALL ON A 0.5 mm BGA CANNOT ESCAPE ON THE SURFACE. The land is
    0.25 mm across, which leaves 0.25 mm to the next land, and a 0.1 mm track
    with 0.1 mm clearance on each side needs 0.3 mm. There is no route out. The
    router does not report this as impossible — it reports four unconnected pads
    and stops, which is the same thing said quietly.
    ⭐ This is the claim an earlier version of this project made about the QFN,
    where it was false: a QFN has one perimeter row and every pin escapes
    outwards. On a BGA it is true, and only for the balls that are actually
    surrounded. Twenty-three of the A121's fifty balls carry signals and only
    four of those are interior, so four vias per sensor is the whole cost.

    ⚠️ Via-in-pad has to be FILLED AND CAPPED at fabrication or the paste drains
    into the hole and the joint starves. tools/fab_notes.py says so.
    """
    import math

    import generate_footprints as gf
    out = []
    for ref in ("U2", "U6"):
        px, py = settled[ref]
        # ⛔ THE BALL OFFSETS HAVE TO BE ROTATED WITH THE PART. The first version
        # of this used the footprint's own coordinates directly, and once the
        # sensors were turned to face the processor every via landed on a
        # different ball — quietly, because a via on the wrong pad is still a
        # legal via. KiCad's angle is counter-clockwise in a y-down frame, so
        # x' = bx cos + by sin and y' = -bx sin + by cos.
        th = math.radians(nl.ROTATION.get(ref, 0))
        cos_t, sin_t = math.cos(th), math.sin(th)
        for ball, name in gf.A121_BALLS.items():
            row, col = gf.A121_ROWS.index(ball[0]), int(ball[1:])
            interior = 0 < row < len(gf.A121_ROWS) - 1 and 1 < col < 10
            if not interior or name == "GND":
                continue
            bx, by = gf.a121_position(ball)
            rx = bx * cos_t + by * sin_t
            ry = -bx * sin_t + by * cos_t
            net = nl.pad_nets(ref)[ball]
            out.append(via(px + rx, py + ry, net_index[net], size=0.25, drill=0.1))
    return out


# Ground stitching: (x range, the two y rows it runs along).
STITCH_ROWS = [
    (range(-46, 48, 4), (-9.3, 9.3)),      # centre island, along both edges
    (range(-76, -48, 3), (-2.6, 2.6)),     # left flex tail
    (range(51, 79, 3), (-2.6, 2.6)),       # right flex tail
    (range(-94, -78, 4), (-7.6, 7.6)),     # left rigid island
    (range(82, 98, 4), (-7.6, 7.6)),       # right rigid island
]


def route(net_index, settled):
    """Ground stitching plus the signal routing from route.py."""
    out = []
    gnd = net_index["GND"]
    boxes = _keepouts(settled)
    # ⛔ THE CLEARANCE TEST USED TO GUARD ONE ROW OUT OF FIVE. The comment on
    # _keepouts said a via grid has to know where the parts are; four of the
    # five loops below did not ask. It survived because the tails and the end
    # islands were nearly empty — until a fiducial moved onto one of those rows
    # and collected a short, two hole clearances, a mask bridge and a keepout
    # violation from a single unguarded via.
    for xs, ys in STITCH_ROWS:
        for x in xs:
            for y in ys:
                if _clear(x, y, boxes):
                    out.append(via(x, y, gnd))

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
    # 2. RF. ⭐ THIS USED TO BE ABOUT THE 60 GHz PATCHES and it no longer is.
    #    The board carried two 2x4 patch arrays on 0.25 mm islands because the
    #    transceiver was in the middle; rf/feed_loss.py priced that feed at
    #    8.2 dB one way, and then the real part settled it — the Acconeer A121
    #    has its antenna inside the package, so the sensors moved to the ends
    #    and the patches are gone. In1.Cu stays a solid reference anyway: it is
    #    still the return plane for a 2.4 GHz feed and for SPI running the whole
    #    196 mm of the board.
    #
    # ⚠️ In1.Cu is poured and NOT routed on, and that is enforced rather than
    # asserted: tools/route.sh marks it a `power` layer in the Specctra export,
    # because an autorouter handed four signal layers will use four.
    # ⛔ A VDD_3V3 POUR ON B.Cu WAS TRIED HERE AND MADE THINGS WORSE. B.Cu was
    # nearly empty — 22 tracks against 334 on In2.Cu — so pouring the 3.3 V rail
    # on it looked free. It cost four clearance errors where the pour met ground
    # copper the router had already placed, and it did not fix the two supply
    # pins it was meant to fix. power_zone() is kept because the reasoning still
    # holds for a board laid out with the pour in mind from the start; adding a
    # plane underneath finished routing is not the same thing.
    # ⛔ A no-connect pin must carry NO net on the board. The schematic gives it
    # an auto-generated "unconnected-(U1-P1.09-Pad37)" name; putting this
    # project's own SPARE3 on the pad instead makes the two files disagree and
    # DRC reports it as a net conflict — correctly, because a pad that claims to
    # be on a net the schematic has never heard of is exactly the divergence
    # schematic parity exists to catch.
    settled, worst = place.relax(nl.PARTS,
                                 lambda l, f: open(footprint_path(l, f)).read(),
                                 rotation=nl.ROTATION)
    print(f"    placement settled, worst displacement {worst:.2f} mm")

    # ⛔ The keepout is written BEFORE the pours so it is unambiguous which one
    # wins; KiCad honours it either way, but a reader should not have to know
    # that.
    _ax, _ay = settled["AE1"]
    r.append(antenna_keepout(_ax, _ay))
    for _ref, _v, _sym, *_rest in nl.PARTS:
        if _sym == place.FIDUCIAL_SYMBOL:
            r.append(fiducial_keepout(*settled[_ref]))
    r.append(ground_zone("F.Cu", "GND_top"))
    r.append(ground_zone("In1.Cu", "GND_reference"))
    r.append(ground_zone("B.Cu", "GND_bottom"))

    # ⭐ The coordinates in netlist.py are a FLOORPLAN, not a layout: they say
    # the radars belong at the ends and the FSR front end belongs beside its
    # connector. place.relax() turns that into positions whose courtyards do not
    # intersect, because 91 hand-typed coordinates always collide somewhere —
    # the first pass collided in 28 places.
    # components, placed and netted from netlist.py
    for ref, val, _sym, lib, fp, pins, _hx, _hy in nl.PARTS:
        x, y = settled[ref]
        # ⚠️ A no-connect pin is not netless on the board — KiCad's schematic
        # invents a name for it, `unconnected-(U1-P1.09-Pad37)`, with slashes in
        # the pin name escaped as {slash}. Leaving the pad netless is just as
        # much a divergence as putting the wrong net on it; parity wants the
        # same string on both sides, so it is reproduced here exactly.
        _pn = {}
        for _num, _pname, _et, _net in pins:
            if _net in nl.SINGLE_PIN_NETS:
                _safe = _pname.replace("/", "{slash}")
                _pn[str(_num)] = f"unconnected-({ref}-{_safe}-Pad{_num})"
            else:
                _pn[str(_num)] = _net
        r.append(read_footprint(lib, fp, ref, val, x, y, _pn, NET_INDEX,
                                nl.ROTATION.get(ref, 0)))

    # ── Routing ──────────────────────────────────────────────────────────
    # ⛔ THE DECORATIVE ROUTING IS GONE. Before there was a netlist, this block
    # drew bundles of tracks on net 0 to make the renders look like a circuit.
    # The moment the pads carried real nets, DRC read those tracks for what they
    # were: 40 shorts, 6 clearance violations and 168 solder-mask bridges — one
    # object producing more than half the errors on the board. Tracks that are
    # not connectivity have no business in a board file.
    r += via_in_pad(NET_INDEX, settled)
    r += route(NET_INDEX, settled)

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
        "U2/U6 A121: 60 GHz radar, antenna in package",
    ]):
        r.append(text(s_, 22.0, -0.6 + i * 1.9, "B.SilkS", 0.9, 0.14))

    # Design notes: comments layer, these never go to fabrication.
    for i, s_ in enumerate([
        "rigid FR4 islands 0.6 mm on 2L polyimide flex",
        "8 mm flex tails: min bend radius 12 mm (10x thickness)",
        "J4: 16 cols + 6 rows = 22 lines on a 24-way FFC",
        "U2/U6 need solid ground under the whole package (A121 ds 5.4)",
        "no 60 GHz copper on this board: the antennas are inside the A121",
    ]):
        r.append(text(s_, -98.0, 16.0 + i * 2.4, "Cmts.User", 1.1, 0.18))

    r.append(')')
    return "\n".join(r) + "\n"


if __name__ == "__main__":
    with open(OUT, "w") as f:
        f.write(build())
    print(f"OK  {OUT}  ({len(nl.PARTS)} components, {len(NET_INDEX) - 1} nets, "
          f"{len(OUTLINE)}-vertex outline)")
