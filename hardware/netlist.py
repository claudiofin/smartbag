#!/usr/bin/env python3
"""The netlist: real parts, real pinouts. One source, three consumers.

⛔ WHAT CHANGED, AND WHY IT IS THE WHOLE POINT. This file used to declare
component *classes* — "SoC+NPU BLE 5.4", "mmWave 60GHz TRX" — with pinouts
invented to suit. It said so at the top, which is better than not saying so, and
it was still a board nobody could build: no real SoC has ground on exactly pins
3 and 4. Every pin below now comes from a datasheet, and the three parts that
could not survive that check are gone:

  U1  nRF54L15-QFAA-R   QFN48 6x6 0.4 mm   pinout from figure 173, datasheet v1.0
  U2  Acconeer A121     fcCSP50            ball map from tables on pages 8-9
  U6  Acconeer A121     the second sensor — see below
  U3  nPM1300-QEAA-R7   QFN32 5x5 0.5 mm   pin table, page 150
  U4  BMI270            LGA-14             table 22
  U5  DRV5032           SOT-23             table 5-1

⭐ THE ARCHITECTURE THE PARTS FORCED. Three findings in this repo each demanded a
change, and the real components turned out to make all three for us:

  1. rf/feed_loss.py priced the 60 GHz feed from a central transceiver to the
     two antenna islands at 8.2 dB one way. The A121's datasheet says the
     antenna is inside the package and "it is not possible to connect trace
     antenna" — so there is no feed. TWO SENSORS, ONE ON EACH ISLAND, and what
     runs down the flex is SPI. ANT_A1 and ANT_A2 no longer exist.
  2. thermal/budget.py put the cell at ~60 C on a 5 W charge against a 45 C
     limit, and asked for charge current to be a function of cell temperature.
     The nPM1300 has an NTC input and JEITA charge control; RT1 is the
     thermistor the old board had nowhere to connect.
  3. firmware/test_sb_fsr.c measured both scan modes the old board could run:
     one invents phantom taxels, the other reads real ones 83% light. The cure
     is rows at a fixed potential, so the rows now land on transimpedance
     amplifiers and the columns are pulled to that same potential — see the
     FSR front end below.

⚠️ WHAT IS STILL NOT REAL. The nRF54L15 has no NPU: recognition runs on a
128 MHz Cortex-M33, not in 120 ms. It fits because the firmware already waits
2 s for the object to settle before it measures — inference happens inside a
window that existed anyway. The camera is an off-board module on J1 and its part
is not chosen.
"""

# Electrical types, as KiCad names them.
PWR_IN, PWR_OUT, IN, OUT, BIDI, PASSIVE, TRI = (
    "power_in", "power_out", "input", "output", "bidirectional", "passive",
    "tri_state")


def _bus(prefix, n, etype, start_pin):
    """`n` consecutive pins carrying prefix0..prefix{n-1}."""
    return [(start_pin + i, f"{prefix}{i}", etype, f"{prefix}{i}")
            for i in range(n)]


# ─── U1: nRF54L15-QFAA-R, QFN48 ───────────────────────────────────────────────
# Pin numbers and names are figure 173 of the nRF54L15 datasheet v1.0, read off
# the rendered page because the table itself is split across page breaks in a
# way no text extractor survives.
#
# ⭐ THE SIX FSR ROWS LAND ON AIN0..AIN5. The part has eight analog inputs, which
# is what makes a transimpedance front end affordable here: six amplifier
# outputs go straight to the ADC with no multiplexer between them, so nothing
# has to be settled and re-settled per row.
U1_PINS = [
    # ⭐ XL1/XL2, NOT GPIO. These two pins came free when the camera turned out
    # to need neither a reset nor a power-down, and they are the 32.768 kHz
    # oscillator inputs. The internal RC is ±500 ppm — 43 seconds a day — and
    # this product puts an age on the front of every position it reports:
    # "measured 40 minutes ago" is a claim about a clock. A ±20 ppm crystal
    # makes it 1.7 seconds a day. Nordic's reference calls for 2012, Cl = 9 pF.
    (1,  "P1.00/XL1", PASSIVE, "XTAL32K_1"),
    (2,  "P1.01/XL2", PASSIVE, "XTAL32K_2"),
    (3,  "P1.02", OUT,     "MUX_S0"),
    (4,  "P1.03", OUT,     "MUX_S1"),
    (5,  "P1.04/AIN0", IN, "ADC0"),
    (6,  "P1.05/AIN1", IN, "ADC1"),
    (7,  "P1.06/AIN2", IN, "ADC2"),
    (8,  "P1.07/AIN3", IN, "ADC3"),
    (9,  "P1.08", OUT,     "MUX_S2"),
    (10, "VDD", PWR_IN,    "VDD_3V3"),
    # ⛔ WHICH GPIO CARRIES WHICH SIGNAL IS A LAYOUT DECISION, and getting it
    # wrong is invisible until the router gives up. Pin 11 is on the package's
    # WEST edge and used to carry MUX_S3, whose only destination is 71 mm to the
    # EAST — so that net began by crossing the whole processor. Freerouting left
    # eight of this block's pins unrouted, and every one of them was a signal
    # pointed the wrong way.
    #
    # ⭐ These are now ordered BY DESTINATION: westbound nets on the west pins,
    # eastbound on the east ones, furthest travel on the outermost pin. On a
    # QFN48 pin 11 is the bottom of the west edge and pins 14-21 run west to
    # east along the south edge, so the order below is a physical one.
    #
    # ⚠️ P2.01/SCK, P2.02/SDO and P2.04/SDI DO NOT MOVE. Those are the pins the
    # nRF54L15's high-speed SPIM is wired to in silicon; the other SPIM
    # instances reach any GPIO through PSEL but run at 8 MHz instead of 32, and
    # the A121 streams sweeps over this bus.
    #
    # ⚠️ CS_RADAR_R gives up P2.05/CSN, and that costs nothing: there are two
    # radars on one bus, so at most one chip select could ever have been the
    # hardware CSN. Driving one from the peripheral and one from a GPIO would
    # have made two identical parts behave differently.
    (11, "P2.00", OUT,     "CS_RADAR_L"),
    (12, "P2.01/SCK", OUT, "SPI_SCK"),
    (13, "P2.02/SDO", OUT, "SPI_MOSI"),
    (14, "P2.03", IN,      "RADAR_IRQ_L"),
    (15, "P2.04/SDI", IN,  "SPI_MISO"),
    (16, "P2.05/CSN", OUT, "CS_CAM"),
    (17, "P2.06", OUT,     "RADAR_EN"),
    (18, "P2.07", OUT,     "MUX_S3"),
    (19, "P2.08", OUT,     "MUX_EN_N"),
    (20, "P2.09", IN,      "RADAR_IRQ_R"),
    (21, "P2.10", OUT,     "CS_RADAR_R"),
    (22, "VDD", PWR_IN,    "VDD_3V3"),
    (23, "P0.00", BIDI,    "I2C_SDA"),
    (24, "P0.01", OUT,     "I2C_SCL"),
    (25, "SWDIO", BIDI,    "SWDIO"),
    (26, "SWDCLK", IN,     "SWDCLK"),
    (27, "P0.02", IN,      "IMU_INT1"),
    (28, "P0.03", IN,      "HALL_OUT"),
    (29, "P0.04", IN,      "PMIC_IRQ"),
    (30, "nRESET", IN,     "NRESET"),
    (31, "ANT", PASSIVE,   "ANT_FEED"),
    (32, "VSS_PA", PWR_IN, "GND"),
    (33, "DECRF", PASSIVE, "DECRF"),
    (34, "XC1", PASSIVE,   "XTAL32M_1"),
    (35, "XC2", PASSIVE,   "XTAL32M_2"),
    (36, "VDD", PWR_IN,    "VDD_3V3"),
    (37, "P1.09", OUT,     "IR_LED_EN"),
    (38, "P1.10", OUT,     "TOF_XSHUT"),
    (39, "P1.11/AIN4", IN, "ADC4"),
    (40, "P1.12/AIN5", IN, "ADC5"),
    (41, "P1.13/AIN6", PASSIVE, "VSYS_SNS"),
    (42, "P1.14/AIN7", IN, "TOF_INT"),
    (43, "DECA", PASSIVE,  "DECA"),
    (44, "VSS", PWR_IN,    "GND"),
    (45, "DECD", PASSIVE,  "DECD"),
    (46, "DCC", PASSIVE,   "DCC"),
    (47, "VDD", PWR_IN,    "VDD_3V3"),
    (48, "VDD", PWR_IN,    "VDD_3V3"),
    (49, "EP", PWR_IN,     "GND"),
]

