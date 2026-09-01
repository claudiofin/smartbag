#!/usr/bin/env python3
"""A maze router for the handful of connections freerouting gave up on.

⛔ WHY THIS EXISTS AND finish.py DOES NOT DO IT. finish.py tries nine shapes per
pad — a straight line and two L-bends, on three layers — and on a board this
dense every one of them crosses something. It is honest about that: it reports
"no shape fits" and stops. What it cannot do is go *around*, and going around is
the whole job. Four connections were left, one of them 108 mm end to end.

⭐ THE TRICK IS THAT ZONES ARE NOT OBSTACLES. Almost every square millimetre of
F.Cu and B.Cu is ground pour, so a router that treated the pour as solid would
find no route anywhere. It does not have to: KiCad re-fills the zone around
whatever copper it finds, so a new track lays itself into the pour and the pour
retracts. The obstacles are pads, tracks and vias belonging to OTHER nets, plus
the rule areas and the board edge. That is the difference between "impossible"
and "twenty seconds".

⭐ AND THE OBSTACLES ARE DRAWN, NOT COMPUTED. Testing a million grid points
against two thousand segments in Python is a minute per net; drawing those
segments into a bitmap with a brush already fattened by (their width + the
clearance + ours) is milliseconds, and gives exactly the same answer. Pillow is
the collision engine.

⚠️ IT PROPOSES, DRC DISPOSES. Every route is applied to a copy, checked by a real
`kicad-cli pcb drc`, and kept only if the board comes out with fewer unconnected
items and no new violations. The router's own clearance model is an
approximation — pads are inflated by their bounding box, not their true shape —
so it is allowed to be optimistic as long as something exact has the last word.

Usage:
  <kicad-python> hardware/maze.py hardware/smartbag_core.kicad_pcb
"""
import heapq
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile

import numpy as np
import pcbnew
from PIL import Image, ImageDraw

MM = 1e6                      # pcbnew works in nanometres
PITCH = 0.1                   # mm, one grid cell
TRACK_W = 0.1                 # mm, replaced per net from the netclass
CLEAR = 0.1                   # mm, likewise
VIA_D, VIA_DRILL = 0.25, 0.10
VIA_COST = 24                 # in cells: a via is worth about 2.4 mm of track
MARGIN = 18.0                 # mm of room around the two endpoints to search in

LAYERS = [pcbnew.F_Cu, pcbnew.In2_Cu, pcbnew.B_Cu]
ALL_CU = [pcbnew.F_Cu, pcbnew.In1_Cu, pcbnew.In2_Cu, pcbnew.B_Cu]


# ── the DRC report tells us what is still open ───────────────────────────────
def drc(path, report=None, kinds=None):
    """(violations, unconnected, [(a, b, netname)]) from a real DRC run."""
    tmp = report or tempfile.NamedTemporaryFile(suffix=".rpt", delete=False).name
    subprocess.run(["kicad-cli", "pcb", "drc", "--schematic-parity",
                    "--severity-error", "-o", tmp, path],
                   capture_output=True)
    text = open(tmp).read()
    v = int(re.search(r"Found (\d+) DRC violations", text).group(1))
    u = int(re.search(r"Found (\d+) unconnected pads", text).group(1))
    pairs = []
    for block in text.split("[unconnected_items]")[1:]:
        # ⚠️ "Pad 10 [VDD_3V3]" has the pad number between the word and the net,
        # and the first version of this pattern required them to be adjacent —
        # so every pair lost its second endpoint and the router reported that
        # there was nothing to route.
        pts = re.findall(
            r"@\((-?[\d.]+) mm, (-?[\d.]+) mm\): (\w+)[^\[\n]*\[([^\]]*)\]",
            block[:400])
        if len(pts) >= 2 and pts[0][2] != "Zone" and pts[1][2] != "Zone":
            a = (float(pts[0][0]), float(pts[0][1]))
            b = (float(pts[1][0]), float(pts[1][1]))
            pairs.append((a, b, pts[0][3]))
    if kinds is not None:
        kinds.clear()
        for k in re.findall(r"^\[(\w+)\]", text, re.M):
            kinds[k] = kinds.get(k, 0) + 1
    if report is None:
        os.unlink(tmp)
    return v, u, pairs


# ⛔ A SHORT IS A CLEARANCE VIOLATION THAT WENT ALL THE WAY. freerouting laid
# QI_ILIM across VDD_3V3 on an inner layer and DRC called it shorting_items
# rather than clearance — a different word for the same pair of tracks in the
# same place, and the repair is identical. Leaving shorts out of this list meant
# the one violation that can destroy a board was the one nothing acted on.
OFFENCES = ("[clearance]", "[shorting_items]")


