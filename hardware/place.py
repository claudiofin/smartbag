#!/usr/bin/env python3
"""Push overlapping parts apart, starting from the positions netlist.py suggests.

⛔ WHY THIS EXISTS. The netlist carries a position for every part because the
floorplan is a design decision — the two radars belong at the ends, the power
stage belongs beside the PMIC, the FSR front end belongs beside its connector.
What it cannot carry is exact clearance, because a courtyard is a property of a
footprint and 91 hand-typed coordinates will always collide somewhere. The first
attempt collided in 28 places.

⭐ SO THE COORDINATES ARE A HINT AND THIS IS THE ARBITER. A few hundred passes of
"if two courtyards overlap, push both along the shortest axis" settles a board
this size in well under a second, and every part stays within a millimetre or so
of where the designer put it. It is not a placer — it does not know about nets
or routing — it only guarantees the one thing DRC will otherwise refuse.

⚠️ It moves parts, so it can move one somewhere routing-hostile. That is why the
displacement is reported: if the relaxation has had to shove something a long
way, the floorplan is wrong and should be fixed rather than nudged.
"""
import re

MARGIN = 0.15          # extra millimetres between courtyards
STEP = 0.35

# ⛔ COMPONENTS GO ON THE RIGID ISLANDS AND NOWHERE ELSE. The board is a 196 mm
# strip with two 30 mm flex tails in it, and the first version of this file
# clamped everything to one big rectangle — which put a 24-way connector and a
# row of resistors out over a tail, and over the board edge, because the tail is
# 8 mm tall and the rectangle assumed 20. A part soldered to a flex section that
# bends does not stay soldered. The islands are the only legal ground, and the
# 1.0 mm inset is the copper-to-edge rule with room for a courtyard.
ISLANDS = [
    (-97.0, -85.0, -9.0, 9.0),      # left rigid island: the first radar
    (-61.0,  61.0, -9.0, 9.0),      # centre: processor, power, radio, FSR
    ( 85.0,  97.0, -9.0, 9.0),      # right rigid island: the second radar
]


def island_for(x, y):
    """The island a part belongs to: the one it is in, or the nearest."""
    for i, (x0, x1, y0, y1) in enumerate(ISLANDS):
        if x0 <= x <= x1 and y0 <= y <= y1:
            return i
    return min(range(len(ISLANDS)),
               key=lambda i: abs(x - (ISLANDS[i][0] + ISLANDS[i][1]) / 2))


def courtyard_box(text):
    """(x0, x1, y0, y1) of a footprint's front courtyard, in its own frame."""
    pts = [(float(a), float(b))
           for m in re.finditer(
               r'\(fp_(?:line|rect|poly)\b(.*?)\(layer "F\.CrtYd"', text, re.S)
           for a, b in re.findall(
               r'\((?:start|end|xy) ([-\d.]+) ([-\d.]+)\)', m.group(1))]
    if not pts:
        return -1.0, 1.0, -1.0, 1.0
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    return min(xs), max(xs), min(ys), max(ys)


def _at_y_limit(ref, boxes, pos, home, slack=0.4):
    _x0, _x1, y0, y1 = boxes[ref]
    _ix0, _ix1, iy0, iy1 = ISLANDS[home[ref]]
    return (pos[ref][1] - y0 <= iy0 + slack) or (pos[ref][1] + y1 >= iy1 - slack)


def _box_for(ref, lib, fp, footprint_text, rotation):
    """⚠️ A part turned 90 degrees has its courtyard turned with it. Checking the
    unrotated box would pass a placement DRC then rejects."""
    x0, x1, y0, y1 = courtyard_box(footprint_text(lib, fp))
    if rotation.get(ref, 0) % 180 == 90:
        return y0, y1, x0, x1
    return x0, x1, y0, y1


FIDUCIAL_SYMBOL = "FIDUCIAL"
# ⚠️ A fiducial's courtyard in the KiCad library is barely wider than its 1 mm
# pad, which is true of the part and useless as a placement rule: what has to
# stay clear is the 2 mm soldermask window the camera looks through. Same number
# as generate_pcb.fiducial_keepout, and for the same reason.
FID_COURTYARD = 2.0
FID_GRID = 0.25        # mm, the search step for a clear spot
FID_SEARCH = 6.0       # mm, how far a fiducial may be nudged from its intent
FID_WANT = 0.6         # mm, clearance past which more room stops being better


