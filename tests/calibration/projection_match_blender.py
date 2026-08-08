# -*- coding: utf-8 -*-
"""Blender half of the texture projection measurement.

    "C:\\Program Files\\Blender Foundation\\Blender 5.2\\blender.exe" ^
        --background --factory-startup ^
        --python tests/calibration/projection_match_blender.py -- write

    <maya half>

    "C:\\Program Files\\Blender Foundation\\Blender 5.2\\blender.exe" ^
        --background --factory-startup ^
        --python tests/calibration/projection_match_blender.py -- compare

``write`` produces the four quadrant image the Maya half projects. ``compare``
imports the sphere the Maya half exported, builds each candidate node tree on
it, bakes into the same UV space and reports the mean absolute difference
against Maya's bake.

A rig, not a test: it produces the mapping table rather than checking it. The
candidates are deliberately more than the ones expected to win, because a
mapping that is merely plausible and a mapping that matches are exactly what
this exists to tell apart.
"""

import glob
import json
import math
import os
import sys
import tempfile

import bpy
import mathutils

TOOL_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)
if TOOL_ROOT not in sys.path:
    sys.path.insert(0, TOOL_ROOT)

OUT = os.path.join(tempfile.gettempdir(), "mlender_projection_match")
QUAD = os.path.join(OUT, "quad.png")

# The measured planar construction, which every other candidate starts from:
# -90 about X undoes the Y-up to Z-up conversion the Object output applies.
BASE_ROTATION = (-math.pi / 2.0, 0.0, 0.0)

# Blender projection mode, mapping location, mapping rotation. Several per
# Maya type on purpose.
CANDIDATES = {
    "Planar": [
        ("FLAT", (0.5, 0.5, 0.0), BASE_ROTATION),
        ("FLAT", (0.0, 0.0, 0.0), BASE_ROTATION),
    ],
    "Spherical": [
        ("SPHERE", (0.0, 0.0, 0.0), BASE_ROTATION),
        ("SPHERE", (0.5, 0.0, 0.0), BASE_ROTATION),
        ("SPHERE", (0.0, 0.0, 0.0), (0.0, 0.0, 0.0)),
    ],
    "Cylindrical": [
        ("TUBE", (0.0, 0.0, 0.0), BASE_ROTATION),
        ("TUBE", (0.5, 0.0, 0.0), BASE_ROTATION),
        ("TUBE", (0.0, 0.0, 0.0), (0.0, 0.0, 0.0)),
    ],
    "Ball": [
        ("SPHERE", (0.0, 0.0, 0.0), BASE_ROTATION),
        ("SPHERE", (0.5, 0.0, 0.0), BASE_ROTATION),
    ],
    "Cubic": [
        ("BOX", (0.5, 0.5, 0.5), BASE_ROTATION),
        ("BOX", (0.0, 0.0, 0.0), BASE_ROTATION),
    ],
    "TriPlanar": [
        ("BOX", (0.5, 0.5, 0.5), BASE_ROTATION),
        ("BOX", (0.0, 0.0, 0.0), BASE_ROTATION),
    ],
    "Concentric": [
        ("FLAT", (0.5, 0.5, 0.0), BASE_ROTATION),
    ],
    "Perspective": [
        ("FLAT", (0.5, 0.5, 0.0), BASE_ROTATION),
    ],
}

RESOLUTION = 128
# The scene is in centimetres, which is what the export writes.
METERS_PER_UNIT = 0.01
# Below this the two pictures are the same to the eye; above it they are
# not. The Planar control lands at 0.03 -- bake filtering at the seam,
# not a mapping error -- and every wrong candidate measured so far sits
# above 0.35, so the gap this has to straddle is wide.
MATCH_THRESHOLD = 0.06


# Sixteen cells, every one a different colour. Four quadrants were not
# enough: two spherical candidates that differ by a mirror in u scored
# 0.0216 and 0.0217 against them, which is no answer at all. A fixture that
# cannot tell two candidates apart is not measuring them.
GRID = 4


