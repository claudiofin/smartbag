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
PITCH = 0.1                   # mm, one grid cell (see FINE_PITCH)
FINE_PITCH = 0.05             # mm, the second attempt
TRACK_W = 0.1                 # mm, replaced per net from the netclass
CLEAR = 0.1                   # mm, likewise
VIA_D, VIA_DRILL = 0.25, 0.10
VIA_COST = 24                 # in cells: a via is worth about 2.4 mm of track
MARGIN = 18.0                 # mm of room around the two endpoints to search in

# ⚠️ In1 and In4 are ground planes and are not routed on; In2 and In3 are
# the signal pair between them. Four routable layers, not three.
LAYERS = [pcbnew.F_Cu, pcbnew.In2_Cu, pcbnew.In3_Cu, pcbnew.B_Cu]
ALL_CU = [pcbnew.F_Cu, pcbnew.In1_Cu, pcbnew.In2_Cu, pcbnew.In3_Cu,
          pcbnew.In4_Cu, pcbnew.B_Cu]


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
    """Remove fanout vias nothing ever used. Returns how many.

    ⛔ AND NOT THE ONES THAT ARE A PIN'S ONLY WAY OFF THE TOP LAYER. That
    exception is the whole of this function's history. generate_pcb.py puts a
    via 0.35 mm outside every signal pad of the dense QFNs so a signal can leave
    the package on F.Cu and immediately drop; the autorouter uses most of them
    and leaves the rest looking unused. They are not unused — they are the only
    thing standing between a pad and the other three layers.
    ⚠️ Removing two of them stranded U1's pins 10 and 22 on F.Cu inside a 0.4 mm
    escape row, and every router in this repository then reported, correctly,
    that there was no way out. Three tools and several hours went into the
    consequences of a tidy-up.
    """
    v, _u, _pairs = drc(path)
    report = tempfile.NamedTemporaryFile(suffix=".rpt", delete=False).name
    subprocess.run(["kicad-cli", "pcb", "drc", "--severity-all", "-o", report,
                    path], capture_output=True)
    text = open(report).read()
    os.unlink(report)
    pts = []
    for block in text.split("[via_dangling]")[1:]:
        m = re.search(r"@\((-?[\d.]+) mm, (-?[\d.]+) mm\)", block[:200])
        if m:
            pts.append((float(m.group(1)), float(m.group(2))))
    if not pts:
        return 0
    board = pcbnew.LoadBoard(path)
    doomed, spared = [], 0
    for t in list(board.GetTracks()):
        if t.Type() != pcbnew.PCB_VIA_T:
            continue
        p = t.GetPosition()
        if not any(abs(p.x / MM - x) < 0.02 and abs(p.y / MM - y) < 0.02
                   for x, y in pts):
            continue
        # ⭐ Is this via the only multi-layer access of a pad that has none?
        # If the island it sits on contains a pad and no other via, it is.
        net = t.GetNetCode()
        island = _island_tracks(board, net, (p.x / MM, p.y / MM))
        pads = [i for i in island if i.Type() == pcbnew.PCB_PAD_T]
        vias = [i for i in island if i.Type() == pcbnew.PCB_VIA_T]
        if pads and len(vias) <= 1:
            spared += 1
            continue
        doomed.append(t)
    for t in doomed:
        board.Remove(t)
    if doomed:
        pcbnew.ZONE_FILLER(board).Fill(board.Zones())
        board.Save(path)
    if spared:
        print(f"  {spared} dangling via(s) kept: a pad's only escape")
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

    def __init__(self, board, net, x0, y0, x1, y1, track_w=TRACK_W, clear=CLEAR,
                 pitch=PITCH):
        self.track_w, self.clear, self.pitch = track_w, clear, pitch
        self.x0, self.y0 = x0, y0
        PITCH_ = pitch
        self.w = int((x1 - x0) / PITCH_) + 1
        self.h = int((y1 - y0) / PITCH_) + 1
        self.net = net
        track_pad = (track_w / 2 + clear) / PITCH_     # cells to fatten by
        via_pad = (VIA_D / 2 + clear) / PITCH_

        self.track = {L: Image.new("1", (self.w, self.h), 0) for L in LAYERS}
        via_img = Image.new("1", (self.w, self.h), 0)
        draws = {L: ImageDraw.Draw(im) for L, im in self.track.items()}
        via_draw = ImageDraw.Draw(via_img)
        self.mine = {L: Image.new("1", (self.w, self.h), 0) for L in LAYERS}
        mine_draws = {L: ImageDraw.Draw(im) for L, im in self.mine.items()}

        def px(p):
            return ((p.x / MM - self.x0) / PITCH_, (p.y / MM - self.y0) / PITCH_)

        for t in board.GetTracks():
            own = t.GetNetCode() == net
            if t.Type() == pcbnew.PCB_VIA_T:
                r = t.GetWidth(pcbnew.F_Cu) / MM / 2 / PITCH_
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
                r = t.GetWidth() / MM / 2 / PITCH_
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
                lo = ((bb.GetLeft() / MM - self.x0) / PITCH_,
                      (bb.GetTop() / MM - self.y0) / PITCH_)
                hi = ((bb.GetRight() / MM - self.x0) / PITCH_,
                      (bb.GetBottom() / MM - self.y0) / PITCH_)
                for L in LAYERS:
                    if not pad.IsOnLayer(L):
                        continue
                    if own:
                        mine_draws[L].rectangle([lo, hi], fill=1)
                    else:
                        draws[L].rectangle(_rect(lo, hi, track_pad), fill=1)
                if not own:
                    via_draw.rectangle(_rect(lo, hi, via_pad), fill=1)

        # ⛔ Rule areas are not copper and block anyway: a fiducial's window and
        # the antenna's clearance are the two places on this board where the
        # absence of copper is the specification.
        for zone in board.Zones():
            if not zone.GetIsRuleArea():
                continue
            poly = zone.Outline()
            for i in range(poly.OutlineCount()):
                pts = [((poly.Outline(i).CPoint(k).x / MM - self.x0) / PITCH_,
                        (poly.Outline(i).CPoint(k).y / MM - self.y0) / PITCH_)
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
                    width=max(2, int(2 * (track_w / 2 + clear) / PITCH_)))
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
        r = int(radius / self.pitch)
        y0, y1 = max(0, cy - r), min(self.h, cy + r + 1)
        x0, x1 = max(0, cx - r), min(self.w, cx + r + 1)
        yy, xx = np.ogrid[y0:y1, x0:x1]
        disk = (yy - cy) ** 2 + (xx - cx) ** 2 <= r * r
        for L in LAYERS:
            self.blocked[L][y0:y1, x0:x1] &= ~disk

    def cell(self, mm_xy):
        return (int(round((mm_xy[0] - self.x0) / self.pitch)),
                int(round((mm_xy[1] - self.y0) / self.pitch)))

    def mm(self, cell):
        return (self.x0 + cell[0] * self.pitch, self.y0 + cell[1] * self.pitch)


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