def _clearance(box, at, others):
    """Smallest gap between a courtyard placed at `at` and any of `others`.

    Negative when they overlap, which is how the search rejects a candidate
    without a separate collision test.
    """
    x0, x1, y0, y1 = box
    ax0, ax1, ay0, ay1 = at[0] + x0, at[0] + x1, at[1] + y0, at[1] + y1
    worst = float("inf")
    for bx0, bx1, by0, by1 in others:
        gap = max(bx0 - ax1, ax0 - bx1, by0 - ay1, ay0 - by1)
        worst = min(worst, gap)
    return worst


def place_fiducials(fids, boxes, pos, home, occupied):
    """Settle each fiducial near where the netlist asked for it, but in the clear.

    ⛔ A FIDUCIAL IS NOT AN ORDINARY PART AND MUST NOT BE RELAXED LIKE ONE. It
    has no net and no neighbour it wants to be near, so the push-apart loop —
    which only knows how to move things a third of a millimetre at a time —
    spends its rounds shoving a fiducial between two capacitors that have
    nowhere to go, and stalls with it still on top of one. That is exactly what
    happened: FID4 ended up inside C23's courtyard and FID5 inside C33's.

    ⛔ AND IT MUST NOT SIMPLY BE PUT WHERE THERE IS THE MOST ROOM. That was the
    first repair, and it was worse: told to maximise clearance, the search
    emptied all five fiducials onto the two end islands and left three of them
    in a row 3 mm apart. Three collinear marks tell a placement camera about one
    axis. Where a fiducial goes is a DECISION — diagonally opposite corners, one
    pair per rigid island, because the flex tails let the islands move relative
    to each other and a machine that locates one island has learned nothing
    about the next.

    ⭐ So the netlist states the intent and this only nudges: search a window
    around the requested point, and among positions with enough room prefer the
    one closest to what was asked for. Clearance past FID_WANT buys nothing —
    a fiducial with 4 mm of space is not better placed than one with 1 mm, it is
    just somewhere else.
    """
    placed, exiled = {}, []

    def search(ref, hx, hy, reach):
        ix0, ix1, iy0, iy1 = ISLANDS[home[ref]]
        x0, x1, y0, y1 = boxes[ref]
        lo_x, hi_x = max(ix0 - x0, hx - reach), min(ix1 - x1, hx + reach)
        lo_y, hi_y = max(iy0 - y0, hy - reach), min(iy1 - y1, hy + reach)
        best, best_key = None, None
        cx = lo_x
        while cx <= hi_x + 1e-9:
            cy = lo_y
            while cy <= hi_y + 1e-9:
                gap = min(_clearance(boxes[ref], (cx, cy), occupied), FID_WANT)
                key = (gap, -((cx - hx) ** 2 + (cy - hy) ** 2))
                if best_key is None or key > best_key:
                    best_key, best = key, (cx, cy)
                cy += FID_GRID
            cx += FID_GRID
        return best, best_key[0]

    for ref in fids:
        hx, hy = pos[ref]
        best, gap = search(ref, hx, hy, FID_SEARCH)
        # ⛔ NEVER SETTLE FOR AN OVERLAP. The window says where the fiducial
        # BELONGS; it does not promise the room exists. FID4 was asked for the
        # top-right corner of the centre island, which is where the multiplexer
        # is, and within six millimetres of there every candidate still sat
        # inside U7's courtyard. A placement that merely "did its best" would
        # hand that to DRC as a courtyard violation, which is how the previous
        # two got through. Widening to the whole island is a worse position and
        # a correct board, and the compromise is reported rather than hidden.
        if gap < 0:
            best, gap = search(ref, hx, hy, float("inf"))
            exiled.append((ref, ((best[0] - hx) ** 2 + (best[1] - hy) ** 2) ** 0.5))
        x0, x1, y0, y1 = boxes[ref]
        pos[ref] = [round(best[0], 3), round(best[1], 3)]
        placed[ref] = tuple(pos[ref])
        occupied.append((best[0] + x0, best[0] + x1, best[1] + y0, best[1] + y1))
    for ref, dist in exiled:
        print(f"    ⚠️  {ref} had no room where it was asked for; moved "
              f"{dist:.1f} mm across its island")
    return placed


