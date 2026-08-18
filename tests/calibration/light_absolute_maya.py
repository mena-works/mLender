# -*- coding: utf-8 -*-
"""Export a scene whose lighting has a closed-form answer, for Unreal.

Pairs with light_absolute_unreal.py to settle absolute brightness -- the one
thing render_match_unreal_* could not. It does that by comparing Unreal against
**analytic physics** rather than against Arnold: Arnold's pixel values are in
its own arbitrary scale, which is exactly why a ratio against them can never be
absolute. A Lambertian plane under a small light at a known height has a
luminance that can be computed, and that is an absolute reference.

    "C:\\Program Files\\Autodesk\\Maya2023\\bin\\mayapy.exe" ^
        tests/calibration/light_absolute_maya.py

The geometry is chosen so the answer is simple and the rig is self-checking:

* The camera looks **straight down** from directly above, so the sampled ground
  point sits at a known distance under the light and the image is
  rotationally symmetric. Left/right and top/bottom then both become symmetry
  controls, which the tilted composition in render_match could not offer.
* The light is **small** (20 cm at 150 cm) so treating it as a point source is
  good to well under a percent, and it is made invisible to the camera so it
  does not cover the region being measured.
* Specular is zero and the surface is a plain Lambertian grey, so the expected
  value has no BRDF fitting in it.

Only one package is exported. The variants -- distance, intensity, exposure and
albedo -- are applied on the Unreal side through the receiver's own light code,
so what is under test is the production conversion rather than a copy of it.
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
OUT = os.path.join(tempfile.gettempdir(), "ml_light_absolute")

if TOOL_ROOT not in sys.path:
    sys.path.insert(0, TOOL_ROOT)

GROUND_SIZE = 2000.0
CAMERA_HEIGHT = 1000.0
CAMERA_FOCAL = 50.0
# 20 cm of emitting surface: an Arnold quad spans -1..1, so scale 10 is 20 units.
LIGHT_SCALE = 10.0
LIGHT_HEIGHT = 150.0
LIGHT_INTENSITY = 80.0
LIGHT_EXPOSURE = 1.0
GROUND_ALBEDO = 0.8

# Each variant moves exactly one term of the conversion, so a constant ratio
# across them means every term is right and a ratio that moves names the term.
#
# Distance covers the inverse square law and the squared scene-unit term,
# intensity covers linearity, and exposure covers the 2^stops factor. Between
# them that is the whole light energy conversion.
#
# **There is no albedo variant, and that is measured rather than an oversight.**
# Changing the ground's Material Instance BaseColor from Python stores the value
# -- the read-back confirms it -- but does not reach the render: the sampled
# pixel came back bit-identical to the previous albedo while the prediction
# halved, which reads exactly like a transfer error and is not one. Light
# changes do re-render in the same rig, so the limitation is specific to
# material instance parameters. The albedo the package carries (0.8) is still
# exercised, because it sits in the prediction for every variant.
VARIANTS = [
    {"name": "base", "height": 150.0, "intensity": 80.0, "exposure": 1.0,
     "albedo": 0.8},
    {"name": "twice_the_distance", "height": 300.0, "intensity": 80.0,
     "exposure": 1.0, "albedo": 0.8},
    {"name": "twice_the_intensity", "height": 150.0, "intensity": 160.0,
     "exposure": 1.0, "albedo": 0.8},
    {"name": "one_more_stop", "height": 150.0, "intensity": 80.0,
     "exposure": 2.0, "albedo": 0.8},
    {"name": "quarter_the_distance_and_a_stop_down", "height": 75.0,
     "intensity": 80.0, "exposure": 0.0, "albedo": 0.8},
]


def main():
    cmds.loadPlugin("mtoa", quiet=True)
    if os.path.isdir(OUT):
        shutil.rmtree(OUT)
    os.makedirs(OUT)

    cmds.file(new=True, force=True)
    cmds.currentUnit(linear="cm")
    try:
        cmds.colorManagementPrefs(edit=True, cmEnabled=False)
    except Exception:
        pass

    ground = cmds.polyPlane(
        width=GROUND_SIZE, height=GROUND_SIZE,
        subdivisionsX=1, subdivisionsY=1, name="ground",
    )[0]
    shader = cmds.shadingNode(
        "aiStandardSurface", asShader=True, name="groundShader"
    )
    cmds.setAttr(shader + ".base", 1.0)
    cmds.setAttr(
        shader + ".baseColor",
        GROUND_ALBEDO, GROUND_ALBEDO, GROUND_ALBEDO, type="double3",
    )
    cmds.setAttr(shader + ".specular", 0.0)
    cmds.setAttr(shader + ".metalness", 0.0)
    engine = cmds.sets(
        renderable=True, noSurfaceShader=True, empty=True, name="groundSG"
    )
    cmds.connectAttr(shader + ".outColor", engine + ".surfaceShader", force=True)
    cmds.sets(ground, edit=True, forceElement=engine)

    light = cmds.createNode("aiAreaLight", name="keyLightShape")
    light_tf = cmds.listRelatives(light, parent=True, fullPath=True)[0]
    cmds.setAttr(light + ".aiTranslator", "quad", type="string")
    cmds.setAttr(light + ".intensity", LIGHT_INTENSITY)
    cmds.setAttr(light + ".exposure", LIGHT_EXPOSURE)
    cmds.setAttr(light + ".aiNormalize", True)
    # Invisible to the camera, or the light covers the patch being measured.
    # Reported rather than assumed: if the attribute is not there the Unreal
    # side still works, but a bright quad sits in the middle of the frame.
    camera_visible = None
    for attribute in ("camera", "aiCamera"):
        if cmds.attributeQuery(attribute, node=light, exists=True):
            cmds.setAttr("{0}.{1}".format(light, attribute), 0.0)
            camera_visible = attribute
            break
    cmds.setAttr(light_tf + ".translate", 0.0, LIGHT_HEIGHT, 0.0, type="double3")
    cmds.setAttr(light_tf + ".rotateX", -90.0)
    cmds.setAttr(
        light_tf + ".scale", LIGHT_SCALE, LIGHT_SCALE, LIGHT_SCALE,
        type="double3",
    )

    # Straight down from directly above: rotateX -90 turns the camera's local
    # -Z onto Maya's -Y.
    camera_tf, _shape = cmds.camera(name="nadirCam")
    camera_tf = cmds.rename(camera_tf, "nadirCam")
    camera = cmds.listRelatives(camera_tf, shapes=True, fullPath=True)[0]
    cmds.setAttr(camera + ".focalLength", CAMERA_FOCAL)
    cmds.setAttr(camera + ".renderable", True)
    cmds.setAttr(
        camera_tf + ".translate", 0.0, CAMERA_HEIGHT, 0.0, type="double3"
    )
    cmds.setAttr(camera_tf + ".rotateX", -90.0)

    import mlender_exporter as ml

    result = ml.export_scene(OUT)
    with open(result["json_path"], "r") as handle:
        payload = json.load(handle)

    expected = {
        "package": result["package_folder"],
        "meters_per_maya_unit": payload.get("meters_per_maya_unit"),
        "linear_unit": payload.get("maya_linear_unit"),
        "ground_size": GROUND_SIZE,
        "camera_height": CAMERA_HEIGHT,
        "camera_focal": CAMERA_FOCAL,
        "light_scale": LIGHT_SCALE,
        "light_camera_visibility_attr": camera_visible,
        "base": {
            "height": LIGHT_HEIGHT, "intensity": LIGHT_INTENSITY,
            "exposure": LIGHT_EXPOSURE, "albedo": GROUND_ALBEDO,
        },
        "variants": VARIANTS,
        "exporter_build": ml.BUILD_VERSION,
    }
    with open(os.path.join(OUT, "expected.json"), "w") as handle:
        json.dump(expected, handle, indent=2)

    print("exporter build:", ml.BUILD_VERSION)
    print("package:", result["package_folder"])
    print("light camera visibility attribute:", camera_visible or "NOT FOUND")
    print("lights exported:", result["light_count"])
    print("cameras exported:", result["camera_count"])
    record = payload["lights"][0]
    print("light record intensity/exposure:",
          record["intensity"], record["exposure"])
    print("light record translation:", record["transform"]["translation"])
    print("light record scale:", record["transform"]["scale"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
