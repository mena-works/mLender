# -*- coding: utf-8 -*-
"""End-to-end export test against a real headless Maya with Arnold.

Builds a scene using every supported Arnold shader and light, runs the real
exporter, and asserts on the JSON it produces. Nothing is mocked.

    "C:\\Program Files\\Autodesk\\Maya2023\\bin\\mayapy.exe" tests/maya_export_test.py

Writes its package to <temp>/za_lookdev_test, which blender_import_test.py
then reads. Run this one first.
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

TOOL_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(tempfile.gettempdir(), "za_lookdev_test")

if TOOL_ROOT not in sys.path:
    sys.path.insert(0, TOOL_ROOT)

failures = []


def check(label, condition, detail=""):
    if condition:
        print("  ok    {0}".format(label))
    else:
        failures.append("{0} {1}".format(label, detail))
        print("  FAIL  {0}  {1}".format(label, detail))


def shaded_cube(name, shader_type):
    transform = cmds.polyCube(name=name)[0]
    shader = cmds.shadingNode(shader_type, asShader=True, name=name + "_shd")
    engine = cmds.sets(
        renderable=True, noSurfaceShader=True, empty=True, name=name + "_SG"
    )
    cmds.connectAttr(shader + ".outColor", engine + ".surfaceShader", force=True)
    cmds.sets(transform, edit=True, forceElement=engine)
    return transform, shader


def build_scene():
    _, std = shaded_cube("stdSurfCube", "aiStandardSurface")
    cmds.setAttr(std + ".specularRoughness", 0.33)
    cmds.setAttr(std + ".metalness", 0.75)
    cmds.setAttr(std + ".opacity", 0.5, 0.5, 0.5, type="double3")
    cmds.setAttr(std + ".emission", 0.4)
    cmds.setAttr(std + ".emissionColor", 1.0, 0.2, 0.1, type="double3")

    _, pbr = shaded_cube("openPbrCube", "aiOpenPBRSurface")
    cmds.setAttr(pbr + ".baseColor", 0.9, 0.1, 0.1, type="double3")
    cmds.setAttr(pbr + ".specularRoughness", 0.12)
    cmds.setAttr(pbr + ".baseMetalness", 1.0)
    cmds.setAttr(pbr + ".geometryOpacity", 0.25)
    cmds.setAttr(pbr + ".emissionLuminance", 250.0)
    cmds.setAttr(pbr + ".emissionColor", 0.0, 1.0, 0.0, type="double3")

    _, flat = shaded_cube("flatCube", "aiFlat")
    cmds.setAttr(flat + ".color", 0.1, 0.9, 0.4, type="double3")

    _, lam = shaded_cube("aiLambertCube", "aiLambert")
    cmds.setAttr(lam + ".KdColor", 0.3, 0.3, 0.7, type="double3")
    cmds.setAttr(lam + ".opacity", 0.8, 0.8, 0.8, type="double3")

    # Texture behind a colour correct node, to exercise the upstream walk.
    texture = os.path.join(OUT, "fake_basecolor.tx").replace("\\", "/")
    with open(texture, "w") as handle:
        handle.write("only the path is exported, never the pixels")
    file_node = cmds.shadingNode("file", asTexture=True, name="baseTex")
    cmds.setAttr(file_node + ".fileTextureName", texture, type="string")
    correct = cmds.shadingNode("aiColorCorrect", asUtility=True, name="cc")
    cmds.connectAttr(file_node + ".outColor", correct + ".input", force=True)
    cmds.connectAttr(correct + ".outColor", std + ".baseColor", force=True)

    area = cmds.createNode("aiAreaLight", name="aiAreaShape")
    area_tf = cmds.listRelatives(area, parent=True, fullPath=True)[0]
    cmds.setAttr(area + ".aiTranslator", "disk", type="string")
    cmds.setAttr(area + ".intensity", 12.0)
    cmds.setAttr(area + ".exposure", 2.0)
    cmds.setAttr(area + ".aiColorTemperature", 4500.0)
    cmds.setAttr(area + ".aiUseColorTemperature", True)
    cmds.setAttr(area_tf + ".translateY", 5.0)
    cmds.setAttr(area_tf + ".scaleX", 3.0)
    cmds.setAttr(area_tf + ".scaleY", 3.0)

    dome = cmds.createNode("aiSkyDomeLight", name="aiDomeShape")
    cmds.setAttr(dome + ".intensity", 2.0)
    cmds.setAttr(dome + ".aiExposure", 1.0)

    ies = cmds.createNode("aiPhotometricLight", name="aiIesShape")
    profile = os.path.join(OUT, "fake.ies").replace("\\", "/")
    with open(profile, "w") as handle:
        handle.write("IESNA:LM-63-2002")
    cmds.setAttr(ies + ".aiFilename", profile, type="string")
    cmds.setAttr(ies + ".coneAngle", 75.0)

    # Portals emit nothing and must not become black area lights.
    cmds.createNode("aiLightPortal", name="aiPortalShape")


def main():
    cmds.loadPlugin("mtoa", quiet=True)
    print("MtoA:", cmds.pluginInfo("mtoa", query=True, version=True))

    if os.path.isdir(OUT):
        shutil.rmtree(OUT)
    os.makedirs(OUT)
    build_scene()

    import za_lookdev_exporter as za

    print("exporter build:", za.BUILD_VERSION)
    result = za.export_lookdev(OUT)
    with open(result["json_path"], "r") as handle:
        payload = json.load(handle)

    materials = {}
    for mesh in payload["meshes"]:
        for material in mesh["materials"]:
            materials[material["shader_type"]] = material
    lights = {light["node_type"]: light for light in payload["lights"]}

    def channels(shader_type):
        return materials.get(shader_type, {}).get("channels", {})

    print("\npackage")
    check("FBX written", os.path.isfile(result["fbx_path"]))
    check("4 meshes exported", payload["mesh_count"] == 4, payload["mesh_count"])

    print("\naiStandardSurface")
    std = channels("aiStandardSurface")
    check("roughness from specularRoughness",
          std.get("roughness", {}).get("maya_attr") == "specularRoughness")
    check("metallic from metalness 0.75",
          abs(std.get("metallic", {}).get("value", -1) - 0.75) < 1e-6)
    check("opacity is NOT inverted (Arnold opacity is not Maya transparency)",
          not std.get("opacity", {}).get("invert", False), std.get("opacity"))
    check("base colour texture found through aiColorCorrect",
          std.get("base_color", {}).get("texture", {}).get("path", "")
          .endswith(".tx"))

    print("\naiOpenPBRSurface")
    pbr = channels("aiOpenPBRSurface")
    check("metallic from baseMetalness",
          pbr.get("metallic", {}).get("maya_attr") == "baseMetalness")
    check("opacity from geometryOpacity",
          pbr.get("opacity", {}).get("maya_attr") == "geometryOpacity")
    check("emission tagged as a luminance",
          pbr.get("emission_strength", {}).get("source_semantic")
          == "openpbr_emission_luminance")
    check("emission luminance 250 nits carried raw",
          abs(pbr.get("emission_strength", {}).get("value", -1) - 250.0) < 1e-6)

    print("\naiFlat")
    flat = channels("aiFlat")
    check("emission reads color, not the computed outColor",
          flat.get("emission", {}).get("maya_attr") == "color",
          flat.get("emission"))
    check("emission keeps the authored 0.1/0.9/0.4",
          [round(v, 3) for v in flat.get("emission", {}).get("value", [])][:3]
          == [0.1, 0.9, 0.4], flat.get("emission", {}).get("value"))
    check("fully opaque, aiFlat has no transparency attribute",
          flat.get("opacity", {}).get("value") == [1.0, 1.0, 1.0, 1.0])

    print("\naiLambert")
    lam = channels("aiLambert")
    check("base colour from KdColor",
          lam.get("base_color", {}).get("maya_attr") == "KdColor")
    check("opacity is NOT inverted",
          not lam.get("opacity", {}).get("invert", False))

    print("\nlights")
    area = lights.get("aiAreaLight", {})
    check("aiAreaLight exported", bool(area))
    check("shape DISK resolved from the aiTranslator string",
          area.get("area_shape") == "DISK", area.get("area_shape"))
    check("intensity 12 with exposure 2 gives 48",
          abs(area.get("effective_intensity", -1) - 48.0) < 1e-4)
    check("temperature 4500 via aiColorTemperature",
          abs(area.get("parameters", {}).get("temperature", -1) - 4500.0) < 1e-6)
    check("aiSkyDomeLight resolves to DOME",
          lights.get("aiSkyDomeLight", {}).get("light_kind") == "DOME")
    check("aiSkyDomeLight exposure read from aiExposure",
          abs(lights.get("aiSkyDomeLight", {}).get("exposure", -1) - 1.0) < 1e-6)
    check("aiPhotometricLight resolves to IES",
          lights.get("aiPhotometricLight", {}).get("light_kind") == "IES")
    check("IES profile read from aiFilename",
          (lights.get("aiPhotometricLight", {}).get("ies_profile") or {})
          .get("path", "").endswith(".ies"))
    check("aiLightPortal excluded, it emits nothing",
          "aiLightPortal" not in lights)

    print()
    if failures:
        print("FAILURES ({0}):".format(len(failures)))
        for item in failures:
            print("  - {0}".format(item))
        return 1
    print("all export assertions passed")
    print("package: {0}".format(result["package_folder"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
