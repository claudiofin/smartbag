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
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import dimensions as d              # noqa: E402
sys.path.insert(0, os.path.join(ROOT, "hardware"))
import generate_pcb as pcb          # noqa: E402
import netlist as nl                # noqa: E402
import place as pl                  # noqa: E402
import optics_netlist as onl        # noqa: E402
import taxel_netlist as tnl         # noqa: E402

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
j4_fp = nl.part("J4")[4]
check("J4 is the connector the matrix count implies", "24S" in j4_fp, j4_fp)

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

print("\n── schematic and board agree")
# ⛔ Every pin must land on a pad that exists. A symbol with more pins than its
# footprint has pads imports without complaint and then silently drops nets.
import re                                                       # noqa: E402
bad_pins = []
for ref, _v, _sym, lib, fp, pins, _x, _y in nl.PARTS:
    path = pcb.footprint_path(lib, fp)
    pads = set(re.findall(r'\(pad "([^"]*)"', open(path).read()))
    missing = {str(p[0]) for p in pins} - pads
    if missing:
        bad_pins.append(f"{ref}: {sorted(missing)}")
check("every declared pin has a pad in its footprint", not bad_pins,
      "; ".join(bad_pins))

nets = nl.nets()
driven = {n for n, pins in nets.items()
          if any(t in ("power_out", "output", "bidirectional") for _r, _p, t in pins)}
undriven_power = sorted(n for n, pins in nets.items()
                        if any(t == "power_in" for _r, _p, t in pins)
                        and n not in driven and n not in nl.POWER_FLAGS)
check("every power rail is driven or carries a power flag", not undriven_power,
      str(undriven_power))

clashes = {n: [r for r, _p, t in pins if t == "output"]
           for n, pins in nets.items()}
clashes = {n: v for n, v in clashes.items() if len(v) > 1}
check("no net has two outputs fighting", not clashes, str(clashes))

# ⛔ THIS USED TO CHECK THAT THE FSR COLUMNS LEFT U1 IN PIN ORDER, which was the
# claim that the board needed no autorouter. Both halves of that are gone: the
# columns leave a multiplexer now, not the processor, and the board is routed by
# Freerouting. What is worth checking instead is that all sixteen columns and all
# six rows still reach the connector, because the front end grew an extra chip
# between them and it would be easy to lose one.
_j4 = {net for _n, _p, _t, net in nl.part("J4")[5]}
_mux = {net for _n, _p, _t, net in nl.part("U7")[5]}
_cols = {f"FSR_C{i}" for i in range(d.FSR_COLS)}
_rows = {f"FSR_R{i}" for i in range(d.FSR_ROWS)}
check("every FSR column reaches both the connector and the multiplexer",
      _cols <= _j4 and _cols <= _mux,
      f"missing at J4 {sorted(_cols - _j4)}, at U7 {sorted(_cols - _mux)}")
check("every FSR row reaches the connector", _rows <= _j4,
      str(sorted(_rows - _j4)))

# ⭐ And that each row lands on an amplifier rather than on a bare ADC pin. This
# is the whole finding of firmware/test_sb_fsr.c expressed as an assertion: a
# row tied straight to the processor is the topology that reads 83% low.
_amp_in = {net for ref in ("U8", "U9")
           for _n, name, _t, net in nl.part(ref)[5] if name.endswith("-")}
check("every FSR row lands on a transimpedance amplifier input",
      _rows <= _amp_in, str(sorted(_rows - _amp_in)))

print("\n── placement")
# ⚠️ Courtyards, not pad extents. The first version of this check used pad
# bounding boxes and passed a J1/U2 pair that DRC then rejected.
def courtyard(lib, fp):
    t = open(pcb.footprint_path(lib, fp)).read()
    pts = [(float(a), float(b))
           for m in re.finditer(r'\(fp_(?:line|rect|poly)\b(.*?)\(layer "F\.CrtYd"',
                                t, re.S)
           for a, b in re.findall(r'\((?:start|end|xy) ([-\d.]+) ([-\d.]+)\)',
                                  m.group(1))]
    xs = [q[0] for q in pts] or [-1, 1]
    ys = [q[1] for q in pts] or [-1, 1]
    return min(xs), max(xs), min(ys), max(ys)