def clearance_pairs(path):
    """[(x, y, netname, length_mm)] for every item in a clearance or short."""
    tmp = tempfile.NamedTemporaryFile(suffix=".rpt", delete=False).name
    subprocess.run(["kicad-cli", "pcb", "drc", "--schematic-parity",
                    "--severity-error", "-o", tmp, path], capture_output=True)
    text = open(tmp).read()
    os.unlink(tmp)
    out = []
    blocks = []
    for kind in OFFENCES:
        blocks += text.split(kind)[1:]
    for block in blocks:
        # ⚠️ Vias offend too, and the first version of this pattern only read
        # tracks — so a QI_ILIM via sitting 0.0016 mm from a VDD_3V3 track was a
        # violation nothing could act on, and the tool kept reporting "0 ripped"
        # against a DRC report it had just read. A via is given length 0 so that
        # when it is paired with a track the via is always the one removed: a
        # layer change is cheap to redo, four millimetres of routed track is not.
        for m in re.finditer(
                r"@\((-?[\d.]+) mm, (-?[\d.]+) mm\): (Track|Via) \[([^\]]*)\]"
                r"[^\n]*?(?:length ([\d.]+) mm)?$", block[:400], re.M):
            out.append((float(m.group(1)), float(m.group(2)), m.group(4),
                        float(m.group(5)) if m.group(5) else 0.0))
    return out


def drop_dangling(path):
    """Delete fanout vias the router never used. Returns how many.

    ⛔ A VIA THAT GOES NOWHERE IS A DRILL HIT SOMEBODY PAYS FOR. qfn_fanout()
    puts one outside every signal pin of the dense packages so the router has
    three layers to start on instead of one — which took the board from ten
    unconnected pads to one — and the router does not need all of them. Nine
    were left connected on a single layer, and a fabrication package that ships
    them is asking for holes nothing uses.

    ⚠️ Vias only. DRC also reports dangling TRACKS, and those are not the same
    thing: a track stub is usually the near end of a connection that did not
    finish, and deleting it removes the evidence of what is missing.
    """
    tmp = tempfile.NamedTemporaryFile(suffix=".rpt", delete=False).name
    subprocess.run(["kicad-cli", "pcb", "drc", "--severity-all", "-o", tmp,
                    path], capture_output=True)
    text = open(tmp).read()
    os.unlink(tmp)
    pts = []
    for block in text.split("[via_dangling]")[1:]:
        m = re.search(r"@\((-?[\d.]+) mm, (-?[\d.]+) mm\)", block[:200])
        if m:
            pts.append((float(m.group(1)), float(m.group(2))))
    if not pts:
        return 0
    board = pcbnew.LoadBoard(path)
    doomed = []
    for t in list(board.GetTracks()):
        if t.Type() != pcbnew.PCB_VIA_T:
            continue
        p = t.GetPosition()
        if any(abs(p.x / MM - x) < 0.02 and abs(p.y / MM - y) < 0.02
               for x, y in pts):
            doomed.append(t)
    for t in doomed:
        board.Remove(t)
    if doomed:
        pcbnew.ZONE_FILLER(board).Fill(board.Zones())
        board.Save(path)
    return len(doomed)


def rip_offenders(path):
    """Delete the shorter track of each clearance pair. Returns how many.

    ⛔ A ROUTER THAT CANNOT UNDO CANNOT REPAIR. maze.py could only ever add
    copper, so a board that came back from freerouting with two tracks 0.127 mm
    apart where the Power class asks for 0.15 was a board it had nothing to say
    about — it would refuse its own routes for making a bad number worse and
    stop. Removing the offending piece first turns a clearance violation into an
    unconnected pad, which is the one problem this file knows how to solve.

    ⚠️ THE SHORTER ONE, and that is a real choice rather than a coin toss: these
    pairs are almost always a long working track and a stub the optimiser left
    behind at a junction. Ripping the long one throws away a route that was fine
    everywhere except one corner.
    """
    pairs = clearance_pairs(path)
    if not pairs:
        return 0
    board = pcbnew.LoadBoard(path)
    victims = {}
    for i in range(0, len(pairs) - 1, 2):
        a, b = pairs[i], pairs[i + 1]
        v = a if a[3] <= b[3] else b
        victims[(round(v[0], 4), round(v[1], 4))] = v[2]
    # ⚠️ MATCH BY NET AND NEARNESS, NOT BY EXACT START POINT. DRC reports a point
    # ON the offending track, which is its start only sometimes; keying on the
    # start meant the tool reported "0 ripped" while the violation it had just
    # read was still there. Anything of the right net with an end within a tenth
    # of a millimetre of the reported point is the track that was meant.
    doomed = []
    for t in list(board.GetTracks()):
        for (vx, vy), net in victims.items():
            if t.GetNetname() != net:
                continue
            ends = ((t.GetPosition(),) if t.Type() == pcbnew.PCB_VIA_T
                    else (t.GetStart(), t.GetEnd()))
            for e in ends:
                if abs(e.x / MM - vx) < 0.1 and abs(e.y / MM - vy) < 0.1:
                    doomed.append(t)
                    break
            else:
                continue
            break
    for t in doomed:
        board.Remove(t)
    if doomed:
        pcbnew.ZONE_FILLER(board).Fill(board.Zones())
        board.Save(path)
    return len(doomed)