def _rect(lo, hi, pad):
    """A pad's bounding box grown by `pad` cells, rounded OUT — see _box."""
    pad = math.ceil(pad) + 1
    return [math.floor(lo[0]) - pad, math.floor(lo[1]) - pad,
            math.ceil(hi[0]) + pad, math.ceil(hi[1]) + pad]


def _box(c, r):
    """A bounding box for an obstacle circle of radius `r` cells, rounded OUT.

    ⛔ PILLOW DRAWS ELLIPSES TO WHOLE PIXELS AND ROUNDS THEM IN. The line case a
    few dozen lines up already knew this — it takes math.ceil of the width and
    adds one — and the ellipse case did not, so every via on the board was drawn
    as an obstacle up to a cell smaller than it is. At the fine 0.05 mm grid that
    is 50 micrometres of clearance the router believed it had and did not.
    That is not a rounding curiosity: it is exactly the size of the failures.
    SPI_MISO came back from a 2264-cell search with sixteen clearance violations
    of 0.02 to 0.08 mm, every one of them a track passing a via, and the router
    had proposed each of them believing it was legal. A collision model that is
    optimistic by less than a cell produces routes that are wrong by less than a
    cell, which is the hardest kind of wrong to see and the easiest to fix.
    """
    r = math.ceil(r) + 1
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


