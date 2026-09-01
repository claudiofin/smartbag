#!/usr/bin/env python3
"""SmartBag — the animated shots. Run it FROM Blender.

⭐ REUSES `scenes`, it does not copy it. Materials, lights, STL import, loading
the board from GLB, the section cut and the camera rig are already written and
already tuned there. What gets added here is the only thing the stills do not
have: time — moving cameras, the section opening up, layers separating, taxels
lighting in a wave.

⛔ NO 3D CALLOUTS IN VIDEO. In the stills the text is geometry pulled in front of
the model; with the camera moving it would have to be reoriented every frame and
the leader lines would crawl across the model. The film's captions are composited
afterwards, in `render/build_video.py`, where fades and legibility can be
controlled.

Usage:
  blender -b --python render/animation.py -- <shot> [--width 1600]
                                             [--from 1] [--to 0] [--samples 32]
Shots: opening  exploded  scanning  unzip  object_drop
"""
import math
import os
import sys

import bpy
import mathutils

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import scenes as sc          # noqa: E402

FPS = 24
OUT = os.path.join(sc.ROOT, "render", "anim")

LENGTH = {"opening": 120, "exploded": 168, "scanning": 144,
          "unzip": 120, "object_drop": 144}


def parse_args():
    a = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    # ⚠️ Flags that take no value must say so, or the argument after them is
    # swallowed as if it were theirs — the same trap render/scenes.py fell into.
    BARE = {"--vertical"}
    free, skip = [], False
    for x in a:
        if skip:
            skip = False
        elif x.startswith("-"):
            skip = x not in BARE
        else:
            free.append(x)

    def val(n, d):
        return int(a[a.index(n) + 1]) if n in a else d
    return (free[0] if free else "opening", val("--width", 1600),
            val("--samples", 32), val("--threads", 5), val("--from", 1),
            val("--to", 0), "--vertical" in a)


# ══ time tools ═══════════════════════════════════════════════════════════════
def keys(obj, path, values):
    """`values` = [(frame, value), ...]. Interpolated with ease in and out: a
    linear move in a product film reads as a technical animation, not as a
    camera."""
    for f, v in values:
        if isinstance(v, (tuple, list)):
            setattr(obj, path, mathutils.Vector(v)
                    if path != "rotation_euler" else mathutils.Euler(v))
        else:
            setattr(obj, path, v)
        obj.keyframe_insert(data_path=path, frame=f)
    smooth_keys(obj)


def smooth_keys(obj):
    """Set every keyframe to Bezier with ease in/out.

    ⛔ `action.fcurves` NO LONGER EXISTS. Since Blender 4.4 actions are layered
    and slotted: the curves live in
    `action.layers[..].strips[..].channelbag(slot)` and the flat accessor was
    removed in 5.0 — the first version failed with
    `'Action' object has no attribute 'fcurves'`.
    """
    ad = getattr(obj, "animation_data", None)
    if ad is None and hasattr(obj, "id_data"):
        ad = getattr(obj.id_data, "animation_data", None)
    if not ad or not ad.action:
        return
    for layer in ad.action.layers:
        for strip in layer.strips:
            cb = strip.channelbag(ad.action_slot)
            if cb is None:
                continue
            for fc in cb.fcurves:
                for kp in fc.keyframe_points:
                    kp.interpolation = "BEZIER"
                    kp.easing = "EASE_IN_OUT"


def camera_pose(aim, distance, azimuth, elevation):
    a, e = math.radians(azimuth), math.radians(elevation)
    m = mathutils.Vector(aim)
    p = m + mathutils.Vector((distance * math.cos(e) * math.cos(a),
                              distance * math.cos(e) * math.sin(a),
                              distance * math.sin(e)))
    return p, (m - p).to_track_quat("-Z", "Y").to_euler()


