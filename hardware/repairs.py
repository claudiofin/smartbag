#!/usr/bin/env python3
"""The connections a person finished, written down so a machine can redo them.

⛔ TWO NETS ON THIS BOARD DO NOT COME OUT OF THE AUTOROUTER CONNECTED, and after
enough passes it is clear neither is a routing problem. Both are one via and a
fraction of a millimetre of copper — the kind of thing somebody closes in KiCad's
interactive router in about ninety seconds — and both defeat every automatic tool
here for the same reason: the pair KiCad names is the two islands' REPRESENTATIVE
items, not the two ends that need joining, so the maze router is sent to route a
centimetre across the board when the answer is a via where it already is.

⭐ SO THEY ARE WRITTEN HERE RATHER THAN CLICKED IN. A board file is generated on
this project; copper added by hand in pcbnew is copper that disappears the next
time anybody runs the pipeline, and the two hours that found it disappear with
it. This file is the same edit, in a form that survives.

⚠️ AND EVERY REPAIR CHECKS ITS OWN PREMISE FIRST. A repair is a coordinate, and a
coordinate is only meaningful for the routing it was read off. If the board is
re-routed and the geometry moves, the expectation below fails and the repair is
REFUSED and reported — rather than silently dropping a via into whatever is
there now, which would be worse than the missing connection it was fixing.

Usage:  <kicad-python> hardware/repairs.py <board>
"""
import math
import sys

import pcbnew

MM = 1e6
VIA_D = int(0.30 * MM)
VIA_DRILL = int(0.15 * MM)
NEAR = 0.02        # mm; how exactly a premise has to match to be believed


# ── the repairs ──────────────────────────────────────────────────────────────
# Each is: the net, what is wrong, what has to be true for the fix to apply, and
# the copper that closes it.
# ⭐ EMPTY, AND THAT IS THE RESULT RATHER THAN THE STARTING STATE. Two repairs
# lived here — a via for U1 pin 22 and a drop for FSR_R2 — and both are gone
# because the board no longer needs them: on six copper layers the router closes
# every net on its own. Their premises would fail against the current geometry
# and this file would refuse them loudly, which is the designed behaviour and
# also exactly the noise a clean pipeline should not print.
#
# ⚠️ The machinery below is kept. It cost a day to work out what a hand repair
# has to check before it draws anything — that a through via is an obstacle on
# every layer, that a track must end on the destination's own layer, that the
# pair DRC names is not the pair that needs joining — and the next board to come
# back one connection short should not have to learn it again.
REPAIRS = [
    dict(
        net="VDD_3V3",
        why=(
            "U1 pin 10 is a supply pin on a QFN48 whose escape ring uses "
            "every routable layer around it. Freerouting leaves it, and it is "
            "not a routing failure: on four layers the pin had 0.4 mm2 of "
            "reachable space and nothing of its own net in it. On six there is "
            "a path, and this is it — found by a breadth-first search on a "
            "0.1 mm grid and checked by DRC."),
        expect_pad=("U1", "10", (191.05, 149.4)),
        polyline=("In3.Cu", [(190.700, 149.400), (190.500, 149.400), (190.400, 149.400), (190.000, 149.400), (189.900, 149.400), (189.600, 149.400), (189.500, 149.300), (189.400, 149.200), (189.300, 149.100), (189.000, 148.800), (188.900, 148.700), (188.800, 148.600), (188.600, 148.400)]),
    ),
    dict(
        net="VDD_3V3",
        why=(
            "U1 pin 22 is a supply pin on a QFN48 whose escape ring uses "
            "every routable layer around it. Freerouting leaves it, and it is "
            "not a routing failure: on four layers the pin had 0.4 mm2 of "
            "reachable space and nothing of its own net in it. On six there is "
            "a path, and this is it — found by a breadth-first search on a "
            "0.1 mm grid and checked by DRC."),
        expect_pad=("U1", "22", (195.4, 150.95)),
        polyline=("F.Cu", [(195.400, 151.300), (195.400, 151.400), (195.300, 151.500), (195.200, 151.600), (195.100, 151.700), (194.900, 151.700), (194.700, 151.900), (194.600, 152.000), (194.500, 152.100), (194.200, 152.400), (194.100, 152.500), (194.000, 152.600)]),
    ),
]


def _layer(board, name):
    for i in range(pcbnew.PCB_LAYER_ID_COUNT):
        if board.GetLayerName(i) == name:
            return i
    raise KeyError(name)


