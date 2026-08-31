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
    (1,  "P1.00", OUT,     "CAM_PWDN"),
    (2,  "P1.01", OUT,     "CAM_RESET"),
    (3,  "P1.02", OUT,     "MUX_S0"),
    (4,  "P1.03", OUT,     "MUX_S1"),
    (5,  "P1.04/AIN0", IN, "ADC0"),
    (6,  "P1.05/AIN1", IN, "ADC1"),
    (7,  "P1.06/AIN2", IN, "ADC2"),
    (8,  "P1.07/AIN3", IN, "ADC3"),
    (9,  "P1.08", OUT,     "MUX_S2"),
    (10, "VDD", PWR_IN,    "VDD_3V3"),
    (11, "P2.00", OUT,     "MUX_S3"),
    (12, "P2.01/SCK", OUT, "SPI_SCK"),
    (13, "P2.02/SDO", OUT, "SPI_MOSI"),
    (14, "P2.03", OUT,     "CS_RADAR_L"),
    (15, "P2.04/SDI", IN,  "SPI_MISO"),
    (16, "P2.05/CSN", OUT, "CS_RADAR_R"),
    (17, "P2.06", OUT,     "CS_CAM"),
    (18, "P2.07", OUT,     "RADAR_EN"),
    (19, "P2.08", IN,      "RADAR_IRQ_L"),
    (20, "P2.09", IN,      "RADAR_IRQ_R"),
    (21, "P2.10", OUT,     "MUX_EN_N"),
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
    (37, "P1.09", PASSIVE, "SPARE3"),
    (38, "P1.10", PASSIVE, "SPARE1"),
    (39, "P1.11/AIN4", IN, "ADC4"),
    (40, "P1.12/AIN5", IN, "ADC5"),
    (41, "P1.13/AIN6", PASSIVE, "VSYS_SNS"),
    (42, "P1.14/AIN7", PASSIVE, "SPARE2"),
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

# ─── Crystals ────────────────────────────────────────────────────────────────
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
J1_PINS = [
    (1, "GND", PWR_IN, "GND"), (2, "VDD", PWR_IN, "VDD_CAM"),
    (3, "SCL", PASSIVE, "I2C_SCL"), (4, "SDA", PASSIVE, "I2C_SDA"),
    (5, "SCK", PASSIVE, "SPI_SCK"), (6, "MOSI", PASSIVE, "SPI_MOSI"),
    (7, "MISO", PASSIVE, "SPI_MISO"), (8, "CS", PASSIVE, "CS_CAM"),
    (9, "PWDN", PASSIVE, "CAM_PWDN"), (10, "RST", PASSIVE, "CAM_RESET"),
]
J4_PINS = ([(1, "GND", PWR_IN, "GND")]
           + [(2 + i, f"C{i}", PASSIVE, f"FSR_C{i}") for i in range(16)]
           + [(18 + i, f"R{i}", PASSIVE, f"FSR_R{i}") for i in range(6)]
           + [(24, "SHLD", PWR_IN, "GND")])
J2_PINS = [(1, "BAT+", PWR_OUT, "VBAT"), (2, "BAT-", PWR_IN, "GND")]
J3_PINS = [(1, "QI+", PWR_OUT, "VQI"), (2, "QI-", PWR_IN, "GND")]
J5_PINS = [(1, "VDD", PWR_IN, "VDD_3V3"), (2, "SWCLK", PASSIVE, "SWDCLK"),
           (3, "SWDIO", PASSIVE, "SWDIO"), (4, "GND", PWR_IN, "GND")]