def direct_join(path, a, b, netname, base_v, base_u):
    """Try the simplest thing first: a straight track between the two points.

    ⛔ THE MAZE ROUTER WAS FAILING ON GAPS A CHILD COULD DRAW. Two VREF fragments
    0.83 mm apart on the same layer, and A* produced a route that came back
    DRC-clean and still unconnected — seven times, on seven different nets. A
    hand-placed straight segment between the two reported points closed it
    immediately and cost nothing.
    ⭐ So the order is: try the line, then try the maze. The expensive machine
    exists for the 108 mm case that has to go around three components; asking it
    to solve a 0.8 mm gap was always going to be the part where its assumptions
    about anchors and layers earned nothing.

    ⚠️ Different layers get a via at the far end. Two fragments of one net that
    ended up on F and B are a layer change the router did not finish, and that is
    what a via is.
    """
    board = pcbnew.LoadBoard(path)
    net = board.GetNetcodeFromNetname(netname)
    if net == 0:
        return False
    layers = {}
    for t in list(board.GetTracks()):
        if t.GetNetCode() != net or t.Type() == pcbnew.PCB_VIA_T:
            continue
        for e in (t.GetStart(), t.GetEnd()):
            for pt in (a, b):
                if abs(e.x / MM - pt[0]) < 0.02 and abs(e.y / MM - pt[1]) < 0.02:
                    layers[pt] = t.GetLayer()
    for fp in board.GetFootprints():
        for pad in fp.Pads():
            if pad.GetNetCode() != net:
                continue
            p = pad.GetPosition()
            for pt in (a, b):
                if abs(p.x / MM - pt[0]) < 0.05 and abs(p.y / MM - pt[1]) < 0.05:
                    layers.setdefault(pt, pcbnew.F_Cu)

    la = layers.get(a, pcbnew.F_Cu)
    lb = layers.get(b, pcbnew.F_Cu)
    added = []
    if la != lb:
        v = pcbnew.PCB_VIA(board)
        v.SetPosition(pcbnew.VECTOR2I(int(b[0] * MM), int(b[1] * MM)))
        v.SetWidth(int(VIA_D * MM))
        v.SetDrill(int(VIA_DRILL * MM))
        v.SetLayerPair(pcbnew.F_Cu, pcbnew.B_Cu)
        v.SetNetCode(net)
        board.Add(v)
        added.append(v)
    t = pcbnew.PCB_TRACK(board)
    t.SetStart(pcbnew.VECTOR2I(int(a[0] * MM), int(a[1] * MM)))
    t.SetEnd(pcbnew.VECTOR2I(int(b[0] * MM), int(b[1] * MM)))
    t.SetWidth(int(TRACK_W * MM))
    t.SetLayer(la)
    t.SetNetCode(net)
    board.Add(t)
    added.append(t)
    pcbnew.ZONE_FILLER(board).Fill(board.Zones())
    board.Save(path)
    v2, u2, _ = drc(path)
    return u2 < base_u and v2 <= base_v


