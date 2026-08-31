#!/usr/bin/env python3
"""Check the board's footprints against the real parts' own datasheets.

⛔ WHY THIS IS A PROGRAM AND NOT A TABLE. A bill of materials written by hand
agrees with the board by construction, because the same person wrote both. This
one does not: hardware/bom.py carries body dimensions copied out of each
vendor's datasheet, this script measures what the KiCad footprint actually is,
and it prints every place the two disagree. Three of the disagreements it finds
are design changes, not layout ones.

Writes hardware/bom.csv and prints the report.

Usage:  python3 tools/bom_report.py
"""
import csv
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "hardware"))

import bom                              # noqa: E402
import netlist as nl                    # noqa: E402
import generate_pcb as pcb              # noqa: E402

FP_LIB = pcb._footprint_library()
DS = os.path.join(ROOT, "hardware", "datasheets")

# ⛔ THE FIRST VERSION OF THIS CHECK PASSED U2, and U2 is the worst mismatch on
# the board. It counted `(pad "...")` occurrences: KiCad splits a QFN thermal
# pad into nine sub-pads, so a QFN-40 footprint has 40 + 9 + 1 = 50 pad records
# — exactly the ball count of the 50-ball part it does not resemble in any other
# way. A coincidence in a number is all it takes for a naive check to certify
# the thing it exists to catch. So: distinct NUMERIC pad numbers, which is the
# electrical pin count and nothing else.


def footprint_text(lib, fp):
    return open(pcb.footprint_path(lib, fp)).read()


def measure(lib, fp):
    """(electrical pins, courtyard x, courtyard y) of a footprint, in mm."""
    t = footprint_text(lib, fp)
    # ⚠️ NOT `isdigit()`. That was the second version of this check and it
    # scored the A121 at zero pins: a BGA's pads are named A1, K9, J10, and a
    # rule written for QFNs quietly reports the part as empty rather than as
    # wrong. Distinct pad NAMES, minus the mechanical ones a datasheet never
    # counts as pins — thermal sub-pads share a name and collapse to one, which
    # is the behaviour that made this check worth writing in the first place.
    MECHANICAL = {"", "MP", "SH", "MP1", "MP2", "NC"}
    numbers = {n for n in re.findall(r'\(pad "([^"]*)" ', t)
               if n not in MECHANICAL}
    pts = [(float(a), float(b))
           for m in re.finditer(
               r'\(fp_(?:line|rect|poly)\b(.*?)\(layer "F\.CrtYd"', t, re.S)
           for a, b in re.findall(
               r'\((?:start|end|xy) ([-\d.]+) ([-\d.]+)\)', m.group(1))]
    if not pts:
        return len(numbers), None, None
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    return len(numbers), max(xs) - min(xs), max(ys) - min(ys)


def body_fits(cx, cy, bx, by):
    """⭐ A courtyard LARGER than the body is correct — it is a keep-out, and a
    chip antenna's is deliberately enormous. Only a courtyard the real part
    would not physically fit inside is an error, so the test is one-sided."""
    if cx is None:
        return False
    return ((cx >= bx - 0.01 and cy >= by - 0.01)
            or (cx >= by - 0.01 and cy >= bx - 0.01))


def main():
    print("BOM vs footprints — measured, not asserted\n")
    rows, problems = [], []

    for ref, val, sym, lib, fp, pins, x, y in nl.PARTS:
        entry = bom.BOM.get(ref)
        if entry is None:
            continue
        pads, cx, cy = measure(lib, fp)
        bx, by, _bz = entry["body"]
        fits = body_fits(cx, cy, bx, by)
        # ⚠️ A thermal pad carries a number the datasheet may or may not count
        # as a pin, so one extra is tolerated and no more.
        pin_gap = pads - entry["pins"]
        ok = fits and 0 <= pin_gap <= 1

        pdf = entry["pdf"]
        archived = pdf and os.path.exists(os.path.join(DS, pdf))
        rows.append({
            "ref": ref, "mpn": entry["mpn"], "manufacturer": entry["manufacturer"],
            "description": entry["description"], "package": entry["package"],
            "body_mm": f"{bx} x {by} x {entry['body'][2]}",
            "pitch_mm": entry["pitch"] or "",
            "datasheet_pins": entry["pins"], "footprint_pads": pads,
            "footprint": fp,
            "courtyard_mm": f"{cx:.2f} x {cy:.2f}" if cx else "",
            "datasheet": entry["datasheet"],
            "archived_pdf": pdf if archived else "",
            "usd": entry["usd"] if entry["usd"] is not None else "",
            # ⚠️ Availability is a snapshot, not a property of the part. Two of
            # the three chips this design most depends on were out of stock at
            # LCSC on the day this was written, which is worth recording and
            # worth not trusting a month from now.
            "availability": entry.get("stock", ""),
            "agrees": "yes" if ok else "NO",
        })

        mark = "  ok " if ok else "  ⛔  "
        print(f"{mark}{ref:4} {entry['mpn']:22} {entry['package']:10} "
              f"datasheet {entry['pins']:>3} pins / {bx}x{by} mm   "
              f"footprint {pads:>3} pins / "
              f"{f'{cx:.1f}x{cy:.1f}' if cx else '?':>9} mm"
              + ("" if archived else "   [pdf not archived]"))
        if not ok:
            problems.append((ref, entry["verdict"]))

    out = os.path.join(ROOT, "hardware", "bom.csv")
    with open(out, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)

    noted = [r for r in rows if r["availability"]]
    if noted:
        print("\n  availability, as of 2026-08-30 — a snapshot, not a promise:")
        for r in noted:
            print(f"     {r['ref']:4} {r['availability']}")

    groups = bom.passives()
    count = sum(len(refs) for _pkg, refs in groups.values())
    print(f"\n  {count} passives in {len(groups)} distinct values, "
          "derived from the netlist:")
    for value, (pkg, refs) in groups.items():
        shown = " ".join(refs[:6]) + (f" +{len(refs) - 6} more" if len(refs) > 6 else "")
        print(f"     {pkg:14} {value:22} x{len(refs):<3} {shown}")

    if problems:
        print(f"\n⛔ {len(problems)} parts the board cannot accept as drawn:\n")
        for ref, verdict in problems:
            print(f"   {ref}: {verdict}\n")

    print(f"⚠️ {len(bom.MISSING)} things the design needs and the board has not got:\n")
    for what, why in bom.MISSING:
        print(f"   - {what}\n     {why}\n")

    print(f"wrote {os.path.relpath(out, ROOT)}")
    # ⚠️ Deliberately exit 0. This is a report, not a gate: the mismatches are
    # the finding, and a red build would only tempt someone to silence them.
    return 0


if __name__ == "__main__":
    sys.exit(main())
