#!/usr/bin/env python3
"""Real parts, with the places the design does not survive contact with them.

⛔ WHAT THIS FILE IS FOR. netlist.py names component *classes* — "SoC+NPU BLE
5.4", "mmWave 60GHz TRX" — and picks a package that looks plausible for each.
That is how the whole board was drawn, and it is a comfortable way to be wrong:
a footprint invented to fit an idea always fits. This file goes the other way.
Every entry below is a part you can buy, its package comes from its own
datasheet, and `verdict` says whether the board as drawn can accept it.

⭐ THE MISMATCHES ARE GONE, BECAUSE THE BOARD CHANGED TO MEET THEM. This file
used to report three parts the board could not accept: an invented QFN for a
60 GHz transceiver that does not exist in that package, a QFN-24 for a PMIC that
is QFN-32, and a processor with an NPU that has no camera interface. All three
findings were acted on rather than annotated — see hardware/netlist.py — and the
board now carries the parts named here. What the file still does is check, every
run, that it still does.

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
        mpn="NRF54L15-QFAA-R",
        manufacturer="Nordic Semiconductor",
        description="Cortex-M33 wireless SoC, Bluetooth LE, 1.5 MB NVM, 256 kB RAM",
        package="QFN48", body=(6.0, 6.0, 0.85), pitch=0.4, pins=48,
        datasheet="https://www.nordicsemi.com/Products/nRF54L15",
        pdf="nRF54L15_nordic.pdf", usd=2.72,
        stock="LCSC C42458750, $3.99/1, $2.72/100, out of stock 2026-08-30",
        verdict="OK — QFN48 6x6 0.4 mm, and the pin assignment comes from "
                "figure 173 of the datasheet rather than from an idea of what a "
                "processor ought to look like. ⚠️ It has NO NPU: recognition "
                "runs on the M33. That is survivable only because the firmware "
                "already waits 2 s for the object to settle before measuring, "
                "so inference happens inside a window that existed anyway.",
    ),
    "U2": PART(
        mpn="A121-001-T&R",
        manufacturer="Acconeer",
        description="60 GHz pulsed coherent radar, antenna in package, SPI",
        package="fcCSP50", body=(5.2, 5.5, 0.88), pitch=0.5, pins=50,
        datasheet="https://developer.acconeer.com/download/a121-datasheet",
        pdf="A121_acconeer.pdf", usd=None,
        stock="distributor stock not verified",
        verdict="OK — the footprint is generated ball by ball from the pin "
                "tables on pages 8-9. ⭐ This part is why there are two radars "
                "and no 60 GHz copper: its antenna is inside the package and "
                "the datasheet says a trace antenna cannot be connected, so the "
                "sensor goes where its antenna has to be.",
    ),
    "U6": PART(
        mpn="A121-001-T&R",
        manufacturer="Acconeer",
        description="60 GHz radar, second viewpoint at the other end of the insert",
        package="fcCSP50", body=(5.2, 5.5, 0.88), pitch=0.5, pins=50,
        datasheet="https://developer.acconeer.com/download/a121-datasheet",
        pdf="A121_acconeer.pdf", usd=None,
        stock="distributor stock not verified",
        verdict="OK — identical to U2. ⚠️ Two of its fifty balls are fully "
                "surrounded, so they carry via-in-pad; see the fabrication "
                "note, because those holes have to be filled and capped.",
    ),
    "U3": PART(
        mpn="NPM1300-QEAA-R7",
        manufacturer="Nordic Semiconductor",
        description="PMIC: 800 mA charger with NTC/JEITA, fuel gauge, 2 bucks, 2 LDOs",
        package="QFN32", body=(5.0, 5.0, 0.9), pitch=0.5, pins=32,
        datasheet="https://download.mikroe.com/documents/datasheets/nPM1300_datasheet.pdf",
        pdf="nPM1300_nordic.pdf", usd=1.66,
        stock="LCSC C7501206, $1.75/1, $1.66/100, out of stock 2026-08-30",
        verdict="OK — QFN32 5x5, pin table page 150. ⭐ RT1 hangs off its NTC "
                "input, which is the answer thermal/budget.py asked for: the "
                "charge current has to be a function of cell temperature, and "
                "this part does that in hardware.",
    ),
    "U4": PART(
        mpn="BMI270", manufacturer="Bosch Sensortec",
        description="6-axis IMU, 14-pin LGA, I2C",
        package="LGA-14", body=(2.5, 3.0, 0.83), pitch=0.5, pins=14,
        datasheet="https://www.bosch-sensortec.com/media/boschsensortec/downloads/datasheets/bst-bmi270-ds000.pdf",
        pdf="BMI270_bosch.pdf", usd=None, stock="commodity, widely stocked",
        verdict="OK — CSB to VDDIO selects I2C and SDO to ground picks the low "
                "address, both on the datasheet's instruction (7.2.3).",
    ),
    "U5": PART(
        mpn="DRV5032FBDBZR", manufacturer="Texas Instruments",
        description="Omnipolar digital Hall latch, 1.65-5.5 V, ~540 nA average",
        package="SOT-23-3", body=(2.92, 2.37, 1.12), pitch=0.95, pins=3,
        datasheet="https://www.ti.com/lit/ds/symlink/drv5032.pdf",
        pdf="DRV5032_ti.pdf", usd=None, stock="commodity, widely stocked",
        verdict="OK — the sentinel that arms everything else. 540 nA is what "
                "lets the rest of the board sleep.",
    ),
    "U7": PART(
        mpn="CD74HC4067SM96", manufacturer="Texas Instruments",
        description="16:1 analog multiplexer, the FSR column selector",
        package="SSOP-24", body=(5.3, 8.2, 2.0), pitch=0.65, pins=24,
        datasheet="https://www.ti.com/lit/ds/symlink/cd74hc4067.pdf",
        pdf="CD74HC4067_ti.pdf", usd=None, stock="commodity",
        verdict="OK. ⛔ The first transcription of this pinout was wrong in "
                "almost every position and invented a VEE pin the package does "
                "not have; tools/check.py caught it by noticing channel 0 "
                "existed nowhere. It is now figure 4-1 of SCHS209D.",
    ),
    "U8": PART(
        mpn="TLV9064IPWR", manufacturer="Texas Instruments",
        description="Quad RRIO op-amp, 1.8-5.5 V — four of the six taxel amplifiers",
        package="TSSOP-14", body=(4.4, 5.0, 1.2), pitch=0.65, pins=14,
        datasheet="https://www.ti.com/lit/ds/symlink/tlv9064.pdf",
        pdf=None, usd=None, stock="commodity",
        verdict="OK. ⭐ These exist because firmware/test_sb_fsr.c measured what "
                "the matrix does without them: phantom taxels at 39% of a real "
                "press, or real ones read 83% light.",
    ),
    "U9": PART(
        mpn="TLV9064IPWR", manufacturer="Texas Instruments",
        description="Quad RRIO op-amp — the remaining two amplifiers",
        package="TSSOP-14", body=(4.4, 5.0, 1.2), pitch=0.65, pins=14,
        datasheet="https://www.ti.com/lit/ds/symlink/tlv9064.pdf",
        pdf=None, usd=None, stock="commodity",
        verdict="OK — its two spare channels are wired as unity-gain followers "
                "at VREF rather than left floating.",
    ),
    "Y1": PART(
        mpn="ABM8-32.000MHZ-B2-T", manufacturer="Abracon",
        description="32 MHz crystal, Cl = 8 pF — the SoC's HFXO",
        package="SMD-2016-4", body=(2.0, 1.6, 0.5), pitch=None, pins=4,
        datasheet="https://abracon.com/Resonators/ABM8.pdf",
        pdf=None, usd=None, stock="commodity",
        verdict="OK — 2016 4-pad, and the load capacitance is Nordic's "
                "(table 87), not a guess.",
    ),
    "Y2": PART(
        mpn="ABM8-24.000MHZ-B2-T", manufacturer="Abracon",
        description="24 MHz crystal for the first radar",
        package="SMD-2016-4", body=(2.0, 1.6, 0.5), pitch=None, pins=4,
        datasheet="https://abracon.com/Resonators/ABM8.pdf",
        pdf=None, usd=None, stock="commodity",
        verdict="OK. ⚠️ One crystal PER SENSOR — the A121 has an oscillator, not "
                "a clock input, so the second radar cannot share the first's.",
    ),
    "Y3": PART(
        mpn="ABM8-24.000MHZ-B2-T", manufacturer="Abracon",
        description="24 MHz crystal for the second radar",
        package="SMD-2016-4", body=(2.0, 1.6, 0.5), pitch=None, pins=4,
        datasheet="https://abracon.com/Resonators/ABM8.pdf",
        pdf=None, usd=None, stock="commodity", verdict="OK.",
    ),
    "J1": PART(
        mpn="FH12-10S-0.5SH(55)", manufacturer="Hirose",
        description="FFC connector, 10 way, 0.5 mm — the optics module",
        package="FH12-10S", body=(9.4, 4.3, 1.0), pitch=0.5, pins=10,
        datasheet="https://www.hirose.com/product/p/CL0580-1163-2-55",
        pdf=None, usd=None, stock="commodity",
        verdict="OK. ⚠️ The camera on the other end of it is NOT a chosen part.",
    ),
    "J4": PART(
        mpn="FH12-24S-0.5SH(55)", manufacturer="Hirose",
        description="FFC connector, 24 way — the taxel matrix",
        package="FH12-24S", body=(16.4, 4.3, 1.0), pitch=0.5, pins=24,
        datasheet="https://www.hirose.com/product/p/CL0580-1173-6-55",
        pdf=None, usd=None, stock="commodity",
        verdict="OK — 16 columns, 6 rows, a ground and a shield tab.",
    ),
    "J2": PART(
        mpn="SM02B-SRSS-TB(LF)(SN)", manufacturer="JST",
        description="SH series 2-pin 1.0 mm header — the cell",
        package="JST-SH-02", body=(4.25, 2.9, 2.9), pitch=1.0, pins=2,
        datasheet="https://www.jst.com/wp-content/uploads/2021/01/eSH1.pdf",
        pdf=None, usd=None, stock="commodity",
        verdict="OK at the charge current thermal/budget.py allows. ⚠️ At the "
                "5 W the design originally asked for, an SH contact is at its "
                "1 A rating and a 2 mm PH would be the honest choice.",
    ),
    "J3": PART(
        mpn="SM02B-SRSS-TB(LF)(SN)", manufacturer="JST",
        description="SH series 2-pin header — the Qi receiver coil",
        package="JST-SH-02", body=(4.25, 2.9, 2.9), pitch=1.0, pins=2,
        datasheet="https://www.jst.com/wp-content/uploads/2021/01/eSH1.pdf",
        pdf=None, usd=None, stock="commodity", verdict="OK.",
    ),
    "J5": PART(
        mpn="SM04B-SRSS-TB(LF)(SN)", manufacturer="JST",
        description="SH series 4-pin header — SWD",
        package="JST-SH-04", body=(6.25, 2.9, 2.9), pitch=1.0, pins=4,
        datasheet="https://www.jst.com/wp-content/uploads/2021/01/eSH1.pdf",
        pdf=None, usd=None, stock="commodity", verdict="OK.",
    ),
    "AE1": PART(
        mpn="2450AT43F0100E", manufacturer="Johanson Technology",
        description="2.4 GHz ceramic chip antenna",
        package="0402-style chip", body=(3.2, 1.6, 1.3), pitch=None, pins=2,
        datasheet="https://www.johansontechnology.com/datasheets/2450AT43F0100/2450AT43F0100.pdf",
        pdf=None, usd=None, stock="commodity",
        verdict="OK. ⚠️ Its matching network is Nordic's reference (L2, C6, C11 "
                "from table 87) and has NOT been tuned for this board — a chip "
                "antenna's match depends on the ground plane around it, so this "
                "is a starting point for a VNA, not a finished network.",
    ),
}
# ── passives ─────────────────────────────────────────────────────────────────
# ⛔ DERIVED, NOT MAINTAINED. This used to be a hand-written dict and it drifted
# the moment the board changed: it still described a 10 uF capacitor at C6 after
# C6 had become a 1.5 pF part of the antenna match, and a 1 uH inductor at L2
# that was by then 2.7 nH. A second list of the same facts is a list that will
# be wrong. The values live in netlist.py, next to the nets they sit on, and
# this groups them.
#
# ⚠️ Manufacturer part numbers are deliberately absent. A 100 nF 0402 X7R is a
# commodity and naming one vendor's would imply a selection nobody made. What
# does need choosing — dielectric, voltage rating, saturation current — is in
# the value string, because those are the ones that bite.
def passives():
    """{value: (package, [refs])} for every R, C and L on the board."""
    import netlist as _nl
    groups = {}
    for ref, val, _sym, _lib, fp, _pins, _x, _y in _nl.PARTS:
        if ref[0] not in "RCL" or ref.startswith("RT"):
            continue
        pkg = fp.split("_")[1] if "_" in fp else fp
        groups.setdefault((val, pkg), []).append(ref)
    return {v: (pkg, sorted(refs)) for (v, pkg), refs in sorted(groups.items())}


# ⭐ THREE OF THE FOUR THINGS THIS LIST USED TO CONTAIN ARE NOW ON THE BOARD:
# the cell thermistor (RT1, into the nPM1300's NTC input), the transimpedance
# front end (U8/U9 with U7 selecting columns), and the pin budget, solved by
# moving the sixteen columns behind a multiplexer instead of onto GPIO.
MISSING = [
    ("a camera module", "J1 is a 10-way FFC carrying power, I2C, SPI and two "
     "control lines, which is the right interface for a small sensor module — "
     "but no module is chosen, and until one is, the optical half of the "
     "recognition pipeline has no part number."),
    ("an NPU", "the SoC is a 128 MHz Cortex-M33. ml/classify.py measured the "
     "recognition method, not its runtime on this part. The 2 s settle window "
     "the firmware already waits is the budget it has to fit in."),
    ("a tuned antenna match", "L2/C6/C11 are the chip vendor's reference "
     "values. A chip antenna matches against the ground plane around it, and "
     "this ground plane is not theirs."),
]