def _layer_at(board, net, pt):
    """Which copper layer this net already occupies at a point, or None."""
    for t in list(board.GetTracks()):
        if t.GetNetCode() != net or t.Type() == pcbnew.PCB_VIA_T:
            continue
        for e in (t.GetStart(), t.GetEnd()):
            if abs(e.x / MM - pt[0]) < 0.03 and abs(e.y / MM - pt[1]) < 0.03:
                return t.GetLayer()
    for fp in board.GetFootprints():
        for pad in fp.Pads():
            if pad.GetNetCode() != net:
                continue
            p = pad.GetPosition()
            if abs(p.x / MM - pt[0]) < 0.06 and abs(p.y / MM - pt[1]) < 0.06:
                return pcbnew.F_Cu
    return None


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
    def add_via(xy):
        v = pcbnew.PCB_VIA(board)
        v.SetPosition(pcbnew.VECTOR2I(int(xy[0] * MM), int(xy[1] * MM)))
        v.SetWidth(int(VIA_D * MM))
        v.SetDrill(int(VIA_DRILL * MM))
        v.SetLayerPair(pcbnew.F_Cu, pcbnew.B_Cu)
        v.SetNetCode(net)
        board.Add(v)
        items.append(v)

    for (l1, p1), (l2, _p2) in zip(runs, runs[1:]):
        add_via(grid.mm(p1[-1][:2]))

    # ⛔ AND A VIA AT EACH END IF THE ROUTE LANDS ON THE WRONG LAYER. The path
    # may legitimately start on B.Cu — that is what makes it routable — while
    # the fragment it has to reach is a 0.35 mm stub on F.Cu. The wire then comes
    # back from DRC beautifully drawn, clearance-clean and STILL UNCONNECTED,
    # which is the single most confusing failure this file can produce and cost
    # seven refused routes before anyone looked at which layer each end was on.
    if ends:
        for xy, (layer_i, pts) in ((ends[0], runs[0]), (ends[1], runs[-1])):
            want = _layer_at(board, net, xy)
            if want is not None and want != LAYERS[layer_i]:
                add_via(xy)
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


def _island_of(board, net, at):
    """Every point of the piece of `net` that contains the item at `at`."""
    cn = board.GetConnectivity()
    seed, best = None, None
    for t in board.GetTracks():
        if t.GetNetCode() != net:
            continue
        for e in ((t.GetPosition(),) if t.Type() == pcbnew.PCB_VIA_T
                  else (t.GetStart(), t.GetEnd())):
            d = math.hypot(e.x / MM - at[0], e.y / MM - at[1])
            if best is None or d < best:
                best, seed = d, t
    for f in board.GetFootprints():
        for p in f.Pads():
            if p.GetNetCode() != net:
                continue
            c = p.GetCenter()
            d = math.hypot(c.x / MM - at[0], c.y / MM - at[1])
            if best is None or d < best:
                best, seed = d, p
    if seed is None or best > 0.05:
        return None
    pts = []
    for it in cn.GetConnectedItems(seed):
        ty = it.Type()
        if ty == pcbnew.PCB_PAD_T:
            ls = it.GetLayerSet().CuStack()
            c = it.GetCenter()
            pts.append((c.x / MM, c.y / MM, ls[0] if len(ls) == 1 else None))
        elif ty == pcbnew.PCB_VIA_T:
            p = it.GetPosition()
            pts.append((p.x / MM, p.y / MM, None))
        elif ty == pcbnew.PCB_TRACE_T:
            L = it.GetLayer()
            pts.append((it.GetStart().x / MM, it.GetStart().y / MM, L))
            pts.append((it.GetEnd().x / MM, it.GetEnd().y / MM, L))
    return pts or None


