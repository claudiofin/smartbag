#!/usr/bin/env python3
"""Render the training set from the same scene that makes the films. FROM Blender.

⭐ THE LOOP CLOSES HERE. The collar camera's position, focal length and
illuminators are already modelled — they had to be, to render the films. So the
images this classifier trains on are taken through the same optics the product
would have, from the same place, lit by the same LEDs. That is worth more than
a bigger dataset shot through the wrong lens.

⛔ WHAT THIS DOES AND DOES NOT PROVE. The objects are primitives: boxes,
cylinders, a torus. Telling a box from a cylinder is not the hard part of object
recognition and a high score here says nothing about telling a wallet from a
passport. What IS reproduced faithfully is the *imaging condition* — three
frames of something falling past in 125 ms, lit for a few milliseconds by
infrared LEDs, monochrome, noisy, motion-blurred, sometimes clipped by the
mouth. That is the part the product has to survive, and it is the part this set
lets you measure.

⚠️ The classes are split into two disjoint groups. The embedding trains on one
group and is then asked to enrol and recognise objects from the other, which it
has never seen. Training and testing on the same objects would measure nothing
except memorisation — and enrolment, by definition, happens after the model
ships.

Usage:
  blender -b --python ml/render_dataset.py -- [--samples 100] [--size 96]
"""
import math
import os
import random
import sys

import bpy
import mathutils

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "render"))
import scenes as sc          # noqa: E402

OUT = os.path.join(sc.ROOT, "ml", "dataset")

# (name, group, shape, size in mm, material)
# `group` 0 trains the embedding, 1 is held out for enrolment and testing,
# 2 is never enrolled at all — it exists to be rejected.
CATALOGUE = [
    ("bar_small", 0, "box", (60, 12, 90), "leather_burgundy"),
    ("bar_wide", 0, "box", (86, 22, 70), "leather"),
    ("slab", 0, "box", (70, 8, 140), "dark_glass"),
    ("cube", 0, "box", (44, 40, 46), "microfibre"),
    ("rod_thin", 0, "cyl", (14, 14, 80), "gold"),
    ("rod_fat", 0, "cyl", (30, 30, 60), "steel"),
    ("disc", 0, "cyl", (52, 52, 14), "copper"),
    ("ring", 0, "ring", (34, 34, 8), "steel"),

    ("wallet", 1, "box", (70, 20, 100), "leather_burgundy"),
    ("phone", 1, "box", (70, 8, 148), "dark_glass"),
    ("pouch", 1, "box", (66, 28, 62), "leather"),
    ("lipstick", 1, "cyl", (18, 18, 76), "gold"),
    ("keys", 1, "ring", (30, 30, 6), "steel"),

    ("stranger_a", 2, "box", (30, 30, 30), "copper"),
    ("stranger_b", 2, "cyl", (40, 40, 40), "microfibre_dark"),
]


def args():
    a = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []

    def val(n, d):
        return int(a[a.index(n) + 1]) if n in a else d
    return val("--samples", 100), val("--size", 96), val("--seed", 7)


def build_subject(shape, size, material, mat_):
    w, d, h = (v * sc.MM for v in size)
    if shape == "box":
        bpy.ops.mesh.primitive_cube_add(size=1)
        o = bpy.context.object
        o.scale = (w, d, h)
        bpy.ops.object.transform_apply(scale=True)
        bpy.ops.object.modifier_add(type="BEVEL")
        o.modifiers["Bevel"].width = 0.002
        o.modifiers["Bevel"].segments = 2
    elif shape == "cyl":
        bpy.ops.mesh.primitive_cylinder_add(radius=w / 2, depth=h, vertices=40)
        o = bpy.context.object
    else:
        bpy.ops.mesh.primitive_torus_add(major_radius=w / 2, minor_radius=d / 10)
        o = bpy.context.object
    sc.assign(o, mat_[material])
    bpy.ops.object.shade_smooth_by_angle(angle=math.radians(40))
    return o


LED_WATTS = 6.0


