#!/usr/bin/env python3
"""Thermal budget: bursts, average power, and the case that actually matters.

⛔ THE INTERESTING CASE IS NOT THE ONE YOU EXPECT. A 60 GHz radar ping and an
NPU inference sound like the thermal problem, and they are not: both last a
fraction of a second a few dozen times a day, so their average contribution is
microwatts. The case that matters is **wireless charging**, because that is a
watt of loss, for two hours, inside a closed bag, a few millimetres from a
lithium cell, with no airflow at all.

⭐ LUMPED, NOT FEA. Each number here is one thermal resistance or one heat
capacity, chosen so the reasoning is inspectable. A finite-element model would
give a prettier isotherm and would not change the conclusion, which is decided
by two facts: a watt has nowhere to go, and lithium cells have a charging
temperature limit.

⚠️ Every figure is an estimate. Package heat capacities are from bulk properties
and volume, not datasheets; the convection coefficient is the usual still-air
range; charger efficiency is typical rather than measured. The conclusion holds
across a factor of two in any of them, which is the only reason to state it.

Usage:  python3 thermal/budget.py
"""
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

import dimensions as dim          # noqa: E402

AMBIENT = 25.0                    # °C, and generous: a bag in a car is not 25

# ─── what dissipates, and for how long ────────────────────────────────────────
# ⛔ THESE USED TO BE GUESSES ABOUT INVENTED PARTS — "radar ping 1.2 W", "NPU
# inference 0.4 W" — and both parts are gone. Every figure below now comes from
# the datasheet of a component that is actually on the board, and the two that
# changed most changed downwards.
#
# (name, peak watts, seconds per event, events per day)
LOADS = [
    # ⚠️ Two radars now, not one. The A121 datasheet caps "current into any
    # power supply" at 100 mA on a 1.8 V rail; the measurement itself is tens of
    # milliseconds, not the 150 ms the invented transceiver was charged for.
    ("radar ping (U2+U6)", 2 * 0.100 * 1.8, 0.05, 40),
    # Arducam Mega B0435: 56-136 mA at 3.3 V, 42 ms to wake. The capture window
    # is 3 frames of 96x96, which ml/inference_budget.py puts at 28 ms.
    ("camera burst (J1)", 0.136 * 3.3, 0.10, 40),
    # ⭐ Inference is now the CHEAPEST of the three, not the most expensive. A
    # Cortex-M33 at 128 MHz is a few milliamps; the NPU it replaced was charged
    # at 400 mW. See ml/inference_budget.py for the 164 ms.
    ("inference on the M33", 0.006 * 3.3, 0.164, 40),
    ("IR illuminators", 0.60, 0.01, 40),
    # Eight TLV9064 channels at ~0.5 mA each, plus the multiplexer, for the
    # length of one 16-column sweep.
    ("FSR sweep", 0.008 * 0.5e-3 * 3.3 * 1000, 0.005, 86400),
    ("BLE advertising", 0.012, 0.001, 86400),
    ("deep sleep", 25e-6, 1.0, 86400),
]

# ─── package thermal mass, from bulk properties ───────────────────────────────
# (name, mm^3 of package, density kg/m^3, specific heat J/kgK)
PACKAGES = {
    "radar ping (U2+U6)": (5.2 * 5.5 * 0.88, 2000, 800),   # A121 fcCSP50
    "inference on the M33": (6.0 * 6.0 * 0.85, 2000, 800),  # nRF54L15 QFN48
}

# ─── the charging case ────────────────────────────────────────────────────────
QI_INPUT_W = 5.0
QI_EFFICIENCY = 0.80              # coil + rectifier + PMIC, optimistic
CHARGE_HOURS = 2.2
CELL_LIMIT_C = 45.0               # standard Li-ion charge ceiling
MARGIN_K = 5.0                    # nobody designs to the limit itself

# ⚠️ Mirrored in firmware/sb_power.h, and tools/check.py asserts the two agree.
# A safety limit written down twice is a limit that will eventually be written
# down differently.
SB_JEITA_COOL = 10.0
SB_JEITA_WARM = 40.0

# The path from the coil face to open air. ⚠️ Two of these are properties of the
# insert as designed, and they are the reason the answer comes out badly: the
# wall is soft microfibre over foam, which is a thermal insulator, and it is
# wrapped in leather, which is another one.
COIL_R_M = 0.024                  # Qi coil radius, from the CAD
WALL_T_M = 0.003                  # microfibre + foam + leather
WALL_K = 0.05                     # W/mK, textile/foam laminate
SPREADING = 3.0                   # heat leaves an area larger than the coil


def bag_surface_m2():
    """Outer surface of the bag, which is the only place heat leaves from."""
    w = dim.BAG_W_TOP / 1000
    d = dim.BAG_D_TOP / 1000
    h = dim.BAG_MOUTH_Z / 1000
    return 2 * w * h + 2 * d * h + w * d


