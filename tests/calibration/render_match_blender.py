# -*- coding: utf-8 -*-
"""Import the render match package, render it, and compare against Arnold.

The camera comes through the transfer, so both renders look through the same
lens from the same place. Both write linear EXR, so no view transform is in
the way and the numbers are directly comparable.

    "C:\\Program Files\\Blender Foundation\\Blender 5.2\\blender.exe" ^
        --background --factory-startup --python tests/calibration/render_match_blender.py

Run render_match_maya.py first.
"""
import glob
import json
import os
import sys
import tempfile

import bpy

# Three levels up: tests/<group>/<file>.py
TOOL_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)
OUT = os.path.join(tempfile.gettempdir(), "ml_render_match")

if TOOL_ROOT not in sys.path:
    sys.path.insert(0, TOOL_ROOT)

# Patches sampled from both renders, as fractions of the frame.
SAMPLES = {
    "cube front face": (0.50, 0.46),
    "ground left of cube": (0.25, 0.60),
    "ground right of cube": (0.75, 0.60),
    "ground far behind": (0.50, 0.78),
}
PATCH = 5


def patch_average(pixels, width, height, u, v):
    x0 = int(u * width)
    y0 = int((1.0 - v) * height)
    total = 0.0
    count = 0
    for y in range(max(0, y0 - PATCH), min(height, y0 + PATCH)):
        for x in range(max(0, x0 - PATCH), min(width, x0 + PATCH)):
            total += pixels[(y * width + x) * 4]
            count += 1
    return total / count if count else 0.0


def sample(path):
    image = bpy.data.images.load(path, check_existing=False)
    width, height = image.size
    pixels = list(image.pixels)
    values = {
        label: patch_average(pixels, width, height, u, v)
        for label, (u, v) in SAMPLES.items()
    }
    bpy.data.images.remove(image)
    return values


def main():
    with open(os.path.join(OUT, "expected.json"), "r") as handle:
        expected = json.load(handle)
    if not expected.get("arnold_exr") or not os.path.isfile(expected["arnold_exr"]):
        raise SystemExit("No Arnold render. Run render_match_maya.py first.")

    packages = sorted(glob.glob(os.path.join(OUT, "mLender_*")))
    import mlender_importer as zi

    print("Blender {0}, importer build {1}".format(
        bpy.app.version_string, zi.BUILD_VERSION))
    result = zi.import_scene_package(packages[-1], import_scale=1.0)
    for warning in result["warnings"]:
        print("  warn: {0}".format(warning))
    print("  cameras imported: {0}, active {1}".format(
        result["camera_count"], result["active_camera"]))

    if bpy.context.scene.camera is None:
        raise SystemExit("The package brought no camera to render through.")

    scene = bpy.context.scene
    scene.render.engine = "CYCLES"
    scene.cycles.samples = 96
    scene.cycles.use_denoising = False
    # Match Arnold's direct-only setup so the light itself is what is compared.
    scene.cycles.max_bounces = 0
    scene.cycles.diffuse_bounces = 0
    scene.render.resolution_x = expected["resolution"]
    scene.render.resolution_y = expected["resolution"]
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "OPEN_EXR"
    scene.render.image_settings.color_depth = "32"
    scene.render.image_settings.exr_codec = "NONE"
    scene.view_settings.view_transform = "Standard"
    scene.view_settings.look = "None"

    blender_exr = os.path.join(OUT, "blender.exr")
    scene.render.filepath = blender_exr
    bpy.ops.render.render(write_still=True)

    arnold = sample(expected["arnold_exr"])
    blender = sample(blender_exr)

    print("\n{0:24s} {1:>12s} {2:>12s} {3:>10s}".format(
        "sample", "arnold", "blender", "ratio"))
    print("-" * 62)
    ratios = []
    for label in SAMPLES:
        a, b = arnold[label], blender[label]
        ratio = (b / a) if a > 1e-9 else float("nan")
        if a > 1e-6 and b > 1e-6:
            ratios.append(ratio)
        print("{0:24s} {1:12.6g} {2:12.6g} {3:10.4f}".format(label, a, b, ratio))

    print()
    if not ratios:
        print("Both renders are black; nothing to compare.")
        return 1
    low, high = min(ratios), max(ratios)
    mean = sum(ratios) / len(ratios)
    print("blender / arnold: min {0:.4f}  max {1:.4f}  mean {2:.4f}".format(
        low, high, mean))
    print("spread across samples: {0:.2f}%".format(100.0 * (high - low) / mean))
    if abs(mean - 1.0) <= 0.05:
        print("\nMATCH: the transfer reproduces the Arnold lighting.")
        return 0
    print(
        "\nMISMATCH: Blender is {0:.3g}x Arnold. A consistent ratio across "
        "samples points at the intensity conversion; a varying one points at "
        "geometry, falloff or the camera.".format(mean)
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