def setup(size):
    """Camera and lighting as the collar has them, not as a studio would."""
    sc.reset()
    sc.world(background=(0.0, 0.0, 0.0))
    m = sc.palette()
    s = bpy.context.scene
    s.render.engine = "BLENDER_EEVEE"
    s.render.threads_mode = "FIXED"
    s.render.threads = 5
    s.eevee.taa_render_samples = 16
    s.render.resolution_x = s.render.resolution_y = size
    s.render.image_settings.file_format = "PNG"
    s.render.image_settings.color_mode = "BW"
    s.view_settings.view_transform = "Standard"
    # ⚠️ Exposure, not just lamp power. Dark leather under four small LEDs is a
    # genuinely dim scene: at 6 W and neutral exposure the whole set came back
    # with a mean pixel value near 1 and under 2% of pixels above 20. A real IR
    # camera answers this with sensor gain, and this is the same knob.
    s.view_settings.exposure = 3.0

    # ⛔ CANONICAL POSE, REAL OPTICS. The first version derived the camera's
    # position and aim from the collar geometry, and the subjects came out as
    # slivers at the edge of frame: a 69-degree lens pointed down a diagonal is
    # unforgiving, and getting that pose right is a modelling exercise that
    # teaches nothing about recognition. What matters for the images is the
    # OPTICS and the LIGHT, and those are the real ones — 2.6 mm lens on a
    # 3.6 mm sensor, four illuminators at the spacing they have on the board,
    # nothing else lit. The camera looks down its own axis and subjects are
    # placed in front of it.
    #
    # ⚠️ So this set reproduces the imaging conditions, not the mounting. A
    # subject clipped by the mouth of the bag, which the real camera would see
    # often, is not in here.
    c = bpy.data.cameras.new("cam")
    c.lens = 2.6
    c.sensor_width = 3.6
    # ⛔ THE NEAR CLIP PLANE WAS EATING THE SUBJECTS. Blender defaults to
    # clip_start = 0.1 m; the whole point of this camera is that it works at
    # 5-20 cm. Every early render came back with a thin sliver of the object at
    # the far edge and nothing else, and it looked like a lighting problem for
    # three attempts. It was geometry: most of each subject was in front of the
    # near plane and simply not rendered.
    c.clip_start = 0.005
    c.clip_end = 2.0
    o = bpy.data.objects.new("cam", c)
    bpy.context.collection.objects.link(o)
    o.location = (0.0, 0.0, 0.0)
    o.rotation_euler = (0.0, 0.0, 0.0)      # looking down -Z
    s.camera = o

    # ⭐ Four infrared illuminators at the spacing they have on the board,
    # measured from the lens. They are the only light in the scene: inside a
    # closed bag there is no other.
    for i, x in enumerate(sc.LED_X):
        d = bpy.data.lights.new(f"ir{i}", type="POINT")
        d.energy = LED_WATTS
        d.color = (1.0, 0.32, 0.30)
        d.shadow_soft_size = 0.002
        ob = bpy.data.objects.new(f"ir{i}", d)
        bpy.context.collection.objects.link(ob)
        ob.location = ((x - sc.CAMERA_X) * sc.MM, 0.0, 0.0)
    return m


def main():
    samples, size, seed = args()
    random.seed(seed)
    m = setup(size)
    s = bpy.context.scene
    total = 0
    for name, group, shape, dims, material in CATALOGUE:
        folder = os.path.join(OUT, f"{group}_{name}")
        os.makedirs(folder, exist_ok=True)
        for i in range(samples):
            for ob in [x for x in bpy.data.objects if x.name.startswith(
                    ("Cube", "Cylinder", "Torus", "subject"))]:
                bpy.data.objects.remove(ob, do_unlink=True)
            o = build_subject(shape, dims, material, m)
            o.name = "subject"
            # ⚠️ The variation is the point. An object dropped into a bag is
            # never twice in the same pose, never at the same distance, and is
            # always moving — a clean still of it would train the model on a
            # situation that never occurs.
            # Distance varies the apparent size; lateral jitter keeps the
            # subject in frame but never centred. Half-FOV is 34.7 degrees, so
            # at 70 mm the frame is 97 mm wide — +/-22 mm is comfortably inside.
            # 9-20 cm: closer than that and a 100 mm object overflows a
            # 69-degree frame, which the real camera would also do but which
            # teaches the classifier nothing.
            dist = random.uniform(0.090, 0.200)
            o.location = (random.uniform(-0.030, 0.030),
                          random.uniform(-0.030, 0.030),
                          -dist)
            o.rotation_euler = (random.uniform(-0.5, 0.5),
                                random.uniform(-0.4, 0.4),
                                random.uniform(0, 6.28))
            for ob in bpy.data.objects:
                if ob.name.startswith("ir"):
                    ob.data.energy = random.uniform(0.5, 1.4)
            # Motion blur stands in for the fall: at 24 fps in the film, but in
            # the product three frames span 40 ms while the object moves ~15 cm.
            s.render.use_motion_blur = True
            s.render.motion_blur_shutter = random.uniform(0.3, 1.6)
            s.render.filepath = os.path.join(folder, f"{i:04d}.png")
            bpy.ops.render.render(write_still=True)
            total += 1
        print(f"  {name}: {samples} samples")
    print(f"DONE -> {OUT} ({total} images)")


if __name__ == "__main__":
    main()
