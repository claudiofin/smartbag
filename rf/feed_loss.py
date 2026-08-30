#!/usr/bin/env python3
"""What it costs to feed a 60 GHz antenna from 90 mm away. Closed-form, not FDTD.

⛔ THIS EXISTS BECAUSE THE ROUTER COULD NOT DRAW THE FEED, and asking why turned
up something worse than a routing problem. The transceiver sits at x = -6 and
the two antenna islands at x = ±93: the microstrip runs are 87 mm and 99 mm.
At 60 GHz that is not a long trace, it is an attenuator.

⭐ WHY ANALYTIC AND NOT SIMULATED. The loss per unit length of a uniform
microstrip is a solved problem with standard closed forms (Hammerstad-Jensen for
the impedance, the usual dielectric and conductor terms for the loss). A
full-wave run would give the same number after an hour of meshing. FDTD earns
its keep on the patch, where the geometry is the answer; here it would only
confirm arithmetic.

⚠️ Estimates. εr and tan δ are assumed, the roughness factor is a rule of thumb,
and nothing here accounts for bends, the flex, or the connector. The conclusion
survives a factor of two in either direction, which is the only reason it is
worth stating.

Usage:  python3 rf/feed_loss.py
"""
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "hardware"))

import dimensions as dim          # noqa: E402
import netlist as nl              # noqa: E402

F = 60e9
C0 = 299792458.0
EPS_R = 3.4
TAN_D = 0.008
SIGMA_CU = 5.8e7          # S/m
ROUGHNESS = 1.6           # multiplier on conductor loss; electro-deposited foil
Z0_TARGET = 50.0


def eps_eff(w_h):
    return (EPS_R + 1) / 2 + (EPS_R - 1) / 2 * (1 + 12 / w_h) ** -0.5


def z0_microstrip(w_h):
    """Hammerstad, the wide-line branch — a 50 ohm line on 0.25 mm is wide."""
    e = eps_eff(w_h)
    if w_h < 1:
        return 60 / math.sqrt(e) * math.log(8 / w_h + w_h / 4)
    return 120 * math.pi / (math.sqrt(e) * (w_h + 1.393
                                            + 0.667 * math.log(w_h + 1.444)))


def width_for_50r(h_mm):
    lo, hi = 0.1, 20.0
    for _ in range(80):
        mid = (lo + hi) / 2
        if z0_microstrip(mid) > Z0_TARGET:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2 * h_mm


def losses(h_mm):
    w_mm = width_for_50r(h_mm)
    e = eps_eff(w_mm / h_mm)
    lam0 = C0 / F

    # Dielectric: the standard filling-factor form, in dB per metre.
    a_d = (27.3 * (EPS_R * (e - 1)) / (math.sqrt(e) * (EPS_R - 1))
           * TAN_D / lam0)

    # Conductor: surface resistance over the strip, roughened.
    rs = math.sqrt(math.pi * F * 4e-7 * math.pi / SIGMA_CU)
    a_c = 8.686 * rs / (Z0_TARGET * (w_mm * 1e-3)) * ROUGHNESS

    return w_mm, e, a_d / 100.0, a_c / 100.0      # dB/cm


def feed_lengths():
    """Straight-line distance from the transceiver to each antenna island."""
    _r, _v, _s, _l, _f, pins, ux, uy = nl.part("U2")
    out = {}
    for net, x_island in (("ANT_A1", -93.5), ("ANT_A2", 81.5)):
        out[net] = abs(x_island - ux)
    return out


def main():
    h = dim.ANTENNA_SUBSTRATE_T
    w, e, a_d, a_c = losses(h)
    total = a_d + a_c
    print("60 GHz microstrip feed, closed-form")
    print(f"  substrate {h} mm, eps_r {EPS_R}, tan d {TAN_D}")
    print(f"  50 ohm line is {w:.3f} mm wide, eps_eff {e:.2f}")
    print(f"  dielectric {a_d:.2f} dB/cm + conductor {a_c:.2f} dB/cm "
          f"= {total:.2f} dB/cm\n")

    worst = 0.0
    for net, mm in sorted(feed_lengths().items()):
        one_way = total * mm / 10.0
        worst = max(worst, one_way)
        print(f"  {net}: {mm:.0f} mm of line -> {one_way:.1f} dB one way, "
              f"{2 * one_way:.1f} dB there and back")

    print()
    if worst > 6.0:
        print(f"  ⛔ {worst:.0f} dB of feed loss makes this architecture "
              "unbuildable as drawn.")
        print("     A radar link budget goes as the fourth power of range, so "
              f"{2 * worst:.0f} dB round trip")
        print(f"     costs a factor of {10 ** (2 * worst / 40):.1f} in range "
              "before the antenna has done anything.")
        print()
        print("     The transceiver cannot sit in the middle and feed two "
              "antennas 90 mm away.")
        print("     Three ways out, none of them free:")
        print("       - put a transceiver ON each antenna island, and "
              "distribute a low IF")
        print("         plus a reference clock down the flex instead of "
              "60 GHz;")
        print("       - move both antennas next to the transceiver, and give "
              "up the two")
        print("         separated viewpoints the two-island layout exists for;")
        print("       - keep one island only, and accept a single viewpoint.")
        print()
        print("     This is an architecture decision, not a layout one.")
        print()
        print("     ⭐ AND THE SILICON HAS ALREADY TAKEN IT. hardware/bom.py went")
        print("     looking for a 60 GHz transceiver you can buy; the Acconeer "
              "A121's")
        print("     datasheet says the antenna is inside the package and 'it is "
              "not")
        print("     possible to connect trace antenna'. There is no feed to "
              "lose 8 dB")
        print("     in, because a real part is placed where its antenna has to "
              "be —")
        print("     which is option one above, arrived at by the parts bin "
              "rather than")
        print("     by choice. ANT_A1 and ANT_A2 should not be nets at all.")
    else:
        print(f"  Feed loss {worst:.1f} dB one way — acceptable.")


if __name__ == "__main__":
    main()
