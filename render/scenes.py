#!/usr/bin/env python3
"""PBR rendering of the SmartBag. Run it FROM Blender, not from python.

⛔ THIRD STAGE OF THE PIPELINE. First stage: KiCad generates the board and
exports it to GLB. Second: CadQuery generates bag and insert as STL. Here the
two worlds meet in one scene — and this is the only place where you can see
whether the board actually fits in the collar, because it is the only place
where the two geometries share a coordinate system.

⭐ EEVEE, NOT CYCLES. A lesson already paid for on an earlier project: Cycles at
40 samples took ~50 s per frame and drove the load average to 147 on 10 cores,
making the machine unusable. EEVEE does the same job in 2-3 s and is still a PBR
engine: metals, emission, shadows and layered materials are all there.

Usage:
  blender -b --python render/scenes.py -- [scene ...] [--width 1920]
Scenes: hero  exploded  section  collar  all
"""
import math
import os
import sys

import bpy
import mathutils

# ⚠️ Derived from __file__, never hardcoded: Blender is launched with an
# absolute path to this script, so the repo can live anywhere.
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STL = os.path.join(ROOT, "cad", "stl")
OUT = os.path.join(ROOT, "render", "views")

# ⚠️ CadQuery emits STL in millimetres. Importing 1:1 puts the bag at 280 Blender
# units: area lights, cutting planes and atmospheric falloff all have to be
# retuned to that scale, and Blender's defaults (which assume metres) stop
# working. Import in metres and think in metres.
MM = 0.001

# Dimensions shared with cad/bag_and_insert.py. ⚠️ If they change there they have
# to change here: there is no single dimensions file, and that is the project's
# known debt.
LEATHER = 3.5
INS_W, INS_D = 225.0, 78.0
Z_INSERT = LEATHER           # the insert rests on the bag's inner floor
Z_FSR_TOP = Z_INSERT + 8.0 + 1.6
INS_COLLAR_H = 20.0
Z_COLLAR = 9.6 + 150.0       # base + floor + walls, from the CAD model
SEAT_Y = -26.5               # centre of the board seat inside the band
Z_BOARD = Z_INSERT + Z_COLLAR + INS_COLLAR_H - 4.2   # the seat plane
INS_TOTAL_H = Z_COLLAR + INS_COLLAR_H


def parse_args():
    a = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    # ⚠️ `--width 1280` leaves "1280" among the positional arguments: without
    # skipping the value that follows a flag, it got taken for a scene name.
    scenes, skip = [], False
    for x in a:
        if skip:
            skip = False
        elif x.startswith("-"):
            skip = True
        else:
            scenes.append(x)
    scenes = scenes or ["all"]

    def val(n, d):
        return int(a[a.index(n) + 1]) if n in a else d
    return scenes, val("--width", 1920), val("--samples", 48), val("--threads", 5)


# ══ materials ════════════════════════════════════════════════════════════════
def mat(name, colour, metallic=0.0, roughness=0.5, emission=0.0,
        alpha=1.0, ior=1.45):
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    b = m.node_tree.nodes["Principled BSDF"]
    b.inputs["Base Color"].default_value = (*colour, 1.0)
    b.inputs["Metallic"].default_value = metallic
    b.inputs["Roughness"].default_value = roughness
    b.inputs["IOR"].default_value = ior
    if emission:
        b.inputs["Emission Color"].default_value = (*colour, 1.0)
        b.inputs["Emission Strength"].default_value = emission
    if alpha < 1.0:
        b.inputs["Alpha"].default_value = alpha
        m.surface_render_method = "BLENDED"
    return m


def palette():
    return {
        "leather": mat("leather", (0.055, 0.045, 0.042), 0.0, 0.52),
        "gold": mat("gold", (0.78, 0.60, 0.27), 1.0, 0.22),
        "microfibre": mat("microfibre", (0.30, 0.265, 0.225), 0.0, 0.88),
        "microfibre_dark": mat("microfibre_dark", (0.14, 0.125, 0.11), 0.0, 0.9),
        "fsr_film": mat("fsr_film", (0.045, 0.045, 0.055), 0.0, 0.42),
        "taxel_off": mat("taxel_off", (0.10, 0.10, 0.13), 0.2, 0.35),
        "taxel_on": mat("taxel_on", (1.0, 0.42, 0.10), 0.0, 0.3, 5.0),
        "copper": mat("copper", (0.72, 0.42, 0.20), 1.0, 0.28),
        "lipo": mat("lipo", (0.74, 0.75, 0.78), 0.85, 0.34),
        "polyimide": mat("polyimide", (0.68, 0.36, 0.09), 0.0, 0.35),
        "beam_radar": mat("beam_radar", (0.22, 0.78, 0.98), 0.0, 0.5, 0.7,
                          alpha=0.028),
        "dark_glass": mat("dark_glass", (0.03, 0.03, 0.04), 0.1, 0.10),
        "leather_burgundy": mat("leather_burgundy", (0.22, 0.045, 0.06), 0.0, 0.55),
        "steel": mat("steel", (0.62, 0.63, 0.65), 1.0, 0.30),
        # Sensor beams: different colours because they are different sensors,
        # and in six seconds of film colour is the only thing that tells them
        # apart.
        "beam_tof": mat("beam_tof", (0.35, 0.95, 0.55), 0.0, 0.5, 1.0,
                        alpha=0.026),
        "beam_cam": mat("beam_cam", (0.98, 0.30, 0.42), 0.0, 0.5, 1.0,
                        alpha=0.030),
        "hall_led": mat("hall_led", (0.40, 1.0, 0.62), 0.0, 0.4, 6.0),
        "ir_led": mat("ir_led", (1.0, 0.22, 0.30), 0.0, 0.25, 0.0),
        "optics": mat("optics", (0.045, 0.045, 0.05), 0.2, 0.28),
    }


