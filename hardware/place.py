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
import math
import re

MARGIN = 0.15          # extra millimetres between courtyards
STEP = 0.35

# ⚠️ The board's own process minimums, used to work out how much room a signal
# needs to leave an escape via. Same numbers as the netclass in the .kicad_pro;
# they are here because a placement that does not know them puts a capacitor
# where a track has to go.
TRACK_W = 0.10
CLEAR = 0.15

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


# ⚠️ How far a decoupling capacitor may be nudged looking for room, and the step
# it looks on. 4 mm is far more than any of them should need — the point of the
# reach is that failing to find room is REPORTED rather than silently accepted.
DEC_SEARCH = 4.0
DEC_GRID = 0.1

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


def pad_at(text, number, at, rot):
    """Where pad `number` of a footprint placed at `at` and turned `rot` sits.

    ⭐ DERIVED FROM THE FOOTPRINT, NOT TYPED IN. The alternative is a table of
    pad offsets beside the table of part positions, which is two descriptions of
    one fact and drifts the first time a footprint changes.
    """
    for m in re.finditer(r'\(pad "([^"]+)"[^\n]*\n?\s*\(at ([-\d.]+) ([-\d.]+)',
                         text):
        if m.group(1) != number:
            continue
        px, py = float(m.group(2)), float(m.group(3))
        r = math.radians(rot % 360)
        # ⚠️ KiCad turns footprints anticlockwise and its Y axis points down, so
        # a naive rotation puts every pad on the wrong side of the part.
        rx = px * math.cos(r) + py * math.sin(r)
        ry = -px * math.sin(r) + py * math.cos(r)
        return at[0] + rx, at[1] + ry
    return None


def fanout_ring(refs, pos, libs, footprint_text, rotation, out_mm, via_mm,
                pad_nets, skip_nets=("GND", "", None)):
    """The escape vias generate_pcb.py is about to draw, as courtyard boxes.

    ⛔ THE PLACER USED TO BE BLIND TO THESE AND IT COST TWO ROUTED SIGNALS. A
    fine-pitch QFN escapes through a ring of vias a third of a millimetre
    outside its pads, and everything on that edge travels through the gap
    between the package and the ring. Put a 0402 there — which is exactly what
    "as close to the pin as possible" asks for — and the gap is gone. C7 landed
    on U1's bottom edge and RADAR_IRQ_R and CS_RADAR_R, which had routed for
    months, stopped routing.

    ⭐ So the ring is an obstacle for placement even though it does not exist
    yet, and the capacitor settles just outside it: about 1.6 mm from the pad
    rather than 1.0, still inside the two millimetres the datasheet wants, and
    the channel stays open.
    """
    boxes = []
    # ⛔ THE VIA IS NOT THE OBSTACLE, THE CHANNEL IS. Blocking a 0.25 mm circle
    # at each escape via left room for a 0402 to nestle between two of them and
    # sit on top of the tracks that leave them — which is what happened: the
    # capacitors moved out by 0.2 mm and U1's pins 20, 21 and 22 stayed
    # unroutable. What has to stay clear is the via, plus a track leaving it,
    # plus clearance on both sides of that track.
    r = via_mm / 2 + TRACK_W + 2 * CLEAR + MARGIN
    for ref in refs:
        if ref not in pos:
            continue
        lib, fp = libs.get(ref, (None, None))
        if lib is None:
            continue
        text = footprint_text(lib, fp)
        rot = math.radians(rotation.get(ref, 0))
        cos_t, sin_t = math.cos(rot), math.sin(rot)
        pads = re.findall(r'\(pad "(\d+)"[^\n]*\n\s*\(at ([-\d.]+) ([-\d.]+)',
                          text)
        if not pads:
            continue
        nets = pad_nets(ref)
        xs = [float(a) for _n, a, _b in pads]
        ys = [float(b) for _n, _a, b in pads]
        hw, hh = (max(xs) - min(xs)) / 2, (max(ys) - min(ys)) / 2
        for num, ax, ay in pads:
            if nets.get(num) in skip_nets:
                continue
            ax, ay = float(ax), float(ay)
            if abs(ax) / max(hw, 1e-6) >= abs(ay) / max(hh, 1e-6):
                bx, by = ax + (out_mm if ax > 0 else -out_mm), ay
            else:
                bx, by = ax, ay + (out_mm if ay > 0 else -out_mm)
            vx = pos[ref][0] + bx * cos_t + by * sin_t
            vy = pos[ref][1] - bx * sin_t + by * cos_t
            boxes.append((vx - r, vx + r, vy - r, vy + r))
    return boxes


