#!/usr/bin/env python3
"""Real parts, with the places the design does not survive contact with them.

⛔ WHAT THIS FILE IS FOR. netlist.py names component *classes* — "SoC+NPU BLE
5.4", "mmWave 60GHz TRX" — and picks a package that looks plausible for each.
That is how the whole board was drawn, and it is a comfortable way to be wrong:
a footprint invented to fit an idea always fits. This file goes the other way.
Every entry below is a part you can buy, its package comes from its own
datasheet, and `verdict` says whether the board as drawn can accept it.

⭐ THE POINT IS THE MISMATCHES. Three of them change the design rather than the
layout, and one of them dissolves a problem the RF work had already proved was
fatal. They are the reason this is worth more than a price list.

⚠️ Prices and stock are indicative and were true when written (2026-08-30), not
guaranteed. Where a figure was not verified it is None, and the report says so
rather than filling it in.

Datasheets that could be fetched are archived under hardware/datasheets/ and
named in `pdf`; the rest are linked. Vendors that block scripted downloads
(Mouser, LCSC, Hirose) are marked `pdf=None` — a link is not an archive and is
not pretended to be one.
"""

# fields: mpn, manufacturer, description, package, body (x, y, z) mm, pitch,
#         pins, datasheet url, local pdf, usd, verdict
PART = dict

