# -*- coding: utf-8 -*-
"""Export a scene through the real pipeline and render it with Arnold.

Pairs with render_match_blender.py to answer one question end to end: does a
light that looks a certain way in Arnold look the same in Blender after the
transfer? Everything is neutral and colour management is off, so the two
renders are directly comparable linear values rather than tone mapped images.

    "C:\\Program Files\\Autodesk\\Maya2023\\bin\\mayapy.exe" tests/calibration/render_match_maya.py
"""
from __future__ import print_function

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

import maya.standalone

maya.standalone.initialize(name="python")

import maya.cmds as cmds  # noqa: E402

# Three levels up: tests/<group>/<file>.py
TOOL_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)
OUT = os.path.join(tempfile.gettempdir(), "za_render_match")
KICK = r"C:\Program Files\Autodesk\Arnold\maya2023\bin\kick.exe"

if TOOL_ROOT not in sys.path:
    sys.path.insert(0, TOOL_ROOT)

RESOLUTION = 160
GROUND_SIZE = 400.0
CUBE_SIZE = 40.0
LIGHT_HEIGHT = 150.0
LIGHT_SCALE = 30.0
LIGHT_INTENSITY = 80.0
LIGHT_EXPOSURE = 1.0
CAMERA_POSITION = (0.0, 90.0, 260.0)
CAMERA_PITCH = -14.0


def white_shader(name):
    shader = cmds.shadingNode("aiStandardSurface", asShader=True, name=name)
    cmds.setAttr(shader + ".base", 1.0)
    cmds.setAttr(shader + ".baseColor", 0.8, 0.8, 0.8, type="double3")
    cmds.setAttr(shader + ".specular", 0.0)
    cmds.setAttr(shader + ".metalness", 0.0)
    return shader


def assign(transform, shader, name):
    engine = cmds.sets(
        renderable=True, noSurfaceShader=True, empty=True, name=name
    )
    cmds.connectAttr(shader + ".outColor", engine + ".surfaceShader", force=True)
    cmds.sets(transform, edit=True, forceElement=engine)


def build_scene():
    cmds.file(new=True, force=True)
    cmds.currentUnit(linear="cm")
    cmds.loadPlugin("mtoa", quiet=True)
    try:
        cmds.colorManagementPrefs(edit=True, cmEnabled=False)
    except Exception:
        pass

    ground = cmds.polyPlane(
        width=GROUND_SIZE, height=GROUND_SIZE,
        subdivisionsX=1, subdivisionsY=1, name="ground",
    )[0]
    assign(ground, white_shader("groundShader"), "groundSG")

    cube = cmds.polyCube(
        width=CUBE_SIZE, height=CUBE_SIZE, depth=CUBE_SIZE, name="probeCube"
    )[0]
    cmds.setAttr(cube + ".translateY", CUBE_SIZE / 2.0)
    assign(cube, white_shader("cubeShader"), "cubeSG")

    light = cmds.createNode("aiAreaLight", name="keyLightShape")
    light_tf = cmds.listRelatives(light, parent=True, fullPath=True)[0]
    cmds.setAttr(light + ".aiTranslator", "quad", type="string")
    cmds.setAttr(light + ".intensity", LIGHT_INTENSITY)
    cmds.setAttr(light + ".exposure", LIGHT_EXPOSURE)
    cmds.setAttr(light + ".aiNormalize", True)
    cmds.setAttr(light + ".aiSamples", 4)
    cmds.setAttr(light_tf + ".translate", 0.0, LIGHT_HEIGHT, 0.0, type="double3")
    cmds.setAttr(light_tf + ".rotateX", -90.0)
    cmds.setAttr(
        light_tf + ".scale", LIGHT_SCALE, LIGHT_SCALE, LIGHT_SCALE, type="double3"
    )

    camera_tf = cmds.rename(cmds.camera()[0], "shotCam")
    camera = cmds.listRelatives(camera_tf, shapes=True, fullPath=True)[0]
    cmds.setAttr(camera + ".focalLength", 50.0)
    cmds.setAttr(camera + ".renderable", True)
    cmds.setAttr(camera_tf + ".translate", *CAMERA_POSITION, type="double3")
    cmds.setAttr(camera_tf + ".rotateX", CAMERA_PITCH)
    return camera


def render_with_kick(camera):
    """Export an ass and render it, so the output is a real linear EXR."""
    cmds.setAttr("defaultRenderGlobals.currentRenderer", "arnold", type="string")
    try:
        import mtoa.core as core

        core.createOptions()
    except Exception:
        pass
    for plug, value in (
        # Direct lighting only, so the comparison isolates the light itself.
        ("defaultArnoldRenderOptions.GIDiffuseDepth", 0),
        ("defaultArnoldRenderOptions.GISpecularDepth", 0),
        ("defaultArnoldRenderOptions.AASamples", 5),
        ("defaultArnoldRenderOptions.denoiseBeauty", 0),
        ("defaultResolution.width", RESOLUTION),
        ("defaultResolution.height", RESOLUTION),
        ("defaultResolution.deviceAspectRatio", 1.0),
        ("defaultResolution.pixelAspect", 1.0),
    ):
        try:
            cmds.setAttr(plug, value)
        except Exception:
            pass

    ass_path = os.path.join(OUT, "scene.ass").replace("\\", "/")
    # lightLinks and shadowLinks must be 0. With them on, the export writes
    # "use_light_group on" against an empty group, which means every surface
    # is lit by exactly nothing and the render comes out black.
    cmds.arnoldExportAss(
        filename=ass_path, selected=False, mask=255,
        boundingBox=True, cam=camera,
        lightLinks=0, shadowLinks=0,
    )

    # The exported ass references a denoiser node it does not contain.
    with open(ass_path, "r") as handle:
        text = handle.read()
    text = re.sub(r'^ input "defaultArnoldDenoiser"\n', "", text, flags=re.M)
    with open(ass_path, "w") as handle:
        handle.write(text)

    exr = os.path.join(OUT, "arnold.exr")
    process = subprocess.run(
        [KICK, "-i", ass_path, "-o", exr, "-r", str(RESOLUTION), str(RESOLUTION),
         "-dw", "-nostdin", "-v", "1"],
        capture_output=True, text=True,
    )
    for line in (process.stdout + process.stderr).splitlines():
        if "ERROR" in line or "licen" in line.lower():
            print("  kick:", line.strip())
    return exr if os.path.isfile(exr) else ""


def main():
    if os.path.isdir(OUT):
        shutil.rmtree(OUT)
    os.makedirs(OUT)

    camera = build_scene()

    import za_lookdev_exporter as za

    result = za.export_lookdev(OUT)
    print("exporter build:", za.BUILD_VERSION)
    print("package:", result["package_folder"])
    print("cameras exported:", result["camera_count"])

    exr = render_with_kick(camera)
    print("arnold render:", exr or "FAILED")

    with open(os.path.join(OUT, "expected.json"), "w") as handle:
        json.dump(
            {
                "resolution": RESOLUTION,
                "light_intensity": LIGHT_INTENSITY,
                "light_exposure": LIGHT_EXPOSURE,
                "arnold_exr": exr,
                "package": result["package_folder"],
            },
            handle,
            indent=2,
        )
    return 0 if exr else 1


if __name__ == "__main__":
    sys.exit(main())
