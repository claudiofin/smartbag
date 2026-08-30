#!/usr/bin/env python3
"""Assert the constraints that the renders discovered by accident.

⛔ WHY THIS EXISTS. Every constraint checked here was found the expensive way —
by modelling something, rendering it, and seeing that it was wrong. A board
51 mm deep in a 4 mm collar wall. An FSR tail 40 mm long against a 150 mm drop.
An object landing on top of the divider. None of those raise an error anywhere:
they produce a picture that looks fine until you look closely. Written down as
assertions they cannot silently come back.

⚠️ It imports nothing from Blender, so it runs on plain python3 and could sit in
CI. `render/animation.py` is read with the AST rather than imported, because
importing it needs bpy.

Usage:  python3 tools/check.py
"""
import ast
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import dimensions as d              # noqa: E402
sys.path.insert(0, os.path.join(ROOT, "hardware"))
import generate_pcb as pcb          # noqa: E402

FAILURES = []


def check(label, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"   [{detail}]" if detail else ""))
    if not ok:
        FAILURES.append(label)


def scene_contents():
    """CONTENTS from render/scenes.py, read without importing bpy."""
    tree = ast.parse(open(os.path.join(ROOT, "render", "scenes.py")).read())
    node = [n for n in tree.body if isinstance(n, ast.Assign)
            and getattr(n.targets[0], "id", "") == "CONTENTS"][0]
    return ast.literal_eval(node.value)


def drop_reads_from_contents():
    """True if the object_drop shot derives its landing spot from CONTENTS.

    ⭐ STRUCTURAL, NOT NUMERIC. The first version of this check compared two
    literals and asserted they matched. Better than nothing, but the real fix
    was to delete one of them: the shot now unpacks the entry out of
    `sc.CONTENTS`, so there is no second copy left to drift. What is verified
    here is that the copy has not come back.
    """
    src = open(os.path.join(ROOT, "render", "animation.py")).read()
    tree = ast.parse(src)
    for n in ast.walk(tree):
        if not (isinstance(n, ast.Assign) and isinstance(n.targets[0], ast.Tuple)):
            continue
        names = [getattr(e, "id", "") for e in n.targets[0].elts]
        if "OBJ_X" not in names or "OBJ_Y" not in names:
            continue
        # derived: the right-hand side mentions CONTENTS somewhere
        return "CONTENTS" in ast.dump(n.value)
    return False


def rect_overlap(a, b, slack=0.0):
    (ax, ay, aw, ad), (bx, by, bw, bd) = a, b
    return (abs(ax - bx) < (aw + bw) / 2 - slack
            and abs(ay - by) < (ad + bd) / 2 - slack)


print("── board vs its seat")
outline_x = [p[0] for p in pcb.OUTLINE]
outline_y = [p[1] for p in pcb.OUTLINE]
board_w = max(outline_x) - min(outline_x)
board_d = max(outline_y) - min(outline_y)
check("declared board envelope matches the drawn outline",
      (board_w, board_d) == (d.BOARD_W, d.BOARD_D),
      f"drawn {board_w}x{board_d}, declared {d.BOARD_W}x{d.BOARD_D}")
check("board fits the seat in depth", board_d <= d.SEAT_D,
      f"{board_d} <= {d.SEAT_D}")
check("seat fits inside the front band", d.SEAT_D <= d.BAND_D,
      f"{d.SEAT_D} <= {d.BAND_D}")
# ⛔ The original failure: a board deeper than the collar wall. The band exists
# precisely so this passes; without it the wall is INS_COLLAR_T = 4 mm.
check("board would NOT fit a plain collar wall (this is why the band exists)",
      board_d > d.INS_COLLAR_T, f"{board_d} > {d.INS_COLLAR_T}")

print("\n── board vs the collar footprint")
# ⚠️ Measured at the BOARD's own front edge, not the band's. The band reaches
# further forward than the board does, and at its front edge the collar's corner
# radius has fully turned — testing there rejected a board that actually fits.
y_front = d.SEAT_Y - d.BOARD_D / 2
dy = abs(y_front) - (d.INS_D / 2 - d.INS_R)
half_w = (d.INS_W / 2 - d.INS_R) + (
    (d.INS_R ** 2 - dy ** 2) ** 0.5 if dy > 0 else d.INS_R)
check("antenna islands stay inside the collar at the band's front edge",
      max(outline_x) <= half_w, f"board {max(outline_x)} <= collar {half_w:.1f}")

print("\n── optical windows in the collar band")
# ⚠️ NOT "on the rigid island". The optics module hangs under the band and
# reaches the board through J1's FFC, so the windows only have to fall inside
# the band — an earlier version of this check demanded they sit on the board's
# central island and failed a perfectly sound illuminator position.
band_half = 210.0 / 2
for name, x in [("camera", d.CAMERA_X), ("ToF", d.TOF_X)] + \
               [(f"LED{i}", v) for i, v in enumerate(d.LED_X)]:
    check(f"{name} window inside the band", abs(x) <= band_half, f"x={x}")

print("\n── insert vs bag")
inner_w, inner_d = (2 * (h - d.LEATHER) for h in d.bag_section_at(0.0))
check("insert passes the bag's smallest cross-section (the floor, not the mouth)",
      d.INS_W <= inner_w and d.INS_D <= inner_d,
      f"insert {d.INS_W}x{d.INS_D} vs floor {inner_w:.1f}x{inner_d:.1f}")
# ⛔ The insert must end below where the neck starts pinching, or closing the zip
# drives soft leather straight into a rigid collar.
check("insert top clears the start of the soft neck",
      d.LEATHER + d.INS_TOTAL_H <= d.BAG_H,
      f"{d.LEATHER + d.INS_TOTAL_H} <= {d.BAG_H}")

print("\n── FSR matrix vs its connector")
lines = d.FSR_COLS + d.FSR_ROWS
check("row+column lines fit the FFC", lines + 2 <= d.FSR_FFC_WAYS,
      f"{lines} signals + 2 = {lines + 2} <= {d.FSR_FFC_WAYS} ways")
j4 = [c for c in pcb.COMPONENTS if c[0] == "J4"][0]
check("J4 is the connector the matrix count implies", "24S" in j4[3], j4[3])

print("\n── contents do not collide")
contents = scene_contents()
foot = [(c[1], c[2], c[3], c[4]) for c in contents]
names = [c[0] for c in contents]
for i in range(len(foot)):
    for j in range(i + 1, len(foot)):
        check(f"{names[i]} does not overlap {names[j]}",
              not rect_overlap(foot[i], foot[j]))
for (name, (cx, cy, w, dd)) in zip(names, foot):
    straddles = any(abs(cx - sx) < (w + d.DIVIDER_T) / 2
                    for sx in (-d.DIVIDER_X, d.DIVIDER_X))
    check(f"{name} does not straddle a divider", not straddles,
          f"x={cx}, dividers at +/-{d.DIVIDER_X}")
    inside = (abs(cx) + w / 2 <= d.INS_W / 2 - d.INS_WALL_T
              and abs(cy) + dd / 2 <= d.INS_D / 2 - d.INS_WALL_T)
    check(f"{name} fits inside the insert", inside)

print("\n── the film agrees with the model")
# ⛔ The bug the video showed: the dropped object landed at x = 44, on top of
# the divider, because the shot carried its own copy of the coordinate.
check("object_drop reads its landing spot from CONTENTS, not a second copy",
      drop_reads_from_contents())

print()
if FAILURES:
    print(f"{len(FAILURES)} FAILED:")
    for f in FAILURES:
        print(f"  - {f}")
    sys.exit(1)
print("all constraints hold")
