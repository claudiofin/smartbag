#!/usr/bin/env python3
"""Turn the bill of materials into something a distributor will take.

⛔ A BOM IS NOT AN ORDER. This project has spent a long time making sure every
part is real — 23 named components, each with a manufacturer part number whose
package was measured against its own datasheet — and none of that puts anything
in a basket. What a distributor wants is a two-column file: what, and how many.

⭐ SO THIS WRITES ONE, AND IT WRITES THE QUANTITIES FOR A BUILD RATHER THAN FOR A
BOARD. Five prototypes of a design with two radars on it is ten radars, and the
commonest way to be short a part on assembly day is to have ordered one board's
worth of a component that appears twice.

⚠️ AND IT DOES NOT SHIP PRICES. hardware/bom.py carries a dated snapshot for the
parts that dominate the cost, which is enough to size an order; the live figure
has to come from the distributor, because a number in a repository does not go
out of stock on its own. Upload the file this writes and the basket prices
itself.

⛔ PASSIVES ARE A SPECIFICATION, NOT A PART NUMBER, and that is deliberate. There
are 29 distinct values across 82 passives, all 0402 commodity parts, and an
assembly house sources those from its own reels — asking for a specific Murata
reel number would raise the price and delay the build for no electrical reason.
What has to be exact is the value, the tolerance, the dielectric and the voltage,
and those are in the second file.

Usage:  python3 tools/order.py [boards]      (default 5)
"""
import csv
import os
import sys
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "hardware"))

import bom                      # noqa: E402
import netlist as nl            # noqa: E402
import optics_netlist as onl    # noqa: E402

OUT = os.path.join(ROOT, "fab")

# ⚠️ Spares, because 0402 parts are lost on the floor and BGAs are lost to
# rework. One extra of everything cheap, two of anything that gets reflowed
# twice when the first attempt does not come up.
SPARE_MIN = 2


def per_board():
    """{ref-family: (mpn, count)} across all three boards."""
    named = Counter()
    for part in list(nl.PARTS) + list(onl.PARTS):
        ref = part[0]
        for table in (bom.BOM, bom.OPTICS):
            if ref in table:
                named[ref] += 1
                break
        else:
            # ⚠️ D1..D4 and the like are one BOM line and several references.
            base = ref.rstrip("0123456789")
            for table in (bom.BOM, bom.OPTICS):
                for key in table:
                    if key.startswith(base) and key.rstrip("0123456789") == base:
                        named[key] += 1
                        break
    return named


def main():
    boards = int(sys.argv[1]) if len(sys.argv) > 1 else 5
    counts = per_board()
    os.makedirs(OUT, exist_ok=True)

    rows, unquoted, total = [], [], 0.0
    for ref, entry in list(bom.BOM.items()) + list(bom.OPTICS.items()):
        n = max(counts.get(ref, 1), 1) * boards + SPARE_MIN
        price = entry.get("usd10") or entry.get("usd1") or entry.get("usd")
        if price:
            total += price * n
        else:
            unquoted.append(ref)
        rows.append({
            "Manufacturer Part Number": entry["mpn"],
            "Digi-Key Part Number": entry.get("dk", ""),
            "Quantity": n,
            "Customer Reference": ref,
            "Description": entry["description"][:70],
        })

    path = os.path.join(OUT, "smartbag-order.csv")
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    print(f"OK  {path}  ({len(rows)} lines for {boards} boards + {SPARE_MIN} spares)")

    # The passives, as the specification an assembly house actually wants.
    spec = os.path.join(OUT, "smartbag-passives.csv")
    with open(spec, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["Value", "Package", "Quantity per board", "Total",
                    "References"])
        for value, (pkg, refs) in sorted(bom.passives().items()):
            w.writerow([value, pkg, len(refs), len(refs) * boards + SPARE_MIN,
                        " ".join(refs)])
    n_pass = sum(len(r) for _p, r in bom.passives().values())
    print(f"OK  {spec}  ({len(bom.passives())} values, {n_pass} placements)")

    print(f"\n  named parts quoted:   ${total:,.2f} for {boards} boards")
    print(f"  not yet quoted:       {len(unquoted)} lines — {', '.join(unquoted)}")
    print("  passives, PCBs, stencil and assembly are not in that figure.")

    # ⛔ A PRICE IS NOT AVAILABILITY, AND THE THING THAT ACTUALLY DELAYS A BUILD
    # IS THE ONE LINE NOBODY HAS. Every part below is real, catalogued and
    # priced; the question an order asks is whether it is on a shelf today.
    short, unknown = [], []
    for ref, entry in list(bom.BOM.items()) + list(bom.OPTICS.items()):
        want = max(counts.get(ref, 1), 1) * boards + SPARE_MIN
        have = entry.get("dk_stock")
        if have is None:
            unknown.append(ref)
        elif have < want:
            short.append((ref, entry["mpn"], have, want))

    if short:
        print(f"\n  ⛔ {len(short)} line(s) cannot be filled from stock today:")
        for ref, mpn, have, want in short:
            print(f"     {ref:<8} {mpn:<34} {have} in stock, {want} needed")
        print("     These set the build date. Order them first and separately;")
        print("     everything else on this list ships the day it is ordered.")
    if unknown:
        print(f"\n  ⚠️ {len(unknown)} line(s) priced without a stock figure: "
              f"{', '.join(unknown)}")
        print("     The distributor's page gave a price and no quantity. Check "
              "them in the basket.")


if __name__ == "__main__":
    main()
