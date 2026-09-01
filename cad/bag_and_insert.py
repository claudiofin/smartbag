#!/usr/bin/env python3
"""SmartBag — CAD model of the bag and the smart insert (CadQuery).

⛔ WHAT IT MODELS AND WHAT IT DOESN'T. The bag here is a **volume**, not a piece
of leather goods: a structured flared tote with arched handles, there to give
the right scale and the container the insert has to live in. The insert, on the
other hand, is modelled by functional layer, because that is the part the
renders have to explain: collar (compute + camera), walls (flex + antennas),
FSR floor, power plate (LiPo + Qi coil).

⭐ WHY SEPARATE PARTS AND NOT ONE SOLID. Each layer is exported as its own STL
because in Blender it needs a different material — leather, microfibre,
polyimide, copper, LiPo cell. A single solid would force hand-picking faces in
the renderer, which is exactly the non-reproducible work this pipeline avoids.

⚠️ A REAL DIMENSIONAL CONSTRAINT. The bag is flared: narrower at the bottom than
at the mouth. The insert has to pass through the **smallest** cross-section (the
floor), not the mouth. That is why the insert is 225x78 and not 240x82: at 240
it would go in from the top and jam halfway down.

Usage:  python3 cad/bag_and_insert.py            (writes cad/stl/*.stl)
"""
import os
import sys
import time

import cadquery as cq

HERE = os.path.dirname(os.path.abspath(__file__))
STL = os.path.join(HERE, "stl")

# ⭐ Every shared dimension comes from one file. A wildcard import is normally
# a smell; here it is deliberate — `dimensions.py` is nothing but named numbers
# with no imports of its own, and spelling out twenty-five names would only
# invite someone to add a twenty-sixth in the wrong place.
sys.path.insert(0, os.path.dirname(HERE))
from dimensions import *          # noqa: E402,F401,F403

def rrect(w, d, r, h, z=0.0):
    """Prism on a rectangular base with filleted vertical edges."""
    return (cq.Workplane("XY").box(w, d, h, centered=(True, True, False))
            .edges("|Z").fillet(r).translate((0, 0, z)))


# ══ BAG ══════════════════════════════════════════════════════════════════════
def bag_body():
    """Flared shell, hollow, open at the top.

    ⚠️ The `shell` has to come AFTER the vertical edge fillets: the other way
    round, the fillet would have to chase two surfaces (outer and inner) with
    different radii, and OCC refuses that on a 3.5 mm wall.
    """
    # ⛔ THE FILLET GOES IN THE SKETCH, not on the solid. On a flared body the
    # corner edges are NOT parallel to Z, so `edges("|Z")` selects nothing and
    # the fillet fails. Filleting the two profiles before the loft gives the
    # same result without depending on a selector.
    low = cq.Sketch().rect(BAG_W_BOTTOM, BAG_D_BOTTOM).vertices().fillet(CORNER_R)
    high = cq.Sketch().rect(BAG_W_TOP, BAG_D_TOP).vertices().fillet(CORNER_R + 2)
    solid = (cq.Workplane("XY")
             .placeSketch(low, high.moved(cq.Location(cq.Vector(0, 0, BAG_H))))
             .loft())
    return solid.faces(">Z").shell(-LEATHER)


def bag_handles():
    """Two arched handles: half a torus, cut at the attachment height.

    ⭐ A torus rather than a sweep along a spline: CadQuery's sweep wants the
    profile on a plane normal to the path's starting tangent, and for an arc
    that starts inclined that plane has to be built by hand. Half a torus gives
    the same geometry from a single primitive, and the major radius IS the
    distance between the two attachment points.
    """
    ARC_R, TUBE_R = 62.0, 4.5
    # ⚠️ The handles attach to the BODY, not to the rim: the neck pinches shut,
    # and a handle stitched to the rim would hang in mid-air with the bag closed.
    Z_ATTACH = HANDLE_Z
    parts = []
    for y in (-BAG_D_TOP / 2 + 1.5, BAG_D_TOP / 2 - 1.5):
        torus = cq.Solid.makeTorus(ARC_R, TUBE_R, cq.Vector(0, y, Z_ATTACH),
                                   cq.Vector(0, 1, 0))
        half = (cq.Workplane(obj=torus)
                .intersect(cq.Workplane("XY").box(200, 30, 120,
                                                  centered=(True, True, False))
                           .translate((0, y, Z_ATTACH))))
        parts.append(half)
        # Attachments: two leather tabs riveted to the body.
        for x in (-ARC_R, ARC_R):
            parts.append(cq.Workplane("XY")
                         .box(16, 5, 26, centered=(True, True, False))
                         .edges("|Y").fillet(2.5)
                         .translate((x, y, Z_ATTACH - 22)))
    fused = parts[0]
    for p in parts[1:]:
        fused = fused.union(p)
    return fused


