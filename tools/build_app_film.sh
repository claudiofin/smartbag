#!/bin/bash
# The app, in a phone, as a 9:16 film — from the app that actually runs.
#
# ⛔ THE ONE THING THE CG FILMS CANNOT SHOW. This product has nothing to see on
# the outside: no screen, no light, no logo. Everything it does surfaces on a
# phone, so a discovery clip of the bag alone is a clip of a handbag. What has
# to be visible is the RELATIONSHIP — something goes in, and the phone knows.
#
# ⭐ AND IT IS THE REAL APP, NOT A REDRAW. app/film.html puts index.html in an
# iframe 390 px wide, which is what makes it lay itself out as a phone, and
# drives the same SimulatedInsert that encodes real payloads byte for byte and
# the same protocol.js that decodes them. There is one code path. A hand-drawn
# animation of a UI is a promise about software; this is the software.
#
# ⛔ EVERY FRAME IS ADDRESSED BY NUMBER AND REPLAYS THE WHOLE STORY. `?f=42` is
# frame 42 and always shows the same thing, whatever the machine was doing.
# Screenshotting a page that animates on wall-clock time gives frames whose
# content depends on load, which is not a film anybody can rebuild.
#
# ⚠️ One Chrome per frame. It is slower than driving one browser through a
# devtools socket and it cannot go wrong halfway: no shared state between
# frames, and a frame that fails to render fails visibly rather than repeating
# its predecessor.
#
# Usage:  tools/build_app_film.sh [seconds]        (default 12)
set -e
set -o pipefail
cd "$(dirname "$0")/.."

CHROME="${CHROME:-/Applications/Google Chrome.app/Contents/MacOS/Google Chrome}"
[ -x "$CHROME" ] || { echo "no Chrome at $CHROME (set CHROME)"; exit 1; }
command -v ffmpeg >/dev/null || { echo "ffmpeg not found"; exit 1; }

FPS=30
SECONDS_LONG="${1:-12}"
FRAMES=$(( FPS * SECONDS_LONG ))
OUT="render/anim/app_film"
FILM="media/smartbag_app.mp4"
# ⛔ OVER HTTP, NOT file://. app.js is an ES module and Chrome refuses module
# imports across file:// for CORS. The page still loads and the iframe still
# loads — the app inside just never runs and renders its own empty state, which
# is indistinguishable from a bag with nothing in it. Twelve seconds of an empty
# app is how that gets noticed late.
PORT="${PORT:-8731}"
python3 -m http.server "$PORT" --directory app >/dev/null 2>&1 &
SERVER=$!
trap 'kill $SERVER 2>/dev/null' EXIT
sleep 1
curl -sf "http://localhost:$PORT/film.html" >/dev/null \
  || { echo "the local server did not come up on port $PORT"; exit 1; }
APP="http://localhost:$PORT/film.html"

mkdir -p "$OUT" media
echo "== $FRAMES frames at ${FPS} fps =="

for i in $(seq 0 $((FRAMES - 1))); do
  f=$(printf "%04d" "$i")
  [ -f "$OUT/f$f.png" ] && continue
  # ⚠️ --virtual-time-budget is what makes the capture deterministic AND lets
  # the page finish: the iframe has to boot, app.js has to run as a module, and
  # the simulator has to exist before the timeline can touch it. 1200 ms of
  # virtual time costs no wall clock and is far more than that needs.
  "$CHROME" --headless --disable-gpu --hide-scrollbars \
    --force-device-scale-factor=1 --window-size=1080,1920 \
    --virtual-time-budget=1200 \
    --screenshot="$OUT/f$f.png" \
    "$APP?f=$i" >/dev/null 2>&1
  [ -f "$OUT/f$f.png" ] || { echo "frame $i did not render"; exit 1; }
  [ $((i % 30)) -eq 0 ] && echo "   $i/$FRAMES"
done

echo "== encode =="
# ⚠️ yuv420p and an even size, or the file plays on a laptop and not on a phone.
ffmpeg -y -framerate $FPS -i "$OUT/f%04d.png" \
  -c:v libx264 -preset slow -crf 20 -pix_fmt yuv420p \
  -vf "scale=1080:1920:flags=lanczos" \
  -movflags +faststart "$FILM" 2>/dev/null

SZ=$(du -h "$FILM" | cut -f1)
echo "DONE -> $FILM ($SZ, ${SECONDS_LONG}s, 1080x1920)"