# ─── U2 / U6: Acconeer A121, fcCSP50 ─────────────────────────────────────────
# ⛔ EVERY UNUSED PIN GOES TO GROUND BECAUSE THE DATASHEET SAYS SO, not because
# it is convenient: Analog0/1, CTRL, GPIO1..4 and PLL_RF_TEST are all listed as
# "connect to ground" or "must be connected to solid ground plane". RESET_N goes
# to VIO, also on instruction — it is not a reset the host drives.
_A121_GND = ("A3 A4 A5 A6 A7 A8 B2 B9 C1 C10 D2 D9 E1 E2 E9 F2 F9 G1 G10 "
             "H2 H9 J3 J5 J6 J8 K4 K7").split()
_A121_TIE_GND = ["A2", "A9", "B1", "B10", "E10", "F1", "H1", "K5"]


def _a121(cs, irq, xin, xout):
    pins = [(b, "GND", PWR_IN, "GND") for b in _A121_GND]
    pins += [(b, b, PASSIVE, "GND") for b in _A121_TIE_GND]
    pins += [
        ("C2", "VRX", PWR_IN, "VDD_1V8"),
        ("D1", "VRX", PWR_IN, "VDD_1V8"),
        ("C9", "VTX", PWR_IN, "VDD_1V8"),
        ("D10", "VTX", PWR_IN, "VDD_1V8"),
        ("J9", "VDIG", PWR_IN, "VDD_1V8"),
        ("K9", "VIO", PWR_IN, "VDD_3V3"),
        ("J1", "RESET_N", PASSIVE, "VDD_3V3"),
        ("F10", "ENABLE", IN, "RADAR_EN"),
        ("J2", "SPI_SS", IN, cs),
        ("K2", "SPI_CLK", IN, "SPI_SCK"),
        ("K3", "SPI_MISO", TRI, "SPI_MISO"),
        ("K6", "SPI_MOSI", IN, "SPI_MOSI"),
        ("K8", "INTERRUPT", OUT, irq),
        ("J10", "XIN", PASSIVE, xin),
        ("H10", "XOUT", PASSIVE, xout),
    ]
    return pins


U2_PINS = _a121("CS_RADAR_L", "RADAR_IRQ_L", "X24L_1", "X24L_2")
U6_PINS = _a121("CS_RADAR_R", "RADAR_IRQ_R", "X24R_1", "X24R_2")

# ─── U3: nPM1300-QEAA-R7, QFN32 ──────────────────────────────────────────────
# Pin table, nPM1300 product specification v1.1 page 150.
#
# ⭐ RT1 ON PIN 18 IS THE THERMAL FIX. thermal/budget.py inverted its own model
# and got 2.2 W as the ceiling for charging inside a closed bag; the nPM1300
# reads the cell through NTC and applies the JEITA profile, which is the same
# answer implemented in silicon rather than in a comment.
U3_PINS = [
    (1,  "VOUT1", PWR_OUT, "VDD_1V8"),
    (2,  "PVSS1", PWR_IN,  "GND"),
    (3,  "SW1", PASSIVE,   "SW1"),
    (4,  "PVDD", PWR_IN,   "VSYS"),
    (5,  "SW2", PASSIVE,   "SW2"),
    (6,  "PVSS2", PWR_IN,  "GND"),
    (7,  "GPIO0", OUT,     "PMIC_IRQ"),
    (8,  "GPIO1", PASSIVE, "GND"),
    (9,  "GPIO2", PASSIVE, "GND"),
    (10, "GPIO3", PASSIVE, "GND"),
    (11, "GPIO4", PASSIVE, "GND"),
    (12, "VDDIO", PWR_IN,  "VDD_3V3"),
    (13, "SDA", BIDI,      "I2C_SDA"),
    (14, "SCL", IN,        "I2C_SCL"),
    (15, "SHPHLD", IN,     "SHPHLD"),
    (16, "VSET2", PASSIVE, "VSET2"),
    (17, "VSET1", PASSIVE, "VSET1"),
    (18, "NTC", PASSIVE,   "NTC"),
    (19, "VBAT", PWR_IN,   "VBAT"),
    (20, "VSYS", PWR_OUT,  "VSYS"),
    (21, "VBUS", PWR_IN,   "VQI"),
    (22, "VBUSOUT", PWR_OUT, "VBUSOUT"),
    (23, "CC1", PASSIVE,   "GND"),
    (24, "CC2", PASSIVE,   "GND"),
    (25, "LED0", OUT,      "LED0"),
    (26, "LED1", PASSIVE,  "GND"),
    (27, "LED2", PASSIVE,  "GND"),
    (28, "LSIN1", PWR_IN,  "VSYS"),
    (29, "LSOUT1", PWR_OUT, "VDD_CAM"),
    (30, "LSIN2", PASSIVE, "GND"),
    (31, "LSOUT2", PASSIVE, "GND"),
    (32, "VOUT2", PWR_OUT, "VDD_3V3"),
    (33, "EP", PWR_IN,     "GND"),
]

