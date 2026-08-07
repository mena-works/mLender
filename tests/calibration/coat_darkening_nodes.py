# -*- coding: utf-8 -*-
"""Check the coat darkening node chain against the closed form it copies.

There are two paths through ``apply_coat_darkening``. A flat base colour is
darkened in Python, one line of arithmetic. A textured one cannot be, so the
same curve is built out of eight Vector Math nodes.

Nothing else compares the two. The chart next door only uses flat colours, so
a swapped operand in the node chain, a subtract the wrong way round or a
divide upside down, would render wrong and no test would say so.

This drives an image of a single constant colour through the textured path and
the same colour through the flat path, renders both under the same dome and
requires the two to agree. A constant image makes the paths equivalent by
construction, so any difference is the chain getting the algebra wrong.

    "C:\\Program Files\\Blender Foundation\\Blender 5.2\\blender.exe" ^
        --background --factory-startup --python ^
        tests/calibration/coat_darkening_nodes.py
"""
import os
import sys
import tempfile

import bpy

TOOL_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)
if TOOL_ROOT not in sys.path:
    sys.path.insert(0, TOOL_ROOT)

OUT = os.path.join(tempfile.gettempdir(), "za_coat_darkening")

# Values worth separating: a dark base is darkened hard, a bright one barely,
# and full coverage differs from partial. A single mid grey would hide an
# error that only shows at one end.
CASES = [
    (0.10, 1.0, 1.0),
    (0.30, 1.0, 1.0),
    (0.90, 1.0, 1.0),
    (0.30, 0.5, 1.0),
    (0.30, 1.0, 0.5),
]

failures = []


def check(label, ok, detail=""):
    if ok:
        print("  ok    {0}".format(label))
    else:
        failures.append("{0} {1}".format(label, detail))
        print("  FAIL  {0}  {1}".format(label, detail))


def constant_image(name, value):
    image = bpy.data.images.new(name, width=4, height=4, alpha=False,
                                float_buffer=True)
    image.colorspace_settings.name = "Non-Color"
    image.pixels = [value, value, value, 1.0] * 16
    return image


def build_material(name, channels, image=None):
    """Build through the importer itself, so the code under test is the code."""
    from za_lookdev_importer import materials

    material = bpy.data.materials.new(name)
    material.use_nodes = True
    material.node_tree.nodes.clear()
    nodes = material.node_tree.nodes
    links = material.node_tree.links

    output = nodes.new("ShaderNodeOutputMaterial")
    bsdf = nodes.new("ShaderNodeBsdfPrincipled")
    links.new(bsdf.outputs["BSDF"], output.inputs["Surface"])

    base = materials.principled_input(bsdf, "base_color")
    if image is None:
        base.default_value = channels["_colour"] + (1.0,)
    else:
        texture = nodes.new("ShaderNodeTexImage")
        texture.image = image
        texture.interpolation = "Closest"
        links.new(texture.outputs["Color"], base)

    for channel, socket_key in (("coat", "coat"), ("coat_ior", "coat_ior")):
        socket = materials.principled_input(bsdf, socket_key)
        if socket is not None:
            socket.default_value = channels[channel]["value"]

    materials.apply_coat_darkening(material, bsdf, channels, [])
    return material


def quad(name, material, x):
    bpy.ops.mesh.primitive_plane_add(size=1.6, location=(x, 0.0, 0.0),
                                     rotation=(1.5707963, 0.0, 0.0))
    obj = bpy.context.active_object
    obj.name = name
    obj.data.materials.append(material)
    return obj


def sample(path, count):
    image = bpy.data.images.load(path, check_existing=False)
    width, height = image.size
    pixels = list(image.pixels)
    values = []
    for index in range(count):
        x = int((index + 0.5) * width / count)
        y = height // 2
        offset = (y * width + x) * 4
        values.append(pixels[offset])
    bpy.data.images.remove(image)
    return values


def main():
    if not os.path.isdir(OUT):
        os.makedirs(OUT)
    bpy.ops.wm.read_factory_settings(use_empty=True)

    world = bpy.data.worlds.new("dome")
    world.use_nodes = True
    background = world.node_tree.nodes["Background"]
    background.inputs[0].default_value = (1.0, 1.0, 1.0, 1.0)
    background.inputs[1].default_value = 1.0
    bpy.context.scene.world = world

    columns = []
    for index, (albedo, weight, darkening) in enumerate(CASES):
        channels = {
            "_colour": (albedo, albedo, albedo),
            "coat": {"value": weight},
            "coat_ior": {"value": 1.6},
            "coat_darkening": {"value": darkening},
        }
        flat = build_material("flat_{0}".format(index), dict(channels))
        mapped = build_material(
            "mapped_{0}".format(index),
            dict(channels),
            constant_image("img_{0}".format(index), albedo),
        )
        # Two quads per case, side by side: flat then mapped.
        columns.append(("flat", index, albedo, weight, darkening))
        columns.append(("mapped", index, albedo, weight, darkening))
        quad("flat_{0}".format(index), flat, len(columns) - 2 - len(CASES))
        quad("mapped_{0}".format(index), mapped, len(columns) - 1 - len(CASES))

    for index, obj in enumerate(
        sorted(bpy.data.objects, key=lambda o: o.location.x)
    ):
        obj.location.x = index - (len(columns) - 1) / 2.0

    camera_data = bpy.data.cameras.new("cam")
    camera_data.type = "ORTHO"
    camera_data.ortho_scale = float(len(columns))
    camera = bpy.data.objects.new("cam", camera_data)
    camera.location = (0.0, -10.0, 0.0)
    camera.rotation_euler = (1.5707963, 0.0, 0.0)
    bpy.context.scene.collection.objects.link(camera)
    bpy.context.scene.camera = camera

    scene = bpy.context.scene
    scene.render.engine = "CYCLES"
    scene.cycles.samples = 64
    scene.render.resolution_x = 64 * len(columns)
    scene.render.resolution_y = 64
    scene.render.image_settings.file_format = "OPEN_EXR"
    scene.render.image_settings.color_depth = "32"
    scene.render.filepath = os.path.join(OUT, "chain")
    scene.view_settings.view_transform = "Standard"
    bpy.ops.render.render(write_still=True)

    values = sample(scene.render.filepath + ".exr", len(columns))
    print("\ncase                       flat      mapped     ratio")
    print("-" * 56)
    for index in range(len(CASES)):
        albedo, weight, darkening = CASES[index]
        flat_value = values[index * 2]
        mapped_value = values[index * 2 + 1]
        ratio = mapped_value / flat_value if flat_value else float("inf")
        print("albedo {0:.2f} coat {1:.2f} dark {2:.2f}  {3:8.5f}  {4:8.5f}"
              "  {5:8.5f}".format(albedo, weight, darkening,
                                  flat_value, mapped_value, ratio))
        check(
            "node chain matches the closed form at albedo {0:.2f}, coat "
            "{1:.2f}, darkening {2:.2f}".format(albedo, weight, darkening),
            abs(ratio - 1.0) < 0.01,
            ratio,
        )

    print()
    if failures:
        print("FAILURES ({0}):".format(len(failures)))
        for item in failures:
            print("  - {0}".format(item))
        return 1
    print("the textured path reproduces the flat one")
    return 0


if __name__ == "__main__":
    sys.exit(main())
