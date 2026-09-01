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
import sys

import pcbnew

MM = 1e6
VIA_D = int(0.30 * MM)
VIA_DRILL = int(0.15 * MM)
NEAR = 0.02        # mm; how exactly a premise has to match to be believed


# ── the repairs ──────────────────────────────────────────────────────────────
# Each is: the net, what is wrong, what has to be true for the fix to apply, and
# the copper that closes it.
REPAIRS = [
    dict(
        net="VDD_3V3",
        why=(
            "U1 pin 22 is a supply pin in the middle of the QFN's bottom edge. "
            "Its escape stub is drawn outward, away from the package, and the "
            "VDD_3V3 distribution on In2.Cu runs UNDER the package a "
            "millimetre the other way — so the stub points at nothing and the "
            "pin is left on its own. A via at the end of the stub and a "
            "millimetre of In2.Cu back to the run is the whole fix."),
        # the fanout stub has to be where it was read
        expect_track=("F.Cu", (195.400, 150.950), (195.400, 151.300)),
        expect_track2=("In2.Cu", (191.825, 150.319), (195.949, 150.319)),
        via=(195.400, 151.300),
        # ⚠️ 0.25 mm, which is the size the rest of this escape row uses. A
        # 0.30 mm via here sits 0.125 mm from its neighbours on a 0.4 mm pitch
        # and the Power netclass wants 0.15 — the first attempt at this repair
        # produced four clearance errors and closed the net, which is a worse
        # board than the one it started from.
        via_size=(0.25, 0.10),
        track=("In2.Cu", (195.400, 151.300), (195.400, 150.319)),
    ),
    dict(
        net="FSR_R2",
        why=(
            "The router brought this one across the board on B.Cu and finished "
            "it exactly on R42's pad — which is on F.Cu. The copper is in the "
            "right place, there is no via, and the ratsnest line is zero "
            "millimetres long. It is the most convincing way for a board to be "
            "wrong."),
        expect_track=("B.Cu", (242.840, 146.850), (242.590, 146.600)),
        expect_pad=("R42", "1", (242.590, 146.600)),
        # ⛔ THE VIA GOES IN THE PAD AND NOT BESIDE IT. Beside it was the first
        # attempt: a via 0.35 mm away and a short track back to the pad, which
        # is what a person draws — and on F.Cu that track crosses ADC2 and
        # shorts two nets. There is nowhere on the surface for it to go. The
        # B.Cu track already ends exactly on the pad, so the drop belongs where
        # the copper already is.
        via=(242.590, 146.600),
        via_size=(0.25, 0.10),
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

        # ⚠️ Idempotent: running this twice must not stack two vias in one hole.
        vx, vy = r["via"]
        if not any(t.Type() == pcbnew.PCB_VIA_T and t.GetNetCode() == code
                   and abs(pcbnew.ToMM(t.GetPosition().x) - vx) < NEAR
                   and abs(pcbnew.ToMM(t.GetPosition().y) - vy) < NEAR
                   for t in board.GetTracks()):
            d_mm, dr_mm = r.get("via_size", (0.30, 0.15))
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
