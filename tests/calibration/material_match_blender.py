# -*- coding: utf-8 -*-
"""Import the material chart, render it in Cycles, compare against Arnold.

Read material_match_maya.py first for what this can and cannot answer: the two
BRDFs differ, so small deviations mean nothing and only large structured ones
point at a transfer bug.

    "C:\\Program Files\\Blender Foundation\\Blender 5.2\\blender.exe" ^
        --background --factory-startup --python ^
        tests/calibration/material_match_blender.py
"""
import glob
import json
import os
import sys
import tempfile

import bpy

TOOL_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)
OUT = os.path.join(tempfile.gettempdir(), "za_material_match")

if TOOL_ROOT not in sys.path:
    sys.path.insert(0, TOOL_ROOT)

PATCH = 6

# Above this the two renderers disagree by more than their BRDFs explain, so
# it is worth looking at. Chosen from the light rig's experience: real transfer
# bugs there were factors, not percentages.
SUSPICIOUS = 0.25


def sample_cells(path, cell_count):
    """Average each chart cell, reading the middle of it to avoid the edges."""
    image = bpy.data.images.load(path, check_existing=False)
    width, height = image.size
    pixels = list(image.pixels)
    values = []
    for index in range(cell_count):
        centre_x = int((index + 0.5) * width / cell_count)
        centre_y = height // 2
        totals = [0.0, 0.0, 0.0]
        count = 0
        for y in range(max(0, centre_y - PATCH), min(height, centre_y + PATCH)):
            for x in range(max(0, centre_x - PATCH),
                           min(width, centre_x + PATCH)):
                offset = (y * width + x) * 4
                for channel in range(3):
                    totals[channel] += pixels[offset + channel]
                count += 1
        values.append([total / count if count else 0.0 for total in totals])
    bpy.data.images.remove(image)
    return values


def luminance(rgb):
    return 0.2126 * rgb[0] + 0.7152 * rgb[1] + 0.0722 * rgb[2]