def camera_move(stops, focal=78):
    """Animated camera. `stops` = [(frame, aim, distance, azimuth, elevation)].

    ⚠️ Position AND rotation are keyed explicitly instead of using a Track To
    constraint: the constraint chases the target every frame and on close
    passes produces an orientation snap that EEVEE does not show in the
    viewport but that is glaring in the finished film.
    """
    c = bpy.data.cameras.new("cam")
    c.lens = focal
    o = bpy.data.objects.new("cam", c)
    bpy.context.collection.objects.link(o)
    bpy.context.scene.camera = o
    pos, rot = [], []
    for f, aim, d, az, el in stops:
        p, r = camera_pose(aim, d, az, el)
        pos.append((f, p))
        rot.append((f, r))
    keys(o, "location", pos)
    keys(o, "rotation_euler", rot)
    return o


def animated_cutter(cutter, offsets):
    """Animate the section cutter through a parent empty.

    ⛔ ANIMATING THE CUTTER DIRECTLY DOES NOT WORK. Measured on Blender 5.2:
    with the exact same keys, the evaluated bag goes from 7705 vertices (cut) to
    10378 (intact) the moment the boolean's operand object gets an action of its
    own — with the EXACT solver and with FLOAT alike. The modifier is there, it
    points at the right object, the evaluated matrix is right, and the cut still
    does not apply.
    ⭐ Moving the animation onto a parent EMPTY makes the boolean evaluate
    again: the operand stays static and its parent moves. `offsets` are
    displacements relative to the cutter's rest pose.
    """
    pivot = bpy.data.objects.new("cut_pivot", None)
    bpy.context.collection.objects.link(pivot)
    cutter.parent = pivot
    keys(pivot, "location", offsets)
    return pivot


def place_neck(m, closed, slider_x):
    """Soft neck + zip, in the given state. `closed` runs 0 (gaping) to 1.

    ⛔ REPLACES the earlier helper that rotated two rigid flaps about a hinge.
    See the comment at the top of `neck_zip` in scenes.py: that motion is a
    hatch, and no pose rescues it. Here the neck changes shape and the teeth
    separate.
    """
    neck, teeth, slider, shape_keys = sc.neck_zip(m)
    for k in shape_keys:
        k.value = closed
    slider.location.x = slider_x * sc.MM
    return neck, teeth, slider, shape_keys


def place_optics(m):
    """Camera module + illuminators + ToF, with the lenses split by material.

    ⛔ IT EXISTS BECAUSE THE CAMERA COULD NOT BE SEEN. Before, a pink cone came
    out of a hole in the microfibre: a sensor you cannot see is a sensor nobody
    understands, and the camera at the mouth is the part that does the
    recognition — the thing the project promises. Now there is a module, with
    its lens, and the four illuminators fire at the instant of the snapshot.

    Returns (body, camera_lens, leds, tof_lens).
    """
    body = sc.load_stl("optics_body", m["optics"], sc.Z_INSERT)
    lenses = sc.load_stl("optics_lenses", m["dark_glass"], sc.Z_INSERT)
    bpy.ops.object.select_all(action="DESELECT")
    lenses.select_set(True)
    bpy.context.view_layer.objects.active = lenses
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="SELECT")
    bpy.ops.mesh.separate(type="LOOSE")
    bpy.ops.object.mode_set(mode="OBJECT")
    pieces = [o for o in bpy.context.selected_objects if o.type == "MESH"]
    # ⚠️ The lenses are told apart by POSITION, not by order: `separate` gives no
    # guarantee about the sequence the loose parts come out in.
    camera, leds, tof = None, [], None
    for o in pieces:
        x = o.matrix_world.translation.x / sc.MM
        if abs(x + 20) < 6:
            camera = o
        elif abs(x - 48) < 6:
            tof = o
        else:
            leds.append(o)
    return body, camera, leds, tof


