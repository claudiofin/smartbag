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
import subprocess
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
                            rotation=nl.ROTATION, decouple=nl.DECOUPLE,
                            fanout=nl.FANOUT, fanout_out=nl.FANOUT_OUT_MM,
                            fanout_via=nl.FANOUT_VIA_MM, pad_nets=nl.pad_nets,
                            back=nl.BACK)
# ⛔ THE ROTATION WAS MISSING HERE AND THE PLACER HAD IT. A part turned 90
# degrees has its courtyard turned with it; this test used the unrotated box, so
# for the two radars — the only rotated parts on the board — it was checking a
# rectangle 0.15 mm out in each axis from the one that gets fabricated. Latent
# for as long as nothing sat that close to them, and the moment the decoupling
# capacitors moved up against the packages it reported two overlaps that are not
# on the board and would have hidden any that were. Same function as the placer
# now, so the two cannot disagree about geometry again.
boxes = []
for ref, _v, _s, lib, fp, _p, _hx, _hy in nl.PARTS:
    x, y = _settled[ref]
    x0, x1, y0, y1 = pl._box_for(
        ref, lib, fp, lambda l, f: open(pcb.footprint_path(l, f)).read(),
        nl.ROTATION)
    boxes.append((ref, x + x0, x + x1, y + y0, y + y1, ref in nl.BACK))
# ⚠️ TWO PARTS ON OPPOSITE SIDES OF THE BOARD DO NOT COLLIDE, and the moment
# anything went on the back this test said the processor overlapped all four of
# its own decoupling capacitors. A courtyard is a keep-out on ONE side.
overlap = [(boxes[i][0], boxes[j][0])
           for i in range(len(boxes)) for j in range(i + 1, len(boxes))
           if boxes[i][5] == boxes[j][5]
           and boxes[i][1] < boxes[j][2] and boxes[j][1] < boxes[i][2]
           and boxes[i][3] < boxes[j][4] and boxes[j][3] < boxes[i][4]]