# ── the board, as three bitmaps ──────────────────────────────────────────────
class Grid:
    """Obstacle bitmaps for one net, over a window of the board.

    One image per routable layer for tracks, plus one more that is the union
    over EVERY copper layer — a via has to be clear on all of them, including
    the In1 plane it punches through.
    """

    def __init__(self, board, net, x0, y0, x1, y1, track_w=TRACK_W, clear=CLEAR):
        self.track_w, self.clear = track_w, clear
        self.x0, self.y0 = x0, y0
        self.w = int((x1 - x0) / PITCH) + 1
        self.h = int((y1 - y0) / PITCH) + 1
        self.net = net
        track_pad = (track_w / 2 + clear) / PITCH      # cells to fatten by
        via_pad = (VIA_D / 2 + clear) / PITCH

        self.track = {L: Image.new("1", (self.w, self.h), 0) for L in LAYERS}
        via_img = Image.new("1", (self.w, self.h), 0)
        draws = {L: ImageDraw.Draw(im) for L, im in self.track.items()}
        via_draw = ImageDraw.Draw(via_img)
        self.mine = {L: Image.new("1", (self.w, self.h), 0) for L in LAYERS}
        mine_draws = {L: ImageDraw.Draw(im) for L, im in self.mine.items()}

        def px(p):
            return ((p.x / MM - self.x0) / PITCH, (p.y / MM - self.y0) / PITCH)

        for t in board.GetTracks():
            own = t.GetNetCode() == net
            if t.Type() == pcbnew.PCB_VIA_T:
                r = t.GetWidth(pcbnew.F_Cu) / MM / 2 / PITCH
                c = px(t.GetPosition())
                if own:
                    for L in LAYERS:
                        mine_draws[L].ellipse(_box(c, r), fill=1)
                    continue
                via_draw.ellipse(_box(c, r + via_pad), fill=1)
                for L in LAYERS:
                    draws[L].ellipse(_box(c, r + track_pad), fill=1)
            else:
                L = t.GetLayer()
                a, b = px(t.GetStart()), px(t.GetEnd())
                r = t.GetWidth() / MM / 2 / PITCH
                if own:
                    if L in mine_draws:
                        mine_draws[L].line([a, b], fill=1, width=max(1, int(2 * r)))
                    continue
                # ⚠️ Round caps, and the width rounded UP. Pillow's `line` gives
                # a butt-ended rectangle, so a polyline's corners come out thin
                # and a route can be squeezed through the notch on the outside
                # of a bend — which is not a gap that exists on the board. The
                # first run produced nine clearance violations from exactly
                # that, plus a truncated width that under-inflated by up to one
                # cell.
                _w = math.ceil(2 * (r + via_pad)) + 1
                via_draw.line([a, b], fill=1, width=_w)
                via_draw.ellipse(_box(a, r + via_pad), fill=1)
                via_draw.ellipse(_box(b, r + via_pad), fill=1)
                if L in draws:
                    _w = math.ceil(2 * (r + track_pad)) + 1
                    draws[L].line([a, b], fill=1, width=_w)
                    draws[L].ellipse(_box(a, r + track_pad), fill=1)
                    draws[L].ellipse(_box(b, r + track_pad), fill=1)

        for fp in board.GetFootprints():
            for pad in fp.Pads():
                own = pad.GetNetCode() == net
                bb = pad.GetBoundingBox()
                lo = ((bb.GetLeft() / MM - self.x0) / PITCH,
                      (bb.GetTop() / MM - self.y0) / PITCH)
                hi = ((bb.GetRight() / MM - self.x0) / PITCH,
                      (bb.GetBottom() / MM - self.y0) / PITCH)
                for L in LAYERS:
                    if not pad.IsOnLayer(L):
                        continue
                    if own:
                        mine_draws[L].rectangle([lo, hi], fill=1)
                    else:
                        draws[L].rectangle([lo[0] - track_pad, lo[1] - track_pad,
                                            hi[0] + track_pad, hi[1] + track_pad],
                                           fill=1)
                if not own:
                    via_draw.rectangle([lo[0] - via_pad, lo[1] - via_pad,
                                        hi[0] + via_pad, hi[1] + via_pad], fill=1)

        # ⛔ Rule areas are not copper and block anyway: a fiducial's window and
        # the antenna's clearance are the two places on this board where the
        # absence of copper is the specification.
        for zone in board.Zones():
            if not zone.GetIsRuleArea():
                continue
            poly = zone.Outline()
            for i in range(poly.OutlineCount()):
                pts = [((poly.Outline(i).CPoint(k).x / MM - self.x0) / PITCH,
                        (poly.Outline(i).CPoint(k).y / MM - self.y0) / PITCH)
                       for k in range(poly.Outline(i).PointCount())]
                if len(pts) < 3:
                    continue
                if zone.GetDoNotAllowTracks():
                    for L in LAYERS:
                        draws[L].polygon(pts, fill=1)
                if zone.GetDoNotAllowVias():
                    via_draw.polygon(pts, fill=1)

        self.blocked = {L: np.array(im, dtype=bool) for L, im in self.track.items()}
        self.via_blocked = np.array(via_img, dtype=bool)
        self.own = {L: np.array(im, dtype=bool) for L, im in self.mine.items()}

        # ⚠️ Outside the board is not a place a track may go, and the edge needs
        # the same clearance as anything else. Drawn as a band along the outline
        # rather than by offsetting the polygon, which is non-convex here.
        edge = Image.new("1", (self.w, self.h), 1)
        ed = ImageDraw.Draw(edge)
        outline = []
        for d in board.GetDrawings():
            if d.GetLayer() == pcbnew.Edge_Cuts and d.GetShape() == pcbnew.SHAPE_T_SEGMENT:
                outline.append((px(d.GetStart()), px(d.GetEnd())))
        if outline:
            ring = _chain(outline)
            ed.polygon(ring, fill=0)
            ed.line(ring + [ring[0]], fill=1,
                    width=max(2, int(2 * (track_w / 2 + clear) / PITCH)))
        outside = np.array(edge, dtype=bool)
        for L in LAYERS:
            self.blocked[L] |= outside
        self.via_blocked |= outside

    def free_around(self, mm_xy, radius=0.1):
        """Clear a small disk so a pin can leave its own pad.

        ⛔ A 0.4 mm PITCH QFN HAS NO LEGAL CHANNEL ON A 0.1 mm GRID. The gap
        between two adjacent pads is 0.4 mm less the pad width; inflate the
        neighbours by clearance plus half a track and what is left is a fraction
        of one cell, so the grid seals the pin in and the router reports no
        route — for a pin that plainly has one, because the autorouter got forty
        others out of the same package.

        ⭐ The escape is opened here and judged by DRC afterwards, which is the
        arrangement this whole file runs on: be optimistic where the model is
        coarse, and let something exact refuse.
        """
        cx, cy = self.cell(mm_xy)
        r = int(radius / PITCH)
        y0, y1 = max(0, cy - r), min(self.h, cy + r + 1)
        x0, x1 = max(0, cx - r), min(self.w, cx + r + 1)
        yy, xx = np.ogrid[y0:y1, x0:x1]
        disk = (yy - cy) ** 2 + (xx - cx) ** 2 <= r * r
        for L in LAYERS:
            self.blocked[L][y0:y1, x0:x1] &= ~disk

    def cell(self, mm_xy):
        return (int(round((mm_xy[0] - self.x0) / PITCH)),
                int(round((mm_xy[1] - self.y0) / PITCH)))

    def mm(self, cell):
        return (self.x0 + cell[0] * PITCH, self.y0 + cell[1] * PITCH)


