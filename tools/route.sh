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
# ⛔ MORE PASSES IS NOT BETTER, AND IT WAS WORTH MEASURING RATHER THAN ASSUMING.
# -mp caps the AUTOROUTER's passes, not just the optimiser's, so 60 looked like
# an arbitrary limit somebody had left on. Running the same board at 400 took 52
# minutes instead of 15 and came back with SIX unconnected pads instead of four.
# Rip-up and retry does not improve monotonically: given more passes it tears out
# routes it already had and does not always find them again.
#
# ⚠️ So 60 is a measurement, not a default. If the board changes enough to be
# worth re-testing, back up hardware/smartbag_core.ses first — this script
# overwrites it, and a worse session is not obviously worse until DRC says so.
#
# Usage:  tools/route.sh [passes]        (default 60, and 60 is the best one found)
set -e
set -o pipefail   # `| tail -1` otherwise hides every failure
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

# ⛔ THE FLIP HAS TO HAPPEN BEFORE THE ROUTER SEES THE BOARD. generate_pcb.py is
# a text generator and puts every part on the front; netlist.py's BACK list says
# which belong underneath, and a router handed the unflipped board routes to
# pads that are about to move to the other side.
"$KPY" hardware/flip_back.py "$BOARD" | tail -1

echo "== export DSN =="
# In1.Cu is marked a PLANE, not a signal layer. ⛔ Without that the router uses
# it: the first routed board put 34% of its tracks through the RF reference
# plane, which a comment claimed was never routed on. A comment is not a rule.
"$KPY" hardware/specctra.py export "$BOARD" "$WORK/board.dsn" In1.Cu | tail -1

echo "== route ($PASSES passes) =="
# ⛔ -mt 1, AND THE OBVIOUS SPEED-UP IS A TRAP. The optimiser's own log says
# "route optimization on 1 thread", and on the wider-tailed board that phase ran
# for over two hours after an auto-route that finished in eighteen minutes — so
# handing it the other eight cores looks like the whole fix. Freerouting's answer
# to -mt 8 is a warning in its own log: "Multi-threaded route optimization is
# broken and it is known to generate clearance violations."
#
# ⚠️ So the stall is paid rather than solved. It costs wall-clock and nothing
# else: the optimiser trims vias and length and does not change connectivity, so
# a run killed during it loses tidiness, not routes — except that freerouting
# only writes the session at the very end, which is why it has to be waited out.
( cd "$WORK" && java -jar "$JAR" -de board.dsn -do board.ses -mp "$PASSES" \
    -mt 1 > freerouting.log 2>&1 ) || true
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