BOM = {
    "U1": PART(
        mpn="NRF54LM20B-QGAA-R7",
        manufacturer="Nordic Semiconductor",
        description="Cortex-M33 wireless SoC, Bluetooth LE, Axon NPU, 512 kB RAM",
        package="QFN52", body=(6.0, 6.0, 0.85), pitch=0.4, pins=52,
        datasheet="https://www.nordicsemi.com/Products/nRF54LM20B",
        pdf=None, usd=None, stock="DigiKey lists it; not priced here",
        verdict="MISMATCH: footprint is QFN-48 6x6. Right family, right body, "
                "four pins out. ⛔ And the harder problem is the pin budget: "
                "this part has 32 GPIO and the design asks for 46 signals, 22 "
                "of them the FSR matrix alone. Either the matrix is "
                "multiplexed through an external driver or U1 splits in two.",
        alternatives=[
            "NRF54L15-QFAA-R — QFN48 6x6 0.4 mm, an EXACT footprint match "
            "(LCSC C42458750, $3.99/1, $2.72/100, out of stock 2026-08-30), "
            "but no NPU and no camera interface. Fits the board; does not do "
            "the job the board was drawn for.",
        ],
    ),
    "U2": PART(
        mpn="A121-001-T&R",
        manufacturer="Acconeer",
        description="60 GHz pulsed coherent radar, antenna in package, SPI",
        package="fcCSP50", body=(5.2, 5.5, 0.88), pitch=0.5, pins=50,
        datasheet="https://developer.acconeer.com/download/a121-datasheet",
        pdf="A121_acconeer.pdf", usd=None,
        stock="distributor stock not verified",
        verdict="⛔ MISMATCH, AND IT DISSOLVES THE RF PROBLEM. The footprint is "
                "a QFN-40 5x5 with TX_A1/TX_A2/RX_A1/RX_A2 antenna ports. The "
                "real part is a 50-ball fcCSP and its datasheet says, in so "
                "many words, that the antenna is in the package and 'it is not "
                "possible to connect trace antenna'. So the 88 mm feed that "
                "rf/feed_loss.py priced at 8.2 dB one way does not exist in a "
                "real design — because a real 60 GHz part is placed where its "
                "antenna has to be. That is option one from feed_loss.py, "
                "arrived at by the silicon rather than by choice, and it "
                "deletes ANT_A1 and ANT_A2 from the netlist entirely.",
    ),
    "U3": PART(
        mpn="NPM1300-QEAA-R7",
        manufacturer="Nordic Semiconductor",
        description="PMIC: 800 mA charger with NTC/JEITA, fuel gauge, 2 bucks, 2 LDOs",
        package="QFN32", body=(5.0, 5.0, 0.9), pitch=0.5, pins=32,
        datasheet="https://download.mikroe.com/documents/datasheets/nPM1300_datasheet.pdf",
        pdf="nPM1300_nordic.pdf", usd=1.66,
        stock="LCSC C7501206, $1.75/1, $1.66/100, OUT OF STOCK 2026-08-30; "
              "LCSC lists the package as QFN-32-EP(5x5), which confirms it",
        verdict="MISMATCH: footprint is QFN-24 4x4. ⭐ Worth the change anyway — "
                "this part has a battery NTC input and JEITA charge control, "
                "which is the missing piece thermal/budget.py identified: the "
                "cell reaches ~60 C on a 5 W charge and the fix is to throttle "
                "on cell temperature. The board had no thermistor because the "
                "invented PMIC had nowhere to put one.",
    ),
    "U4": PART(
        mpn="BMI270",
        manufacturer="Bosch Sensortec",
        description="6-axis IMU, 14-pin LGA",
        package="LGA-14", body=(2.5, 3.0, 0.83), pitch=0.5, pins=14,
        datasheet="https://www.bosch-sensortec.com/media/boschsensortec/downloads/datasheets/bst-bmi270-ds000.pdf",
        pdf="BMI270_bosch.pdf", usd=None,
        stock="commodity, widely stocked",
        verdict="OK — the footprint is Bosch_LGA-14_3x2.5mm_P0.5mm and the "
                "datasheet says 2.5 x 3.0 mm, 14 pins, 0.83 mm high. Exact.",
    ),
    "U5": PART(
        mpn="DRV5032FBDBZR",
        manufacturer="Texas Instruments",
        description="Omnipolar digital Hall latch, 1.65-5.5 V, ~540 nA average",
        package="SOT-23-3", body=(2.92, 2.37, 1.12), pitch=0.95, pins=3,
        datasheet="https://www.ti.com/lit/ds/symlink/drv5032.pdf",
        pdf="DRV5032_ti.pdf", usd=None,
        stock="commodity, widely stocked",
        verdict="OK — SOT-23 3-pin, 2.92 x 2.37 mm. The footprint is SOT-23.",
    ),
    "Y1": PART(
        mpn="ABM8-32.000MHZ-B2-T",
        manufacturer="Abracon",
        description="32 MHz crystal, 3.2 x 2.5 mm, 4-pad SMD",
        package="SMD-3225-4", body=(3.2, 2.5, 0.8), pitch=None, pins=4,
        datasheet="https://abracon.com/Resonators/ABM8.pdf",
        pdf=None, usd=None,
        verdict="OK — 3225 4-pad is the footprint used. ⚠️ Load capacitance has "
                "to match the SoC's oscillator; not checked here.",
    ),
    "J1": PART(
        mpn="FH12-10S-0.5SH(55)", manufacturer="Hirose",
        description="FFC/FPC connector, 10 way, 0.5 mm pitch, horizontal, bottom contact",
        package="FH12-10S", body=(9.4, 4.3, 1.0), pitch=0.5, pins=10,
        datasheet="https://www.hirose.com/product/p/CL0580-1163-2-55",
        pdf=None, usd=None,
        verdict="OK — the footprint is named for this exact part.",
    ),
    "J4": PART(
        mpn="FH12-24S-0.5SH(55)", manufacturer="Hirose",
        description="FFC/FPC connector, 24 way, 0.5 mm pitch, horizontal",
        package="FH12-24S", body=(16.4, 4.3, 1.0), pitch=0.5, pins=24,
        datasheet="https://www.hirose.com/product/p/CL0580-1173-6-55",
        pdf=None, usd=None,
        verdict="OK — 23 of 24 ways used: 16 columns, 6 rows, one ground.",
    ),
    "J2": PART(
        mpn="SM02B-SRSS-TB(LF)(SN)", manufacturer="JST",
        description="SH series 2-pin 1.0 mm header, top entry — battery",
        package="JST-SH-02", body=(4.25, 2.9, 2.9), pitch=1.0, pins=2,
        datasheet="https://www.jst.com/wp-content/uploads/2021/01/eSH1.pdf",
        pdf=None, usd=None,
        verdict="OK. ⚠️ 1 A of charge current through an SH contact is close to "
                "its 1 A rating; a 2 mm PH series would be the safer choice if "
                "the 5 W charge path survives the thermal review.",
    ),
    "J3": PART(
        mpn="SM02B-SRSS-TB(LF)(SN)", manufacturer="JST",
        description="SH series 2-pin 1.0 mm header — Qi coil",
        package="JST-SH-02", body=(4.25, 2.9, 2.9), pitch=1.0, pins=2,
        datasheet="https://www.jst.com/wp-content/uploads/2021/01/eSH1.pdf",
        pdf=None, usd=None, verdict="OK.",
    ),
    "J5": PART(
        mpn="SM04B-SRSS-TB(LF)(SN)", manufacturer="JST",
        description="SH series 4-pin 1.0 mm header — SWD",
        package="JST-SH-04", body=(6.25, 2.9, 2.9), pitch=1.0, pins=4,
        datasheet="https://www.jst.com/wp-content/uploads/2021/01/eSH1.pdf",
        pdf=None, usd=None, verdict="OK.",
    ),
    "AE1": PART(
        mpn="2450AT43F0100E", manufacturer="Johanson Technology",
        description="2.4 GHz ceramic chip antenna, 3.2 x 1.6 x 1.3 mm",
        package="0402-style chip", body=(3.2, 1.6, 1.3), pitch=None, pins=2,
        datasheet="https://www.johansontechnology.com/datasheets/2450AT43F0100/2450AT43F0100.pdf",
        pdf=None, usd=None,
        verdict="OK as a part. ⛔ But its 50 ohm feed is 1.4 mm wide on this "
                "0.6 mm stack (rf/feed_loss.py), and the router could not fit "
                "that across 26 mm of a 20 mm-tall board without pushing other "
                "nets out. BLE_ANT is one of the pads still unconnected, and "
                "the honest reading is that the antenna is in the wrong place, "
                "not that the trace is hard to draw.",
    ),
}