# ─── U11: BQ51013B, the Qi receiver. VQFN-20 (RHL), pin table SLUSB62D ───────
# ⛔ THIS CHIP WAS SIMPLY NOT THERE, and its absence was invisible: J3 went from
# a connector labelled "Qi RX coil" straight into the PMIC's VBUS pin, and every
# check passed because a net that reaches two pins is a net. What nothing looked
# at is that a receiver coil produces ALTERNATING current at 100-200 kHz and the
# nPM1300's VBUS wants 4.0 to 5.5 V of DC — it is a USB-C input. The board would
# have been built, put on a charging pad, and done nothing at all.
#
# ⭐ WHAT THIS PART ACTUALLY DOES, and why a rectifier alone would not: Qi is a
# negotiation. The receiver tells the transmitter how much power it wants by
# modulating its own load, and a transmitter that hears nothing back shuts down
# after a second. COMM1/COMM2 are that voice.
U11_PINS = [
    (1,  "PGND", PWR_IN, "GND"),
    (2,  "AC1", PASSIVE, "QI_AC1"),
    (3,  "BOOT1", PASSIVE, "QI_BOOT1"),
    (4,  "OUT", PWR_OUT, "VQI"),
    (5,  "CLAMP1", PASSIVE, "QI_CLAMP1"),
    (6,  "COMM1", PASSIVE, "QI_COMM1"),
    # ⚠️ Open-drain, "float or tie to PGND if unused". Floated: the PMIC already
    # reports charge state over I2C and a second, dumber signal for the same
    # thing is a pin that can disagree with it.
    (7,  "CHG", PASSIVE, "QI_CHG"),
    (8,  "AD_EN", PASSIVE, "QI_AD_EN"),
    # AD is the wired-adapter input. There is no wired adapter — the bag has no
    # socket — so the datasheet says connect it directly to PGND.
    (9,  "AD", PWR_IN, "GND"),
    (10, "EN1", PWR_IN, "GND"),      # <00> = wireless charging enabled
    (11, "EN2", PWR_IN, "GND"),
    (12, "ILIM", PASSIVE, "QI_ILIM"),
    (13, "TS_CTRL", PASSIVE, "QI_TS"),
    (14, "FOD", PASSIVE, "QI_FOD"),
    (15, "COMM2", PASSIVE, "QI_COMM2"),
    (16, "CLAMP2", PASSIVE, "QI_CLAMP2"),
    (17, "BOOT2", PASSIVE, "QI_BOOT2"),
    (18, "RECT", PWR_OUT, "QI_RECT"),
    (19, "AC2", PASSIVE, "QI_AC2"),
    (20, "PGND", PWR_IN, "GND"),
    (21, "EP", PWR_IN, "GND"),
]

# ─── U4: BMI270, LGA-14. Table 22, and the I2C connection diagram (7.2.3) ────
# ⚠️ CSB to VDDIO selects I2C; SDO to ground picks the low address. Both are
# instructions from the datasheet, not preferences.
U4_PINS = [
    (1,  "SDO", PASSIVE,  "GND"),
    (2,  "ASDx", PASSIVE, "GND"),
    (3,  "ASCx", PASSIVE, "GND"),
    (4,  "INT1", OUT,     "IMU_INT1"),
    (5,  "VDDIO", PWR_IN, "VDD_3V3"),
    (6,  "GNDIO", PWR_IN, "GND"),
    (7,  "GND", PWR_IN,   "GND"),
    (8,  "VDD", PWR_IN,   "VDD_3V3"),
    (9,  "INT2", PASSIVE, "IMU_INT2"),
    (10, "OCSB", PASSIVE, "GND"),
    (11, "OSDO", PASSIVE, "GND"),
    (12, "CSB", PASSIVE,  "VDD_3V3"),
    (13, "SCX", IN,       "I2C_SCL"),
    (14, "SDX", BIDI,     "I2C_SDA"),
]

# ─── U5: DRV5032FBDBZR, SOT-23. Table 5-1 ────────────────────────────────────
U5_PINS = [
    (1, "VCC", PWR_IN, "VDD_3V3"),
    (2, "OUT", OUT,    "HALL_OUT"),
    (3, "GND", PWR_IN, "GND"),
]

# ─── The FSR front end ───────────────────────────────────────────────────────
# ⛔ THIS IS THE PART THE OLD BOARD DID NOT HAVE, and firmware/test_sb_fsr.c is
# the reason it exists. A passive 16x6 matrix with no per-taxel isolation reads
# correctly only when every unselected element has zero volts across it. The
# topology here achieves that on a single supply:
#
#   - all sixteen columns are pulled to VREF through R20..R35;
#   - U7, a 16:1 analog multiplexer, pulls exactly ONE column down to ground;
#   - all six rows sit on transimpedance amplifiers whose non-inverting inputs
#     are also at VREF, so every row is held at VREF whatever happens to it.
#
# An unselected taxel therefore has VREF on both ends and carries nothing. The
# selected column is the only place current can go, and it arrives through
# exactly one taxel per row. That is the "TIA" case in the test, the one that
# reads 500 uS where the others read 112 uS of phantom and 83 uS of real.
#
# ⚠️ The multiplexer's on-resistance (~70 ohm) is in series with the taxel and
# is a systematic few-percent error. It calibrates out with sb_fsr_calibrate.
# ⛔ THIS PINOUT WAS WRONG IN ALMOST EVERY POSITION on the first attempt, and
# tools/check.py caught it by noticing that channel 0 did not exist anywhere.
# The version below is figure 4-1 of SCHS209D: pin 1 is the common terminal,
# channels count DOWN from I7 at pin 2 to I0 at pin 9, and there is no VEE — a
# 24-pin package holds 16 channels, four selects, an enable, common, VCC and GND
# exactly, with nothing left over. Writing it from memory produced a part with
# fifteen channels and a supply pin that does not exist.
#
# ⚠️ E is ACTIVE LOW. Driving MUX_EN_N high disconnects every column, which is
# also how the scan parks the matrix between sweeps.
U7_PINS = [
    (1,  "COM", PASSIVE, "FSR_SINK"),
    (2,  "I7", PASSIVE, "FSR_C7"),
    (3,  "I6", PASSIVE, "FSR_C6"),
    (4,  "I5", PASSIVE, "FSR_C5"),
    (5,  "I4", PASSIVE, "FSR_C4"),
    (6,  "I3", PASSIVE, "FSR_C3"),
    (7,  "I2", PASSIVE, "FSR_C2"),
    (8,  "I1", PASSIVE, "FSR_C1"),
    (9,  "I0", PASSIVE, "FSR_C0"),
    (10, "S0", IN, "MUX_S0"),
    (11, "S1", IN, "MUX_S1"),
    (12, "GND", PWR_IN, "GND"),
    (13, "S3", IN, "MUX_S3"),
    (14, "S2", IN, "MUX_S2"),
    (15, "EN", IN, "MUX_EN_N"),
    (16, "I15", PASSIVE, "FSR_C15"),
    (17, "I14", PASSIVE, "FSR_C14"),
    (18, "I13", PASSIVE, "FSR_C13"),
    (19, "I12", PASSIVE, "FSR_C12"),
    (20, "I11", PASSIVE, "FSR_C11"),
    (21, "I10", PASSIVE, "FSR_C10"),
    (22, "I9", PASSIVE, "FSR_C9"),
    (23, "I8", PASSIVE, "FSR_C8"),
    (24, "VCC", PWR_IN, "VDD_3V3"),
]


def _quad_opamp(rows):
    """TLV9064, TSSOP-14. Four inverting transimpedance stages.

    ⚠️ Pinout is the industry-standard quad layout (OUT1 1, IN1- 2, IN1+ 3,
    V+ 4, IN2+ 5, IN2- 6, OUT2 7, OUT3 8, IN3- 9, IN3+ 10, V- 11, IN4+ 12,
    IN4- 13, OUT4 14), which every quad op-amp in a 14-pin package shares.

    ⛔ UNUSED CHANNELS ARE WIRED AS FOLLOWERS, NOT LEFT FLOATING. Six rows need
    six amplifiers and two quads supply eight, so two channels are spare. An
    op-amp with an open inverting input is not idle — it saturates against a
    rail and can oscillate, and on a shared die that couples into the channels
    you are using. Tying the output back to the inverting input and the
    non-inverting input to VREF makes each spare a unity-gain buffer sitting
    quietly at VREF. It also happens to satisfy ERC, which is the smaller
    reason.
    """
    a, b, c, d = rows
    n3 = f"FSR_R{c}" if c is not None else "OPA_SPARE3"
    o3 = f"ADC{c}" if c is not None else "OPA_SPARE3"
    n4 = f"FSR_R{d}" if d is not None else "OPA_SPARE4"
    o4 = f"ADC{d}" if d is not None else "OPA_SPARE4"
    return [
        (1,  "OUT1", OUT, f"ADC{a}"),
        (2,  "IN1-", IN, f"FSR_R{a}"),
        (3,  "IN1+", IN, "VREF"),
        (4,  "V+", PWR_IN, "VDD_3V3"),
        (5,  "IN2+", IN, "VREF"),
        (6,  "IN2-", IN, f"FSR_R{b}"),
        (7,  "OUT2", OUT, f"ADC{b}"),
        (8,  "OUT3", OUT, o3),
        (9,  "IN3-", IN, n3),
        (10, "IN3+", IN, "VREF"),
        (11, "V-", PWR_IN, "GND"),
        (12, "IN4+", IN, "VREF"),
        (13, "IN4-", IN, n4),
        (14, "OUT4", OUT, o4),
    ]


