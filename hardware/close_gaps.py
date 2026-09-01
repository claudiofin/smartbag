#!/usr/bin/env python3
"""Repair the two ways a router leaves a net a hair short of connected.

⛔ NEITHER OF THESE IS A ROUTING PROBLEM AND THE MAZE ROUTER CANNOT FIX EITHER.
Freerouting works on its own grid and writes a session file back through a
coordinate conversion, and two things come out of that:

  a GAP — two pieces of one net a tenth of a millimetre apart on the same layer,
  which is under a track width and looks joined at any zoom a person would use;

  a MISSED DROP — a track that ends exactly on a pad, on the wrong layer. The
  copper is in the right place and there is no via, so a B.Cu track finishes on
  top of an F.Cu pad and touches nothing. This is the commoner of the two and
  the more convincing: the ratsnest line is zero millimetres long.

Sent at either of these, the maze router routes a centimetre around the houses,
because the pair KiCad names is the two islands' representative items and not
the two ends that nearly meet. It then fails, because there is nowhere to go.

⭐ SO THIS ASKS THE ONLY QUESTION THAT MATTERS FOR THESE TWO FAILURES: across
all the copper of one net, which two pieces are nearest, and is that distance
small enough to be a mistake rather than a route? A tenth of a millimetre is a
mistake. Three millimetres is a route, and this refuses to draw it — there is a
maze router for that, and a straight line drawn in ignorance of what lies
between two points is how you short two nets together.

⭐ AND CONNECTIVITY COMES FROM KICAD, NOT FROM A MODEL OF IT. The first version
of this file worked out the islands itself and found eight that were two
micrometres apart — its own rounding, not the board's. Asking the board object
that DRC will ask means the tool cannot invent a defect or miss one.

Usage:  <kicad-python> hardware/close_gaps.py <board> [max_mm]
"""
import os
import sys

import pcbnew

MM = 1e6
DEFAULT_MAX_MM = 0.40      # a track is 0.10 wide; four of those is a mistake
VIA_D = int(0.30 * MM)
VIA_DRILL = int(0.15 * MM)


def _islands(board, code):
    """The net's disjoint pieces, as KiCad's connectivity sees them."""
    cn = board.GetConnectivity()
    items = [t for t in board.GetTracks() if t.GetNetCode() == code]
    items += [p for f in board.GetFootprints() for p in f.Pads()
              if p.GetNetCode() == code]
    seen, groups = set(), []
    for it in items:
        if id(it) in seen:
            continue
        group = list(cn.GetConnectedItems(it)) or [it]
        ids = {id(x) for x in group}
        ids.add(id(it))
        if not ids & seen:
            groups.append(group if it in group else group + [it])
        seen |= ids
    return groups


def _points(group):
    """(x, y, layer_or_None) for every end of every piece in one island."""
    out = []
    for it in group:
        ty = it.Type()
        if ty == pcbnew.PCB_PAD_T:
            c = it.GetCenter()
            # ⚠️ A surface-mount pad is on ONE layer and that is the whole point
            # of the missed-drop case: a track ending on it from the other side
            # is not connected to it.
            ls = it.GetLayerSet().CuStack()
            out.append((c.x / MM, c.y / MM,
                        ls[0] if len(ls) == 1 else None))
        elif ty == pcbnew.PCB_VIA_T:
            p = it.GetPosition()
            out.append((p.x / MM, p.y / MM, None))
        elif ty == pcbnew.PCB_TRACE_T:
            L = it.GetLayer()
            out.append((it.GetStart().x / MM, it.GetStart().y / MM, L))
            out.append((it.GetEnd().x / MM, it.GetEnd().y / MM, L))
    return out


def _nearest(a, b):
    """The closest pair of ends between two islands, and whether it needs a via.

    ⚠️ A pair on different layers is a candidate too — that is the missed drop —
    but only when the two ends are essentially on top of each other. Two ends a
    tenth of a millimetre apart on opposite sides of the board are not one
    connection, and joining them would draw copper through the laminate.
    """
    best = None
    for x1, y1, l1 in a:
        for x2, y2, l2 in b:
            d = ((x1 - x2) ** 2 + (y1 - y2) ** 2) ** 0.5
            same = l1 is None or l2 is None or l1 == l2
            if not same and d > 0.05:
                continue
            if best is None or d < best[0]:
                best = (d, (x1, y1, l1), (x2, y2, l2), same)
    return best