# ── passives ─────────────────────────────────────────────────────────────────
# ⚠️ Generic on purpose. A 100 nF 0402 X7R is a commodity; naming one
# manufacturer's part would imply a selection that was never made. What DOES
# need choosing is the dielectric and the voltage rating, so those are here.
PASSIVES = {
    "C_100n": ("100 nF ±10% X7R 16 V", "0402", ["C1", "C2", "C5"]),
    "C_1u":   ("1 µF ±10% X5R 10 V", "0402", ["C4"]),
    "C_4u7":  ("4.7 µF ±20% X5R 10 V", "0402", ["C3"]),
    "C_10u":  ("10 µF ±20% X5R 6.3 V", "0402", ["C6"]),
    "C_22u":  ("22 µF ±20% X5R 6.3 V", "0402", ["C7", "C8"]),
    "R_10k":  ("10 kΩ ±1% 1/16 W", "0402", ["R1", "R2", "R3"]),
    "R_100k": ("100 kΩ ±1% 1/16 W", "0402", ["R4"]),
    "L_2u2":  ("2.2 µH ≥1.2 A Isat shielded", "0603", ["L1"]),
    "L_1u0":  ("1.0 µH ≥1.2 A Isat shielded", "0603", ["L2"]),
}

# ⛔ Parts the design needs and the board does not have. Each one is a
# consequence of something measured elsewhere in this repo, not a wish list.
MISSING = [
    ("cell NTC thermistor, 10 kΩ B=3380", "thermal/budget.py puts the cell near "
     "60 C on a 5 W charge against a 45 C limit. The nPM1300 has the input; "
     "there is no thermistor on the board to connect to it."),
    ("transimpedance front end for the FSR rows (6 channels, or 1 + a mux)",
     "firmware/test_sb_fsr.c measures the two scan modes this board can run: "
     "one invents phantom taxels at 39% of a real press, the other reads real "
     "ones 83% light. Rows at virtual ground are exact and need an amplifier."),
    ("a second processor, or an external FSR driver",
     "the NPU part has 32 GPIO and the design asks for 46."),
    ("camera interface", "no BLE+NPU SoC in a QFN offers one; the image path "
     "needs either an SPI camera module or a different processor."),
]