def _island_tracks(board, net, at):
    """The TRACK items of the piece of `net` containing the item at `at`.

    ⛔ PROXIMITY IS NOT MEMBERSHIP, AND CONFUSING THE TWO WASTED A ROUND OF
    THIS. The via has to land on the copper of the island you are coming FROM;
    picking candidate points by "within 3 mm of that end" picks points on the
    island you are trying to reach, because the two ends are a millimetre apart.
    Every candidate was then a via placed on the far island, connected to
    nothing new, and DRC correctly reported no improvement.
    """
    cn = board.GetConnectivity()
    seed, best = None, None
    for t in board.GetTracks():
        if t.GetNetCode() != net:
            continue
        for e in ((t.GetPosition(),) if t.Type() == pcbnew.PCB_VIA_T
                  else (t.GetStart(), t.GetEnd())):
            d = math.hypot(e.x / MM - at[0], e.y / MM - at[1])
            if best is None or d < best:
                best, seed = d, t
    for f in board.GetFootprints():
        for p in f.Pads():
            if p.GetNetCode() != net:
                continue
            c = p.GetCenter()
            d = math.hypot(c.x / MM - at[0], c.y / MM - at[1])
            if best is None or d < best:
                best, seed = d, p
    if seed is None or best > 0.05:
        return []
    return list(cn.GetConnectedItems(seed))


def _island_of_kind(board, net, at, kind):
    return [it for it in _island_tracks(board, net, at) if it.Type() == kind]


def nearest_ends(board, net, a, b):
    """⛔ THE PAIR DRC NAMES IS NOT THE PAIR THAT HAS TO BE JOINED. KiCad reports
    one REPRESENTATIVE item per disconnected island, so a net whose two halves
    nearly touch under a package gets reported as a pad at one end of the board
    and a track at the other — and the router is sent ten millimetres across the
    most congested copper on the design when the answer is a via 0.35 mm away.
    ⭐ These are the two ends that actually need joining, with their layers."""
    ia, ib = _island_of(board, net, a), _island_of(board, net, b)
    if not ia or not ib:
        return None
    best = None
    for x1, y1, l1 in ia:
        for x2, y2, l2 in ib:
            d = math.hypot(x1 - x2, y1 - y2)
            if best is None or d < best[0]:
                best = (d, (round(x1, 4), round(y1, 4)),
                        (round(x2, 4), round(y2, 4)), l1, l2)
    if not best:
        return None
    return best[1], best[2], best[3], best[4], best[0]


def net_breaks(path, netname, report=None):
    """How many unconnected items DRC reports for ONE net.

    ⛔ THE ONLY ACCEPTANCE TEST THAT CANNOT BE FOOLED, AND IT TOOK THREE WRONG
    ONES TO GET HERE. "Fewer unconnected pads on the board" is wrong: KiCad
    reports one ratsnest line per net, so closing one of a net's two breaks
    changes nothing and a correct repair gets thrown away. "The pair DRC named
    is gone" is wrong: KiCad picks a different representative item every run, so
    that is always true and this file once accepted twelve vias that connected
    nothing. Counting islands with GetConnectedItems is wrong too — it reported
    two pieces where DRC clearly saw three.
    ⭐ Asking DRC how many breaks THIS net has left is the same question, put to
    the same referee that decides whether the board ships.
    """
    tmp = report or tempfile.NamedTemporaryFile(suffix=".rpt", delete=False).name
    subprocess.run(["kicad-cli", "pcb", "drc", "--schematic-parity",
                    "--severity-error", "-o", tmp, path], capture_output=True)
    text = open(tmp).read()
    n = 0
    for block in text.split("[unconnected_items]")[1:]:
        if f"[{netname}]" in block[:400]:
            n += 1
    v = int(re.search(r"Found (\d+) DRC violations", text).group(1))
    if report is None:
        os.unlink(tmp)
    return n, v