def assign(o, m):
    o.data.materials.clear()
    o.data.materials.append(m)


# ══ import ═══════════════════════════════════════════════════════════════════
def load_stl(name, material, dz=0.0):
    f = os.path.join(STL, f"{name}.stl")
    if not os.path.exists(f):
        raise SystemExit(f"missing STL: {f} (run cad/bag_and_insert.py first)")
    before = set(bpy.data.objects)
    bpy.ops.wm.stl_import(filepath=f, global_scale=MM)
    o = [x for x in bpy.data.objects if x not in before][0]
    o.name = name
    o.location.z += dz * MM
    bpy.ops.object.select_all(action="DESELECT")
    o.select_set(True)
    bpy.context.view_layer.objects.active = o
    bpy.ops.object.shade_smooth_by_angle(angle=math.radians(24))
    if material:
        assign(o, material)
    return o


def load_board(position, rotation=(0, 0, 0)):
    """Import the real board exported from KiCad and place it.

    ⛔ KICAD'S GLB HAS A SINGLE ROOT, and it is an EMPTY ("Node_0"): all the
    meshes are already its children. The first version of this function looked
    for meshes with `parent is None` to reparent them — it found none, so the
    move was never applied and the board stayed where it was, out of frame. What
    gets reparented here are the **roots**, whatever type they are.

    ⚠️ The GLB arrives in metres (measured: 0.126 x 0.052 x 0.0036 m) but centred
    on the origin of the KiCad SHEET, not on itself. The centre is derived from
    the actual bounding box, so moving the board on the sheet does not break the
    scene.
    """
    f = os.path.join(STL, "smartbag_core.glb")
    if not os.path.exists(f):
        print("WARNING: smartbag_core.glb missing, board not placed")
        return None
    before = set(bpy.data.objects)
    bpy.ops.import_scene.gltf(filepath=f)
    new = [x for x in bpy.data.objects if x not in before]
    meshes = [x for x in new if x.type == "MESH"]
    if not meshes:
        return None
    mn = mathutils.Vector((1e9, 1e9, 1e9))
    mx = mathutils.Vector((-1e9, -1e9, -1e9))
    for o in meshes:
        for v in o.bound_box:
            q = o.matrix_world @ mathutils.Vector(v)
            mn = mathutils.Vector((min(mn[i], q[i]) for i in range(3)))
            mx = mathutils.Vector((max(mx[i], q[i]) for i in range(3)))
    # ⛔ THE BOTTOM OF THE BOARD IS WHAT GETS ALIGNED, not the centre of the
    # bounding box. That box includes the components (up to 3.6 mm tall against
    # the substrate's 0.6): centring it put the board 1.8 mm below the seat
    # plane, and the render showed only the connectors poking out with the green
    # substrate buried in the microfibre.
    centre = mathutils.Vector(((mn.x + mx.x) / 2, (mn.y + mx.y) / 2, mn.z))
    pivot = bpy.data.objects.new("board", None)
    bpy.context.collection.objects.link(pivot)
    pivot.location = centre
    bpy.context.view_layer.update()
    inv = pivot.matrix_world.inverted()
    for o in [x for x in new if x.parent is None]:
        o.parent = pivot
        o.matrix_parent_inverse = inv
    pivot.location = mathutils.Vector(position) * MM
    pivot.rotation_euler = tuple(math.radians(a) for a in rotation)
    return pivot


# ══ SOFT NECK AND ZIP ════════════════════════════════════════════════════════
# ⛔ WHY THIS CODE EXISTS. Three attempts tried to close the bag with two rigid
# flaps hinged on the rim, opening them up, down, inwards and outwards. All four
# looked like a HATCH, and the reason was not the pose: two rigid plates
# rotating about a hinge are a hatch, whichever way you turn them.
#
# ⭐ On a real bag the motion is not a rotation. The neck is SOFT: closing the
# zip pinches the mouth down to a line, opening it lets the mouth gape into an
# oval. The two rows of teeth do not rotate — they SEPARATE. Here the neck is a
# surface generated in two states (mouth open / mouth pinched) on identical
# topology, interpolated by a shape key.
NECK_Z0, NECK_Z1 = 190.0, 245.0          # start and end of the neck, in mm
NECK_A = (138.0, 143.2)                   # half-width at z0 and z1
NECK_B = (56.0, 58.5)                     # half-depth at z0 and z1
NECK_R = (22.0, 22.6)                     # corner radius
MOUTH_CLOSED = 5.5                        # half-depth with the mouth pinched
TOOTH_PITCH = 3.4