def beam_cone(name, from_mm, to_mm, r0, r1, material):
    """Conical beam between two points given in scene millimetres."""
    p = mathutils.Vector(from_mm) * sc.MM
    a = mathutils.Vector(to_mm) * sc.MM
    d = a - p
    bpy.ops.mesh.primitive_cone_add(radius1=r0, radius2=r1, depth=d.length,
                                    vertices=48)
    c = bpy.context.object
    c.name = name
    c.location = p + d / 2
    c.rotation_euler = d.to_track_quat("Z", "Y").to_euler()
    sc.assign(c, material)
    return c


def indicator(name, point_mm, radius, material):
    bpy.ops.mesh.primitive_uv_sphere_add(radius=radius, segments=24, ring_count=12)
    o = bpy.context.object
    o.name = name
    o.location = mathutils.Vector(point_mm) * sc.MM
    sc.assign(o, material)
    return o


def emission(material, values):
    """Animate the emission strength of a Principled material."""
    b = material.node_tree.nodes["Principled BSDF"]
    i = b.inputs["Emission Strength"]
    for f, v in values:
        i.default_value = v
        i.keyframe_insert(data_path="default_value", frame=f)
    smooth_keys(material.node_tree)


def _load_section_set(m):
    """The parts every section shot loads. Returns the cuttable ones."""
    cuttable = []
    # ⛔ THE HANDLES WERE THE ONE THING THE SECTION DID NOT CUT. Everything else
    # in the shot is passed to the cutter and the handles were loaded beside it,
    # so the front strap stayed whole and ran straight through the opening the
    # cut had just made — a leather loop passing through leather. A section
    # plane goes through whatever is in its way, handles included.
    for name, k in (("bag_body", "leather"), ("bag_hardware", "gold"),
                    ("insert_walls", "microfibre"),
                    ("insert_collar", "microfibre"),
                    ("insert_base", "microfibre"),
                    ("insert_floor", "fsr_film"), ("fsr_cable", "polyimide"),
                    ("bag_handles", "leather")):
        dz = 0 if name.startswith("bag") else sc.Z_INSERT
        cuttable.append(sc.load_stl(name, m[k], dz))

    sc.load_stl("battery", m["lipo"], sc.Z_INSERT)
    sc.load_stl("qi_coil", m["copper"], sc.Z_INSERT - 6)
    sc.load_stl("insert_dividers", m["microfibre_dark"], sc.Z_INSERT)
    return cuttable


# ══ shot 1 — the bag opens in section ════════════════════════════════════════
def opening(m, n):
    """The closed bag opening up: the front-right quarter retracts.

    ⛔ THE CUT IS AN OBJECT THAT MOVES, not a part that fades away. Dissolving
    the panel would have been cheaper, but a boolean that moves leaves the cut
    surfaces CLOSED frame by frame: you see the thickness of the leather and of
    the layers as it opens, which is exactly the information this shot exists
    for.
    """
    cuttable = _load_section_set(m)
    fsr = sc.load_stl("fsr_matrix", m["taxel_off"], sc.Z_INSERT)
    sc.light_taxels(fsr, m)
    sc.place_contents(m)
    sc.load_board((0, sc.SEAT_Y, sc.Z_BOARD))
    place_optics(m)
    # The zip is here too, open: both films have to show the same bag.
    neck, teeth, slider, _ = place_neck(m, 0.0, 138.0)
    cuttable += [neck, teeth, slider]
    cutter = sc.section_cut(cuttable, (0.22, -0.22, 0.12), (0.44, 0.44, 0.50))

    # ⛔ THE TRAVEL HAS TO BE COMPUTED, not eyeballed. The cutter is 0.44 m deep:
    # it makes contact when its back face (centre + 0.22) reaches the front of
    # the bag, i.e. at centre = −0.2775, and finishes at −0.22 where the cut
    # reaches the mid-plane. That is 57.5 mm of useful travel — exactly half the
    # depth of the bag. The first version started at −0.62: for two thirds of
    # the shot the cutter travelled through empty air and the bag stayed shut
    # almost to the end.
    animated_cutter(cutter, [(1, (0, -0.0610, 0)), (26, (0, -0.0610, 0)),
                             (104, (0, 0, 0)), (n, (0, 0, 0))])

    sc.backdrop(m)
    sc.light("key", (0.75, -0.95, 0.95), 80, 1.5, (0, 0, 0.12))
    sc.light("fill", (-0.95, -0.55, 0.45), 24, 2.0, (0, 0, 0.10),
             colour=(0.78, 0.84, 1.0))
    sc.light("rim", (-0.25, 0.90, 0.80), 42, 1.2, (0, 0, 0.18),
             colour=(1.0, 0.88, 0.74))
    interior = sc.light("interior", (0.09, -0.05, 0.235), 4.5, 0.10,
                        (0.02, 0.0, 0.05), colour=(1.0, 0.93, 0.86))
    # The interior light only comes up once there is an interior to light.
    keys(interior.data, "energy", [(1, 0.0), (40, 0.0), (100, 4.5), (n, 4.5)])

    camera_move([(1, (0, 0, 0.128), 1.72, -96, 11),
                 (48, (0, 0, 0.126), 1.54, -76, 16),
                 (n, (0.015, -0.015, 0.120), 1.36, -52, 20)])