def _clear_hit(x, y, r, board, net, layer=None):
    """Does a circle of radius r at (x, y) touch another net on `layer`?"""
    for t in board.GetTracks():
        if t.GetNetCode() == net:
            continue
        if t.Type() == pcbnew.PCB_VIA_T:
            p = t.GetPosition()
            if math.hypot(p.x / MM - x, p.y / MM - y) < r + 0.125:
                return True
            continue
        if layer is not None and t.GetLayer() != layer:
            continue
        ax, ay = t.GetStart().x / MM, t.GetStart().y / MM
        bx, by = t.GetEnd().x / MM, t.GetEnd().y / MM
        dx, dy = bx - ax, by - ay
        if dx or dy:
            u = max(0.0, min(1.0, ((x - ax) * dx + (y - ay) * dy)
                             / (dx * dx + dy * dy)))
            px, py = ax + u * dx, ay + u * dy
        else:
            px, py = ax, ay
        if math.hypot(x - px, y - py) < r + t.GetWidth() / MM / 2:
            return True
    for f in board.GetFootprints():
        for pad in f.Pads():
            if pad.GetNetCode() == net:
                continue
            if layer is not None and not pad.IsOnLayer(layer):
                continue
            bb = pad.GetBoundingBox()
            if (bb.GetLeft() / MM - r <= x <= bb.GetRight() / MM + r
                    and bb.GetTop() / MM - r <= y <= bb.GetBottom() / MM + r):
                return True
    return False