def cell_colour(column, row):
    """A colour per cell, spread so no two are close in any channel."""
    index = row * GRID + column
    return (
        ((index % 4) / 3.0),
        (((index // 4) % 4) / 3.0),
        (0.25 if index % 2 else 1.0),
    )


def write_quad():
    """The reference image both applications project."""
    if not os.path.isdir(OUT):
        os.makedirs(OUT)
    size = 64
    image = bpy.data.images.new("quad", width=size, height=size, alpha=False)
    pixels = [0.0] * (size * size * 4)
    step = size // GRID
    for y in range(size):
        for x in range(size):
            index = (y * size + x) * 4
            colour = cell_colour(min(x // step, GRID - 1),
                                 min(y // step, GRID - 1))
            pixels[index:index + 4] = [colour[0], colour[1], colour[2], 1.0]
    image.pixels = pixels
    image.filepath_raw = QUAD
    image.file_format = "PNG"
    image.save()
    print("wrote {0}".format(QUAD))


def load_sphere(manifest):
    import mlender_importer as importer

    packages = sorted(
        glob.glob(os.path.join(manifest["package_folder"], "..", "mLender_*"))
    )
    folder = packages[-1] if packages else manifest["package_folder"]
    importer.import_scene_package(folder, import_scale=1.0)
    for obj in bpy.data.objects:
        if obj.type == "MESH" and "projSphere" in obj.name:
            return obj
    raise SystemExit("The exported sphere is not in the package.")


def placement_empty():
    """The place3dTexture stand-in, scaled the way the importer scales one.

    Maya's placement sits at the origin unrotated in this rig, so the only
    thing this carries is the scene unit: object coordinates read in metres
    and Maya projects over Maya units, so the Empty's axes are one Maya unit
    long. Without it the whole sphere falls inside a single texel.
    """
    empty = bpy.data.objects.get("rigPlacement")
    if empty is None:
        empty = bpy.data.objects.new("rigPlacement", None)
        bpy.context.scene.collection.objects.link(empty)
    empty.matrix_world = mathutils.Matrix.Diagonal(
        mathutils.Vector((METERS_PER_UNIT,) * 3)
    ).to_4x4()
    return empty


def build_candidate(obj, mode, location, rotation):
    """An emission material carrying one candidate projection."""
    material = bpy.data.materials.new("candidate")
    material.use_nodes = True
    tree = material.node_tree
    tree.nodes.clear()
    output = tree.nodes.new("ShaderNodeOutputMaterial")
    emission = tree.nodes.new("ShaderNodeEmission")
    image = tree.nodes.new("ShaderNodeTexImage")
    image.image = bpy.data.images.load(QUAD)
    image.projection = mode
    # Measured: Maya clamps a projection at its extent rather than
    # tiling. With Blender's default REPEAT the Planar control scored
    # 0.50, with CLIP 0.36 and with EXTEND 0.03.
    image.extension = "EXTEND"
    coords = tree.nodes.new("ShaderNodeTexCoord")
    # A real placement Empty, scaled the way the importer scales one. Leaving
    # it off looked equivalent -- the placement is at the origin unrotated --
    # and was not: object coordinates come out in metres while Maya projects
    # over half a Maya unit, so the whole sphere landed inside one pixel and
    # every candidate scored the same. The Planar control is what caught it.
    coords.object = placement_empty()
    mapping = tree.nodes.new("ShaderNodeMapping")
    mapping.inputs["Location"].default_value = location
    mapping.inputs["Rotation"].default_value = rotation
    tree.links.new(coords.outputs["Object"], mapping.inputs["Vector"])
    tree.links.new(mapping.outputs["Vector"], image.inputs["Vector"])
    tree.links.new(image.outputs["Color"], emission.inputs["Color"])
    tree.links.new(emission.outputs["Emission"], output.inputs["Surface"])

    target = bpy.data.images.new("bake", width=RESOLUTION, height=RESOLUTION)
    bake_node = tree.nodes.new("ShaderNodeTexImage")
    bake_node.image = target
    tree.nodes.active = bake_node

    obj.data.materials.clear()
    obj.data.materials.append(material)
    return material, target


def bake_candidate(obj, target):
    scene = bpy.context.scene
    scene.render.engine = "CYCLES"
    scene.cycles.samples = 1
    scene.cycles.bake_type = "EMIT"
    scene.render.bake.use_selected_to_active = False
    bpy.ops.object.select_all(action="DESELECT")
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    bpy.ops.object.bake(type="EMIT")
    return list(target.pixels)


def difference(baked, reference_path):
    reference = bpy.data.images.load(reference_path)
    width, height = reference.size
    if width != RESOLUTION or height != RESOLUTION:
        bpy.data.images.remove(reference)
        return None
    other = list(reference.pixels)
    bpy.data.images.remove(reference)

    total = 0.0
    count = 0
    for index in range(0, len(baked), 4):
        for channel in range(3):
            total += abs(baked[index + channel] - other[index + channel])
            count += 1
    return total / max(count, 1)


def compare():
    with open(os.path.join(OUT, "manifest.json"), "r") as handle:
        manifest = json.load(handle)

    print("Blender {0}".format(bpy.app.version_string))
    print("{0:12} {1:8} {2:22} {3:>9}  {4}".format(
        "maya type", "mode", "mapping", "diff", "verdict"))
    table = {}
    for label, reference_path in sorted(manifest["baked"].items()):
        if not reference_path or not os.path.isfile(reference_path):
            print("  {0:12} no Maya bake".format(label))
            continue
        best = None
        for mode, location, rotation in CANDIDATES.get(label, []):
            obj = load_sphere(manifest)
            _material, target = build_candidate(obj, mode, location, rotation)
            baked = bake_candidate(obj, target)
            score = difference(baked, reference_path)
            if score is None:
                continue
            described = "loc{0} rotX{1:+.0f}".format(
                tuple(round(v, 2) for v in location),
                math.degrees(rotation[0]),
            )
            print("{0:12} {1:8} {2:22} {3:9.4f}".format(
                label, mode, described, score))
            if best is None or score < best[0]:
                best = (score, mode, location, rotation)
        if best is None:
            continue
        verdict = "MATCH" if best[0] <= MATCH_THRESHOLD else "no match"
        print("  -> {0:10} best {1:.4f}  {2}".format(label, best[0], verdict))
        table[label] = {
            "mode": best[1],
            "location": list(best[2]),
            "rotation": list(best[3]),
            "difference": best[0],
            "match": best[0] <= MATCH_THRESHOLD,
        }

    with open(os.path.join(OUT, "table.json"), "w") as handle:
        json.dump(table, handle, indent=2)
    print("\nwrote {0}".format(os.path.join(OUT, "table.json")))


def main():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    if argv and argv[0] == "write":
        write_quad()
        return 0
    compare()
    return 0


if __name__ == "__main__":
    sys.exit(main())