def bag_hardware():
    """Metal band at the end of the rigid body, feet, handle studs.

    ⛔ THE RIM TRIM AND THE TURN-LOCK ARE GONE. The trim was a rigid ring right
    where the mouth now pinches: with the bag closed it would have been an oval
    of metal around nothing. The turn-lock is no longer needed either — the bag
    closes with the zip.
    """
    parts = []
    # Band at the end of the rigid body: this is where the structured leather
    # ends and the soft neck begins, so a profile there is genuinely justified.
    outer = rrect(BAG_W_TOP + 1.4, BAG_D_TOP + 1.4, CORNER_R, 6.0, BAG_H - 6.0)
    inner = rrect(BAG_W_TOP - 2 * LEATHER, BAG_D_TOP - 2 * LEATHER,
                  CORNER_R - LEATHER, 12.0, BAG_H - 9.0)
    parts.append(outer.cut(inner))
    for x in (-92, 92):
        for y in (-30, 30):
            parts.append(cq.Workplane("XY").center(x, y).circle(6.0)
                         .extrude(-3.0).edges(">Z or <Z").fillet(1.0))
    # studs at the handle attachments
    for x in (-62, 62):
        for y in (-BAG_D_TOP / 2 + 1.5, BAG_D_TOP / 2 - 1.5):
            parts.append(cq.Workplane("XY").center(x, y).circle(3.2)
                         .extrude(2.0).translate((0, 0, 160.0)))
    fused = parts[0]
    for p in parts[1:]:
        fused = fused.union(p)
    return fused


# ══ INSERT ═══════════════════════════════════════════════════════════════════
def insert_base():
    """Power plate: a pocket for the cell and a recess for the coil, SIDE BY SIDE.

    ⛔ THEY USED TO BE STACKED, AND THAT WAS THE THERMAL PROBLEM. The reasoning
    was sound as far as it went: the coil has to face the bottom of the bag,
    because that is what rests on a charging pad, and a lithium cell between the
    coil and the pad would absorb the field. So the coil recess opened downwards
    and the cell sat on top of it — leaving a watt of charging loss with a
    lithium cell directly above it and nowhere else to go. thermal/budget.py put
    the cell near 60 °C against a 45 °C limit, and that number rests entirely on
    this geometry.

    ⭐ A REAL CELL DISSOLVED IT. The old pouch was 148 mm long because it was
    drawn to fill the floor; Jauch's LP523450JU is 53 mm, which leaves 170 mm of
    floor free. The cell moves aside, the coil keeps the middle — a charging pad
    is a spot on a table you put the bag down on, and a receiver coil off to one
    side is one you would have to aim. Neither is above the other now, so the
    cell is not in the field's way AND not on top of the loss.
    """
    p = rrect(INS_W - 3, INS_D - 3, INS_R - 1.5, INS_BASE_H, Z_BASE)
    # cell pocket, open at the top, at the cell's own size plus slack
    depth = CELL_T + CELL_CLEAR
    pocket = rrect(CELL_L + 2 * CELL_CLEAR, CELL_W + 2 * CELL_CLEAR, 3.0, depth,
                   Z_BASE + INS_BASE_H - depth).translate((CELL_X, 0, 0))
    p = p.cut(pocket)
    # coil recess, open at the bottom
    coil = (cq.Workplane("XY").center(QI_X, 0).circle(QI_R_OUT).circle(QI_R_IN)
            .extrude(1.4).translate((0, 0, Z_BASE)))
    return p.cut(coil)


def battery():
    """Jauch LP523450JU, at the thickness it reaches after cycling."""
    return (rrect(CELL_L, CELL_W, 3.0, CELL_T,
                  Z_BASE + INS_BASE_H - CELL_T - 0.4)
            .translate((CELL_X, 0, 0))
            .edges("|X or |Y").fillet(0.8))