def _section(A, B, r, n_long=44, n_short=10, n_arc=8):
    """Rounded rectangle sampled at FIXED counts.

    ⚠️ The number of points must not depend on the dimensions: the two states of
    the neck have to share identical topology, otherwise no shape key can link
    them. Hence sampling by count, not by metric step.
    """
    r = min(r, A * 0.98, B * 0.98)
    ax, by, p = A - r, B - r, []
    for i in range(n_short):
        p.append((A, -by + 2 * by * i / n_short))
    for i in range(n_arc):
        th = (i / n_arc) * (math.pi / 2)
        p.append((ax + r * math.cos(th), by + r * math.sin(th)))
    for i in range(n_long):
        p.append((ax - 2 * ax * i / n_long, B))
    for i in range(n_arc):
        th = math.pi / 2 + (i / n_arc) * (math.pi / 2)
        p.append((-ax + r * math.cos(th), by + r * math.sin(th)))
    for i in range(n_short):
        p.append((-A, by - 2 * by * i / n_short))
    for i in range(n_arc):
        th = math.pi + (i / n_arc) * (math.pi / 2)
        p.append((-ax + r * math.cos(th), -by + r * math.sin(th)))
    for i in range(n_long):
        p.append((-ax + 2 * ax * i / n_long, -B))
    for i in range(n_arc):
        th = 1.5 * math.pi + (i / n_arc) * (math.pi / 2)
        p.append((ax + r * math.cos(th), -by + r * math.sin(th)))
    return p


def _lerp(a, b, t):
    return a + (b - a) * t


def _taper(x, A, strength, Lg=40.0):
    """How much the depth is squeezed near the two ends of the mouth.

    ⛔ NEEDED BECAUSE A ZIP HAS TO END SOMEWHERE. With a rounded-rectangle mouth
    the two rows of teeth stayed 100 mm apart even at the extremes: the slider,
    at the end of its travel, floated in mid-air instead of sitting where the
    two sides close. On a real bag the ends of the mouth are stitched and the
    opening is a POINTED oval. Here the depth is squeezed to 4.5% over the last
    40 mm, and the zip gets two real ends for the slider to stop at.
    """
    f = min(1.0, max(0.0, (A - abs(x)) / Lg))
    return (1 - strength) + strength * (0.045 + 0.955 * f * f * (3 - 2 * f))


def _rim_y(x, A, B, r, strength):
    """Half-depth of the mouth rim at coordinate x (rounded rectangle)."""
    r = min(r, A * 0.98, B * 0.98)
    ax = A - r
    y = B if abs(x) <= ax else B - r + math.sqrt(max(0.0, r * r - (abs(x) - ax) ** 2))
    return y * _taper(x, A, strength)


def _with_shape_key(name, verts_open, verts_closed, faces, material):
    """Build the object in the OPEN state and attach the CLOSED shape to it."""
    me = bpy.data.meshes.new(name)
    me.from_pydata([(x * MM, y * MM, z * MM) for x, y, z in verts_open],
                   [], faces)
    me.update()
    o = bpy.data.objects.new(name, me)
    bpy.context.collection.objects.link(o)
    o.shape_key_add(name="open", from_mix=False)
    k = o.shape_key_add(name="closed", from_mix=False)
    for i, (x, y, z) in enumerate(verts_closed):
        k.data[i].co = (x * MM, y * MM, z * MM)
    k.value = 0.0
    assign(o, material)
    return o, k


