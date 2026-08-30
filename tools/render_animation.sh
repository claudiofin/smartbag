#!/bin/bash
# Renders the shots for both films. ~2 s per frame on the reference machine.
# `scanning` is shared: rendered once, assembled into both films.
set -e
cd "$(dirname "$0")/.."
W=${1:-1600}
for shot in ${2:-opening exploded scanning unzip object_drop}; do
  blender -b --python render/animation.py -- $shot --width "$W" 2>&1 \
    | grep -E "^-- shot|DONE|taxels lit"
done