def qi_coil():
    """Flat coil: 9 concentric turns of litz wire."""
    turns = []
    for i in range(9):
        r = QI_R_IN + 0.6 + i * 1.5
        turns.append(cq.Workplane("XY").center(QI_X, 0)
                     .circle(r + 0.45).circle(r - 0.45).extrude(0.9)
                     .translate((0, 0, Z_BASE + 0.15)))
    c = turns[0]
    for t in turns[1:]:
        c = c.union(t)
    return c


def insert_floor():
    return rrect(INS_W - 3, INS_D - 3, INS_R - 1.5, INS_FSR_H, Z_FSR)


def fsr_matrix():
    """96 taxels (16 columns x 6 rows) of piezoresistive film.

    ⭐ Exported as a compound of 96 separate solids, unfused: an STL does not
    need a single manifold solid, and the boolean union of 96 boxes in OCC costs
    more than the rest of the model put together.
    """
    nx, ny = FSR_COLS, FSR_ROWS
    pitch_x = (INS_W - 18) / nx
    pitch_y = (INS_D - 14) / ny
    side_x, side_y = pitch_x - 2.4, pitch_y - 2.4
    taxels = []
    for i in range(nx):
        for j in range(ny):
            x = -(INS_W - 18) / 2 + pitch_x * (i + 0.5)
            y = -(INS_D - 14) / 2 + pitch_y * (j + 0.5)
            taxels.append(cq.Workplane("XY")
                          .box(side_x, side_y, 0.35, centered=(True, True, False))
                          .translate((x, y, Z_FSR + INS_FSR_H)).val())
    return cq.Workplane("XY").add(taxels)


def insert_walls():
    """Semi-rigid microfibre walls, with the channel for the flex tail."""
    outer = rrect(INS_W, INS_D, INS_R, INS_WALL_H, Z_WALLS)
    cavity = rrect(INS_W - 2 * INS_WALL_T, INS_D - 2 * INS_WALL_T,
                   INS_R - INS_WALL_T, INS_WALL_H + 2, Z_WALLS - 1)
    p = outer.cut(cavity)
    # FSR flex channel: runs down the back wall.
    channel = (cq.Workplane("XY")
               .box(12, 1.2, INS_WALL_H - 6, centered=(True, True, False))
               .translate((0, INS_D / 2 - INS_WALL_T, Z_WALLS + 3)))
    return p.cut(channel)


def insert_dividers():
    """Two dividers — also the quadrants the app uses to name positions."""
    d = []
    for x in (-DIVIDER_X, DIVIDER_X):
        d.append(cq.Workplane("XY")
                 .box(DIVIDER_T, INS_D - 2 * INS_WALL_T - 1, INS_WALL_H * 0.62,
                      centered=(True, True, False))
                 .edges("|X").fillet(0.6)
                 .translate((x, 0, Z_WALLS)))
    return d[0].union(d[1])


def insert_collar():
    """Rigid collar: a thin ring on three sides, a solid band at the front.

    ⛔ WHY THE BAND. The first version was a uniform 4 mm ring, and in the render
    the board ended up floating over the mouth, because **a board 20 mm deep
    does not fit in a 4 mm wall**. The front band takes the depth to 24 mm only
    where it is needed, leaving the other three sides thin. It is also the right
    place for the camera, which has to look down from the front and not from the
    centre (from the centre it would frame the back of your hand instead of the
    object held between your fingers).
    """
    outline = rrect(INS_W, INS_D, INS_R, INS_COLLAR_H, Z_COLLAR)
    cavity = rrect(INS_W - 2 * INS_COLLAR_T, INS_D - 2 * INS_COLLAR_T,
                   INS_R - INS_COLLAR_T, INS_COLLAR_H + 2, Z_COLLAR - 1)
    c = outline.cut(cavity)
    # ⚠️ The band has to be intersected with the collar outline, otherwise it
    # sticks out past the corner radius and the insert no longer passes through
    # the smallest cross-section of the bag.
    band = (cq.Workplane("XY")
            .box(210, BAND_D, INS_COLLAR_H, centered=(True, True, False))
            .translate((0, BAND_Y, Z_COLLAR))
            .intersect(outline))
    c = c.union(band)
    # Board seat, open upwards.
    z_seat = Z_COLLAR + INS_COLLAR_H - SEAT_DEPTH_Z
    c = c.cut(cq.Workplane("XY")
              .box(200, SEAT_D, SEAT_DEPTH_Z + 1, centered=(True, True, False))
              .translate((0, SEAT_Y, z_seat)))

    # Optical windows: they run from the seat down through the band.
    def hole(x, r):
        return (cq.Workplane("XY").center(x, SEAT_Y - 4.0).circle(r)
                .extrude(INS_COLLAR_H + 2).translate((0, 0, Z_COLLAR - 1)))
    c = c.cut(hole(CAMERA_X, 2.6))               # IR lens
    for x in LED_X:
        c = c.cut(hole(x, 1.3))                  # IR illuminators
    c = c.cut(hole(TOF_X, 1.8))                  # ToF window
    return c


