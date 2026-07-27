# -*- coding: utf-8 -*-
"""Import the scale probe package and measure what actually landed.

Meshes come in through the FBX and lights through the JSON, so their scales
are set by unrelated code. If they disagree the light-to-object distance is
wrong and no amount of correct energy conversion will match the Maya render.

    "C:\\Program Files\\Blender Foundation\\Blender 5.2\\blender.exe" ^
        --background --factory-startup --python tests/scale_probe_blender.py

Run scale_probe_maya.py first.
"""
import glob
import json
import math
import os
import sys
import tempfile

import bpy

TOOL_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROBE = os.path.join(tempfile.gettempdir(), "za_scale_probe")

if TOOL_ROOT not in sys.path:
    sys.path.insert(0, TOOL_ROOT)

failures = []


def check(label, condition, detail=""):
    if condition:
        print("  ok    {0}".format(label))
    else:
        failures.append("{0} {1}".format(label, detail))
        print("  FAIL  {0}  {1}".format(label, detail))


def main():
    with open(os.path.join(PROBE, "expected.json"), "r") as handle:
        expected = json.load(handle)
    packages = sorted(glob.glob(os.path.join(PROBE, "MTB_Z_A_*")))
    if not packages:
        raise SystemExit("No package. Run scale_probe_maya.py first.")

    import za_lookdev_importer as zi

    print("Blender {0}, importer build {1}".format(
        bpy.app.version_string, zi.BUILD_VERSION))
    result = zi.import_lookdev_package(packages[-1], import_scale=1.0)
    for warning in result["warnings"]:
        print("  warn: {0}".format(warning))

    unit = expected["meters_per_maya_unit"]
    print("\nmaya scene")
    print("  linear unit           {0}, {1} m per unit".format(
        expected["linear_unit"], unit))
    print("  cube                  {0} units".format(expected["cube_size_maya"]))
    print("  light height          {0} units".format(expected["light_height_maya"]))

    mesh = next((o for o in bpy.data.objects if o.type == "MESH"), None)
    light = next((o for o in bpy.data.objects if o.type == "LIGHT"), None)
    check("cube imported", mesh is not None)
    check("light imported", light is not None)
    if mesh is None or light is None:
        return 1

    size = max(mesh.dimensions)
    height = light.matrix_world.translation.z
    print("\nwhat landed in blender")
    print("  cube largest dimension  {0:.6g}".format(size))
    print("  light height            {0:.6g}".format(height))
    print("  light energy            {0:.6g} W".format(light.data.energy))
    print("  light size              {0:.6g}".format(getattr(light.data, "size", 0.0)))

    # The ratio is what matters: both should have shrunk by the same factor.
    mesh_factor = size / expected["cube_size_maya"]
    light_factor = height / expected["light_height_maya"]
    print("\nscale factors applied")
    print("  to the mesh   {0:.6g}".format(mesh_factor))
    print("  to the light  {0:.6g}".format(light_factor))
    print("  disagreement  {0:.6g}x".format(
        light_factor / mesh_factor if mesh_factor else float("inf")))

    check(
        "mesh and light use the same scale",
        abs(light_factor - mesh_factor) <= 1e-4 * max(mesh_factor, light_factor),
        "mesh {0:.6g} vs light {1:.6g}".format(mesh_factor, light_factor),
    )

    # Distance from the light to the top of the cube drives the illumination.
    gap_maya = expected["light_height_maya"] - expected["cube_size_maya"] / 2.0
    gap_blender = height - size / 2.0
    print("\nlight to cube top")
    print("  maya     {0:.6g} units".format(gap_maya))
    print("  blender  {0:.6g}".format(gap_blender))
    check(
        "the gap scaled consistently",
        abs(gap_blender / gap_maya - mesh_factor) <= 1e-3 * mesh_factor,
        "{0:.6g} vs expected {1:.6g}".format(
            gap_blender / gap_maya, mesh_factor),
    )

    effective = expected["light_intensity"] * (2.0 ** expected["light_exposure"])
    check(
        "energy is effective intensity times pi",
        abs(light.data.energy - effective * math.pi) < 1e-3,
        "{0:.6g} vs {1:.6g}".format(light.data.energy, effective * math.pi),
    )

    print()
    if failures:
        print("FAILURES ({0}):".format(len(failures)))
        for item in failures:
            print("  - {0}".format(item))
        return 1
    print("scale is consistent")
    return 0


if __name__ == "__main__":
    sys.exit(main())
