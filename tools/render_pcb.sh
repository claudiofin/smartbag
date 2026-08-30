#!/bin/bash
# Board renders, using KiCad's raytracer.
# ⭐ Zones have to be filled FIRST (hardware/fill_zones.py): kicad-cli draws
# whatever it finds in the file, it does not recompute the copper.
set -e
cd "$(dirname "$0")/.."
P=hardware/smartbag_core.kicad_pcb
O=hardware/render
KPY=/Applications/KiCad/KiCad.app/Contents/Frameworks/Python.framework/Versions/Current/bin/python3
mkdir -p "$O"

python3 hardware/generate_pcb.py
$KPY hardware/fill_zones.py $P 2>/dev/null | tail -1

r() { # name, side, rotation, zoom, width, height
  kicad-cli pcb render -o "$O/$1.png" --side "$2" --rotate "$3" --zoom "$4" \
    --width "$5" --height "$6" --quality high --background opaque \
    --perspective --floor "$P" >/dev/null 2>&1
  echo "  -> $O/$1.png"
}
r pcb_top     top 0,0,0       1.9 2400 560
r pcb_bottom  top 180,0,0     1.9 2400 560
r pcb_iso     top -32,0,-18   1.6 2200 900
r pcb_iso_b   top -28,0,26    1.6 2200 900
echo "DONE -> $O"