def neck_zip(mat_, rings=18):
    """Soft neck + two rows of teeth + slider. Also returns the shape keys, so
    the animation can open and close the bag by interpolating them."""
    op, cl, faces = [], [], []
    NU = len(_section(NECK_A[0], NECK_B[0], NECK_R[0]))
    for i in range(rings):
        t = i / (rings - 1)
        z = _lerp(NECK_Z0, NECK_Z1, t)
        A, B, r = (_lerp(*NECK_A, t), _lerp(*NECK_B, t), _lerp(*NECK_R, t))
        # ⭐ Smoothstep on height: the pinch does not start abruptly at the end
        # of the rigid body, it accumulates going up — which is how soft leather
        # behaves when a zip pulls it shut.
        p = t * t * (3 - 2 * t)
        b_c = _lerp(B, MOUTH_CLOSED, p)
        # ⚠️ The end taper grows with t CUBED, not linearly: applied in
        # proportion to height it squeezed the neck over all 55 mm and the two
        # ends turned into wedges — from the side the bag looked like it had a
        # pitched roof. The ends of a mouth are stitched over the last few
        # centimetres, not over the whole height of the neck.
        g = t ** 3
        for x, y in _section(A, B, r):
            op.append((x, y * _taper(x, A, g), z))
        for x, y in _section(A, b_c, min(r, b_c * 0.92)):
            cl.append((x, y * _taper(x, A, g), z))
    for i in range(rings - 1):
        for j in range(NU):
            k = (j + 1) % NU
            faces.append((i * NU + j, i * NU + k, (i + 1) * NU + k,
                          (i + 1) * NU + j))
    neck, neck_key = _with_shape_key("neck", op, cl, faces, mat_["leather"])
    sol = neck.modifiers.new("thickness", "SOLIDIFY")
    sol.thickness, sol.offset = 0.0032, -1.0
    bpy.ops.object.select_all(action="DESELECT")
    neck.select_set(True)
    bpy.context.view_layer.objects.active = neck
    bpy.ops.object.shade_smooth_by_angle(angle=math.radians(40))

    # ── teeth: two rows that separate, not two plates that rotate ────────────
    # ⭐ Every tooth sits ON THE RIM, at its own x: that way the two rows
    # converge at the ends following the oval, and the slider's travel finishes
    # where the zip finishes. A straight line at constant y left the teeth
    # 100 mm apart even at the tip, with the slider stranded in mid-air.
    A_t, B_t, r_t = NECK_A[1], NECK_B[1], NECK_R[1]
    b_ct = MOUTH_CLOSED
    z_t = NECK_Z1 - 2.4
    dx, dy, dz = 1.2, 1.5, 1.1
    op, cl, faces = [], [], []
    x_max = A_t - 5.0
    n = int(2 * x_max / TOOTH_PITCH)
    for i in range(n):
        x = -x_max + i * TOOTH_PITCH
        side = 1 if i % 2 == 0 else -1
        y_op = max(1.9, _rim_y(x, A_t, B_t, r_t, 1.0) - 5.0)
        y_cl = max(1.9, _rim_y(x, A_t, b_ct, min(r_t, b_ct * 0.92), 1.0) - 1.2)
        for target, y in ((op, side * y_op), (cl, side * y_cl)):
            for sx, sy, sz in ((-1, -1, -1), (1, -1, -1), (1, 1, -1), (-1, 1, -1),
                               (-1, -1, 1), (1, -1, 1), (1, 1, 1), (-1, 1, 1)):
                target.append((x + sx * dx, y + sy * dy, z_t + sz * dz))
        b = i * 8
        for f in ((0, 1, 2, 3), (4, 7, 6, 5), (0, 4, 5, 1), (1, 5, 6, 2),
                  (2, 6, 7, 3), (3, 7, 4, 0)):
            faces.append(tuple(b + q for q in f))
    teeth, teeth_key = _with_shape_key("teeth", op, cl, faces, mat_["gold"])

    slider = load_stl("zip_slider", mat_["gold"])
    return neck, teeth, slider, (neck_key, teeth_key)


# ══ things inside the bag ════════════════════════════════════════════════════
# (name, cx, cy, width_x, depth_y, height_z, material, shape)
# Coordinates in the insert's plane, in millimetres. ⭐ They all stand UPRIGHT,
# and that is not an aesthetic choice: the insert is 78 mm deep and a 105 mm
# wallet lying flat does not fit. Handbags get packed vertically, which is also
# why the radar looks down from above rather than across from the side.
CONTENTS = [
    ("wallet", -72, 2, 95, 20, 105, "leather_burgundy", "box"),
    ("phone", 2, 24, 72, 8, 148, "dark_glass", "box"),
    ("pouch", 62, 20, 78, 28, 62, "leather", "box"),
    # ⛔ MOVED FROM x = 44 TO x = 60. At 44 the lipstick landed straddling the
    # divider (which sits at x = 37.5 and is 1.6 mm thick): in the film the
    # object fell INSIDE another part. At 60 the compartment is clear — checked
    # against the divider, the pouch (x 23..101, y 6..34) and the keys
    # (x 71..105).
    ("lipstick", 60, -20, 18, 18, 76, "gold", "cyl"),
    ("keys", 88, 4, 34, 30, 6, "steel", "keys"),
]


def place_contents(mat_, exclude=()):
    """`exclude` drops items from the scene. ⭐ The sequence film needs it: the
    lipstick must not already be in the bag, it arrives during the shot."""
    made = []
    for name, cx, cy, w, d, h, material, shape in CONTENTS:
        if name in exclude:
            continue
        z = Z_FSR_TOP + 0.4
        if shape == "box":
            bpy.ops.mesh.primitive_cube_add(size=1)
            o = bpy.context.object
            o.scale = (w * MM, d * MM, h * MM)
            o.location = (cx * MM, cy * MM, (z + h / 2) * MM)
            bpy.ops.object.transform_apply(scale=True)
            bpy.ops.object.modifier_add(type="BEVEL")
            o.modifiers["Bevel"].width = 0.003
            o.modifiers["Bevel"].segments = 3
        elif shape == "cyl":
            bpy.ops.mesh.primitive_cylinder_add(
                radius=w / 2 * MM, depth=h * MM,
                location=(cx * MM, cy * MM, (z + h / 2) * MM))
            o = bpy.context.object
        else:  # bunch of keys: a ring plus three flat blades
            bpy.ops.mesh.primitive_torus_add(
                major_radius=15 * MM, minor_radius=1.4 * MM,
                location=(cx * MM, cy * MM, (z + 2) * MM))
            o = bpy.context.object
            for ang in (-0.5, 0.15, 0.8):
                bpy.ops.mesh.primitive_cube_add(size=1)
                blade = bpy.context.object
                blade.scale = (44 * MM, 8 * MM, 2.2 * MM)
                blade.rotation_euler = (0, 0, ang)
                blade.location = ((cx + 22 * math.cos(ang)) * MM,
                                  (cy + 22 * math.sin(ang)) * MM, (z + 1.5) * MM)
                bpy.ops.object.transform_apply(scale=True)
                assign(blade, mat_["steel"])
                made.append(blade)
        o.name = name
        assign(o, mat_[material])
        bpy.ops.object.shade_smooth_by_angle(angle=math.radians(40))
        made.append(o)
    return made


