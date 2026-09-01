#!/usr/bin/env python3
"""Put netlist.py's BACK parts on the back, and give them a way up.

⛔ MIRRORING A FOOTPRINT IN A TEXT GENERATOR IS A GOOD WAY TO BUILD AN
UNBUILDABLE BOARD. A flipped part is not "the same s-expression with F.Cu
swapped for B.Cu": every child item moves to its mirrored layer, the geometry
reflects about the footprint origin, and the pad numbering ends up transposed as
seen from the top. Get one of those wrong and the board looks right in every
render and has pin 1 in the wrong corner.

⭐ SO KICAD DOES IT. generate_pcb.py writes every part on the front, and this
step calls FOOTPRINT::Flip() on the few that belong underneath — the same
function pcbnew calls when somebody presses F. There is no second implementation
of the mirroring to be wrong.

⚠️ AND A CAPACITOR UNDER A PIN IS NOT CONNECTED TO IT BY BEING UNDER IT. Its
ground terminal lands on the bottom ground pour, which is the point; its supply
terminal is on B.Cu and the pin is on F.Cu, so something has to carry it up.

⛔ THAT SOMETHING IS NOT A VIA IN THE PAD, AND TRYING IT UNDID THE WHOLE POINT OF
MOVING THE PART. A through via punches every layer, and directly under a QFN
every layer is where the escapes are: four vias in four pads produced five shorts
against MUX_S2, ADC3 and CS_RADAR_R, two drilled holes exactly on top of existing
ones, and eight solder-mask bridges. The capacitor was moved to the back to get
copper OFF the top surface; a via in its pad puts it straight back.

⭐ SO THE ROUTER DOES IT. The capacitor's supply pad and the pin are two ends of
one net like any other, and Freerouting will drop its own via wherever there is
room — which is a question about the whole board, not about this pad, and is
exactly what a router is for. This file only flips.

Usage:  <kicad-python> hardware/flip_back.py <board>
"""
import os
import sys

import pcbnew

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import netlist as nl              # noqa: E402

MM = 1e6


def flip(path):
    board = pcbnew.LoadBoard(path)
    moved = 0

    for f in board.GetFootprints():
        ref = f.GetReference()
        if ref not in nl.BACK:
            continue
        if f.IsFlipped():
            continue
        # ⚠️ Flip about the part's own position, so it stays where the placement
        # put it. Flipping about the board origin would send it across the room.
        f.Flip(f.GetPosition(), False)
        moved += 1


    if moved:
        pcbnew.ZONE_FILLER(board).Fill(board.Zones())
        board.Save(path)
    print(f"OK  {moved} part(s) moved to the back -> {path}")
    # ⛔ A BOARD WITH NOTHING ON THE BACK IS NOT AN ERROR, IT IS A CHANGED
    # netlist.py. Saying so is better than a silent no-op that looks like
    # success on the day somebody empties BACK and wonders why assembly still
    # quotes two sides.
    if not moved and nl.BACK:
        print(f"    (already flipped: {', '.join(nl.BACK)})")
    return moved


if __name__ == "__main__":
    flip(sys.argv[1])
