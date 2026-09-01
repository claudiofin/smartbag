#!/bin/bash
# Build the target image for the nRF54L15.
#
# ⭐ THIS SCRIPT IS THE DIFFERENCE BETWEEN "written against the API" AND "builds".
# Everything under firmware/target was written without a compiler for a while and
# the README said so; four things were wrong and every one of them was the kind
# only a build finds:
#
#   - the board's devicetree gives spi00 a sleep pinctrl state as well as a
#     default, so an overlay naming one state leaves pinctrl-1 unnamed;
#   - on nRF54L15 the peripheral instances are SHARED — SPI20, TWIM20 and
#     UARTE20 are one block — and the DK's console sits on uart20, so the I2C
#     bus had to move to instance 21;
#   - nordic,npm1300-charger is a binding under dts/bindings/SENSOR in this
#     tree, so Zephyr's charger API compiles and does not link;
#   - a designated initialiser for spi_config's cs field needs braces.
#
# ⚠️ It builds for the nRF54L15 DK, which is the same silicon as the SmartBag
# board and can be bought today. boards/smartbag.overlay carries this board's pin
# map onto it. A production build wants real board files, which want the board.
#
# Usage:  tools/build_firmware.sh [build dir]
set -e
set -o pipefail
cd "$(dirname "$0")/.."

: "${ZEPHYR_BASE:=$HOME/zephyrproject/zephyr}"
: "${ZEPHYR_SDK_INSTALL_DIR:=$HOME/zephyr-sdk-1.0.1}"
export ZEPHYR_BASE ZEPHYR_SDK_INSTALL_DIR
export ZEPHYR_TOOLCHAIN_VARIANT=zephyr

BUILD="${1:-build/target}"

if [ ! -d "$ZEPHYR_BASE" ]; then
  echo "no Zephyr at $ZEPHYR_BASE — set ZEPHYR_BASE" >&2
  exit 2
fi

# ⛔ The pin map is generated from the netlist and must be current BEFORE the
# compiler reads it. Building against a stale one would produce an image that
# addresses the pins the schematic used to have.
python3 hardware/generate_pinmap.py | tail -1

cmake -B "$BUILD" -GNinja -DBOARD=nrf54l15dk/nrf54l15/cpuapp \
  -DDTC_OVERLAY_FILE=boards/smartbag.overlay firmware/target > /dev/null
ninja -C "$BUILD" | tail -6
