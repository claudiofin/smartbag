#!/usr/bin/env python3
"""Every shared dimension, in millimetres. One number, one place.

⛔ WHY THIS FILE EXISTS. It used to not, and both `cad/bag_and_insert.py` and
`render/scenes.py` carried their own copy of the bag and insert dimensions, with
a comment in each admitting it: *"if they change there they have to change here;
this is the project's known debt"*. The two copies happened to agree, but
nothing enforced it — and the values are coupled in non-obvious ways. The height
of the board seat, for instance, is `base + floor + walls + collar − recess +
leather`: five numbers from the CAD deciding one number in the renderer. Getting
that wrong does not raise an error, it silently sinks the board into the
microfibre, which is exactly the bug that showed up as "only the connectors are
visible".

⭐ Pure python, zero imports: it can be imported both by system python (CadQuery)
and by Blender's bundled python, which is the whole reason it can be shared.

Cross-domain constraints that no single file can express — the board fitting in
its seat, the insert passing the bag's smallest cross-section, the contents not
overlapping — are asserted in `tools/check.py`.
"""

# ─── Bag ──────────────────────────────────────────────────────────────────────
# The rigid body ends at BAG_H. The last stretch up to BAG_MOUTH_Z is the soft
# neck, generated in Blender (render/scenes.py, `neck_zip`) because it is the
# one part of the bag that has to change shape.
BAG_W_BOTTOM, BAG_D_BOTTOM = 240.0, 95.0
BAG_W_TOP, BAG_D_TOP = 276.0, 112.0     # section at the end of the rigid body
BAG_H = 190.0                            # end of the rigid body
BAG_MOUTH_Z = 245.0                      # the rim, top of the neck
LEATHER = 3.5                            # structured leather thickness
CORNER_R = 20.0                          # vertical edge radius
HANDLE_Z = 176.0                         # handles attach to the body, not the rim

# ─── Insert ───────────────────────────────────────────────────────────────────
INS_W, INS_D, INS_R = 225.0, 78.0, 16.0
INS_BASE_H = 8.0         # power plate: LiPo + Qi coil
INS_FSR_H = 1.6          # sensing floor
INS_WALL_H = 150.0
INS_COLLAR_H = 20.0
INS_WALL_T = 2.2
INS_COLLAR_T = 4.0

Z_BASE = 0.0
Z_FSR = Z_BASE + INS_BASE_H
Z_WALLS = Z_FSR + INS_FSR_H
Z_COLLAR = Z_WALLS + INS_WALL_H
INS_TOTAL_H = Z_COLLAR + INS_COLLAR_H

# Dividers, which are also the compartments the app names positions by.
DIVIDER_X = INS_W / 6
DIVIDER_T = 1.6

# ─── Collar front band: the board's seat ──────────────────────────────────────
# Derived FROM the board, not chosen by eye. This is the constraint that forced
# the PCB to be redrawn as a strip.
BAND_Y = -27.0           # centre of the band along the depth
BAND_D = 24.0
SEAT_Y = -26.5           # centre of the seat = centre of the board
SEAT_D = 21.0
SEAT_DEPTH_Z = 4.2       # how far the board is recessed below the top edge

# ─── Board envelope (see hardware/generate_pcb.py, OUTLINE) ───────────────────
BOARD_W = 196.0
BOARD_D = 20.0
BOARD_T = 0.6

# ─── FSR matrix ───────────────────────────────────────────────────────────────
FSR_COLS, FSR_ROWS = 16, 6
FSR_FFC_WAYS = 24        # J4: Hirose FH12-24S

# ─── Optics in the collar ─────────────────────────────────────────────────────
# x positions on the board, in board coordinates.
CAMERA_X = -20.0
LED_X = (-52.0, -36.0, -4.0, 12.0)
TOF_X = 48.0
OPTICS_DROP = 9.0        # how far the module hangs below the board plane


def board_seat_z():
    """Height of the seat plane in bag coordinates (insert sitting on the floor).

    ⚠️ Five numbers decide this one. It is a function and not a constant so that
    both the CAD and the renderer get it from the same arithmetic.
    """
    return Z_COLLAR + INS_COLLAR_H - SEAT_DEPTH_Z + LEATHER


def bag_section_at(z):
    """(half-width, half-depth) of the rigid body at height z, outer faces."""
    t = min(max(z / BAG_H, 0.0), 1.0)
    w = BAG_W_BOTTOM + (BAG_W_TOP - BAG_W_BOTTOM) * t
    d = BAG_D_BOTTOM + (BAG_D_TOP - BAG_D_BOTTOM) * t
    return w / 2, d / 2


def neck_section_at(z):
    """(half-width, half-depth, corner radius) of the soft neck at height z.

    ⭐ The neck continues the body's flare instead of restating it. The four
    numbers this replaces used to be literals in the renderer — change the bag's
    taper and the neck would have quietly stopped matching the body it grows
    out of.
    """
    rate_w = (BAG_W_TOP - BAG_W_BOTTOM) / BAG_H
    rate_d = (BAG_D_TOP - BAG_D_BOTTOM) / BAG_H
    rate_r = 2.0 / BAG_H          # the top sketch is filleted at CORNER_R + 2
    over = z - BAG_H
    return ((BAG_W_TOP + rate_w * over) / 2,
            (BAG_D_TOP + rate_d * over) / 2,
            CORNER_R + 2.0 + rate_r * over)