# ⚠️ The SETTLED positions, not the hints in netlist.py. Checking the hints
# would test a floorplan nobody fabricates.
_settled, _worst = pl.relax(nl.PARTS,
                            lambda l, f: open(pcb.footprint_path(l, f)).read(),
                            rotation=nl.ROTATION)
boxes = []
for ref, _v, _s, lib, fp, _p, _hx, _hy in nl.PARTS:
    x, y = _settled[ref]
    x0, x1, y0, y1 = courtyard(lib, fp)
    boxes.append((ref, x + x0, x + x1, y + y0, y + y1))
overlap = [(boxes[i][0], boxes[j][0])
           for i in range(len(boxes)) for j in range(i + 1, len(boxes))
           if boxes[i][1] < boxes[j][2] and boxes[j][1] < boxes[i][2]
           and boxes[i][3] < boxes[j][4] and boxes[j][3] < boxes[i][4]]
check("no two courtyards overlap", not overlap, str(overlap))
# ⛔ THREE ISLANDS, NOT ONE, AND NOTHING ON THE FLEX. The board is a 196 mm strip
# with two 30 mm flex tails in it; a package soldered across a section that bends
# does not stay soldered. An earlier placement pass put a 24-way connector and a
# row of resistors out over a tail, and off the board edge with them.
outside = [r for r, x0, x1, y0, y1 in boxes
           if not any(ix0 <= x0 and x1 <= ix1 and iy0 <= y0 and y1 <= iy1
                      for ix0, ix1, iy0, iy1 in pl.ISLANDS)]
check("every part sits on a rigid island, none on the flex tails",
      not outside, str(outside))

print("\n── the firmware agrees with the model")
# ⛔ The taxel grid exists in three places — dimensions.py, the FFC pinout in
# netlist.py, and #defines in the C. Nothing links them, so nothing stops one of
# them drifting, and a driver that scans 16 columns of a 12-column matrix reads
# garbage from four of them without ever erroring.
_fsr_h = open(os.path.join(ROOT, "firmware", "sb_fsr.h")).read()


def _cdefine(name):
    m = re.search(r"#define\s+%s\s+(\d+)" % name, _fsr_h)
    return int(m.group(1)) if m else None


check("firmware SB_FSR_COLS matches dimensions.py",
      _cdefine("SB_FSR_COLS") == d.FSR_COLS,
      f"C {_cdefine('SB_FSR_COLS')} vs dimensions {d.FSR_COLS}")
check("firmware SB_FSR_ROWS matches dimensions.py",
      _cdefine("SB_FSR_ROWS") == d.FSR_ROWS,
      f"C {_cdefine('SB_FSR_ROWS')} vs dimensions {d.FSR_ROWS}")
_ways = 1 + d.FSR_COLS + d.FSR_ROWS
check("the FFC has a way for every line plus a ground",
      _ways <= d.FSR_FFC_WAYS,
      f"{d.FSR_COLS} cols + {d.FSR_ROWS} rows + GND = {_ways} "
      f"into a {d.FSR_FFC_WAYS}-way connector")

print("\n── the two new boards fit the things they go inside")
# ⛔ THE OPTICS FLEX AND THE TAXEL SHEET WERE NEVER CHECKED AGAINST THE BAG. The
# insert board has been measured against the collar since early on; the other
# two arrived later and nothing looked at them. A board that does not fit is not
# a DRC problem — DRC is delighted by a board of any size — it is this file's.
_ow = max(x for x, _ in onl.OUTLINE) - min(x for x, _ in onl.OUTLINE)
_oh = max(y for _, y in onl.OUTLINE) - min(y for _, y in onl.OUTLINE)
check("the optics flex fits across the insert",
      _ow <= d.INS_W, f"{_ow:.0f} mm strip in a {d.INS_W:.0f} mm insert")
check("the optics flex fits inside the collar band",
      _oh <= d.INS_COLLAR_H,
      f"{_oh:.0f} mm tall against a {d.INS_COLLAR_H:.0f} mm collar")

# ⭐ The optics positions live in dimensions.py because the renders, the CAD and
# this board all have to agree about where the camera is pointing. Assert the
# board actually used them rather than a copy that has drifted.
for _ref, _want in (("U10", d.TOF_X), ("J11", d.CAMERA_X)):
    _got = onl.part(_ref)[6]
    check(f"{_ref} sits where dimensions.py puts it",
          abs(_got - _want) < 0.01, f"board {_got} vs dimensions {_want}")
