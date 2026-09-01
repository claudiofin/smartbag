#!/usr/bin/env python3
"""The four things that cannot be finished until a board exists — as a procedure.

⛔ EVERY OTHER NUMBER IN THIS PROJECT COMES FROM A DATASHEET AND IS CHECKED BY
tools/check.py. These four do not, and no amount of care makes them: L′ of a
coil depends on the shielding around it, a foreign-object detector depends on
what a real receiver looks like to a real transmitter, a chip antenna matches
against the ground plane it is sitting on, and a 60 GHz radar sees the inside of
the enclosure it is bolted into. All four are properties of an ASSEMBLY, and the
assembly does not exist yet.

⭐ SO THIS IS NOT A MEASUREMENT, IT IS THE FORM THE MEASUREMENT GOES ON. It
computes the target and the acceptance window from the files that already hold
the model — hardware/qi_resonance.py, hardware/bom.py, firmware/sb_sense.h — and
prints what to do, with what instrument, and what answer means pass. Fill in
fab/calibration.json as the numbers come off the bench and run it again: it will
tell you which of them the design survives and which of them move a component
value, and for the ones that move a value it says which file to change.

⚠️ WHAT THIS DELIBERATELY WILL NOT DO is invent a measured column. An empty
field prints as "not measured" and the exit status stays non-zero until all four
are filled. A calibration file that defaults to passing is worse than no file.

Usage:  python3 tools/calibrate.py [fab/calibration.json]
"""
import json
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "hardware"))

import bom                       # noqa: E402
import qi_resonance as qi        # noqa: E402

DEFAULT = os.path.join(ROOT, "fab", "calibration.json")


def firmware_define(path, name, cast=int):
    src = open(os.path.join(ROOT, "firmware", path)).read()
    for line in src.splitlines():
        if line.startswith(f"#define {name} "):
            return cast(line.split()[2])
    raise KeyError(name)


# ─────────────────────────────────────────────────────────────────────────────
def coil_inductance():
    """L′ — the coil's inductance with this receiver's shielding in place."""
    free_air = qi.COIL_UH
    # ⚠️ WPC's own guidance, quoted in qi_resonance.py: L' runs 10-20% above the
    # free-air figure once the shield and a reference transmitter are present.
    # That is the window, not a prediction — a coil outside it means the shield
    # or the spacing is not what the CAD drew.
    lo, hi = free_air * 1.05, free_air * 1.30
    cs, cd = qi.preferred()
    return {
        "id": "coil_l_prime",
        "what": f"L' of the {qi.COIL_MPN} receiver coil, in microhenries",
        "how": "LCR meter at 100 kHz, coil fitted in the assembled insert with "
               "its ferrite shield, against a WPC reference transmitter coil "
               "at the design separation. Free air is not this measurement.",
        "target": free_air * 1.15,
        "window": (lo, hi),
        "unit": "uH",
        "moves": f"hardware/qi_resonance.py COIL_UH, and with it Cs and Cd "
                 f"(today {cs} and {cd}). Re-run tools/check.py: it compares "
                 f"the board's capacitor values against this file's answer.",
    }


def fod_reference():
    """The quality factor a transmitter measures to decide nothing is burning."""
    # ⛔ FOD IS NOT A NUMBER THIS PROJECT CAN COMPUTE. The WPC's Q-factor method
    # has the transmitter measure the resonant quality of the receiver it can
    # see and compare it against a reference value the RECEIVER declares. The
    # declared value has to be the one this assembly actually has, and a wrong
    # declaration either fails to detect a coin on the pad or refuses to charge
    # a healthy bag.
    return {
        "id": "fod_q_reference",
        "what": "Reference quality factor of the receiver coil in the "
                "assembled bag, unitless",
        "how": "LCR meter or network analyser, Q at 100 kHz, insert fully "
               "assembled with the cell and both PCBs in place and NOTHING on "
               "the pad. Repeat with a 20 mm steel disc on the coil face and "
               "record that too — the difference is what detection has to see.",
        "target": None,
        "window": (None, None),
        "unit": "Q",
        "moves": "the value written into the receiver's WPC identification "
                 "packet. ⚠️ There is no default that is safe: a bag that "
                 "declares a Q it does not have is a bag that charges with a "
                 "coin on it.",
        "extra": ["fod_q_with_coin"],
    }


