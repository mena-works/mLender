# -*- coding: utf-8 -*-
"""End-to-end export test against a real headless Maya with Arnold.

Builds a scene using every supported Arnold shader and light, runs the real
exporter, and asserts on the JSON it produces. Nothing is mocked.

    "C:\\Program Files\\Autodesk\\Maya2023\\bin\\mayapy.exe" tests/host/maya_export_test.py

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

# Three levels up: tests/<group>/<file>.py
TOOL_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)
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
    # Nested groups, so the exported folder trail has more than one level.
    # stdSurfCube is parented under |setDressing|props.
    cmds.group("stdSurfCube", name="props")
    cmds.group("props", name="setDressing")
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

    _, glass = shaded_cube("glassCube", "aiStandardSurface")
    cmds.setAttr(glass + ".transmission", 1.0)
    cmds.setAttr(glass + ".transmissionColor", 0.2, 0.9, 0.8, type="double3")
    cmds.setAttr(glass + ".transmissionExtraRoughness", 0.05)
    cmds.setAttr(glass + ".specularIOR", 1.52)
    cmds.setAttr(glass + ".thinWalled", True)

    _, lam = shaded_cube("aiLambertCube", "aiLambert")
    cmds.setAttr(lam + ".KdColor", 0.3, 0.3, 0.7, type="double3")
    cmds.setAttr(lam + ".opacity", 0.8, 0.8, 0.8, type="double3")

    # Texture behind a colour correct node, to exercise the upstream walk.
    texture = os.path.join(OUT, "fake_basecolor.tx").replace("\\", "/")
    with open(texture, "w") as handle:
        handle.write("only the path is exported, never the pixels")
    file_node = cmds.shadingNode("file", asTexture=True, name="baseTex")
    cmds.setAttr(file_node + ".fileTextureName", texture, type="string")
    # Two corrections in series, so the exported chain has to come back in
    # apply order rather than in the order the history walk found them.
    gamma_node = cmds.shadingNode("gammaCorrect", asUtility=True, name="gc")
    cmds.setAttr(gamma_node + ".gamma", 2.2, 2.2, 2.2, type="double3")
    correct = cmds.shadingNode("aiColorCorrect", asUtility=True, name="cc")
    cmds.setAttr(correct + ".gamma", 2.0)
    cmds.setAttr(correct + ".saturation", 0.5)
    cmds.setAttr(correct + ".exposure", 1.0)
    cmds.setAttr(correct + ".multiply", 2.0, 1.0, 1.0, type="double3")
    cmds.connectAttr(file_node + ".outColor", gamma_node + ".value", force=True)
    cmds.connectAttr(gamma_node + ".outValue", correct + ".input", force=True)
    cmds.connectAttr(correct + ".outColor", std + ".baseColor", force=True)

    # Displacement, which Maya hangs off the shadingEngine rather than the
    # shader. The cube subdivides, so the displacement has geometry to move.
    _, disp_shader = shaded_cube("dispCube", "aiStandardSurface")
    disp_shape = cmds.listRelatives("dispCube", shapes=True, fullPath=True)[0]
    cmds.setAttr(disp_shape + ".aiSubdivType", 1)
    cmds.setAttr(disp_shape + ".aiSubdivIterations", 3)
    cmds.setAttr(disp_shape + ".aiDispHeight", 0.25)
    cmds.setAttr(disp_shape + ".aiDispZeroValue", 0.5)
    cmds.setAttr(disp_shape + ".aiDispAutobump", True)
    height_path = os.path.join(OUT, "fake_height.tx").replace("\\", "/")
    with open(height_path, "w") as handle:
        handle.write("only the path is exported")
    height_tex = cmds.shadingNode("file", asTexture=True, name="heightTex")
    cmds.setAttr(height_tex + ".fileTextureName", height_path, type="string")
    disp_node = cmds.shadingNode("displacementShader", asShader=True,
                                 name="cubeDisp")
    cmds.setAttr(disp_node + ".scale", 2.0)
    cmds.connectAttr(height_tex + ".outAlpha", disp_node + ".displacement",
                     force=True)
    cmds.connectAttr(disp_node + ".displacement", "dispCube_SG.displacementShader",
                     force=True)

    # remapValue with a real curve, which is the whole point of the node: the
    # two default stops plus one that bends it away from a straight line.
    remap = cmds.shadingNode("remapValue", asUtility=True, name="remapCoat")
    cmds.setAttr(remap + ".value[2].value_Position", 0.4)
    cmds.setAttr(remap + ".value[2].value_FloatValue", 0.9)
    cmds.setAttr(remap + ".value[2].value_Interp", 1)
    cmds.connectAttr(file_node + ".outAlpha", remap + ".inputValue", force=True)
    cmds.connectAttr(remap + ".outValue", std + ".coat", force=True)

    # A clamp and a blendColors on another channel, so both new builders run.
    clamp_node = cmds.shadingNode("clamp", asUtility=True, name="clampSheen")
    cmds.setAttr(clamp_node + ".max", 0.75, 0.75, 0.75, type="double3")
    cmds.setAttr(clamp_node + ".min", 0.1, 0.1, 0.1, type="double3")
    cmds.connectAttr(file_node + ".outColor", clamp_node + ".input", force=True)
    blend_node = cmds.shadingNode("blendColors", asUtility=True, name="blendTint")
    cmds.setAttr(blend_node + ".blender", 0.25)
    cmds.setAttr(blend_node + ".color2", 1.0, 0.0, 0.0, type="double3")
    cmds.connectAttr(clamp_node + ".output", blend_node + ".color1", force=True)
    cmds.connectAttr(blend_node + ".output", std + ".sheenColor", force=True)

    # aiComposite still has no builder, so the reporting path stays covered.
    composite = cmds.shadingNode("aiComposite", asUtility=True, name="compProbe")
    cmds.connectAttr(file_node + ".outColor", composite + ".A", force=True)
    cmds.connectAttr(composite + ".outColor", std + ".coatColor", force=True)

    # A UDIM set, driven through Maya's own tiling mode rather than a token in
    # the path, which is the case a naive path scan gets wrong.
    for tile in (1001, 1002, 1011):
        with open(os.path.join(OUT, "tile.{0}.tx".format(tile)), "w") as handle:
            handle.write("tile {0}".format(tile))
    udim_node = cmds.shadingNode("file", asTexture=True, name="udimTex")
    cmds.setAttr(
        udim_node + ".fileTextureName",
        os.path.join(OUT, "tile.1001.tx").replace("\\", "/"),
        type="string",
    )
    try:
        cmds.setAttr(udim_node + ".uvTilingMode", 3)
    except Exception:
        pass
    cmds.connectAttr(udim_node + ".outColor", lam + ".KdColor", force=True)

    # A shadow-only object: invisible to the camera but still casting. This is
    # the everyday lookdev case that used to arrive fully visible.
    cmds.setAttr("glassCubeShape.primaryVisibility", False)
    cmds.setAttr("glassCubeShape.aiVisibleInSpecularReflection", False)
    cmds.setAttr("aiLambertCubeShape.aiMatte", True)
    cmds.setAttr("openPbrCube.visibility", False)

    # An animated mesh, so the FBX side of the animation transfer is covered
    # too; the camera alone would only prove the JSON path works.
    cmds.setKeyframe("flatCube.translateX", time=1, value=0.0)
    cmds.setKeyframe("flatCube.translateX", time=25, value=8.0)

    # A turntable: the camera orbits a full 360 degrees while its focal length
    # pulls in. A full turn is the case that exposes Euler decomposition
    # flipping between frames, so the range deliberately closes the loop.
    turntable = cmds.rename(cmds.camera()[0], "turntableCam")
    turntable_shape = cmds.listRelatives(turntable, shapes=True, fullPath=True)[0]
    cmds.setAttr(turntable_shape + ".renderable", True)
    cmds.setAttr(turntable + ".translateZ", 20.0)
    for frame, rotation, focal in ((1, 0.0, 35.0), (13, 180.0, 50.0),
                                   (25, 360.0, 85.0)):
        cmds.setKeyframe(turntable + ".rotateY", time=frame, value=rotation)
        cmds.setKeyframe(turntable_shape + ".focalLength", time=frame,
                         value=focal)
    cmds.playbackOptions(minTime=1, maxTime=25)

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

    # Light linking. The query only means anything once the light is in
    # defaultLightSet, which Maya does itself for lights made in a scene.
    try:
        cmds.sets(area_tf, edit=True, forceElement="defaultLightSet")
    except Exception:
        pass
    cmds.lightlink(b=True, light=area_tf, object="flatCube")
    cmds.lightlink(b=True, light=area_tf, object="glassCube")
    # Shadow linking is stored separately from light linking, so it is broken
    # on a different mesh to prove the two are carried independently.
    cmds.lightlink(b=True, shadow=True, light=area_tf, object="openPbrCube")

    dome = cmds.createNode("aiSkyDomeLight", name="aiDomeShape")
    cmds.setAttr(dome + ".intensity", 2.0)
    cmds.setAttr(dome + ".aiExposure", 1.0)

    ies = cmds.createNode("aiPhotometricLight", name="aiIesShape")
    profile = os.path.join(OUT, "fake.ies").replace("\\", "/")
    with open(profile, "w") as handle:
        handle.write("IESNA:LM-63-2002")
    cmds.setAttr(ies + ".aiFilename", profile, type="string")
    cmds.setAttr(ies + ".coneAngle", 75.0)

    # Subdivision must follow the Maya mesh, not be applied blindly.
    # stdSurfCube is left alone: Arnold defaults aiSubdivType to none.
    pbr_shape = cmds.listRelatives("openPbrCube", shapes=True, fullPath=True)[0]
    cmds.setAttr(pbr_shape + ".aiSubdivType", 1)          # catclark
    cmds.setAttr(pbr_shape + ".aiSubdivIterations", 3)
    cmds.setAttr(pbr_shape + ".aiSubdivUvSmoothing", 1)   # pin_borders

    flat_shape = cmds.listRelatives("flatCube", shapes=True, fullPath=True)[0]
    cmds.setAttr(flat_shape + ".aiSubdivType", 2)         # linear

    lam_shape = cmds.listRelatives("aiLambertCube", shapes=True, fullPath=True)[0]
    cmds.setAttr(lam_shape + ".displaySmoothMesh", 2)     # smooth mesh preview
    cmds.setAttr(lam_shape + ".smoothLevel", 1)

    # A purely procedural network. There is no file on disk to reference, so
    # the exporter has to bake it or the material arrives flat.
    _, proc = shaded_cube("procCube", "aiStandardSurface")
    checker = cmds.shadingNode("checker", asTexture=True, name="procChecker")
    place = cmds.shadingNode("place2dTexture", asUtility=True, name="procPlace")
    cmds.connectAttr(place + ".outUV", checker + ".uvCoord", force=True)
    cmds.connectAttr(
        place + ".outUvFilterSize", checker + ".uvFilterSize", force=True
    )
    cmds.setAttr(checker + ".color1", 0.9, 0.1, 0.1, type="double3")
    cmds.setAttr(checker + ".color2", 0.1, 0.2, 0.9, type="double3")
    cmds.connectAttr(checker + ".outColor", proc + ".baseColor", force=True)
    ramp = cmds.shadingNode("ramp", asTexture=True, name="procRamp")
    cmds.connectAttr(ramp + ".outAlpha", proc + ".specularRoughness", force=True)

    # A tiled, rotated texture behind a bump node. Placement and bump strength
    # both used to be dropped on the way past.
    _, tiled = shaded_cube("tiledCube", "aiStandardSurface")
    cmds.setAttr(tiled + ".coat", 0.6)
    cmds.setAttr(tiled + ".coatRoughness", 0.08)
    cmds.setAttr(tiled + ".coatColor", 0.9, 0.95, 1.0, type="double3")
    cmds.setAttr(tiled + ".sheen", 0.4)
    cmds.setAttr(tiled + ".sheenRoughness", 0.25)
    cmds.setAttr(tiled + ".subsurface", 0.3)
    cmds.setAttr(tiled + ".subsurfaceScale", 2.5)
    cmds.setAttr(tiled + ".specularAnisotropy", 0.35)

    tiled_tex = os.path.join(OUT, "tiled_basecolor.tx").replace("\\", "/")
    with open(tiled_tex, "w") as handle:
        handle.write("placement is what matters here")
    tiled_file = cmds.shadingNode("file", asTexture=True, name="tiledTex")
    cmds.setAttr(tiled_file + ".fileTextureName", tiled_tex, type="string")
    tiled_place = cmds.shadingNode(
        "place2dTexture", asUtility=True, name="tiledPlace"
    )
    cmds.connectAttr(tiled_place + ".outUV", tiled_file + ".uvCoord", force=True)
    cmds.connectAttr(
        tiled_place + ".outUvFilterSize", tiled_file + ".uvFilterSize", force=True
    )
    cmds.setAttr(tiled_place + ".repeatU", 4.0)
    cmds.setAttr(tiled_place + ".repeatV", 3.0)
    cmds.setAttr(tiled_place + ".offset", 0.25, 0.5, type="double2")
    cmds.setAttr(tiled_place + ".rotateUV", 45.0)
    cmds.setAttr(tiled_place + ".mirrorU", True)
    cmds.connectAttr(tiled_file + ".outColor", tiled + ".baseColor", force=True)

    normal_tex = os.path.join(OUT, "tiled_normal.tx").replace("\\", "/")
    with open(normal_tex, "w") as handle:
        handle.write("normal map")
    normal_file = cmds.shadingNode("file", asTexture=True, name="normalTex")
    cmds.setAttr(normal_file + ".fileTextureName", normal_tex, type="string")
    bump = cmds.shadingNode("bump2d", asUtility=True, name="tiledBump")
    cmds.setAttr(bump + ".bumpDepth", 0.35)
    cmds.setAttr(bump + ".bumpInterp", 1)          # Tangent Space Normals
    cmds.connectAttr(normal_file + ".outAlpha", bump + ".bumpValue", force=True)
    cmds.connectAttr(bump + ".outNormal", tiled + ".normalCamera", force=True)

    # Portals emit nothing and must not become black area lights.
    cmds.createNode("aiLightPortal", name="aiPortalShape")

    # A shot camera with a non default lens, plus an orthographic one. Maya's
    # startup cameras must not come along.
    # cmds.camera ignores a name flag, so the transform is renamed explicitly
    # and the shape re-read from it.
    shot_tf = cmds.rename(cmds.camera()[0], "shotCam")
    shot = cmds.listRelatives(shot_tf, shapes=True, fullPath=True)[0]
    cmds.setAttr(shot + ".focalLength", 50.0)
    cmds.setAttr(shot + ".horizontalFilmAperture", 0.9449)   # 24 mm
    cmds.setAttr(shot + ".verticalFilmAperture", 0.5315)     # 13.5 mm
    cmds.setAttr(shot + ".nearClipPlane", 1.0)
    cmds.setAttr(shot + ".farClipPlane", 5000.0)
    cmds.setAttr(shot + ".depthOfField", True)
    cmds.setAttr(shot + ".fStop", 2.8)
    cmds.setAttr(shot + ".focusDistance", 250.0)
    cmds.setAttr(shot + ".filmFit", 2)                        # Vertical
    cmds.setAttr(shot + ".horizontalFilmOffset", 0.09449)     # a tenth across
    cmds.setAttr(shot + ".renderable", True)
    cmds.setAttr(shot_tf + ".translate", 0.0, 30.0, 120.0, type="double3")

    ortho_tf = cmds.rename(cmds.camera()[0], "orthoCam")
    ortho = cmds.listRelatives(ortho_tf, shapes=True, fullPath=True)[0]
    cmds.setAttr(ortho + ".orthographic", True)
    cmds.setAttr(ortho + ".orthographicWidth", 40.0)


def main():
    cmds.loadPlugin("mtoa", quiet=True)
    print("MtoA:", cmds.pluginInfo("mtoa", query=True, version=True))

    if os.path.isdir(OUT):
        shutil.rmtree(OUT)
    os.makedirs(OUT)
    build_scene()

    import za_lookdev_exporter as za

    print("exporter build:", za.BUILD_VERSION)
    # Baking creates file nodes; the export must clean up after itself, so the
    # scene's own file nodes are recorded to compare against afterwards.
    file_nodes_before = set(cmds.ls(type="file") or [])
    # Animation on, so the turntable is sampled rather than frozen. The frame
    # is deliberately parked away from the range start, to prove sampling puts
    # it back.
    cmds.currentTime(7, edit=True)
    result = za.export_lookdev(OUT, export_animation=True)
    restored_frame = cmds.currentTime(query=True)
    with open(result["json_path"], "r") as handle:
        payload = json.load(handle)

    # Keyed by material name, not shader type: the glass cube is also an
    # aiStandardSurface and would otherwise overwrite the plain one.
    materials = {}
    for mesh in payload["meshes"]:
        for material in mesh["materials"]:
            materials[material.get("material") or ""] = material
    lights = {light["node_type"]: light for light in payload["lights"]}

    def channels(name):
        for key, material in materials.items():
            if name in key:
                return material.get("channels", {})
        return {}

    print("\npackage")
    check("FBX written", os.path.isfile(result["fbx_path"]))
    check("8 meshes exported", payload["mesh_count"] == 8, payload["mesh_count"])

    print("\naiStandardSurface")
    std = channels("stdSurfCube")
    check("roughness from specularRoughness",
          std.get("roughness", {}).get("maya_attr") == "specularRoughness")
    check("metallic from metalness 0.75",
          abs(std.get("metallic", {}).get("value", -1) - 0.75) < 1e-6)
    check("opacity is NOT inverted (Arnold opacity is not Maya transparency)",
          not std.get("opacity", {}).get("invert", False), std.get("opacity"))
    check("base colour texture found through aiColorCorrect",
          std.get("base_color", {}).get("texture", {}).get("path", "")
          .endswith(".tx"))

    corrections = (
        std.get("base_color", {}).get("texture", {}).get("corrections") or []
    )
    kinds = [entry.get("type") for entry in corrections]
    check("both correction nodes recorded, nearest the texture first",
          kinds == ["gammaCorrect", "aiColorCorrect"], kinds)
    correct_params = next(
        (entry.get("parameters", {}) for entry in corrections
         if entry.get("type") == "aiColorCorrect"),
        {},
    )
    check("aiColorCorrect gamma recorded",
          abs(correct_params.get("gamma", 0.0) - 2.0) < 1e-6, correct_params)
    check("aiColorCorrect saturation recorded",
          abs(correct_params.get("saturation", 0.0) - 0.5) < 1e-6)
    check("aiColorCorrect exposure recorded",
          abs(correct_params.get("exposure", 0.0) - 1.0) < 1e-6)
    check("aiColorCorrect multiply recorded per channel",
          [round(value, 6) for value in correct_params.get("multiply", [])]
          == [2.0, 1.0, 1.0], correct_params.get("multiply"))
    gamma_params = next(
        (entry.get("parameters", {}) for entry in corrections
         if entry.get("type") == "gammaCorrect"),
        {},
    )
    check("gammaCorrect keeps its three components",
          [round(value, 5) for value in gamma_params.get("gamma", [])]
          == [2.2, 2.2, 2.2], gamma_params.get("gamma"))

    unsupported = [
        entry.get("node_type")
        for entry in (
            std.get("coat_tint", {}).get("texture", {})
            .get("unsupported_corrections") or []
        )
    ]
    check("a node with no builder is still reported, not dropped silently",
          "aiComposite" in unsupported, unsupported)

    coat_corrections = [
        entry.get("type")
        for entry in ((std.get("coat", {}).get("texture") or {})
                      .get("corrections") or [])
    ]
    check("remapValue is rebuilt now rather than reported",
          "remapValue" in coat_corrections, coat_corrections)
    remap_params = next(
        (entry.get("parameters", {})
         for entry in ((std.get("coat", {}).get("texture") or {})
                       .get("corrections") or [])
         if entry.get("type") == "remapValue"),
        {},
    )
    ramp = remap_params.get("ramp") or []
    check("the ramp curve was read", len(ramp) == 3, ramp)
    check("ramp stops arrive sorted by position",
          [round(stop["position"], 3) for stop in ramp] == [0.0, 0.4, 1.0],
          [stop.get("position") for stop in ramp])
    check("the bent stop kept its value",
          len(ramp) > 1 and abs(ramp[1]["value"] - 0.9) < 1e-4,
          ramp[1] if len(ramp) > 1 else None)

    sheen_corrections = [
        entry.get("type")
        for entry in ((std.get("sheen_tint", {}).get("texture") or {})
                      .get("corrections") or [])
    ]
    check("clamp and blendColors recorded, nearest the texture first",
          sheen_corrections == ["clamp", "blendColors"], sheen_corrections)
    blend_params = next(
        (entry.get("parameters", {})
         for entry in ((std.get("sheen_tint", {}).get("texture") or {})
                       .get("corrections") or [])
         if entry.get("type") == "blendColors"),
        {},
    )
    check("blendColors knows which input the texture arrived on",
          blend_params.get("connected_input") == "color1", blend_params)

    print("\nselection scope")
    # Selecting the group is how an asset is normally picked, so the selection
    # must expand to its descendants rather than be read literally.
    cmds.select("setDressing", replace=True)
    selected_result = za.export_lookdev(
        os.path.join(OUT, "selected"), selected_only=True
    )
    with open(selected_result["json_path"], "r") as handle:
        selected_payload = json.load(handle)
    selected_names = {
        record.get("mesh") for record in selected_payload["meshes"]
    }
    check("only the selected group's mesh was exported",
          selected_names == {"stdSurfCube"}, sorted(selected_names))
    check("the package says it was a selection",
          selected_payload.get("selected_only") is True)
    check("lighting still travels whole",
          selected_payload["light_count"] == payload["light_count"],
          (selected_payload["light_count"], payload["light_count"]))
    check("cameras still travel whole",
          selected_payload["camera_count"] == payload["camera_count"])

    cmds.select(clear=True)
    failed = False
    try:
        za.export_lookdev(os.path.join(OUT, "empty"), selected_only=True)
    except RuntimeError:
        failed = True
    check("an empty selection fails loudly rather than exporting nothing",
          failed)
    check("the failed export left no package folder behind",
          not os.path.isdir(os.path.join(OUT, "empty", "MTB_Z_A_01")),
          os.listdir(os.path.join(OUT, "empty"))
          if os.path.isdir(os.path.join(OUT, "empty")) else "no folder")

    print("\nlight linking")
    lights_by_name = {light.get("name"): light for light in payload["lights"]}
    area_light = next(
        (light for name, light in lights_by_name.items()
         if str(name).startswith("aiArea")),
        {},
    )
    linked = area_light.get("linked_meshes")
    check("the restricted light lists its meshes", linked is not None, linked)
    if linked is not None:
        check("the two unlinked meshes are excluded",
              "flatCube" not in linked and "glassCube" not in linked, linked)
        check("everything else is still lit",
              "stdSurfCube" in linked and "dispCube" in linked, linked)
    unrestricted = next(
        (light for name, light in lights_by_name.items()
         if str(name).startswith("aiIes")),
        {},
    )
    # This light was never added to defaultLightSet, so Maya answers nothing
    # for it. That must read as "no restriction", never as "lights nothing",
    # which would black the light out in Blender.
    shadow = area_light.get("shadow_meshes")
    check("shadow linking carried separately from light linking",
          shadow is not None and "openPbrCube" not in shadow, shadow)
    check("the two restrictions are genuinely different sets",
          shadow != linked, (shadow, linked))

    check("an unanswerable light gets no restriction rather than an empty one",
          "linked_meshes" not in unrestricted,
          unrestricted.get("linked_meshes"))

    print("\ncollected textures")
    # A second export with collection on, into its own folder so the package
    # numbering the Blender import test reads from is left alone, and so the
    # first package keeps proving the default of pointing at the Maya paths.
    collected_result = za.export_lookdev(
        os.path.join(OUT, "collected"), collect_textures_into_package=True
    )
    with open(collected_result["json_path"], "r") as handle:
        collected_payload = json.load(handle)
    collected_folder = os.path.join(
        collected_result["package_folder"], "textures_collected"
    )
    check("collection folder created", os.path.isdir(collected_folder),
          collected_folder)
    check("something was collected",
          collected_result["collected_texture_count"] > 0,
          collected_result["collected_texture_count"])

    collected_paths = []
    for mesh in collected_payload["meshes"]:
        for material in mesh["materials"]:
            for entry in (material.get("channels") or {}).values():
                path = (entry.get("texture") or {}).get("path") or ""
                if path:
                    collected_paths.append(path)
    check("every texture path now points inside the package",
          collected_paths
          and all("textures_collected" in path for path in collected_paths),
          [p for p in collected_paths if "textures_collected" not in p][:3])
    check("the original Maya path is kept for reference",
          any(
              (entry.get("texture") or {}).get("original_path")
              for mesh in collected_payload["meshes"]
              for material in mesh["materials"]
              for entry in (material.get("channels") or {}).values()
          ))
    # The UDIM set is three tiles behind one <UDIM> pattern; copying the
    # pattern verbatim would have copied nothing.
    tiles = [
        name for name in os.listdir(collected_folder)
        if name.startswith("tile.")
    ]
    check("UDIM tiles expanded and copied, not the pattern",
          len(tiles) == 3, sorted(tiles))
    check("no file is named after the pattern itself",
          not any("<UDIM>" in name for name in os.listdir(collected_folder)),
          os.listdir(collected_folder))

    print("\ncolour management")
    color = payload.get("color_management") or {}
    check("colour management exported", bool(color), color)
    check("Maya 2023 defaults to the ACES config",
          color.get("rendering_space") == "ACEScg", color.get("rendering_space"))
    check("view transform name carried",
          "ACES" in str(color.get("view_transform") or ""),
          color.get("view_transform"))
    check("display carried", color.get("display") == "sRGB",
          color.get("display"))
    check("the <MAYA_RESOURCES> token was resolved to a real path",
          "<MAYA_RESOURCES>" not in str(color.get("config_path") or "")
          and str(color.get("config_path") or "").endswith(".ocio"),
          color.get("config_path"))

    print("\nvisibility flags")
    by_name = {record.get("mesh"): record for record in payload["meshes"]}
    glass_vis = (by_name.get("glassCube") or {}).get("visibility") or {}
    check("primaryVisibility off exported",
          glass_vis.get("camera") is False, glass_vis)
    check("specular reflection visibility off exported",
          glass_vis.get("glossy") is False, glass_vis)
    check("flags left at their default are not written",
          "shadow" not in glass_vis and "diffuse" not in glass_vis, glass_vis)
    check("aiMatte exported as matte",
          ((by_name.get("aiLambertCube") or {}).get("visibility") or {})
          .get("matte") is True,
          (by_name.get("aiLambertCube") or {}).get("visibility"))
    check("a hidden transform exported",
          ((by_name.get("openPbrCube") or {}).get("visibility") or {})
          .get("visible") is False,
          (by_name.get("openPbrCube") or {}).get("visibility"))
    check("an ordinary mesh writes no flags at all",
          (by_name.get("stdSurfCube") or {}).get("visibility") == {},
          (by_name.get("stdSurfCube") or {}).get("visibility"))

    print("\nanimation")
    animation = payload.get("animation") or {}
    check("animation reported as enabled", animation.get("enabled") is True,
          animation)
    check("playback range picked up, 1 to 25",
          (animation.get("start"), animation.get("end")) == (1.0, 25.0),
          (animation.get("start"), animation.get("end")))
    check("25 frames", animation.get("frame_count") == 25,
          animation.get("frame_count"))
    check("fps read from the scene, film is 24",
          abs(animation.get("fps", 0.0) - 24.0) < 1e-6, animation.get("fps"))
    check("sampling put the current frame back",
          abs(restored_frame - 7.0) < 1e-6, restored_frame)

    turntable = next(
        (camera for camera in payload["cameras"]
         if camera.get("name") == "turntableCam"),
        {},
    )
    samples = turntable.get("samples") or []
    check("camera sampled once per frame", len(samples) == 25, len(samples))
    if samples:
        check("samples carry the frame number",
              samples[0].get("frame") == 1.0 and samples[-1].get("frame") == 25.0,
              (samples[0].get("frame"), samples[-1].get("frame")))
        check("focal length animates across the range",
              abs(samples[0].get("focal_length_mm", 0) - 35.0) < 1e-4
              and abs(samples[-1].get("focal_length_mm", 0) - 85.0) < 1e-4,
              (samples[0].get("focal_length_mm"),
               samples[-1].get("focal_length_mm")))
        # A full turn returns to the start, so the matrices must match again.
        first = samples[0].get("matrix") or []
        last = samples[-1].get("matrix") or []
        check("a full turn returns to where it started",
              len(first) == 16 and len(last) == 16
              and all(abs(a - b) < 1e-4 for a, b in zip(first, last)),
              (first[:4], last[:4]))
        middle = samples[12].get("matrix") or []
        check("the halfway sample is genuinely rotated",
              len(middle) == 16 and abs(middle[0] - first[0]) > 1.0,
              (first[0], middle[0]))

    still = next(
        (light for light in payload["lights"]
         if light.get("name", "").startswith("aiArea")),
        {},
    )
    check("lights are sampled too", len(still.get("samples") or []) == 25,
          len(still.get("samples") or []))

    print("\ndisplacement")
    disp = next(
        (material.get("displacement") or {})
        for mesh in payload["meshes"] if mesh.get("mesh") == "dispCube"
        for material in mesh["materials"]
    )
    check("displacement found on the shading engine", disp.get("enabled"),
          disp)
    check("height map path exported",
          disp.get("texture", {}).get("path", "").endswith(".tx"),
          disp.get("texture"))
    check("mesh aiDispHeight 0.25 exported",
          abs(disp.get("height", 0.0) - 0.25) < 1e-6, disp.get("height"))
    check("mesh aiDispZeroValue 0.5 exported",
          abs(disp.get("zero_value", -1.0) - 0.5) < 1e-6, disp.get("zero_value"))
    check("displacementShader scale 2.0 exported",
          abs(disp.get("scale", 0.0) - 2.0) < 1e-6, disp.get("scale"))
    check("autobump exported", disp.get("autobump") is True, disp.get("autobump"))
    check("scalar, not vector displacement", disp.get("vector") is False)
    check("subdivision presence reported alongside it",
          disp.get("subdivision_enabled") is True)

    undisplaced = next(
        (material.get("displacement") or {})
        for mesh in payload["meshes"] if mesh.get("mesh") == "flatCube"
        for material in mesh["materials"]
    )
    check("a mesh with no displacement says so",
          undisplaced.get("enabled") is False, undisplaced)

    print("\ngroup hierarchy")
    by_mesh = {record.get("mesh"): record for record in payload["meshes"]}
    check("nested groups exported outermost first",
          by_mesh.get("stdSurfCube", {}).get("groups")
          == ["setDressing", "props"],
          by_mesh.get("stdSurfCube", {}).get("groups"))
    check("an ungrouped mesh reports no folders",
          by_mesh.get("flatCube", {}).get("groups") == [],
          by_mesh.get("flatCube", {}).get("groups"))

    print("\naiOpenPBRSurface")
    pbr = channels("openPbrCube")
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
    flat = channels("flatCube")
    check("emission reads color, not the computed outColor",
          flat.get("emission", {}).get("maya_attr") == "color",
          flat.get("emission"))
    check("emission keeps the authored 0.1/0.9/0.4",
          [round(v, 3) for v in flat.get("emission", {}).get("value", [])][:3]
          == [0.1, 0.9, 0.4], flat.get("emission", {}).get("value"))
    check("fully opaque, aiFlat has no transparency attribute",
          flat.get("opacity", {}).get("value") == [1.0, 1.0, 1.0, 1.0])

    print("\naiLambert")
    lam = channels("aiLambertCube")
    check("base colour from KdColor",
          lam.get("base_color", {}).get("maya_attr") == "KdColor")
    check("opacity is NOT inverted",
          not lam.get("opacity", {}).get("invert", False))

    print("\nglass")
    glass = channels("glassCube")
    check("glass material exported", bool(glass))
    check("transmission weight 1.0",
          abs(glass.get("transmission", {}).get("value", -1) - 1.0) < 1e-6,
          glass.get("transmission"))
    check("transmission colour from transmissionColor",
          glass.get("transmission_color", {}).get("maya_attr") == "transmissionColor",
          glass.get("transmission_color"))
    check("transmission roughness from transmissionExtraRoughness",
          glass.get("transmission_roughness", {}).get("maya_attr")
          == "transmissionExtraRoughness",
          glass.get("transmission_roughness"))
    check("ior 1.52 from specularIOR",
          abs(glass.get("ior", {}).get("value", -1) - 1.52) < 1e-5,
          glass.get("ior"))
    check("thin walled flag carried",
          bool(glass.get("thin_walled", {}).get("value")),
          glass.get("thin_walled"))
    check("a non refractive shader still reports transmission 0",
          abs(channels("openPbrCube").get("transmission", {}).get("value", -1))
          < 1e-9,
          channels("openPbrCube").get("transmission"))

    print("\nUDIM")
    udim = channels("aiLambertCube").get("base_color", {}).get("texture", {})
    check("UDIM detected from Maya's tiling mode", bool(udim.get("udim")), udim)
    check("path carries the <UDIM> token, not tile 1001",
          "<UDIM>" in udim.get("path", ""), udim.get("path"))
    check("the concrete tile path is kept alongside",
          udim.get("original_path", "").endswith("tile.1001.tx"),
          udim.get("original_path"))
    check("detection credited to Maya, not to path guessing",
          udim.get("udim_mode") == "maya_uv_tiling_mode", udim.get("udim_mode"))

    print("\nsubdivision follows the Maya mesh")

    def subdiv(name):
        for mesh in payload["meshes"]:
            if name in (mesh.get("mesh") or ""):
                return mesh.get("subdivision") or {}
        return {}

    plain = subdiv("stdSurfCube")
    check("a mesh that never asked is not subdivided",
          plain.get("enabled") is False, plain)
    catclark = subdiv("openPbrCube")
    check("aiSubdivType catclark is picked up",
          catclark.get("enabled") and catclark.get("scheme") == "CATMULL_CLARK",
          catclark)
    check("catclark iterations 3 carried",
          catclark.get("render_iterations") == 3, catclark)
    check("uv smoothing carried",
          catclark.get("uv_smoothing") == "pin_borders",
          catclark.get("uv_smoothing"))
    check("credited to arnold", catclark.get("source") == "arnold",
          catclark.get("source"))
    check("aiSubdivType linear stays linear",
          subdiv("flatCube").get("scheme") == "LINEAR", subdiv("flatCube"))
    preview = subdiv("aiLambertCube")
    check("maya smooth mesh preview is picked up",
          preview.get("enabled")
          and preview.get("source") == "maya_smooth_preview",
          preview)
    check("preview level 1 carried",
          preview.get("viewport_iterations") == 1, preview)

    print("\nplacement, bump and the extra lobes")
    tiled = channels("tiledCube")
    placement = tiled.get("base_color", {}).get("texture", {}).get("placement", {})
    check("place2dTexture was captured", bool(placement), placement)
    check("repeatU 4 carried", placement.get("repeat_u") == 4.0, placement)
    check("repeatV 3 carried", placement.get("repeat_v") == 3.0, placement)
    check("offset carried",
          [round(v, 4) for v in (placement.get("offset") or [])][:2] == [0.25, 0.5],
          placement.get("offset"))
    check("rotateUV exported in degrees",
          abs(placement.get("rotate_uv_degrees", 0) - 45.0) < 1e-4,
          placement.get("rotate_uv_degrees"))
    check("mirrorU carried", bool(placement.get("mirror_u")), placement)

    bump = tiled.get("normal", {}).get("texture", {}).get("bump", {})
    check("bump2d was captured", bool(bump), bump)
    check("bumpDepth 0.35 carried",
          abs(bump.get("depth", 0) - 0.35) < 1e-5, bump.get("depth"))
    check("bump interpretation carried",
          "tangent" in str(bump.get("interpretation", "")).lower(),
          bump.get("interpretation"))

    check("coat weight 0.6", abs(tiled.get("coat", {}).get("value", 0) - 0.6) < 1e-5)
    check("coat roughness 0.08",
          abs(tiled.get("coat_roughness", {}).get("value", 0) - 0.08) < 1e-5)
    check("sheen weight 0.4",
          abs(tiled.get("sheen", {}).get("value", 0) - 0.4) < 1e-5)
    check("subsurface weight 0.3",
          abs(tiled.get("subsurface", {}).get("value", 0) - 0.3) < 1e-5)
    check("subsurface scale 2.5",
          abs(tiled.get("subsurface_scale", {}).get("value", 0) - 2.5) < 1e-5)
    check("anisotropy 0.35",
          abs(tiled.get("anisotropic", {}).get("value", 0) - 0.35) < 1e-5)

    print("\nprocedural baking")
    proc = channels("procCube")
    base = proc.get("base_color", {}).get("texture", {})
    check("procedural base colour was baked", bool(base.get("baked")), base)
    check("the baked file exists on disk",
          os.path.isfile(base.get("path", "")), base.get("path"))
    check("the baked map is flagged linear", base.get("linear") is True, base)
    check("the bake records what it came from",
          "procChecker" in str(base.get("baked_from")), base.get("baked_from"))
    check("procedural roughness was baked too",
          bool(proc.get("roughness", {}).get("texture", {}).get("baked")),
          proc.get("roughness", {}).get("texture"))
    check("baked textures are counted in the payload",
          payload.get("baked_texture_count", 0) >= 2,
          payload.get("baked_texture_count"))
    check("bakes live inside the package folder",
          base.get("path", "").startswith(
              result["package_folder"].replace("\\", "/")),
          base.get("path"))
    check("a real file texture is still referenced rather than baked",
          not channels("stdSurfCube").get("base_color", {})
          .get("texture", {}).get("baked", False))
    # convertSolidTx wires a new file node into the scene for every bake. The
    # export must hand the user's scene back exactly as it found it, so what
    # matters is the difference across the export, not the total.
    check("baking left no new file node behind",
          set(cmds.ls(type="file") or []) == file_nodes_before,
          sorted(set(cmds.ls(type="file") or []) - file_nodes_before))

    print("\ncameras")
    cameras = {c["name"]: c for c in payload.get("cameras") or []}
    check("all three authored cameras exported", len(cameras) == 3,
          sorted(cameras))
    check("maya startup cameras excluded",
          not any(n in cameras for n in ("persp", "top", "front", "side")),
          sorted(cameras))

    shot = cameras.get("shotCam", {})
    check("focal length carried",
          abs(shot.get("focal_length_mm", 0) - 50.0) < 1e-6,
          shot.get("focal_length_mm"))
    check("film back converted from inches to mm",
          abs(shot.get("sensor_width_mm", 0) - 24.0) < 0.01,
          shot.get("sensor_width_mm"))
    check("film fit label carried", shot.get("film_fit") == "Vertical",
          shot.get("film_fit"))
    check("film offset became a sensor fraction",
          abs(shot.get("shift_x", 0) - 0.1) < 1e-3, shot.get("shift_x"))
    check("clip planes carried in scene units",
          shot.get("near_clip") == 1.0 and shot.get("far_clip") == 5000.0,
          (shot.get("near_clip"), shot.get("far_clip")))
    check("depth of field carried",
          shot.get("depth_of_field") and abs(shot.get("f_stop", 0) - 2.8) < 1e-6,
          shot.get("f_stop"))
    check("renderable flagged", shot.get("renderable") is True)

    ortho = cameras.get("orthoCam", {})
    check("orthographic flagged", ortho.get("orthographic") is True)
    check("orthographic width carried",
          abs(ortho.get("orthographic_width", 0) - 40.0) < 1e-6,
          ortho.get("orthographic_width"))
    check("orthographic camera is not renderable",
          ortho.get("renderable") is False, ortho.get("renderable"))

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