def link_islands(path, project, netname, base_v):
    """Close every break in one net with a via and a stub. Returns breaks left.

    ⛔ NONE OF THE THREE CONNECTIONS THIS BOARD COULD NOT CLOSE WAS A ROUTING
    PROBLEM. Every one was a net whose two halves end a millimetre apart on
    DIFFERENT LAYERS: an In2 track finishing 1.2 mm from a pad on F.Cu, a B.Cu
    track finishing exactly on an F.Cu pad. There is no path to find — the
    straight line is obvious. What is missing is the via, and WHERE the via goes
    is the whole question, because a through via is an obstacle on four layers
    and the obvious spot always has somebody else's track under it.

    ⚠️ AND THE CLEARANCE HAS TO BE THE NET'S OWN. An earlier version of this
    search used 0.15 mm for everything — the Power class figure — against nets
    that are Default at 0.10, and reported that there was nowhere to put a via
    in a region where there plainly was. That is the same mistake rules_for()
    was written to stop, made again two hundred lines below it.
    """
    _w, clear = rules_for(project, netname)
    board = pcbnew.LoadBoard(path)
    net = board.GetNetcodeFromNetname(netname)
    if net == 0:
        return 0
    breaks, _v = net_breaks(path, netname)
    pristine = path + ".link-backup"

    for _round in range(6):
        if breaks == 0:
            break
        board = pcbnew.LoadBoard(path)
        _bv, _bu, pairs = drc(path)
        mine = [p for p in pairs if p[2] == netname]
        if not mine:
            break
        a0, b0, _n = mine[0]
        near = nearest_ends(board, net, a0, b0)
        # ⛔ A "GAP" OF ZERO ON ONE LAYER MEANS THE REFINEMENT FAILED, NOT THAT
        # THE NET IS JOINED. It happens when both DRC representatives resolve to
        # the same island — KiCad's connectivity query does not always give back
        # the piece you asked about — and the search then hunts around a point
        # that is not the problem. The reported pair is the fallback: cruder,
        # and it is what actually closed FSR_R2.
        if near and near[4] < 0.001 and near[2] == near[3]:
            near = None
        if not near:
            a, b, la, lb, gap = a0, b0, None, None, math.hypot(
                b0[0] - a0[0], b0[1] - a0[1])
        else:
            a, b, la, lb, gap = near

        # ⭐ The via goes on ONE island's copper and the stub runs on the OTHER
        # island's layer to its end. Anything else connects to only one of them.
        # ⚠️ EVERY LAYER FOR THE STUB, NOT JUST THE FAR END'S. Constraining it
        # to the destination end's layer looks right and is not: the far island
        # may be a via, or may occupy several layers where the stub arrives, and
        # the combination that actually merged FSR_R2 was a stub on the layer of
        # the NEAR end. What must be constrained is where the via lands — on the
        # source island's own copper — and DRC settles the rest.
        plan = []
        for src, dst in ((a, b), (b, a)):
            # ⭐ The island the via must land on, not everything nearby.
            pts = []
            for t in _island_of_kind(board, net, src, pcbnew.PCB_TRACE_T):
                p = (t.GetStart().x / MM, t.GetStart().y / MM)
                q = (t.GetEnd().x / MM, t.GetEnd().y / MM)
                if min(math.hypot(p[0] - dst[0], p[1] - dst[1]),
                       math.hypot(q[0] - dst[0], q[1] - dst[1])) > 6.0:
                    continue
                n = max(1, int(math.hypot(q[0] - p[0], q[1] - p[1]) / 0.1))
                for i in range(n + 1):
                    u = i / n
                    pts.append((p[0] + (q[0] - p[0]) * u,
                                p[1] + (q[1] - p[1]) * u))
            pts.sort(key=lambda P: math.hypot(P[0] - dst[0], P[1] - dst[1]))
            if os.environ.get("MAZE_DEBUG"):
                print(f"    [dbg] {netname}: {len(pts)} points on the island of "
                      f"({src[0]:.3f},{src[1]:.3f}) toward "
                      f"({dst[0]:.3f},{dst[1]:.3f})")
            for vx, vy in pts[:200]:
                if _clear_hit(vx, vy, 0.125 + clear, board, net):
                    continue
                if math.hypot(vx - dst[0], vy - dst[1]) < 0.01:
                    plan.append(((vx, vy), None, dst))
                    continue
                n = max(2, int(math.hypot(dst[0] - vx, dst[1] - vy) / 0.05))
                for dst_layer in LAYERS:
                    if any(_clear_hit(vx + (dst[0] - vx) * i / n,
                                      vy + (dst[1] - vy) * i / n,
                                      TRACK_W / 2 + clear, board, net, dst_layer)
                           for i in range(n + 1)):
                        continue
                    plan.append(((vx, vy), dst_layer, dst))
                if len(plan) >= 12:
                    break
            if len(plan) >= 12:
                break

        # ⭐ AND SOMETIMES NO NEW VIA IS NEEDED AT ALL, WHICH IS THE CASE THIS
        # SEARCH KEPT MISSING. If the island already has a via near the gap it
        # is already on every layer, and the whole repair is a track. VDD_3V3's
        # U1.10 island has a fanout via 1.45 mm from the In2 run it has to reach
        # — and this function spent every candidate trying to add a second via
        # beside the first, in the one place on the board where there is no room
        # for one.
        if not plan:
            for src, dst in ((a, b), (b, a)):
                # ⚠️ The via has to be on the SOURCE island — "a via somewhere
                # near" picked one 5 mm away on a different piece of the net and
                # proposed a track from it, which connects nothing.
                for t in _island_of_kind(board, net, src, pcbnew.PCB_VIA_T):
                    p = (t.GetPosition().x / MM, t.GetPosition().y / MM)
                    if math.hypot(p[0] - dst[0], p[1] - dst[1]) > 6.0:
                        continue
                    n = max(2, int(math.hypot(dst[0] - p[0],
                                              dst[1] - p[1]) / 0.05))
                    for L in LAYERS:
                        if any(_clear_hit(p[0] + (dst[0] - p[0]) * i / n,
                                          p[1] + (dst[1] - p[1]) * i / n,
                                          TRACK_W / 2 + clear, board, net, L)
                               for i in range(n + 1)):
                            continue
                        plan.append((p, L, dst, True))
            plan = [(v, l, d, True) for v, l, d, *_ in plan]

        # ⭐ AND IF NEITHER END HAS ROOM, JOIN THE ISLANDS SOMEWHERE ELSE. The
        # two ends DRC points at are where the gap is NARROWEST, which on a
        # dense board is also where there is least room — VDD_3V3's 1.2 mm gap
        # is under a QFN48 with thirty-five escapes through it. But an island is
        # not a point: it runs somewhere, and a via on one island can reach any
        # part of the other. A track between a via that already exists and a
        # point on the far island's copper is one segment, no new hole, and it
        # merges them just as well.
        if not plan:
            for src, dst_pt in ((a, b), (b, a)):
                vias = _island_of_kind(board, net, src, pcbnew.PCB_VIA_T)
                far = []
                for t in _island_of_kind(board, net, dst_pt, pcbnew.PCB_TRACE_T):
                    p = (t.GetStart().x / MM, t.GetStart().y / MM)
                    q = (t.GetEnd().x / MM, t.GetEnd().y / MM)
                    n = max(1, int(math.hypot(q[0] - p[0], q[1] - p[1]) / 0.25))
                    for i in range(n + 1):
                        u = i / n
                        far.append((p[0] + (q[0] - p[0]) * u,
                                    p[1] + (q[1] - p[1]) * u))
                for v in vias:
                    vp = (v.GetPosition().x / MM, v.GetPosition().y / MM)
                    cand = sorted(far, key=lambda P: math.hypot(P[0] - vp[0],
                                                                P[1] - vp[1]))
                    for P in cand[:40]:
                        d = math.hypot(P[0] - vp[0], P[1] - vp[1])
                        if d < 0.05 or d > 8.0:
                            continue
                        n = max(2, int(d / 0.05))
                        for L in LAYERS:
                            if any(_clear_hit(vp[0] + (P[0] - vp[0]) * i / n,
                                              vp[1] + (P[1] - vp[1]) * i / n,
                                              TRACK_W / 2 + clear, board, net, L)
                                   for i in range(n + 1)):
                                continue
                            plan.append((vp, L, P, True))
                            break
                        if len(plan) >= 8:
                            break
                    if len(plan) >= 8:
                        break

        if not plan:
            print(f"  {netname}: no via and stub fits within 3 mm "
                  f"(gap {gap:.2f} mm, clearance {clear:.2f})")
            break

        shutil.copy(path, pristine)
        won = False
        for entry in plan:
            (vx, vy), layer, dst = entry[0], entry[1], entry[2]
            reuse = len(entry) > 3 and entry[3]
            trial = pcbnew.LoadBoard(path)
            if not reuse:
                v = pcbnew.PCB_VIA(trial)
                v.SetPosition(pcbnew.VECTOR2I(int(vx * MM), int(vy * MM)))
                v.SetWidth(int(0.25 * MM))
                v.SetDrill(int(0.10 * MM))
                v.SetLayerPair(pcbnew.F_Cu, pcbnew.B_Cu)
                v.SetNetCode(net)
                trial.Add(v)
            if layer is not None:
                t = pcbnew.PCB_TRACK(trial)
                t.SetStart(pcbnew.VECTOR2I(int(vx * MM), int(vy * MM)))
                t.SetEnd(pcbnew.VECTOR2I(int(dst[0] * MM), int(dst[1] * MM)))
                t.SetWidth(int(TRACK_W * MM))
                t.SetLayer(layer)
                t.SetNetCode(net)
                trial.Add(t)
            pcbnew.ZONE_FILLER(trial).Fill(trial.Zones())
            trial.Save(path)
            nb, nv = net_breaks(path, netname)
            if os.environ.get("MAZE_DEBUG"):
                print(f"    [dbg] via ({vx:.3f},{vy:.3f}) "
                      f"{'in place' if layer is None else trial.GetLayerName(layer)}"
                      f" -> {nb} breaks (was {breaks}), {nv} viol (base {base_v})")
            if nb < breaks and nv <= base_v:
                where = "in place" if layer is None else trial.GetLayerName(layer)
                how = ("a track from the via it already had"
                       if reuse else "a via was missing, not a route")
                print(f"  {netname}: {how} — ({vx:.3f}, {vy:.3f}) {where}; "
                      f"{breaks} -> {nb} breaks")
                breaks = nb
                won = True
                break
            shutil.copy(pristine, path)
        os.unlink(pristine)
        if not won:
            print(f"  {netname}: {len(plan)} candidates, DRC refused every one")
            break
    return breaks


