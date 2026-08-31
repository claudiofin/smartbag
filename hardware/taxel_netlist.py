#!/usr/bin/env python3
"""The taxel sheet's electrical description: one connector and 22 nets.

⚠️ THERE ARE NO COMPONENTS. The sensing elements are copper geometry, not parts,
so this file exists to give the sheet a netlist at all — a board with one
connector still needs one, or nothing can check that the twenty-two lines
leaving it are the same twenty-two the insert board expects.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import dimensions as dim          # noqa: E402

PWR_IN, PWR_OUT, IN, OUT, BIDI, PASSIVE = (
    "power_in", "power_out", "input", "output", "bidirectional", "passive")

# ⚠️ Pin for pin with J4 on the insert board. tools/check.py asserts it.
J20_PINS = ([(1, "GND", PWR_IN, "GND")]
            + [(2 + i, f"C{i}", PASSIVE, f"FSR_C{i}") for i in range(dim.FSR_COLS)]
            + [(18 + i, f"R{i}", PASSIVE, f"FSR_R{i}") for i in range(dim.FSR_ROWS)]
            + [(24, "SHLD", PWR_IN, "GND")])

PARTS = [
    ("J20", "FFC to insert, 24 way", "FFC_24", "Connector_FFC-FPC",
     "Hirose_FH12-24S-0.5SH_1x24-1MP_P0.50mm_Horizontal", J20_PINS,
     0.0, dim.INS_D / 2 + 14.0),
    ("FID1", "fiducial", "FIDUCIAL", "Fiducial", "Fiducial_1mm_Mask2mm",
     [], -dim.INS_W / 2 + 4.0, dim.INS_D / 2 + 14.0),
    ("FID2", "fiducial", "FIDUCIAL", "Fiducial", "Fiducial_1mm_Mask2mm",
     [], dim.INS_W / 2 - 4.0, dim.INS_D / 2 + 14.0),
]

# ⛔ Every column and row is a power flag. Not because they carry power, but
# because on THIS board nothing drives them: the drivers are 200 mm away at the
# other end of a flex cable, and ERC has no way to know that. A board that is
# one half of a circuit has to say which half.
POWER_FLAGS = (["GND"] + [f"FSR_C{i}" for i in range(dim.FSR_COLS)]
               + [f"FSR_R{i}" for i in range(dim.FSR_ROWS)])
SINGLE_PIN_NETS = []
NOT_IN_BOM = {"FID1", "FID2"}

# The sensing area is the insert floor; the connector sits on a tab above it.
# ⚠️ Nine millimetres of margin on the LEFT, two on the right. The six row
# busses climb out of the sensing area on that side, each in its own lane, and
# the first outline gave them 2 mm for 2.7 mm of lanes — sixty-three
# copper-to-edge violations, all of them the same mistake counted once per
# segment.
OUTLINE = [(-dim.INS_W / 2 - 9, -dim.INS_D / 2 - 2),
           (dim.INS_W / 2 + 2, -dim.INS_D / 2 - 2),
           (dim.INS_W / 2 + 2, dim.INS_D / 2 + 26),
           (-dim.INS_W / 2 - 9, dim.INS_D / 2 + 26)]


def nets():
    out = {}
    for ref, _v, _s, _fl, _fp, pins, _x, _y in PARTS:
        for number, _name, etype, net in pins:
            out.setdefault(net, []).append((ref, number, etype))
    return out


def part(ref):
    return [p for p in PARTS if p[0] == ref][0]


def pad_nets(ref):
    return {str(number): net for number, _n, _t, net in part(ref)[5]}


def symbols():
    out = {}
    for _r, _v, sym, _fl, _fp, pins, _x, _y in PARTS:
        out.setdefault(sym, pins)
    return out
