#!/usr/bin/env python3
"""A board generator for the two boards that are not the insert board.

⛔ WHY NOT REUSE generate_pcb.py. That file is the insert board: it knows about
rigid islands and flex tails, three ground pours, an antenna keepout, via-in-pad
for a BGA and a placement relaxer. None of that applies to a 124 x 12 mm optics
strip with fifteen parts on it, and bending it until it did would put the
complicated board at risk to save a hundred lines. What IS shared is imported —
the footprint resolver, the s-expression inliner, the net injector — so there is
still one implementation of the tricky parts.

⭐ TWO LAYERS, ONE POUR. These boards are flex: the optics strip folds into the
collar and the taxel sheet lies under the whole insert. Four layers on a folding
flex is a fabrication problem nobody needs; two is what the interconnect
actually requires.

Usage:  python3 hardware/generate_board.py optics
"""
import importlib
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(HERE))

import generate_pcb as base       # noqa: E402
import place                     # noqa: E402


def stackup():
    return ('\t\t(layers\n'
            '\t\t\t(0 "F.Cu" signal)\n'
            '\t\t\t(2 "B.Cu" signal)\n'
            '\t\t\t(9 "F.Adhes" user "F.Adhesive")\n'
            '\t\t\t(11 "F.Paste" user)\n'
            '\t\t\t(5 "F.SilkS" user "F.Silkscreen")\n'
            '\t\t\t(7 "F.Mask" user)\n'
            '\t\t\t(6 "B.SilkS" user "B.Silkscreen")\n'
            '\t\t\t(8 "B.Mask" user)\n'
            '\t\t\t(10 "B.Paste" user)\n'
            '\t\t\t(44 "Edge.Cuts" user)\n'
            '\t\t\t(45 "Margin" user)\n'
            '\t\t\t(39 "F.CrtYd" user "F.Courtyard")\n'
            '\t\t\t(40 "B.CrtYd" user "B.Courtyard")\n'
            '\t\t\t(41 "F.Fab" user)\n'
            '\t\t\t(42 "B.Fab" user)\n'
            '\t\t\t(19 "Cmts.User" user "User.Comments")\n'
            '\t\t)\n')


def ground_pour(nl, layer, name, net_index):
    x0 = min(p[0] for p in nl.OUTLINE) + 0.4
    x1 = max(p[0] for p in nl.OUTLINE) - 0.4
    y0 = min(p[1] for p in nl.OUTLINE) + 0.4
    y1 = max(p[1] for p in nl.OUTLINE) - 0.4
    pts = " ".join(f"(xy {base.CX + x:.4f} {base.CY + y:.4f})"
                   for x, y in ((x0, y0), (x1, y0), (x1, y1), (x0, y1)))
    return f'''\t(zone
\t\t(net {net_index["GND"]})
\t\t(net_name "GND")
\t\t(layers "{layer}")
\t\t(uuid "{base.uid()}")
\t\t(name "{name}")
\t\t(hatch edge 0.5)
\t\t(connect_pads yes (clearance 0.2))
\t\t(min_thickness 0.2)
\t\t(filled_areas_thickness no)
\t\t(fill yes (island_removal_mode 0) (thermal_gap 0.3) (thermal_bridge_width 0.25))
\t\t(polygon (pts {pts}))
\t)'''


