#!/bin/bash
# Rebuild the routed board from the committed session file, without a router.
#
# ⭐ WHY THE .ses IS COMMITTED. The routed .kicad_pcb is a generated file: it
# comes from generate_pcb.py plus a routing session. Committing only the board
# would make the routing a thing nobody could reproduce or review; committing
# the session makes it a reviewable artefact that regenerates the board in two
# seconds on a machine with no Java.
set -e
cd "$(dirname "$0")/.."
KPY="${KICAD_PYTHON:-/Applications/KiCad/KiCad.app/Contents/Frameworks/Python.framework/Versions/Current/bin/python3}"
python3 hardware/generate_pcb.py | tail -1
"$KPY" hardware/specctra.py import hardware/smartbag_core.kicad_pcb hardware/smartbag_core.ses | tail -1
"$KPY" hardware/fill_zones.py hardware/smartbag_core.kicad_pcb | tail -1
"$KPY" hardware/stitch.py hardware/smartbag_core.kicad_pcb | tail -1