U8_PINS = _quad_opamp((0, 1, 2, 3))
U9_PINS = _quad_opamp((4, 5, None, None))

# ─── Q1: the IR illuminator switch ──────────────────────────────────────────
# ⛔ A GPIO CANNOT DRIVE THESE. thermal/budget.py budgets 0.6 W of illuminator
# for 10 ms, which at the cell voltage is around 160 mA — more than an order of
# magnitude past what a pin will source. The LEDs live on the optics module in
# two series pairs off VSYS; what the main board owes them is a low-side switch
# and somewhere to put the current-set resistor.
#
# ⚠️ R13 is a pull-DOWN on the gate, not a pull-up, and it is the reason the
# illuminators are dark while the processor is in reset. A floating gate on a
# logic-level FET is a 160 mA load waiting for a static charge.
Q1_PINS = [
    (1, "G", IN, "IR_LED_EN"),
    (2, "S", PWR_IN, "GND"),
    (3, "D", PASSIVE, "IR_LED_K"),
]

# ─── Crystals ────────────────────────────────────────────────────────────────
Y4_PINS = [(1, "XI", PASSIVE, "XTAL32K_1"), (2, "XO", PASSIVE, "XTAL32K_2")]
Y1_PINS = [(1, "XI", PASSIVE, "XTAL32M_1"), (2, "GND", PWR_IN, "GND"),
           (3, "XO", PASSIVE, "XTAL32M_2"), (4, "GND", PWR_IN, "GND")]
Y2_PINS = [(1, "XI", PASSIVE, "X24L_1"), (2, "GND", PWR_IN, "GND"),
           (3, "XO", PASSIVE, "X24L_2"), (4, "GND", PWR_IN, "GND")]
Y3_PINS = [(1, "XI", PASSIVE, "X24R_1"), (2, "GND", PWR_IN, "GND"),
           (3, "XO", PASSIVE, "X24R_2"), (4, "GND", PWR_IN, "GND")]

# ─── Connectors ──────────────────────────────────────────────────────────────
# ⚠️ EVERY SIGNAL PIN ON A CONNECTOR IS PASSIVE. It was tempting to give these
# the direction of the thing on the other end, and ERC was right to reject it: a
# connector drives nothing, and calling pin 5 an output puts two drivers on the
# clock net. The only pins with a direction here are the supplies.
#
# ⛔ THIS USED TO CARRY I2C, A POWER-DOWN AND A RESET, and the real camera wants
# none of them. The Arducam Mega is SPI only — "we removed two I2C interfaces
# and now only 6 pin left, 4 for SPI, 2 for power" — so three ways came free and
# went to the thing the board was actually missing: a way to drive the
# illuminators. thermal/budget.py has been costing them at 0.6 W for a hundredth
# of a second since before there was anything to switch them with.
#
# ⭐ VDD_CAM IS A SWITCHED RAIL, not the 3.3 V bus. It comes off the nPM1300's
# load switch, so the camera — 56 to 136 mA whenever it is awake — is off
# between bursts rather than merely idle.
# ⛔ TWELVE WAYS, AND THE TWO NEW ONES ARE THE HOLE THIS PROJECT HAD ALL ALONG.
# The firmware's wake-up chain has always turned on SB_EV_TOF_CROSSED — the beam
# across the mouth breaking is what arms the camera — dimensions.py has placed a
# time-of-flight sensor at TOF_X = 48 since the first commit, and the films show
# it working. No schematic ever contained one. The state machine depended on an
# event no hardware could generate, and every check passed because none of them
# reads the firmware's event list against the netlist. tools/check.py does now.
#
# ⭐ The sensor lives on the OPTICS FLEX, not here, because it has to look across
# the opening. What crosses this connector is its I2C, its shutdown and its
# interrupt.
J1_PINS = [
    (1,  "GND", PWR_IN, "GND"),
    (2,  "VDD", PWR_IN, "VDD_CAM"),
    (3,  "SCK", PASSIVE, "SPI_SCK"),
    (4,  "MOSI", PASSIVE, "SPI_MOSI"),
    (5,  "MISO", PASSIVE, "SPI_MISO"),
    (6,  "CS", PASSIVE, "CS_CAM"),
    (7,  "SDA", PASSIVE, "I2C_SDA"),
    (8,  "SCL", PASSIVE, "I2C_SCL"),
    (9,  "XSHUT", PASSIVE, "TOF_XSHUT"),
    (10, "TOF_INT", PASSIVE, "TOF_INT"),
    (11, "LED+", PWR_IN, "VSYS"),
    (12, "LED-", PASSIVE, "IR_LED_K"),
]

J4_PINS = ([(1, "GND", PWR_IN, "GND")]
           + [(2 + i, f"C{i}", PASSIVE, f"FSR_C{i}") for i in range(16)]
           + [(18 + i, f"R{i}", PASSIVE, f"FSR_R{i}") for i in range(6)]
           + [(24, "SHLD", PWR_IN, "GND")])
# ⛔ THREE PINS, BECAUSE THE THERMISTOR BELONGS TO THE PACK. RT1 was a 0402 on
# this board — which measures THIS BOARD, twenty millimetres of foam away from
# the cell whose temperature the entire charge policy is about. The nPM1300's
# own words are "the battery thermistor"; every real lithium pack brings it out
# on a third wire, and that is the only place it means anything.
# ⛔ THE ORDER IS THE CELL'S, NOT MINE. This used to be +, NTC, −, which is the
# order you would choose if you were drawing a connector rather than plugging one
# in. The pack that is actually going to be bought — Jauch LP523450JU, whose
# harness is moulded onto a JST PHR-3 — is wired Pin 1 red (+), Pin 2 black (−),
# Pin 3 yellow (NTC). Plugging that into the old footprint puts the cell's
# NEGATIVE on the PMIC's thermistor input and the thermistor on ground.
#
# ⚠️ Nothing in this repository could have caught that. Every check here asks
# whether a net reaches the pins it should; none of them knew what colour wire
# comes out of the pack, because until a real cell was chosen there was no pack.
J2_PINS = [(1, "BAT+", PWR_OUT, "VBAT"),
           (2, "BAT-", PWR_IN, "GND"),
           (3, "NTC", PASSIVE, "NTC")]
# ⚠️ NEITHER PIN IS GROUND. A receiver coil is a floating winding: both ends go
# to the rectifier's AC inputs. The old version had one end on VQI and the other
# on GND, which is a coil shorted to ground through half the rectifier.
# ⚠️ Only ONE end goes through a capacitor. Cs is the series resonant element
# and it sits between the coil and AC1; the other end of the winding lands on
# AC2 directly. Putting a capacitor in both legs would halve the series
# capacitance and move the tank off 100 kHz.
J3_PINS = [(1, "COIL_A", PASSIVE, "QI_COIL_A"),
           (2, "COIL_B", PASSIVE, "QI_AC2")]