def footprints():
    """Contact rectangles of the contents, in millimetres (cx, cy, w, d)."""
    return [(cx, cy, w, d) for _, cx, cy, w, d, _, _, _ in CONTENTS]


def light_taxels(fsr_object, mat_):
    """Split the 96 taxels apart and light the ones under an object.

    ⭐ This is the visual heart of the scene: the FSR matrix is not an abstract
    datum, it is the imprint the contents leave on the floor. The test is
    geometric and derived from the same numbers that place the contents, so
    moving an object automatically lights different taxels.
    """
    bpy.ops.object.select_all(action="DESELECT")
    fsr_object.select_set(True)
    bpy.context.view_layer.objects.active = fsr_object
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="SELECT")
    bpy.ops.mesh.separate(type="LOOSE")
    bpy.ops.object.mode_set(mode="OBJECT")
    pieces = [o for o in bpy.context.selected_objects if o.type == "MESH"]
    fp = footprints()
    lit = 0
    for p in pieces:
        c = p.matrix_world @ (sum((mathutils.Vector(v) for v in p.bound_box),
                                  mathutils.Vector()) / 8)
        x, y = c.x / MM, c.y / MM
        under = any(abs(x - cx) <= w / 2 + 3 and abs(y - cy) <= d / 2 + 3
                    for cx, cy, w, d in fp)
        assign(p, mat_["taxel_on"] if under else mat_["taxel_off"])
        lit += under
    print(f"   taxels lit: {lit}/{len(pieces)}")
    return pieces


def radar_beams(mat_):
    """The two 60 GHz radar lobes: translucent cones rising from the sides."""
    # ⛔ SCALED DOWN. In the first version the cones were bigger than the bag and
    # spilled out the sides: they read as a graphic effect, not as the volume
    # being illuminated. They now start at the two antenna islands (x = ±93, in
    # the front band) and point at the centre of the floor, which is the real
    # volume of interest.
    cones = []
    start = (93.0, SEAT_Y, Z_BOARD - 2.0)
    end = (0.0, 6.0, Z_FSR_TOP)
    for side in (-1, 1):
        p = mathutils.Vector((side * start[0], start[1], start[2])) * MM
        a = mathutils.Vector((side * end[0], end[1], end[2])) * MM
        d = a - p
        bpy.ops.mesh.primitive_cone_add(radius1=0.003, radius2=0.036,
                                        depth=d.length, vertices=48)
        c = bpy.context.object
        c.name = f"radar_beam_{'l' if side < 0 else 'r'}"
        c.location = p + d / 2
        c.rotation_euler = d.to_track_quat("Z", "Y").to_euler()
        assign(c, mat_["beam_radar"])
        cones.append(c)
    return cones


def callout(label, anchor_mm, dx=0.20, dz=0.0, size=0.011):
    """A 3D caption aligned to the camera, with its own leader line.

    ⭐ An exploded view without names is a nice object that explains nothing: the
    question the render has to answer is "what does this layer do". The text is
    geometry in the scene (not a post overlay) so it stays attached to the part
    even if the framing changes.

    ⚠️ Call it AFTER `camera_at`: the orientation is copied from the camera, and
    if the camera does not exist yet the text comes out facing sideways.
    """
    cam = bpy.context.scene.camera
    right = cam.matrix_world.to_3x3() @ mathutils.Vector((1, 0, 0))
    up = cam.matrix_world.to_3x3() @ mathutils.Vector((0, 1, 0))
    anchor = mathutils.Vector(anchor_mm) * MM
    pos = anchor + right * dx + up * dz
    # ⛔ THE TEXT HAS TO BE BROUGHT IN FRONT OF THE MODEL. A caption is geometry,
    # and as such it ends up behind the bag's leather the moment you move it
    # over the silhouette: in the early renders half the labels vanished,
    # swallowed by the front panel. It gets pulled back along the ray from the
    # camera to the point, shortened to a fraction of the distance and scaled
    # down in the same proportion: on screen it is identical, but it sits in
    # front of everything.
    FORWARD = 0.55
    ray = pos - cam.location
    pos = cam.location + ray * FORWARD
    size = size * FORWARD
    c = bpy.data.curves.new("txt", type="FONT")
    c.body = label
    c.size = size
    c.align_x = "RIGHT" if dx < 0 else "LEFT"
    c.align_y = "CENTER"
    o = bpy.data.objects.new(f"label_{label[:12]}", c)
    bpy.context.collection.objects.link(o)
    o.location = pos
    o.rotation_euler = cam.rotation_euler
    assign(o, mat(f"txt_{label[:8]}", (0.85, 0.86, 0.90), 0.0, 0.5, 1.6))
    # leader line
    bpy.ops.mesh.primitive_cylinder_add(radius=0.00035, depth=1, vertices=6)
    ln = bpy.context.object
    ln.name = f"leader_{label[:10]}"
    d = pos - anchor
    ln.location = anchor + d / 2
    ln.scale = (1, 1, d.length)
    ln.rotation_euler = d.to_track_quat("Z", "Y").to_euler()
    assign(ln, mat(f"leader_{label[:8]}", (0.55, 0.57, 0.62), 0.0, 0.5, 0.9))
    return o


