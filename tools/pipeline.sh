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
KPY=/Applications/KiCad/KiCad.app/Contents/Frameworks/Python.framework/Versions/Current/bin/python3
W=${1:-1920}

echo "-- 1/4  circuit (KiCad)"
python3 hardware/generate_pcb.py
$KPY hardware/fill_zones.py hardware/smartbag_core.kicad_pcb 2>/dev/null | tail -1

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

echo "-- 3/4  geometry (CadQuery) + board as GLB"
mkdir -p cad/stl
kicad-cli pcb export glb -f --include-tracks --include-zones --include-pads \
  --include-silkscreen --include-soldermask --subst-models \
  -o cad/stl/smartbag_core.glb hardware/smartbag_core.kicad_pcb 2>&1 | grep -E "created"
python3 cad/bag_and_insert.py

echo "-- 4/4  scenes (Blender EEVEE)"
blender -b --python render/scenes.py -- all --width "$W" 2>&1 \
  | grep -E "DONE|taxels lit"
echo "OK"