J5_PINS = [(1, "VDD", PWR_IN, "VDD_3V3"), (2, "SWCLK", PASSIVE, "SWDCLK"),
           (3, "SWDIO", PASSIVE, "SWDIO"), (4, "GND", PWR_IN, "GND")]
# ⛔ TERMINAL 2 IS "NC", AND IT WAS TIED TO GROUND. The Johanson datasheet's
# terminal table says pin 1 is the feeding point and pin 2 is Not Connected —
# it is a mechanical anchor, not a return. Grounding it loads the radiator
# directly and there is no matching network that recovers from that. This was in
# the netlist from the first version and nothing caught it, because a pad tied
# to ground is electrically unremarkable in every check the project runs.
AE1_PINS = [(1, "FEED", PASSIVE, "BLE_ANT"), (2, "NC", PASSIVE, "ANT_NC")]

_2 = lambda a, b: [(1, "1", PASSIVE, a), (2, "2", PASSIVE, b)]   # noqa: E731

# ─── The board ───────────────────────────────────────────────────────────────
# ⭐ THE TWO RADARS SIT ON THE END ISLANDS. That placement used to be a pair of
# patch arrays fed 88 mm of 60 GHz microstrip from a transceiver in the middle;
# now it is the transceivers themselves, and what crosses the flex is SPI.
PARTS = [
    ("U1", "nRF54L15-QFAA-R", "NRF54L15", "Package_DFN_QFN",
     "QFN-48-1EP_6x6mm_P0.4mm_EP4.6x4.6mm", U1_PINS, -12.0, 0.0),
    ("U2", "Acconeer A121", "A121", "SmartBag",
     "Acconeer_A121_fcCSP50", U2_PINS, -86.0, 0.0),
    ("U6", "Acconeer A121", "A121", "SmartBag",
     "Acconeer_A121_fcCSP50", U6_PINS, 86.0, 0.0),
    ("U3", "nPM1300-QEAA-R7", "NPM1300", "Package_DFN_QFN",
     "QFN-32-1EP_5x5mm_P0.5mm_EP3.45x3.45mm", U3_PINS, 8.0, 0.0),
    ("U4", "BMI270", "BMI270", "Package_LGA",
     "Bosch_LGA-14_3x2.5mm_P0.5mm", U4_PINS, -3.0, -6.5),
    ("U5", "DRV5032FBDBZR", "DRV5032", "Package_TO_SOT_SMD",
     "SOT-23", U5_PINS, -30.0, -6.0),
    ("U11", "BQ51013BRHLR", "BQ51013B", "Package_DFN_QFN",
     "Texas_VQFN-RHL-20", U11_PINS, 30.0, 0.0),
    ("Q1", "SI2302CDS-T1-GE3", "NMOS", "Package_TO_SOT_SMD",
     "SOT-23", Q1_PINS, -30.0, 3.0),
    ("U7", "CD74HC4067SM96", "MUX16", "Package_SO",
     "SSOP-24_5.3x8.2mm_P0.65mm", U7_PINS, 42.0, 1.5),
    ("U8", "TLV9064IPWR", "OPA_QUAD", "Package_SO",
     "TSSOP-14_4.4x5mm_P0.65mm", U8_PINS, 34.0, -5.5),
    ("U9", "TLV9064IPWR", "OPA_QUAD", "Package_SO",
     "TSSOP-14_4.4x5mm_P0.65mm", U9_PINS, 44.0, -5.5),
    ("Y1", "32 MHz Cl=8pF", "XTAL4", "Crystal",
     "Crystal_SMD_2016-4Pin_2.0x1.6mm", Y1_PINS, -19.5, -6.0),
    ("Y4", "32.768 kHz Cl=9pF", "XTAL2", "Crystal",
     "Crystal_SMD_2012-2Pin_2.0x1.2mm", Y4_PINS, -22.0, -3.0),
    ("Y2", "24 MHz", "XTAL4", "Crystal",
     "Crystal_SMD_2016-4Pin_2.0x1.6mm", Y2_PINS, -81.0, -5.5),
    ("Y3", "24 MHz", "XTAL4", "Crystal",
     "Crystal_SMD_2016-4Pin_2.0x1.6mm", Y3_PINS, 81.0, -5.5),
    ("J1", "FFC optics, 12 way", "FFC_12", "Connector_FFC-FPC",
     "Hirose_FH12-12S-0.5SH_1x12-1MP_P0.50mm_Horizontal", J1_PINS, -46.0, 6.0),
    ("J4", "FFC FSR matrix, 24 way", "FFC_24", "Connector_FFC-FPC",
     "Hirose_FH12-24S-0.5SH_1x24-1MP_P0.50mm_Horizontal", J4_PINS, 34.0, -4.5),
    # ⭐ PH, NOT SH — 2.0 mm pitch and 2 A a contact instead of 1. The note in
    # bom.py had been saying so since the charge current was first written down;
    # the real pack settles it, because that is the housing its harness comes
    # with and an adapter between a battery and a charger is not a thing to build.
    ("J2", "Jauch LP523450JU 950mAh", "CONN3", "Connector_JST",
     "JST_PH_S3B-PH-K_1x03_P2.00mm_Horizontal", J2_PINS, 20.0, 6.5),
    ("J3", "Qi RX coil", "CONN2", "Connector_JST",
     "JST_SH_SM02B-SRSS-TB_1x02-1MP_P1.00mm_Horizontal", J3_PINS, 28.0, 6.5),
    ("J5", "SWD debug", "CONN4", "Connector_JST",
     "JST_SH_SM04B-SRSS-TB_1x04-1MP_P1.00mm_Horizontal", J5_PINS, -37.0, 6.0),
    # ⭐ FIDUCIALS ARE IN THE NETLIST, and that is not pedantry. Put them on the
    # board only and schematic parity reports five "extra footprint" warnings
    # forever — correctly, because the board would contain things the schematic
    # has never heard of. A fiducial with no pins is a part with no nets, which
    # is exactly what it is.
    # ⚠️ NO PINS, AND THE FOOTPRINT AGREES. A fiducial's copper target is a pad
    # with an EMPTY number — `(pad "" smd circle ...)` — because it is not a
    # connection, it is a thing a camera looks at. So the symbol has no pins
    # either, and the two match. Giving it a pin numbered 1 produced "no pad
    # found for pin 1", which is DRC being right twice in a row.
    #
    # ⛔ And `in_bom no`, because the footprint carries `exclude_from_bom` and a
    # symbol that disagrees is a footprint/symbol mismatch. Five parts, two
    # warnings each, for a checkbox.
    # ⛔ TWO PER RIGID ISLAND, DIAGONALLY OPPOSITE — not three global marks on a
    # 196 mm strip. This board is three rigid islands joined by flex tails, and
    # a tail is exactly the thing that lets one island sit a little rotated with
    # respect to the next. A machine that has located the left island from two
    # marks there knows nothing about where the right one ended up. The previous
    # five were placed as if the board were one rigid piece, and two of them
    # landed on the flex.
    ("FID1", "fiducial", "FIDUCIAL", "Fiducial", "Fiducial_1mm_Mask2mm", [], -96.0, -7.5),
    ("FID2", "fiducial", "FIDUCIAL", "Fiducial", "Fiducial_1mm_Mask2mm", [], -86.0, 7.5),
    ("FID3", "fiducial", "FIDUCIAL", "Fiducial", "Fiducial_1mm_Mask2mm", [], -59.0, -7.5),
    ("FID4", "fiducial", "FIDUCIAL", "Fiducial", "Fiducial_1mm_Mask2mm", [], 59.0, 7.5),
    ("FID5", "fiducial", "FIDUCIAL", "Fiducial", "Fiducial_1mm_Mask2mm", [], 86.0, -7.5),
    ("FID6", "fiducial", "FIDUCIAL", "Fiducial", "Fiducial_1mm_Mask2mm", [], 96.0, 7.5),
    ("AE1", "2450AT43F0100E", "ANTENNA", "RF_Antenna",
     "Johanson_2450AT43F0100_2400-2500Mhz", AE1_PINS, -42.0, 0.0),
]

