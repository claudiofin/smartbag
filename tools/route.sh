#!/bin/bash
# Route the board: KiCad -> Specctra -> Freerouting -> KiCad.
#
# ⛔ KICAD HAS NO AUTOROUTER. It had one up to version 5 and it was removed. What
# survives is the interchange format, so the flow is: pcbnew writes a .dsn,
# somebody else's router writes a .ses, pcbnew reads it back.
#
# ⭐ THE ROUTER IS FREEROUTING, which is a maze router with rip-up and retry —
# exactly the thing three hand-written attempts in hardware/route.py established
# was missing. Those attempts scored 466, 989 and 852 violations. This scores 0.
# Rip-up is the whole difference: a router that never reconsiders paints itself
# into the first congested channel it meets.
#
# ⚠️ Freerouting 1.9 is a GUI application. It calls getScreenSize() before it
# does anything else, so it cannot run headless — it will open a window. With
# -de/-do it routes and exits on its own.
#
# Usage:  tools/route.sh [passes]        (default 60)
set -e
cd "$(dirname "$0")/.."

# No bytecode cache: a stale .pyc means checking a file that is no
# longer on disk. See tools/verify.sh.
export PYTHONDONTWRITEBYTECODE=1

JAR="${FREEROUTING_JAR:-$HOME/.kicad-mcp/freerouting.jar}"
KPY="${KICAD_PYTHON:-/Applications/KiCad/KiCad.app/Contents/Frameworks/Python.framework/Versions/Current/bin/python3}"
PASSES="${1:-60}"
BOARD=hardware/smartbag_core.kicad_pcb
WORK="$(mktemp -d)"

[ -f "$JAR" ] || { echo "no freerouting.jar (set FREEROUTING_JAR)"; exit 1; }

echo "== generate =="
python3 hardware/generate_pcb.py | tail -1

echo "== export DSN =="
# In1.Cu is marked a PLANE, not a signal layer. ⛔ Without that the router uses
# it: the first routed board put 34% of its tracks through the RF reference
# plane, which a comment claimed was never routed on. A comment is not a rule.
"$KPY" hardware/specctra.py export "$BOARD" "$WORK/board.dsn" In1.Cu | tail -1

echo "== route ($PASSES passes) =="
( cd "$WORK" && java -jar "$JAR" -de board.dsn -do board.ses -mp "$PASSES" \
    > freerouting.log 2>&1 ) || true
grep -E "Auto-routing was completed|Saving" "$WORK/freerouting.log" | sed 's/^/  /'
[ -f "$WORK/board.ses" ] || { echo "router produced no session file"; exit 1; }

cp "$WORK/board.ses" hardware/smartbag_core.ses
echo "  kept hardware/smartbag_core.ses"

echo "== import =="
"$KPY" hardware/specctra.py import "$BOARD" hardware/smartbag_core.ses | tail -1
"$KPY" hardware/fill_zones.py "$BOARD" | tail -1
# ⭐ Stitching has to happen AFTER routing, not before. generate_pcb.py drops a
# grid of ground vias when there is nothing on the board yet; the islands that
# matter are the ones the routing itself cuts out of the pour, and those can
# only be found once the tracks exist.
"$KPY" hardware/stitch.py "$BOARD" | tail -1

echo "== DRC =="
kicad-cli pcb drc --schematic-parity --severity-all -o "$WORK/drc.rpt" "$BOARD" \
  >/dev/null 2>&1 || true
grep -E "Found .* (DRC violations|unconnected pads|Footprint errors)" "$WORK/drc.rpt" \
  | sed 's/^\*\* /  /;s/ \*\*$//'
rm -rf "$WORK"