def fsr_cable():
    """Flat cable carrying the matrix from connector J4 down to the floor.

    ⭐ It is its own part and NOT a tail on the PCB. In the first layout the
    matrix was served by a 40 mm flex tail leaving the board: it did not reach
    the floor (150 mm further down) and it turned the PCB into a cross that fit
    nowhere. A separate FFC solves both, and it is also how it would really be
    assembled — the cable pulls out to open the insert.
    """
    y_wall = -INS_D / 2 + INS_WALL_T + 0.3
    z_top = Z_COLLAR + INS_COLLAR_H - SEAT_DEPTH_Z
    z_bottom = Z_FSR + INS_FSR_H + 0.25
    t = 0.3
    # ⭐ ROUTE: J4 (x = +32) → horizontal run under the band across to x = -32 →
    # down the inner face of the front wall → back in along the floor, under the
    # matrix.
    #
    # ⛔ THE DESCENT IS ON THE LEFT even though the connector is on the right,
    # and that is not a composition choice. The section render removes the
    # front-right quarter: with the descent at x = +32 the cable was left
    # hanging in mid-air across the opening, detached from the wall that was
    # holding it. On the left it stays attached to a wall that still exists. The
    # extra run is 64 mm of FFC — a real cost that buys a sane mounting.
    #
    # ⚠️ J4 faces the BACK of the band (y = SEAT_Y + 6.6): the board is mounted
    # without rotation, and KiCad's GLB export flips the Y axis.
    y_conn = SEAT_Y + 6.6
    x_conn, x_descent = 32.0, -32.0
    runs = [
        cq.Workplane("XY")
        .box(abs(x_conn - x_descent) + 15, 9, t, centered=(True, True, False))
        .translate(((x_conn + x_descent) / 2, y_conn - 4.5, z_top - 0.9)),
        cq.Workplane("XY").box(15, 22, t, centered=(True, True, False))
        .translate((x_descent, (y_conn + y_wall) / 2 + 2, z_top - 0.9)),
        cq.Workplane("XY").box(15, t, z_top - 0.9 - z_bottom,
                               centered=(True, True, False))
        .translate((x_descent, y_wall, z_bottom)),
        cq.Workplane("XY").box(15, 28, t, centered=(True, True, False))
        .translate((x_descent, y_wall + 14, z_bottom)),
    ]
    c = runs[0]
    for r in runs[1:]:
        c = c.union(r)
    return c


# ⛔ `radar_islands` REMOVED. It was a piece of plastic pretending to be the
# antenna, glued to the walls. With the strip-shaped board the two rigid radar
# islands ARE part of the PCB, at the ends of the flex tails: modelling them
# again here would mean keeping two different truths about the same thing.


# ══ ZIP ══════════════════════════════════════════════════════════════════════
# ⛔ THE FLAPS AND TEETH ARE NO LONGER MODELLED HERE. They were two rigid
# 273x54 panels hinged on the rim, and opening them — up, down, inwards,
# outwards, all four were tried — always looked like a hatch, because two rigid
# plates rotating around a hinge ARE a hatch. The right motion is not a
# rotation: it is the mouth gaping open and the two rows of teeth SEPARATING.
# That needs a surface that changes shape, so neck and teeth are generated in
# Blender (render/scenes.py, `neck_zip`) as a mesh with two interpolable states.
# What stays here is the slider, the only genuinely rigid part of a zip.
def zip_slider():
    """Slider with a hanging pull. Modelled at x = 0: the travel is animated.

    ⛔ THE PULL HANGS OFF THE FRONT, it does not stick out sideways. The first
    version was a horizontal beak poking out in +x, and combined with the slider
    sitting stranded in the middle of a gaping mouth it made the zip look like a
    decorative clasp. A pull hangs by gravity down the front side of the zip:
    that is what tells you which way it gets pulled.
    """
    body = (cq.Workplane("XY").box(13.0, 8.0, 5.6, centered=(True, True, False))
            .edges("|Z").fillet(2.4).edges(">Z").fillet(1.2)
            .translate((0, 0, BAG_MOUTH_Z - 4.6)))
    # eyelet on the front face
    eyelet = (cq.Workplane("XY").box(3.2, 3.0, 3.2, centered=(True, True, False))
              .translate((0, -5.0, BAG_MOUTH_Z - 3.2)))
    pull = (cq.Workplane("XY")
            .box(7.0, 1.4, 15.0, centered=(True, True, False))
            .edges("|Y").fillet(3.0)
            .translate((0, -6.2, BAG_MOUTH_Z - 17.0)))
    return body.union(eyelet).union(pull)