# ══ shot 2 — the insert comes apart ══════════════════════════════════════════
def exploded(m, n):
    """The layers separate. The offsets match the `exploded` still, so the last
    frame of the video is that photograph."""
    LIFT = 62.0
    steps = [("insert_base", "microfibre", 0.0), ("battery", "lipo", 22.0),
             ("qi_coil", "copper", -48.0), ("insert_floor", "fsr_film", 46.0),
             ("insert_walls", "microfibre", 96.0),
             ("insert_dividers", "microfibre_dark", 96.0),
             ("fsr_cable", "polyimide", 96.0),
             ("insert_collar", "microfibre", 146.0)]
    # ⚠️ Staggered start order, top down: if every layer leaves at the same
    # moment the motion is an accordion and you cannot tell which piece came out
    # of which.
    delay = {"insert_collar": 0, "insert_walls": 8, "insert_dividers": 8,
             "fsr_cable": 8, "insert_floor": 16, "battery": 24,
             "qi_coil": 24, "insert_base": 0}
    for name, k, rise in steps:
        o = sc.load_stl(name, m[k], LIFT)
        d = delay[name]
        keys(o, "location", [(1, o.location.copy()),
                             (18 + d, o.location.copy()),
                             (104 + d, o.location + mathutils.Vector(
                                 (0, 0, rise * sc.MM))),
                             (n, o.location + mathutils.Vector(
                                 (0, 0, rise * sc.MM)))])
    fsr = sc.load_stl("fsr_matrix", m["taxel_off"], LIFT)
    pieces = sc.light_taxels(fsr, m)
    for p in pieces:
        base = p.location.copy()
        keys(p, "location", [(1, base), (34, base),
                             (120, base + mathutils.Vector((0, 0, 46 * sc.MM))),
                             (n, base + mathutils.Vector((0, 0, 46 * sc.MM)))])
    board = sc.load_board((0, sc.SEAT_Y, LIFT + sc.INS_TOTAL_H - 4.2))
    if board:
        base = board.location.copy()
        high = base + mathutils.Vector((0, 0, (146 + 62) * sc.MM))
        keys(board, "location", [(1, base), (14, base), (98, high), (n, high)])

    sc.backdrop(m)
    sc.light("key", (0.45, -0.80, 1.10), 52, 1.5, (0, 0, 0.30))
    sc.light("fill", (-0.95, -0.25, 0.55), 17, 2.0, (0, 0, 0.28),
             colour=(0.78, 0.84, 1.0))
    sc.light("rim", (-0.10, 0.95, 0.95), 30, 1.2, (0, 0, 0.34),
             colour=(1.0, 0.88, 0.74))
    camera_move([(1, (0, 0, 0.118), 1.46, -74, 12),
                 (n, (0, 0, 0.235), 1.56, -60, 16)], focal=72)


