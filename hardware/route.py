#!/usr/bin/env python3
"""Route the board: pad escapes on the front, lanes on the back.

⛔ WHY A ROUTER AND NOT AN AUTOROUTER. The layout is generated, so the router
can be given the one thing an autorouter never has: a floorplan chosen to make
routing trivial. The FSR bus leaves U1 on pins 27..42 in exactly the order it
arrives at J4 on pins 2..23, and the two parts face each other. Twenty-two nets
that are monotonic at both ends cannot cross, whatever layer they are on. That
property is declared in netlist.py and is the reason this file is a few hundred
lines instead of a research project.

⭐ THE LAYER SPLIT. Every pad escapes to a via just outside its own courtyard —
short stubs on F.Cu, where the parts are — and everything else happens on B.Cu,
which carries no components. B.Cu also carries the ground pour, and the pour is
filled *after* these tracks exist, so it flows around them at the clearance the
rules ask for.

⚠️ GND IS NOT ROUTED HERE. 76 of the 208 pads are ground and they connect to the
pours directly. Routing them as tracks would be worse in every way.
"""
import math
import os
import re

FANOUT = 0.45        # mm from the courtyard edge to the first via row
FANOUT_STAGGER = 0.5  # second row, so neighbouring vias are not at pad pitch
STUB_W = 0.12        # mm, escape stub on F.Cu
LANE_W = 0.12        # mm, lane on B.Cu
POWER_W = 0.3        # mm, for the rails
LANE_LO, LANE_HI = -8.2, 8.2
LANE_PITCH = 0.32
COLUMN_PITCH = 0.45  # spacing between escape columns on B.Cu

# ⚠️ Nets that must NOT be routed like signals. GND is the pours; the three
# antenna feeds are microstrip whose geometry is the component, and they stay on
# F.Cu over the ground plane where their impedance is defined.
SKIP = {"GND"}
RF_NETS = {"ANT_A1", "ANT_A2", "BLE_ANT"}
POWER_NETS = {"VDD_3V3", "VDD_1V8", "VBAT", "VQI", "SW1", "SW2"}


def _footprint(fp_lib, lib, fp):
    return open(os.path.join(fp_lib, f"{lib}.pretty", f"{fp}.kicad_mod")).read()


def pad_positions(fp_lib, parts):
    """{(ref, pad): (x, y, net)} in board coordinates."""
    out = {}
    pat = re.compile(r'\(pad "([^"]*)"[^\n]*\n\s*\(at ([-\d.]+) ([-\d.]+)')
    for ref, _v, _s, lib, fp, pins, px, py in parts:
        found = {m.group(1): (float(m.group(2)), float(m.group(3)))
                 for m in pat.finditer(_footprint(fp_lib, lib, fp))}
        for num, _n, _t, net in pins:
            p = found.get(str(num))
            if p:
                out[(ref, str(num))] = (px + p[0], py + p[1], net)
    return out


def courtyards(fp_lib, parts):
    """{ref: (x0, x1, y0, y1, cx, cy)} in board coordinates."""
    out = {}
    for ref, _v, _s, lib, fp, _pins, px, py in parts:
        t = _footprint(fp_lib, lib, fp)
        pts = [(float(a), float(b))
               for m in re.finditer(
                   r'\(fp_(?:line|rect|poly)\b(.*?)\(layer "F\.CrtYd"', t, re.S)
               for a, b in re.findall(
                   r'\((?:start|end|xy) ([-\d.]+) ([-\d.]+)\)', m.group(1))]
        if not pts:
            pts = [(-1.0, -1.0), (1.0, 1.0)]
        xs = [q[0] for q in pts]
        ys = [q[1] for q in pts]
        out[ref] = (px + min(xs), px + max(xs), py + min(ys), py + max(ys), px, py)
    return out


