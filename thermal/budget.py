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
# (name, peak watts, seconds per event, events per day)
LOADS = [
    ("radar ping (U2)", 1.20, 0.15, 40),
    ("NPU inference (U1)", 0.40, 0.12, 40),
    ("IR illuminators", 0.60, 0.01, 40),
    ("FSR sweep", 0.006, 0.005, 86400),      # the 1 Hz sentinel
    ("BLE advertising", 0.012, 0.001, 86400),
    ("deep sleep", 25e-6, 1.0, 86400),
]

# ─── package thermal mass, from bulk properties ───────────────────────────────
# (name, mm^3 of package, density kg/m^3, specific heat J/kgK)
PACKAGES = {
    "radar ping (U2)": (5.0 * 5.0 * 0.9, 2000, 800),
    "NPU inference (U1)": (6.0 * 6.0 * 0.9, 2000, 800),
}

# ─── the charging case ────────────────────────────────────────────────────────
QI_INPUT_W = 5.0
QI_EFFICIENCY = 0.80              # coil + rectifier + PMIC, optimistic
CHARGE_HOURS = 2.2
CELL_LIMIT_C = 45.0               # standard Li-ion charge ceiling
MARGIN_K = 5.0                    # nobody designs to the limit itself

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

    # ⛔ The whole-bag number is the reassuring one and it is the wrong one. The
    # loss is not spread over the bag: it is in the coil and the PMIC, and the
    # cell is sitting on top of them. What decides the cell temperature is the
    # series resistance from the coil face to open air, and the first term in it
    # is the insert wall — which was chosen to be soft, and soft means insulating.
    coil_area = math.pi * (COIL_R_M ** 2)       # the Qi coil, from the CAD
    r_wall = WALL_T_M / (WALL_K * coil_area * SPREADING)
    r_conv = 1.0 / (h_still * coil_area * SPREADING)
    local_rise = lost * (r_wall + r_conv)
    cell_temp = AMBIENT + bag_rise + local_rise
    print(f"   coil face {coil_area * 1e4:.1f} cm2, spreading x{SPREADING:.0f} "
          f"-> {coil_area * SPREADING * 1e4:.0f} cm2 effective")
    print(f"   wall {WALL_T_M * 1000:.0f} mm of k={WALL_K} foam: "
          f"{r_wall:.0f} K/W   +   surface: {r_conv:.0f} K/W")
    print(f"   local rise at the cell: +{local_rise:.0f} K")
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
        print("      ⚠️ None of these are implemented. The firmware has no "
              "charge")
        print("      control and the board has no cell thermistor.")
    else:
        print(f"   Cell stays at {cell_temp:.0f} C, inside its window.")


if __name__ == "__main__":
    main()
