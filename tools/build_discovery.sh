#!/bin/bash
# The 9:16 clip for Kickstarter's discovery feed.
#
# ⛔ 9:16 IS NOT A CROP OF 16:9. Cutting the ends off a landscape shot of a
# 276 mm bag gives you the middle of a bag, and every frame of it looks like a
# mistake. render/animation.py renders the shots again with the frame turned on
# its side and the lens corrected — Blender fits the sensor to the larger
# dimension, so turning the frame already widens the horizontal field and the
# correction is to zoom back IN until the bag spans the width.
#
# ⭐ NO CAPTIONS. The other two films explain; this one has about eleven seconds
# in a feed, with the sound off, next to something else. What it has to do is be
# recognisably a handbag and then be recognisably not just a handbag.
set -e
set -o pipefail
cd "$(dirname "$0")/.."

OUT=media/smartbag_discovery.mp4
LIST=$(mktemp)
for shot in unzip object_drop; do
  for f in render/anim/${shot}_v/f*.png; do echo "file '$PWD/$f'"; done
done > "$LIST"

# ⚠️ yuv420p and even dimensions, or half the phones that see this will not
# decode it. 1080x1920 is exactly 9:16 and needs no padding.
ffmpeg -y -r 24 -f concat -safe 0 -i "$LIST" \
  -vf "scale=1080:1920:force_original_aspect_ratio=decrease,pad=1080:1920:(ow-iw)/2:(oh-ih)/2" \
  -c:v libx264 -pix_fmt yuv420p -crf 20 -movflags +faststart "$OUT" \
  2>&1 | tail -2
rm -f "$LIST"
ls -l "$OUT" | awk '{print "  " $NF, int($5/1024) "KB"}'