# ══ shot 3 — the scan ════════════════════════════════════════════════════════
def scanning(m, n):
    """The bag already open: the radar beams sweep, the taxels light up.

    ⭐ THE WAVE HAS A DIRECTION AND A DURATION. Lighting every taxel at once
    would show a result; lighting them left to right shows a MEASUREMENT — which
    is what the product actually does, and the only thing that justifies a video
    instead of a photograph.
    """
    cuttable = _load_section_set(m)
    fsr = sc.load_stl("fsr_matrix", m["taxel_off"], sc.Z_INSERT)
    pieces = sc.light_taxels(fsr, m)
    sc.place_contents(m)
    sc.load_board((0, sc.SEAT_Y, sc.Z_BOARD))
    place_optics(m)
    neck, teeth, slider, _ = place_neck(m, 0.0, 138.0)
    cuttable += [neck, teeth, slider]
    sc.section_cut(cuttable, (0.22, -0.22, 0.12), (0.44, 0.44, 0.50))

    # ── the wave across the lit taxels ───────────────────────────────────────
    # ⚠️ Every lit taxel gets a COPY of the material: sharing a single one would
    # mean any key lights them all in the same instant and the wave would not
    # exist.
    f0, f1 = 26, 104
    lit = [p for p in pieces if p.data.materials
           and p.data.materials[0].name.startswith("taxel_on")]
    for p in lit:
        x = p.matrix_world.translation.x / sc.MM
        t = (x + 112.5) / 225.0                      # 0 at left, 1 at right
        f = f0 + (f1 - f0) * t
        mm = m["taxel_on"].copy()
        p.data.materials.clear()
        p.data.materials.append(mm)
        emission(mm, [(1, 0.0), (max(2, f - 3), 0.0), (f + 2, 9.0),
                      (f + 14, 4.2), (n, 4.2)])

    # ── the two beams pulse as the scan progresses ───────────────────────────
    cones = sc.radar_beams(m)
    for i, c in enumerate(cones):
        mm = m["beam_radar"].copy()
        c.data.materials.clear()
        c.data.materials.append(mm)
        phase = i * 9
        emission(mm, [(1, 0.0), (14 + phase, 0.0), (34 + phase, 1.4),
                      (58 + phase, 0.35), (80 + phase, 1.4),
                      (108 + phase, 0.25), (n, 0.0)])

    sc.backdrop(m)
    sc.light("key", (0.75, -0.95, 0.95), 80, 1.5, (0, 0, 0.12))
    sc.light("fill", (-0.95, -0.55, 0.45), 24, 2.0, (0, 0, 0.10),
             colour=(0.78, 0.84, 1.0))
    sc.light("rim", (-0.25, 0.90, 0.80), 42, 1.2, (0, 0, 0.18),
             colour=(1.0, 0.88, 0.74))
    sc.light("interior", (0.09, -0.05, 0.235), 4.5, 0.10, (0.02, 0.0, 0.05),
             colour=(1.0, 0.93, 0.86))
    # ⚠️ The push-in stops at 1.16 m: closer than that, the move cropped the
    # collar and the board — exactly the part doing the measuring.
    camera_move([(1, (0.015, -0.015, 0.120), 1.38, -52, 18),
                 (n, (0.010, -0.018, 0.104), 1.16, -46, 15)])


# ══ shot 4 — the zip opens ═══════════════════════════════════════════════════
def closed_bag_scene(m, closed, slider_x):
    """The whole bag with the insert inside. No section: here the bag is a
    closed object, and that is the point of the shot."""
    for name, k in (("bag_body", "leather"), ("bag_hardware", "gold"),
                    ("bag_handles", "leather")):
        sc.load_stl(name, m[k])
    for name, k, dz in (("insert_walls", "microfibre", sc.Z_INSERT),
                        ("insert_collar", "microfibre", sc.Z_INSERT),
                        ("insert_base", "microfibre", sc.Z_INSERT),
                        ("insert_floor", "fsr_film", sc.Z_INSERT),
                        ("fsr_cable", "polyimide", sc.Z_INSERT),
                        ("insert_dividers", "microfibre_dark", sc.Z_INSERT),
                        ("battery", "lipo", sc.Z_INSERT),
                        ("qi_coil", "copper", sc.Z_INSERT - 6)):
        sc.load_stl(name, m[k], dz)
    fsr = sc.load_stl("fsr_matrix", m["taxel_off"], sc.Z_INSERT)
    sc.light_taxels(fsr, m)
    sc.load_board((0, sc.SEAT_Y, sc.Z_BOARD))
    place_optics(m)
    return place_neck(m, closed, slider_x)


