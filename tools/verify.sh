#!/bin/bash
# Everything that can be checked without a human looking at a picture.
#
# ⭐ Four independent checks, and they disagree in useful ways: check.py knows
# about geometry the CAD and the renderer share, ERC knows about the schematic,
# DRC knows about the board, and the firmware tests know about time. Each has
# caught things the others could not see.
set -e
cd "$(dirname "$0")/.."
KPY=/Applications/KiCad/KiCad.app/Contents/Frameworks/Python.framework/Versions/Current/bin/python3

echo "== design constraints =="
python3 tools/check.py | tail -1

echo
echo "== firmware =="
make -s -C firmware test | tail -2

echo
echo "== ERC =="
kicad-cli sch erc --severity-all --exit-code-violations \
  -o /tmp/smartbag_erc.rpt hardware/smartbag_core.kicad_sch >/dev/null 2>&1 \
  && echo "  0 violations" || sed -n '/ERC messages/p' /tmp/smartbag_erc.rpt

echo
echo "== DRC (with schematic parity) =="
kicad-cli pcb drc --schematic-parity --severity-all \
  -o /tmp/smartbag_drc.rpt hardware/smartbag_core.kicad_pcb >/dev/null 2>&1 || true
grep -E "Found .* (DRC violations|unconnected pads|Footprint errors)" /tmp/smartbag_drc.rpt \
  | sed 's/^\*\* /  /;s/ \*\*$//'