def build(nl, name, notes=(), pour=True):
    net_index = {"": 0, "GND": 1}
    for n in sorted(nl.nets()):
        net_index.setdefault(n, len(net_index))
    for ref, _v, _s, _l, _f, pins, _x, _y in nl.PARTS:
        for num, pname, _t, net in pins:
            if net in nl.SINGLE_PIN_NETS:
                key = f"unconnected-({ref}-{pname.replace('/', '{slash}')}-Pad{num})"
                net_index.setdefault(key, len(net_index))

    r = ['(kicad_pcb (version 20241229) (generator "smartbag")',
         '\t(generator_version "9.0")',
         '\t(general (thickness 0.2) (legacy_teardrops no))',
         '\t(paper "A3")']
    r.append(stackup().rstrip())
    r.append('\t(setup (pad_to_mask_clearance 0)'
             ' (allow_soldermask_bridges_in_footprints no))')
    for n, i in sorted(net_index.items(), key=lambda kv: kv[1]):
        r.append(f'\t(net {i} "{n}")')

    pts = list(nl.OUTLINE) + [nl.OUTLINE[0]]
    for (x1, y1), (x2, y2) in zip(pts, pts[1:]):
        r.append(base.line(x1, y1, x2, y2, "Edge.Cuts", 0.1))

    # ⛔ NOT EVERY BOARD WANTS A GROUND POUR. The taxel sheet is ninety-six pairs
    # of electrodes that must stay isolated from each other until a film presses
    # them together; pouring ground between them shorts the entire matrix to
    # ground, which DRC reported as ten shorting items and would have reported
    # as a dead sensor. A pour is a default, not a law.
    # ⛔ THE POUR AND THE ROUTER BOTH HAVE TO BE TOLD WHERE THE FIDUCIALS ARE.
    # Neither can work it out: a fiducial carries no net, so copper flows over
    # its window and a placement camera looks for a round mark on bare mask and
    # finds a track. The keepout goes in BEFORE the pours so it is unambiguous
    # which one wins. Same 2 mm — the footprint's own soldermask opening — as
    # the insert board.
    for ref, _v, sym, _l, _f, _p, x, y in nl.PARTS:
        if sym == place.FIDUCIAL_SYMBOL:
            r.append(base.fiducial_keepout(x, y, layers='"F.Cu" "B.Cu"'))
    if pour:
        r.append(ground_pour(nl, "F.Cu", "GND_top", net_index))
        r.append(ground_pour(nl, "B.Cu", "GND_bottom", net_index))

    for ref, val, _sym, lib, fp, pins, x, y in nl.PARTS:
        pn = {}
        for num, pname, _t, net in pins:
            if net in nl.SINGLE_PIN_NETS:
                safe = pname.replace("/", "{slash}")
                pn[str(num)] = f"unconnected-({ref}-{safe}-Pad{num})"
            else:
                pn[str(num)] = net
        r.append(base.read_footprint(lib, fp, ref, val, x, y, pn, net_index))

    for i, s in enumerate(notes):
        r.append(base.text(s, min(p[0] for p in nl.OUTLINE),
                           max(p[1] for p in nl.OUTLINE) + 4 + i * 2.4,
                           "Cmts.User", 1.1, 0.18))
    r.append(')')
    return "\n".join(r) + "\n"


BOARDS = {
    "optics": ("optics_netlist", "smartbag_optics", [
        "flexible polyimide, 0.2 mm, 2 layers, ENIG",
        "folds into the bag collar: min bend radius 2 mm",
        "U10 needs a clear optical window; no coverlay over its aperture",
        "D1-D4 are 850 nm: the camera on J11 must be a NoIR variant",
    ]),
}

# ⛔ "taxels" IS NOT IN BOARDS, AND THAT IS THE POINT. It used to be, and this
# file will happily produce a smartbag_taxels.kicad_pcb from it: a legal board
# with the right outline, the right connector and NONE OF THE 1155 COPPER SHAPES
# that are the entire reason the sheet exists. It overwrote the real one, and
# what gave it away was a single unconnected pad — the only visible trace of 96
# missing sensors.
#
# ⭐ The taxel sheet is built by generate_taxels.py, which calls build() here and
# then injects the electrodes. Two entry points for one board is a trap, so the
# wrong one now refuses instead of silently succeeding.
DELEGATED = {"taxels": "hardware/generate_taxels.py"}


def main():
    which = sys.argv[1] if len(sys.argv) > 1 else "optics"
    if which in DELEGATED:
        sys.exit(f"{which!r} is not built here — run {DELEGATED[which]}. "
                 "This generator would write a board with no electrodes on it.")
    if which not in BOARDS:
        sys.exit(f"unknown board {which!r}; known: {', '.join(BOARDS)}")
    mod, stem, notes = BOARDS[which]
    nl = importlib.import_module(mod)
    out = os.path.join(HERE, f"{stem}.kicad_pcb")
    with open(out, "w") as f:
        f.write(build(nl, stem, notes))
    print(f"OK  {out}  ({len(nl.PARTS)} components, {len(nl.nets())} nets)")


if __name__ == "__main__":
    main()