def rules_for(project, netname):
    """(track width, clearance) for one net, out of the project's own rules.

    ⛔ ONE HARDCODED CLEARANCE IS THE WRONG NUMBER FOR EVERY NET. This used 0.15
    mm for all of them — the Power class's figure — and the signal nets it was
    actually trying to route are Default, at 0.10. A tenth of a millimetre too
    much on each side of every obstacle is what turned a pin's escape channel
    into a sealed pocket of 79 cells: the router reported no route for a pin
    the autorouter had already got forty of its neighbours out of.
    """
    import json
    try:
        ns = json.load(open(project))["net_settings"]
    except Exception:
        return TRACK_W, CLEAR
    klass = "Default"
    for pat in ns.get("netclass_patterns") or []:
        if pat.get("pattern") == netname:
            klass = pat["netclass"]
            break
    for c in ns.get("classes") or []:
        if c.get("name") == klass:
            return (c.get("track_width", TRACK_W), c.get("clearance", CLEAR))
    return TRACK_W, CLEAR


def _box(c, r):
    return [c[0] - r, c[1] - r, c[0] + r, c[1] + r]


def _chain(segments):
    """Order edge segments into one closed ring of points."""
    pts = [segments[0][0], segments[0][1]]
    rest = list(segments[1:])
    while rest:
        for i, (a, b) in enumerate(rest):
            if _close(a, pts[-1]):
                pts.append(b)
            elif _close(b, pts[-1]):
                pts.append(a)
            else:
                continue
            rest.pop(i)
            break
        else:
            break
    return pts


def _close(a, b, tol=0.6):
    return abs(a[0] - b[0]) < tol and abs(a[1] - b[1]) < tol


