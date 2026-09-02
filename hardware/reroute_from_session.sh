#!/bin/bash
# Rebuild the routed board from the committed session file, without a router.
#
# ⭐ WHY THE .ses IS COMMITTED. The routed .kicad_pcb is a generated file: it
# comes from generate_pcb.py plus a routing session. Committing only the board
# would make the routing a thing nobody could reproduce or review; committing
# the session makes it a reviewable artefact that regenerates the board in two
# seconds on a machine with no Java.
set -e
# ⛔ AND pipefail, WITHOUT WHICH set -e IS DECORATION HERE. Every step in this
# file ends in `| tail -1`, so the exit status the shell sees is tail's, and
# tail always succeeds. A crash inside specctra.py printed its traceback and the
# script carried straight on into fill, stitch and route — producing a board
# with 117 unconnected pads out of an import that had never happened, and
# reporting it as a normal run.
set -o pipefail
cd "$(dirname "$0")/.."
KPY="${KICAD_PYTHON:-/Applications/KiCad/KiCad.app/Contents/Frameworks/Python.framework/Versions/Current/bin/python3}"
python3 hardware/generate_pcb.py | tail -1
"$KPY" hardware/specctra.py import hardware/smartbag_core.kicad_pcb hardware/smartbag_core.ses | tail -1
"$KPY" hardware/fill_zones.py hardware/smartbag_core.kicad_pcb | tail -1
"$KPY" hardware/stitch.py hardware/smartbag_core.kicad_pcb | tail -1
# ⛔ THE FINISHING IS NOT IN THE SESSION FILE. freerouting wrote the .ses and
# left five connections; what closed them lives in four steps after it — the
# escape vias the tidy-up now KEEPS, the layer changes that were never routing
# problems, and two paths a breadth-first search found and DRC accepted. All of
# it is deterministic, so re-running it here reproduces the same board.
# ⚠️ Order matters. --tidy first, because it decides which fanout vias survive;
# --link before the maze router, because the maze router answers a question
# these do not ask and spends a minute per pair doing it; repairs.py last,
# because it lays copper the searches cannot find.
"$KPY" hardware/maze.py --tidy hardware/smartbag_core.kicad_pcb | tail -1
for _ in 1 2 3; do
  "$KPY" hardware/maze.py --link hardware/smartbag_core.kicad_pcb 2>/dev/null \
    | grep -E "via was|track from" || true
  "$KPY" hardware/maze.py hardware/smartbag_core.kicad_pcb 2>/dev/null \
    | grep -E "^done" || true
done
"$KPY" hardware/repairs.py hardware/smartbag_core.kicad_pcb | tail -1