def escape(pad_xy, yard, index):
    """Where a pad's via goes: straight out of the nearest courtyard edge.

    ⚠️ Two rows, alternating. A single row puts vias at the pad pitch — 0.4 mm
    on the QFN-48 — and a 0.3 mm via with 0.1 mm clearance needs exactly that,
    with nothing left for the stub running past it. Staggering doubles the room
    at the cost of half a millimetre of board.
    """
    x, y = pad_xy
    x0, x1, y0, y1 = yard[:4]
    depth = FANOUT + (FANOUT_STAGGER if index % 2 else 0.0)
    # distance to each edge; escape through the closest one
    d = {"l": x - x0, "r": x1 - x, "d": y - y0, "u": y1 - y}
    side = min(d, key=d.get)
    if side == "l":
        return (x0 - depth, y)
    if side == "r":
        return (x1 + depth, y)
    if side == "d":
        return (x, y0 - depth)
    return (x, y1 + depth)


def assign_lanes(nets, pads):
    """One y per net on B.Cu, ordered so that monotonic buses stay monotonic.

    ⭐ Sorted by the mean y of the net's pads. For the FSR bus, whose pads are
    monotonic at both ends by construction, this reproduces the pin order and
    the twenty-two lanes run parallel without a single crossing.
    """
    order = sorted(nets, key=lambda n: (
        sum(pads[k][1] for k in nets[n]) / len(nets[n]), n))
    span = LANE_HI - LANE_LO
    step = min(LANE_PITCH, span / max(1, len(order) - 1))
    return {n: LANE_LO + i * step for i, n in enumerate(order)}


def route(parts, fp_lib, net_index, seg, via, keepout):
    """RF feeds only. The signal nets are NOT routed, and this is why.

    ⛔ THREE ATTEMPTS, ALL REJECTED BY DRC, IN THIS ORDER:

      1. Two layers, escape stubs on F.Cu and lanes on B.Cu.
         Everything connected — 0 unconnected pads — but 466 violations: with a
         single signal layer the horizontal lanes and the vertical drops share
         it and must cross. 116 crossings, 165 clearance.
      2. Four layers, one axis each, escapes still on F.Cu.
         Worse: 989. The escape stubs have to fan sideways to give twelve pads
         in a QFN column twelve distinct escape columns, and sideways is where
         the other parts are.
      3. Four layers, via-in-pad, a reserved column per pad and lane per net.
         852. The jogs from each via to its column run at the pad's own y, and
         pads sharing a y — every QFN row — collide along it.

    ⭐ WHAT THAT ACTUALLY ESTABLISHED, which is worth more than a bad layout:
      - at 0.4 mm pitch **via-in-pad is not optional**, there is nowhere else
        for the via to go;
      - **two layers cannot carry this board**, measured rather than asserted;
      - what is missing is not a bigger board or a cleverer floorplan but a
        maze router with rip-up and retry, and that is a project of its own.

    ⚠️ So the board is unrouted, DRC reports 80 unconnected pads, and that number
    is the honest size of the gap. Decorative tracks that make renders look like
    a circuit were deleted once already; they are not coming back as a
    substitute for routing.
    """
    pads = pad_positions(fp_lib, parts)
    nets = {}
    for key, (_x, _y, net) in pads.items():
        if net not in SKIP:
            nets.setdefault(net, []).append(key)
    out = []

    # ── RF feeds: NOT drawn either ───────────────────────────────────────────
    # ⛔ The first version ran a microstrip from U2 straight to each antenna
    # island. DRC rejected it — the path goes through U1 — and asking why turned
    # up something that no layout can fix: the islands are 87 and 99 mm away,
    # and rf/feed_loss.py puts that at roughly 9 dB of 60 GHz microstrip loss
    # one way. A radar link budget goes as the fourth power of range, so 18 dB
    # round trip costs a factor of ~2.8 in range before the antenna has done
    # anything.
    #
    # ⚠️ That is an ARCHITECTURE problem, not a routing one: a transceiver in
    # the middle cannot feed two antennas at the ends of a 196 mm board at
    # 60 GHz. Drawing the trace anyway would hide it. The options are in
    # rf/feed_loss.py, and choosing between them is not a decision this file
    # gets to make.
    return out