# ── A* over (x, y, layer) ────────────────────────────────────────────────────
STEPS = [(1, 0, 10), (-1, 0, 10), (0, 1, 10), (0, -1, 10),
         (1, 1, 14), (1, -1, 14), (-1, 1, 14), (-1, -1, 14)]


def route(grid, start, goal):
    """A list of (x, y, layer) from start to goal, or None."""
    w, h = grid.w, grid.h
    nl = len(LAYERS)
    idx = {L: i for i, L in enumerate(LAYERS)}
    blocked = np.stack([grid.blocked[L] for L in LAYERS])       # (l, y, x)
    own = np.stack([grid.own[L] for L in LAYERS])
    viabad = grid.via_blocked

    def free(x, y, l):
        if not (0 <= x < w and 0 <= y < h):
            return False
        return own[l, y, x] or not blocked[l, y, x]

    sx, sy = start
    gx, gy = goal

    # ⛔ START AND FINISH ON THE LAYER THE NET IS ACTUALLY ON. "Any layer that is
    # not blocked here" is not the same thing: the router happily began on B.Cu
    # a tenth of a millimetre under a track that lives on In2.Cu, drew a
    # flawless wire and connected nothing — DRC clean, still unconnected, twice.
    # Copper of this net at this point is the only acceptable place to attach.
    def anchors(x, y, reach=int(2.0 / PITCH)):
        """Every cell of this net's own copper near (x, y).

        ⭐ ATTACHING ANYWHERE ALONG THE WIRE IS LEGAL, and insisting on the one
        point the DRC report happened to name is what made two of these
        unroutable: a pin on a 0.4 mm pitch package has one channel out, and if
        that channel is taken the router gives up — when the track it is trying
        to reach runs for two millimetres and any of it would have done.
        """
        out = []
        for l in range(nl):
            y0, y1 = max(0, y - reach), min(h, y + reach + 1)
            x0, x1 = max(0, x - reach), min(w, x + reach + 1)
            ys, xs = np.nonzero(own[l, y0:y1, x0:x1])
            out += [(int(xx) + x0, int(yy) + y0, l) for yy, xx in zip(ys, xs)]
        return out or [(x, y, l) for l in range(nl) if free(x, y, l)]

    starts = anchors(sx, sy)
    goals = set(anchors(gx, gy))
    if len(starts) > 4000 or len(goals) > 4000:      # a pour, not a wire
        starts = starts[:4000]
        goals = set(list(goals)[:4000])
    if not starts or not goals:
        return None

    def hcost(x, y):
        dx, dy = abs(x - gx), abs(y - gy)
        return 10 * (dx + dy) - 6 * min(dx, dy)

    INF = 1 << 60
    dist = {}
    prev = {}
    heap = []
    for s in starts:
        dist[s] = 0
        heapq.heappush(heap, (hcost(s[0], s[1]), 0, s))
    limit = 4_000_000
    seen = 0
    while heap:
        _f, d, cur = heapq.heappop(heap)
        if d > dist.get(cur, INF):
            continue
        if cur in goals:
            path = [cur]
            while path[-1] in prev:
                path.append(prev[path[-1]])
            return path[::-1]
        seen += 1
        if seen > limit:
            return None
        x, y, l = cur
        for dx, dy, step in STEPS:
            nx, ny = x + dx, y + dy
            if not free(nx, ny, l):
                continue
            nd = d + step
            key = (nx, ny, l)
            if nd < dist.get(key, INF):
                dist[key] = nd
                prev[key] = cur
                heapq.heappush(heap, (nd + hcost(nx, ny), nd, key))
        # a layer change, if a via fits here
        if not viabad[y, x]:
            for nl_ in range(len(LAYERS)):
                if nl_ == l or not free(x, y, nl_):
                    continue
                nd = d + VIA_COST * 10
                key = (x, y, nl_)
                if nd < dist.get(key, INF):
                    dist[key] = nd
                    prev[key] = cur
                    heapq.heappush(heap, (nd + hcost(x, y), nd, key))
    return None


def simplify(path):
    """Collapse the cell path into corner points, per layer run."""
    runs = []
    cur = [path[0]]
    for p in path[1:]:
        if p[2] != cur[-1][2]:
            runs.append(cur)
            cur = [p]
        else:
            cur.append(p)
    runs.append(cur)
    out = []
    for run in runs:
        pts = [run[0]]
        for i in range(1, len(run) - 1):
            ax, ay = run[i][0] - run[i - 1][0], run[i][1] - run[i - 1][1]
            bx, by = run[i + 1][0] - run[i][0], run[i + 1][1] - run[i][1]
            if (ax, ay) != (bx, by):
                pts.append(run[i])
        pts.append(run[-1])
        out.append((run[0][2], pts))
    return out