_led_x = sorted(onl.part(f"D{i + 1}")[6] for i in range(len(d.LED_X)))
check("the illuminators sit where dimensions.py puts them",
      _led_x == sorted(d.LED_X), f"{_led_x} vs {sorted(d.LED_X)}")

# ⚠️ Every part on the optics flex has to be inside its own outline too — the
# LEDs are placed from dimensions.py, which knows nothing about this board.
_ox0, _ox1 = min(x for x, _ in onl.OUTLINE), max(x for x, _ in onl.OUTLINE)
_off = [p[0] for p in onl.PARTS if not (_ox0 + 2 <= p[6] <= _ox1 - 2)]
check("every optics part is on the optics board", not _off, str(_off))

_tw = max(x for x, _ in tnl.OUTLINE) - min(x for x, _ in tnl.OUTLINE)
check("the taxel sheet's sensing area is the insert floor",
      _tw >= d.INS_W and _tw <= d.INS_W + 20,
      f"{_tw:.0f} mm wide against a {d.INS_W:.0f} mm floor")

print("\n── the three boards agree about the cables between them")
# ⛔ A FLEX CABLE IS A PROMISE BETWEEN TWO FILES. J1 on the insert board and J10
# on the optics flex are the two ends of one cable; so are J4 and J20. Nothing
# stops somebody inserting a pin on one end and not the other, and the failure
# mode is not subtle — it puts VSYS into an interrupt input. These are declared
# in different modules precisely so they can be compared.
for a_mod, a_ref, b_mod, b_ref, cable in (
        (nl, "J1", onl, "J10", "insert to optics"),
        (nl, "J4", tnl, "J20", "insert to taxels")):
    _a = {n: net for n, _pn, _t, net in a_mod.part(a_ref)[5]}
    _b = {n: net for n, _pn, _t, net in b_mod.part(b_ref)[5]}
    _diff = sorted(k for k in set(_a) | set(_b) if _a.get(k) != _b.get(k))
    check(f"{a_ref} and {b_ref} agree pin for pin ({cable})", not _diff,
          "; ".join(f"pin {k}: {_a.get(k)} vs {_b.get(k)}" for k in _diff))

print("\n── the firmware's events have hardware that can raise them")
# ⛔ THE CHECK THAT WAS MISSING FOR THE WHOLE PROJECT. firmware/smartbag.h
# declares the events the wake-up chain runs on, and one of them —
# SB_EV_TOF_CROSSED, the beam across the mouth breaking — had no sensor anywhere
# in the netlist. Not a regression: no schematic ever had one. dimensions.py
# placed it, the films showed it working, the state machine depended on it, and
# every check passed, because nothing read the two files against each other.
#
# ⚠️ This maps each event to a net that must exist. It cannot prove the hardware
# WORKS; it can prove somebody wired something up, which is the failure that
# actually happened.
EVENT_SOURCES = {
    "SB_EV_CLOSURE_OPENED": "HALL_OUT",
    "SB_EV_CLOSURE_CLOSED": "HALL_OUT",
    "SB_EV_TOF_CROSSED": "TOF_INT",
    "SB_EV_FRAME_READY": "CS_CAM",
    "SB_EV_CLASSIFIED": "CS_CAM",
    "SB_EV_MOTION": "IMU_INT1",
    "SB_EV_STILL": "IMU_INT1",
}
_h = open(os.path.join(ROOT, "firmware", "smartbag.h")).read()
_declared = set(re.findall(r"\b(SB_EV_[A-Z_]+)\b", _h))
_nets = set(nets)
_unmapped = sorted(_declared - set(EVENT_SOURCES))
check("every firmware event is mapped to a source net", not _unmapped,
      str(_unmapped))
_orphan = sorted(e for e, n in EVENT_SOURCES.items()
                 if e in _declared and n not in _nets)
check("every firmware event has hardware that can raise it", not _orphan,
      "; ".join(f"{e} needs {EVENT_SOURCES[e]}" for e in _orphan))

