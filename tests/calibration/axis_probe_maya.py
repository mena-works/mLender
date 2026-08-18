# -*- coding: utf-8 -*-
"""Export a scene whose every axis carries a different number, for Unreal.

Maya is Y-up right-handed, Unreal is Z-up left-handed, and the two halves of a
package reach Unreal by completely separate routes: mesh transforms ride the
FBX and Unreal's own importer converts them, while light and camera transforms
ride the JSON and this tool converts them. Either route can be wrong on its
own, so the rig measures both from one scene.

Nothing here is symmetric, on purpose. The repository already learned this the
hard way once: an animation test that asserted only on X could not see an axis
bug at all, because X maps to X under every convention worth considering.

    "C:\\Program Files\\Autodesk\\Maya2023\\bin\\mayapy.exe" ^
        tests/calibration/axis_probe_maya.py

Writes <temp>/ml_axis_probe/expected.json beside the package, which
axis_probe_unreal.py reads back.
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
OUT = os.path.join(tempfile.gettempdir(), "ml_axis_probe")

if TOOL_ROOT not in sys.path:
    sys.path.insert(0, TOOL_ROOT)

CUBE_SIZE = 4.0
# One cube per axis, each at a distance nothing else uses, so the axis mapping
# can be read straight off the answer instead of solved for.
AXIS_POSITIONS = {
    "probeAxisX": (30.0, 0.0, 0.0),
    "probeAxisY": (0.0, 40.0, 0.0),
    "probeAxisZ": (0.0, 0.0, 50.0),
}
# A general rotation: no two angles equal and none a multiple of 90, so a
# wrong Euler order or a mirrored basis cannot survive it.
ROTATED_POSITION = (10.0, 20.0, 30.0)
ROTATED_EULER = (15.0, 30.0, 45.0)
# Non-uniform scale, because a uniform one hides an axis swap in the scale.
ROTATED_SCALE = (1.0, 2.0, 3.0)

LIGHT_POSITION = (11.0, 22.0, 33.0)
LIGHT_EULER = (-35.0, 25.0, 10.0)
LIGHT_SCALE = 20.0
LIGHT_INTENSITY = 50.0

CAMERA_POSITION = (60.0, 70.0, 80.0)
CAMERA_EULER = (-20.0, 40.0, 5.0)
CAMERA_FOCAL = 50.0


def _cube(name, position, euler=None, scale=None):
    cube = cmds.polyCube(
        width=CUBE_SIZE, height=CUBE_SIZE, depth=CUBE_SIZE, name=name
    )[0]
    cmds.setAttr(cube + ".translate", *position, type="double3")
    if euler:
        cmds.setAttr(cube + ".rotate", *euler, type="double3")
    if scale:
        cmds.setAttr(cube + ".scale", *scale, type="double3")
    return cube


def main():
    cmds.loadPlugin("mtoa", quiet=True)
    if os.path.isdir(OUT):
        shutil.rmtree(OUT)
    os.makedirs(OUT)

    cmds.file(new=True, force=True)
    cmds.currentUnit(linear="cm")

    shader = cmds.shadingNode(
        "aiStandardSurface", asShader=True, name="probeShader"
    )
    engine = cmds.sets(
        renderable=True, noSurfaceShader=True, empty=True, name="probeSG"
    )
    cmds.connectAttr(shader + ".outColor", engine + ".surfaceShader", force=True)

    cubes = []
    for name, position in sorted(AXIS_POSITIONS.items()):
        cubes.append(_cube(name, position))
    cubes.append(
        _cube("probeRotated", ROTATED_POSITION, ROTATED_EULER, ROTATED_SCALE)
    )
    for cube in cubes:
        cmds.sets(cube, edit=True, forceElement=engine)

    light = cmds.createNode("aiAreaLight", name="probeLightShape")
    light_tf = cmds.listRelatives(light, parent=True, fullPath=True)[0]
    cmds.setAttr(light + ".aiTranslator", "quad", type="string")
    cmds.setAttr(light + ".intensity", LIGHT_INTENSITY)
    cmds.setAttr(light + ".exposure", 0.0)
    cmds.setAttr(light + ".aiNormalize", True)
    cmds.setAttr(light_tf + ".translate", *LIGHT_POSITION, type="double3")
    cmds.setAttr(light_tf + ".rotate", *LIGHT_EULER, type="double3")
    cmds.setAttr(
        light_tf + ".scale", LIGHT_SCALE, LIGHT_SCALE, LIGHT_SCALE,
        type="double3"
    )

    camera_tf, camera_shape = cmds.camera(name="probeCamera")
    camera_tf = cmds.rename(camera_tf, "probeCamera")
    cmds.setAttr(camera_tf + ".translate", *CAMERA_POSITION, type="double3")
    cmds.setAttr(camera_tf + ".rotate", *CAMERA_EULER, type="double3")
    cmds.setAttr(camera_tf + ".focalLength", CAMERA_FOCAL)
    cmds.setAttr(camera_tf + ".renderable", True)

    import mlender_exporter as ml

    result = ml.export_scene(OUT)
    with open(result["json_path"], "r") as handle:
        payload = json.load(handle)

    expected = {
        "package": result["package_folder"],
        "fbx": result["fbx_path"],
        "linear_unit": payload.get("maya_linear_unit"),
        "meters_per_maya_unit": payload.get("meters_per_maya_unit"),
        "cube_size_maya": CUBE_SIZE,
        "axis_positions_maya": AXIS_POSITIONS,
        "rotated_position_maya": ROTATED_POSITION,
        "rotated_euler_maya": ROTATED_EULER,
        "rotated_scale_maya": ROTATED_SCALE,
        "light_position_maya": LIGHT_POSITION,
        "light_euler_maya": LIGHT_EULER,
        "light_scale_maya": LIGHT_SCALE,
        "camera_position_maya": CAMERA_POSITION,
        "camera_euler_maya": CAMERA_EULER,
        "camera_focal_maya": CAMERA_FOCAL,
        "exporter_build": ml.BUILD_VERSION,
    }
    with open(os.path.join(OUT, "expected.json"), "w") as handle:
        json.dump(expected, handle, indent=2)

    print("exporter build:", ml.BUILD_VERSION)
    print("package:", result["package_folder"])
    print("\nwhat the JSON carries for the light")
    light_record = payload["lights"][0]
    print("  translation ", light_record["transform"]["translation"])
    print("  rotation    ", light_record["transform"].get("rotation"))
    print("  scale       ", light_record["transform"]["scale"])
    print("  matrix      ", light_record["transform"].get("matrix"))
    print("\nwhat the JSON carries for the camera")
    camera_record = payload["cameras"][0]
    print("  translation ", camera_record["transform"]["translation"])
    print("  rotation    ", camera_record["transform"].get("rotation"))
    print("  focal       ", camera_record.get("focal_length"))
    print("\nmesh records (transforms are NOT here; the FBX carries them)")
    for record in payload["meshes"]:
        print("  ", record["mesh"], "groups:", record.get("groups"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
