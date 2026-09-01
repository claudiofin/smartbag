# The target build

The nRF Connect SDK application: nine HAL functions, a `main()` that hands them
to the logic, and a devicetree that says which pin is which.

## ✅ It builds

```
FLASH:  173288 B   1524 KB   11.10%
RAM:     43662 B    256 KB   16.66%
```

`tools/build_firmware.sh` produces `zephyr.hex`, and `tools/verify.sh` runs it.

⛔ **It was written against the API for a while and four things were wrong** —
each of them the kind only a compiler finds:

| | |
|---|---|
| the board gives `spi00` a **sleep** pinctrl state as well as a default | an overlay naming one state leaves `pinctrl-1` unnamed, and the build stops |
| on nRF54L15 the peripheral **instances are shared** — SPI20, TWIM20 and UARTE20 are one block | the DK's console is on `uart20`, so the I²C bus had to move to instance 21. On the SmartBag board, which has no console UART, 20 would have been free — and this would have been found on silicon |
| `nordic,npm1300-charger` is a binding under `dts/bindings/`**`sensor`** | Zephyr's charger API compiles and does not link. It is `sensor_attr_set()` — and the attribute that sets a current is the **VBUS input limit**, which is what the policy actually constrains |
| `spi_config`'s `cs` field | needs braces |

Say what is still true:

| | |
|---|---|
| the logic below the HAL | **378 host assertions**, `-Werror`, and it is the *same source files* this build compiles — not a copy |
| `src/sb_pinmap.h` | **generated** from `hardware/netlist.py`, and compiled with `-Werror` by `tools/check.py` on every run |
| `boards/smartbag.overlay` | **generated** from the netlist and the cell's datasheet, checked for drift the same way |
| `src/sb_hal_zephyr.c`, `src/npm1300.c`, `src/gatt.c`, `src/main.c` | **built, never run.** It links and fits; nothing has met silicon |

## Building it

The board is a custom nRF54L15. Until its board files exist, the overlay targets
the **nRF54L15 DK**, which is the same silicon and can be bought today:

```bash
west build -b nrf54l15dk/nrf54l15/cpuapp firmware/target -- -DDTC_OVERLAY_FILE=boards/smartbag.overlay
```

```bash
west flash
```

## What is in each file

| | |
|---|---|
| `src/main.c` | deliberately short and with nothing to test in it. Every decision the bag makes lives in `../smartbag.c`, `../sb_power.c`, `../sb_sensors.c`, `../sb_fsr.c` — if a rule appears here it has escaped from somewhere it could be checked |
| `src/sb_hal_zephyr.c` | the nine functions `../sb_hal.h` declares. GPIO, SPI with GPIO chip selects, I²C, SAADC, and the multiplexer |
| `src/npm1300.c` | the charger, through **Nordic's driver** and not through register addresses recalled from memory. The JEITA thresholds are devicetree; what is left for C is turning a decision into a current limit |
| `src/sb_pinmap.h` | generated — do not edit |
| `boards/smartbag.overlay` | generated — do not edit |

## What is still missing

- **Board files.** `boards/smartbag.overlay` overlays a DK. A production build
  wants a real board definition, which needs the board to exist first.
- **The sensing loop.** `src/gatt.c` reports the ledger with every position at
  confidence zero — a compartment and no point — because the points come from a
  radar sweep and nothing on the target runs one yet. Both ends were written for
  that state: `sb_ble.c` encodes it and `app/app.js` draws it as a tinted third
  of the bag. It is the honest answer until the sweep exists.
- **A fuel gauge.** `sb_pmic_battery_pct()` maps cell voltage linearly between
  3.0 and 4.2 V, which is wrong in the middle of a lithium discharge curve. A
  product wants Nordic's fuel gauge library and a discharge table for this cell.

## Why the pin map is generated

Routing moved the whole P2 block: signals that had to travel east were on the
package's west edge, which cost sixteen unconnected pads. That was a cheap change
**only because the firmware addresses pins through symbolic ids** — `SB_PIN_HALL`,
not `P0.03`. This header is where those ids become silicon, and it is written by
`hardware/generate_pinmap.py` from the same netlist the copper comes from.

⛔ Edit it by hand and the board and the image disagree, silently, and the only
symptom is a peripheral that does not answer. `tools/check.py` regenerates it on
every run and fails if anything moved.
