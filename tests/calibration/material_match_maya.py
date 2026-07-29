# -*- coding: utf-8 -*-
"""Render a material chart in Arnold, for material_match_blender.py to compare.

The light rig next door deliberately uses neutral white materials so that the
light is what is being measured. This is the other half: fixed neutral light,
varying materials.

What this can and cannot answer matters. Arnold's standard_surface and
Blender's Principled are different BRDFs, so an exact pixel match is not
expected and a few per cent apart means nothing. What it does catch is
transfer error: a channel that never arrived, a value that arrived inverted,
a weight that landed on the wrong socket. Those show up as large, structured
deviations, not as noise.

The chart is flat quads facing the camera with the light behind it, so every
sample is at normal incidence. That removes geometry and shading normals from
the comparison and leaves the material response on its own.

    "C:\\Program Files\\Autodesk\\Maya2023\\bin\\mayapy.exe" ^
        tests/calibration/material_match_maya.py
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

TOOL_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)
OUT = os.path.join(tempfile.gettempdir(), "za_material_match")
KICK = r"C:\Program Files\Autodesk\Arnold\maya2023\bin\kick.exe"

if TOOL_ROOT not in sys.path:
    sys.path.insert(0, TOOL_ROOT)

# Which surface to chart, and how far the quads are turned from the camera.
# Two runs rather than two rows: the multi row version of this rig produced
# numbers I could not reconcile with the single row one, and rather than ship
# an instrument I did not trust, each angle now gets its own run of exactly
# the chart that is known to be sound.
#
#   material_match_maya.py                          aiStandardSurface, head on
#   material_match_maya.py aiStandardSurface 70     the same at grazing
#   material_match_maya.py aiOpenPBRSurface         the other surface
SURFACE = sys.argv[1] if len(sys.argv) > 1 else "aiStandardSurface"
TILT_DEGREES = float(sys.argv[2]) if len(sys.argv) > 2 else 0.0

# Semantic name -> what each surface calls it. OpenPBR renames half of these
# and had never been checked against a render.
ATTRS = {
    "aiStandardSurface": {
        "base_color": "baseColor", "specular": "specular",
        "roughness": "specularRoughness", "metalness": "metalness",
        "coat": "coat", "coat_roughness": "coatRoughness",
        "sheen": "sheen", "sheen_roughness": "sheenRoughness",
        "emission": "emission", "emission_color": "emissionColor",
        "opacity": "opacity",
    },
    "aiOpenPBRSurface": {
        "base_color": "baseColor", "specular": "specularWeight",
        "roughness": "specularRoughness", "metalness": "baseMetalness",
        "coat": "coatWeight", "coat_roughness": "coatRoughness",
        # OpenPBR calls the sheen lobe fuzz and states emission in nits.
        "sheen": "fuzzWeight", "sheen_roughness": "fuzzRoughness",
        "emission": "emissionLuminance", "emission_color": "emissionColor",
        "opacity": "geometryOpacity",
    },
}

# OpenPBR emission is a luminance in nits and the importer divides by
# OPENPBR_EMISSION_LUMINANCE_SCALE to reach a Blender strength. This chart
# is what measured that constant: at 100 the two sides were exactly ten
# times apart, and 1000 makes them agree at every luminance tried.
OPENPBR_EMISSION_NITS = 100.0

RESOLUTION = 1024
CELL = 10.0          # world width of one chart cell
LIGHT_DISTANCE = 60.0
LIGHT_INTENSITY = 40.0

# Each entry is one cell. Two things are being asked of this chart, and the
# second is why several cells come in pairs.
#
# Matching values alone is not enough: a channel that silently arrives as zero
# on both sides also matches. So for every channel worth doubting there is an
# off cell and an on cell differing in exactly that channel. If the pair is
# identical in Arnold the chart is wrong; if it is identical in Blender but not
# in Arnold, the channel did not survive the transfer.
BASE = {"base_color": (0.3, 0.3, 0.3), "specular": 0.0, "roughness": 0.4}


def _cell(**overrides):
    values = dict(BASE)
    values.update(overrides)
    return values


MATERIALS = [
    ("grey_diffuse", _cell(base_color=(0.5, 0.5, 0.5))),
    ("dark_diffuse", _cell(base_color=(0.18, 0.18, 0.18))),
    ("red_diffuse", _cell(base_color=(0.8, 0.15, 0.1))),

    ("spec_off", _cell(specular=0.0, roughness=0.1)),
    ("spec_on", _cell(specular=1.0, roughness=0.1)),
    ("spec_rough", _cell(specular=1.0, roughness=0.6)),

    ("metal_off", _cell(base_color=(0.9, 0.9, 0.9), metalness=0.0)),
    ("metal_on", _cell(base_color=(0.9, 0.9, 0.9), metalness=1.0,
                       roughness=0.3)),

    ("coat_off", _cell(coat=0.0)),
    ("coat_on", _cell(coat=1.0, coat_roughness=0.1)),

    ("sheen_off", _cell(sheen=0.0)),
    ("sheen_on", _cell(sheen=1.0, sheen_roughness=0.3)),

    ("emission_off", _cell(emission=0.0)),
    ("emission_on", _cell(emission=1.0, emission_color=(0.4, 0.4, 0.4))),
    # Above one on purpose. The first version of this chart used 0.4 and
    # so never noticed that the importer clamped emission colours to one,
    # which flattened every bright emissive material.
    ("emission_hdr", _cell(emission=1.0, emission_color=(4.0, 4.0, 4.0))),

    ("opacity_full", _cell(base_color=(0.8, 0.8, 0.8))),
    ("opacity_half", _cell(base_color=(0.8, 0.8, 0.8),
                           opacity=(0.5, 0.5, 0.5))),
]

# Pairs that must differ from each other, on both sides. A pair that is
# identical in Blender while Arnold separates it is a channel that was lost.
PAIRS = [
    ("spec_off", "spec_on"),
    ("metal_off", "metal_on"),
    ("coat_off", "coat_on"),
    ("sheen_off", "sheen_on"),
    ("emission_off", "emission_on"),
    ("emission_on", "emission_hdr"),
    ("opacity_full", "opacity_half"),
]


def build_scene():
    cmds.file(new=True, force=True)
    cmds.currentUnit(linear="cm")
    cmds.loadPlugin("mtoa", quiet=True)
    try:
        cmds.colorManagementPrefs(edit=True, cmEnabled=False)
    except Exception:
        pass

    count = len(MATERIALS)
    names = ATTRS[SURFACE]
    for index, (name, attrs) in enumerate(MATERIALS):
        quad = cmds.polyPlane(
            # Deliberately not widened to keep filling the cell when turned.
            # Widening by 1/cos(tilt) makes a 70 degree quad nearly three
            # cells across and every cell then reads its neighbours.
            width=CELL * 0.9, height=CELL * 0.9,
            subdivisionsX=1, subdivisionsY=1, name=name,
        )[0]
        # Stand it up to face the camera, which looks down -Z, then turn it.
        cmds.setAttr(quad + ".rotateX", 90.0)
        cmds.setAttr(quad + ".rotateY", TILT_DEGREES)
        cmds.setAttr(quad + ".translateX", (index - (count - 1) / 2.0) * CELL)

        shader = cmds.shadingNode(SURFACE, asShader=True, name=name + "_shd")
        for semantic, value in attrs.items():
            attr = names.get(semantic)
            if not attr or not cmds.attributeQuery(
                attr, node=shader, exists=True
            ):
                continue
            if semantic == "emission" and SURFACE == "aiOpenPBRSurface":
                # A luminance in nits, not a nought to one weight.
                value = OPENPBR_EMISSION_NITS if value else 0.0
            # The float check comes first: OpenPBR states opacity as a single
            # geometryOpacity where standard surface uses an RGB opacity, and
            # testing for a tuple first would send a colour to a float plug.
            if semantic == "opacity" and SURFACE == "aiOpenPBRSurface":
                if isinstance(value, tuple):
                    value = value[0]
                cmds.setAttr(shader + "." + attr, float(value))
            elif isinstance(value, tuple):
                cmds.setAttr(shader + "." + attr, value[0], value[1], value[2],
                             type="double3")
            else:
                cmds.setAttr(shader + "." + attr, value)
        engine = cmds.sets(renderable=True, noSurfaceShader=True, empty=True,
                           name=name + "_SG")
        cmds.connectAttr(shader + ".outColor", engine + ".surfaceShader",
                         force=True)
        cmds.sets(quad, edit=True, forceElement=engine)

    # One light, behind the camera, so every quad is lit at normal incidence.
    light = cmds.createNode("aiAreaLight", name="chartLightShape")
    light_tf = cmds.listRelatives(light, parent=True, fullPath=True)[0]
    cmds.setAttr(light + ".aiTranslator", "quad", type="string")
    cmds.setAttr(light + ".intensity", LIGHT_INTENSITY)
    cmds.setAttr(light + ".aiNormalize", True)
    cmds.setAttr(light + ".aiSamples", 4)
    cmds.setAttr(light_tf + ".translateZ", LIGHT_DISTANCE)
    cmds.setAttr(light_tf + ".scale", 20.0, 20.0, 20.0, type="double3")

    camera_tf = cmds.rename(cmds.camera()[0], "chartCam")
    camera = cmds.listRelatives(camera_tf, shapes=True, fullPath=True)[0]
    cmds.setAttr(camera + ".orthographic", True)
    cmds.setAttr(camera + ".orthographicWidth", CELL * count)
    cmds.setAttr(camera + ".renderable", True)
    cmds.setAttr(camera_tf + ".translateZ", LIGHT_DISTANCE + 20.0)
    return camera


def render_with_kick(camera):
    cmds.setAttr("defaultRenderGlobals.currentRenderer", "arnold",
                 type="string")
    try:
        import mtoa.core as core

        core.createOptions()
    except Exception:
        pass
    for plug, value in (
        # Direct only, so what is compared is the surface response itself.
        ("defaultArnoldRenderOptions.GIDiffuseDepth", 0),
        ("defaultArnoldRenderOptions.GISpecularDepth", 0),
        ("defaultArnoldRenderOptions.AASamples", 5),
        ("defaultArnoldRenderOptions.denoiseBeauty", 0),
        ("defaultResolution.width", RESOLUTION),
        ("defaultResolution.height", RESOLUTION // len(MATERIALS)),
        ("defaultResolution.deviceAspectRatio", float(len(MATERIALS))),
        ("defaultResolution.pixelAspect", 1.0),
    ):
        try:
            cmds.setAttr(plug, value)
        except Exception:
            pass

    ass_path = os.path.join(OUT, "chart.ass").replace("\\", "/")
    cmds.arnoldExportAss(filename=ass_path, selected=False, mask=255,
                         boundingBox=True, cam=camera,
                         lightLinks=0, shadowLinks=0)
    with open(ass_path, "r") as handle:
        text = handle.read()
    text = re.sub(r'^ input "defaultArnoldDenoiser"\n', "", text, flags=re.M)
    with open(ass_path, "w") as handle:
        handle.write(text)

    exr = os.path.join(OUT, "arnold_chart.exr")
    height = RESOLUTION // len(MATERIALS)
    process = subprocess.run(
        [KICK, "-i", ass_path, "-o", exr, "-r", str(RESOLUTION), str(height),
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

    result = za.export_lookdev(OUT, bake_procedurals=False)
    print("exporter build:", za.BUILD_VERSION)
    print("package:", result["package_folder"])

    exr = render_with_kick(camera)
    print("arnold chart:", exr or "FAILED")

    with open(os.path.join(OUT, "expected.json"), "w") as handle:
        json.dump(
            {
                "resolution": RESOLUTION,
                "height": RESOLUTION // len(MATERIALS),
                "cells": [name for name, _ in MATERIALS],
                "surface": SURFACE,
                "tilt_degrees": TILT_DEGREES,
                "pairs": PAIRS,
                "arnold_exr": exr,
                "package": result["package_folder"],
            },
            handle,
            indent=2,
        )
    return 0 if exr else 1


if __name__ == "__main__":
    sys.exit(main())
