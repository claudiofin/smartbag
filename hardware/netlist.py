#!/usr/bin/env python3
"""The netlist: pins, nets and part classes. One source, three consumers.

⛔ WHY THIS FILE EXISTS. The board used to have no schematic at all — pads with
no nets, routing drawn for looks, and a README that had to open by admitting
ERC and DRC could not pass. Adding a schematic by hand next to a *generated*
board would have created the classic divergence: two descriptions of the same
circuit, drifting. Instead the connectivity is declared once here and consumed
by everything that needs it:

  hardware/generate_schematic.py  -> symbols + schematic + ERC
  hardware/generate_pcb.py        -> nets on the pads, for schematic parity
  tools/check.py                  -> assertions about the whole thing

⚠️ STILL A DESIGN STUDY. The pinouts are plausible allocations for a component
*class*, not the pinout of a chosen part: no real SoC has GND on exactly pins 3
and 4. What is real is that every pin has a role, every net has at least a
driver and a load, and the whole thing is electrically consistent enough for
ERC to have an opinion about it.

⭐ PIN ORDER IS THE FLOORPLAN. The FSR columns leave U1 on pins 27..42 in the
same order they arrive at J4, and the two parts face each other on the board.
That is deliberate: it makes the 22-line bus route as parallel lanes with no
crossings, which is why this layout needs no autorouter.
"""

# Electrical types, as KiCad names them.
PWR_IN, PWR_OUT, IN, OUT, BIDI, PASSIVE = (
    "power_in", "power_out", "input", "output", "bidirectional", "passive")


def _bus(prefix, n, etype, start_pin):
    """`n` consecutive pins carrying prefix0..prefix{n-1}."""
    return [(start_pin + i, f"{prefix}{i}", etype, f"{prefix}{i}") for i in range(n)]


# ─── U1: SoC + NPU ────────────────────────────────────────────────────────────
# 48 signal pins plus the thermal pad. Budgeted exactly: the FSR matrix alone
# takes 22 of them, which is what makes 16x6 the largest matrix this part can
# drive without adding a multiplexer.
U1_PINS = [
    (1, "VDD_CORE", PWR_IN, "VDD_1V8"),
    (2, "VDD_IO", PWR_IN, "VDD_3V3"),
    (3, "GND", PWR_IN, "GND"),
    (4, "GND", PWR_IN, "GND"),
    (5, "XI", PASSIVE, "XTAL_I"),
    (6, "XO", PASSIVE, "XTAL_O"),
    (7, "~{RESET}", IN, "nRESET"),
    (8, "SWDIO", BIDI, "SWDIO"),
    (9, "SWCLK", IN, "SWCLK"),
    (10, "ANT", PASSIVE, "BLE_ANT"),
    (11, "SPI_SCK", OUT, "SPI_SCK"),
    (12, "SPI_MOSI", OUT, "SPI_MOSI"),
    (13, "SPI_MISO", IN, "SPI_MISO"),
    (14, "SPI_CS", OUT, "SPI_CS"),
    (15, "RADAR_IRQ", IN, "RADAR_IRQ"),
    (16, "SDA", BIDI, "I2C_SDA"),
    (17, "SCL", OUT, "I2C_SCL"),
    (18, "IMU_INT", IN, "IMU_INT"),
    (19, "HALL", IN, "HALL"),
    (20, "TOF_INT", IN, "TOF_INT"),
    (21, "CAM_CLK", OUT, "CAM_CLK"),
    (22, "CAM_DATA", IN, "CAM_DATA"),
    (23, "CAM_PWDN", OUT, "CAM_PWDN"),
    (24, "LED_PWM", OUT, "LED_PWM"),
    (25, "VBAT_SNS", IN, "VBAT_SNS"),
    (26, "PMIC_EN", OUT, "PMIC_EN"),
] + _bus("FSR_C", 16, OUT, 27) + _bus("FSR_R", 6, IN, 43) + [
    (49, "EP", PWR_IN, "GND"),
]