def unzip(m, n):
    """The slider runs and the mouth gapes open. This is the first link in the
    chain: with the bag closed the system sleeps at microamps, and what wakes it
    is the Hall sensor on the closure.

    ⭐ THE MOUTH OPENS BY INTERPOLATING SHAPE, not by rotating parts. The neck
    goes from pinched to gaping and the two rows of teeth separate along the
    rim: that is the motion you see on a real bag.

    ⚠️ The pinch releases AFTER the slider's travel, with a lag. Release them
    together and the mouth would gape open ahead of a slider still halfway
    across — i.e. it would open on its own.
    """
    # ⚠️ Naming: `keys` is already the function that inserts keyframes, so the
    # SHAPE keys have to be called something else.
    _, _, slider, shapes = closed_bag_scene(m, 1.0, -138.0)
    # ⚠️ ±138 and not ±125: the travel has to end where the zip ends, at the tip
    # of the oval. Stopping short leaves the slider in the middle of a mouth
    # that is still wide, and it reads as a clasp sitting there.
    keys(slider, "location",
         [(1, (-138 * sc.MM, 0, 0)), (18, (-138 * sc.MM, 0, 0)),
          (76, (138 * sc.MM, 0, 0)), (n, (138 * sc.MM, 0, 0))])
    for k in shapes:
        keys(k, "value", [(1, 1.0), (34, 1.0), (104, 0.0), (n, 0.0)])

    # Hall sensor indicator: it lights when the closure actually opens.
    hall = indicator("hall_led", (-43.5, sc.SEAT_Y, sc.Z_BOARD + 4), 0.004,
                     m["hall_led"])
    mh = m["hall_led"].copy()
    sc.assign(hall, mh)
    emission(mh, [(1, 0.0), (58, 0.0), (70, 14.0), (88, 5.0), (n, 5.0)])

    sc.backdrop(m)
    sc.light("key", (0.62, -0.80, 1.15), 68, 1.4, (0, 0, 0.19))
    sc.light("fill", (-0.90, -0.35, 0.58), 21, 1.8, (0, 0, 0.17),
             colour=(0.80, 0.85, 1.0))
    sc.light("rim", (-0.30, 0.92, 0.88), 36, 1.0, (0, 0, 0.23),
             colour=(1.0, 0.90, 0.78))
    camera_move([(1, (0, 0, 0.170), 1.52, -74, 22),
                 (n, (0, 0, 0.176), 1.28, -64, 38)], focal=80)