AE1_PINS = [(1, "FEED", PASSIVE, "BLE_ANT"), (2, "GND", PWR_IN, "GND")]

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
    ("U7", "CD74HC4067SM96", "MUX16", "Package_SO",
     "SSOP-24_5.3x8.2mm_P0.65mm", U7_PINS, 42.0, 1.5),
    ("U8", "TLV9064IPWR", "OPA_QUAD", "Package_SO",
     "TSSOP-14_4.4x5mm_P0.65mm", U8_PINS, 34.0, -5.5),
    ("U9", "TLV9064IPWR", "OPA_QUAD", "Package_SO",
     "TSSOP-14_4.4x5mm_P0.65mm", U9_PINS, 44.0, -5.5),
    ("Y1", "32 MHz Cl=8pF", "XTAL4", "Crystal",
     "Crystal_SMD_2016-4Pin_2.0x1.6mm", Y1_PINS, -19.5, -6.0),
    ("Y2", "24 MHz", "XTAL4", "Crystal",
     "Crystal_SMD_2016-4Pin_2.0x1.6mm", Y2_PINS, -81.0, -5.5),
    ("Y3", "24 MHz", "XTAL4", "Crystal",
     "Crystal_SMD_2016-4Pin_2.0x1.6mm", Y3_PINS, 81.0, -5.5),
    ("J1", "FFC optics, 10 way", "FFC_10", "Connector_FFC-FPC",
     "Hirose_FH12-10S-0.5SH_1x10-1MP_P0.50mm_Horizontal", J1_PINS, -46.0, 6.0),
    ("J4", "FFC FSR matrix, 24 way", "FFC_24", "Connector_FFC-FPC",
     "Hirose_FH12-24S-0.5SH_1x24-1MP_P0.50mm_Horizontal", J4_PINS, 34.0, -4.5),
    ("J2", "LiPo 3.7V 2000mAh", "CONN2", "Connector_JST",
     "JST_SH_SM02B-SRSS-TB_1x02-1MP_P1.00mm_Horizontal", J2_PINS, 20.0, 6.5),
    ("J3", "Qi RX coil", "CONN2", "Connector_JST",
     "JST_SH_SM02B-SRSS-TB_1x02-1MP_P1.00mm_Horizontal", J3_PINS, 28.0, 6.5),
    ("J5", "SWD debug", "CONN4", "Connector_JST",
     "JST_SH_SM04B-SRSS-TB_1x04-1MP_P1.00mm_Horizontal", J5_PINS, -37.0, 6.0),
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
    # ⛔ The cell thermistor. thermal/budget.py is the whole reason it is here.
    ("RT1", "10k NTC B3380", "R_0402_1005Metric", "NTC", "GND", 2.0, -5.5),
    ("R1", "10k 1%", "R_0402_1005Metric", "VSYS", "NTC", 4.5, -5.5),
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
    "U2": (-88.0, 0.0), "Y2": (-81.5, -5.5),
    "C20": (-93.0, 5.0), "C21": (-90.0, 5.0), "C22": (-87.0, 5.0),
    "C23": (-84.0, 5.0), "C24": (-85.0, -5.5), "C25": (-92.0, -5.5),

    # ── right rigid island: the second radar ────────────────────────────────
    "U6": (88.0, 0.0), "Y3": (81.5, -5.5),
    "C30": (93.0, 5.0), "C31": (90.0, 5.0), "C32": (87.0, 5.0),
    "C33": (84.0, 5.0), "C34": (85.0, -5.5), "C35": (92.0, -5.5),

    # ── centre island, band 1 (x -46..-28): radio front end and the two FFCs ─
    "AE1": (-44.0, 0.0), "C6": (-41.0, 4.0), "L2": (-39.5, 0.0),
    "C11": (-37.0, 4.0),
    "J1": (-34.0, 5.5), "J5": (-34.0, -5.0),
    # ── band 2 (x -28..-4): the processor ───────────────────────────────────
    "U1": (-16.0, 0.0), "Y1": (-25.0, -6.0), "U5": (-25.0, 2.0),
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
    # ── band 4 (x +18..+46): the FSR front end ──────────────────────────────
    # The connector is 18 mm long and owns the bottom of this band outright.
    "J4": (35.0, -4.5),
    "U8": (20.5, 3.0), "U9": (27.0, 3.0), "U7": (39.5, 3.5),
    "R10": (19.0, -3.5), "R11": (21.5, -3.5), "R12": (24.0, -3.5),
    "C60": (26.5, -3.5), "C61": (19.0, -6.5), "C62": (21.5, -6.5),
    "C63": (24.0, -6.5),
}
# TIA feedback, one row just under the amplifiers
PLACEMENT.update({f"R{40 + i}": (18.5 + i * 2.3, 0.0) for i in range(6)})
# the sixteen column pull-ups, two rows along the top
PLACEMENT.update({f"R{60 + i}": (18.5 + (i % 8) * 2.3, 7.0 - (i // 8) * 2.3)
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
# ⚠️ U1 IS NOT ROTATED, AND THAT WAS TESTED. Turning it 180 degrees puts its SPI
# and multiplexer-control pins on the side the FSR front end is on, which is the
# obvious improvement — and it made Freerouting's optimiser grind for over an
# hour without producing a session file, twice. The unrotated board routes in
# three minutes. A layout the tool cannot finish is worse than one that is a
# little less tidy, and the cost is measured rather than assumed: three of the
# multiplexer control lines end up unrouted, listed in the README.
ROTATION = {"U2": 270, "U6": 90}

PARTS = [(r, v, sy, li, fp, pi) + PLACEMENT.get(r, (x, y))
         for r, v, sy, li, fp, pi, x, y in PARTS]

POWER_FLAGS = ["GND"]

# ⚠️ Nets that legitimately reach one pin. The op-amp spares are unused channels
# whose inputs the datasheet wants tied, and they are named rather than shorted
# so nobody later mistakes them for a mistake.
SINGLE_PIN_NETS = ["SPARE1", "SPARE2", "SPARE3", "VSYS_SNS", "IMU_INT2"]


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