# ─── U2: 60 GHz mmWave transceiver ────────────────────────────────────────────
# ⚠️ Pins 15..40 are all GND. That is not padding: an mmWave QFN really is
# mostly ground, because every signal pin needs a return next to it.
U2_PINS = [
    (1, "VDD", PWR_IN, "VDD_1V8"),
    (2, "VDD", PWR_IN, "VDD_1V8"),
    (3, "GND", PWR_IN, "GND"),
    (4, "GND", PWR_IN, "GND"),
    (5, "SCK", IN, "SPI_SCK"),
    (6, "MOSI", IN, "SPI_MOSI"),
    (7, "MISO", OUT, "SPI_MISO"),
    (8, "~{CS}", IN, "SPI_CS"),
    (9, "IRQ", OUT, "RADAR_IRQ"),
    (10, "~{RESET}", IN, "nRESET"),
    (11, "TX_A1", PASSIVE, "ANT_A1"),
    (12, "TX_A2", PASSIVE, "ANT_A2"),
    (13, "RX_A1", PASSIVE, "ANT_A1"),
    (14, "RX_A2", PASSIVE, "ANT_A2"),
] + [(i, "GND", PWR_IN, "GND") for i in range(15, 41)] + [
    (41, "EP", PWR_IN, "GND"),
]

# ─── U3: PMIC ─────────────────────────────────────────────────────────────────
# The only part that DRIVES the rails, which is what stops ERC complaining that
# every VDD pin in the design is undriven.
U3_PINS = [
    (1, "VBAT", PWR_IN, "VBAT"),
    (2, "VIN_QI", PWR_IN, "VQI"),
    (3, "EN", IN, "PMIC_EN"),
    (4, "SW1", PASSIVE, "SW1"),
    (5, "SW2", PASSIVE, "SW2"),
    (6, "VOUT_3V3", PWR_OUT, "VDD_3V3"),
    (7, "VOUT_1V8", PWR_OUT, "VDD_1V8"),
    (8, "FB", IN, "VDD_3V3"),
    (9, "PGND", PWR_IN, "GND"),
    (10, "AGND", PWR_IN, "GND"),
    (11, "VBAT_SNS", OUT, "VBAT_SNS"),
] + [(i, "GND", PWR_IN, "GND") for i in range(12, 25)] + [
    (25, "EP", PWR_IN, "GND"),
]

# ─── U4: 6-axis IMU (LGA-14) ──────────────────────────────────────────────────
U4_PINS = [
    (1, "VDD", PWR_IN, "VDD_3V3"),
    (2, "GND", PWR_IN, "GND"),
    (3, "SDA", BIDI, "I2C_SDA"),
    (4, "SCL", IN, "I2C_SCL"),
    (5, "INT1", OUT, "IMU_INT"),
    # ⚠️ CS high and SDO low select I2C mode and address 0. Tying them is not
    # decoration: left floating the part would come up in SPI mode and the bus
    # in the schematic would be a lie.
    (6, "~{CS}", IN, "VDD_3V3"),
    (7, "SDO", IN, "GND"),
    (8, "VDDIO", PWR_IN, "VDD_3V3"),
] + [(i, "GND", PWR_IN, "GND") for i in range(9, 15)]

# ─── U5: Hall switch on the zip closure ───────────────────────────────────────
U5_PINS = [
    (1, "VDD", PWR_IN, "VDD_3V3"),
    (2, "GND", PWR_IN, "GND"),
    (3, "OUT", OUT, "HALL"),
]

# ─── Y1: 32 MHz crystal ───────────────────────────────────────────────────────
Y1_PINS = [
    (1, "XI", PASSIVE, "XTAL_I"),
    (2, "GND", PASSIVE, "GND"),
    (3, "XO", PASSIVE, "XTAL_O"),
    (4, "GND", PASSIVE, "GND"),
]

# ─── J1: FFC to the optics module (10 ways) ───────────────────────────────────
# ⭐ The camera shares I2C with the IMU. That is what freed the two pins the FSR
# matrix needed: with a private bus the budget came to 51 pins on a 48-pin part.
J1_PINS = [
    (1, "GND", PASSIVE, "GND"),
    (2, "VDD", PASSIVE, "VDD_3V3"),
    (3, "SCL", PASSIVE, "I2C_SCL"),
    (4, "SDA", PASSIVE, "I2C_SDA"),
    (5, "CAM_CLK", PASSIVE, "CAM_CLK"),
    (6, "CAM_DATA", PASSIVE, "CAM_DATA"),
    (7, "CAM_PWDN", PASSIVE, "CAM_PWDN"),
    (8, "LED_PWM", PASSIVE, "LED_PWM"),
    (9, "TOF_INT", PASSIVE, "TOF_INT"),
    (10, "GND", PASSIVE, "GND"),
]

