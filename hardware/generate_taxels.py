#!/usr/bin/env python3
"""The taxel sheet: 96 force-sensing sites on a flex the size of the insert floor.

⛔ THE THIRD BOARD, AND THE ONE WITH NO COMPONENTS ON IT. J4 on the insert board
has been a 24-way connector to nothing since the first commit. Everything the
firmware's sb_fsr.c drives — sixteen columns, six rows, ninety-six taxels — lives
here, and "here" did not exist.

⭐ HOW A CHEAP FSR MATRIX IS ACTUALLY BUILT, which is not what a schematic would
lead you to draw. There is no component per taxel. Each site is a pair of
INTERDIGITATED COMBS on one copper layer, facing a plain sheet of
pressure-sensitive film held a fraction of a millimetre away. Press, and the film
touches down and bridges the two combs; the resistance falls with the contact
area. One comb belongs to a column, the other to a row.

⚠️ SO THE FILM IS NOT ON THIS BOARD. What ships from the fabricator is copper and
polyimide; the sensing layer is a separate sheet — Velostat or an equivalent
piezoresistive film — laminated over it with a spacer. That is an assembly step
and a bill-of-materials line, and it is written on the board in Cmts.User rather
than assumed.

⭐ AND THE GEOMETRY IS WHY THE FRONT END EXISTS. firmware/test_sb_fsr.c solved
this exact matrix as a circuit and found that with no diode per taxel the array
ghosts. There is no room for 96 diodes here — that is the whole point of a
printed sheet — so the fix went to the other end of the cable, into the
transimpedance amplifiers on the insert board.

Usage:  python3 hardware/generate_taxels.py
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(HERE))

import dimensions as dim          # noqa: E402
import generate_pcb as base       # noqa: E402
import generate_board as gb       # noqa: E402

W, D = dim.INS_W, dim.INS_D                 # 225 x 78 mm, the insert floor
COLS, ROWS = dim.FSR_COLS, dim.FSR_ROWS
PITCH_X, PITCH_Y = W / COLS, D / ROWS

FINGERS = 3            # per comb
FINGER_W = 0.9
GAP = 0.5              # comb to comb, and finger to finger
BUS_W = 0.8            # column and row bus width
TAXEL_W = PITCH_X - 3.0
TAXEL_H = PITCH_Y - 3.0

# ⭐ THE TAB IS 20 mm TALL AND THAT IS NOT SPARE ROOM. Sixteen column lines and
# six row lines have to fan out from a connector 12 mm wide to electrodes spread
# over 225 mm, and each needs its own horizontal lane: 22 lanes at 0.55 mm is
# 12 mm of tab before anything else. The first version gave them 4 mm and the
# lanes had to overlap.
CONN_Y = D / 2 + 14.0
BUS_TOP = D / 2 + 1.0
# ⚠️ Eight lanes for sixteen columns, between the connector and the sheet.
LANE_Y0 = D / 2 + 9.0
LANE_W = 0.3
# ⚠️ 0.85, and the number is forced by the widest thing that crosses a lane:
# a lane-to-bus drop is BUS_W (0.8) wide, so centre to centre has to beat
# 0.4 + 0.15 + 0.1 = 0.65. At 0.55 the drop and the lane above it touched with
# exactly zero clearance — fourteen shorts, all of them the same tenth of a
# millimetre.
LANE_PITCH = 0.85
FAN_Y0 = D / 2 + 1.5


def wire(a, b, width, layer, net):
    """Copper between two points, on a net.

    ⛔ generate_pcb.copper_rect() CANNOT BE USED HERE, and finding out why cost
    116 DRC shorts. It emits a `gr_poly`: a graphic polygon, netless by
    definition, because it exists to draw 60 GHz antenna patches where the
    geometry IS the component and a net would be meaningless. Netless copper
    over a matrix of electrodes shorts every one of them to every other.

    ⚠️ And it takes ENDPOINTS, not a centre and a size. The version that took
    (centre, width, height) had to inset by half the track width to get the ends
    right, got it wrong by exactly one finger width, and left every electrode
    just barely not touching its own spine — 499 unconnected pads on a board
    with 24 pins. Endpoints cannot be off by half of anything.
    """
    return base.track([a, b], round(width, 4), layer, net)


def taxel_x(c):
    return -W / 2 + PITCH_X * (c + 0.5)


def taxel_y(r):
    return -D / 2 + PITCH_Y * (r + 0.5)


def spine_x(cx, flip):
    return cx + (-1 if flip else 1) * (TAXEL_W / 2 - FINGER_W / 2)


def comb(cx, cy, layer, net, flip):
    """One half of an interdigitated pair: a spine with FINGERS teeth.

    ⭐ The teeth stop a gap short of the OPPOSITE spine — that gap is the sensor.
    A film pressed onto it bridges the two combs, and the resistance falls with
    how much of the interleaved perimeter it touches. Teeth that reach the far
    spine are a short; teeth that barely leave their own are a sensor with almost
    no perimeter and so almost no sensitivity.

    ⚠️ `flip` mirrors the comb AND offsets its teeth by half a pitch, so the two
    halves interlock rather than facing each other across one long gap.
    """
    sign = -1 if flip else 1
    sx = spine_x(cx, flip)
    ox = spine_x(cx, not flip)
    tip = ox + sign * (FINGER_W + GAP)
    out = wire((sx, cy - TAXEL_H / 2), (sx, cy + TAXEL_H / 2),
               FINGER_W, layer, net)
    slots = FINGERS * 2
    step = TAXEL_H / slots
    for i in range(FINGERS):
        fy = cy - TAXEL_H / 2 + step * (2 * i + (1 if flip else 0)) + step / 2
        out += wire((sx, fy), (tip, fy), FINGER_W, layer, net)
    return out


def row_margin_x(rr):
    """Where row `rr` climbs out of the sensing area, on B.Cu.

    ⛔ THE ORDER IS INVERTED ON PURPOSE. Six vertical lines have to leave six
    horizontal busses and reach the tab, all on the same layer, without crossing
    the busses they are not part of. Give the row NEAREST the tab the INNERMOST
    lane and the farthest row the outermost: then every vertical passes to the
    left of the left end of every bus above it, and nothing crosses. Ordering
    them the obvious way — row 0 innermost — crosses five busses.
    """
    # ⚠️ 1.2 mm apart, not 0.5. The lanes are 0.3 mm wide but the BUSSES they
    # have to clear are 0.8, so centre-to-centre has to beat 0.4 + 0.15 plus a
    # clearance — at 0.5 they overlapped by five hundredths of a millimetre and
    # DRC found every one of them.
    return -W / 2 - 1.5 - 1.2 * (ROWS - 1 - rr)


def fanout(net_index, conn_pads, gnd_x):
    """Connector to electrodes.

    ⭐ STRAIGHT SEGMENTS, NOT DOG-LEGS. The connector's pins are in the same
    left-to-right order as the busses they feed, and two monotonic sequences on
    two parallel lines can always be joined pairwise by straight lines that
    never cross. The first version routed each line orthogonally into its own
    horizontal lane and produced twenty-nine crossings, because the vertical
    drop from a pad cuts through the lanes of every trace inside it.

    ⚠️ Columns go on F.Cu and rows on B.Cu, so the two fans can overlap in the
    tab without touching.
    """
    r = []
    for c in range(COLS):
        net = net_index[f"FSR_C{c}"]
        px, py = conn_pads[f"FSR_C{c}"]
        bus_x = taxel_x(c) - TAXEL_W / 2 - 1.2
        # ⛔ LANES, NOT A FAN, AND THE ORDER IS FORCED. A straight line from the
        # connector to a bus is nearly horizontal — 107 mm across for 13 mm
        # down — and two of them starting 0.5 mm apart are only
        # 0.5 x sin(angle) = 0.05 mm apart PERPENDICULAR. Sixteen of those is
        # sixteen shorts, and no amount of tab height fixes it: getting 0.4 mm
        # of perpendicular clearance out of a 0.5 mm pitch would need 140 mm of
        # vertical run.
        #
        # ⭐ So each line gets its own horizontal lane, and the lane ORDER is not
        # free. Working it out rather than guessing: the drop from a pad crosses
        # every lane shallower than its own that spans that pad's x, and the
        # drop from a lane to a bus crosses every lane deeper than its own that
        # spans that bus's x. Both conditions are satisfied at once only if the
        # line travelling FURTHEST gets the DEEPEST lane. Columns 0..7 go left
        # and 8..15 go right, so k = min(c, 15 - c) — and the two halves can
        # share the same eight lanes, because their horizontals never overlap
        # in x.
        k = min(c, COLS - 1 - c)
        ly = LANE_Y0 - k * LANE_PITCH
        r.extend(base.track([(px, py), (px, ly)], LANE_W, "F.Cu", net))
        r.extend(base.track([(px, ly), (bus_x, ly)], LANE_W, "F.Cu", net))
        r.extend(base.track([(bus_x, ly), (bus_x, D / 2 - 1.0)],
                            BUS_W, "F.Cu", net))
    for rr in range(ROWS):
        net = net_index[f"FSR_R{rr}"]
        px, py = conn_pads[f"FSR_R{rr}"]
        mx = row_margin_x(rr)
        by = taxel_y(rr) + TAXEL_H / 2 + 1.4
        # ⛔ AN L, NOT A DIAGONAL. A straight line from the connector to a row
        # bus is 141 mm of B.Cu drawn across the entire sensing area, and it
        # crosses every other row bus on the way — the straight-line argument
        # that works for the columns does not transfer, because the columns end
        # on a line and the rows end at six different heights.
        #
        # ⚠️ The lane order matters as much as the margin order: the row that
        # reaches furthest left takes the tab lane CLOSEST to the sheet, so its
        # long horizontal runs below everything else's drop.
        # ⚠️ REVERSED. The row that reaches furthest left must use the lane
        # FURTHEST from the sheet, not the closest: a horizontal at lane y
        # crosses every vertical whose lane is deeper than it, and ordering
        # these the natural way produced exactly that, once per adjacent pair.
        # ⛔ THE ROWS ESCAPE UPWARDS, over the connector, not down into the tab.
        # Below the connector every millimetre of F.Cu is a column lane and the
        # right-hand columns run right past the row pads on their way out; a row
        # leg dropping through that crosses six of them. Above the connector
        # there is nothing at all.
        ly = CONN_Y + 2.0 + 0.85 * (ROWS - 1 - rr)
        # ⛔ THE VIA GOES AT THE LANE, NOT AT THE PAD. Six vias on 0.5 mm pad
        # pitch are 0.45 mm across: 0.05 mm apart, which is half the clearance
        # rule. Dropping to the lane on F.Cu first spreads them over 0.85 mm of
        # y as well, and the row pads sit to the right of where any column lane
        # reaches, so the F.Cu leg crosses nothing.
        r.extend(base.track([(px, py), (px, ly)], LANE_W, "F.Cu", net))
        r.append(base.via(px, ly, net, size=0.45, drill=0.25))
        r.extend(base.track([(px, ly), (mx, ly)], LANE_W, "B.Cu", net))
        r.extend(base.track([(mx, ly), (mx, by)], LANE_W, "B.Cu", net))

    # ⚠️ The two ground pins tie to each other along the top of the tab. There
    # is no plane on this sheet — a pour would short the matrix — so GND's only
    # job here is to be the shield reference the insert board's J4 expects, and
    # a pin that connects to nothing is a pin nobody checked.
    g = net_index["GND"]
    gy = CONN_Y + 2.0 + 0.85 * ROWS + 1.5
    gl, gr = min(x for x, _ in gnd_x), max(x for x, _ in gnd_x)
    # ⚠️ The climb is on F.Cu and only the link across is on B.Cu. Taking both
    # up the bottom layer put pin 1's riser straight through all six row lanes,
    # which fan out leftward and cover the x it sits at. Above the connector
    # F.Cu is empty.
    for gx, gpy in gnd_x:
        # ⚠️ LANE_W, not BUS_W. A 0.8 mm riser leaving a pad on a 0.5 mm
        # pitch overlaps its neighbours before it has gone anywhere.
        r.extend(base.track([(gx, gpy), (gx, gy)], LANE_W, "F.Cu", g))
        r.append(base.via(gx, gy, g, size=0.45, drill=0.25))
    r.extend(base.track([(gl, gy), (gr, gy)], BUS_W, "B.Cu", g))
    return r


def build(net_index):
    r = []
    # ── columns: a bus down the sheet on F.Cu, one comb per taxel ────────────
    for c in range(COLS):
        net = net_index[f"FSR_C{c}"]
        bx = taxel_x(c) - TAXEL_W / 2 - 1.2
        r += wire((bx, -D / 2 + 1.0), (bx, D / 2 - 1.0), BUS_W, "F.Cu", net)
        for rr in range(ROWS):
            r += comb(taxel_x(c), taxel_y(rr), "F.Cu", net, flip=True)
            r += wire((bx, taxel_y(rr)),
                      (spine_x(taxel_x(c), True), taxel_y(rr)),
                      FINGER_W, "F.Cu", net)
    # ── rows: mating combs on F.Cu, bussed across on B.Cu, one via each ──────
    # ⚠️ The row bus HAS to be on the other layer: on F.Cu it would cross all
    # sixteen column busses. One via per taxel is what that costs, and it is why
    # this sheet is two-layer rather than one.
    for rr in range(ROWS):
        net = net_index[f"FSR_R{rr}"]
        by = taxel_y(rr) + TAXEL_H / 2 + 1.4
        r += wire((row_margin_x(rr), by), (W / 2 - 1.0, by), BUS_W, "B.Cu", net)
        for c in range(COLS):
            r += comb(taxel_x(c), taxel_y(rr), "F.Cu", net, flip=False)
            vx = spine_x(taxel_x(c), False)
            r += wire((vx, taxel_y(rr)), (vx, by), FINGER_W, "F.Cu", net)
            r.append(base.via(vx, by, net, size=0.45, drill=0.25))
    return r


def main():
    import taxel_netlist as nl
    net_index = {"": 0, "GND": 1}
    for n in sorted(nl.nets()):
        net_index.setdefault(n, len(net_index))

    # ⭐ Pad positions read out of the footprint, not assumed. The fan-out has
    # to start exactly where the connector's copper is; guessing the pitch would
    # put twenty-two lanes half a millimetre off in the same direction.
    import re as _re
    fp_text = open(base.footprint_path(
        "Connector_FFC-FPC",
        "Hirose_FH12-24S-0.5SH_1x24-1MP_P0.50mm_Horizontal")).read()
    found = {m.group(1): (float(m.group(2)), float(m.group(3)))
             for m in _re.finditer(
                 r'\(pad "([^"]*)"[^\n]*\n\s*\(at ([-\d.]+) ([-\d.]+)',
                 fp_text)}
    _jx, _jy = nl.part("J20")[6], nl.part("J20")[7]
    conn_pads = {}
    gnd_x = []
    for num, _n, _t, net in nl.part("J20")[5]:
        if str(num) in found:
            dx, dy = found[str(num)]
            if net == "GND":
                gnd_x.append((_jx + dx, _jy + dy))
            else:
                conn_pads[net] = (_jx + dx, _jy + dy)

    body = gb.build(nl, "smartbag_taxels", pour=False, notes=[
        "printed force-sensing sheet: 16 columns x 6 rows = 96 taxels",
        "flexible polyimide, 0.1 mm, 2 layers, ENIG (bare copper oxidises)",
        "NO SOLDER MASK over the taxel area: the film has to touch the combs",
        "ASSEMBLY: laminate a piezoresistive film (Velostat or equivalent)",
        "  over the sensing area with a 0.1 mm spacer. Not supplied on this PCB.",
        "the matrix has no per-taxel diode; the transimpedance front end on the",
        "  insert board is what makes it readable - see firmware/sb_fsr.c",
    ])
    electrodes = "\n".join(build(net_index) + fanout(net_index, conn_pads, gnd_x))
    out = body.rstrip()[:-1].rstrip() + "\n" + electrodes + "\n)\n"
    path = os.path.join(HERE, "smartbag_taxels.kicad_pcb")
    with open(path, "w") as f:
        f.write(out)
    print(f"OK  {path}  ({COLS}x{ROWS} = {COLS * ROWS} taxels, "
          f"{len(electrodes.splitlines())} copper shapes)")


if __name__ == "__main__":
    main()