def relax(parts, footprint_text, rounds=600, rotation=None):
    """parts: [(ref, ..., fp_lib, fp, pins, x, y)] -> {ref: (x, y)}.

    Returns the settled positions and the largest distance any part travelled.
    """
    rotation = rotation or {}
    boxes = {}
    pos = {}
    fids = []
    for ref, _v, sym, lib, fp, _pins, x, y in parts:
        boxes[ref] = _box_for(ref, lib, fp, footprint_text, rotation)
        pos[ref] = [float(x), float(y)]
        if sym == FIDUCIAL_SYMBOL:
            h = FID_COURTYARD / 2
            boxes[ref] = (-h, h, -h, h)
            fids.append(ref)
    start = {r: tuple(p) for r, p in pos.items()}
    refs = [p[0] for p in parts if p[0] not in set(fids)]
    # ⚠️ An island is chosen ONCE, from the hint, and never revised. Letting the
    # relaxation migrate a part between islands would move a decoupling
    # capacitor 160 mm away from the pin it decouples and call it progress.
    home = {r: island_for(*pos[r]) for r in refs + fids}

    def extent(ref):
        x0, x1, y0, y1 = boxes[ref]
        px, py = pos[ref]
        return px + x0 - MARGIN / 2, px + x1 + MARGIN / 2, \
            py + y0 - MARGIN / 2, py + y1 + MARGIN / 2

    for _ in range(rounds):
        moved = False
        for i in range(len(refs)):
            for j in range(i + 1, len(refs)):
                a, b = refs[i], refs[j]
                ax0, ax1, ay0, ay1 = extent(a)
                bx0, bx1, by0, by1 = extent(b)
                ox = min(ax1, bx1) - max(ax0, bx0)
                oy = min(ay1, by1) - max(ay0, by0)
                if ox <= 0 or oy <= 0:
                    continue
                moved = True
                # ⭐ Push along the shorter overlap: separating two parts that
                # are barely touching sideways by moving them vertically would
                # walk the whole board apart.
                #
                # ⚠️ Unless there is no vertical room left. The board is 94 mm
                # of usable width and 18 mm of height, so parts pile up against
                # the top and bottom edges and then push each other into a
                # boundary they cannot cross — the relaxation stalls with the
                # pair still overlapping. When both are pinned against the same
                # edge, the only direction that can help is sideways.
                pinned = (_at_y_limit(a, boxes, pos, home)
                          and _at_y_limit(b, boxes, pos, home))
                if ox < oy and not pinned:
                    d = STEP if pos[a][0] <= pos[b][0] else -STEP
                    pos[a][0] -= d
                    pos[b][0] += d
                else:
                    d = STEP if pos[a][1] <= pos[b][1] else -STEP
                    pos[a][1] -= d
                    pos[b][1] += d
        for ref in refs:
            x0, x1, y0, y1 = boxes[ref]
            ix0, ix1, iy0, iy1 = ISLANDS[home[ref]]
            pos[ref][0] = min(max(pos[ref][0], ix0 - x0), ix1 - x1)
            pos[ref][1] = min(max(pos[ref][1], iy0 - y0), iy1 - y1)
        if not moved:
            break

    if fids:
        place_fiducials(fids, boxes, pos, home,
                        [(pos[r][0] + boxes[r][0], pos[r][0] + boxes[r][1],
                          pos[r][1] + boxes[r][2], pos[r][1] + boxes[r][3])
                         for r in refs])
    # ⚠️ Fiducials are excluded from the displacement report on purpose: they are
    # placed, not nudged, so "how far did it move" says nothing about whether
    # the floorplan is sound — which is the only question that number answers.
    worst = max((abs(pos[r][0] - start[r][0]) ** 2
                 + abs(pos[r][1] - start[r][1]) ** 2) ** 0.5 for r in refs)
    return {r: (round(p[0], 3), round(p[1], 3)) for r, p in pos.items()}, worst


def overlaps(parts, footprint_text, placed, rotation=None):
    """Any courtyard pairs still intersecting, for the checker to assert on."""
    rotation = rotation or {}
    out = []
    boxes = {ref: _box_for(ref, lib, fp, footprint_text, rotation)
             for ref, _v, _s, lib, fp, _p, _x, _y in parts}
    refs = list(placed)
    for i in range(len(refs)):
        for j in range(i + 1, len(refs)):
            a, b = refs[i], refs[j]
            ax0, ax1, ay0, ay1 = boxes[a]
            bx0, bx1, by0, by1 = boxes[b]
            ax, ay = placed[a]
            bx, by = placed[b]
            if (ax + ax0 < bx + bx1 and bx + bx0 < ax + ax1
                    and ay + ay0 < by + by1 and by + by0 < ay + ay1):
                out.append((a, b))
    return out
