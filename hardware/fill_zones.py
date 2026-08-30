#!/usr/bin/env python3
"""Fill the ground zones of the generated board. Run it with KiCad's Python.

⛔ WHY THIS IS A SEPARATE STEP. `kicad-cli pcb render` **does not fill zones**:
it draws whatever it finds in the file. The generator writes each zone as an
empty polygon, so without this pass the render shows a bare green board — and a
bare board communicates the wrong thing (it looks like a cutout, not a circuit).

Usage:
  /Applications/KiCad/KiCad.app/Contents/Frameworks/Python.framework/Versions/\\
      Current/bin/python3 hardware/fill_zones.py hardware/smartbag_core.kicad_pcb
"""
import sys

import pcbnew

path = sys.argv[1]
board = pcbnew.LoadBoard(path)
filler = pcbnew.ZONE_FILLER(board)
zones = board.Zones()
filler.Fill(zones)
board.Save(path)
print(f"OK  filled {len(zones)} zones -> {path}")