def main():
    print("SmartBag thermal budget (lumped, estimates)\n")

    print("── duty-cycled average power")
    total_avg = 0.0
    for name, watts, secs, per_day in LOADS:
        avg = watts * secs * per_day / 86400
        total_avg += avg
        print(f"   {name:<22} {watts * 1000:>7.1f} mW peak  x {secs:>5.3f} s "
              f"x {per_day:>5} /day  ->  {avg * 1e6:>8.1f} uW average")
    print(f"   {'TOTAL':<22} {total_avg * 1000:>34.2f} mW average")
    # ⭐ Worth naming out loud, because it moved. The bursts everyone worries
    # about are duty-cycled into irrelevance; what is left is whatever runs
    # continuously, and after the FSR front end grew six amplifiers that is the
    # front end rather than the radio or the radar.
    top = max(LOADS, key=lambda L: L[1] * L[2] * L[3])
    share = top[1] * top[2] * top[3] / 86400 / total_avg * 100
    print(f"   dominated by {top[0]!r}: {share:.0f}% of the average, and it is "
          "the one")
    print("   thing here that is not a burst — it runs every second the bag is "
          "shut.")

    print("\n── burst temperature rise (adiabatic, package only)")
    # ⚠️ Adiabatic is the pessimistic bound: for a 150 ms burst almost no heat
    # has left the package yet, so all of it goes into raising its own
    # temperature. Anything the board spreads makes this smaller.
    for name, watts, secs, _ in LOADS:
        if name not in PACKAGES:
            continue
        vol_mm3, rho, c = PACKAGES[name]
        heat_capacity = vol_mm3 * 1e-9 * rho * c
        rise = watts * secs / heat_capacity
        print(f"   {name:<22} C = {heat_capacity * 1000:>5.1f} mJ/K  ->  "
              f"+{rise:>4.1f} K per burst")

    print("\n── steady state, whole bag")
    area = bag_surface_m2()
    h_still = 8.0                 # W/m^2K, natural convection + radiation
    rise = total_avg / (h_still * area)
    print(f"   bag surface {area * 1e4:.0f} cm2, h = {h_still} W/m2K")
    print(f"   {total_avg * 1000:.2f} mW  ->  +{rise:.3f} K. "
          "Sensing does not heat this bag.")

    print("\n── charging, which is the real case")
    lost = QI_INPUT_W * (1 - QI_EFFICIENCY)
    bag_rise = lost / (h_still * area)
    print(f"   {QI_INPUT_W:.1f} W in at {QI_EFFICIENCY * 100:.0f}% -> "
          f"{lost:.2f} W dissipated for {CHARGE_HOURS:.1f} h")
    print(f"   whole-bag rise: +{bag_rise:.1f} K")

    # ⛔ The whole-bag number is the reassuring one and it is the wrong one for
    # the COIL. The loss is not spread over the bag: it is in the coil and the
    # PMIC, and what decides the temperature there is the series resistance from
    # the coil face to open air — whose first term is the insert wall, which was
    # chosen to be soft, and soft means insulating.
    coil_area = math.pi * (COIL_R_M ** 2)       # the Qi coil, from the CAD
    r_wall = WALL_T_M / (WALL_K * coil_area * SPREADING)
    r_conv = 1.0 / (h_still * coil_area * SPREADING)
    coil_rise = lost * (r_wall + r_conv)
    coil_temp = AMBIENT + bag_rise + coil_rise
    print(f"   coil face {coil_area * 1e4:.1f} cm2, spreading x{SPREADING:.0f} "
          f"-> {coil_area * SPREADING * 1e4:.0f} cm2 effective")
    print(f"   wall {WALL_T_M * 1000:.0f} mm of k={WALL_K} foam: "
          f"{r_wall:.0f} K/W   +   surface: {r_conv:.0f} K/W")
    print(f"   coil face reaches ~{coil_temp:.0f} C")

    # ⭐ AND THE CELL IS NO LONGER ON TOP OF IT. Every earlier run of this file
    # printed a cell near 60 C, and that number rested on one sentence in the
    # docstring: the Qi coil sits directly under the LiPo. It did — because the
    # cell was a 148 mm semi-custom pouch drawn to fill the floor, and there was
    # nowhere else for the coil to go. The cell is now a 53 mm catalogue part
    # (Jauch LP523450JU) and dimensions.py puts the two SIDE BY SIDE.
    #
    # ⚠️ Which is worth computing rather than asserting. The heat now has to
    # reach the cell along the base plate — 62 mm of the same foam, through a
    # section the width of the cell — while an easier path to ambient sits right
    # above the coil. Two resistances in a divider, and the divider is lopsided.
    lateral_m = abs(dim.CELL_X - dim.QI_X) / 1000
    lateral_area = (dim.INS_BASE_H / 1000) * (dim.CELL_W / 1000)
    r_lateral = lateral_m / (WALL_K * lateral_area)
    cell_area = (dim.CELL_L / 1000) * (dim.CELL_W / 1000)
    r_cell_air = 1.0 / (h_still * cell_area * SPREADING)
    coupling = r_cell_air / (r_lateral + r_cell_air)
    cell_rise = coil_rise * coupling
    cell_temp = AMBIENT + bag_rise + cell_rise
    print()
    print(f"   cell is {lateral_m * 1000:.0f} mm to one side: "
          f"{r_lateral:.0f} K/W along the plate against {r_cell_air:.0f} K/W "
          f"straight to air")
    print(f"   so it takes {coupling * 100:.1f}% of the coil's rise: "
          f"+{cell_rise:.2f} K")
    print(f"   cell temperature ~ {cell_temp:.0f} C against a "
          f"{CELL_LIMIT_C:.0f} C charging limit")

    print()
    if cell_temp > CELL_LIMIT_C:
        print("   ⛔ Charging as specified puts the cell over its limit.")
        print("      The Qi coil sits directly under the LiPo — that stack was")
        print("      chosen so the coil faces the charging pad, and it also "
              "puts the")
        print("      hottest part of the system against the one component with "
              "a")
        print("      temperature limit that matters.")
        print()
        # ⭐ Invert the model: how much input power fits under the limit?
        headroom = CELL_LIMIT_C - MARGIN_K - AMBIENT
        safe_lost = headroom / (r_wall + r_conv + 1 / (h_still * area))
        safe_in = safe_lost / (1 - QI_EFFICIENCY)
        slower = QI_INPUT_W / safe_in
        print(f"      Inverting the same model: {headroom:.0f} K of headroom to "
              f"{CELL_LIMIT_C:.0f} C")
        print(f"      minus {MARGIN_K:.0f} K of margin allows "
              f"{safe_lost * 1000:.0f} mW of loss, so {safe_in:.1f} W in —")
        print(f"      {slower:.1f}x slower, {CHARGE_HOURS * slower:.0f} hours "
              "for a full charge.")
        print()
        print("      What has to change, in order of preference:")
        print("        - interlock: charge only while the Hall sensor says the "
              "bag is")
        print("          open. The firmware already knows. Costs nothing.")
        print(f"        - throttle to {safe_in:.1f} W in, which is the number "
              "above;")
        print("        - a thermistor on the cell and a real charge-temperature "
              "loop,")
        print("          which is what a shipping product would do anyway.")
        print()
        print("      ✅ ALL THREE ARE NOW IMPLEMENTED, which is why this "
              "section still")
        print("      prints a number that no longer happens. RT1 is a 10k NTC "
              "on the")
        print("      cell and U3 is an nPM1300 that reads it — this analysis "
              "is why")
        print("      both are on the board — and firmware/sb_power.c holds the "
              "policy:")
        print("      full current only with the bag OPEN and the cell between "
              f"{SB_JEITA_COOL:.0f} and")
        print(f"      {SB_JEITA_WARM:.0f} C, {safe_in:.1f} W otherwise, and "
              "nothing at all if the")
        print("      thermistor has come off. 264 host assertions, including a "
              "sweep")
        print("      over every cell temperature with the bag shut.")
        print()
        print("      ⚠️ The figure above is what the hardware does UNCONFIGURED, "
              "and it")
        print("      is kept because that is still true on the first boot "
              "before")
        print("      anything writes to the PMIC. A limit is only real once "
              "somebody")
        print("      has set it.")
    else:
        print(f"   ✅ THE CELL IS OUT OF IT: {cell_temp:.0f} C, well inside its "
              "window, and")
        print("      not because the analysis was wrong — because the geometry "
              "changed.")
        print("      Choosing a cell you can actually order made it 53 mm "
              "instead of")
        print("      148, which left room to put the coil BESIDE it instead of "
              "under.")
        print()
        # ⛔ AND THE HEADLINE MOVES RATHER THAN DISAPPEARING. A watt still has
        # nowhere to go; all that changed is what is sitting on top of it. The
        # coil face is against microfibre, foam and then leather, and the number
        # below is what a person would touch and what those materials have to
        # survive for two hours at a time.
        print(f"   ⚠️ THE COIL FACE IS STILL AT ~{coil_temp:.0f} C, and that is "
              "now the finding.")
        print("      Nothing there has a 45 C limit, but leather does age and a "
              "bag is")
        print("      a thing people hold. The interlock earns its place here "
              "instead:")
        headroom = 45.0 - AMBIENT
        safe_lost = headroom / (r_wall + r_conv + 1 / (h_still * area))
        safe_in = safe_lost / (1 - QI_EFFICIENCY)
        print(f"      {safe_in:.1f} W in holds the coil face at 45 C, and "
              f"{QI_INPUT_W:.0f} W is fine")
        print("      with the bag open. firmware/sb_power.c already refuses to "
              "charge")
        print("      at full current with the bag shut — written for the cell, "
              "kept for")
        print("      the coil, and the number it uses comes from this line.")


if __name__ == "__main__":
    main()
