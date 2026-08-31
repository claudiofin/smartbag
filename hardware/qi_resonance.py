#!/usr/bin/env python3
"""The two resonant capacitors, from the coil's inductance and the WPC spec.

⛔ THESE CANNOT BE COPIED FROM THE CHIP'S DATASHEET, and TI says so: "These two
capacitors must be sized correctly per the WPC v1.2 specification... the
receiver designer will be required to take inductance measurements with a
standard test fixture." They belong to the COIL, not to the receiver IC — change
the coil and both change.

⭐ WHAT THE SPECIFICATION FIXES is not the capacitance but two frequencies. The
series capacitor resonates with the coil at 100 kHz, which is where a Qi
transmitter drives; the parallel one resonates at 1 MHz, which is what the
transmitter pings with to find out whether anything is there at all. Given a
coil inductance, both values follow.

⚠️ AND THE INDUCTANCE THAT MATTERS IS NOT THE ONE ON THE COIL'S DATASHEET. WPC
specifies L' — the inductance measured with the receiver's own shielding in
place and a reference transmitter coil against it — and that is typically 10 to
20 percent above the free-air figure. The numbers below use the datasheet value
because there is nothing built to measure; they are a starting point for a first
article, not a final BOM line. The same caveat as the antenna match, for the
same reason: a component whose value depends on an assembly nobody has built.

Usage:  python3 hardware/qi_resonance.py
"""
import math

# Würth 760308103305, WE-WPCC receiver coil: 8.8 µH, 44 x 45 x 0.72 mm.
COIL_UH = 8.8
COIL_MPN = "760308103305"

F_SERIES = 100e3        # WPC: the power transfer frequency band
F_PARALLEL = 1.0e6      # WPC: the transmitter's analogue ping


def cap_for(f_hz, l_h):
    return 1.0 / ((2 * math.pi * f_hz) ** 2 * l_h)


def nearest_e12(farads):
    """The nearest value anybody actually stocks."""
    e12 = [1.0, 1.2, 1.5, 1.8, 2.2, 2.7, 3.3, 3.9, 4.7, 5.6, 6.8, 8.2]
    decade = 10 ** math.floor(math.log10(farads))
    best = min(e12, key=lambda m: abs(m * decade - farads))
    return best * decade


def main():
    l_h = COIL_UH * 1e-6
    cs = cap_for(F_SERIES, l_h)
    cd = cap_for(F_PARALLEL, l_h)
    print(f"Qi resonant network for {COIL_MPN} ({COIL_UH} uH)\n")
    print(f"  Cs (series, {F_SERIES/1e3:.0f} kHz):   "
          f"{cs*1e9:7.1f} nF  ->  {nearest_e12(cs)*1e9:.0f} nF")
    print(f"  Cd (parallel, {F_PARALLEL/1e6:.0f} MHz):  "
          f"{cd*1e9:7.2f} nF  ->  {nearest_e12(cd)*1e9:.1f} nF")
    print()
    # ⚠️ The sensitivity is worth printing, because it decides whether the
    # datasheet's L is close enough to start with.
    for pct in (10, 20):
        alt = cap_for(F_SERIES, l_h * (1 + pct / 100))
        print(f"  if L' measures {pct}% high, Cs becomes {alt*1e9:.0f} nF "
              f"({(alt/cs - 1)*100:+.0f}%)")
    print()
    print("  ⚠️ Both are C0G/NP0 and they carry the full coil current at "
          "100 kHz.")
    print("     A capacitor whose value drifts with voltage detunes the tank, "
          "so X7R")
    print("     is not a substitute here however close its nominal value is.")


if __name__ == "__main__":
    main()