def _has_track(board, code, layer, a, b):
    for t in board.GetTracks():
        if t.GetNetCode() != code or t.Type() == pcbnew.PCB_VIA_T:
            continue
        if t.GetLayer() != layer:
            continue
        ends = ((pcbnew.ToMM(t.GetStart().x), pcbnew.ToMM(t.GetStart().y)),
                (pcbnew.ToMM(t.GetEnd().x), pcbnew.ToMM(t.GetEnd().y)))
        for p, q in (ends, ends[::-1]):
            if (abs(p[0] - a[0]) < NEAR and abs(p[1] - a[1]) < NEAR
                    and abs(q[0] - b[0]) < NEAR and abs(q[1] - b[1]) < NEAR):
                return True
    return False


def _has_pad(board, ref, num, at):
    for f in board.GetFootprints():
        if f.GetReference() != ref:
            continue
        for p in f.Pads():
            if p.GetNumber() != num:
                continue
            c = p.GetCenter()
            return (abs(pcbnew.ToMM(c.x) - at[0]) < NEAR
                    and abs(pcbnew.ToMM(c.y) - at[1]) < NEAR)
    return False


def _clear_for_via(board, code, x, y, d_mm):
    """Is a via of diameter `d_mm` at (x, y) clear of everything on every layer?

    ⛔ A THROUGH VIA IS AN OBSTACLE ON FOUR LAYERS AND THE FIRST VERSION OF THIS
    FILE CHECKED NONE OF THEM. Both repairs were a coordinate somebody read off
    the board, and both landed on copper: the pin-22 drop crossed I2C_SCL on
    In2, and the FSR_R2 via-in-pad came out 0.0012 mm from ADC4. Reading a
    coordinate off a board tells you where the copper you are looking at is, not
    where the copper you are not looking at is.

    ⚠️ Clearance is taken as the widest netclass on this board, so this is
    pessimistic by design: refusing a legal spot costs a search step, accepting
    an illegal one costs a board.
    """
    r = d_mm / 2 + 0.15
    for t in board.GetTracks():
        if t.GetNetCode() == code:
            continue
        if t.Type() == pcbnew.PCB_VIA_T:
            p = t.GetPosition()
            if math.hypot(pcbnew.ToMM(p.x) - x, pcbnew.ToMM(p.y) - y) < r + 0.15:
                return False
            continue
        a = (pcbnew.ToMM(t.GetStart().x), pcbnew.ToMM(t.GetStart().y))
        b = (pcbnew.ToMM(t.GetEnd().x), pcbnew.ToMM(t.GetEnd().y))
        if _point_to_seg(x, y, a, b) < r + pcbnew.ToMM(t.GetWidth()) / 2:
            return False
    for f in board.GetFootprints():
        for pad in f.Pads():
            if pad.GetNetCode() == code:
                continue
            bb = pad.GetBoundingBox()
            if (pcbnew.ToMM(bb.GetLeft()) - r <= x <= pcbnew.ToMM(bb.GetRight()) + r
                    and pcbnew.ToMM(bb.GetTop()) - r <= y
                    <= pcbnew.ToMM(bb.GetBottom()) + r):
                return False
    return True


def _point_to_seg(px, py, a, b):
    ax, ay = a
    bx, by = b
    dx, dy = bx - ax, by - ay
    if dx == 0 and dy == 0:
        return math.hypot(px - ax, py - ay)
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


def find_drop(board, code, a, b, d_mm, step=0.05):
    """The first point along a->b where a via clears every layer.

    ⭐ THE DROP GOES WHERE THE COPPER ALREADY IS. The router brought this net to
    within a fraction of a millimetre of its pad and stopped on the wrong layer;
    the fix is a via somewhere on the copper it already laid, and which point on
    it does not matter electrically. So instead of naming one and hoping, walk
    the track and take the first place a via actually fits.
    """
    n = max(2, int(math.hypot(b[0] - a[0], b[1] - a[1]) / step) + 1)
    for i in range(n + 1):
        t = i / n
        x = a[0] + (b[0] - a[0]) * t
        y = a[1] + (b[1] - a[1]) * t
        if _clear_for_via(board, code, x, y, d_mm):
            return round(x, 4), round(y, 4)
    return None