def finish_layer_changes(path, project=None):
    """Close every net whose halves only need a layer change."""
    project = project or os.path.splitext(path)[0] + ".kicad_pro"
    v0, u0, pairs = drc(path)
    nets = sorted({p[2] for p in pairs})
    if not nets:
        print("nothing open")
        return 0
    print(f"start: {v0} violations, {u0} unconnected, "
          f"nets open: {', '.join(nets)}")
    for netname in nets:
        link_islands(path, project, netname, v0)
    v, u, _ = drc(path)
    print(f"done: {v} violations, {u} unconnected")
    return u


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
        # ⚠️ AND A FINER GRID IF THE COARSE ONE'S ROUTE IS REFUSED. A tenth of a
        # millimetre per cell is plenty for going around a component and not
        # enough for threading between two vias: the last connection on this
        # board came back 0.02 mm inside the Power class's clearance, which is a
        # fifth of one cell. Halving the pitch quadruples the search and is worth
        # it exactly once, on the connection nothing else could close.
        found = grid = None
        widths = (tw, TRACK_W) if tw > TRACK_W else (tw,)
        for pitch in (PITCH, FINE_PITCH):
            for width in widths:
                grid = Grid(board, net, x0 - MARGIN, y0 - MARGIN,
                            x1 + MARGIN, y1 + MARGIN, track_w=width, clear=cl,
                            pitch=pitch)
                grid.free_around(a)
                grid.free_around(b)
                found = route(grid, grid.cell(a), grid.cell(b))
                if not found:
                    if os.environ.get("MAZE_DEBUG"):
                        print(f"    [dbg] {netname} p={pitch} w={width}: NO PATH")
                    continue
                trial = pcbnew.LoadBoard(path)
                tg = Grid(trial, net, x0 - MARGIN, y0 - MARGIN, x1 + MARGIN,
                          y1 + MARGIN, track_w=width, clear=cl, pitch=pitch)
                apply(trial, tg, found, net, ends=(a, b))
                pcbnew.ZONE_FILLER(trial).Fill(trial.Zones())
                trial.Save(path)
                tv, tu, _ = drc(path)
                shutil.copy(pristine, path)
                if os.environ.get("MAZE_DEBUG"):
                    print(f"    [dbg] {netname} p={pitch} w={width}: {len(found)} "
                          f"cells -> {tv} viol / {tu} unconn (base {base_v}/{base_u})")
                if tu <= base_u and tv <= base_v:
                    if width != tw:
                        print(f"  {netname}: necked down to {width} mm to get out")
                    if pitch != PITCH:
                        print(f"  {netname}: took a {pitch} mm grid to thread it")
                    break
                found = None
            if found:
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
    if len(sys.argv) > 2 and sys.argv[1] == "--link":
        finish_layer_changes(sys.argv[2])
    elif len(sys.argv) > 2 and sys.argv[1] == "--rip":
        print(rip_offenders(sys.argv[2]))
    elif len(sys.argv) > 2 and sys.argv[1] == "--tidy":
        print(drop_dangling(sys.argv[2]))
    else:
        main(sys.argv[1])
