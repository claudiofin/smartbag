#!/bin/bash
# Full pipeline: circuit -> bag -> render.
#
# ⭐ IT IS A CHAIN, not three separate things. The PCB does not end up in a PDF:
# it is exported to GLB and becomes an object in the same scene as the bag. That
# is the only way to notice that a board does not fit where it was supposed to —
# and that actually happened on the first pass (see the comment above OUTLINE in
# hardware/generate_pcb.py).
set -e
cd "$(dirname "$0")/.."
# No bytecode cache: a stale .pyc means checking a file that is no
# longer on disk. See tools/verify.sh.
export PYTHONDONTWRITEBYTECODE=1

KPY=/Applications/KiCad/KiCad.app/Contents/Frameworks/Python.framework/Versions/Current/bin/python3
W=${1:-1920}

echo "-- 1/4  circuit (KiCad)"
# ⛔ THREE BOARDS, AND THE PIPELINE KNEW ABOUT ONE. The optics flex and the taxel
# sheet arrived after this script was written, so every render in the repository
# went on showing a product with a single PCB in it. A render is a claim about a
# design at a moment; a stale one is worse than none, because it looks like
# evidence. tools/check.py now fails when any picture is older than the files it
# depicts, which is what caught this.
#
# ⚠️ The insert board is REBUILT from its committed session file rather than
# regenerated unrouted — generate_pcb.py alone produces a board with no copper
# on it, and rendering that would be its own kind of lie.
./hardware/reroute_from_session.sh 2>/dev/null | tail -1
python3 hardware/generate_board.py optics
python3 hardware/generate_taxels.py
# ⛔ AND THE OPTICS FLEX NEEDED THE SAME TREATMENT, which the paragraph above
# argued for and then did not do. It was regenerated and poured but its routing
# session was never read back, so every run quietly reverted the flex to bare
# copper and 33 unconnected pads — and then rendered it. The taxel sheet needs no
# such step: its copper is generated, not routed.
$KPY hardware/specctra.py import hardware/smartbag_optics.kicad_pcb \
  hardware/smartbag_optics.ses 2>/dev/null | tail -1
$KPY hardware/fill_zones.py hardware/smartbag_optics.kicad_pcb 2>/dev/null | tail -1
$KPY hardware/stitch.py hardware/smartbag_optics.kicad_pcb 2>/dev/null | tail -1

echo "-- 2/4  board renders (KiCad raytracer)"
mkdir -p hardware/render
for v in "pcb_top top 0,0,0 1.9 2400 560" \
         "pcb_bottom top 180,0,0 1.9 2400 560" \
         "pcb_iso top -32,0,-18 1.6 2200 900" \
         "pcb_iso_b top -28,0,26 1.6 2200 900"; do
  set -- $v
  kicad-cli pcb render -o "hardware/render/$1.png" --side "$2" --rotate "$3" \
    --zoom "$4" --width "$5" --height "$6" --quality high --background opaque \
    --perspective --floor hardware/smartbag_core.kicad_pcb >/dev/null 2>&1
  echo "   -> hardware/render/$1.png"
done
for b in optics taxels; do
  kicad-cli pcb render -o "hardware/render/pcb_$b.png" --side top --rotate 0,0,0 \
    --zoom 1.9 --width 2400 --height 560 --quality high --background opaque \
    --perspective --floor "hardware/smartbag_$b.kicad_pcb" >/dev/null 2>&1
  echo "   -> hardware/render/pcb_$b.png"
done

echo "-- 3/4  geometry (CadQuery) + board as GLB"
mkdir -p cad/stl
kicad-cli pcb export glb -f --include-tracks --include-zones --include-pads \
  --include-silkscreen --include-soldermask --subst-models \
  -o cad/stl/smartbag_core.glb hardware/smartbag_core.kicad_pcb 2>&1 | grep -E "created"
for b in optics taxels; do
  kicad-cli pcb export glb -f --include-tracks --include-zones --include-pads \
    --include-silkscreen --include-soldermask --subst-models \
    -o "cad/stl/smartbag_$b.glb" "hardware/smartbag_$b.kicad_pcb" 2>&1 \
    | grep -E "created"
done
python3 cad/bag_and_insert.py

echo "-- 4/4  scenes (Blender EEVEE)"
blender -b --python render/scenes.py -- all --width "$W" 2>&1 \
  | grep -E "DONE|taxels lit"
echo "OK"