def apply(path):
    board = pcbnew.LoadBoard(path)
    done, refused = 0, []
    for r in REPAIRS:
        # ⚠️ str() on every key. GetNetsByName() hands back KiCad's own string
        # type, and `"VDD_3V3" in nets.keys()` is False for a net that is right
        # there — which made both this file and close_gaps.py report politely
        # that they had nothing to do.
        codes = {str(k): v.GetNetCode()
                 for k, v in board.GetNetsByName().items()}
        if r["net"] not in codes:
            refused.append((r["net"], "no such net"))
            continue
        code = codes[r["net"]]

        ok, why_not = True, ""
        for key in ("expect_track", "expect_track2"):
            if key not in r:
                continue
            lname, a, b = r[key]
            if not _has_track(board, code, _layer(board, lname), a, b):
                ok, why_not = False, f"{lname} {a}->{b} is not there any more"
                break
        if ok and "expect_pad" in r:
            ref, num, at = r["expect_pad"]
            if not _has_pad(board, ref, num, at):
                ok, why_not = False, f"{ref}.{num} has moved"
        if not ok:
            refused.append((r["net"], why_not))
            continue

        # ⭐ A POLYLINE REPAIR IS COPPER, NOT A VIA. It is what a person draws
        # when the router gives up: a path found once, checked by DRC, and
        # written down so regenerating the board from its session file does not
        # throw it away. Which is what happened the first time — the two paths
        # that took this board to zero vanished on the next `specctra import`,
        # because a .ses holds what the ROUTER did.
        if "polyline" in r:
            lname, pts = r["polyline"]
            layer = _layer(board, lname)
            laid = 0
            for k in range(len(pts) - 1):
                if _has_track(board, code, layer, pts[k], pts[k + 1]):
                    continue
                t = pcbnew.PCB_TRACK(board)
                t.SetStart(pcbnew.VECTOR2I(int(pts[k][0] * MM),
                                           int(pts[k][1] * MM)))
                t.SetEnd(pcbnew.VECTOR2I(int(pts[k + 1][0] * MM),
                                         int(pts[k + 1][1] * MM)))
                t.SetWidth(int(0.10 * MM))
                t.SetLayer(layer)
                t.SetNetCode(code)
                board.Add(t)
                laid += 1
            done += 1
            print(f"  {r['net']}: {laid} segment(s) on {lname} "
                  f"({len(pts)} vertices)")
            continue

        d_mm, dr_mm = r.get("via_size", (0.30, 0.15))
        if "search" in r:
            a, b = r["search"]
            found = find_drop(board, code, a, b, d_mm)
            if found is None:
                refused.append((r["net"],
                                "no clear via spot anywhere along its own track"))
                continue
            r = dict(r, via=found)
            print(f"    {r['net']}: drop found at ({found[0]:.3f}, {found[1]:.3f})")

        # ⚠️ Idempotent: running this twice must not stack two vias in one hole.
        vx, vy = r["via"]
        if not any(t.Type() == pcbnew.PCB_VIA_T and t.GetNetCode() == code
                   and abs(pcbnew.ToMM(t.GetPosition().x) - vx) < NEAR
                   and abs(pcbnew.ToMM(t.GetPosition().y) - vy) < NEAR
                   for t in board.GetTracks()):
            v = pcbnew.PCB_VIA(board)
            v.SetPosition(pcbnew.VECTOR2I(int(vx * MM), int(vy * MM)))
            v.SetWidth(int(d_mm * MM))
            v.SetDrill(int(dr_mm * MM))
            v.SetLayerPair(pcbnew.F_Cu, pcbnew.B_Cu)
            v.SetNetCode(code)
            board.Add(v)

        if "track" not in r:
            done += 1
            print(f"  {r['net']}: via in pad at ({vx:.3f}, {vy:.3f})")
            continue
        lname, a, b = r["track"]
        layer = _layer(board, lname)
        if not _has_track(board, code, layer, a, b):
            t = pcbnew.PCB_TRACK(board)
            t.SetStart(pcbnew.VECTOR2I(int(a[0] * MM), int(a[1] * MM)))
            t.SetEnd(pcbnew.VECTOR2I(int(b[0] * MM), int(b[1] * MM)))
            t.SetWidth(int(0.10 * MM))
            t.SetLayer(layer)
            t.SetNetCode(code)
            board.Add(t)
        done += 1
        print(f"  {r['net']}: via at ({vx:.3f}, {vy:.3f}) + "
              f"{lname} {a[0]:.3f},{a[1]:.3f} -> {b[0]:.3f},{b[1]:.3f}")

    if done:
        pcbnew.ZONE_FILLER(board).Fill(board.Zones())
        board.Save(path)
    for net, why in refused:
        # ⛔ LOUD, because a refused repair means the board moved under it and
        # the connection is open again. Silence here would be a board that
        # passed this step and failed DRC for a reason nobody had written down.
        print(f"  ⛔ {net}: REFUSED — {why}")
        print(f"     The routing has changed since this repair was read off the "
              f"board.\n     Re-read it, or delete it if the router now closes "
              f"the net itself.")
    return done, len(refused)


if __name__ == "__main__":
    d, r = apply(sys.argv[1])
    print(f"OK  {d} repair(s) applied, {r} refused -> {sys.argv[1]}")
    sys.exit(1 if r else 0)