def antenna_match():
    """The one MISSING entry that a bench closes and a datasheet cannot."""
    for what, _why in bom.MISSING:
        if "antenna" in what:
            break
    else:                       # pragma: no cover - the list is checked
        raise SystemExit("bom.MISSING no longer lists the antenna match")
    return {
        "id": "antenna_s11_db",
        "what": "Return loss at 2.44 GHz with the match as fitted, in dB",
        "how": "Vector network analyser on a board-edge u.FL or a soldered "
               "semi-rigid pigtail, insert closed, cell fitted, bag closed "
               "around it. ⚠️ A match measured on a bare board is not this "
               "measurement — leather and a lithium pouch are both in the near "
               "field.",
        "target": -10.0,
        # -10 dB is 90% of the power into the antenna and is the number every
        # chip-antenna datasheet draws its own curve against. Worse than -6 dB
        # is a link budget problem, not a tuning nicety.
        "window": (-60.0, -6.0),
        "unit": "dB",
        "moves": "L2/C6/C11 in hardware/netlist.py, which are the vendor's "
                 "reference values today. A Smith chart and three parts.",
    }


def radar_floor():
    """What the radar sees when the bag is empty — which is never nothing."""
    blind = firmware_define("sb_sense.h", "SB_RADAR_BLIND_BINS")
    per_bin = firmware_define("sb_sense.h", "SB_RADAR_BIN_MM")
    bins = firmware_define("sb_sense.h", "SB_RADAR_BINS")
    return {
        "id": "radar_blind_bins",
        "what": "Range bins occupied by the sensor's own package and the "
                "enclosure wall, counted from zero",
        "how": "Assembled insert, bag empty and closed, capture a sweep from "
               "each radar and find the last bin that is still transmit "
               "leakage or the enclosure. Take the larger of the two.",
        "target": float(blind),
        # ⚠️ Below 4 bins the leakage is not being excluded; above 16 the sensor
        # is looking at 48 mm of its own housing and the far half of the bag is
        # what is left.
        "window": (4.0, 16.0),
        "unit": "bins",
        "moves": f"firmware/sb_sense.h SB_RADAR_BLIND_BINS, today {blind}. "
                 f"Each bin is {per_bin} mm, so the current setting hides the "
                 f"first {blind * per_bin} mm of a "
                 f"{bins * per_bin} mm sweep.",
    }


ITEMS = [coil_inductance(), fod_reference(), antenna_match(), radar_floor()]


# ─────────────────────────────────────────────────────────────────────────────
def verdict(item, measured):
    if measured is None:
        return "not measured", False
    lo, hi = item["window"]
    if lo is None and hi is None:
        # ⚠️ FOD has no window because nothing in this repository knows what Q
        # this assembly has. Recording it is the whole of the requirement.
        return f"recorded: {measured:g} {item['unit']}", True
    if lo is not None and measured < lo:
        return f"{measured:g} {item['unit']} — BELOW the window", False
    if hi is not None and measured > hi:
        return f"{measured:g} {item['unit']} — ABOVE the window", False
    return f"{measured:g} {item['unit']} — inside the window", True


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else DEFAULT
    try:
        data = json.load(open(path))
    except FileNotFoundError:
        data = {}
        print(f"⚠️ no {os.path.relpath(path, ROOT)} yet — nothing measured\n")

    done = 0
    for item in ITEMS:
        measured = data.get(item["id"])
        text, ok = verdict(item, measured)
        done += ok
        mark = "✅" if ok else "⛔"
        print(f"{mark} {item['what']}")
        print(f"   how     {item['how']}")
        lo, hi = item["window"]
        if item["target"] is not None:
            print(f"   expect  {item['target']:g} {item['unit']}"
                  + (f", acceptable {lo:g} to {hi:g}"
                     if lo is not None and hi is not None else ""))
        else:
            print("   expect  no predicted value — this one is only ever "
                  "measured")
        for extra in item.get("extra", []):
            got = data.get(extra)
            print(f"   also    {extra}: "
                  + (f"{got:g}" if got is not None else "not measured"))
            if got is None:
                ok = False
        print(f"   result  {text}")
        print(f"   moves   {item['moves']}\n")

    print(f"{done} of {len(ITEMS)} calibrations closed.")
    if done < len(ITEMS):
        print("\n⛔ THE REST NEED A BUILT BOARD, and that is the honest state of "
              "them.\n   Nothing here can be closed by reading a datasheet more "
              "carefully;\n   these four are why the first article exists.")
        print(f"\n   Write the numbers into {os.path.relpath(path, ROOT)} as:")
        print("   " + json.dumps({i["id"]: 0 for i in ITEMS}, indent=3)
              .replace("\n", "\n   "))
    return 0 if done == len(ITEMS) else 1


if __name__ == "__main__":
    sys.exit(main())