def place_decoupling(pairs, boxes, pos, home, occupied, footprint_text,
                     libs, rotation):
    """Settle each decoupling capacitor against the pin it decouples.

    ⛔ THE PUSH-APART LOOP CAN ONLY MAKE THIS WORSE, WHICH IS WHY IT RAN FOR THE
    WHOLE LIFE OF THIS BOARD AND NOBODY NOTICED. It separates courtyards; there
    is nothing in it that pulls anything toward anything. Every capacitor
    started at a hand-typed coordinate near its pin and every round of the
    relaxation moved it a little further away, and the result was forty-one
    supply pins whose nearest capacitor on the same rail was between two and
    twenty-six millimetres off. At 26 mm a 100 nF part is an inductor with a
    capacitor in series with it.

    ⭐ SO THEY ARE PLACED, NOT RELAXED — same treatment as the fiducials, and
    the objective is the one that matters: of every position that does not
    overlap anything, take the one nearest the PAD. Not the part centre; a pin
    on the far side of a nine-millimetre package is nine millimetres away.

    ⚠️ AND A CAPACITOR THAT CANNOT GET CLOSE IS REPORTED. There is no useful
    fallback — "somewhere near the right end of the board" is what this file is
    fixing — so it says how far it had to settle for and lets check.py decide
    whether that is a board.
    """
    placed, report = {}, []
    for cap, (ic, pin) in sorted(pairs.items()):
        if cap not in pos or ic not in pos:
            continue
        lib, fp = libs.get(ic, (None, None))
        target = None
        if lib is not None:
            target = pad_at(footprint_text(lib, fp), pin, pos[ic],
                            rotation.get(ic, 0))
        if target is None:
            # ⚠️ No such pad in the footprint. That is a netlist error, not a
            # placement one, and check.py is where it should surface.
            report.append((cap, ic, pin, None))
            continue
        tx, ty = target
        ix0, ix1, iy0, iy1 = ISLANDS[home[cap]]
        x0, x1, y0, y1 = boxes[cap]
        lo_x, hi_x = max(ix0 - x0, tx - DEC_SEARCH), min(ix1 - x1, tx + DEC_SEARCH)
        lo_y, hi_y = max(iy0 - y0, ty - DEC_SEARCH), min(iy1 - y1, ty + DEC_SEARCH)
        best, best_d = None, None
        cx = lo_x
        while cx <= hi_x + 1e-9:
            cy = lo_y
            while cy <= hi_y + 1e-9:
                # ⚠️ MARGIN, not zero. Accepting "just touching" put a
                # capacitor 0.04 mm from a radar's courtyard, which is a
                # placement DRC will refuse and a stencil nobody can print.
                if _clearance(boxes[cap], (cx, cy), occupied) >= MARGIN:
                    # distance from the pad to the NEAREST EDGE of the part, not
                    # to its centre: what matters is where the copper starts.
                    dx = max(cx + x0 - tx, tx - (cx + x1), 0.0)
                    dy = max(cy + y0 - ty, ty - (cy + y1), 0.0)
                    d = dx * dx + dy * dy
                    if best_d is None or d < best_d:
                        best_d, best = d, (cx, cy)
                cy += DEC_GRID
            cx += DEC_GRID
        if best is None:
            report.append((cap, ic, pin, float("inf")))
            continue
        pos[cap] = [round(best[0], 3), round(best[1], 3)]
        placed[cap] = tuple(pos[cap])
        occupied.append((best[0] + x0, best[0] + x1, best[1] + y0, best[1] + y1))
        report.append((cap, ic, pin, best_d ** 0.5))
    worst = [r for r in report if r[3] is None or r[3] > 1.0]
    for cap, ic, pin, d in worst:
        where = "no such pad" if d is None else (
            "no room within %.0f mm" % DEC_SEARCH if d == float("inf")
            else f"{d:.2f} mm away")
        print(f"    ⚠️  {cap} decouples {ic}.{pin}: {where}")
    return placed, report