def apply(board, grid, path, net, ends=None):
    """Write the route onto the board. Returns the items added.

    ⛔ THE TWO ENDS ARE NOT ON THE GRID AND MUST NOT BE SNAPPED TO IT. A cell is
    0.1 mm; rounding the last point to the nearest one leaves the track ending up
    to 0.05 mm short of the thing it was drawn to reach, and a 0.1 mm track that
    stops 0.05 mm away from another one touches it by nothing. The route came
    back from DRC clean and still unconnected — a perfect wire to almost the
    right place. The interior may snap; the endpoints are exact.
    """
    items = []
    runs = simplify(path)
    exact = {}
    if ends:
        exact[(runs[0][1][0][0], runs[0][1][0][1])] = ends[0]
        exact[(runs[-1][1][-1][0], runs[-1][1][-1][1])] = ends[1]

    def at(cell):
        return exact.get((cell[0], cell[1]), grid.mm(cell[:2]))

    for layer_i, pts in runs:
        layer = LAYERS[layer_i]
        for a, b in zip(pts, pts[1:]):
            t = pcbnew.PCB_TRACK(board)
            t.SetStart(pcbnew.VECTOR2I(*[int(v * MM) for v in at(a)]))
            t.SetEnd(pcbnew.VECTOR2I(*[int(v * MM) for v in at(b)]))
            t.SetWidth(int(grid.track_w * MM))
            t.SetLayer(layer)
            t.SetNetCode(net)
            board.Add(t)
            items.append(t)
    for (l1, p1), (l2, _p2) in zip(runs, runs[1:]):
        v = pcbnew.PCB_VIA(board)
        v.SetPosition(pcbnew.VECTOR2I(*[int(x * MM) for x in grid.mm(p1[-1][:2])]))
        v.SetWidth(int(VIA_D * MM))
        v.SetDrill(int(VIA_DRILL * MM))
        v.SetLayerPair(pcbnew.F_Cu, pcbnew.B_Cu)
        v.SetNetCode(net)
        board.Add(v)
        items.append(v)
    return items


def main(path, rounds=4):
    """Route, then look again: joining one net changes what the others can do.

    ⛔ ONE PASS CLOSED ONE CONNECTION AND STOPPED. The list of open pairs is read
    from a DRC report taken before anything was routed, and a net that could not
    escape its pin at that moment may be able to once a neighbour's track has
    been laid somewhere else — or, more often, the pair's own second endpoint has
    moved because the copper it named is now part of a longer wire. Two rounds
    close what one round leaves; the loop stops as soon as a round gains nothing.
    """
    total = 0
    # ⚠️ IN ITS OWN PROCESS, and that is not tidiness. pcbnew keeps a board alive
    # behind the SWIG wrapper as long as anything references a track taken out of
    # it, and the next LoadBoard in the same interpreter then hands back a raw
    # pointer instead of a BOARD — which fails much later, on an unrelated line,
    # with an error about SwigPyObject having no netlist methods. A process
    # boundary is the only reliable way to put a board down.
    r = subprocess.run([sys.executable, __file__, "--rip", path],
                       capture_output=True, text=True)
    # ⚠️ The last integer line, not the whole of stdout: KiCad's Python prints
    # wxWidgets assertions to stdout before anything this file writes.
    ripped = 0
    for line in reversed((r.stdout or "").splitlines()):
        if line.strip().isdigit():
            ripped = int(line.strip())
            break
    if ripped:
        print(f"  ripped {ripped} track(s) that broke a clearance rule")
    for _ in range(rounds):
        gained = _pass(path)
        total += gained
        if not gained:
            break
    v, u, _ = drc(path)
    print(f"done: {v} violations, {u} unconnected, {total} joined")


