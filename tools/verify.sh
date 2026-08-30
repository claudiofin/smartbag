#!/bin/bash
# Everything that can be checked without a human looking at a picture.
#
# ⭐ Six independent checks, and they disagree in useful ways: check.py knows
# about geometry the CAD and the renderer share, ERC knows about the schematic,
# DRC knows about the board, the firmware tests know about time and about what
# current does in a passive matrix, the protocol test knows whether the phone
# and the device still agree on a byte layout, and the physics scripts know
# what the design costs. Each has caught things the others could not see.
set -e
cd "$(dirname "$0")/.."
KPY=/Applications/KiCad/KiCad.app/Contents/Frameworks/Python.framework/Versions/Current/bin/python3

echo "== design constraints =="
python3 tools/check.py | tail -1

echo
echo "== firmware =="
make -s -C firmware test | grep -E "checks|passed"

echo
echo "== protocol: the app decodes the firmware's own bytes =="
make -s -C firmware vectors >/dev/null
node app/test_protocol.mjs | tail -1

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

echo
echo "== physics =="
# ⚠️ These do not pass or fail: they report. Both currently report a problem
# the design has not answered, and printing the headline here is the only thing
# stopping it being quietly forgotten.
python3 rf/feed_loss.py | grep -E "^  (⛔|  Feed loss)" | head -1
python3 thermal/budget.py | grep -E "⛔|Cell stays" | head -1
