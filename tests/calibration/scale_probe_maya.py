# -*- coding: utf-8 -*-
"""Export a cube-and-light scene with known dimensions through the real tool.

The point is to check that the mesh and the lights land at the same scale in
Blender. Meshes travel through the FBX and lights through the JSON, so the two
are scaled by completely separate code paths and can silently disagree.

    "C:\\Program Files\\Autodesk\\Maya2023\\bin\\mayapy.exe" tests/calibration/scale_probe_maya.py
"""
from __future__ import print_function

import json
import os
import shutil
import sys
import tempfile

import maya.standalone

maya.standalone.initialize(name="python")

import maya.cmds as cmds  # noqa: E402

# Three levels up: tests/<group>/<file>.py
TOOL_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)
OUT = os.path.join(tempfile.gettempdir(), "za_scale_probe")

if TOOL_ROOT not in sys.path:
    sys.path.insert(0, TOOL_ROOT)

# Everything in Maya's default centimetres, with round numbers so a scale
# mistake in Blender is obvious by eye.
CUBE_SIZE = 10.0
LIGHT_HEIGHT = 100.0
LIGHT_SCALE = 20.0
LIGHT_INTENSITY = 50.0
LIGHT_EXPOSURE = 0.0


def main():
    cmds.loadPlugin("mtoa", quiet=True)
    if os.path.isdir(OUT):
        shutil.rmtree(OUT)
    os.makedirs(OUT)

    cmds.file(new=True, force=True)
    cmds.currentUnit(linear="cm")

    cube = cmds.polyCube(
        width=CUBE_SIZE, height=CUBE_SIZE, depth=CUBE_SIZE, name="probeCube"
    )[0]
    shader = cmds.shadingNode("aiStandardSurface", asShader=True, name="probeShader")
    cmds.setAttr(shader + ".base", 1.0)
    cmds.setAttr(shader + ".baseColor", 1.0, 1.0, 1.0, type="double3")
    cmds.setAttr(shader + ".specular", 0.0)
    engine = cmds.sets(renderable=True, noSurfaceShader=True, empty=True,
                       name="probeSG")
    cmds.connectAttr(shader + ".outColor", engine + ".surfaceShader", force=True)
    cmds.sets(cube, edit=True, forceElement=engine)

    light = cmds.createNode("aiAreaLight", name="probeLightShape")
    light_tf = cmds.listRelatives(light, parent=True, fullPath=True)[0]
    cmds.setAttr(light + ".aiTranslator", "quad", type="string")
    cmds.setAttr(light + ".intensity", LIGHT_INTENSITY)
    cmds.setAttr(light + ".exposure", LIGHT_EXPOSURE)
    cmds.setAttr(light + ".aiNormalize", True)
    cmds.setAttr(light_tf + ".translate", 0.0, LIGHT_HEIGHT, 0.0, type="double3")
    cmds.setAttr(light_tf + ".rotateX", -90.0)
    cmds.setAttr(
        light_tf + ".scale", LIGHT_SCALE, LIGHT_SCALE, LIGHT_SCALE, type="double3"
    )

    import za_lookdev_exporter as za

    result = za.export_lookdev(OUT)
    with open(result["json_path"], "r") as handle:
        payload = json.load(handle)

    expected = {
        "linear_unit": payload.get("maya_linear_unit"),
        "meters_per_maya_unit": payload.get("meters_per_maya_unit"),
        "cube_size_maya": CUBE_SIZE,
        "light_height_maya": LIGHT_HEIGHT,
        "light_scale_maya": LIGHT_SCALE,
        "light_intensity": LIGHT_INTENSITY,
        "light_exposure": LIGHT_EXPOSURE,
        "package": result["package_folder"],
    }
    with open(os.path.join(OUT, "expected.json"), "w") as handle:
        json.dump(expected, handle, indent=2)

    print("MtoA:", cmds.pluginInfo("mtoa", query=True, version=True))
    print("exporter build:", za.BUILD_VERSION)
    for key, value in sorted(expected.items()):
        print("  {0:22s} {1}".format(key, value))

    light_record = payload["lights"][0]
    print("\nlight record as exported")
    print("  intensity        ", light_record["intensity"])
    print("  exposure         ", light_record["exposure"])
    print("  effective        ", light_record["effective_intensity"])
    print("  translation      ", light_record["transform"]["translation"])
    print("  scale            ", light_record["transform"]["scale"])
    print("  normalize        ", light_record["parameters"].get("normalize"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
