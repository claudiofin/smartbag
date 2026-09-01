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
set -o pipefail   # `| tail -1` otherwise hides every failure
cd "$(dirname "$0")/.."
# ⛔ NO BYTECODE CACHE. Every number this project prints comes from importing
# hardware/*.py and measuring what is in them, which makes a stale __pycache__
# entry a way to check the wrong file and be told it passed. That is not
# hypothetical: restoring bom.py from a backup produced a file whose size and
# timestamp matched the .pyc of an earlier version, so Python kept serving the
# old bytecode and the bill of materials was validated against a part number
# that was no longer in the source. Writing none is cheaper than invalidating.
export PYTHONDONTWRITEBYTECODE=1

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
kicad-cli pcb drc --schematic-parity --severity-error \
  -o /tmp/smartbag_drc.rpt hardware/smartbag_core.kicad_pcb >/dev/null 2>&1 || true
grep -E "Found .* (DRC violations|unconnected pads|Footprint errors)" /tmp/smartbag_drc.rpt \
  | sed 's/^\*\* /  /;s/ \*\*$//'

echo
echo "== the other two boards =="
# ⛔ THERE ARE THREE. The insert board is the one with the processor on it; the
# optics flex carries the camera, the illuminators and the time-of-flight sensor
# that arms the whole wake-up chain, and the taxel sheet carries 96 force-sensing
# sites. Checking only the first would have been checking a third of the product.
for _b in optics taxels; do
  kicad-cli pcb drc --severity-error -o /tmp/sb_$_b.rpt \
    hardware/smartbag_$_b.kicad_pcb >/dev/null 2>&1 || true
  printf "  %-8s %s\n" "$_b" \
    "$(grep -E 'Found .*(violations|unconnected pads)' /tmp/sb_$_b.rpt \
       | sed 's/^\*\* //;s/ \*\*$//' | tr '\n' ' ')"
done

echo
echo "== BOM vs footprints =="
python3 tools/bom_report.py > /tmp/smartbag_bom.txt
echo "  $(grep -cE '^  ok ' /tmp/smartbag_bom.txt) of $(grep -cE '^  (ok|⛔) ' /tmp/smartbag_bom.txt) named parts have a real MPN whose package fits"
grep "cannot accept" /tmp/smartbag_bom.txt | sed 's/^/  /' || true

echo
echo "== recognition fits the processor =="
python3 ml/inference_budget.py | grep -E "IT FITS|IT DOES NOT" | sed 's/^ */  /'

echo
echo "== physics =="
# ⚠️ These do not pass or fail: they report. Both currently report a problem
# the design has not answered, and printing the headline here is the only thing
# stopping it being quietly forgotten.
python3 rf/feed_loss.py | grep -E "✅ SETTLED|^  ⛔" | tail -1
python3 thermal/budget.py | grep -E "✅ ALL THREE|Cell stays" | tail -1