# ─── Passives, from the manufacturers' own reference integrations ────────────
# ⚠️ NOT A GUESS AT WHAT LOOKS RIGHT. Nordic's table 87 (nRF54L15 circuit
# configuration 1) and Acconeer's table 13 (A121 integration) each list exactly
# what their part needs; both are transcribed here. Where a value is this
# project's own — the TIA feedback, the column pull-ups, the VREF divider — the
# comment says why it is that number.
_PASSIVES = [
    # nRF54L15, Nordic table 87
    ("C1", "2.2u X6T 2.5V", "C_0402_1005Metric", "DECA", "GND", -19.5, 3.5),
    ("C2", "2.2u X6T 2.5V", "C_0402_1005Metric", "DECD", "GND", -17.5, 3.5),
    ("C3", "10u X6S 6.3V", "C_0402_1005Metric", "VDD_3V3", "GND", -15.5, 3.5),
    ("C4", "100n X7R", "C_0402_1005Metric", "VDD_3V3", "GND", -13.5, 3.5),
    ("C5", "2.2n X7R", "C_0402_1005Metric", "DECRF", "GND", -11.5, 3.5),
    ("C7", "100n X7R", "C_0402_1005Metric", "VDD_3V3", "GND", -9.5, 3.5),
    ("C8", "100n X7R", "C_0402_1005Metric", "VDD_3V3", "GND", -7.5, 3.5),
    ("L1", "4.7u 120mA", "L_0603_1608Metric", "DCC", "VDD_3V3", -21.5, 3.5),
    # ⭐ The 2.4 GHz match. Nordic's reference is a pi network between ANT and
    # the antenna; the chip antenna's own datasheet then asks for a series
    # element. C6/L2/C11 are that network — values from table 87.
    ("L2", "2.7n", "L_0402_1005Metric", "ANT_FEED", "BLE_ANT", -39.0, 0.0),
    ("C6", "1.5p NP0", "C_0402_1005Metric", "ANT_FEED", "GND", -41.0, 3.5),
    ("C11", "0.3p C0G", "C_0402_1005Metric", "BLE_ANT", "GND", -37.0, 3.5),
    # A121 left: table 13 asks for 1 uF on each of VRX, VTX, VDIG, VIO
    ("C20", "1u X5R", "C_0402_1005Metric", "VDD_1V8", "GND", -91.0, 3.5),
    ("C21", "1u X5R", "C_0402_1005Metric", "VDD_1V8", "GND", -89.0, 3.5),
    ("C22", "1u X5R", "C_0402_1005Metric", "VDD_1V8", "GND", -87.0, 3.5),
    ("C23", "1u X5R", "C_0402_1005Metric", "VDD_3V3", "GND", -85.0, 3.5),
    ("C24", "8p NP0", "C_0402_1005Metric", "X24L_1", "GND", -81.0, -5.5),
    ("C25", "8p NP0", "C_0402_1005Metric", "X24L_2", "GND", -84.0, -5.5),
    # A121 right
    ("C30", "1u X5R", "C_0402_1005Metric", "VDD_1V8", "GND", 91.0, 3.5),
    ("C31", "1u X5R", "C_0402_1005Metric", "VDD_1V8", "GND", 89.0, 3.5),
    ("C32", "1u X5R", "C_0402_1005Metric", "VDD_1V8", "GND", 87.0, 3.5),
    ("C33", "1u X5R", "C_0402_1005Metric", "VDD_3V3", "GND", 85.0, 3.5),
    ("C34", "8p NP0", "C_0402_1005Metric", "X24R_1", "GND", 81.0, -5.5),
    ("C35", "8p NP0", "C_0402_1005Metric", "X24R_2", "GND", 84.0, -5.5),
    # nPM1300 power stage
    ("L3", "2.2u 1.2A", "L_0603_1608Metric", "SW1", "VDD_1V8", 13.0, 4.5),
    ("L4", "2.2u 1.2A", "L_0603_1608Metric", "SW2", "VDD_3V3", 13.0, 1.5),
    ("C40", "10u X5R 6.3V", "C_0402_1005Metric", "VSYS", "GND", 17.0, 6.5),
    ("C41", "10u X5R 6.3V", "C_0402_1005Metric", "VDD_1V8", "GND", 19.4, 6.5),
    ("C42", "10u X5R 6.3V", "C_0402_1005Metric", "VDD_3V3", "GND", 21.8, 6.5),
    ("C43", "1u X5R", "C_0402_1005Metric", "VBAT", "GND", 24.2, 6.5),
    ("C44", "1u X5R", "C_0402_1005Metric", "VQI", "GND", 26.6, 6.5),
    ("C45", "1u X5R", "C_0402_1005Metric", "VBUSOUT", "GND", 29.0, 6.5),
    ("C46", "1u X5R", "C_0402_1005Metric", "VDD_CAM", "GND", 31.4, 6.5),
    # ⛔ RT1 AND ITS PULL-UP ARE GONE, and both were wrong. The thermistor now
    # lives in the battery pack on J2 pin 2, where the temperature it reports is
    # the one the charge policy is actually about — a 0402 on this board
    # measures this board, twenty millimetres of foam away from the cell. And R1
    # pulled NTC up to VSYS: the nPM1300 biases that pin itself and measures
    # ratiometrically, so an external pull-up does not help the reading, it
    # corrupts it.
    #
    # ⚠️ The pack's thermistor must be 10 kohm, B25/50 = 3380 K, 1% — nPM1300
    # table 12 supports exactly three types and this is one of them.

    # ── the Qi resonant tank and the receiver's support parts ──────────────
    # ⭐ Cs and Cd are COMPUTED by hardware/qi_resonance.py from the chosen
    # coil's inductance and the two frequencies WPC fixes: 100 kHz where a
    # transmitter drives, and 1 MHz where it pings to discover anything is
    # there. They belong to the COIL, not to the chip — change the coil and both
    # change. ⚠️ C0G, not X7R: a capacitor whose value walks with applied
    # voltage detunes the tank, and this one carries the full coil current.
    ("C80", "270n C0G (Cs)", "C_0603_1608Metric", "QI_COIL_A", "QI_AC1", 24.0, 4.0),
    ("C81", "2n7 C0G (Cd)", "C_0402_1005Metric", "QI_AC1", "QI_AC2", 26.5, 4.0),
    ("C82", "10n X7R", "C_0402_1005Metric", "QI_BOOT1", "QI_AC1", 24.0, -3.0),
    ("C83", "10n X7R", "C_0402_1005Metric", "QI_BOOT2", "QI_AC2", 26.0, -3.0),
    # ⚠️ The overvoltage clamp. Above 15 V on RECT both switches close and these
    # become a low impedance across the coil — this is what survives a
    # transmitter still pushing after the load has gone away.
    ("C84", "470n X7R 25V", "C_0603_1608Metric", "QI_CLAMP1", "QI_AC1", 28.0, -3.0),
    ("C85", "470n X7R 25V", "C_0603_1608Metric", "QI_CLAMP2", "QI_AC2", 30.5, -3.0),
    # ⭐ The receiver's voice. Qi is a negotiation: the transmitter learns how
    # much power to send by watching reflected impedance change as these switch
    # in, and one that hears nothing back shuts down within a second. The
    # datasheet wants 22 nF EFFECTIVE across AC1-AC2; two in series halve, so
    # each is 47 nF.
    ("C86", "47n X7R", "C_0402_1005Metric", "QI_COMM1", "QI_AC1", 33.0, -3.0),
    ("C87", "47n X7R", "C_0402_1005Metric", "QI_COMM2", "QI_AC2", 35.0, -3.0),
    ("C88", "10u X5R 25V", "C_0603_1608Metric", "QI_RECT", "GND", 29.0, 4.0),
    # RILIM = R20 + R21 = 320 ohm, and KILIM/RILIM = 314/320 puts the hardware
    # current limit just under 1 A. FOD taps between them.
    # ⚠️ The split is a starting point. Foreign-object detection compares
    # received power against expected, and the ratio has to be calibrated
    # against a built unit on a real transmitter — like the antenna match, a
    # value that cannot be computed from any datasheet.
    ("R20", "220R 1%", "R_0402_1005Metric", "QI_ILIM", "QI_FOD", 32.0, 4.0),
    ("R21", "100R 1%", "R_0402_1005Metric", "QI_FOD", "GND", 34.0, 4.0),
    ("R22", "10k 1%", "R_0402_1005Metric", "QI_TS", "GND", 36.0, 4.0),

    # nPM1300 output-voltage straps and the hold pin
    ("R2", "10k 1%", "R_0402_1005Metric", "VSET1", "GND", 7.0, -5.5),
    ("R3", "10k 1%", "R_0402_1005Metric", "VSET2", "GND", 9.5, -5.5),
    ("R4", "1M 1%", "R_0402_1005Metric", "SHPHLD", "VSYS", 12.0, -5.5),
    ("R5", "10k 1%", "R_0402_1005Metric", "NRESET", "VDD_3V3", 14.5, -5.5),
    ("R6", "1k 1%", "R_0402_1005Metric", "LED0", "GND", 17.0, -5.5),
    # IMU and Hall decoupling, from their datasheets
    ("C50", "100n X7R", "C_0402_1005Metric", "VDD_3V3", "GND", -9.5, -6.5),
    ("C51", "100n X7R", "C_0402_1005Metric", "VDD_3V3", "GND", -2.5, -6.5),
    ("C52", "100n X7R", "C_0402_1005Metric", "VDD_3V3", "GND", -27.0, 5.0),
    # I2C pull-ups
    ("R13", "100k 1%", "R_0402_1005Metric", "IR_LED_EN", "GND", -27.0, 2.0),
    ("R7", "4.7k 1%", "R_0402_1005Metric", "I2C_SDA", "VDD_3V3", -20.0, 3.0),
    ("R8", "4.7k 1%", "R_0402_1005Metric", "I2C_SCL", "VDD_3V3", -17.5, 3.0),
    # ⭐ VREF for the whole FSR front end: 3.3 V through a 6.8k/1.2k divider is
    # 0.49 V. Low enough that a 2 kohm pressed taxel draws 245 uA and an 8.2k
    # feedback resistor swings 2.0 V — most of the ADC range — and high enough
    # to stay inside the amplifier's input common-mode range.
    ("R10", "6.8k 1%", "R_0402_1005Metric", "VDD_3V3", "VREF", 30.0, -8.0),
    ("R11", "1.2k 1%", "R_0402_1005Metric", "VREF", "GND", 32.5, -8.0),
    ("C60", "1u X5R", "C_0402_1005Metric", "VREF", "GND", 17.0, -8.0),
    ("C61", "100n X7R", "C_0402_1005Metric", "VDD_3V3", "GND", 19.5, -8.0),
    ("C62", "100n X7R", "C_0402_1005Metric", "VDD_3V3", "GND", 22.0, -8.0),
    ("C63", "100n X7R", "C_0402_1005Metric", "VDD_3V3", "GND", 24.5, -8.0),
    # ⛔ The multiplexer common pin goes to ground through nothing but itself.
    # FSR_SINK exists as a named net so the schematic has to say so out loud.
    ("R12", "0R", "R_0402_1005Metric", "FSR_SINK", "GND", 35.0, -8.0),
]