# ══ shot 5 — an object goes in ═══════════════════════════════════════════════
def object_drop(m, n):
    """An object is dropped in, the camera scans it on the way past, it lands.

    ⛔ NO HAND. Four attempts tried to make one read — from above, tilted, in
    section, with tapered and curled phalanges. It stayed the worst thing in the
    frame and stole attention from the sensors, which are the subject. An object
    descending on its own is a product-animation convention: understood in the
    first frame, with nothing to get wrong.

    ⛔ THE LANDING POSITION IS READ FROM `sc.CONTENTS`, never restated. An
    earlier version carried its own copy and drifted: the object fell on top of
    the divider, i.e. inside another part. `tools/check.py` asserts the two
    agree, but reading it makes the assertion impossible to fail.
    """
    cuttable = _load_section_set(m)
    fsr = sc.load_stl("fsr_matrix", m["taxel_off"], sc.Z_INSERT)
    pieces = sc.light_taxels(fsr, m)
    sc.place_contents(m, exclude=("lipstick",))
    sc.load_board((0, sc.SEAT_Y, sc.Z_BOARD))
    _, _, leds, tof_lens = place_optics(m)
    neck, teeth, slider, _ = place_neck(m, 0.0, 138.0)
    cuttable += [neck, teeth, slider]
    sc.section_cut(cuttable, (0.22, -0.22, 0.12), (0.44, 0.44, 0.50))

    # ── the descending object ────────────────────────────────────────────────
    _, OBJ_X, OBJ_Y, OBJ_W, _, OBJ_H, _, _ = [
        c for c in sc.CONTENTS if c[0] == "lipstick"][0]
    z_rest = sc.Z_FSR_TOP + OBJ_H / 2 + 0.4
    bpy.ops.mesh.primitive_cylinder_add(radius=OBJ_W / 2 * sc.MM,
                                        depth=OBJ_H * sc.MM,
                                        vertices=48)
    obj = bpy.context.object
    obj.name = "dropped_object"
    m_obj = m["gold"].copy()
    sc.assign(obj, m_obj)
    obj.rotation_euler = (math.radians(7), 0, math.radians(12))
    keys(obj, "location",
         [(1, (OBJ_X * sc.MM, OBJ_Y * sc.MM, 0.330)),
          (14, (OBJ_X * sc.MM, OBJ_Y * sc.MM, 0.330)),
          (72, (OBJ_X * sc.MM, OBJ_Y * sc.MM, 0.196)),
          (104, (OBJ_X * sc.MM, OBJ_Y * sc.MM, z_rest * sc.MM)),
          (n, (OBJ_X * sc.MM, OBJ_Y * sc.MM, z_rest * sc.MM))])
    # A touch of rotation on the way down: an object that descends perfectly
    # straight looks glued to a rail.
    keys(obj, "rotation_euler",
         [(1, (math.radians(7), 0, math.radians(12))),
          (104, (0.0, 0.0, math.radians(-6))),
          (n, (0.0, 0.0, math.radians(-6)))])

    # ── ToF: intercepts the object at the mouth ──────────────────────────────
    z_opt = sc.Z_BOARD - 9.0
    tof = beam_cone("beam_tof", (48, sc.SEAT_Y - 4, z_opt),
                    (56, -14, z_opt + 52), 0.003, 0.016, m["beam_tof"])
    m_tof = m["beam_tof"].copy()
    sc.assign(tof, m_tof)
    emission(m_tof, [(1, 0.25), (48, 0.25), (62, 2.8), (92, 2.8), (108, 0.3),
                     (n, 0.25)])
    if tof_lens:
        sc.assign(tof_lens, m["beam_tof"].copy())

    # ── IR camera: aims at the object, the LEDs flash ────────────────────────
    cam = beam_cone("beam_camera", (-20, sc.SEAT_Y - 4, z_opt),
                    (OBJ_X, OBJ_Y, z_opt - 42), 0.004, 0.034, m["beam_cam"])
    m_cam = m["beam_cam"].copy()
    sc.assign(cam, m_cam)
    m_led = m["ir_led"].copy()
    for o in leds:
        sc.assign(o, m_led)
    # ⚠️ Three flashes of 3 frames each: at 24 fps that is 125 ms, not the real
    # 40 ms. A single-frame flash, on a screen, simply cannot be seen.
    f_cone, f_led, f_obj = [(1, 0.0), (68, 0.0)], [(1, 0.0), (68, 0.0)], \
        [(1, 0.0), (68, 0.0)]
    for k in range(3):
        b = 70 + k * 7
        f_cone += [(b, 3.6), (b + 3, 0.0)]
        f_led += [(b, 22.0), (b + 3, 0.0)]
        # ⭐ The object lights up too: it is the only thing that makes clear the
        # flash is HITTING it, rather than being a graphic effect alongside.
        f_obj += [(b, 1.4), (b + 3, 0.0)]
    for seq in (f_cone, f_led, f_obj):
        seq.append((n, 0.0))
    emission(m_cam, f_cone)
    emission(m_led, f_led)
    emission(m_obj, f_obj)

    # ── the taxels under the object light when it lands ──────────────────────
    for p in pieces:
        x = p.matrix_world.translation.x / sc.MM
        y = p.matrix_world.translation.y / sc.MM
        if not (abs(x - OBJ_X) <= 12 and abs(y - OBJ_Y) <= 12):
            continue
        mm = m["taxel_on"].copy()
        p.data.materials.clear()
        p.data.materials.append(mm)
        emission(mm, [(1, 0.0), (104, 0.0), (112, 9.0), (124, 4.2), (n, 4.2)])

    sc.backdrop(m)
    sc.light("key", (0.75, -0.95, 1.05), 78, 1.5, (0, 0, 0.15))
    sc.light("fill", (-0.95, -0.55, 0.52), 23, 2.0, (0, 0, 0.13),
             colour=(0.78, 0.84, 1.0))
    sc.light("rim", (-0.25, 0.90, 0.88), 40, 1.2, (0, 0, 0.21),
             colour=(1.0, 0.88, 0.74))
    sc.light("interior", (0.09, -0.05, 0.245), 4.0, 0.10, (0.02, 0.0, 0.06),
             colour=(1.0, 0.93, 0.86))
    camera_move([(1, (0.02, -0.015, 0.158), 1.24, -54, 26),
                 (n, (0.02, -0.015, 0.124), 1.06, -48, 21)], focal=76)


