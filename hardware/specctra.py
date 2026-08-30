#!/usr/bin/env python3
"""Specctra round trip: KiCad -> Freerouting -> KiCad. Run with KiCad's Python.

⛔ KICAD HAS NO AUTOROUTER. It had one through version 5 and it was removed;
what remains is the interchange format. `pcbnew` can write a Specctra `.dsn` and
read back a `.ses` session, and the router in between is somebody else's
program — in practice Freerouting, which is a maze router with rip-up and retry,
which is exactly what hand-rolling one here established was missing.

⭐ WHY THIS BEATS THE THREE HAND-WRITTEN ATTEMPTS. Not because the algorithm is
secret, but because rip-up is the whole problem. A router that places tracks and
never reconsiders is a router that paints itself into a corner on the first
congested channel; all three attempts in route.py failed that way, in three
different places. Rip-up means being willing to destroy work that is in the way,
and that turns out to be the entire difference between 852 violations and a
board.

Usage:
  <kicad-python> hardware/specctra.py export  board.kicad_pcb out.dsn [plane,layers]
  <kicad-python> hardware/specctra.py import  hardware/smartbag_core.kicad_pcb in.ses
"""
import os
import sys

import re

import pcbnew

EDGE_CLEARANCE_MM = 0.15


def inset_boundary(path, mm):
    """Shrink the DSN outline so the router keeps copper off the board edge.

    ⛔ THE ROUTER HAS NEVER HEARD OF COPPER-TO-EDGE CLEARANCE. Specctra's
    boundary *is* the outline, so freerouting is free to put a via tangent to
    it; one ended up 0.120 mm from an edge against KiCad's 0.150 mm rule.

    ⚠️ The first attempt at this was to move the offending via afterwards. It
    worked — the via cleared the edge and landed 0.089 mm from a ground pad
    instead. Nudging copper after the fact just moves a violation somewhere the
    router is no longer looking. Shrinking the boundary states the constraint
    where it can actually be honoured.

    ⭐ Offsets each edge inward by `mm` and re-intersects, which is exact for
    the rectilinear outline this board has, notches included.
    """
    txt = open(path).read()
    m = re.search(r"\(boundary\s*\(path pcb 0([^)]*)\)", txt, re.S)
    if not m:
        return
    nums = [float(v) for v in m.group(1).split()]
    pts = list(zip(nums[0::2], nums[1::2]))
    if len(pts) > 2 and pts[0] == pts[-1]:
        pts = pts[:-1]

    # signed area gives the winding, which gives which side is "inward"
    area = sum(pts[i][0] * pts[(i + 1) % len(pts)][1]
               - pts[(i + 1) % len(pts)][0] * pts[i][1]
               for i in range(len(pts))) / 2.0
    sign = 1.0 if area > 0 else -1.0
    d = mm * 1000.0                     # the DSN resolution here is 1 unit = 1 um

    lines = []
    n = len(pts)
    for i in range(n):
        (x0, y0), (x1, y1) = pts[i], pts[(i + 1) % n]
        ex, ey = x1 - x0, y1 - y0
        L = (ex * ex + ey * ey) ** 0.5
        if L == 0:
            continue
        nx, ny = -ey / L * sign, ex / L * sign
        lines.append((x0 + nx * d, y0 + ny * d, ex, ey))

    out = []
    for i in range(len(lines)):
        ax, ay, adx, ady = lines[i - 1]
        bx, by, bdx, bdy = lines[i]
        den = adx * bdy - ady * bdx
        if abs(den) < 1e-9:             # parallel: keep the corner as offset
            out.append((bx, by))
            continue
        t = ((bx - ax) * bdy - (by - ay) * bdx) / den
        out.append((ax + adx * t, ay + ady * t))

    # ⚠️ Substitute the NUMBERS ONLY. The first version rewrote the whole
    # (boundary (path ...)) form and left the original's closing paren behind;
    # the file still looked plausible and freerouting died three minutes later
    # on a null package library, which is not a message that says "unbalanced
    # parentheses in the boundary".
    body = "  ".join(f"{x:.0f} {y:.0f}" for x, y in out + [out[0]])
    txt = txt[:m.start(1)] + "  " + body + txt[m.end(1):]
    open(path, "w").write(txt)