# ─── J4: FFC to the FSR matrix (24 ways) ──────────────────────────────────────
# 16 columns + 6 rows + 2 grounds = 24. This is the constraint that fixes the
# matrix at 16x6 rather than 16x16.
J4_PINS = ([(1, "GND", PASSIVE, "GND")]
           + [(2 + i, f"C{i}", PASSIVE, f"FSR_C{i}") for i in range(16)]
           + [(18 + i, f"R{i}", PASSIVE, f"FSR_R{i}") for i in range(6)]
           + [(24, "GND", PASSIVE, "GND")])

J2_PINS = [(1, "VBAT", PASSIVE, "VBAT"), (2, "GND", PASSIVE, "GND")]

# ─── J5: SWD debug connector ──────────────────────────────────────────────────
# ⛔ ADDED BECAUSE ERC WAS RIGHT. SWDIO and SWCLK went nowhere: the board simply
# had no way to program or debug the part on it. That is not an ERC quirk to
# suppress, it is a missing connector, and the fix is the connector.
#
# ⚠️ The pins are BIDIRECTIONAL, not passive. That is electrically accurate — a
# debugger drives SWCLK and both ends drive SWDIO — and it is also what lets ERC
# see U1's SWCLK input as driven. Declaring them passive would have left the
# error in place while pretending to have fixed it.
J5_PINS = [
    (1, "SWDIO", BIDI, "SWDIO"),
    (2, "SWCLK", BIDI, "SWCLK"),
    (3, "~{RESET}", BIDI, "nRESET"),
    (4, "GND", PASSIVE, "GND"),
]

# ─── AE1: 2.4 GHz chip antenna ────────────────────────────────────────────────
# ⛔ ALSO ADDED BECAUSE IT WAS MISSING. The SoC had an ANT pin connected to
# nothing: a BLE radio with no antenna. The renders never showed it because an
# antenna that is not there does not render as anything.
AE1_PINS = [
    (1, "FEED", PASSIVE, "BLE_ANT"),
    (2, "GND", PASSIVE, "GND"),
]
J3_PINS = [(1, "VQI", PASSIVE, "VQI"), (2, "GND", PASSIVE, "GND")]


def _two(a, b):
    return [(1, "1", PASSIVE, a), (2, "2", PASSIVE, b)]