# ══ scene plumbing ═══════════════════════════════════════════════════════════
def reset():
    bpy.ops.wm.read_factory_settings(use_empty=True)


def world(background=(0.020, 0.021, 0.028)):
    m = bpy.data.worlds.new("world")
    bpy.context.scene.world = m
    m.use_nodes = True
    m.node_tree.nodes["Background"].inputs[0].default_value = (*background, 1.0)
    m.node_tree.nodes["Background"].inputs[1].default_value = 1.0


def light(name, position, energy, size, aim=(0, 0, 0), colour=(1, 1, 1)):
    d = bpy.data.lights.new(name, type="AREA")
    d.energy = energy
    d.size = size
    d.color = colour
    o = bpy.data.objects.new(name, d)
    bpy.context.collection.objects.link(o)
    o.location = position
    direction = mathutils.Vector(aim) - mathutils.Vector(position)
    o.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()
    return o


def backdrop(mat_):
    """A cyclorama: a cylinder seen from the inside, not a plane.

    ⛔ A plane, however large, has a HORIZON: in the early renders it cut the
    image with a hard line halfway up the frame, which in a product shot reads
    as a mistake. The cylinder does what a curved studio backdrop does — the
    floor rises into the wall with no seam.
    """
    bpy.ops.mesh.primitive_cylinder_add(radius=11.0, depth=44.0,
                                        rotation=(0, math.radians(90), 0),
                                        location=(0, 0, 11.0))
    p = bpy.context.object
    p.name = "backdrop"
    assign(p, mat("backdrop", (0.055, 0.056, 0.065), 0.0, 0.62))
    bpy.ops.object.shade_smooth_by_angle(angle=math.radians(60))
    return p


def camera_at(aim, distance, azimuth, elevation, focal=85, ortho=None, pan=0.0):
    """Camera in spherical coordinates around the target. Angles in degrees."""
    c = bpy.data.cameras.new("cam")
    c.lens = focal
    if ortho:
        c.type, c.ortho_scale = "ORTHO", ortho
    o = bpy.data.objects.new("cam", c)
    bpy.context.collection.objects.link(o)
    a, e = math.radians(azimuth), math.radians(elevation)
    m = mathutils.Vector(aim)
    o.location = m + mathutils.Vector((
        distance * math.cos(e) * math.cos(a),
        distance * math.cos(e) * math.sin(a),
        distance * math.sin(e)))
    o.rotation_euler = (m - o.location).to_track_quat("-Z", "Y").to_euler()
    # ⭐ `pan` is a real pan (a translation along the camera's X axis), not a
    # rotation: it moves the subject within the frame without changing the point
    # of view, which is what makes room for the callouts on the right.
    if pan:
        o.location += (o.matrix_world.to_3x3() @ mathutils.Vector((1, 0, 0))) * pan
    bpy.context.scene.camera = o
    return o


def section_cut(objects, centre, size):
    """Section: subtract a box from every object passed in.

    ⛔ This is not a camera clipping plane. Clipping also cuts interior faces and
    leaves the model open (you see nothing inside the walls); a boolean leaves
    the cut surfaces closed, and that is what makes the thickness of the layers
    legible.
    """
    bpy.ops.mesh.primitive_cube_add(size=1, location=centre)
    cut = bpy.context.object
    cut.name = "cutter"
    cut.scale = size
    bpy.ops.object.transform_apply(scale=True)
    # ⛔ ONLY `hide_render`, NEVER `hide_viewport`. Hiding the cutter from the
    # viewport excludes it from the depsgraph: on a still scene the boolean
    # survived anyway (its matrix was already fixed at creation), but the moment
    # the cutter is ANIMATED its evaluated copy no longer exists and the boolean
    # stops applying — in the film the bag did not open at all, despite the
    # modifier being right and the keys being correct. Measured: 10378 evaluated
    # vertices (no cut) against 7705 (cut).
    cut.hide_render = True
    for o in objects:
        if o is None:
            continue
        m = o.modifiers.new("section", "BOOLEAN")
        m.operation = "DIFFERENCE"
        m.solver = "EXACT"
        m.object = cut
    return cut


def engine(samples, threads, width, height):
    s = bpy.context.scene
    s.render.engine = "BLENDER_EEVEE"
    # ⭐ Capping the threads is the piece that was missing on an earlier
    # project: without it Blender takes every core and the machine stops
    # responding during the render.
    s.render.threads_mode = "FIXED"
    s.render.threads = max(1, threads)
    s.eevee.taa_render_samples = samples
    s.eevee.use_raytracing = True
    # ⛔ The dark streaks across the inner walls of the collar were NOT badly
    # tessellated faces: they were shadow acne from EEVEE's shadow map on
    # surfaces nearly parallel to the light. More rays, more steps and full map
    # resolution close them; touching the mesh does not.
    s.eevee.shadow_ray_count = 4
    s.eevee.shadow_step_count = 12
    s.eevee.shadow_resolution_scale = 1.0
    s.render.resolution_x = width
    s.render.resolution_y = height
    s.render.film_transparent = False
    s.view_settings.view_transform = "AgX"
    s.view_settings.look = "AgX - Medium High Contrast"
    # ⚠️ AgX compresses the highlights but does not lower exposure: with three
    # area lights the microfibre came out milky and the layers stopped reading
    # as separate.
    s.view_settings.exposure = -0.9


