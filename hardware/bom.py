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
    "U11": PART(
        mpn="BQ51013BRHLR", manufacturer="Texas Instruments",
        description="5 W Qi receiver: synchronous rectifier, WPC control, 5 V out",
        package="VQFN-20 (RHL)", body=(4.5, 3.5, 0.9), pitch=0.5, pins=20,
        datasheet="https://www.ti.com/lit/ds/symlink/bq51013b.pdf",
        pdf="BQ51013B_ti.pdf", usd=None, stock="commodity",
        verdict="⛔ THIS PART WAS SIMPLY NOT ON THE BOARD, and nothing noticed. "
                "J3 ran from a connector labelled 'Qi RX coil' straight into "
                "the PMIC's VBUS pin — and VBUS wants 4.0 to 5.5 V of DC, it is "
                "a USB-C input, while a receiver coil produces ALTERNATING "
                "current at 100-200 kHz. Every check passed, because a net that "
                "reaches two pins is a net. The board would have been built, "
                "put on a charging pad, and done nothing at all. ⭐ And a bare "
                "rectifier would not have been enough either: Qi is a "
                "negotiation, and a transmitter that hears nothing back shuts "
                "down within a second.",
    ),
    "L_COIL": PART(
        mpn="760308103305", manufacturer="Würth Elektronik",
        description="WE-WPCC Qi receiver coil, 8.8 µH, litz wire with shield",
        package="coil", body=(44.0, 45.0, 0.72), pitch=None, pins=2,
        datasheet="https://www.we-online.com/en/components/products/WE-WPCC-RECEIVER",
        pdf=None, usd=None, stock="commodity",
        verdict="⚠️ NOT ON ANY OF THE THREE BOARDS — it hangs off J3 and lies "
                "under the cell. ⭐ It is in this list anyway because it sets "
                "two components that ARE on the board: hardware/qi_resonance.py "
                "computes Cs and Cd from its 8.8 µH and the two frequencies WPC "
                "fixes. Change the coil and both change. ⚠️ And the inductance "
                "that matters is WPC's L', measured with the shielding in place "
                "against a reference transmitter — typically 10-20% above the "
                "datasheet figure, which moves Cs by the same.",
    ),
    "BT1": PART(
        mpn="LP523450JU+PCM+JST PHR-3 70MM", manufacturer="Jauch Quartz",
        description="Li-Po 3.7 V 950 mAh pouch, PCM + 10k NTC, JST PHR-3 harness",
        package="pouch 53.0 x 34.5 x 5.4 mm", body=(53.0, 34.5, 5.8), pitch=2.0,
        pins=3,
        # ⭐ The cell's own charge table, machine-readable, so firmware/sb_power.h
        # can be checked against it instead of against a memory of it.
        capacity_mah=950, full_ma=1000, reduced_ma=200,
        charge_bands_c=(0, 15, 45, 55),   # none / 0.2C / 1.0C / 0.5C / none
        ntc="10k B=3435",
        datasheet="https://www.jauch.com/downloadfile/"
                  "63bedb31cabb36c600600ee0ce09460cb/lp523450jupcmjst_phr-3_70mm.pdf",
        pdf=None, usd=11.71, stock="Digi-Key 1908-LP523450JU+PCM+JSTPHR-370MM-ND",
        verdict="⭐ THE LINE THAT USED TO SAY 'NOT A PART YOU CAN ORDER'. It was "
                "a 4.2 x 58 x 148 mm semi-custom pouch — a shape derived from "
                "the insert floor, which nobody stocks, so the whole design "
                "ended at a battery you would have to have made. This is a "
                "catalogue cell with 507 in stock. ⭐ AND IT BRINGS ITS OWN "
                "THERMISTOR: 10 kΩ ±1% B=3435, on pin 3 of the harness, which "
                "is exactly what nPM1300 wants and what firmware/sb_power.c has "
                "been written against since the thermal analysis asked for it. "
                "⚠️ 950 mAh, not 2000 — and the capacity was never the "
                "constraint: thermal/budget.py measures 0.14 mW average, which "
                "this cell carries for nearly three years. ⛔ WHAT IT DOES "
                "CONSTRAIN is charge current: 1.0 C is 1000 mA and the design "
                "was written around 5 W of input. See firmware/sb_power.h. "
                "⭐ And being 53 x 34.5 instead of 148 x 58, it no longer has to "
                "sit on top of the Qi coil — which is the single assumption the "
                "thermal model's bad answer rested on.",
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
        mpn="FH12-12S-0.5SH(55)", manufacturer="Hirose",
        description="FFC connector, 12 way, 0.5 mm — the optics flex",
        package="FH12-12S", body=(10.4, 4.3, 1.0), pitch=0.5, pins=12,
        datasheet="https://www.hirose.com/product/p/CL0580-1165-8-55",
        pdf=None, usd=None, stock="commodity",
        verdict="OK — twelve ways, not ten. It grew when the time-of-flight "
                "sensor the firmware had always assumed finally got a "
                "schematic: its I2C, shutdown and interrupt cross this cable.",
    ),
    "Q1": PART(
        mpn="SI2302CDS-T1-GE3", manufacturer="Vishay",
        description="Logic-level N-channel MOSFET — the illuminator switch",
        package="SOT-23", body=(2.9, 1.3, 1.1), pitch=0.95, pins=3,
        datasheet="https://www.vishay.com/docs/70573/si2302cds.pdf",
        pdf=None, usd=None, stock="commodity",
        verdict="OK. ⭐ It exists because thermal/budget.py has been costing "
                "0.6 W of illuminator for 10 ms since before the board had any "
                "way to switch it — that is 160 mA, an order of magnitude past "
                "what a GPIO will source.",
    ),
    "Y4": PART(
        mpn="ABS07-32.768KHZ-9-T", manufacturer="Abracon",
        description="32.768 kHz crystal, Cl = 9 pF — the low-power timebase",
        package="SMD-2012-2", body=(2.0, 1.2, 0.6), pitch=None, pins=2,
        datasheet="https://abracon.com/Resonators/abs07.pdf",
        pdf=None, usd=None, stock="commodity",
        verdict="OK. ⭐ Not decoration: the app puts an age on every position it "
                "reports, and the SoC's internal RC is ±500 ppm — 43 seconds a "
                "day. A claim about a clock deserves a clock.",
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
        mpn="S3B-PH-K-S(LF)(SN)", manufacturer="JST",
        description="PH series 3-pin 2.0 mm side-entry header — the cell",
        package="JST-PH-03", body=(7.9, 4.5, 6.0), pitch=2.0, pins=3,
        datasheet="https://www.jst-mfg.com/product/pdf/eng/ePH.pdf",
        pdf=None, usd=None, stock="commodity",
        verdict="⭐ THE MATING HALF OF A BATTERY THAT EXISTS. It is a PH and not "
                "the SH it used to be for two reasons, and only one of them is "
                "the one this file predicted: a PH contact is rated 2 A against "
                "the SH's 1 A, which the charge current needed — and the pack "
                "that is going to be bought comes with its harness moulded onto "
                "a PHR-3 housing. An adapter between a cell and a charger is not "
                "a thing anyone should build. ⛔ And the PIN ORDER had to change "
                "with it: the harness is 1 red (+), 2 black (−), 3 yellow (NTC), "
                "and this board had NTC on 2 and the cell's negative on 3.",
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
        package="SMD chip", body=(6.0, 2.0, 1.2), pitch=None, pins=2,
        datasheet="https://www.johansontechnology.com/datasheets/2450AT43F0100/2450AT43F0100.pdf",
        pdf=None, usd=None, stock="commodity",
        verdict="OK now, and it was wrong three ways before the datasheet was "
                "read. ⛔ The body was recorded as 3.2 x 1.6 mm and is 6.0 x "
                "2.0. ⛔ Terminal 2 was tied to GROUND and the terminal table "
                "says NC — grounding it loads the radiator and no match "
                "recovers from that. ⚠️ And the network values are Johanson's "
                "own evaluation-board figures, which their datasheet says will "
                "be different on any other PCB; they are a topology with "
                "placeholders in it, to be swept on a VNA.",
    ),
}
# ─── the optics flex ─────────────────────────────────────────────────────────
# ⚠️ A SEPARATE BOARD, and these are its parts. J1 on the insert board has been
# a connector to nothing since the first commit; this is what is on the other
# end of it.
OPTICS = {
    "U10": PART(
        mpn="VL53L1X", manufacturer="STMicroelectronics",
        description="Time-of-flight ranging sensor, 940 nm, I2C, LGA-12",
        package="LGA-12", body=(4.9, 2.5, 1.56), pitch=0.8, pins=12,
        datasheet="https://www.st.com/resource/en/datasheet/vl53l1x.pdf",
        pdf="VL53L1X_st.pdf", usd=None, stock="commodity",
        verdict="⛔ THE PART THE WHOLE WAKE-UP CHAIN ASSUMED AND NOBODY DREW. "
                "firmware/smartbag.h has declared SB_EV_TOF_CROSSED since the "
                "first commit, dimensions.py places a sensor at TOF_X = 48, and "
                "the films show it working — with no schematic anywhere "
                "containing one. KiCad ships the footprint, so at least nothing "
                "had to be hand-drawn. It is a Class 1 laser product and the "
                "enclosure has to be labelled as one.",
    ),
    "D1..D4": PART(
        mpn="VSMY1850X01", manufacturer="Vishay",
        description="850 nm infrared emitter, 0805, Vf 1.65 V at 100 mA",
        package="0805", body=(2.0, 1.25, 0.85), pitch=None, pins=2,
        datasheet="https://www.vishay.com/docs/83397/vsmy1850.pdf",
        pdf="VSMY1850_vishay.pdf", usd=None, stock="commodity",
        verdict="OK. ⚠️ Four in PARALLEL with a resistor each, not two pairs in "
                "series: two of these need 3.3 V before any current flows and a "
                "LiPo spends half its life below that. ⚠️ And it is not a "
                "current source — 51 ohm gives 49 mA at 4.2 V and 27 mA at 3.0, "
                "so the scene dims by nearly half as the cell empties, while "
                "ml/render_dataset.py trains at one brightness.",
    ),
    "J11": PART(
        mpn="SM06B-SRSS-TB(LF)(SN)", manufacturer="JST",
        description="SH series 6-pin 1.0 mm header — the camera module",
        package="JST-SH-06", body=(8.25, 2.9, 2.9), pitch=1.0, pins=6,
        datasheet="https://www.jst.com/wp-content/uploads/2021/01/eSH1.pdf",
        pdf=None, usd=None, stock="commodity",
        verdict="OK — six ways is the camera's whole interface.",
    ),
    "CAM": PART(
        mpn="B0435 (Arducam Mega 3MP NoIR)", manufacturer="Arducam",
        description="3 MP SPI camera module, M12 lens, no IR-cut filter",
        package="module", body=(0, 0, 0), pitch=None, pins=6,
        datasheet="https://docs.arducam.com/Arduino-SPI-camera/MEGA-SPI/MEGA-SPI-Camera/",
        pdf=None, usd=None, stock="from Arducam directly",
        verdict="⚠️ BOUGHT, NOT BUILT, and it is not on any of these three "
                "boards — it hangs off J11 with its own lens and its own PCB. "
                "⛔ Its 8 MHz SPI ceiling is a design constraint, not a detail: "
                "ml/inference_budget.py works out that 96x96 grey takes 28 ms "
                "for a three-frame burst and fits, while 320x240 RGB565 takes "
                "461 ms and does not fit the firmware's 400 ms capture timeout.",
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