def close(path, max_mm=DEFAULT_MAX_MM, only=None):
    """⚠️ `only` is a list of net names. Walking every net on the board costs
    minutes — KiCad's connectivity query is per item — and there is no reason
    to: the nets worth looking at are the ones DRC has already named."""
    board = pcbnew.LoadBoard(path)
    report = []
    names = only if only else list(board.GetNetsByName().keys())
    for name in names:
        # ⚠️ str() on every key — see repairs.py. Without it this loop skipped
        # every net and reported "0 repairs", which is indistinguishable from
        # there being nothing wrong.
        codes = {str(k): v.GetNetCode()
                 for k, v in board.GetNetsByName().items()}
        if str(name) not in codes:
            continue
        code = codes[str(name)]
        if code == 0:
            continue
        # ⭐ One join can reveal the next: a net broken in two places has three
        # islands, and closing the first gap changes which two are nearest.
        for _ in range(8):
            parts = _islands(board, code)
            if len(parts) < 2:
                break
            pts = [_points(p) for p in parts]
            best, pair = None, None
            for i in range(len(pts)):
                for j in range(i + 1, len(pts)):
                    got = _nearest(pts[i], pts[j])
                    if got and (best is None or got[0] < best[0]):
                        best, pair = got, (i, j)
            if best is None or best[0] > max_mm:
                break
            d, (x1, y1, l1), (x2, y2, l2), same = best
            if same:
                seg = pcbnew.PCB_TRACK(board)
                seg.SetStart(pcbnew.VECTOR2I(int(x1 * MM), int(y1 * MM)))
                seg.SetEnd(pcbnew.VECTOR2I(int(x2 * MM), int(y2 * MM)))
                seg.SetWidth(int(0.10 * MM))
                seg.SetLayer(l1 if l1 is not None else
                             (l2 if l2 is not None else pcbnew.F_Cu))
                seg.SetNetCode(code)
                board.Add(seg)
                report.append((str(name), "gap", d,
                               board.GetLayerName(seg.GetLayer()), x1, y1))
            else:
                v = pcbnew.PCB_VIA(board)
                v.SetPosition(pcbnew.VECTOR2I(int(x1 * MM), int(y1 * MM)))
                v.SetWidth(VIA_D)
                v.SetDrill(VIA_DRILL)
                v.SetLayerPair(pcbnew.F_Cu, pcbnew.B_Cu)
                v.SetNetCode(code)
                board.Add(v)
                report.append((str(name), "drop", d, "F.Cu-B.Cu", x1, y1))
            board.BuildConnectivity()
    if report:
        pcbnew.ZONE_FILLER(board).Fill(board.Zones())
        board.Save(path)
    for name, kind, d, where in ((r[0], r[1], r[2], r[3]) for r in report):
        what = ("%.0f um gap" % (d * 1000) if kind == "gap"
                else "a track that ended on a pad from the wrong layer")
        print(f"  {name}: {what} — {'joined on ' + where if kind == 'gap' else 'via added'}")
    return len(report)


def unconnected_nets(path):
    """The net names KiCad's DRC reports as having a missing connection."""
    import re
    import subprocess
    import tempfile
    with tempfile.NamedTemporaryFile(suffix=".rpt", delete=False) as f:
        rpt = f.name
    subprocess.run(["kicad-cli", "pcb", "drc", "--severity-error", "-o", rpt,
                    path], capture_output=True)
    text = open(rpt).read()
    os.unlink(rpt)
    out, block = [], False
    for line in text.splitlines():
        if "unconnected pads" in line:
            block = True
        elif line.startswith("** Found") and block:
            block = False
        elif block:
            m = re.search(r"\[([^\]]+)\]", line)
            if m and "]:" not in line:
                out.append(m.group(1))
    return sorted(set(out))


if __name__ == "__main__":
    p = sys.argv[1]
    m = float(sys.argv[2]) if len(sys.argv) > 2 else DEFAULT_MAX_MM
    nets = unconnected_nets(p)
    print(f"  nets DRC reports as broken: {', '.join(nets) or 'none'}")
    n = close(p, m, only=nets)
    print(f"OK  {n} repair(s) under {m} mm -> {p}")