# TIA feedback: one 8.2k per row, output to ADC.
_PASSIVES += [(f"R{40 + i}", "8.2k 1%", "R_0402_1005Metric",
               f"FSR_R{i}", f"ADC{i}", 17.0 + i * 2.4, -1.5)
              for i in range(6)]

# ⭐ Sixteen column pull-ups to VREF. This is what makes an unselected column sit
# at exactly the potential the rows are held at, so an unselected taxel has zero
# volts across it and cannot carry the sneak current that produces a phantom.
# 100k against a 70 ohm multiplexer means the selected column is pulled
# essentially all the way down.
_PASSIVES += [(f"R{60 + i}", "100k 1%", "R_0402_1005Metric",
               f"FSR_C{i}", "VREF", 20.0 + (i % 8) * 2.4, 1.5 - (i // 8) * 2.4)
              for i in range(16)]

for _ref, _val, _fp, _na, _nb, _x, _y in _PASSIVES:
    _lib = ("Capacitor_SMD" if _ref.startswith("C")
            else "Inductor_SMD" if _ref.startswith("L")
            else "Resistor_SMD")
    _sym = ("C" if _ref.startswith("C") else "L" if _ref.startswith("L")
            else "R")
    PARTS.append((_ref, _val, _sym, _lib, _fp, _2(_na, _nb), _x, _y))

# ⚠️ VBAT and VQI used to carry power flags as well as coming from connectors
# that declare themselves power outputs. That is two drivers on one net, and ERC
# said so. The connector is the honest source: a battery really does drive VBAT.
# ─── The floorplan ───────────────────────────────────────────────────────────
# ⛔ ONE BLOCK, NOT NINETY-ONE SCATTERED TUPLES. The coordinates above were
# written next to each part, which reads well and is impossible to reason about:
# you cannot see that two bands collide by looking at two entries forty lines
# apart. This overrides them, and it is arranged the way the board is — three
# rigid islands, and the centre island in horizontal bands.
#
# ⚠️ Anything not named here keeps its inline hint. place.relax() then settles
# the whole thing so no two courtyards touch; these are intentions, not
# millimetres.
PLACEMENT = {
    # ── left rigid island: the first radar ──────────────────────────────────
    "U2": (-91.0, 0.0), "Y2": (-87.0, -6.0),
    "C20": (-95.5, 5.5), "C21": (-92.5, 5.5), "C22": (-89.5, 5.5),
    "C23": (-86.5, 5.5), "C24": (-91.0, -6.0), "C25": (-95.0, -6.0),

    # ── right rigid island: the second radar ────────────────────────────────
    "U6": (91.0, 0.0), "Y3": (87.0, -6.0),
    "C30": (95.5, 5.5), "C31": (92.5, 5.5), "C32": (89.5, 5.5),
    "C33": (86.5, 5.5), "C34": (91.0, -6.0), "C35": (95.0, -6.0),

    # ── centre island, band 1 (x -46..-28): radio front end and the two FFCs ─
    "AE1": (-52.0, 0.0), "C6": (-49.0, 4.0), "L2": (-47.5, 0.0),
    "C11": (-45.0, 4.0),
    "J1": (-41.0, 5.5), "J5": (-41.0, -5.0),
    # ── band 2 (x -28..-4): the processor ───────────────────────────────────
    "U1": (-16.0, 0.0), "Y1": (-25.0, -6.0), "U5": (-25.0, 2.5),
    "Q1": (-29.5, -3.0), "R13": (-27.0, -3.0),
    "C52": (-27.5, 5.0), "L1": (-22.0, 5.0),
    # ⛔ THE 100 nF PARTS HUG THE PINS THEY DECOUPLE. They used to sit in a
    # tidy row along the top of the band, which looks organised and is wrong
    # twice over: a decoupling capacitor two centimetres from its pin is an
    # inductor, and it left the router with no nearby anchor for U1's supply
    # pins — two of them stayed unrouted through five passes. The QFN has VDD on
    # all four sides, so there is a capacitor on all four sides.
    "C4": (-21.5, 1.2),      # beside pin 10, left edge
    "C7": (-15.0, 5.0),      # beside pin 22, bottom edge
    "C8": (-10.5, -1.2),     # beside pin 36, right edge
    "C5": (-17.5, -5.0),     # beside pins 47/48, top edge
    "C1": (-21.5, -3.0), "C2": (-21.5, -1.0), "C3": (-13.0, 5.0),
    "R7": (-12.0, -6.0), "R8": (-9.5, -6.0),
    "U4": (-5.0, -6.0), "C50": (-2.5, -6.0), "C51": (-5.0, 5.0),
    # ── band 3 (x -2..+16): power ───────────────────────────────────────────
    "U3": (4.0, 0.0), "L3": (-1.0, 5.0), "L4": (1.5, 5.0),
    "J2": (9.0, 6.0), "J3": (15.5, 6.0),
    "C40": (-1.0, -5.5), "C41": (1.0, -5.5), "C42": (3.0, -5.5),
    "C43": (5.0, -5.5), "C44": (7.0, -5.5), "C45": (9.0, -5.5),
    "C46": (11.0, -5.5),
    "RT1": (13.0, -5.5), "R1": (15.0, -5.5),
    "R2": (8.5, 0.5), "R3": (10.5, 0.5), "R4": (12.5, 0.5),
    "R5": (14.5, 0.5), "R6": (16.5, 0.5),
    # ── band 4 (x +18..+26): the Qi receiver ────────────────────────────────
    # ⭐ Beside J3, because the coil's two wires and the resonant tank are the
    # one part of this board where centimetres of trace are a tuned element
    # rather than a connection.
    "U11": (21.0, 0.0), "J3": (17.0, 6.0),
    "C80": (17.0, 2.5), "C81": (19.5, 2.5), "C88": (25.0, 2.5),
    "C82": (17.0, -3.0), "C83": (19.5, -3.0),
    "C84": (22.0, -3.0), "C85": (24.5, -3.0),
    "C86": (17.0, -6.5), "C87": (19.5, -6.5),
    "R20": (22.0, -6.5), "R21": (24.0, -6.5), "R22": (26.0, -6.5),
    # ── band 5 (x +28..+55): the FSR front end ──────────────────────────────
    # The connector is 18 mm long and owns the bottom of this band outright.
    "J4": (46.0, -4.8),
    "U8": (30.0, 3.0), "U9": (36.5, 3.0), "U7": (55.0, 2.0),
    "R10": (29.0, -3.5), "R11": (31.5, -3.5), "R12": (34.0, -3.5),
    "C60": (36.5, -1.0), "C61": (29.0, -8.0), "C62": (31.5, -8.0),
    "C63": (34.0, -8.0),
}
# TIA feedback, one row just under the amplifiers
PLACEMENT.update({f"R{40 + i}": (28.5 + i * 2.3, 0.8) for i in range(6)})
# the sixteen column pull-ups, two rows along the top
PLACEMENT.update({f"R{60 + i}": (30.0 + (i % 8) * 2.4, 7.2 - (i // 8) * 2.4)
                  for i in range(16)})

# ⭐ ROTATION IS PART OF THE FLOORPLAN, and leaving it out cost a routing pass.
# The A121's SPI pins are all on one edge of the ball grid. With both sensors
# placed at 0 degrees that edge faces the long side of the board on the left
# sensor and away from the processor on the right one, so the bus has to wrap
# around the package to reach four balls that are 0.5 mm apart. Turning each
# sensor to face the processor is free and removes the congestion instead of
# asking the router to route through it.
# ⭐ U1 IS TURNED AROUND TOO, and for the same reason. Its SPI, the four
# multiplexer selects and the enable all sit on pins 9..21, which is the left
# edge and the bottom of the QFN — and everything they talk to is on the RIGHT
# of the board. At 0 degrees those signals had to wrap around the package. At
# 180 the crystal and the antenna pins end up facing Y1 and AE1, which are on
# the left, and the bus faces the FSR front end. Nothing moved; the part just
# faces the right way.
# ⚠️ U1 IS NOT ROTATED, AND THAT WAS TESTED TWICE. Its SPI, the four multiplexer
# selects and the enable all sit on pins 12..21 — the bottom edge of the QFN —
# and everything they talk to is spread along the board, so turning the part to
# face them is the obvious improvement. At 180 degrees and again at 90,
# Freerouting's autorouter finished in minutes and its OPTIMISER then ground for
# over an hour without ever writing a session file. Three attempts, two angles,
# same outcome. The unrotated board routes in three minutes.
#
# ⛔ A layout the tool cannot finish is worse than one that is a little less
# tidy, and the cost of not rotating is measured rather than assumed: it is the
# cluster of unrouted pins on U1's bottom edge listed in the README.
ROTATION = {"U2": 270, "U6": 90}

PARTS = [(r, v, sy, li, fp, pi) + PLACEMENT.get(r, (x, y))
         for r, v, sy, li, fp, pi, x, y in PARTS]

POWER_FLAGS = ["GND"]

# ⚠️ Nets that legitimately reach one pin. The op-amp spares are unused channels
# whose inputs the datasheet wants tied, and they are named rather than shorted
# so nobody later mistakes them for a mistake.
SINGLE_PIN_NETS = ["VSYS_SNS", "IMU_INT2", "ANT_NC",
                   "QI_CHG", "QI_AD_EN"]

# ⚠️ Parts that carry no netlist at all — the schematic must mark them out of the
# bill of materials to match their footprints.
NOT_IN_BOM = {"FID1", "FID2", "FID3", "FID4", "FID5", "FID6"}


def nets():
    """{net name: [(ref, pad number, electrical type), ...]}"""
    out = {}
    for ref, _v, _s, _fl, _fp, pins, _x, _y in PARTS:
        for number, _name, etype, net in pins:
            out.setdefault(net, []).append((ref, number, etype))
    return out


def part(ref):
    return [p for p in PARTS if p[0] == ref][0]


def pad_nets(ref):
    """{pad number: net name} for one part, as the PCB generator needs it."""
    return {str(number): net for number, _n, _t, net in part(ref)[5]}


def symbols():
    """{symbol name: pins} — one entry per distinct part class."""
    out = {}
    for _r, _v, sym, _fl, _fp, pins, _x, _y in PARTS:
        out.setdefault(sym, pins)
    return out