def write_image(name):
    os.makedirs(OUT, exist_ok=True)
    f = os.path.join(OUT, f"{name}.png")
    bpy.context.scene.render.filepath = f
    bpy.ops.render.render(write_still=True)
    print(f"DONE -> {f}")


# ══ the four scenes ══════════════════════════════════════════════════════════
def scene_hero(m):
    """The bag genuinely CLOSED: neck pinched, zip pulled shut.

    ⚠️ The rigid body ends at 190 mm: without the neck the shell stays open at
    the top and the render shows a bucket.
    """
    for n, k in (("bag_body", "leather"), ("bag_handles", "leather"),
                 ("bag_hardware", "gold")):
        load_stl(n, m[k])
    _, _, slider, keys = neck_zip(m)
    for k in keys:
        k.value = 1.0
    slider.location.x = -125 * MM
    backdrop(m)
    light("key", (0.55, -0.75, 0.85), 55, 1.4, (0, 0, 0.13))
    light("fill", (-0.90, -0.35, 0.35), 16, 1.8, (0, 0, 0.11),
          colour=(0.80, 0.85, 1.0))
    light("rim", (-0.30, 0.95, 0.60), 30, 1.0, (0, 0, 0.16),
          colour=(1.0, 0.90, 0.78))
    camera_at((0, 0, 0.132), 1.78, -62, 13, focal=95)


def scene_exploded(m):
    """The layers of the insert pulled apart, with the real board above the collar.

    ⛔ THE OFFSETS ARE EXPLICIT, not a uniform step. The layers have very
    different heights (8 mm for the base, 150 for the walls): with a constant
    step the tall walls ended up touching the collar and the "gap" between the
    two disappeared exactly where it needed to be seen.
    """
    # ⚠️ Everything raised by LIFT: the Qi coil has to be shown UNDER the plate
    # (that is where it really is, so it can face the charging pad) and without
    # the lift it ended up below the studio floor, invisible.
    LIFT = 62.0
    load_stl("insert_base", m["microfibre"], LIFT)
    load_stl("battery", m["lipo"], LIFT + 22)
    load_stl("qi_coil", m["copper"], LIFT - 48)
    load_stl("insert_floor", m["fsr_film"], LIFT + 46)
    fsr = load_stl("fsr_matrix", m["taxel_off"], LIFT + 46)
    light_taxels(fsr, m)
    load_stl("insert_walls", m["microfibre"], LIFT + 96)
    load_stl("insert_dividers", m["microfibre_dark"], LIFT + 96)
    load_stl("fsr_cable", m["polyimide"], LIFT + 96)
    load_stl("insert_collar", m["microfibre"], LIFT + 146)
    load_stl("optics_body", m["optics"], LIFT + 146)
    load_stl("optics_lenses", m["dark_glass"], LIFT + 146)
    load_board((0, SEAT_Y, LIFT + INS_TOTAL_H + 146 + 62))
    backdrop(m)
    light("key", (0.45, -0.80, 1.10), 52, 1.5, (0, 0, 0.30))
    light("fill", (-0.95, -0.25, 0.55), 17, 2.0, (0, 0, 0.28),
          colour=(0.78, 0.84, 1.0))
    light("rim", (-0.10, 0.95, 0.95), 30, 1.2, (0, 0, 0.34),
          colour=(1.0, 0.88, 0.74))
    camera_at((0, 0, 0.245), 1.72, -66, 17, focal=72, pan=0.085)
    for label, z in [
        ("rigid-flex board — SoC+NPU, 60 GHz radar", 443.6),
        ("collar — IR camera module + ToF, board seat", 375.0),
        ("walls + FSR cable — semi-rigid microfibre", 242.0),
        ("FSR floor — 96 taxels", 118.0),
        ("FFC from the collar down to the floor", 205.0),
        ("power plate — LiPo 2000 mAh", 88.0),
        ("Qi coil — charges by setting the bag down", 15.0),
    ]:
        callout(label, (118, 0, z), dx=0.050, size=0.0088)