def _pass(path):
    base_v, base_u, pairs = drc(path)
    print(f"start: {base_v} violations, {base_u} unconnected, "
          f"{len(pairs)} routable pairs")
    if not pairs:
        return 0
    pristine = path + ".maze-backup"
    shutil.copy(path, pristine)
    joined = 0

    for a, b, netname in pairs:
        board = pcbnew.LoadBoard(path)
        net = board.GetNetcodeFromNetname(netname)
        if net == 0:
            continue
        x0, x1 = sorted((a[0], b[0]))
        y0, y1 = sorted((a[1], b[1]))
        # ⭐ The straight line first, and only then the maze.
        if direct_join(path, a, b, netname, base_v, base_u):
            _v, base_u, _p = drc(path)
            print(f"  {netname}: joined with a straight line "
                  f"({base_u} unconnected left)")
            joined += 1
            shutil.copy(path, pristine)
            continue
        shutil.copy(pristine, path)

        tw, cl = rules_for(os.path.splitext(path)[0] + ".kicad_pro", netname)
        # ⭐ NECK DOWN AT THE PAD IF THE CLASS WIDTH WILL NOT FIT. A 0.30 mm
        # supply track needs a 0.60 mm channel to leave a 0.40 mm pitch QFN, and
        # there is not one; a 0.10 mm neck for the few millimetres it takes to
        # get clear is what a person would draw, and what the minimum track
        # width in the design rules exists to permit. It is tried second, so a
        # net that fits at its proper width still gets it.
        # ⭐ NECK DOWN AT THE PAD IF THE CLASS WIDTH WILL NOT FIT. A 0.30 mm
        # supply track needs a 0.60 mm channel to leave a 0.40 mm pitch QFN and
        # there is not one; a 0.10 mm neck for the few millimetres it takes to
        # get clear is what a person would draw, and what min_track_width in the
        # design rules exists to permit. Tried second, so a net that fits at its
        # proper width still gets it.
        #
        # ⚠️ ONE ESCAPE SIZE, NOT A LADDER OF THEM. Trying several and keeping
        # whichever DRC liked sounded strictly better and was strictly worse: it
        # found the same routes, spent four DRC runs per net doing it, and the
        # extra candidates were all near-misses that pushed the good one out.
        found = grid = None
        for width in (tw, TRACK_W) if tw > TRACK_W else (tw,):
            grid = Grid(board, net, x0 - MARGIN, y0 - MARGIN,
                        x1 + MARGIN, y1 + MARGIN, track_w=width, clear=cl)
            grid.free_around(a)
            grid.free_around(b)
            found = route(grid, grid.cell(a), grid.cell(b))
            if found:
                if width != tw:
                    print(f"  {netname}: necked down to {width} mm to get out")
                break
        if not found:
            print(f"  {netname}: no route in a {2 * MARGIN:.0f} mm corridor")
            continue
        apply(board, grid, found, net, ends=(a, b))
        # ⛔ THE POUR HAS TO BE RE-FILLED BEFORE ANYONE JUDGES THE ROUTE. This
        # file's whole premise is that a zone is not an obstacle because KiCad
        # retracts it around new copper — and then it saved the board with the
        # OLD fill still lying on top of the track it had just drawn. DRC read
        # that as the pour touching the route and refused every one, which is
        # the correct answer to the question it was actually asked.
        pcbnew.ZONE_FILLER(board).Fill(board.Zones())
        board.Save(path)
        kinds = {}
        v, u, still = drc(path, kinds=kinds)
        # ⛔ "FEWER UNCONNECTED" IS THE WRONG TEST ON A BOARD WITH SEVERAL GAPS.
        # Closing one can reveal the next: KiCad reports one ratsnest line per
        # net, so joining two fragments of a net that is broken in two places
        # leaves the count exactly where it was, and a route that was correct and
        # DRC-clean got thrown away seven times in a row for it.
        #
        # ⭐ The honest question is whether THIS pair is gone. It is asked
        # directly, and the count is still not allowed to rise.
        closed = not any(abs(pa[0] - a[0]) < 0.01 and abs(pa[1] - a[1]) < 0.01
                         and abs(pb[0] - b[0]) < 0.01 and abs(pb[1] - b[1]) < 0.01
                         for pa, pb, _n in still)
        if closed and u <= base_u and v <= base_v:
            print(f"  {netname}: joined "
                  f"({len(simplify(found))} segments, {u} unconnected left)")
            base_u, base_v = u, v
            joined += 1
            shutil.copy(path, pristine)
        else:
            detail = ", ".join(f"{n}x {k}" for k, n in sorted(kinds.items())
                               if k != "unconnected_items")
            print(f"  {netname}: route found but DRC refused it "
                  f"({v} violations, {u} unconnected) — {detail}")
            shutil.copy(pristine, path)

    os.unlink(pristine)
    return joined


if __name__ == "__main__":
    if len(sys.argv) > 2 and sys.argv[1] == "--rip":
        print(rip_offenders(sys.argv[2]))
    elif len(sys.argv) > 2 and sys.argv[1] == "--tidy":
        print(drop_dangling(sys.argv[2]))
    else:
        main(sys.argv[1])
