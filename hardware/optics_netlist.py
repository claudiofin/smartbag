#!/usr/bin/env python3
"""The optics flex: what sits in the collar of the bag and looks down into it.

⛔ THIS BOARD IS WHY J1 EXISTS, and until now it did not. The main board has had
a ten-way connector labelled "FFC optics" since the first commit, going nowhere.
Everything on the sensing side of this product — the camera that recognises the
object, the illuminators that let it see in a closed bag, and the time-of-flight
beam that decides when to look at all — lives here, on a strip that is not the
insert board and never was.

⭐ IT CARRIES THE EVENT THE WHOLE STATE MACHINE HANGS ON. SB_EV_TOF_CROSSED is
what arms the camera; U10 is the sensor that raises it. The firmware has assumed
this part since before there was a schematic anywhere in the project.

⚠️ Positions come from dimensions.py — CAMERA_X, LED_X, TOF_X — because the
renders, the CAD and this board have to agree about where the optics are, and
they only do if there is one copy of the numbers.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import dimensions as dim          # noqa: E402

PWR_IN, PWR_OUT, IN, OUT, BIDI, PASSIVE = (
    "power_in", "power_out", "input", "output", "bidirectional", "passive")

# ─── U10: VL53L1X, LGA-12. Pin table from the ST datasheet ───────────────────
# ⚠️ AVDDVCSEL and AVDD are separate supply balls and both need the rail; the
# datasheet's application schematic decouples them together. XSHUT must not be
# driven high before AVDD is up, which is why it is a host GPIO and not a
# pull-up: the main board holds it low until the rail is stable.
U10_PINS = [
    (1,  "AVDDVCSEL", PWR_IN, "VDD_CAM"),
    (2,  "AVSSVCSEL", PWR_IN, "GND"),
    (3,  "GND", PWR_IN, "GND"),
    (4,  "GND2", PWR_IN, "GND"),
    (5,  "XSHUT", IN, "TOF_XSHUT"),
    (6,  "GND3", PWR_IN, "GND"),
    (7,  "GPIO1", OUT, "TOF_INT"),
    (8,  "DNC", PASSIVE, "TOF_DNC"),
    (9,  "SDA", BIDI, "I2C_SDA"),
    (10, "SCL", IN, "I2C_SCL"),
    (11, "AVDD", PWR_IN, "VDD_CAM"),
    (12, "GND4", PWR_IN, "GND"),
]

# ─── J10: the other end of the main board's J1 ───────────────────────────────
# ⚠️ Pin for pin with J1, because it is the same flex. If these two ever
# disagree the cable crosses power into a signal; tools/check.py asserts they
# match rather than trusting that nobody edited one of them.
J10_PINS = [
    (1,  "GND", PWR_IN, "GND"),
    (2,  "VDD", PWR_OUT, "VDD_CAM"),
    (3,  "SCK", PASSIVE, "SPI_SCK"),
    (4,  "MOSI", PASSIVE, "SPI_MOSI"),
    (5,  "MISO", PASSIVE, "SPI_MISO"),
    (6,  "CS", PASSIVE, "CS_CAM"),
    (7,  "SDA", PASSIVE, "I2C_SDA"),
    (8,  "SCL", PASSIVE, "I2C_SCL"),
    (9,  "XSHUT", PASSIVE, "TOF_XSHUT"),
    (10, "TOF_INT", PASSIVE, "TOF_INT"),
    (11, "LED+", PWR_OUT, "VSYS"),
    (12, "LED-", PASSIVE, "IR_LED_K"),
]

# ─── J11: the camera module ──────────────────────────────────────────────────
# ⭐ SIX WAYS, WHICH IS THE WHOLE INTERFACE. The Arducam Mega's own
# documentation: "we removed two I2C interfaces and now only 6 pin left, 4 for
# SPI, 2 for power." The module is bought, not built — it arrives with a lens
# and its own board — so what this flex owes it is a connector and a rail that
# can be switched off between bursts.
J11_PINS = [
    (1, "VCC", PWR_OUT, "VDD_CAM"),
    (2, "GND", PWR_IN, "GND"),
    (3, "SCK", PASSIVE, "SPI_SCK"),
    (4, "MISO", PASSIVE, "SPI_MISO"),
    (5, "MOSI", PASSIVE, "SPI_MOSI"),
    (6, "CS", PASSIVE, "CS_CAM"),
]

_2 = lambda a, b: [(1, "A", PASSIVE, a), (2, "K", PASSIVE, b)]   # noqa: E731

# ⛔ FOUR LEDS IN PARALLEL, NOT TWO PAIRS IN SERIES. A LiPo runs 3.0 to 4.2 V and
# two VSMY1850 in series need 3.3 V before any current flows at all — the
# illuminators would go out at half charge and nobody would know why except that
# recognition got worse. Parallel with a resistor each works across the whole
# discharge.
#
# ⚠️ AND IT IS NOT A CONSTANT CURRENT. 51 ohm gives 40 mA at 3.7 V, 49 mA at a
# full 4.2 V and 27 mA at 3.0 V: the scene gets dimmer as the cell empties, by
# nearly a factor of two. ml/render_dataset.py renders its training set at ONE
# brightness. Either the exposure compensates, or the recognition sees a
# different world at 20% charge than the one it was trained on. A current sink
# would fix it and costs a part; this is recorded rather than hidden.
LED_R = 51.0

PARTS = [
    ("U10", "VL53L1X", "VL53L1X", "Sensor_Distance", "ST_VL53L1x",
     U10_PINS, dim.TOF_X, 0.0),
    ("J10", "FFC to insert, 12 way", "FFC_12", "Connector_FFC-FPC",
     "Hirose_FH12-12S-0.5SH_1x12-1MP_P0.50mm_Horizontal", J10_PINS, 58.0, 0.0),
    ("J11", "camera module, 6 way", "CONN6", "Connector_JST",
     "JST_SH_SM06B-SRSS-TB_1x06-1MP_P1.00mm_Horizontal",
     J11_PINS, dim.CAMERA_X, 0.0),
]
for _i, _x in enumerate(dim.LED_X):
    PARTS.append((f"D{_i + 1}", "VSMY1850X01 850nm", "LED", "LED_SMD",
                  "LED_0805_2012Metric", _2("VSYS", f"LED{_i + 1}_K"), _x, -3.0))
    PARTS.append((f"R{_i + 1}", f"{LED_R:.0f}R 1%", "R", "Resistor_SMD",
                  "R_0603_1608Metric", _2(f"LED{_i + 1}_K", "IR_LED_K"),
                  _x, 0.5))
PARTS += [
    ("C1", "100n X7R", "C", "Capacitor_SMD", "C_0402_1005Metric",
     _2("VDD_CAM", "GND"), dim.TOF_X - 3.0, -3.0),
    ("C2", "4u7 X5R 10V", "C", "Capacitor_SMD", "C_0402_1005Metric",
     _2("VDD_CAM", "GND"), dim.TOF_X + 3.0, -3.0),
    ("FID1", "fiducial", "FIDUCIAL", "Fiducial", "Fiducial_1mm_Mask2mm",
     [], -58.0, 4.0),
    ("FID2", "fiducial", "FIDUCIAL", "Fiducial", "Fiducial_1mm_Mask2mm",
     [], 69.0, 0.0),
]

POWER_FLAGS = ["GND", "VSYS", "VDD_CAM", "SPI_SCK", "SPI_MOSI", "SPI_MISO",
               "CS_CAM", "I2C_SDA", "I2C_SCL", "TOF_XSHUT", "IR_LED_K"]
SINGLE_PIN_NETS = ["TOF_DNC"]
NOT_IN_BOM = {"FID1", "FID2"}

# ⚠️ 12 mm tall and 124 long: it lies along the collar of the bag, above the
# mouth, which is why nothing on it may be more than a few millimetres high.
# ⚠️ 134 mm, not 128. The right end grew to make room for a fiducial that kept
# landing inside the 12-way connector's courtyard — a placement machine needs a
# reference it can see, and a target under a connector body is not one.
OUTLINE = [(-62, -6), (72, -6), (72, 6), (-62, 6)]


def nets():
    out = {}
    for ref, _v, _s, _fl, _fp, pins, _x, _y in PARTS:
        for number, _name, etype, net in pins:
            out.setdefault(net, []).append((ref, number, etype))
    return out


def part(ref):
    return [p for p in PARTS if p[0] == ref][0]


def pad_nets(ref):
    return {str(number): net for number, _n, _t, net in part(ref)[5]}


def symbols():
    out = {}
    for _r, _v, sym, _fl, _fp, pins, _x, _y in PARTS:
        out.setdefault(sym, pins)
    return out
