#!/usr/bin/env python3
"""Tie orphaned ground islands back to the plane. Run with KiCad's Python.

⛔ A GROUND POUR IS NOT A GROUND PLANE UNTIL IT IS STITCHED. Routing 1683 tracks
across a 196 x 20 mm board cuts the top pour into pieces, and a piece with no via
in it is a floating sheet of copper: it is not ground, it is an antenna, and DRC
reports it — correctly — as an unconnected item. Seven of the nine unconnected
pads on this board were exactly that.

⭐ WHY THIS RUNS AFTER ROUTING AND NOT BEFORE. generate_pcb.py already drops a
row of stitching vias on a grid, before any track exists. That helps and cannot
be enough: the islands are *made* by the routing, so they can only be found
afterwards. This walks the filled polygons, asks each one whether anything on its
net is inside it, and drops a via where the answer is no.

⚠️ It refuses to place a via it cannot place cleanly. A candidate point is
rejected unless it clears every pad, track and via already there — if no point in
an island qualifies, the island is reported and left alone rather than being
connected with a DRC violation.

Usage:
  <kicad-python> hardware/stitch.py hardware/smartbag_core.kicad_pcb
"""
import sys

import pcbnew

VIA_D = pcbnew.FromMM(0.25)
VIA_DRILL = pcbnew.FromMM(0.1)
CLEARANCE = pcbnew.FromMM(0.20)


def obstacles(board, net):
    """Everything a new via must keep away from.

    Circles as (x, y, r) and segments as (x1, y1, x2, y2, r).

    ⛔ SEGMENTS, NOT SAMPLES. The first version approximated each track by nine
    points along it, which leaves 3 mm gaps in the middle of a 26 mm trace — and
    a stitching via landed in one of them, 0.048 mm from a signal. A track is a
    segment and the distance to it is a closed form; there is no reason to
    guess at it.
    """
    circles, segments = [], []
    for fp in board.GetFootprints():
        for pad in fp.Pads():
            if pad.GetNetCode() == net:
                continue
            r = max(pad.GetSize().x, pad.GetSize().y) / 2
            circles.append((pad.GetPosition().x, pad.GetPosition().y, r))
    for t in board.GetTracks():
        if t.Type() == pcbnew.PCB_VIA_T:
            circles.append((t.GetPosition().x, t.GetPosition().y,
                            t.GetWidth() / 2))
        elif t.GetNetCode() != net:
            a, b = t.GetStart(), t.GetEnd()
            segments.append((a.x, a.y, b.x, b.y, t.GetWidth() / 2))
    return circles, segments


def _seg_dist2(px, py, x1, y1, x2, y2):
    dx, dy = x2 - x1, y2 - y1
    L2 = dx * dx + dy * dy
    if L2 == 0:
        return (px - x1) ** 2 + (py - y1) ** 2
    t = max(0.0, min(1.0, ((px - x1) * dx + (py - y1) * dy) / L2))
    cx, cy = x1 + t * dx, y1 + t * dy
    return (px - cx) ** 2 + (py - cy) ** 2


def clear_of(x, y, obs):
    # ⚠️ 0.2 mm, not the 0.1 mm minimum. The Power net class asks for 0.15 and
    # the RF classes for 0.2, and a stitching via does not know which net it is
    # about to sit next to. Clearing the widest rule on the board is one line;
    # discovering the exception is four DRC errors.
    circles, segments = obs
    need = VIA_D / 2 + CLEARANCE
    for ox, oy, r in circles:
        if (x - ox) ** 2 + (y - oy) ** 2 < (need + r) ** 2:
            return False
    for x1, y1, x2, y2, r in segments:
        if _seg_dist2(x, y, x1, y1, x2, y2) < (need + r) ** 2:
            return False
    return True


def main(path):
    board = pcbnew.LoadBoard(path)
    filler = pcbnew.ZONE_FILLER(board)
    filler.Fill(board.Zones())

    added = skipped = 0
    for zone in board.Zones():
        net = zone.GetNetCode()
        obs = obstacles(board, net)
        for layer in zone.GetLayerSet().CuStack():
            polys = zone.GetFilledPolysList(layer)
            for i in range(polys.OutlineCount()):
                one = pcbnew.SHAPE_POLY_SET()
                one.AddOutline(polys.Outline(i))
                # ⛔ ONLY A VIA COUNTS. The first version of this asked whether
                # anything on the net lay inside the island, and found every
                # island already "anchored" — by tracks, which run ON the layer
                # and connect it to nothing below. An island is tied to the
                # plane when something passes THROUGH it. Surface-mount pads do
                # not either, for the same reason.
                anchored = False
                for t in board.GetTracks():
                    if t.Type() != pcbnew.PCB_VIA_T or t.GetNetCode() != net:
                        continue
                    p = t.GetPosition()
                    if one.Collide(pcbnew.VECTOR2I(p.x, p.y), 0):
                        anchored = True
                        break
                if anchored:
                    continue

                box = one.BBox()
                placed = False
                # ⚠️ Scan the island rather than trusting its centroid: a
                # C-shaped island's centroid is outside it.
                # ⚠️ A coarse grid misses the gap. At 10 x 10 two islands came
                # back "no clear spot" purely because the only place a via fits
                # in a crowded pour is a fraction of a millimetre wide, and a
                # tenth of the bounding box is bigger than that.
                for fy in range(1, 40):
                    for fx in range(1, 40):
                        x = box.GetLeft() + box.GetWidth() * fx // 40
                        y = box.GetTop() + box.GetHeight() * fy // 40
                        if not one.Collide(pcbnew.VECTOR2I(x, y), int(VIA_D)):
                            continue
                        if not clear_of(x, y, obs):
                            continue
                        v = pcbnew.PCB_VIA(board)
                        v.SetPosition(pcbnew.VECTOR2I(x, y))
                        v.SetWidth(VIA_D)
                        v.SetDrill(VIA_DRILL)
                        v.SetLayerPair(pcbnew.F_Cu, pcbnew.B_Cu)
                        v.SetNetCode(net)
                        board.Add(v)
                        obs[0].append((x, y, VIA_D / 2))
                        added += 1
                        placed = True
                        break
                    if placed:
                        break
                if not placed:
                    skipped += 1

    filler.Fill(board.Zones())
    board.Save(path)
    print(f"OK  {added} stitching vias added, {skipped} islands left alone "
          f"(no clear spot) -> {path}")


if __name__ == "__main__":
    main(sys.argv[1])