def relax(parts, footprint_text, rounds=600, rotation=None, decouple=None,
          fanout=None, fanout_out=0.35, fanout_via=0.25, pad_nets=None,
          back=None):
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
    libs = {p[0]: (p[3], p[4]) for p in parts}
    start = {r: tuple(p) for r, p in pos.items()}
    # ⛔ A DECOUPLING CAPACITOR IS EXCLUDED FROM THE PUSH LOOP FOR THE SAME
    # REASON A FIDUCIAL IS: the loop can only move it away from where it has to
    # be. It is placed afterwards, into whatever room the settled board leaves.
    anchored = set(decouple or ())
    on_back = set(back or ())
    refs = [p[0] for p in parts if p[0] not in set(fids) and p[0] not in anchored]
    # ⚠️ An island is chosen ONCE, from the hint, and never revised. Letting the
    # relaxation migrate a part between islands would move a decoupling
    # capacitor 160 mm away from the pin it decouples and call it progress.
    home = {r: island_for(*pos[r]) for r in list(pos)}

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
                # ⛔ PUSH BY THE OVERLAP, NOT BY A FIXED STEP. A third of a
                # millimetre each way is 0.7 mm of separation per round, and a
                # part in a lane only fractionally taller than itself gets
                # thrown past the far wall, bounced back, and thrown again —
                # forever. C80 sat between a resistor and the coil connector in
                # 1.82 mm of room needing 1.76, and six hundred rounds never
                # placed it, because every round moved it four times further
                # than the problem was. Half the overlap each, plus a hair, ends
                # exactly clear and converges in one pass.
                if ox < oy and not pinned:
                    d = ox / 2 + 0.005
                    d = d if pos[a][0] <= pos[b][0] else -d
                    pos[a][0] -= d
                    pos[b][0] += d
                else:
                    d = oy / 2 + 0.005
                    d = d if pos[a][1] <= pos[b][1] else -d
                    pos[a][1] -= d
                    pos[b][1] += d
        for ref in refs:
            x0, x1, y0, y1 = boxes[ref]
            ix0, ix1, iy0, iy1 = ISLANDS[home[ref]]
            pos[ref][0] = min(max(pos[ref][0], ix0 - x0), ix1 - x1)
            pos[ref][1] = min(max(pos[ref][1], iy0 - y0), iy1 - y1)
        if not moved:
            break

    occupied = [(pos[r][0] + boxes[r][0], pos[r][0] + boxes[r][1],
                 pos[r][1] + boxes[r][2], pos[r][1] + boxes[r][3])
                for r in refs]
    # ⭐ Capacitors first, then fiducials. The capacitor has one correct place
    # and the fiducial has a window; giving the constrained part first refusal
    # on the room is the only ordering that can satisfy both.
    if decouple:
        # ⭐ A PART ON THE BACK COLLIDES WITH THE BACK, AND THE BACK IS EMPTY.
        # The escape via ring, the package courtyards, every other capacitor —
        # all of that is on the front and none of it is in this capacitor's way.
        # So the back-side four are placed first, against a list containing only
        # each other, and they land exactly under the pad they serve.
        front = {c: v for c, v in decouple.items() if c not in on_back}
        rear = {c: v for c, v in decouple.items() if c in on_back}
        if rear:
            back_occupied = []
            place_decoupling(rear, boxes, pos, home, back_occupied,
                             footprint_text, libs, rotation)
        occupied += fanout_ring(fanout or (), pos, libs, footprint_text,
                                rotation, fanout_out, fanout_via, pad_nets)
        place_decoupling(front, boxes, pos, home, occupied, footprint_text,
                         libs, rotation)
    if fids:
        place_fiducials(fids, boxes, pos, home, occupied)
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