print("\n── the charge policy agrees with the thermal model")
# ⛔ TWO COPIES OF A SAFETY LIMIT IS ONE COPY TOO MANY. thermal/budget.py
# computes what a closed bag can dissipate; firmware/sb_power.h enforces it. A
# constant that drifts away from the analysis that justified it is worse than no
# constant, because it looks considered. This asserts they are the same number.
_pw = open(os.path.join(ROOT, "firmware", "sb_power.h")).read()


def _cdef(name):
    m = re.search(r"#define\s+%s\s+(-?\d+)" % name, _pw)
    return int(m.group(1)) if m else None


sys.path.insert(0, os.path.join(ROOT, "thermal"))
import budget as _th                                            # noqa: E402

_area = _th.bag_surface_m2()
_coil = 3.141592653589793 * _th.COIL_R_M ** 2
_r = (_th.WALL_T_M / (_th.WALL_K * _coil * _th.SPREADING)
      + 1.0 / (8.0 * _coil * _th.SPREADING))
_head = _th.CELL_LIMIT_C - _th.MARGIN_K - _th.AMBIENT
_safe_w = (_head / (_r + 1 / (8.0 * _area))) / (1 - _th.QI_EFFICIENCY)

check("the firmware's cell ceiling matches thermal/budget.py",
      _cdef("SB_CELL_LIMIT_C") == int(_th.CELL_LIMIT_C),
      f"firmware {_cdef('SB_CELL_LIMIT_C')} vs model {_th.CELL_LIMIT_C}")
check("the firmware's margin matches thermal/budget.py",
      _cdef("SB_CELL_MARGIN_K") == int(_th.MARGIN_K),
      f"firmware {_cdef('SB_CELL_MARGIN_K')} vs model {_th.MARGIN_K}")
# ⚠️ Rounded to 100 mW: the model is a lumped estimate and pretending its third
# significant figure is meaningful would be its own kind of dishonesty.
check("the closed-bag charge ceiling matches what the model allows",
      abs(_cdef("SB_CHG_SLOW_MW") - _safe_w * 1000) < 100,
      f"firmware {_cdef('SB_CHG_SLOW_MW')} mW vs model {_safe_w * 1000:.0f} mW")

print("\n── the pictures are not older than what they show")
# ⛔ NOTHING HAS EVER CHECKED THIS, and it is the easiest way for a repository to
# start lying. A render is a claim about a design at a moment; the design moved
# on — three boards where there was one, an antenna keepout, wider flex tails,
# a whole optics flex — and the images kept showing the old one, confidently,
# with no warning anywhere. A stale picture is worse than no picture because it
# looks like evidence.
#
# ⚠️ It compares modification times, which is crude and occasionally wrong (a
# touched file, a fresh clone). Crude and noisy beats absent: the failure mode
# it catches is "somebody changed the board and forgot", which is the one that
# actually happens.
_SHOWS = {
    "render/views/hero.png": ["cad/bag_and_insert.py", "dimensions.py",
                              "render/scenes.py"],
    "render/views/section.png": ["cad/bag_and_insert.py", "dimensions.py",
                                 "render/scenes.py",
                                 "hardware/smartbag_core.kicad_pcb"],
    "render/views/collar.png": ["dimensions.py", "render/scenes.py",
                                "hardware/optics_netlist.py"],
    "render/views/exploded.png": ["cad/bag_and_insert.py", "dimensions.py",
                                  "render/scenes.py",
                                  "hardware/smartbag_core.kicad_pcb"],
    "media/smartbag.mp4": ["render/animation.py", "render/scenes.py",
                           "dimensions.py"],
    "media/smartbag_sequence.mp4": ["render/animation.py", "render/scenes.py",
                                    "dimensions.py"],
}
_stale = []
for _art, _srcs in _SHOWS.items():
    _ap = os.path.join(ROOT, _art)
    if not os.path.exists(_ap):
        _stale.append(f"{_art} (missing)")
        continue
    _at = os.path.getmtime(_ap)
    for _s in _srcs:
        _sp = os.path.join(ROOT, _s)
        if os.path.exists(_sp) and os.path.getmtime(_sp) > _at:
            _stale.append(f"{_art} < {_s}")
            break
check("every render is newer than the files it depicts", not _stale,
      "; ".join(_stale))

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