check("no two courtyards overlap", not overlap, str(overlap))
# ⛔ THREE ISLANDS, NOT ONE, AND NOTHING ON THE FLEX. The board is a 196 mm strip
# with two 30 mm flex tails in it; a package soldered across a section that bends
# does not stay soldered. An earlier placement pass put a 24-way connector and a
# row of resistors out over a tail, and off the board edge with them.
outside = [r for r, x0, x1, y0, y1, _back in boxes
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
# ⛔ THE HEADROOM IS THE COIL'S NOW, NOT THE CELL'S. While the coil sat directly
# under the LiPo they were the same calculation: whatever the coil reached, the
# cell reached. dimensions.py now puts them side by side, so the cell rides at
# ambient and the thing with a temperature worth limiting is the coil face
# against the leather — 45 °C, without the cell's 5 K design margin, because
# nothing there is a cell.
_head = _th.CELL_LIMIT_C - _th.AMBIENT
_safe_w = (_head / (_r + 1 / (8.0 * _area))) / (1 - _th.QI_EFFICIENCY)

# ⛔ AND THE BANDS COME FROM THE CELL, NOT FROM A MEMORY OF LITHIUM. They were
# 0/10/40/45 — reasonable for a cell nobody had picked, and wrong by 5 K in both
# directions once one was. The cell is Jauch LP523450JU and its datasheet states
# its own table; this is the only place the two can be compared.
sys.path.insert(0, os.path.join(ROOT, "hardware"))
import bom as _bom                                                # noqa: E402

_cell = _bom.BOM["BT1"]
check("the JEITA bands are the cell's own",
      (_cdef("SB_JEITA_COLD_C"), _cdef("SB_JEITA_COOL_C"),
       _cdef("SB_CELL_LIMIT_C"), _cdef("SB_CELL_ABS_MAX_C"))
      == _cell["charge_bands_c"],
      f"firmware {(_cdef('SB_JEITA_COLD_C'), _cdef('SB_JEITA_COOL_C'), _cdef('SB_CELL_LIMIT_C'), _cdef('SB_CELL_ABS_MAX_C'))} "
      f"vs datasheet {_cell['charge_bands_c']}")
check("the charge currents are the cell's own",
      (_cdef("SB_CELL_FULL_MA"), _cdef("SB_CELL_REDUCED_MA"),
       _cdef("SB_CELL_CAPACITY_MAH"))
      == (_cell["full_ma"], _cell["reduced_ma"], _cell["capacity_mah"]),
      f"firmware {(_cdef('SB_CELL_FULL_MA'), _cdef('SB_CELL_REDUCED_MA'), _cdef('SB_CELL_CAPACITY_MAH'))} "
      f"vs datasheet {(_cell['full_ma'], _cell['reduced_ma'], _cell['capacity_mah'])}")
check("the full-current ceiling is 1.0 C, as the datasheet allows",
      _cell["full_ma"] == _cell["capacity_mah"] * 1000 // 950,
      f"{_cell['full_ma']} mA against {_cell['capacity_mah']} mAh")

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

# ⛔ KICAD WARNS THAT THE BOARD'S A121 DOES NOT MATCH THE LIBRARY, AND IT IS
# RIGHT ABOUT THE BYTES. generate_pcb.py re-serialises every footprint as it
# writes it into the board, so the one footprint this project draws itself comes
# out formatted differently from the .kicad_mod it was read from, and the
# lib_footprint_mismatch check compares them and complains. Twice, once per
# radar.
#
# ⚠️ A warning that is expected is a warning nobody reads, and the next one will
# be real. What that check exists to catch is a library edit that never reached
# the board — so the property it actually cares about is asserted here instead,
# against the file on disk: same pad names, same positions, same sizes, same
# layers. Fifty balls, to three decimal places.
print("\n── the board's own footprint still matches the library it came from")


def _pads(text):
    out = {}
    for m in re.finditer(
            r'\(pad "([^"]*)"\s+(\S+)\s+(\S+)[^(]*\(at ([-\d.]+) ([-\d.]+)'
            r'[^)]*\)\s*\(size ([-\d.]+) ([-\d.]+)\)\s*\(layers ([^)]*)\)',
            text, re.S):
        name, typ, shape, x, y, w, h, layers = m.groups()
        out[name] = (typ, shape, round(float(x), 3), round(float(y), 3),
                     round(float(w), 3), round(float(h), 3),
                     tuple(sorted(layers.split())))
    return out


_libfp = os.path.join(ROOT, "hardware", "footprints", "SmartBag.pretty",
                      "Acconeer_A121_fcCSP50.kicad_mod")
_lib_pads = _pads(open(_libfp).read())
_pcb_text = open(os.path.join(ROOT, "hardware", "smartbag_core.kicad_pcb")).read()
_i = _pcb_text.find("Acconeer_A121_fcCSP50")
_j = _pcb_text.rfind("(footprint", 0, _i)
_d, _k = 0, _j
while True:
    if _pcb_text[_k] == "(":
        _d += 1
    elif _pcb_text[_k] == ")":
        _d -= 1
    _k += 1
    if _d == 0:
        break
_board_pads = _pads(_pcb_text[_j:_k])
check("the A121 on the board has the library's 50 balls",
      len(_board_pads) == len(_lib_pads) == 50,
      f"library {len(_lib_pads)}, board {len(_board_pads)}")
_diff = [n for n in _lib_pads if _lib_pads[n] != _board_pads.get(n)]
check("every ball matches name, position, size and layers",
      not _diff, f"{len(_diff)} differ: {_diff[:4]}")

# ⛔ A PIN MAP THAT HAS DRIFTED IS A BOARD AND AN IMAGE THAT DISAGREE, and the
# only symptom is a peripheral that does not answer. firmware/target/src/
# sb_pinmap.h is generated from netlist.py; if regenerating it would change
# anything, somebody has edited one of the two and not the other.
# ⛔ THE RESONANT CAPACITORS ARE COMPUTED IN ONE FILE AND FITTED IN ANOTHER, and
# nothing joined them until the coil changed. hardware/qi_resonance.py derives Cs
# and Cd from the coil's inductance and WPC's 100 kHz and 1 MHz; netlist.py has
# two capacitors with values typed into them. Swapping the coil for one that is
# actually in a catalogue moved the inductance from 8.8 to 12 µH — and would have
# left a tank tuned for a coil nobody could buy.
print("\n── the Qi tank is tuned for the coil that is fitted")

sys.path.insert(0, os.path.join(ROOT, "hardware"))
import qi_resonance as _qi                                        # noqa: E402
import netlist as _nl2                                            # noqa: E402

_want_cs, _want_cd = _qi.preferred()
_fitted = {p[0]: p[1] for p in _nl2._PASSIVES}
_cs = _fitted.get("C80", "")
_cd = _fitted.get("C81", "")
check("Cs on the board is what the coil asks for",
      _cs.startswith(_want_cs), f"board {_cs!r}, computed {_want_cs}")
check("Cd on the board is what the coil asks for",
      _cd.startswith(_want_cd), f"board {_cd!r}, computed {_want_cd}")
check("the coil in the BOM is the one the resonance was computed from",
      _bom.BOM["L_COIL"]["mpn"] == _qi.COIL_MPN,
      f"BOM {_bom.BOM['L_COIL']['mpn']}, resonance {_qi.COIL_MPN}")

print("\n── the firmware's pin map is still the schematic's")

_pm = os.path.join(ROOT, "firmware", "target", "src", "sb_pinmap.h")
_ov = os.path.join(ROOT, "firmware", "target", "boards", "smartbag.overlay")
_before = {f: open(f).read() for f in (_pm, _ov) if os.path.exists(f)}
subprocess.run([sys.executable, os.path.join(ROOT, "hardware",
                                             "generate_pinmap.py")],
               capture_output=True)
_pm_ok = os.path.exists(_pm) and _before.get(_pm) == open(_pm).read()
_ov_ok = os.path.exists(_ov) and _before.get(_ov) == open(_ov).read()
check("sb_pinmap.h matches netlist.py", _pm_ok,
      "" if _pm_ok else "regenerating it changes it — one of the two was edited")
check("the devicetree overlay matches the netlist and the cell", _ov_ok,
      "" if _ov_ok else "regenerating it changes it — one of the two was edited")

# ⚠️ And it has to compile. The generator writes C; a designator with a stray
# character in it produces a header that looks fine and fails on the target,
# which is the worst place to find out.
_probe = """#include "sb_pinmap.h"
int main(void){return sb_pinmap[SB_PIN_HALL].port+sb_cs_pins[0].pin
 +sb_mux_sel[0].pin+sb_adc_rows[5].pin+SB_MUX_EN_PIN+SB_SCK_PIN;}"""
_cc = subprocess.run(["cc", "-std=c99", "-Wall", "-Wextra", "-Werror",
                      "-I", os.path.join(ROOT, "firmware"),
                      "-I", os.path.dirname(_pm), "-fsyntax-only", "-x", "c", "-"],
                     input=_probe, text=True, capture_output=True)
check("the generated pin map compiles with -Werror", _cc.returncode == 0,
      _cc.stderr.strip().splitlines()[0] if _cc.stderr.strip() else "")

print("\n── every supply pin has a capacitor next to it")
# ⛔ THE CHECK THAT SHOULD HAVE EXISTED BEFORE THE FIRST ROUTE. netlist.py's
# PLACEMENT table used to say, in as many words, "THE 100 nF PARTS HUG THE PINS
# THEY DECOUPLE... the QFN has VDD on all four sides, so there is a capacitor on
# all four sides" — and then named C5 as the one on the top edge, which is
# 2.2 nF on DECRF and not a supply capacitor at all. U1 pins 47 and 48 never had
# one, U7 never had one, and the three by the amplifiers sat eleven millimetres
# away in a tidy row. Nothing noticed, because a comment is not a check.
#
# ⭐ PAD TO PAD, FROM THE SETTLED POSITIONS AND THE FOOTPRINTS. Part centres
# would call a pin on the far side of a nine-millimetre package nine millimetres
# from its own capacitor; what decides the loop inductance is where the copper
# is. Both ends come out of place.pad_at(), which is the same function the
# placement uses, so the check cannot disagree with the placer about geometry.
#
# ⚠️ 2 mm IS ALREADY GENEROUS. Nordic's layout guidance puts the 100 nF within
# about a millimetre of the pin with its own via to ground. This asserts the
# generous number so that a failure is a defect and not a preference.
DECOUPLE_MM = 2.0

def _cap_pad_distance(cap, ic, pin):
    """Closest pad-to-pad millimetres between a capacitor and one IC pin."""
    libs = {p[0]: (p[3], p[4]) for p in nl.PARTS}
    text = lambda r: open(pcb.footprint_path(*libs[r])).read()
    target = pl.pad_at(text(ic), pin, _settled[ic], nl.ROTATION.get(ic, 0))
    if target is None:
        return None
    best = None
    for num in ("1", "2"):
        at = pl.pad_at(text(cap), num, _settled[cap], nl.ROTATION.get(cap, 0))
        if at is None:
            continue
        d = ((at[0] - target[0]) ** 2 + (at[1] - target[1]) ** 2) ** 0.5
        best = d if best is None else min(best, d)
    return best

_far, _broken = [], []
for _cap, (_ic, _pin) in sorted(nl.DECOUPLE.items()):
    _d = _cap_pad_distance(_cap, _ic, _pin)
    if _d is None:
        _broken.append(f"{_cap}->{_ic}.{_pin}")
    elif _d > DECOUPLE_MM:
        _far.append((_d, _cap, _ic, _pin))
_far.sort(reverse=True)
check("every DECOUPLE pair names a pad that exists", not _broken,
      f"{len(_broken)} do not: {', '.join(_broken)}")
check(f"every decoupling capacitor is within {DECOUPLE_MM:.0f} mm of its pin",
      not _far,
      f"{len(_far)} of {len(nl.DECOUPLE)} are not — "
      + ", ".join(f"{c}->{i}.{p} {d:.2f} mm" for d, c, i, p in _far[:4]))

# ⛔ AND THE OTHER HALF: a rail with no capacitor anchored to it at all is how
# U7 went twenty-six millimetres without anyone noticing. Every IC pin on a
# supply net has to be covered by SOME entry in DECOUPLE for its part.
SUPPLY_NETS = {"VDD_3V3", "VSYS", "VDD_1V8", "VDDIO", "VBAT", "VREF"}
_covered = {(ic, nl.part(ic) and None) for ic, _ in nl.DECOUPLE.values()}
_by_ic = {}
for _cap, (_ic, _pin) in nl.DECOUPLE.items():
    _by_ic.setdefault(_ic, set()).add(_pin)
_uncovered = []
for _part in nl.PARTS:
    _ref, _v, _sym, _lib, _fp, _pins, _x, _y = _part
    if not _ref.startswith("U"):
        continue
    _rails = {net for _n, _pn, _t, net in _pins if net in SUPPLY_NETS}
    if not _rails:
        continue
    _anchored = _by_ic.get(_ref, set())
    _anchored_rails = {net for _n, _pn, _t, net in _pins
                       if _n in _anchored or str(_n) in _anchored}
    _miss = _rails - _anchored_rails
    if _miss:
        _uncovered.append(f"{_ref} ({', '.join(sorted(_miss))})")
check("every IC rail has a capacitor anchored to it", not _uncovered,
      f"{len(_uncovered)} without one: {'; '.join(_uncovered)}")

print("\n── and every decoupling capacitor has a way back to ground")
# ⛔ HALF A DECOUPLING FIX IS NOT A FIX. The distance check above passed on a
# board where C7 — the processor's own decoupling on pin 22 — had its ground
# terminal on a 0.69 mm2 island of pour with no via in it. One millimetre to the
# supply pin and no return at all. The loop is what sets the inductance and the
# loop is BOTH sides, so measuring one of them and declaring the job done is how
# a board passes its own checks and does not work.
#
# ⚠️ AND THE FIRST FIX CAUSED THIS ONE. Putting the capacitors hard against the
# packages is exactly what pinches the pour off around them — the escape routing
# runs between package and capacitor and cuts the ground it used to sit on.
# ⛔ TWO WRITERS, TWO DIALECTS, AND A CHECK THAT ONLY KNEW ONE. generate_pcb.py
# writes a via's net as a NUMBER — `(net 3)` — because that is what it has;
# KiCad's own writer, which touches the file again the moment anything runs
# pcbnew on it, writes the NAME: `(net "GND")`. A regex that knows one of those
# finds no vias at all on a board written by the other, and "no vias" reads here
# as "no returns", which is the same shape as a real defect. Both forms, and a
# hard failure if neither matches anything, because a check that silently sees
# an empty board is worse than no check.
_via_re = re.compile(
    r'\(via\s+\(at ([-\d.]+) ([-\d.]+)\)(.*?)\(net (?:(\d+)|"([^"]*)")\)', re.S)
_pcb_now = open(os.path.join(ROOT, "hardware", "smartbag_core.kicad_pcb")).read()
_by_code = {int(m.group(1)): m.group(2)
            for m in re.finditer(r'\(net (\d+) "([^"]*)"\)', _pcb_now)}
_gnd_vias = []
for _a, _b, _mid, _num, _name in _via_re.findall(_pcb_now):
    _net = _name if _name else _by_code.get(int(_num), "")
    if _net == "GND":
        _gnd_vias.append((float(_a), float(_b)))
check("the board file's vias can still be read", bool(_gnd_vias),
      "no ground vias found at all — the board's s-expression dialect has "
      "changed and this check is looking at nothing")

RETURN_MM = 1.0
_no_return = []
for _cap in sorted(nl.DECOUPLE):
    # ⭐ A CAPACITOR ON THE BACK NEEDS NO RETURN VIA AND THAT IS THE POINT OF IT
    # BEING THERE. Its ground terminal lands on the bottom ground pour; the
    # return path is the plane it is soldered to. Asking it for a via as well
    # would be asking for a second connection to something it is already on —
    # and a through via under a QFN is not free: four of them, one per pad,
    # produced five shorts and two coincident drill holes. See flip_back.py.
    if _cap in nl.BACK:
        continue
    _nets = nl.pad_nets(_cap)
    _gnd_pin = next((n for n, net in _nets.items() if net == "GND"), None)
    if _gnd_pin is None:
        continue
    _libs = {p[0]: (p[3], p[4]) for p in nl.PARTS}
    _at = pl.pad_at(open(pcb.footprint_path(*_libs[_cap])).read(), _gnd_pin,
                    _settled[_cap], nl.ROTATION.get(_cap, 0))
    if _at is None:
        continue
    # ⚠️ Board coordinates, not the netlist's local frame: the vias above come
    # out of the board file. U1's settled position is the bridge between them.
    _ox = 210.0
    _oy = 148.0
    _bx, _by = _at[0] + _ox, _at[1] + _oy
    _d = min((((_bx - vx) ** 2 + (_by - vy) ** 2) ** 0.5 for vx, vy in _gnd_vias),
             default=None)
    if _d is None or _d > RETURN_MM:
        _no_return.append((_cap, _d))
check(f"every decoupling capacitor has a ground via within {RETURN_MM:.0f} mm "
      "of its return pad", not _no_return,
      f"{len(_no_return)} of {len(nl.DECOUPLE)} do not — "
      + ", ".join(f"{c} ({d:.2f} mm)" if d else f"{c} (none)"
                  for c, d in _no_return[:5]))

print("\n── every named part has a price against it")
# ⛔ "A BOM IS NOT AN ORDER" AND THIS IS THE LINE BETWEEN THEM. Every entry here
# is a real part with a datasheet whose package was measured against it; that
# says nothing about what it costs or whether it exists this week. Fifteen of
# the twenty-seven lines had no price at all until they were looked up one at a
# time, and a list that quietly goes back to fourteen is a list nobody can send
# to a distributor.
_unpriced = [ref for ref, e in list(_bom.BOM.items()) + list(_bom.OPTICS.items())
             if not (e.get("usd10") or e.get("usd1") or e.get("usd"))]
check("every named line carries a distributor price", not _unpriced,
      f"{len(_unpriced)} without one: {', '.join(_unpriced)}")
_undated = [ref for ref, e in list(_bom.BOM.items()) + list(_bom.OPTICS.items())
            if (e.get("usd1") or e.get("usd10")) and not e.get("quoted")]
check("and says when it was quoted", not _undated,
      f"{len(_undated)} priced with no date: {', '.join(_undated)}")

print("\n── the fuel gauge agrees with the cell it is gauging")
# ⛔ THE OLD GAUGE WAS A STRAIGHT LINE AND THE CELL'S OWN DATASHEET REFUTES IT.
# "Delivery State of Charge: Max. 30% (3.75-3.79V); Optional 60% (3.85-3.95V)"
# is two points on this cell's discharge curve, and a linear 3.0-4.2 V map reads
# the first of them as 64%. This checks that the curve in the firmware still has
# the cell's numbers in it and that the ends are the cell's ends.
_pwr_h = open(os.path.join(ROOT, "firmware", "sb_power.h")).read()
_pwr_c = open(os.path.join(ROOT, "firmware", "sb_power.c")).read()
_cell = _bom.BOM["BT1"]
check("the gauge's empty and full are the cell's cut-off and charge ceiling",
      "#define SB_CELL_EMPTY_MV 3000" in _pwr_h
      and "#define SB_CELL_FULL_MV 4200" in _pwr_h,
      "the endpoints have moved away from the datasheet's 3.0 / 4.2 V")
check("the pack impedance is the datasheet's 180 mOhm",
      "#define SB_CELL_IMPEDANCE_MOHM 180" in _pwr_h, "not 180")
_pts = re.findall(r"\{ (\d+), (\d+) \}", _pwr_c)
check("the curve still carries both delivery states",
      ("3770", "30") in [(a, b) for a, b in _pts]
      and ("3900", "60") in [(a, b) for a, b in _pts],
      f"points found: {_pts}")
check("and the cell it was read from is still the cell in the BOM",
      _cell["mpn"].startswith("LP523450JU"),
      f"BOM cell is {_cell['mpn']} — the curve above is not its curve")

print("\n── the camera the model was trained for is the camera that is fitted")
# ⛔ THREE FILES HAD TO AGREE ABOUT ONE NUMBER AND TWO OF THEM WERE WRONG.
# ml/classify.py trains at 96x96 grey; ml/inference_budget.py charged the SPI
# burst at one byte a pixel; firmware/sb_camera.c reads the Arducam Mega's own
# register table, where the format register offers JPEG, RGB and YUV and no
# grey at all. The budget was out by exactly a factor of two and nothing said
# so, because the frame size lived separately in each file.
_cam_h = open(os.path.join(ROOT, "firmware", "sb_camera.h")).read()
_cam_w = int(re.search(r"#define SB_CAM_W (\d+)", _cam_h).group(1))
_cam_hh = int(re.search(r"#define SB_CAM_H (\d+)", _cam_h).group(1))
_infer = open(os.path.join(ROOT, "ml", "inference_budget.py")).read()
_infer_px = int(re.search(r"^INPUT = (\d+)", _infer, re.M).group(1))
check("the driver captures the size the model was trained on",
      _cam_w == _cam_hh == _infer_px,
      f"driver {_cam_w}x{_cam_hh}, model {_infer_px}x{_infer_px}")

# The first camera mode in the budget is the one the driver actually uses, and
# it has to be two bytes a pixel because the module cannot send fewer.
_mode = re.search(r'CAM_MODES = \[\s*\("([^"]+)",\s*(\d+) \* (\d+) \* (\d+)\)',
                  _infer)
check("the budget charges the burst at the wire format, not the model's",
      _mode is not None and int(_mode.group(4)) == 2,
      f"{_mode.group(1) if _mode else '?'} at "
      f"{_mode.group(4) if _mode else '?'} bytes/pixel — RGB565 is 2")
check("and at the resolution the driver asks the module for",
      _mode is not None and int(_mode.group(2)) == _cam_w
      and int(_mode.group(3)) == _cam_hh,
      f"budget {_mode.group(2)}x{_mode.group(3)}" if _mode else "no mode found")

# ⚠️ 8 MHz is the module's ceiling and it is quoted in two files.
_bom_cam = _bom.OPTICS["CAM"]["verdict"]
_infer_mhz = float(re.search(r"CAM_SPI_MHZ = ([\d.]+)", _infer).group(1))
check("the SPI ceiling in the budget is the one the BOM quotes",
      f"{_infer_mhz:.0f} MHz" in _bom_cam,
      f"budget {_infer_mhz:.0f} MHz; BOM says: {_bom_cam[:60]}...")

print("\n── the illuminators are charged for the time they are actually on")
# ⛔ 600 mW, AND THE BUDGET USED TO CHARGE IT FOR ONE FRAME OUT OF THREE. The
# camera term covers the whole burst; part of that is the exposure, which needs
# light, and part is an already-taken image crossing an 8 MHz bus, which does
# not. The illuminator term has to be the first part, and the split is a
# property of the firmware — sb_sense.c drops the pin between sb_cam_expose and
# sb_cam_fetch — so this reads both files rather than trusting either.
_budget = open(os.path.join(ROOT, "thermal", "budget.py")).read()
def _duty(name):
    """The seconds-per-event a budget line charges. ⚠️ The power column is an
    expression ("0.136 * 3.3") often enough that parsing it is not worth it;
    what this check is about is the duration."""
    m = re.search(r'\("' + re.escape(name) + r'",[^,]+,\s*([\d.]+),\s*(\d+)\)',
                  _budget)
    return float(m.group(1)) if m else None

_cam_s = _duty("camera burst (J1)")
_led_s = _duty("IR illuminators")
_frames = int(re.search(r"#define SB_CAPTURE_FRAMES (\d+)",
                        open(os.path.join(ROOT, "firmware", "smartbag.h")).read()
                        ).group(1))
_transfer_s = _frames * (_cam_w * _cam_hh * 2) * 8 / (_infer_mhz * 1e6)
check("the illuminator window is the camera window minus the transfer",
      _led_s is not None and abs(_led_s - (_cam_s - _transfer_s)) < 0.005,
      f"charged {_led_s:.3f} s; camera {_cam_s:.3f} s minus "
      f"{_transfer_s:.3f} s of SPI = {_cam_s - _transfer_s:.3f} s")

_sense_c = open(os.path.join(ROOT, "firmware", "sb_sense.c")).read()
_expose_at = _sense_c.find("sb_cam_expose")
_led_off_at = _sense_c.find("SB_PIN_IR_LED_EN, SB_PIN_LOW")
_fetch_at = _sense_c.find("sb_cam_fetch")
check("and the firmware drops the pin before it fetches the frame",
      -1 < _expose_at < _led_off_at < _fetch_at,
      f"expose@{_expose_at} led-off@{_led_off_at} fetch@{_fetch_at}")

print("\n── something calls sb_feed")
# ⛔ THE HOLE THIS PROJECT HAD FOR MOST OF ITS LIFE. Every decision the bag makes
# hangs off sb_feed(), which was written, tested to 378 assertions, and never
# called: the image booted, advertised, charged, answered a phone, and reported
# an empty bag forever. A check that the loop exists is worth more than any
# number of assertions about what it would do.
_main_c = open(os.path.join(ROOT, "firmware", "target", "src", "main.c")).read()
_cmake = open(os.path.join(ROOT, "firmware", "target", "CMakeLists.txt")).read()
check("the target's main loop steps the sensing loop",
      "sb_sense_step(" in _main_c, "main.c never calls it")
check("and the sensing loop's events reach sb_feed",
      "sb_feed(" in _main_c, "nothing in main.c feeds the state machine")
for _src in ("sb_sense.c", "sb_camera.c"):
    check(f"{_src} is in the image", f"../{_src}" in _cmake,
          "not in target/CMakeLists.txt, so it is tested and not shipped")

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
    "render/views/press.png": ["cad/bag_and_insert.py", "dimensions.py",
                                 "render/scenes.py",
                                 "hardware/smartbag_core.kicad_pcb"],
    "render/views/section.png": ["cad/bag_and_insert.py", "dimensions.py",
                                 "render/scenes.py",
                                 "hardware/smartbag_core.kicad_pcb"],
    "render/views/collar.png": ["dimensions.py", "render/scenes.py",
                                "hardware/optics_netlist.py"],
    "render/views/exploded.png": ["cad/bag_and_insert.py", "dimensions.py",
                                  "render/scenes.py",
                                  "hardware/smartbag_core.kicad_pcb"],
    "media/smartbag_discovery.mp4": ["render/animation.py", "render/scenes.py",
                           "dimensions.py"],
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
