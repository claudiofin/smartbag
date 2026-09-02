#!/usr/bin/env python3
"""Flat cutting patterns for the bag, from the same dimensions the CAD uses.

⛔ A LEATHER GOODS MAKER DOES NOT WORK FROM AN STL. Everything in this repository
that describes the bag describes it in three dimensions — a lofted shell, a
render, a section cut — and none of that is what a pellettiere asks for. They ask
for a cartamodello: flat panels, at 1:1, with seam allowances and notches. The
bag has been the least developed part of this project for exactly as long as
nobody wrote one.

⭐ SO THIS DERIVES THE PANELS FROM dimensions.py, which is where the bag already
lives. Change BAG_W_BOTTOM and the pattern changes with it; there is no second
description of the shape to drift out of step with the first, which is the same
rule the rest of the project runs on.

⚠️ AND IT IS A FIRST PATTERN, NOT A FINAL ONE, WHICH IS NOT A DISCLAIMER BUT HOW
THE TRADE WORKS. You cannot unroll a 3D loft into a leather pattern and cut hides
from it. A structured bag gets its shape from the stiffener and the stitching as
much as from the panel outline, leather stretches on the bias and not across it,
and every maker eases a curve differently. What comes out of here is
dimensionally correct and it is where a pattern maker STARTS: they cut a toile in
cheap material, put it together, and adjust. Two or three iterations is normal
and none of them are a failure of this file.

⛔ WHAT IS NOT NEGOTIABLE IS THE SECOND PAGE. The electronics impose four
constraints on the bag and every one of them is the kind a bag maker would
otherwise violate without knowing — metal feet on the base are standard practice
and would sit between the charging coil and the pad. Those are in the tech pack
and they are specifications, not preferences.

Usage:  python3 cad/patterns.py [out_dir]      (default fab/patterns)
"""
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

import dimensions as d              # noqa: E402

# ⚠️ 8 mm. Leather is stitched at 3-4 mm from the edge and the allowance carries
# the turn as well as the stitch; 8 is what a maker trims back from. It is a
# parameter because a maker who turns edges instead of butting them wants 12.
SEAM = 8.0

# The corner radius grows with the flare — the CAD's `high` sketch uses
# CORNER_R + 2, and the pattern has to use the same number or the panels do not
# meet the base.
R_LOW = d.CORNER_R
R_HIGH = d.CORNER_R + 2.0


def slant(dw, h):
    """True length of a face that moves out by `dw` over height `h`."""
    return math.hypot(h, dw)


def panels():
    """Every panel, as (name, count, outline_points, note).

    Outlines are closed polylines in millimetres, origin at the panel's own
    bottom-left, BEFORE the seam allowance is added.
    """
    out = []

    # ── front and back: the flat faces of the frustum ───────────────────────
    fw_lo = d.BAG_W_BOTTOM - 2 * R_LOW
    fw_hi = d.BAG_W_TOP - 2 * R_HIGH
    fh = slant((d.BAG_W_TOP - d.BAG_W_BOTTOM) / 2, d.BAG_H)
    out.append(("front_back", 2, [
        (-fw_lo / 2, 0.0), (fw_lo / 2, 0.0), (fw_hi / 2, fh), (-fw_hi / 2, fh),
    ], f"flat face, {fw_lo:.0f} -> {fw_hi:.0f} mm over {fh:.1f} mm of slant"))

    # ── the side gusset: a flat face with a quarter corner at each end ──────
    # ⚠️ The corner arcs are on the gusset rather than split down the middle of
    # the corner. A seam in the middle of a 20 mm radius is a seam on the most
    # visible line of the bag and the hardest one to keep straight.
    sw_lo = d.BAG_D_BOTTOM - 2 * R_LOW
    sw_hi = d.BAG_D_TOP - 2 * R_HIGH
    arc_lo = math.pi / 2 * R_LOW
    arc_hi = math.pi / 2 * R_HIGH
    gw_lo = sw_lo + 2 * arc_lo
    gw_hi = sw_hi + 2 * arc_hi
    # ⚠️ The slant differs across the gusset — 190.2 mm at the side face,
    # 190.9 at the corner where it meets the front panel — because the front
    # flares more than the side does. Half a millimetre over 190 is inside what
    # easing absorbs; the taller of the two is used so nothing comes up short.
    gh = max(slant((d.BAG_D_TOP - d.BAG_D_BOTTOM) / 2, d.BAG_H),
             slant((d.BAG_W_TOP - d.BAG_W_BOTTOM) / 2, d.BAG_H))
    out.append(("gusset", 2, [
        (-gw_lo / 2, 0.0), (gw_lo / 2, 0.0), (gw_hi / 2, gh), (-gw_hi / 2, gh),
    ], f"side face {sw_lo:.0f} mm plus a {R_LOW:.0f} mm corner each end; "
       f"{gw_lo:.0f} -> {gw_hi:.0f} mm"))

    # ── base: the bottom section, rounded rectangle ─────────────────────────
    pts = []
    hw, hh = d.BAG_W_BOTTOM / 2 - R_LOW, d.BAG_D_BOTTOM / 2 - R_LOW
    for cx, cy, a0 in ((hw, hh, 0.0), (-hw, hh, 90.0),
                       (-hw, -hh, 180.0), (hw, -hh, 270.0)):
        for i in range(13):
            a = math.radians(a0 + i * 90.0 / 12)
            pts.append((cx + R_LOW * math.cos(a), cy + R_LOW * math.sin(a)))
    out.append(("base", 1, pts,
                f"{d.BAG_W_BOTTOM:.0f} x {d.BAG_D_BOTTOM:.0f} mm, "
                f"R{R_LOW:.0f} corners"))

    # ── the soft neck: one band, joined into a loop ─────────────────────────
    # ⭐ The neck is the one part of the bag that changes shape, so it is cut
    # flat and gets its form from the closure rather than from a pattern.
    per = (2 * (d.BAG_W_TOP - 2 * R_HIGH) + 2 * (d.BAG_D_TOP - 2 * R_HIGH)
           + 2 * math.pi * R_HIGH)
    nh = d.BAG_MOUTH_Z - d.BAG_H
    out.append(("neck", 1, [
        (0.0, 0.0), (per, 0.0), (per, nh), (0.0, nh),
    ], f"band {per:.0f} x {nh:.0f} mm, joined into a loop at one end"))

    # ── handles: a rolled strip ─────────────────────────────────────────────
    # The CAD's handle is half a torus, major radius 62, tube radius 4.5. Rolled
    # over a 9 mm core a strip wants about pi*d plus the overlap.
    arc_r, tube_r = 62.0, 4.5
    hl = math.pi * arc_r
    strip = math.pi * 2 * tube_r + 12.0
    out.append(("handle", 2, [
        (0.0, 0.0), (hl + 2 * 40.0, 0.0), (hl + 2 * 40.0, strip), (0.0, strip),
    ], f"rolled over a {2 * tube_r:.0f} mm core; {hl:.0f} mm of arc plus "
       f"40 mm tabs each end, attached at z = {d.HANDLE_Z:.0f} mm"))

    return out