SHOTS = {"opening": opening, "exploded": exploded, "scanning": scanning,
         "unzip": unzip, "object_drop": object_drop}


if __name__ == "__main__":
    name, width, samples, threads, first, last, vertical = parse_args()
    n = LENGTH[name]
    sc.reset()
    sc.world()
    m = sc.palette()
    # ⭐ 9:16 IS NOT A CROP OF 16:9, and treating it as one is why vertical video
    # of a wide object looks like a mistake. A 196 mm board and a 276 mm bag are
    # landscape things; the portrait frame has to be re-aimed at the part that is
    # tall — the bag standing up, the insert coming out of it — rather than
    # showing the same shot with the ends cut off.
    # ⚠️ The camera pulls back by the ratio of the two aspect ratios, which keeps
    # the subject's HEIGHT filling the frame instead of its width.
    if vertical:
        sc.engine(samples, threads, width, int(width * 16 / 9))
    else:
        sc.engine(samples, threads, width, int(width * 9 / 16))
    s = bpy.context.scene
    s.frame_start, s.frame_end = first, (last or n)
    s.render.fps = FPS
    s.render.image_settings.file_format = "PNG"
    folder = os.path.join(OUT, name + ("_v" if vertical else ""))
    os.makedirs(folder, exist_ok=True)
    s.render.filepath = os.path.join(folder, "f")
    print(f"-- shot {name}: {n} frames at {width}px")
    SHOTS[name](m, n)
    # ⚠️ AFTER the shot, because the shot is what creates the camera. Changing
    # the lens rather than moving the camera keeps every keyframed position the
    # shot set up: the framing changes, the choreography does not.
    #
    # ⛔ AND THE FACTOR IS BIGGER THAN ONE, WHICH IS NOT THE OBVIOUS DIRECTION.
    # A portrait frame is narrower than a landscape one, so the instinct is to
    # widen the lens — and that puts the subject in the middle of a tall empty
    # room. Blender fits the sensor to the LARGER dimension by default, so
    # turning the frame on its side already widened the horizontal field: the
    # correction is to zoom back in until the bag spans the width again.
    if vertical:
        for obj in bpy.data.objects:
            if obj.type == "CAMERA":
                obj.data.lens *= 0.85
    bpy.ops.render.render(animation=True)
    print(f"DONE -> {folder}")