def scene_section(m):
    """The bag opened in section: this is the image that explains the product."""
    cuttable = []
    for n, k in (("bag_body", "leather"), ("bag_hardware", "gold"),
                 ("insert_walls", "microfibre"),
                 ("insert_collar", "microfibre"),
                 ("insert_base", "microfibre"), ("insert_floor", "fsr_film")):
        cuttable.append(load_stl(n, m[k], Z_INSERT if n.startswith("insert") else 0))
    load_stl("bag_handles", m["leather"])
    load_stl("battery", m["lipo"], Z_INSERT)
    load_stl("qi_coil", m["copper"], Z_INSERT - 6)
    load_stl("insert_dividers", m["microfibre_dark"], Z_INSERT)
    load_stl("fsr_cable", m["polyimide"], Z_INSERT)
    load_stl("optics_body", m["optics"], Z_INSERT)
    load_stl("optics_lenses", m["dark_glass"], Z_INSERT)
    fsr = load_stl("fsr_matrix", m["taxel_off"], Z_INSERT)
    light_taxels(fsr, m)
    place_contents(m)
    radar_beams(m)
    load_board((0, SEAT_Y, Z_BOARD))
    neck, teeth, slider, keys = neck_zip(m)
    for k in keys:
        k.value = 0.0
    slider.location.x = 138 * MM
    cuttable += [neck, teeth, slider]
    # Front-right quarter removed: shows layers, contents and taxels.
    section_cut(cuttable, (0.22, -0.22, 0.12), (0.44, 0.44, 0.50))
    backdrop(m)
    light("key", (0.75, -0.95, 0.95), 80, 1.5, (0, 0, 0.12))
    light("fill", (-0.95, -0.55, 0.45), 24, 2.0, (0, 0, 0.10),
          colour=(0.78, 0.84, 1.0))
    light("rim", (-0.25, 0.90, 0.80), 42, 1.2, (0, 0, 0.18),
          colour=(1.0, 0.88, 0.74))
    # ⭐ Interior light: without it the volume the section opens stays black and
    # the image shows an empty shell instead of the contents.
    light("interior", (0.09, -0.05, 0.235), 4.5, 0.10, (0.02, 0.0, 0.05),
          colour=(1.0, 0.93, 0.86))
    camera_at((0.015, -0.015, 0.122), 1.38, -52, 18, focal=78)
    # ⚠️ No callout for the FSR cable: in this framing it runs behind the
    # front-left panel, which the section does NOT remove. An arrow pointing at
    # a piece of closed leather is worse than no arrow — the cable is visible in
    # the exploded view instead.
    for label, point, dx, dz in [
        ("board in the collar", (60, -26, 178), 0.090, 0.086),
        ("60 GHz radar beam", (40, 6, 118), 0.100, 0.018),
        # ⚠️ Anchors have to sit on geometry VISIBLE from the section: the
        # leader lines are real cylinders and get occluded by the leather.
        # Anchoring to the wallet (behind the intact panel) put the arrow on a
        # piece of closed leather.
        ("contents stand upright: only 78 mm deep", (2, 24, 150), -0.092, 0.020),
        ("taxels lit under the objects", (62, -10, 14), 0.070, -0.038),
    ]:
        callout(label, point, dx=dx, dz=dz, size=0.0065)


def scene_collar(m):
    """Collar detail: the board in its seat, the lens, the illuminators."""
    load_stl("insert_collar", m["microfibre"], Z_INSERT)
    load_stl("insert_walls", m["microfibre"], Z_INSERT)
    load_stl("insert_dividers", m["microfibre_dark"], Z_INSERT)
    load_stl("optics_body", m["optics"], Z_INSERT)
    load_stl("optics_lenses", m["dark_glass"], Z_INSERT)
    load_board((0, SEAT_Y, Z_BOARD))
    backdrop(m)
    light("key", (0.20, -0.40, 0.42), 8, 0.6, (0, -0.026, 0.178))
    light("fill", (-0.42, -0.26, 0.26), 3.5, 0.9, (0, -0.026, 0.178),
          colour=(0.80, 0.86, 1.0))
    light("rim", (-0.04, 0.42, 0.34), 6, 0.5, (0, 0, 0.178),
          colour=(1.0, 0.90, 0.76))
    camera_at((0.0, -0.018, 0.170), 0.44, -96, 28, focal=55)
    # The board is mounted without rotation, so the KiCad layout's x values hold
    # in the scene too.
    for label, x_kicad, dx, dz in [
        ("radar array A1", -93, -0.012, 0.020),
        ("IR lens + 4 illuminators", -20, -0.012, 0.038),
        ("SoC + NPU  ·  60 GHz radar", -30, 0.012, 0.052),
        ("J4 — FSR matrix cable", 32, 0.012, 0.032),
        ("radar array A2", 93, 0.012, 0.014),
    ]:
        callout(label, (x_kicad, SEAT_Y, Z_BOARD + 2),
                dx=dx, dz=dz, size=0.0031)


# (function, width, height) at the reference scale. ⚠️ The exploded view is a
# 40 cm vertical stack: in 16:9 it either runs out of frame or becomes tiny.
SCENES = {"hero": (scene_hero, 1920, 1080),
          "exploded": (scene_exploded, 1800, 1900),
          "section": (scene_section, 1920, 1180),
          "collar": (scene_collar, 1920, 1080)}


if __name__ == "__main__":
    wanted, width, samples, threads = parse_args()
    if "all" in wanted:
        wanted = list(SCENES)
    for name in wanted:
        if name not in SCENES:
            print(f"WARNING: unknown scene {name}")
            continue
        fn, lx, ly = SCENES[name]
        reset()
        world()
        m = palette()
        k = width / 1920
        engine(samples, threads, max(320, int(lx * k)), max(320, int(ly * k)))
        print(f"-- scene {name}")
        fn(m)
        write_image(name)