def offset(points, by):
    """Grow a closed polyline outward by `by` millimetres.

    ⚠️ Vertex offset along the angle bisector. Exact for convex outlines, which
    every panel here is; a concave one would need a proper offset and this would
    fold it inside out rather than warn. There are none, and check.py asserts it.
    """
    n = len(points)
    out = []
    for i in range(n):
        px, py = points[(i - 1) % n]
        cx, cy = points[i]
        nx, ny = points[(i + 1) % n]
        a = math.atan2(cy - py, cx - px)
        b = math.atan2(ny - cy, nx - cx)
        # outward normals of the two edges, for a counter-clockwise outline
        n1 = (math.sin(a), -math.cos(a))
        n2 = (math.sin(b), -math.cos(b))
        bx, by_ = n1[0] + n2[0], n1[1] + n2[1]
        m = math.hypot(bx, by_)
        if m < 1e-9:
            out.append((cx, cy))
            continue
        bx, by_ = bx / m, by_ / m
        # scale so the offset edge really sits `by` from the original
        cos_half = max(0.2, abs(bx * n1[0] + by_ * n1[1]))
        out.append((cx + bx * by / cos_half, cy + by_ * by / cos_half))
    return out


def area(points):
    s = 0.0
    for i in range(len(points)):
        x1, y1 = points[i]
        x2, y2 = points[(i + 1) % len(points)]
        s += x1 * y2 - x2 * y1
    return abs(s) / 2


def write_dxf(path, sets):
    import ezdxf
    doc = ezdxf.new("R2010", setup=True)
    doc.header["$INSUNITS"] = 4          # millimetres
    msp = doc.modelspace()
    for layer, colour in (("CUT", 1), ("SEAM", 3), ("TEXT", 7)):
        doc.layers.add(layer, color=colour)
    x = 0.0
    for name, count, pts, note in sets:
        w = max(p[0] for p in pts) - min(p[0] for p in pts)
        h = max(p[1] for p in pts) - min(p[1] for p in pts)
        ox = x - min(p[0] for p in pts) + SEAM + 5
        oy = -min(p[1] for p in pts) + SEAM + 5
        msp.add_lwpolyline([(p[0] + ox, p[1] + oy) for p in pts],
                           close=True, dxfattribs={"layer": "SEAM"})
        cut = offset(pts, SEAM)
        msp.add_lwpolyline([(p[0] + ox, p[1] + oy) for p in cut],
                           close=True, dxfattribs={"layer": "CUT"})
        msp.add_text(f"{name.upper()} x{count}",
                     height=8, dxfattribs={"layer": "TEXT"}).set_placement(
                         (x + 5, -14))
        msp.add_text(note, height=4,
                     dxfattribs={"layer": "TEXT"}).set_placement((x + 5, -24))
        x += w + 2 * SEAM + 40
    doc.saveas(path)


def main():
    out_dir = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
        ROOT, "fab", "patterns")
    os.makedirs(out_dir, exist_ok=True)
    sets = panels()

    path = os.path.join(out_dir, "smartbag-patterns.dxf")
    write_dxf(path, sets)
    print(f"OK  {path}")
    print("    CUT layer is the cutting line, SEAM the stitch line, "
          f"{SEAM:.0f} mm between them\n")

    print("Cut list, per bag:\n")
    total = 0.0
    for name, count, pts, note in sets:
        a = area(offset(pts, SEAM)) / 100.0        # cm2
        total += a * count
        w = max(p[0] for p in pts) - min(p[0] for p in pts) + 2 * SEAM
        h = max(p[1] for p in pts) - min(p[1] for p in pts) + 2 * SEAM
        print(f"  {name:<12} x{count}  {w:6.0f} x {h:6.0f} mm   "
              f"{a * count:6.0f} cm2   {note}")

    # ⚠️ A hide is sold by the square foot and never used whole: 60-70% yield is
    # normal once the maker has avoided the belly, the brands and the scars.
    sqft = total / 929.03
    print(f"\n  leather, panels only:   {total:.0f} cm2  ({sqft:.2f} sq ft)")
    print(f"  at 65% yield:           {sqft / 0.65:.2f} sq ft a bag")
    print("  ⚠️ Lining, stiffener, reinforcement patches and the closure are "
          "not in that\n     figure — they roughly double it.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