def drop_orphan_fragments(board):
    """Delete copper that touches nothing at either end.

    ⛔ NOT "delete short tracks". A routed board has 156 segments under 0.2 mm
    and almost all of them are corners in a perfectly good polyline; removing
    them by length would cut the net they belong to. What is actually wrong is a
    *group* of copper that reaches no pad and no via — a fragment the router or
    the session import left behind. One of those, 0.151 mm long, was enough to
    make DRC report an unconnected pad on a net that was otherwise fully routed.

    ⚠️ Uses KiCad's own connectivity rather than comparing endpoints, so a
    fragment that merely happens to end near a pad is not mistaken for a
    connected one.
    """
    conn = board.GetConnectivity()
    conn.RecalculateRatsnest()

    # group tracks by (net, connectivity cluster) via a simple flood over
    # shared endpoints, then keep only groups with no pad and no via
    def key(pt):
        return (pt.x, pt.y)

    from collections import defaultdict
    by_net = defaultdict(list)
    for t in board.GetTracks():
        by_net[t.GetNetCode()].append(t)

    anchors = defaultdict(set)          # net -> set of pad positions
    for fp in board.GetFootprints():
        for pad in fp.Pads():
            anchors[pad.GetNetCode()].add(key(pad.GetPosition()))

    doomed = []
    for net, items in by_net.items():
        nodes = defaultdict(list)
        for t in items:
            if t.Type() == pcbnew.PCB_VIA_T:
                nodes[key(t.GetPosition())].append(t)
            else:
                nodes[key(t.GetStart())].append(t)
                nodes[key(t.GetEnd())].append(t)
        seen = set()
        for t in items:
            if id(t) in seen:
                continue
            stack, group = [t], []
            seen.add(id(t))
            while stack:
                cur = stack.pop()
                group.append(cur)
                pts = ([key(cur.GetPosition())] if cur.Type() == pcbnew.PCB_VIA_T
                       else [key(cur.GetStart()), key(cur.GetEnd())])
                for pt in pts:
                    for nxt in nodes[pt]:
                        if id(nxt) not in seen:
                            seen.add(id(nxt))
                            stack.append(nxt)
            has_via = any(g.Type() == pcbnew.PCB_VIA_T for g in group)
            touches_pad = any(
                key(g.GetStart()) in anchors[net] or key(g.GetEnd()) in anchors[net]
                for g in group if g.Type() != pcbnew.PCB_VIA_T)
            if not has_via and not touches_pad:
                doomed.extend(group)

    for t in doomed:
        board.Remove(t)
    return len(doomed)


action, board_path = sys.argv[1], sys.argv[2]
other = sys.argv[3]
board = pcbnew.LoadBoard(board_path)

if action == "export":
    ok = pcbnew.ExportSpecctraDSN(board, other)
    if not ok or not os.path.exists(other):
        sys.exit(f"ExportSpecctraDSN failed -> {other}")
    inset_boundary(other, EDGE_CLEARANCE_MM)
    planes = sys.argv[4].split(",") if len(sys.argv) > 4 and sys.argv[4] else []
    if planes:
        # ⛔ AN AUTOROUTER GIVEN FOUR SIGNAL LAYERS WILL USE FOUR SIGNAL LAYERS.
        # The first routed board put 34% of its tracks on In1.Cu — the layer this
        # design calls its RF reference plane and a comment in generate_pcb.py
        # claimed was "never routed on". The claim was not enforced anywhere; it
        # was a sentence. Specctra has a layer type for exactly this, and KiCad
        # does not emit it, so it is patched in here: a `power` layer is one the
        # router may via through and may not route on.
        txt = open(other).read()
        for name in planes:
            marker = f"(layer {name}\n"
            i = txt.find(marker)
            if i < 0:
                sys.exit(f"layer {name} not in the DSN")
            j = txt.index("(type signal)", i)
            txt = txt[:j] + "(type power)" + txt[j + len("(type signal)"):]
        open(other, "w").write(txt)
    print(f"OK  {os.path.getsize(other)} bytes -> {other}"
          + (f"  [planes: {', '.join(planes)}]" if planes else ""))
elif action == "import":
    ok = pcbnew.ImportSpecctraSES(board, other)
    if not ok:
        sys.exit(f"ImportSpecctraSES failed <- {other}")
    removed = drop_orphan_fragments(board)
    board.Save(board_path)
    tracks = board.GetTracks()
    vias = sum(1 for t in tracks if t.Type() == pcbnew.PCB_VIA_T)
    print(f"OK  {len(tracks) - vias} tracks + {vias} vias "
          f"({removed} orphan fragments dropped) -> {board_path}")
else:
    sys.exit("action must be export or import")