# (ref, value, symbol, footprint library, footprint, pins, x, y on the board)
# ⚠️ The x,y are the SAME numbers the PCB generator places the parts at. Keeping
# them here rather than in the layout is what lets check.py verify that a bus
# leaves U1 on the side facing the connector it goes to.
PARTS = [
    ("U1", "SoC+NPU BLE 5.4", "SOC_NPU_48", "Package_DFN_QFN",
     "QFN-48-1EP_6x6mm_P0.4mm_EP4.6x4.6mm", U1_PINS, -18.0, 0.0),
    ("U2", "mmWave 60GHz TRX", "MMWAVE_40", "Package_DFN_QFN",
     "QFN-40-1EP_5x5mm_P0.4mm_EP3.8x3.8mm", U2_PINS, -6.0, 2.0),
    ("U3", "PMIC buck-boost", "PMIC_24", "Package_DFN_QFN",
     "QFN-24-1EP_4x4mm_P0.5mm_EP2.8x2.8mm", U3_PINS, 4.0, 2.5),
    ("U4", "6-axis IMU", "IMU_14", "Package_LGA",
     "Bosch_LGA-14_3x2.5mm_P0.5mm", U4_PINS, 2.0, -6.5),
    ("U5", "Hall, zip", "HALL_3", "Package_TO_SOT_SMD",
     "SOT-23", U5_PINS, -42.0, 6.5),
    ("Y1", "32 MHz", "XTAL_4", "Crystal",
     "Crystal_SMD_3225-4Pin_3.2x2.5mm", Y1_PINS, -34.0, 6.5),
    ("J1", "FFC optics, 10 way", "FFC_10", "Connector_FFC-FPC",
     "Hirose_FH12-10S-0.5SH_1x10-1MP_P0.50mm_Horizontal", J1_PINS, -8.0, -7.0),
    ("J4", "FFC FSR matrix, 24 way", "FFC_24", "Connector_FFC-FPC",
     "Hirose_FH12-24S-0.5SH_1x24-1MP_P0.50mm_Horizontal", J4_PINS, 30.0, -6.0),
    ("J2", "LiPo 3.7V 2000mAh", "CONN_2", "Connector_JST",
     "JST_SH_SM02B-SRSS-TB_1x02-1MP_P1.00mm_Horizontal", J2_PINS, 42.0, 6.0),
    ("J3", "Qi RX coil", "CONN_2", "Connector_JST",
     "JST_SH_SM02B-SRSS-TB_1x02-1MP_P1.00mm_Horizontal", J3_PINS, 34.0, 6.0),
    ("J5", "SWD debug", "CONN_4", "Connector_JST",
     "JST_SH_SM04B-SRSS-TB_1x04-1MP_P1.00mm_Horizontal", J5_PINS, -34.0, -6.5),
    ("AE1", "2.4 GHz chip antenna", "ANTENNA", "RF_Antenna",
     "Johanson_2450AT43F0100_2400-2500Mhz", AE1_PINS, -44.0, 0.0),

    # Decoupling and the few discretes that make the rails real.
    ("C1", "100n", "C", "Capacitor_SMD", "C_0402_1005Metric",
     _two("VDD_1V8", "GND"), -25.0, -6.5),
    ("C2", "100n", "C", "Capacitor_SMD", "C_0402_1005Metric",
     _two("VDD_3V3", "GND"), -22.5, -6.5),
    ("C3", "4u7", "C", "Capacitor_SMD", "C_0402_1005Metric",
     _two("VDD_1V8", "GND"), -20.0, -6.5),
    ("C4", "1u", "C", "Capacitor_SMD", "C_0402_1005Metric",
     _two("VDD_3V3", "GND"), -13.0, 6.5),
    ("C5", "100n", "C", "Capacitor_SMD", "C_0402_1005Metric",
     _two("VDD_1V8", "GND"), -10.5, 6.5),
    ("C6", "10u", "C", "Capacitor_SMD", "C_0402_1005Metric",
     _two("VBAT", "GND"), -8.0, 6.5),
    ("C7", "22u", "C", "Capacitor_SMD", "C_0402_1005Metric",
     _two("VDD_3V3", "GND"), 19.0, 6.5),
    ("C8", "22u", "C", "Capacitor_SMD", "C_0402_1005Metric",
     _two("VDD_1V8", "GND"), 21.5, 6.5),
    ("R1", "10k", "R", "Resistor_SMD", "R_0402_1005Metric",
     _two("nRESET", "VDD_3V3"), -28.5, 6.5),
    ("R2", "10k", "R", "Resistor_SMD", "R_0402_1005Metric",
     _two("I2C_SDA", "VDD_3V3"), -26.0, 6.5),
    ("R3", "10k", "R", "Resistor_SMD", "R_0402_1005Metric",
     _two("I2C_SCL", "VDD_3V3"), 9.5, -1.0),
    ("R4", "100k", "R", "Resistor_SMD", "R_0402_1005Metric",
     _two("VBAT_SNS", "GND"), 9.5, 1.0),
    ("L1", "2u2", "L", "Inductor_SMD", "L_0603_1608Metric",
     _two("SW1", "VDD_3V3"), 12.0, 6.5),
    ("L2", "1u0", "L", "Inductor_SMD", "L_0603_1608Metric",
     _two("SW2", "VDD_1V8"), 15.5, 6.5),
]

# ⚠️ Nets that no `power_out` pin drives. Without an explicit flag ERC reports
# every power_in pin on them as undriven — correctly, because as far as the
# schematic knows a battery connector is just two passive pins.
POWER_FLAGS = ["VBAT", "VQI", "GND"]

# Nets that legitimately reach only one pin. The two mmWave feeds are copper
# geometry on the board — patch arrays, not components — so there is nothing on
# the far end to draw a symbol for.
SINGLE_PIN_NETS = ["ANT_A1", "ANT_A2"]


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
    return {number: net for number, _n, _t, net in part(ref)[5]}


def symbols():
    """{symbol name: pins} — one entry per distinct part class."""
    out = {}
    for _r, _v, sym, _fl, _fp, pins, _x, _y in PARTS:
        out.setdefault(sym, pins)
    return out
