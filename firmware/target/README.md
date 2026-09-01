# The target build

The nRF Connect SDK application: nine HAL functions, a `main()` that hands them
to the logic, and a devicetree that says which pin is which.

## ⚠️ This has not been compiled

There is no nRF Connect SDK and no ARM toolchain on the machine this was written
on. Every file here is written **against the Zephyr API rather than against a
compiler**, and the first `west build` will find things. Say what is true:

| | |
|---|---|
| the logic below the HAL | **378 host assertions**, `-Werror`, and it is the *same source files* this build compiles — not a copy |
| `src/sb_pinmap.h` | **generated** from `hardware/netlist.py`, and compiled with `-Werror` by `tools/check.py` on every run |
| `boards/smartbag.overlay` | **generated** from the netlist and the cell's datasheet, checked for drift the same way |
| `src/sb_hal_zephyr.c`, `src/npm1300.c`, `src/main.c` | **never built.** The arrangement is sound; the spelling of the API calls is where the bugs will be |

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

## Two things that are still missing

- **The GATT service.** `../sb_ble.c` produces the bytes and `app/protocol.js`
  decodes the same bytes under 15 tests, but nothing here registers a service
  and hands them to a characteristic. That is the one part of the firmware the
  host tests cannot stand in for.
- **Board files.** `boards/smartbag.overlay` overlays a DK. A production build
  wants a real board definition, which needs the board to exist first.

## Why the pin map is generated

Routing moved the whole P2 block: signals that had to travel east were on the
package's west edge, which cost sixteen unconnected pads. That was a cheap change
**only because the firmware addresses pins through symbolic ids** — `SB_PIN_HALL`,
not `P0.03`. This header is where those ids become silicon, and it is written by
`hardware/generate_pinmap.py` from the same netlist the copper comes from.

⛔ Edit it by hand and the board and the image disagree, silently, and the only
symptom is a peripheral that does not answer. `tools/check.py` regenerates it on
every run and fails if anything moved.