# ══ OPTICS IN THE COLLAR ═════════════════════════════════════════════════════
# ⛔ ADDED BECAUSE THE CAMERA COULD NOT BE SEEN. The films had a pink cone that
# flashed, but the module emitting it did not exist as an object: light came out
# of a hole in the microfibre. A sensor you cannot see is a sensor nobody
# understands — and the camera at the mouth is the part that does the
# recognition, i.e. the thing the whole project promises.
def optics_body():
    """IR camera module + four illuminators + ToF, hanging under the band."""
    y = SEAT_Y - 4.0
    z = Z_COLLAR + INS_COLLAR_H - SEAT_DEPTH_Z - OPTICS_DROP
    parts = [
        # camera can
        cq.Workplane("XY").box(19.0, 13.0, 9.0, centered=(True, True, False))
        .edges("|Z").fillet(2.0).translate((CAMERA_X, y, z)),
        # illuminator bar
        cq.Workplane("XY").box(74.0, 8.0, 5.0, centered=(True, True, False))
        .edges("|Z").fillet(1.5).translate((CAMERA_X, y, z + 1.0)),
        # ToF can
        cq.Workplane("XY").box(9.0, 9.0, 7.0, centered=(True, True, False))
        .edges("|Z").fillet(1.5).translate((TOF_X, y, z + 1.0)),
    ]
    c = parts[0]
    for q in parts[1:]:
        c = c.union(q)
    return c


def optics_lenses():
    """The lenses, kept separate: on screen they want black glass, not microfibre."""
    y = SEAT_Y - 4.0
    z = Z_COLLAR + INS_COLLAR_H - SEAT_DEPTH_Z - OPTICS_DROP
    lenses = [cq.Workplane("XY").center(CAMERA_X, y).circle(3.6).extrude(-1.6)
              .translate((0, 0, z)).edges("<Z").fillet(0.6)]
    for x in LED_X:
        lenses.append(cq.Workplane("XY").center(x, y).circle(1.7).extrude(-1.2)
                      .translate((0, 0, z + 1.0)))
    lenses.append(cq.Workplane("XY").center(TOF_X, y).circle(2.1).extrude(-1.4)
                  .translate((0, 0, z + 1.0)))
    c = lenses[0]
    for q in lenses[1:]:
        c = c.union(q)
    return c


# ⛔ THE HAND IS GONE. Four attempts to make one read — from above, tilted, in
# section, with tapered and curled phalanges — and it stayed the worst thing in
# the frame while stealing attention from the sensors, which are the subject. In
# the films an object now descends on its own: a standard product-animation
# convention, understood in the first frame, with nothing to get wrong.


PARTS = [
    ("bag_body", bag_body), ("bag_handles", bag_handles),
    ("bag_hardware", bag_hardware),
    ("insert_base", insert_base), ("battery", battery),
    ("qi_coil", qi_coil), ("insert_floor", insert_floor),
    ("fsr_matrix", fsr_matrix), ("insert_walls", insert_walls),
    ("insert_dividers", insert_dividers),
    ("insert_collar", insert_collar), ("fsr_cable", fsr_cable),
    ("zip_slider", zip_slider),
    ("optics_body", optics_body), ("optics_lenses", optics_lenses),
]


if __name__ == "__main__":
    os.makedirs(STL, exist_ok=True)
    print(f"insert: {INS_W} x {INS_D} x {INS_TOTAL_H:.1f} mm")
    for name, fn in PARTS:
        t0 = time.time()
        cq.exporters.export(fn(), os.path.join(STL, f"{name}.stl"),
                            tolerance=0.02, angularTolerance=0.06)
        print(f"OK  {name}.stl  ({time.time() - t0:.1f}s)")
