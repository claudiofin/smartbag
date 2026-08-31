#!/bin/bash
# Everything a fabricator needs, from the routed board.
#
# ⚠️ THIS SCRIPT CANNOT TELL YOU THE BOARD IS BUILDABLE. It turns a .kicad_pcb
# into Gerbers, drill files and a placement list, and it will do that just as
# happily for a board whose footprints are for parts that do not exist. Run
# tools/bom_report.py for that question; run tools/verify.sh for DRC. This is
# the last step, not the check.
#
# Usage:  tools/fab.sh [outdir]
set -e
cd "$(dirname "$0")/.."
OUT="${1:-fab}"
BOARD=hardware/smartbag_core.kicad_pcb
rm -rf "$OUT"; mkdir -p "$OUT/gerbers"

# ⛔ Name every layer explicitly. The default set is for a 2-layer board and
# would silently drop In1.Cu and In2.Cu — a 4-layer stackup plotted as 2 layers
# is a board that shorts everywhere the inner planes were doing the work.
LAYERS="F.Cu,In1.Cu,In2.Cu,B.Cu,F.Paste,B.Paste,F.Silkscreen,B.Silkscreen,F.Mask,B.Mask,Edge.Cuts"

echo "== gerbers =="
kicad-cli pcb export gerbers --output "$OUT/gerbers/" --layers "$LAYERS" \
  --subtract-soldermask --check-zones --no-protel-ext "$BOARD" | tail -2

echo "== drill =="
# Separate PTH and NPTH: a fab that gets them merged plates the mounting holes.
kicad-cli pcb export drill --output "$OUT/gerbers/" --format excellon \
  --excellon-separate-th --generate-map --map-format gerberx2 \
  --excellon-units mm --drill-origin absolute "$BOARD" | tail -1

echo "== placement =="
kicad-cli pcb export pos --output "$OUT/smartbag-top.pos" --side front \
  --format csv --units mm --use-drill-file-origin "$BOARD" | tail -1
kicad-cli pcb export pos --output "$OUT/smartbag-bottom.pos" --side back \
  --format csv --units mm --use-drill-file-origin "$BOARD" | tail -1

echo "== bom =="
python3 tools/bom_report.py > "$OUT/bom-report.txt"
cp hardware/bom.csv "$OUT/smartbag-bom.csv"
echo "  smartbag-bom.csv + bom-report.txt"

echo "== the checks, shipped with the artwork =="
# ⛔ THE DRC REPORT GOES IN THE PACKAGE. A fabricator cannot tell a board that
# passes from one that does not, and neither can anyone reading a zip file six
# months from now. Saying "0 violations, 3 unconnected pads" in a note is a
# claim; shipping the report is evidence.
kicad-cli pcb drc --schematic-parity --severity-all \
  -o "$OUT/drc-report.txt" "$BOARD" >/dev/null 2>&1 || true
kicad-cli sch erc --severity-all -o "$OUT/erc-report.txt" \
  hardware/smartbag_core.kicad_sch >/dev/null 2>&1 || true
grep -E "Found .* (violations|unconnected pads|Footprint errors)" "$OUT/drc-report.txt" \
  | sed 's/^\*\* /  /;s/ \*\*$//'

echo "== the DRC these files were plotted from =="
# ⛔ SHIPPED WITH THE ARTWORK, not summarised. A fabrication package that says
# "DRC is clean" and does not include the report is asking to be believed. This
# one includes what remains, so a reviewer can disagree with it.
kicad-cli pcb drc --schematic-parity --severity-all -o "$OUT/drc-report.txt" \
  "$BOARD" >/dev/null 2>&1 || true
grep -E "Found .*(violations|unconnected pads|Footprint errors)" \
  "$OUT/drc-report.txt" | sed 's/^\*\* /  /;s/ \*\*$//'

echo "== stats =="
kicad-cli pcb export stats --output "$OUT/board-stats.txt" "$BOARD" >/dev/null 2>&1 || true

python3 tools/fab_notes.py > "$OUT/README-FAB.md"
echo "  README-FAB.md"

( cd "$OUT" && zip -qr ../"$OUT"/smartbag-gerbers.zip gerbers )
echo
echo "wrote $OUT/  ($(du -sh "$OUT" | cut -f1))"
ls "$OUT/gerbers" | sed 's/^/  /'