def main():
    with open(os.path.join(OUT, "expected.json"), "r") as handle:
        expected = json.load(handle)
    if not expected.get("arnold_exr") or not os.path.isfile(
        expected["arnold_exr"]
    ):
        raise SystemExit("No Arnold chart. Run material_match_maya.py first.")

    packages = sorted(glob.glob(os.path.join(OUT, "MTB_Z_A_*")))
    import za_lookdev_importer as zi

    print("Blender {0}, importer build {1}".format(
        bpy.app.version_string, zi.BUILD_VERSION))
    result = zi.import_lookdev_package(packages[-1], import_scale=1.0)
    for warning in result["warnings"]:
        print("  warn: {0}".format(warning))

    if bpy.context.scene.camera is None:
        raise SystemExit("The package brought no camera to render through.")

    scene = bpy.context.scene
    scene.render.engine = "CYCLES"
    scene.cycles.samples = 128
    scene.cycles.use_denoising = False
    # Match Arnold's direct-only setup so the surface response is what is
    # being compared.
    scene.cycles.max_bounces = 0
    scene.cycles.diffuse_bounces = 0
    scene.render.resolution_x = expected["resolution"]
    scene.render.resolution_y = expected["height"]
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "OPEN_EXR"
    scene.render.image_settings.color_depth = "32"
    scene.render.image_settings.exr_codec = "NONE"
    scene.view_settings.view_transform = "Standard"
    scene.view_settings.look = "None"

    blender_exr = os.path.join(OUT, "blender_chart.exr")
    scene.render.filepath = blender_exr
    bpy.ops.render.render(write_still=True)

    cells = expected["cells"]
    arnold = sample_cells(expected["arnold_exr"], len(cells))
    blender = sample_cells(blender_exr, len(cells))

    print("\nsurface: {0}   quads turned {1:g} degrees from the camera".format(
        expected.get("surface", "?"), expected.get("tilt_degrees", 0)))
    print("\n{0:16s} {1:>26s} {2:>26s} {3:>9s}".format(
        "cell", "arnold rgb", "blender rgb", "ratio"))
    print("-" * 82)
    flagged = []
    for name, a_rgb, b_rgb in zip(cells, arnold, blender):
        a_lum = luminance(a_rgb)
        b_lum = luminance(b_rgb)
        ratio = (b_lum / a_lum) if a_lum > 1e-6 else float("nan")
        print("{0:16s} {1:>26s} {2:>26s} {3:9.4f}".format(
            name,
            " ".join("{0:7.4f}".format(v) for v in a_rgb),
            " ".join("{0:7.4f}".format(v) for v in b_rgb),
            ratio,
        ))
        if a_lum > 1e-6 and abs(ratio - 1.0) > SUSPICIOUS:
            flagged.append((name, ratio))
        elif a_lum <= 1e-6 and b_lum > 1e-6:
            flagged.append((name, float("inf")))

    # A channel that arrives as zero on both sides would match perfectly, so
    # the paired cells are checked for actually differing. Arnold separating a
    # pair that Blender does not is a channel lost in transfer.
    lookup = dict(zip(cells, zip(arnold, blender)))
    print("\n{0:28s} {1:>12s} {2:>12s}".format(
        "pair (must differ)", "arnold", "blender"))
    print("-" * 56)
    lost = []
    for off_name, on_name in expected.get("pairs") or []:
        if off_name not in lookup or on_name not in lookup:
            continue
        a_off, b_off = lookup[off_name]
        a_on, b_on = lookup[on_name]
        a_delta = abs(luminance(a_on) - luminance(a_off))
        b_delta = abs(luminance(b_on) - luminance(b_off))
        print("{0:28s} {1:12.6f} {2:12.6f}".format(
            "{0} -> {1}".format(off_name, on_name), a_delta, b_delta))
        if a_delta > 1e-6 and b_delta <= a_delta * 0.05:
            lost.append((off_name, on_name, a_delta, b_delta))

    if lost:
        print("\nChannels Arnold reacts to and Blender does not:")
        for off_name, on_name, a_delta, b_delta in lost:
            print("  {0} -> {1}: arnold moved {2:.6f}, blender {3:.6f}".format(
                off_name, on_name, a_delta, b_delta))
        print("That is a channel lost in transfer, not a BRDF difference.")

    # Controls repeat a cell further along the row, so they differ from their
    # twin in position and nothing else. A twin pair that disagrees means the
    # chart is measuring where a quad sits rather than what it is made of, and
    # every other row in the table is then suspect.
    controls = expected.get("controls") or []
    drift = []
    if controls:
        print("\n{0:28s} {1:>12s} {2:>12s}".format(
            "control (must match)", "arnold", "blender"))
        print("-" * 56)
        for twin_name, control_name in controls:
            if twin_name not in lookup or control_name not in lookup:
                continue
            a_twin, b_twin = lookup[twin_name]
            a_ctl, b_ctl = lookup[control_name]
            for label, first, second in (
                ("arnold", luminance(a_twin), luminance(a_ctl)),
                ("blender", luminance(b_twin), luminance(b_ctl)),
            ):
                if max(first, second) > 1e-9 and (
                    abs(first - second) / max(first, second) > 0.05
                ):
                    drift.append((twin_name, control_name, label, first, second))
            print("{0:28s} {1:12.6f} {2:12.6f}".format(
                "{0} == {1}".format(twin_name, control_name),
                abs(luminance(a_twin) - luminance(a_ctl)),
                abs(luminance(b_twin) - luminance(b_ctl))))

    if drift:
        print("\nThe chart is position dependent, so nothing above is a "
              "material result:")
        for twin_name, control_name, label, first, second in drift:
            print("  {0} vs {1} in {2}: {3:.6f} against {4:.6f}".format(
                twin_name, control_name, label, first, second))

    print()
    if drift:
        return 1
    if not flagged and not lost:
        print("No cell differs by more than {0:.0%}, and every paired channel "
              "moves on both sides. Nothing here looks like a transfer "
              "bug.".format(SUSPICIOUS))
        return 0

    print("Cells worth looking at (more than {0:.0%} apart):".format(SUSPICIOUS))
    for name, ratio in flagged:
        print("  {0:16s} blender / arnold = {1:.4f}".format(name, ratio))
    print(
        "\nA difference here is not automatically a bug: the two BRDFs are "
        "not the same model. A factor, an inversion or a channel reading zero "
        "is."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
