# -*- coding: utf-8 -*-
"""End-to-end export test against a real headless Maya with Arnold.

Builds a scene using every supported Arnold shader and light, runs the real
exporter, and asserts on the JSON it produces. Nothing is mocked.

    "C:\\Program Files\\Autodesk\\Maya2023\\bin\\mayapy.exe" tests/host/maya_export_test.py

Writes its package to <temp>/mlender_test, which blender_import_test.py
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
OUT = os.path.join(tempfile.gettempdir(), "mlender_test")

if TOOL_ROOT not in sys.path:
    sys.path.insert(0, TOOL_ROOT)

failures = []


AOV_NAMES = (
    "Z", "N", "motionvector", "crypto_object", "emission", "diffuse",
    "specular", "fuzz", "sss", "opacity", "albedo",
)


def check(label, condition, detail=""):
    if condition:
        print("  ok    {0}".format(label))
    else:
        failures.append("{0} {1}".format(label, detail))
        print("  FAIL  {0}  {1}".format(label, detail))


def _write_png(path):
    """A real one pixel PNG.

    The texture fixtures elsewhere write nonsense into a .tx because only the
    path is ever exported. An image plane is different: the importer loads the
    file into Blender, so it has to be an image Blender can actually open.
    """
    import base64

    data = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8"
        "z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
    )
    with open(path, "wb") as handle:
        handle.write(data)
    return path


def shaded_cube(name, shader_type):
    transform = cmds.polyCube(name=name)[0]
    shader = cmds.shadingNode(shader_type, asShader=True, name=name + "_shd")
    engine = cmds.sets(
        renderable=True, noSurfaceShader=True, empty=True, name=name + "_SG"
    )
    cmds.connectAttr(shader + ".outColor", engine + ".surfaceShader", force=True)
    cmds.sets(transform, edit=True, forceElement=engine)
    return transform, shader


def build_aovs():
    """Enabled Arnold AOVs, chosen to exercise the importer's name matching.

    Not a sample of pretty names: each one lands somewhere different. Z, N,
    motionvector, crypto_object, emission, diffuse and specular each hit a
    mapped branch; sss and opacity fall through to the unmapped path; and
    two are traps the substring matching walks into -- "fuzz" contains a z,
    and a bare "albedo" is not a diffuse pass.

    Before this the AOV path had never run with real data on either side.
    """
    try:
        import mtoa.aovs as mtoa_aovs
    except Exception as exc:
        print("  note: MtoA AOV interface unavailable: {0}".format(exc))
        return []
    try:
        interface = mtoa_aovs.AOVInterface()
    except Exception as exc:
        print("  note: AOVInterface refused: {0}".format(exc))
        return []
    made = []
    for name in AOV_NAMES:
        try:
            interface.addAOV(name)
            made.append(name)
        except Exception as exc:
            print("  note: AOV {0} refused: {1}".format(name, exc))
    return made


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
    # Same number as the standard surface cube's sheenRoughness on purpose:
    # one of the two gets remapped on import and the other must not.
    cmds.setAttr(pbr + ".fuzzWeight", 0.4)
    cmds.setAttr(pbr + ".fuzzRoughness", 0.25)

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

    # A correction chain on a texture a receiver can actually open. The
    # chains elsewhere in this scene sit on .tx stubs, which Unreal refuses to
    # import -- so the correction never had anything to correct there, and the
    # gamma the receiver computes was never checked against a number. Named
    # against the existing fixtures first; that has bitten this repo twice.
    corr_transform, corr_shader = shaded_cube("corrTexCube", "aiStandardSurface")
    corr_png = os.path.join(OUT, "corr_basecolor.png").replace("\\", "/")
    _write_png(corr_png)
    corr_file = cmds.shadingNode("file", asTexture=True, name="corrTex")
    cmds.setAttr(corr_file + ".fileTextureName", corr_png, type="string")
    corr_gamma = cmds.shadingNode("gammaCorrect", asUtility=True,
                                  name="corrGamma")
    cmds.setAttr(corr_gamma + ".gamma", 2.2, 2.2, 2.2, type="double3")
    cmds.connectAttr(corr_file + ".outColor", corr_gamma + ".value",
                     force=True)
    corr_clamp = cmds.shadingNode("clamp", asUtility=True, name="corrClamp")
    cmds.setAttr(corr_clamp + ".minR", 0.1)
    cmds.setAttr(corr_clamp + ".minG", 0.1)
    cmds.setAttr(corr_clamp + ".minB", 0.1)
    cmds.setAttr(corr_clamp + ".maxR", 0.75)
    cmds.setAttr(corr_clamp + ".maxG", 0.75)
    cmds.setAttr(corr_clamp + ".maxB", 0.75)
    cmds.connectAttr(corr_gamma + ".outValue", corr_clamp + ".input",
                     force=True)
    cmds.connectAttr(corr_clamp + ".output", corr_shader + ".baseColor",
                     force=True)

    # A colour correct node whose whole tail folds into one multiply and one
    # add. The measured chain is invert, gamma, contrast, exposure, multiply,
    # add (tests/docs/color_correct.md), so these values have a single right
    # answer on the other side and the receiver can be checked against it
    # rather than against its own arithmetic.
    fold_transform, fold_shader = shaded_cube("ccFoldCube", "aiStandardSurface")
    fold_png = os.path.join(OUT, "ccfold_basecolor.png").replace("\\", "/")
    _write_png(fold_png)
    fold_file = cmds.shadingNode("file", asTexture=True, name="ccFoldTex")
    cmds.setAttr(fold_file + ".fileTextureName", fold_png, type="string")
    fold_cc = cmds.shadingNode("aiColorCorrect", asUtility=True,
                               name="ccFoldCorrect")
    cmds.connectAttr(fold_file + ".outColor", fold_cc + ".input", force=True)
    cmds.setAttr(fold_cc + ".gamma", 2.2)
    cmds.setAttr(fold_cc + ".exposure", 1.0)
    cmds.setAttr(fold_cc + ".multiply", 1.5, 1.5, 1.5, type="double3")
    cmds.setAttr(fold_cc + ".add", 0.05, 0.05, 0.05, type="double3")
    cmds.connectAttr(fold_cc + ".outColor", fold_shader + ".baseColor",
                     force=True)

    # A UDIM set, driven through Maya's own tiling mode rather than a token in
    # the path, which is the case a naive path scan gets wrong.
    #
    # Real PNGs, not the nonsense the other texture fixtures hold. Those were
    # written when only the path travelled, and they still prove what they were
    # meant to -- but Unreal *imports* a texture as an asset, and it refuses a
    # file with no pixels in it. So the UDIM set, which is the one place a
    # receiver has to do something clever with the file itself, carries images
    # a host can actually open.
    for tile in (1001, 1002, 1011):
        _write_png(os.path.join(OUT, "tile.{0}.png".format(tile)))
    udim_node = cmds.shadingNode("file", asTexture=True, name="udimTex")
    cmds.setAttr(
        udim_node + ".fileTextureName",
        os.path.join(OUT, "tile.1001.png").replace("\\", "/"),
        type="string",
    )
    try:
        cmds.setAttr(udim_node + ".uvTilingMode", 3)
    except Exception:
        pass
    cmds.connectAttr(udim_node + ".outColor", lam + ".KdColor", force=True)

    # The native Maya shaders, which have their own code paths and had no
    # coverage at all. They matter because of the transparency conversion:
    # Maya states transparency where Blender wants opacity, and the exporter
    # inverts a flat value itself while leaving a textured one for the
    # importer. Getting that wrong inverts twice and nothing was watching.
    _, lam_native = shaded_cube("lambertCube", "lambert")
    cmds.setAttr(lam_native + ".color", 0.4, 0.6, 0.2, type="double3")
    cmds.setAttr(lam_native + ".transparency", 0.25, 0.25, 0.25, type="double3")

    _, blinn_native = shaded_cube("blinnCube", "blinn")
    cmds.setAttr(blinn_native + ".color", 0.7, 0.7, 0.9, type="double3")
    # Textured transparency takes the other branch: the flag survives to the
    # importer instead of the value being inverted here.
    blinn_tex = cmds.shadingNode("file", asTexture=True, name="blinnTransTex")
    cmds.setAttr(blinn_tex + ".fileTextureName", texture, type="string")
    cmds.connectAttr(blinn_tex + ".outColor", blinn_native + ".transparency",
                     force=True)
    # Deliberately away from the 0.3 default and from the 0.1 the exporter
    # used to pin every blinn to, so the assertion can only pass on code that
    # reads the attribute.
    cmds.setAttr(blinn_native + ".eccentricity", 0.45)

    # Maya's other two legacy shaders, each with a different gloss control.
    # Both were unsupported until measured: phong has cosinePower and no
    # eccentricity, phongE has roughness and no cosinePower.
    _, phong_native = shaded_cube("phongCube", "phong")
    cmds.setAttr(phong_native + ".color", 0.2, 0.6, 0.3, type="double3")
    cmds.setAttr(phong_native + ".cosinePower", 30.0)

    _, phong_e_native = shaded_cube("phongECube", "phongE")
    cmds.setAttr(phong_e_native + ".color", 0.6, 0.2, 0.2, type="double3")
    cmds.setAttr(phong_e_native + ".roughness", 0.8)

    # A ramp shader with a real gradient. The stops are written out of order
    # on purpose: Maya returns the indices in creation order, and a ramp an
    # artist edited comes back shuffled.
    _, ramp_native = shaded_cube("rampCube", "rampShader")
    cmds.setAttr(ramp_native + ".colorInput", 1)          # Facing Angle
    cmds.setAttr(ramp_native + ".color[0].color_Position", 0.0)
    cmds.setAttr(ramp_native + ".color[0].color_Color", 1, 0, 0,
                 type="double3")
    cmds.setAttr(ramp_native + ".color[2].color_Position", 1.0)
    cmds.setAttr(ramp_native + ".color[2].color_Color", 0, 0, 1,
                 type="double3")
    cmds.setAttr(ramp_native + ".color[1].color_Position", 0.5)
    cmds.setAttr(ramp_native + ".color[1].color_Color", 0, 1, 0,
                 type="double3")
    cmds.setAttr(ramp_native + ".color[1].color_Interp", 3)   # Spline
    # Transparency as a ramp too, so the inversion has a gradient to work on.
    cmds.setAttr(ramp_native + ".transparency[0].transparency_Position", 0.0)
    cmds.setAttr(ramp_native + ".transparency[0].transparency_Color",
                 0.25, 0.25, 0.25, type="double3")
    cmds.setAttr(ramp_native + ".transparency[1].transparency_Position", 1.0)
    cmds.setAttr(ramp_native + ".transparency[1].transparency_Color",
                 0.5, 0.5, 0.5, type="double3")
    cmds.setAttr(ramp_native + ".eccentricity", 0.6)

    # A ramp *texture*, which is a different node from a rampShader: a
    # gradient wired into a channel. Measured before this: with Bake
    # Procedurals off it collapsed to a flat colour with no warning.
    _, ramptex_shd = shaded_cube("rampTexCube", "aiStandardSurface")
    ramp_tex = cmds.shadingNode("ramp", asTexture=True, name="vRampTex")
    cmds.setAttr(ramp_tex + ".type", 0)            # V Ramp
    cmds.setAttr(ramp_tex + ".interpolation", 4)   # Smooth
    # Written out of order on purpose, as for the rampShader.
    cmds.setAttr(ramp_tex + ".colorEntryList[0].position", 0.0)
    cmds.setAttr(ramp_tex + ".colorEntryList[0].color", 1, 0, 0,
                 type="double3")
    cmds.setAttr(ramp_tex + ".colorEntryList[2].position", 1.0)
    cmds.setAttr(ramp_tex + ".colorEntryList[2].color", 0, 0, 1,
                 type="double3")
    cmds.setAttr(ramp_tex + ".colorEntryList[1].position", 0.5)
    cmds.setAttr(ramp_tex + ".colorEntryList[1].color", 0, 1, 0,
                 type="double3")
    cmds.connectAttr(ramp_tex + ".outColor", ramptex_shd + ".baseColor",
                     force=True)

    # A file texture behind a projection. Measured before this: the upstream
    # walk stepped through the projection, found the file and shipped it as
    # an ordinary UV mapped texture -- a wrong result that looked right.
    _, proj_shd = shaded_cube("projCube", "aiStandardSurface")
    projection = cmds.shadingNode("projection", asTexture=True,
                                  name="planarProjection")
    cmds.setAttr(projection + ".projType", 1)          # Planar
    proj_file = cmds.shadingNode("file", asTexture=True, name="projFile")
    cmds.setAttr(proj_file + ".fileTextureName", texture, type="string")
    cmds.connectAttr(proj_file + ".outColor", projection + ".image",
                     force=True)
    proj_place = cmds.shadingNode("place3dTexture", asUtility=True,
                                  name="projPlacement")
    cmds.setAttr(proj_place + ".translateY", 4)
    cmds.setAttr(proj_place + ".scaleX", 2)
    cmds.connectAttr(proj_place + ".worldInverseMatrix[0]",
                     projection + ".placementMatrix", force=True)
    cmds.connectAttr(projection + ".outColor", proj_shd + ".baseColor",
                     force=True)

    # Spherical, built from Math nodes rather than Blender's SPHERE mode,
    # which was measured against Maya's bake and rejected.
    _, sph_shd = shaded_cube("sphProjCube", "aiStandardSurface")
    sph = cmds.shadingNode("projection", asTexture=True, name="sphProjection")
    cmds.setAttr(sph + ".projType", 2)                 # Spherical
    sph_file = cmds.shadingNode("file", asTexture=True, name="sphFile")
    cmds.setAttr(sph_file + ".fileTextureName", texture, type="string")
    cmds.connectAttr(sph_file + ".outColor", sph + ".image", force=True)
    sph_place = cmds.shadingNode("place3dTexture", asUtility=True,
                                 name="sphPlacement")
    cmds.connectAttr(sph_place + ".worldInverseMatrix[0]",
                     sph + ".placementMatrix", force=True)
    cmds.connectAttr(sph + ".outColor", sph_shd + ".baseColor", force=True)

    # Cylindrical, whose sweep is a half turn rather than a whole one.
    _, cyl_shd = shaded_cube("cylProjCube", "aiStandardSurface")
    cyl = cmds.shadingNode("projection", asTexture=True, name="cylProjection")
    cmds.setAttr(cyl + ".projType", 3)                 # Cylindrical
    cyl_file = cmds.shadingNode("file", asTexture=True, name="cylFile")
    cmds.setAttr(cyl_file + ".fileTextureName", texture, type="string")
    cmds.connectAttr(cyl_file + ".outColor", cyl + ".image", force=True)
    cyl_place = cmds.shadingNode("place3dTexture", asUtility=True,
                                 name="cylPlacement")
    cmds.connectAttr(cyl_place + ".worldInverseMatrix[0]",
                     cyl + ".placementMatrix", force=True)
    cmds.connectAttr(cyl + ".outColor", cyl_shd + ".baseColor", force=True)

    # Crossings. Every path above was tested on its own; these are the
    # combinations, which is where a later change breaks something quietly.
    _, crossed_mix = shaded_cube("crossMixProj", "aiMixShader")
    cross_lower = cmds.shadingNode("aiStandardSurface", asShader=True,
                                   name="crossLower")
    cross_upper = cmds.shadingNode("aiStandardSurface", asShader=True,
                                   name="crossUpper")
    cross_proj = cmds.shadingNode("projection", asTexture=True,
                                  name="crossProjection")
    cmds.setAttr(cross_proj + ".projType", 1)
    cross_file = cmds.shadingNode("file", asTexture=True, name="crossFile")
    cmds.setAttr(cross_file + ".fileTextureName", texture, type="string")
    cmds.connectAttr(cross_file + ".outColor", cross_proj + ".image",
                     force=True)
    cross_place = cmds.shadingNode("place3dTexture", asUtility=True,
                                   name="crossPlacement")
    cmds.connectAttr(cross_place + ".worldInverseMatrix[0]",
                     cross_proj + ".placementMatrix", force=True)
    cmds.connectAttr(cross_proj + ".outColor", cross_upper + ".baseColor",
                     force=True)
    cmds.connectAttr(cross_lower + ".outColor", crossed_mix + ".shader1",
                     force=True)
    cmds.connectAttr(cross_upper + ".outColor", crossed_mix + ".shader2",
                     force=True)
    cmds.setAttr(crossed_mix + ".mix", 0.5)

    # A gradient on transparency, which is where the inversion lives.
    _, cross_ramp_shd = shaded_cube("crossRampAlpha", "lambert")
    cross_ramp = cmds.shadingNode("ramp", asTexture=True, name="crossRampTex")
    cmds.setAttr(cross_ramp + ".type", 0)
    cmds.setAttr(cross_ramp + ".colorEntryList[0].position", 0.0)
    cmds.setAttr(cross_ramp + ".colorEntryList[0].color", 0.2, 0.2, 0.2,
                 type="double3")
    cmds.setAttr(cross_ramp + ".colorEntryList[1].position", 1.0)
    cmds.setAttr(cross_ramp + ".colorEntryList[1].color", 0.8, 0.8, 0.8,
                 type="double3")
    cmds.connectAttr(cross_ramp + ".outColor",
                     cross_ramp_shd + ".transparency", force=True)

    # A NURBS surface. It used to be the example of a kind this build did not
    # carry -- measured before the coverage scan existed, it left the scene
    # with nothing said. It is tessellated for the export now, so it stands
    # for the opposite: a surface that is not a mesh and arrives as one.
    nurbs_surface = cmds.sphere(name="nurbsBall", r=1)[0]
    cmds.setAttr(nurbs_surface + ".translateZ", -24)

    # TriPlanar and Perspective, the two the measurement rig settled last.
    for label, kind in (("tri", 6), ("persp", 8)):
        _, proj_shader = shaded_cube(label + "ProjCube", "aiStandardSurface")
        node = cmds.shadingNode("projection", asTexture=True,
                                name=label + "Projection")
        cmds.setAttr(node + ".projType", kind)
        image = cmds.shadingNode("file", asTexture=True, name=label + "File")
        cmds.setAttr(image + ".fileTextureName", texture, type="string")
        cmds.connectAttr(image + ".outColor", node + ".image", force=True)
        place = cmds.shadingNode("place3dTexture", asUtility=True,
                                 name=label + "Placement")
        cmds.connectAttr(place + ".worldInverseMatrix[0]",
                         node + ".placementMatrix", force=True)
        cmds.connectAttr(node + ".outColor", proj_shader + ".baseColor",
                         force=True)

    # And a projection type this build does not reproduce, which must say so.
    _, ball_shd = shaded_cube("ballProjCube", "aiStandardSurface")
    ball = cmds.shadingNode("projection", asTexture=True, name="ballProjection")
    cmds.setAttr(ball + ".projType", 4)                # Ball
    ball_file = cmds.shadingNode("file", asTexture=True, name="ballFile")
    cmds.setAttr(ball_file + ".fileTextureName", texture, type="string")
    cmds.connectAttr(ball_file + ".outColor", ball + ".image", force=True)
    ball_place = cmds.shadingNode("place3dTexture", asUtility=True,
                                  name="ballPlacement")
    cmds.connectAttr(ball_place + ".worldInverseMatrix[0]",
                     ball + ".placementMatrix", force=True)
    cmds.connectAttr(ball + ".outColor", ball_shd + ".baseColor", force=True)

    # And a type one Color Ramp cannot make, which must say so rather than
    # arrive as a gradient in the wrong shape.
    _, radial_shd = shaded_cube("radialRampCube", "aiStandardSurface")
    radial_tex = cmds.shadingNode("ramp", asTexture=True, name="radialRampTex")
    cmds.setAttr(radial_tex + ".type", 4)          # Circular Ramp
    cmds.setAttr(radial_tex + ".colorEntryList[0].position", 0.0)
    cmds.setAttr(radial_tex + ".colorEntryList[0].color", 1, 1, 0,
                 type="double3")
    cmds.setAttr(radial_tex + ".colorEntryList[1].position", 1.0)
    cmds.setAttr(radial_tex + ".colorEntryList[1].color", 0, 1, 1,
                 type="double3")
    cmds.connectAttr(radial_tex + ".outColor", radial_shd + ".baseColor",
                     force=True)

    # A mix of two real shaders. Measured: Arnold's mix is the weight of
    # shader2, so 0.25 means a quarter of the green one. The two sub-shaders
    # differ in more than colour so a swapped slot is visible.
    mix_a = cmds.shadingNode("aiStandardSurface", asShader=True, name="mixLower")
    cmds.setAttr(mix_a + ".baseColor", 0.9, 0.1, 0.1, type="double3")
    cmds.setAttr(mix_a + ".specularRoughness", 0.15)
    mix_b = cmds.shadingNode("aiStandardSurface", asShader=True, name="mixUpper")
    cmds.setAttr(mix_b + ".baseColor", 0.1, 0.8, 0.2, type="double3")
    cmds.setAttr(mix_b + ".specularRoughness", 0.65)
    _, mixer = shaded_cube("mixCube", "aiMixShader")
    cmds.connectAttr(mix_a + ".outColor", mixer + ".shader1", force=True)
    cmds.connectAttr(mix_b + ".outColor", mixer + ".shader2", force=True)
    cmds.setAttr(mixer + ".mix", 0.25)

    # And a layer shader, whose disabled slot must not travel: an enabled
    # count that ignores the flag would put a shader nobody asked for on top.
    layer_a = cmds.shadingNode("aiStandardSurface", asShader=True,
                               name="layerBase")
    cmds.setAttr(layer_a + ".baseColor", 0.2, 0.2, 0.8, type="double3")
    layer_b = cmds.shadingNode("aiStandardSurface", asShader=True,
                               name="layerTop")
    cmds.setAttr(layer_b + ".baseColor", 0.8, 0.8, 0.2, type="double3")
    layer_off = cmds.shadingNode("aiStandardSurface", asShader=True,
                                 name="layerDisabled")
    _, layered = shaded_cube("layerCube", "aiLayerShader")
    cmds.connectAttr(layer_a + ".outColor", layered + ".input1", force=True)
    cmds.connectAttr(layer_b + ".outColor", layered + ".input2", force=True)
    cmds.connectAttr(layer_off + ".outColor", layered + ".input3", force=True)
    cmds.setAttr(layered + ".enable2", True)
    cmds.setAttr(layered + ".enable3", False)
    cmds.setAttr(layered + ".mix2", 0.4)

    # Maya's own layeredShader, one cube per compositing mode because the two
    # build different graphs. Its weight is a transparency and index 0 is the
    # top, both the reverse of the Arnold blend shaders above.
    def _maya_layered(cube_name, mode, top_transparency):
        base = cmds.shadingNode("aiStandardSurface", asShader=True,
                                name=cube_name + "Base")
        cmds.setAttr(base + ".baseColor", 0.9, 0.1, 0.1, type="double3")
        cmds.setAttr(base + ".specularRoughness", 0.77)
        top_shader = cmds.shadingNode("aiStandardSurface", asShader=True,
                                      name=cube_name + "Top")
        cmds.setAttr(top_shader + ".baseColor", 0.1, 0.9, 0.1, type="double3")
        _, stack = shaded_cube(cube_name, "layeredShader")
        cmds.setAttr(stack + ".compositingFlag", mode)
        cmds.connectAttr(top_shader + ".outColor", stack + ".inputs[0].color",
                         force=True)
        cmds.connectAttr(base + ".outColor", stack + ".inputs[1].color",
                         force=True)
        cmds.setAttr(stack + ".inputs[0].transparency", top_transparency,
                     top_transparency, top_transparency, type="double3")
        cmds.setAttr(stack + ".inputs[1].transparency", 0.0, 0.0, 0.0,
                     type="double3")
        return top_shader

    maya_top = _maya_layered("mayaLayerCube", 0, 0.4)     # Layer Shaders
    _maya_layered("mayaLayerTexCube", 1, 0.25)            # Layer Texture

    # The crossing the two features share: a layeredTexture driving a channel
    # of a shader that is itself one layer of a layeredShader. Each was
    # written on its own and they had never met.
    cross_stack = cmds.shadingNode("layeredTexture", asTexture=True,
                                   name="crossLayerStack")
    for cross_index, cross_name in enumerate(("crossLayerTop",
                                              "crossLayerBottom")):
        cross_path = os.path.join(OUT, cross_name + ".tx").replace("\\", "/")
        with open(cross_path, "w") as handle:
            handle.write("crossing fixture")
        cross_file = cmds.shadingNode("file", asTexture=True, name=cross_name)
        cmds.setAttr(cross_file + ".fileTextureName", cross_path,
                     type="string")
        element = "{0}.inputs[{1}]".format(cross_stack, cross_index)
        cmds.connectAttr(cross_file + ".outColor", element + ".color",
                         force=True)
        cmds.setAttr(element + ".blendMode", 6 if cross_index == 0 else 1)
        cmds.setAttr(element + ".alpha", 0.5 if cross_index == 0 else 1.0)
        cmds.setAttr(element + ".isVisible", True)
    cmds.connectAttr(cross_stack + ".outColor", maya_top + ".baseColor",
                     force=True)

    _, surface_native = shaded_cube("surfaceCube", "surfaceShader")
    cmds.setAttr(surface_native + ".outColor", 0.9, 0.3, 0.1, type="double3")
    cmds.setAttr(surface_native + ".outTransparency", 0.2, 0.2, 0.2,
                 type="double3")

    # An instanced shape and, next to it, a real duplicate of the same cube.
    # The pair is the point: instances must collapse onto one mesh datablock
    # in Blender and the duplicate must not, so a test that only had instances
    # would pass on code that merged everything with matching geometry.
    instance_source, _ = shaded_cube("instSource", "aiStandardSurface")
    instance_a = cmds.instance(instance_source, name="instA")[0]
    cmds.setAttr(instance_a + ".translateX", 4)
    instance_b = cmds.instance(instance_source, name="instB")[0]
    cmds.setAttr(instance_b + ".translateX", 8)
    instance_copy = cmds.duplicate(instance_source, name="instCopy")[0]
    cmds.setAttr(instance_copy + ".translateX", 12)

    # Transforms carrying no geometry. None of these ride the FBX: it only
    # carries what sits above an exported mesh, so on their own they used to
    # vanish. The mesh parented under another mesh is the control — that one
    # the FBX does carry, and it must keep its parent.
    probe_locator = cmds.spaceLocator(name="probeLocator")[0]
    cmds.setAttr(probe_locator + ".translateY", 7)
    control_group = cmds.group(empty=True, name="controlGroup")
    nested_locator = cmds.spaceLocator(name="nestedLocator")[0]
    cmds.parent(nested_locator, control_group)

    parent_mesh, _ = shaded_cube("parentMesh", "aiStandardSurface")
    child_mesh, _ = shaded_cube("childMesh", "aiStandardSurface")
    cmds.parent(child_mesh, parent_mesh)
    cmds.setAttr(parent_mesh + "|childMesh.translateY", 3)

    # Selection sets and display layers. The component set is the one that
    # matters: Blender has no equivalent for "these three faces", so it must
    # be reported rather than half-built.
    cmds.sets(["stdSurfCube", "flatCube"], name="heroSet")
    cmds.sets("glassCube.f[0:2]", name="faceOnlySet")
    props_layer = cmds.createDisplayLayer(name="hiddenLayer", empty=True)
    cmds.editDisplayLayerMembers(props_layer, "aiLambertCube", noRecurse=True)
    cmds.setAttr(props_layer + ".visibility", False)
    ref_layer = cmds.createDisplayLayer(name="referenceLayer", empty=True)
    cmds.editDisplayLayerMembers(ref_layer, "dispCube", noRecurse=True)
    cmds.setAttr(ref_layer + ".displayType", 2)

    # Render settings. A deliberately non-default resolution: 1920x1080 would
    # pass against a Blender that ignored the record entirely, since that is
    # Blender's own default.
    cmds.setAttr("defaultResolution.width", 1920)
    cmds.setAttr("defaultResolution.height", 804)
    cmds.setAttr("defaultResolution.pixelAspect", 1.0)
    try:
        import mtoa.core as core

        core.createOptions()
        cmds.setAttr("defaultArnoldRenderOptions.motion_blur_enable", True)
        cmds.setAttr("defaultArnoldRenderOptions.motion_frames", 0.75)
    except Exception as exc:
        print("  note: Arnold render options unavailable: {0}".format(exc))

    # Vertex colours. Two sets, because "which one" has to be a real question:
    # a mesh with one set would pass against code that ignored the name. The
    # shader reads the first through aiUserDataColor, which used to make the
    # channel an unsupported network and collapse it to black.
    cpv_transform, cpv_shape = shaded_cube("cpvCube", "aiStandardSurface")
    cmds.polyColorSet(cpv_transform, create=True, colorSet="paintCol",
                      representation="RGBA")
    cmds.polyColorSet(cpv_transform, currentColorSet=True, colorSet="paintCol")
    cmds.select(cpv_transform + ".vtx[0:3]")
    cmds.polyColorPerVertex(rgb=(1.0, 0.0, 0.0), a=1.0)
    cmds.select(cpv_transform + ".vtx[4:7]")
    cmds.polyColorPerVertex(rgb=(0.0, 0.4, 1.0), a=1.0)
    cmds.polyColorSet(cpv_transform, create=True, colorSet="maskCol",
                      representation="RGBA")
    cmds.polyColorSet(cpv_transform, currentColorSet=True, colorSet="maskCol")
    cmds.select(cpv_transform + ".vtx[0:7]")
    cmds.polyColorPerVertex(rgb=(0.0, 1.0, 0.0), a=1.0)
    # Left current on the second set on purpose: the shader names the first,
    # so a receiver that took "the current one" would read the wrong colours.
    cmds.select(clear=True)
    try:
        cpv_reader = cmds.shadingNode(
            "aiUserDataColor", asUtility=True, name="cpvReader"
        )
        cmds.setAttr(cpv_reader + ".attribute", "paintCol", type="string")
        cmds.connectAttr(
            cpv_reader + ".outColor", "cpvCube_shd.baseColor", force=True
        )
    except Exception as exc:
        print("  note: aiUserDataColor unavailable: {0}".format(exc))

    made_aovs = build_aovs()
    print("  AOVs created: {0}".format(", ".join(made_aovs) or "none"))

    # User attributes, the kind a pipeline hangs off a node. One of every type
    # that reads back differently, plus the two traps: a compound is listed
    # together with its children, and an enum reads back as an integer.
    attr_transform, _ = shaded_cube("attrCube", "aiStandardSurface")
    cmds.addAttr(attr_transform, longName="assetId", attributeType="long")
    cmds.setAttr(attr_transform + ".assetId", 4271)
    cmds.addAttr(attr_transform, longName="isHero", attributeType="bool")
    cmds.setAttr(attr_transform + ".isHero", True)
    cmds.addAttr(attr_transform, longName="variantName", dataType="string")
    cmds.setAttr(attr_transform + ".variantName", "rusty", type="string")
    cmds.addAttr(attr_transform, longName="lodLevel", attributeType="enum",
                 enumName="low:mid:high")
    cmds.setAttr(attr_transform + ".lodLevel", 2)
    cmds.addAttr(attr_transform, longName="offsetVec",
                 attributeType="double3")
    for axis in "XYZ":
        cmds.addAttr(attr_transform, longName="offsetVec" + axis,
                     attributeType="double", parent="offsetVec")
    cmds.setAttr(attr_transform + ".offsetVec", 1.0, 2.0, 3.0, type="double3")
    # Named to collide with the importer's own metadata on purpose.
    cmds.addAttr(attr_transform, longName="ml_generated",
                 attributeType="bool")
    cmds.setAttr(attr_transform + ".ml_generated", False)
    attr_shape = cmds.listRelatives(attr_transform, shapes=True,
                                    fullPath=True)[0]
    cmds.addAttr(attr_shape, longName="shapeTag", dataType="string")
    cmds.setAttr(attr_shape + ".shapeTag", "onShape", type="string")

    # Hard and soft edges. These already survive the FBX, and the pair is the
    # point: one cube alone would pass against an export that flattened every
    # mesh to the same shading.
    hard_transform, _ = shaded_cube("hardEdgeCube", "aiStandardSurface")
    cmds.polySoftEdge(hard_transform, angle=0)
    soft_transform, _ = shaded_cube("softEdgeCube", "aiStandardSurface")
    cmds.polySoftEdge(soft_transform, angle=180)

    # A second UV set and a colour set. Both already survive the FBX, so this
    # cube exists to keep them surviving: nothing else pins them, and a change
    # to FBX_EXPORT_OPTIONS could drop either without a word.
    uv_transform, _ = shaded_cube("uvSetCube", "aiStandardSurface")
    uv_shape = cmds.listRelatives(uv_transform, shapes=True, fullPath=True)[0]
    cmds.polyUVSet(uv_shape, create=True, uvSet="lightmap")
    cmds.polyUVSet(uv_shape, currentUVSet=True, uvSet="lightmap")
    cmds.polyProjection(uv_shape + ".f[0:5]", type="planar", md="y",
                        createNewMap=False)
    # Offset it so the two sets cannot be confused if only one survives.
    cmds.polyEditUV(uv_shape + ".map[0:100]", uValue=0.25, vValue=0.5)
    cmds.polyUVSet(uv_shape, currentUVSet=True, uvSet="map1")
    cmds.polyColorSet(uv_shape, create=True, colorSet="paint",
                      representation="RGBA")
    cmds.polyColorSet(uv_shape, currentColorSet=True, colorSet="paint")
    cmds.polyColorPerVertex(uv_shape + ".vtx[0:3]", rgb=(1.0, 0.0, 0.0), a=1.0)
    cmds.polyColorPerVertex(uv_shape + ".vtx[4:7]", rgb=(0.0, 0.0, 1.0), a=1.0)

    # Particles. Blender has no equivalent object, so what is asked of the
    # transfer is that the points land where Maya had them. The transform
    # is moved after creation on purpose: the positions must stay local, or
    # they would be applied twice.
    particle_tf, particle_shape = cmds.particle(
        p=[(0, 0, 0), (1, 2, 0), (3, 1, 5), (-2, 4, 1)],
        name="dustParticle",
    )
    cmds.setAttr(particle_tf + ".translateY", 10)
    # Gravity so the four points actually move. A bake asserted on a still
    # simulation would pass on code that keys the same position every frame.
    # Both of these commands act on the selection when they have one, which
    # is why it is cleared first.
    cmds.select(clear=True)
    gravity = cmds.gravity(name="dustGravity")[0]
    cmds.connectDynamic(particle_tf, fields=gravity)

    # And an emitter, whose count grows as it runs: measured 0, 3, 7 and 15
    # particles at frames 1, 5, 10 and 20. A Blender mesh has a fixed vertex
    # count, so this one must refuse the bake rather than ship a partial one.
    cmds.select(clear=True)
    emitter = cmds.emitter(
        pos=(0, 0, 0), name="sparkEmitter", type="omni", rate=20
    )[0]
    spark_tf, spark_shape = cmds.particle(name="sparkParticle")
    cmds.connectDynamic(spark_tf, emitters=emitter)

    # Geometry placed on points. Nothing looked for an instancer, so it and
    # everything it placed left the scene without a word.
    cmds.select(clear=True)
    inst_geo = cmds.polyCube(name="instancedGeo", w=0.5, h=0.5, d=0.5)[0]
    cmds.setAttr(inst_geo + ".translateZ", -18)
    inst_tf, inst_shape = cmds.particle(
        p=[(0, 0, 0), (2, 0, 0), (4, 0, 0)], name="scatterParticle"
    )
    cmds.setAttr(inst_tf + ".translateZ", -18)
    cmds.particleInstancer(inst_tf, addObject=True, object=inst_geo)

    # A mesh that blinks. Measured: visibility keys do not survive the FBX at
    # all, so before this the cube arrived visible for the whole range.
    blink = cmds.polyCube(name="blinkCube")[0]
    cmds.setAttr(blink + ".translateZ", -12)
    # A NURBS surface and a Maya subdivision surface. Neither is a mesh, so
    # discovery never saw them and they were reported missing rather than
    # carried. They are tessellated for the export and the scene is put back.
    nurbs_shader = cmds.shadingNode(
        "aiStandardSurface", asShader=True, name="nurbsBall_shd"
    )
    nurbs_engine = cmds.sets(
        renderable=True, noSurfaceShader=True, empty=True, name="nurbsBallSG"
    )
    cmds.connectAttr(
        nurbs_shader + ".outColor", nurbs_engine + ".surfaceShader", force=True
    )
    cmds.sets(nurbs_surface, edit=True, forceElement=nurbs_engine)
    # A *trimmed* surface, which is the reason this is a tessellation and not
    # a native rebuild in the receiver: Blender has NURBS surfaces but cannot
    # represent a trim, and a trimmed surface that arrives untrimmed is wrong
    # in a way nobody notices until the hole is missing.
    try:
        trimmed = cmds.nurbsPlane(name="trimmedPanel", width=6, lengthRatio=1,
                                  patchesU=4, patchesV=4)[0]
        cutter = cmds.circle(name="trimCircle", radius=1.2, normal=(0, 0, 1))[0]
        cmds.setAttr(trimmed + ".translateY", 14)
        cmds.setAttr(cutter + ".translateY", 14)
        cmds.setAttr(cutter + ".translateZ", 2)
        cmds.projectCurve(cutter, trimmed, constructionHistory=False)
        # Measured: the trim takes the tessellation from 1024 faces to 448,
        # so this fixture is a real hole and not a decoration.
        cmds.trim(trimmed, lu=0.5, lv=0.5)
        cmds.delete(cutter)
        cmds.sets(trimmed, edit=True, forceElement=nurbs_engine)
    except Exception as exc:
        print("  note: trimmed NURBS fixture unavailable: {0}".format(exc))
    try:
        subdiv_source = cmds.polyCube(name="subdivSource")[0]
        subdiv_transform = cmds.polyToSubdiv(
            subdiv_source, name="subdivBall"
        )[0]
        cmds.delete(subdiv_source)
        cmds.sets(subdiv_transform, edit=True, forceElement=nurbs_engine)
    except Exception as exc:
        print("  note: polyToSubdiv unavailable: {0}".format(exc))

    # Keyed shader parameters. A scalar and a colour, because a colour is a
    # compound and Maya keys its children: asking the compound alone found the
    # roughness and missed the base colour entirely.
    anim_transform, _anim_shape = shaded_cube("animMatCube",
                                              "aiStandardSurface")
    cmds.setKeyframe("animMatCube_shd.specularRoughness", time=1, value=0.05)
    cmds.setKeyframe("animMatCube_shd.specularRoughness", time=25, value=0.9)
    cmds.setKeyframe("animMatCube_shd.baseColorR", time=1, value=1.0)
    cmds.setKeyframe("animMatCube_shd.baseColorR", time=25, value=0.0)
    cmds.setKeyframe("animMatCube_shd.baseColorB", time=1, value=0.0)
    cmds.setKeyframe("animMatCube_shd.baseColorB", time=25, value=1.0)

    cmds.setKeyframe(blink + ".visibility", t=1, v=1)
    cmds.setKeyframe(blink + ".visibility", t=10, v=0)
    cmds.setKeyframe(blink + ".visibility", t=20, v=1)

    # A mesh deformed by something other than its transform. Measured: this
    # arrives frozen through FBX, which is the whole reason the Alembic
    # cache exists, so the fixture has to be a real deformation and not a
    # keyframed translate.
    cmds.select(clear=True)
    wobble = cmds.polyPlane(name="wobblePlane", sx=4, sy=4, w=10, h=10)[0]
    cluster, cluster_handle = cmds.cluster(
        wobble + ".vtx[0:8]", name="wobbleCluster"
    )
    cmds.setKeyframe(cluster_handle + ".translateY", t=1, v=0)
    cmds.setKeyframe(cluster_handle + ".translateY", t=25, v=6)

    # An Arnold volume. The VDB deliberately does not exist: measured on 4.1
    # and 5.2, Blender takes the path, reports no grids and raises nothing, so
    # the volume still marks where it belongs and can be re-pointed. That is
    # the case worth pinning, since a VDB path is routinely a per-frame
    # sequence that resolves somewhere else.
    volume_shape = cmds.createNode("aiVolume", name="smokeVolumeShape")
    volume_tf = cmds.listRelatives(volume_shape, parent=True,
                                   fullPath=True)[0]
    cmds.rename(volume_tf, "smokeVolume")
    cmds.setAttr("smokeVolume.translateY", 40)
    cmds.setAttr("smokeVolume.scaleX", 3)
    cmds.setAttr(volume_shape + ".filename",
                 os.path.join(OUT, "smoke.vdb").replace("\\", "/"),
                 type="string")
    cmds.setAttr(volume_shape + ".grids", "density temperature", type="string")
    cmds.setAttr(volume_shape + ".stepSize", 0.25)
    cmds.setAttr(volume_shape + ".velocityScale", 2.0)
    cmds.setAttr(volume_shape + ".useFrameExtension", True)
    cmds.setAttr(volume_shape + ".frame", 12)

    # Curves. The circle is the one that matters: it is driven by construction
    # history, and reading control points the obvious way returns zeros for
    # exactly that case. It is also periodic, where Maya repeats control
    # points to close the loop, and grouped, so placement is covered too.
    probe_curve = cmds.curve(name="probeCurve", degree=3,
                             point=[(0, 0, 0), (2, 4, 0), (6, 4, 0), (8, 0, 0)])
    # Moved, turned and scaled: each of the three hides a different bug.
    cmds.setAttr(probe_curve + ".translateY", 10)
    cmds.setAttr(probe_curve + ".rotateY", 30)
    cmds.setAttr(probe_curve + ".scaleX", 2)
    cmds.curve(name="probeLine", degree=1,
               point=[(0, 0, 0), (3, 0, 0), (3, 3, 0)])
    probe_circle = cmds.circle(name="probeCircle", radius=5, sections=8)[0]
    cmds.group(probe_circle, name="curveGroup")

    # Values deliberately outside the ranges the rest of the scene uses. The
    # emission clamp bug survived every test because nothing ever asked for a
    # value on the far side of a limit, so this cube does nothing else.
    _, extreme = shaded_cube("extremeCube", "aiStandardSurface")
    cmds.setAttr(extreme + ".emission", 1.0)
    cmds.setAttr(extreme + ".emissionColor", 8.0, 8.0, 8.0, type="double3")
    cmds.setAttr(extreme + ".subsurfaceRadius", 5.0, 5.0, 5.0, type="double3")
    cmds.setAttr(extreme + ".specularIOR", 2.4)
    cmds.setAttr(extreme + ".coat", 1.0)
    cmds.setAttr(extreme + ".coatIOR", 2.0)
    # Exactly at the ends, where an off-by-one clamp shows.
    cmds.setAttr(extreme + ".specularRoughness", 0.0)
    cmds.setAttr(extreme + ".metalness", 1.0)

    # ---------------------------------------------------------- edge cases
    # Two meshes sharing a short name under different groups. Maya allows it,
    # and the importer matches records to objects by name, so this is where a
    # silent mismatch would show up.
    # They are moved apart so a swap is detectable: if the importer pairs the
    # wrong record with the wrong object, the one in setA lands at -7.
    twin_a = cmds.polyCube(name="twin")[0]
    cmds.setAttr(twin_a + ".translateX", 7.0)
    cmds.group(twin_a, name="setA")
    twin_b = cmds.polyCube(name="twin")[0]
    cmds.setAttr(twin_b + ".translateX", -7.0)
    cmds.group(twin_b, name="setB")

    # A non-ASCII name, which is ordinary in a Turkish or French scene.
    accented = cmds.polyCube(name="kirmiziKup")[0]
    try:
        accented = cmds.rename(accented, u"kırmızıKüp")
    except Exception:
        pass
    _, accented_shader = shaded_cube("accentedShaded", "aiStandardSurface")

    # A texture that is referenced but does not exist on disk.
    missing = cmds.shadingNode("file", asTexture=True, name="missingTex")
    cmds.setAttr(
        missing + ".fileTextureName",
        os.path.join(OUT, "definitely_not_here.tx").replace("\\", "/"),
        type="string",
    )
    cmds.connectAttr(
        missing + ".outColor", accented_shader + ".baseColor", force=True
    )

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

    # A light colour above one, which Maya artists use as a boost. It was
    # clamped to white until the same bug that flattened emission was fixed.
    # A point light, not an area one: the assertions below key lights by
    # node type, so a second aiAreaLight would quietly replace the one
    # they are about.
    boost = cmds.createNode("pointLight", name="boostLightShape")
    boost_tf = cmds.listRelatives(boost, parent=True, fullPath=True)[0]
    cmds.setAttr(boost + ".color", 3.0, 2.0, 1.0, type="double3")
    cmds.setAttr(boost + ".intensity", 2.0)
    cmds.setAttr(boost_tf + ".translateY", 12.0)

    # A light that actually changes. Measured: every light in this fixture was
    # sampled and every sample was identical, so the whole animated-light path
    # -- exporter sampling, Blender keyframes, Unreal sequence tracks -- was
    # carried by tests that could not have failed. Intensity, colour and
    # position all move, and they move to values that tell the channels apart:
    # a light that only brightens cannot catch a colour track wired to the
    # intensity samples.
    anim_light = cmds.createNode("pointLight", name="animLightShape")
    anim_light_tf = cmds.listRelatives(anim_light, parent=True,
                                       fullPath=True)[0]
    cmds.setKeyframe(anim_light + ".intensity", time=1, value=1.0)
    cmds.setKeyframe(anim_light + ".intensity", time=25, value=9.0)
    cmds.setKeyframe(anim_light + ".colorR", time=1, value=1.0)
    cmds.setKeyframe(anim_light + ".colorR", time=25, value=0.0)
    cmds.setKeyframe(anim_light + ".colorG", time=1, value=0.0)
    cmds.setKeyframe(anim_light + ".colorG", time=25, value=1.0)
    cmds.setKeyframe(anim_light_tf + ".translateX", time=1, value=0.0)
    cmds.setKeyframe(anim_light_tf + ".translateX", time=25, value=8.0)

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
    # A real Radiance .hdr on the dome. The dome had no texture at all before,
    # so every receiver's environment path was covered by a record that was
    # always empty. Written by hand rather than shipped as a binary: the
    # format is a header and flat RGBE pixels, and a checked-in .hdr is a
    # thing nobody can review.
    dome_hdr = os.path.join(OUT, "fake_dome.hdr").replace("\\", "/")
    width, height = 32, 16
    rows = []
    for row_index in range(height):
        row = bytearray()
        for column in range(width):
            row += bytearray([
                max(1, int(255 * (column / float(width - 1)))),
                max(1, int(255 * (row_index / float(height - 1)))),
                128,
                128,
            ])
        rows.append(bytes(row))
    with open(dome_hdr, "wb") as handle:
        handle.write(b"#?RADIANCE\nFORMAT=32-bit_rle_rgbe\n\n")
        handle.write("-Y {0} +X {1}\n".format(height, width).encode("ascii"))
        for row in rows:
            handle.write(row)
    dome_file = cmds.shadingNode("file", asTexture=True, name="domeHdrFile")
    cmds.setAttr(dome_file + ".fileTextureName", dome_hdr, type="string")
    cmds.connectAttr(dome_file + ".outColor", dome + ".color", force=True)

    ies = cmds.createNode("aiPhotometricLight", name="aiIesShape")
    profile = os.path.join(OUT, "fake.ies").replace("\\", "/")
    # A real IESNA LM-63 file, not a stub with the header line and nothing
    # after it. The stub was enough to prove the path travelled, and no more:
    # a receiver that actually loads the profile needs photometric data, and
    # measured, Unreal rejects a header-only file. Three vertical angles at
    # one horizontal angle, falling 1000 -> 500 -> 0 candela, so a receiver
    # that reads it has something with a shape to read.
    with open(profile, "w") as handle:
        handle.write("\n".join([
            "IESNA:LM-63-2002",
            "[TEST] mLender fixture",
            "[MANUFAC] mLender",
            "TILT=NONE",
            "1 1000 1 3 1 1 2 0 0 0",
            "1 1 100",
            "0 45 90",
            "0",
            "1000 500 0",
            "",
        ]))
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

    # Two UV sets on one mesh, with one texture on each. Both halves matter:
    # a build that records every uvLink answer would put a UV node in front
    # of the default texture too, and only the pair catches that.
    link_transform, uv_shader = shaded_cube("uvLinkCube", "aiStandardSurface")
    uv_shape = cmds.listRelatives(link_transform, shapes=True, fullPath=True)[0]
    cmds.polyUVSet(uv_shape, create=True, uvSet="secondUV")
    cmds.polyUVSet(uv_shape, copy=True, uvSet="map1", newUVSet="secondUV")
    # Offset the second set so the two are not interchangeable in a render.
    cmds.polyEditUV(
        link_transform + ".map[*]", uValue=0.25, uvSetName="secondUV"
    )

    def _uv_texture(name, attribute):
        path = os.path.join(OUT, name + ".tx").replace("\\", "/")
        with open(path, "w") as handle:
            handle.write("uv set fixture")
        node = cmds.shadingNode("file", asTexture=True, name=name)
        cmds.setAttr(node + ".fileTextureName", path, type="string")
        place = cmds.shadingNode(
            "place2dTexture", asUtility=True, name=name + "Place"
        )
        cmds.connectAttr(place + ".outUV", node + ".uvCoord", force=True)
        cmds.connectAttr(
            place + ".outUvFilterSize", node + ".uvFilterSize", force=True
        )
        cmds.connectAttr(node + ".outColor", uv_shader + "." + attribute,
                         force=True)
        return node

    _uv_texture("uvDefaultTex", "baseColor")
    uv_second_file = _uv_texture("uvSecondTex", "coatColor")
    cmds.uvLink(
        make=True,
        uvSet="{0}.uvSet[1].uvSetName".format(uv_shape),
        texture=uv_second_file,
    )

    # A layered texture, with every case that behaves differently in one
    # stack: a plain bottom, a blend mode the importer can build, one it
    # cannot, and a layer Maya is not drawing at all. Index 0 is the top.
    _, layered_shader = shaded_cube("layerTexCube", "aiStandardSurface")
    layered = cmds.shadingNode("layeredTexture", asTexture=True,
                               name="layerStack")

    def _layer_texture(name):
        path = os.path.join(OUT, name + ".tx").replace("\\", "/")
        with open(path, "w") as handle:
            handle.write("layer fixture")
        node = cmds.shadingNode("file", asTexture=True, name=name)
        cmds.setAttr(node + ".fileTextureName", path, type="string")
        return node

    # Top to bottom: an unsupported mode, a multiply, then the base.
    for index, (name, mode, alpha) in enumerate((
        ("layerSaturateTex", 10, 1.0),      # Saturate, no Blender equivalent
        ("layerMultiplyTex", 6, 0.5),       # Multiply
        ("layerBaseTex", 1, 1.0),           # Over
    )):
        element = "{0}.inputs[{1}]".format(layered, index)
        cmds.connectAttr(_layer_texture(name) + ".outColor",
                         element + ".color", force=True)
        cmds.setAttr(element + ".blendMode", mode)
        cmds.setAttr(element + ".alpha", alpha)
        cmds.setAttr(element + ".isVisible", True)
    # A hidden layer, which Maya renders as if it were not there.
    hidden = "{0}.inputs[3]".format(layered)
    cmds.connectAttr(_layer_texture("layerHiddenTex") + ".outColor",
                     hidden + ".color", force=True)
    cmds.setAttr(hidden + ".blendMode", 1)
    cmds.setAttr(hidden + ".isVisible", False)
    cmds.connectAttr(layered + ".outColor", layered_shader + ".baseColor",
                     force=True)

    # Standins: three cases that behave differently. A real Alembic that
    # must actually load, an .ass that Blender cannot read at all and has to
    # become a placeholder, and a gpuCache, which is the same idea under a
    # different attribute name.
    cmds.loadPlugin("AbcExport", quiet=True)
    standin_source = cmds.polyCube(name="standinSource", width=4, height=4,
                                   depth=4)[0]
    cmds.setAttr(standin_source + ".translateY", 3)
    standin_cache = os.path.join(OUT, "standin_source.abc").replace("\\", "/")
    try:
        cmds.AbcExport(j="-frameRange 1 1 -root |{0} -file {1}".format(
            standin_source, standin_cache))
    except Exception as exc:
        print("  note: standin cache not written: {0}".format(exc))
    cmds.delete(standin_source)

    def _standin(name, path, node_type="aiStandIn", attr="dso"):
        shape = cmds.createNode(node_type, name=name + "Shape")
        transform = cmds.listRelatives(shape, parent=True, fullPath=True)[0]
        transform = cmds.rename(transform, name)
        cmds.setAttr(transform + ".translateX", 7)
        try:
            cmds.setAttr(shape + "." + attr, path, type="string")
        except Exception as exc:
            print("  note: {0}.{1} not set: {2}".format(name, attr, exc))
        return transform

    # A USD standin that tries to redecorate the scene: its own time codes,
    # its own light, its own camera. Written as text so this needs no USD
    # library on the Maya side -- the exporter only records the path.
    usd_asset = os.path.join(OUT, "standin_asset.usda").replace("\\", "/")
    with open(usd_asset, "w") as handle:
        handle.write(
            '#usda 1.0\n(\n    defaultPrim = "AssetRoot"\n'
            '    metersPerUnit = 1\n    upAxis = "Z"\n'
            "    startTimeCode = 40\n    endTimeCode = 90\n)\n\n"
            'def Xform "AssetRoot"\n{\n'
            '    def Mesh "propGeo"\n    {\n'
            "        int[] faceVertexCounts = [4]\n"
            "        int[] faceVertexIndices = [0, 1, 2, 3]\n"
            "        point3f[] points = [(-1, -1, 0), (1, -1, 0), "
            "(1, 1, 0), (-1, 1, 0)]\n    }\n\n"
            '    def SphereLight "assetLight"\n    {\n'
            "        float inputs:intensity = 1000\n    }\n\n"
            '    def Camera "assetCam"\n    {\n'
            "        float focalLength = 3500\n    }\n}\n"
        )

    _standin("standinCube", standin_cache)
    _standin("usdStandIn", usd_asset)
    _standin("standinMissing",
             os.path.join(OUT, "no_such_proxy.ass").replace("\\", "/"))
    try:
        cmds.loadPlugin("gpuCache", quiet=True)
        _standin("cacheProxy", standin_cache, node_type="gpuCache",
                 attr="cacheFileName")
    except Exception as exc:
        print("  note: gpuCache unavailable: {0}".format(exc))

    # A three-joint chain skinned to a cylinder, for the pose bridge and the
    # rig transfer both: the bridge mirrors this skeleton, and the FBX path
    # must carry it as an armature. The decoy joint is bound to nothing and
    # must not travel -- sending every scene joint once turned 1014 joints
    # into 132 Blender armatures on a production rig.
    cmds.select(clear=True)
    bridge_root = cmds.joint(name="bridgeRoot", position=(0, 0, 0))
    cmds.joint(name="bridgeMid", position=(0, 4, 0))
    cmds.joint(name="bridgeTip", position=(0, 8, 0))
    cmds.select(clear=True)
    cmds.joint(name="bridgeDecoy", position=(5, 0, 0))
    bridge_cyl = cmds.polyCylinder(
        name="bridgeCylinder", height=8, radius=0.5,
        subdivisionsHeight=8, axis=(0, 1, 0),
    )[0]
    cmds.setAttr(bridge_cyl + ".translateY", 4)
    cmds.skinCluster("bridgeRoot", "bridgeMid", "bridgeTip", bridge_cyl,
                     toSelectedBones=True)

    # A miniature Advanced Skeleton manifest: the two sets, one declared limb
    # chain with twist joints deliberately absent (the bridge fixture covers
    # the plain case), FK/IK/Pole control curves, and a skinned arm. This
    # emulates the convention the五 production rigs declared identically, so
    # the mechanism is in the permanent suite even though the rigs are not.
    cmds.select(clear=True)
    cmds.joint(name="Shoulder_L", position=(0, 8, 0))
    cmds.joint(name="Elbow_L", position=(0, 4, 1))
    cmds.joint(name="Wrist_L", position=(0, 0, 0))
    as_mesh = cmds.polyCylinder(name="asArmMesh", height=8, radius=0.4,
                                subdivisionsHeight=8, axis=(0, 1, 0))[0]
    cmds.setAttr(as_mesh + ".translateY", 4)
    cmds.skinCluster("Shoulder_L", "Elbow_L", "Wrist_L", as_mesh,
                     toSelectedBones=True)

    def _as_circle(name, position):
        circle = cmds.circle(name=name, radius=0.6)[0]
        cmds.xform(circle, worldSpace=True, translation=position)
        return circle

    as_controls = [
        _as_circle("FKShoulder_L", (0, 8, 0)),
        _as_circle("FKElbow_L", (0, 4, 1)),
        _as_circle("IKArm_L", (0, 0, 0)),
        _as_circle("PoleArm_L", (0, 4, 5)),
    ]
    as_switch = cmds.createNode("transform", name="FKIKArm_L")
    cmds.addAttr(as_switch, longName="FKIKBlend", attributeType="double",
                 minValue=0, maxValue=10, defaultValue=10, keyable=True)
    for attr, base in (("startJoint", "Shoulder"), ("middleJoint", "Elbow"),
                       ("endJoint", "Wrist")):
        cmds.addAttr(as_switch, longName=attr, dataType="string")
        cmds.setAttr(as_switch + "." + attr, base, type="string")
    cmds.sets(["Shoulder_L", "Elbow_L", "Wrist_L"], name="DeformSet")
    cmds.sets(as_controls + [as_switch], name="ControlSet")

    # A second rig, referenced-style: the same miniature manifest inside a
    # namespace, with the SAME short names -- that is what two referenced
    # AS characters look like, and the namespace is the only thing keeping
    # their joints apart. Measured: a referenced rig's sets live at
    # NS:DeformSet, so bare-name detection misses them entirely.
    cmds.namespace(add="NSRig")
    cmds.namespace(set="NSRig")
    try:
        cmds.select(clear=True)
        cmds.joint(name="Shoulder_L", position=(6, 8, 0))
        cmds.joint(name="Elbow_L", position=(6, 4, 1))
        cmds.joint(name="Wrist_L", position=(6, 0, 0))
        ns_mesh = cmds.polyCylinder(name="nsArmMesh", height=8, radius=0.4,
                                    subdivisionsHeight=8, axis=(0, 1, 0))[0]
        cmds.setAttr(ns_mesh + ".translateX", 6)
        cmds.setAttr(ns_mesh + ".translateY", 4)
        cmds.skinCluster("NSRig:Shoulder_L", "NSRig:Elbow_L",
                         "NSRig:Wrist_L", ns_mesh, toSelectedBones=True)
        ns_controls = [
            _as_circle("FKShoulder_L", (6, 8, 0)),
            _as_circle("FKElbow_L", (6, 4, 1)),
            _as_circle("IKArm_L", (6, 0, 0)),
            _as_circle("PoleArm_L", (6, 4, 5)),
        ]
        ns_switch = cmds.createNode("transform", name="FKIKArm_L")
        cmds.addAttr(ns_switch, longName="FKIKBlend",
                     attributeType="double", minValue=0, maxValue=10,
                     defaultValue=10, keyable=True)
        for attr, base in (("startJoint", "Shoulder"),
                           ("middleJoint", "Elbow"),
                           ("endJoint", "Wrist")):
            cmds.addAttr(ns_switch, longName=attr, dataType="string")
            cmds.setAttr(ns_switch + "." + attr, base, type="string")
        cmds.sets(["NSRig:Shoulder_L", "NSRig:Elbow_L", "NSRig:Wrist_L"],
                  name="DeformSet")
        cmds.sets(ns_controls + [ns_switch], name="ControlSet")
    finally:
        cmds.namespace(set=":")

    # Animation keyed on a group ABOVE a skeleton. Measured: the FBX turns
    # that group into the armature object and folds its motion there with
    # the key shape flattened to linear -- and motion driven into such a
    # group by a connection never arrives at all. The sampled root-joint
    # truth is what closes both; two axes on purpose, a single-axis check
    # hides axis bugs.
    motion_group = cmds.group(empty=True, name="rootMotionGrp")
    cmds.select(clear=True)
    motion_root = cmds.joint(name="rootMotionRoot", position=(-6, 0, 0))
    cmds.joint(name="rootMotionTip", position=(-6, 4, 0))
    cmds.parent(motion_root, motion_group)
    motion_cube = cmds.polyCube(name="rootMotionCube", height=4)[0]
    cmds.setAttr(motion_cube + ".translateX", -6)
    cmds.setAttr(motion_cube + ".translateY", 2)
    cmds.parent(motion_cube, motion_group)
    cmds.skinCluster("rootMotionRoot", "rootMotionTip",
                     "rootMotionGrp|rootMotionCube", toSelectedBones=True)
    for attr, end_value in (("translateY", 2.0), ("translateZ", 3.0)):
        cmds.setKeyframe(motion_group, attribute=attr, time=1, value=0.0)
        cmds.setKeyframe(motion_group, attribute=attr, time=25,
                         value=end_value)

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

    # An image plane. A real file on disk, because the importer refuses a path
    # that is not there rather than attaching a broken background.
    plane_path = os.path.join(OUT, "ref_plate.png").replace("\\", "/")
    _write_png(plane_path)
    plane_shape = cmds.imagePlane(camera=shot, name="refPlane")[1]
    cmds.setAttr(plane_shape + ".imageName", plane_path, type="string")
    cmds.setAttr(plane_shape + ".alphaGain", 0.6)
    cmds.setAttr(plane_shape + ".depth", 120)
    cmds.setAttr(plane_shape + ".fit", 0)                     # Fill

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

    import mlender_exporter as za

    print("exporter build:", za.BUILD_VERSION)
    # Baking creates file nodes; the export must clean up after itself, so the
    # scene's own file nodes are recorded to compare against afterwards.
    file_nodes_before = set(cmds.ls(type="file") or [])
    # Animation on, so the turntable is sampled rather than frozen. The frame
    # is deliberately parked away from the range start, to prove sampling puts
    # it back.
    cmds.currentTime(7, edit=True)
    result = za.export_scene(
        OUT, export_animation=True, export_alembic_cache=True
    )
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
    check("59 meshes exported", payload["mesh_count"] == 59,
          payload["mesh_count"])
    # The locator, the empty null, the nested locator, the group holding
    # only a curve, and the two shapeless FKIK switchers (root and NSRig:).
    # None has a mesh below it, so the FBX carries none of them.
    check("6 geometry-free transforms exported",
          payload["transform_count"] == 6, payload["transform_count"])

    print("\ninstances")
    # An instanced shape hangs under several transforms. Reading only the
    # first dropped the instances from the FBX selection and the JSON alike,
    # so they never reached Blender at all: no object, no geometry, no warning.
    by_mesh = {record.get("mesh"): record for record in payload["meshes"]}
    for name in ("instSource", "instA", "instB", "instCopy"):
        check("{0} was exported".format(name), name in by_mesh)
    shapes = {
        name: (by_mesh.get(name) or {}).get("shape_path")
        for name in ("instSource", "instA", "instB", "instCopy")
    }
    check("the instances share one shape",
          shapes["instSource"] and shapes["instSource"] == shapes["instA"]
          == shapes["instB"], shapes)
    # The duplicate is the control. Without it a test would pass on code that
    # merged anything whose geometry happened to match.
    check("and a real duplicate does not",
          shapes["instCopy"] and shapes["instCopy"] != shapes["instSource"],
          shapes["instCopy"])
    check("each instance keeps its own transform",
          len({(by_mesh.get(n) or {}).get("mesh_path")
               for n in ("instSource", "instA", "instB")}) == 3)

    print("\ntransforms with no geometry")
    by_transform = {
        item.get("transform"): item
        for item in (payload.get("transforms") or [])
    }
    for name in ("probeLocator", "controlGroup", "nestedLocator"):
        check("{0} was recorded".format(name), name in by_transform,
              sorted(by_transform))
    check("a locator is recorded as one",
          (by_transform.get("probeLocator") or {}).get("transform_type")
          == "locator",
          (by_transform.get("probeLocator") or {}).get("transform_type"))
    check("an empty null is recorded as a group",
          (by_transform.get("controlGroup") or {}).get("transform_type")
          == "group")
    check("a nested locator keeps its parent",
          (by_transform.get("nestedLocator") or {}).get("parent_path", "")
          .endswith("controlGroup"),
          (by_transform.get("nestedLocator") or {}).get("parent_path"))
    check("and its group trail",
          (by_transform.get("nestedLocator") or {}).get("groups")
          == ["controlGroup"],
          (by_transform.get("nestedLocator") or {}).get("groups"))
    # The world matrix is what places it; a locator 7 units up in Maya has
    # that in the translation row.
    matrix = (by_transform.get("probeLocator") or {}).get("world_matrix") or []
    check("the world matrix carries the position",
          len(matrix) == 16 and abs(matrix[13] - 7.0) < 1e-4,
          matrix[12:15] if len(matrix) == 16 else matrix)
    # A transform with a mesh under it already rides the FBX. Recording it
    # here as well would build two Blender objects for one Maya node.
    check("a group holding meshes is not recorded twice",
          "setDressing" not in by_transform and "parentMesh" not in
          by_transform, sorted(by_transform))
    # A curve's transform has a shape, so it must not be swept up as an empty.
    check("a curve transform is not recorded as an empty",
          "probeCurve" not in by_transform and "probeCircle" not in
          by_transform, sorted(by_transform))

    print("\nparticles")
    by_particle = {
        item.get("particle"): item
        for item in (payload.get("particles") or [])
    }
    check("3 particle objects exported", payload["particle_count"] == 3,
          payload["particle_count"])
    dust = by_particle.get("dustParticle") or {}
    check("its count is carried", dust.get("count") == 4, dust.get("count"))
    # particle -q -position returns None; the query that works hands back a
    # flat list of three numbers per particle.
    positions = dust.get("positions") or []
    check("positions are a flat triple per particle",
          len(positions) == 12, len(positions))
    # Local, not world: the transform was moved ten units up after creation,
    # and applying that twice is exactly the mistake to guard against.
    check("and they are local, not world",
          positions[:3] == [0.0, 0.0, 0.0]
          and positions[3:6] == [1.0, 2.0, 0.0],
          positions[:6])
    check("the render type is carried as its label",
          str(dust.get("render_type") or "") != "", dust.get("render_type"))
    # Neither a mesh nor a locator, so neither discovery may claim it.
    check("a particle object is not exported as a mesh",
          "dustParticle" not in by_mesh, sorted(by_mesh))
    check("nor as an empty",
          "dustParticle" not in by_transform, sorted(by_transform))

    print("\nparticle bake")
    # dustParticle and the instancer's scatterParticle both hold a steady
    # count; only the emitter driven one refuses.
    check("the two steady ones could be baked",
          payload.get("particle_baked_count") == 2,
          payload.get("particle_baked_count"))
    samples = dust.get("samples") or []
    check("the constant count one carries a sample per frame",
          len(samples) > 1, len(samples))
    if samples:
        check("every sample names its frame",
              all(item.get("frame") is not None for item in samples))
        check("and holds one triple per particle",
              all(len(item.get("positions") or []) == 12
                  for item in samples),
              [len(item.get("positions") or []) for item in samples])
        # Gravity is connected, so a bake that keys the same value every
        # frame is a bake that is not reading the simulation.
        first = samples[0].get("positions") or []
        last = samples[-1].get("positions") or []
        check("and the points actually moved between them",
              first != last, (first[:3], last[:3]))

    spark = by_particle.get("sparkParticle") or {}
    check("the emitter driven one is flagged as varying",
          spark.get("count_varies") is True, spark.get("count_varies"))
    check("and carries no samples at all",
          not spark.get("samples"), len(spark.get("samples") or []))
    check("while keeping its snapshot",
          "positions" in spark)

    print("\nalembic cache")
    cache = payload.get("alembic") or {}
    cache_path = os.path.join(
        result["package_folder"], os.path.basename(cache.get("file") or "")
    )
    check("a cache file was written",
          bool(cache.get("file")) and os.path.isfile(cache_path),
          cache.get("file"))
    # One deformed mesh and one emitting particle object: exactly the two
    # cases measured to be untransferable any other way.
    check("it holds the deformed mesh",
          cache.get("mesh_count") == 1, cache.get("mesh_count"))
    check("and the emitting particle object",
          cache.get("particle_count") == 1, cache.get("particle_count"))

    wobble = by_mesh.get("wobblePlane") or {}
    check("the deformed mesh record is flagged as cached",
          wobble.get("alembic") is True, wobble.get("alembic"))
    check("and the emitting particle record too",
          spark.get("alembic") is True, spark.get("alembic"))
    # A mesh nothing deforms must stay in the FBX; caching everything would
    # make every package a cache and lose the point of the side channel.
    still = by_mesh.get("cubeA") or by_mesh.get("instSource") or {}
    check("while an undeformed mesh is not cached",
          still and not still.get("alembic"), still.get("alembic"))
    check("and the constant count particle object is not either",
          not dust.get("alembic"), dust.get("alembic"))

    print("\nvolumes")
    by_volume = {
        item.get("volume"): item for item in (payload.get("volumes") or [])
    }
    check("1 volume exported", payload["volume_count"] == 1,
          payload["volume_count"])
    volume = by_volume.get("smokeVolume") or {}
    check("the VDB path is carried",
          str(volume.get("file_path") or "").endswith("smoke.vdb"),
          volume.get("file_path"))
    check("the grid names are carried",
          volume.get("grids") == "density temperature", volume.get("grids"))
    check("frame extension and frame are carried",
          volume.get("use_frame_extension") is True
          and volume.get("frame") == 12,
          (volume.get("use_frame_extension"), volume.get("frame")))
    # Arnold render settings with no Blender equivalent, kept so the gap is
    # visible rather than silently dropped.
    check("Arnold's step size survives as reference",
          abs(float(volume.get("step_size") or 0) - 0.25) < 1e-6,
          volume.get("step_size"))
    check("and the velocity scale",
          abs(float(volume.get("velocity_scale") or 0) - 2.0) < 1e-6,
          volume.get("velocity_scale"))
    # A volume is neither a mesh nor a locator, so it must not be swept up by
    # either of those discoveries.
    check("a volume is not exported as a mesh",
          "smokeVolume" not in by_mesh, sorted(by_mesh))
    check("nor as an empty",
          "smokeVolume" not in by_transform, sorted(by_transform))

    print("\nimage planes")
    shot_record = next(
        (item for item in payload["cameras"] if item.get("name") == "shotCam"),
        {},
    )
    planes = shot_record.get("image_planes") or []
    check("the camera carries its image plane", len(planes) == 1, len(planes))
    if planes:
        plane = planes[0]
        check("the image path is carried",
              str(plane.get("image_path") or "").endswith("ref_plate.png"),
              plane.get("image_path"))
        check("alpha is carried",
              abs(float(plane.get("alpha") or 0) - 0.6) < 1e-6,
              plane.get("alpha"))
        # Enums travel as labels here too, for the same reason as everywhere
        # else: the indices are not stable.
        check("the fit mode is carried as its label",
              plane.get("fit") == "Fill", plane.get("fit"))
        check("and the display mode too",
              plane.get("display_mode") in
              ("RGB", "RGBA", "None", "Outline", "Luminance", "Alpha"),
              plane.get("display_mode"))
    # A camera without a plane must not invent one.
    ortho_record = next(
        (item for item in payload["cameras"] if item.get("name") == "orthoCam"),
        {},
    )
    check("a camera with no plane records none",
          not (ortho_record.get("image_planes") or []),
          ortho_record.get("image_planes"))

    print("\nuser attributes")
    attrs = (by_mesh.get("attrCube") or {}).get("custom_attributes") or {}
    check("an integer attribute is carried",
          attrs.get("assetId") == 4271, attrs.get("assetId"))
    check("a bool keeps being a bool",
          attrs.get("isHero") is True, attrs.get("isHero"))
    check("a string is carried",
          attrs.get("variantName") == "rusty", attrs.get("variantName"))
    # An enum reads back as an integer. Indices are not stable across
    # versions, which is why this codebase matches enums on their label.
    check("an enum is carried as its label, not its index",
          attrs.get("lodLevel") == "high", attrs.get("lodLevel"))
    check("a compound keeps its three components",
          attrs.get("offsetVec") == [1.0, 2.0, 3.0], attrs.get("offsetVec"))
    # Maya lists a compound together with its children, so writing every name
    # would record the same numbers four times over.
    check("and its children are not recorded separately",
          "offsetVecX" not in attrs, sorted(attrs))
    check("a shape attribute comes along too",
          attrs.get("shapeTag") == "onShape", attrs.get("shapeTag"))
    # The exporter carries it; refusing it is the importer's job, because the
    # collision is with Blender-side metadata.
    check("a name colliding with the importer's own is still exported",
          "ml_generated" in attrs, sorted(attrs))
    check("an ordinary mesh records no attributes",
          not ((by_mesh.get("flatCube") or {}).get("custom_attributes")),
          (by_mesh.get("flatCube") or {}).get("custom_attributes"))

    print("\nselection sets and display layers")
    by_set = {item.get("set"): item
              for item in (payload.get("selection_sets") or [])}
    check("heroSet exported", "heroSet" in by_set, sorted(by_set))
    # shadingEngine inherits from objectSet, and defaultObjectSet and
    # defaultLightSet are genuine object sets that a type filter cannot catch.
    check("shading engines are not mistaken for selection sets",
          not any(name.endswith("_SG") for name in by_set), sorted(by_set))
    check("and neither are Maya's own sets",
          "defaultObjectSet" not in by_set and "defaultLightSet" not in by_set,
          sorted(by_set))
    # Blender has no equivalent for a set of faces; it is reported, and a set
    # with nothing else in it is not written as an empty collection.
    check("a component only set is not exported",
          "faceOnlySet" not in by_set, sorted(by_set))
    check("and it was reported instead",
          any("faceOnlySet" in str(w) for w in payload["export_warnings"]),
          payload["export_warnings"])
    members = (by_set.get("heroSet") or {}).get("members") or []
    check("set members are full paths, not ambiguous short names",
          members and all(name.startswith("|") for name in members), members)

    by_layer = {item.get("layer"): item
                for item in (payload.get("display_layers") or [])}
    check("display layers exported",
          "hiddenLayer" in by_layer and "referenceLayer" in by_layer,
          sorted(by_layer))
    check("defaultLayer is skipped", "defaultLayer" not in by_layer,
          sorted(by_layer))
    check("layer visibility carried",
          (by_layer.get("hiddenLayer") or {}).get("visible") is False,
          (by_layer.get("hiddenLayer") or {}).get("visible"))
    check("reference display type carried",
          (by_layer.get("referenceLayer") or {}).get("display_type") == 2,
          (by_layer.get("referenceLayer") or {}).get("display_type"))

    print("\nrender settings")
    report_path = result.get("report_path") or ""
    check("the export wrote a report", bool(report_path)
          and os.path.isfile(report_path), report_path)
    if report_path and os.path.isfile(report_path):
        with open(report_path, "r") as handle:
            report_text = handle.read()
        check("the report names the package",
              str(result.get("package_name")) in report_text,
              report_text[:80])
        check("the report lists the warning count",
              "warnings (" in report_text,
              [l for l in report_text.splitlines() if "warnings" in l][:1])
        check("the report is inside the package folder",
              os.path.dirname(report_path) == result.get("package_folder"),
              os.path.dirname(report_path))

    check("a NURBS surface arrived as a mesh", "nurbsBall" in by_mesh,
          sorted(k for k in by_mesh if "nurbs" in str(k).lower()))
    check("a trimmed NURBS surface arrived as a mesh",
          "trimmedPanel" in by_mesh,
          sorted(k for k in by_mesh if "trim" in str(k).lower()))
    check("a Maya subdivision surface arrived as a mesh",
          "subdivBall" in by_mesh,
          sorted(k for k in by_mesh if "subdiv" in str(k).lower()))
    check("the tessellated surface kept its material",
          bool((by_mesh.get("nurbsBall") or {}).get("materials")),
          (by_mesh.get("nurbsBall") or {}).get("materials"))
    check("the export said it tessellated them",
          any("tessellated" in w for w in result["warnings"]),
          [w for w in result["warnings"] if "tessellated" in w][:1])
    # And coverage must not contradict that line by reporting them missing.
    check("coverage does not also call them missing",
          not any("nurbsSurface" in w and "not exported" in w
                  for w in result["warnings"]),
          [w for w in result["warnings"] if "not exported" in w][:2])
    # The scene is put back: the surfaces are still surfaces and nothing is
    # left wearing the export's suffix.
    check("the NURBS surface is still a NURBS surface in Maya",
          bool(cmds.ls("nurbsBallShape", type="nurbsSurface")),
          cmds.ls("nurbsBall*", long=True))
    check("no tessellation leftovers in the scene",
          not [node for node in (cmds.ls(long=True) or [])
               if "_mlOriginal" in node],
          [node for node in (cmds.ls(long=True) or [])
           if "_mlOriginal" in node][:3])

    anim_material = (by_mesh.get("animMatCube") or {}).get("materials") or [{}]
    anim_channels = (anim_material[0] or {}).get("channels") or {}
    rough_samples = (anim_channels.get("roughness") or {}).get("samples") or []
    colour_samples = (anim_channels.get("base_color") or {}).get("samples") or []
    check("a keyed scalar channel carries samples",
          len(rough_samples) > 2, len(rough_samples))
    # The compound trap: the curves hang off baseColorR and baseColorB, so a
    # check that only asked the compound would find nothing here.
    check("a keyed colour channel carries samples too",
          len(colour_samples) > 2, len(colour_samples))
    if rough_samples:
        first = rough_samples[0].get("value")
        last = rough_samples[-1].get("value")
        check("the samples actually move",
              abs(float(last) - float(first)) > 0.5, (first, last))
    # And an animation curve is not a texture: it used to be walked into as a
    # procedural network and baked, turning a keyed roughness into a flat map.
    check("a keyed channel was not baked into a texture",
          not ((anim_channels.get("roughness") or {}).get("texture") or {}
               ).get("baked"),
          (anim_channels.get("roughness") or {}).get("texture"))

    cpv = by_mesh.get("cpvCube") or {}
    sets = cpv.get("color_sets") or {}
    check("the mesh records its colour sets",
          sorted(sets.get("names") or []) == ["maskCol", "paintCol"],
          sets)
    check("and which one Maya had current",
          sets.get("current") == "maskCol", sets.get("current"))

    aov_records = payload.get("aovs") or []
    by_aov = {item.get("name"): item for item in aov_records}
    check("AOVs exported at all", bool(aov_records), len(aov_records))
    if aov_records:
        check("every created AOV is in the package",
              all(name in by_aov for name in AOV_NAMES),
              sorted(set(AOV_NAMES) - set(by_aov)))
        check("each AOV names its engine",
              all(item.get("engine") == "arnold" for item in aov_records),
              sorted({item.get("engine") for item in aov_records}))
        # The exporter records Arnold's type as a raw integer and comments
        # it "5=RGBA usually" -- a guess. Print the real values so the
        # table can stop guessing.
        print("    AOV type values: {0}".format(
            ", ".join("{0}={1}".format(k, (v or {}).get("type"))
                      for k, v in sorted(by_aov.items()))))
        check("every AOV carries a type",
              all(item.get("type") is not None for item in aov_records),
              [k for k, v in by_aov.items() if v.get("type") is None])

    render = payload.get("render") or {}
    check("resolution carried", render.get("width") == 1920
          and render.get("height") == 804,
          (render.get("width"), render.get("height")))
    check("pixel aspect carried",
          abs(float(render.get("pixel_aspect") or 0) - 1.0) < 1e-6,
          render.get("pixel_aspect"))
    motion = render.get("motion_blur") or {}
    check("motion blur read from Arnold", motion.get("enabled") is True,
          motion)
    # Arnold and Blender both state the shutter as a length in frames.
    check("shutter length carried in frames",
          abs(float(motion.get("shutter_frames") or 0) - 0.75) < 1e-6,
          motion.get("shutter_frames"))
    check("and the attribute it came from is recorded",
          motion.get("length_attr") == "motion_frames",
          motion.get("length_attr"))

    print("\ncurves")
    by_curve = {
        item.get("curve"): item for item in (payload.get("curves") or [])
    }
    check("11 curves exported: 3 fixtures and 4 AS controls per rig",
          payload["curve_count"] == 11,
          payload["curve_count"])
    for name in ("probeCurve", "probeLine", "probeCircle"):
        check("{0} was exported".format(name), name in by_curve,
              sorted(by_curve))
    check("degree is carried",
          (by_curve.get("probeCurve") or {}).get("degree") == 3
          and (by_curve.get("probeLine") or {}).get("degree") == 1,
          [(by_curve.get(n) or {}).get("degree")
           for n in ("probeCurve", "probeLine")])
    check("an open curve reports form 0",
          (by_curve.get("probeCurve") or {}).get("form") == 0,
          (by_curve.get("probeCurve") or {}).get("form"))
    check("a circle reports a closed form",
          (by_curve.get("probeCircle") or {}).get("form") in (1, 2),
          (by_curve.get("probeCircle") or {}).get("form"))
    # Maya repeats degree many control points to close a periodic curve. The
    # unique count is what Blender wants; reading controlPoints instead gives
    # 11 and stacks three duplicates on the seam.
    circle_points = (by_curve.get("probeCircle") or {}).get("control_points")
    check("a periodic circle carries its 8 unique control points",
          circle_points is not None and len(circle_points) == 8,
          len(circle_points) if circle_points is not None else None)
    # The circle is built by construction history, and the obvious way of
    # reading control points returns zeros for exactly that case.
    check("and they are not all at the origin",
          circle_points and any(any(abs(v) > 1e-6 for v in point)
                                for point in circle_points),
          circle_points[0] if circle_points else None)
    # Control points are local: this curve sits ten units up, and its first
    # point is still the origin.
    first = ((by_curve.get("probeCurve") or {}).get("control_points")
             or [[None]])[0]
    check("control points are local, not world",
          first is not None and max(abs(v) for v in first) < 1e-6, first)
    check("a grouped curve keeps its group trail",
          (by_curve.get("probeCircle") or {}).get("groups") == ["curveGroup"],
          (by_curve.get("probeCircle") or {}).get("groups"))

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

    print("\nedge cases")
    names = [record.get("mesh") for record in payload["meshes"]]
    twins = [
        record for record in payload["meshes"] if record.get("mesh") == "twin"
    ]
    check("both same-named meshes were exported", len(twins) == 2, names)
    check("their full paths tell them apart",
          len({record.get("mesh_path") for record in twins}) == 2,
          [record.get("mesh_path") for record in twins])
    check("their groups tell them apart",
          sorted(tuple(record.get("groups") or []) for record in twins)
          == [("setA",), ("setB",)],
          [record.get("groups") for record in twins])

    accented_names = [name for name in names if name and not name.isascii()]
    check("a non-ASCII mesh name survived export", accented_names,
          accented_names)

    accented_record = next(
        (record for record in payload["meshes"]
         for material in record["materials"]
         if material.get("material", "").startswith("accentedShaded")),
        None,
    )
    check("a missing texture is still referenced, not dropped",
          accented_record is not None
          and any(
              (entry.get("texture") or {}).get("path", "").endswith(".tx")
              for material in accented_record["materials"]
              for entry in (material.get("channels") or {}).values()
          ),
          accented_record.get("mesh") if accented_record else None)

    print("\nselection scope")
    # Selecting the group is how an asset is normally picked, so the selection
    # must expand to its descendants rather than be read literally.
    cmds.select("setDressing", replace=True)
    selected_result = za.export_scene(
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
    # Everything added after Export Scope existed ignored it at first, so a
    # scoped export sent every locator, curve and set in the scene alongside
    # the one asset that had been selected.
    check("no unselected locator or empty came along",
          selected_payload["transform_count"] == 0,
          [item.get("transform")
           for item in selected_payload.get("transforms") or []])
    check("no unselected curve came along",
          selected_payload["curve_count"] == 0,
          [item.get("curve")
           for item in selected_payload.get("curves") or []])
    # A set may only name what the package also carries, or it arrives in
    # Blender as a warning and an empty collection. heroSet holds two meshes
    # and one of them is in the selection, so it comes through trimmed rather
    # than dropped, which is the case worth pinning.
    scoped_sets = {item.get("set"): item
                   for item in selected_payload.get("selection_sets") or []}
    check("a set keeps only the members the package carries",
          (scoped_sets.get("heroSet") or {}).get("members") == [
              "|setDressing|props|stdSurfCube"
          ],
          (scoped_sets.get("heroSet") or {}).get("members"))
    check("and so are display layers",
          not (selected_payload.get("display_layers") or []),
          [item.get("layer")
           for item in selected_payload.get("display_layers") or []])

    cmds.select(clear=True)
    failed = False
    try:
        za.export_scene(os.path.join(OUT, "empty"), selected_only=True)
    except RuntimeError:
        failed = True
    check("an empty selection fails loudly rather than exporting nothing",
          failed)
    check("the failed export left no package folder behind",
          not os.path.isdir(os.path.join(OUT, "empty", "mLender_01")),
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
    collected_result = za.export_scene(
        os.path.join(OUT, "collected"), collect_textures_into_package=True,
        archive_package=True,
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

    # Volumes and standins are referenced files too. Collecting used to walk
    # past both: the package carried its textures and left the VDB and the
    # Alembic proxy outside, which is a self-contained package that is not.
    files_folder = os.path.join(
        collected_result["package_folder"], "files_collected"
    )
    check("the non-texture files were collected as well",
          collected_result["collected_file_count"] > 0,
          collected_result["collected_file_count"])
    collected_names = sorted(os.listdir(files_folder)) if os.path.isdir(
        files_folder) else []
    check("the standin's cache is one of them",
          any(name.endswith(".abc") for name in collected_names),
          collected_names)
    for section, key in (("volumes", "file_path"), ("standins", "file_path")):
        outside_files = [
            record.get(key) for record in collected_payload.get(section) or []
            if record.get(key) and "files_collected" not in record.get(key)
            and os.path.isfile(record.get(key) or "")
        ]
        check("every {0} file that exists points inside the package".format(
            section[:-1]), not outside_files, outside_files[:2])

    archive = collected_result.get("archive_path") or ""
    check("an archive was written beside the package",
          os.path.isfile(archive), archive)
    if os.path.isfile(archive):
        import zipfile as _zipfile

        names = _zipfile.ZipFile(archive).namelist()
        top = sorted(set(name.split("/")[0] for name in names))
        # The package folder is the archive's top level, so unzipping makes
        # the folder the importer wants rather than spilling files loose.
        check("with the package folder as its only top level",
              top == [os.path.basename(collected_result["package_folder"])],
              top)
        check("and the collected files inside it",
              any("files_collected/" in name for name in names)
              and any("textures_collected/" in name for name in names),
              [n for n in names if "collected" in n][:3])

    collected_paths = []
    for mesh in collected_payload["meshes"]:
        for material in mesh["materials"]:
            for entry in (material.get("channels") or {}).values():
                path = (entry.get("texture") or {}).get("path") or ""
                if path:
                    collected_paths.append(path)
    # The deliberately missing texture is the one exception: collection
    # reports it and leaves its path alone rather than failing the export.
    outside = [
        path for path in collected_paths
        if "textures_collected" not in path
    ]
    check("every texture that exists now points inside the package",
          collected_paths
          and outside == [p for p in outside if "definitely_not_here" in p],
          outside[:3])
    check("the missing texture was reported",
          any("definitely_not_here" in warning
              for warning in collected_result["warnings"]),
          collected_result["warnings"])
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
    check("specular weight tagged as gating the metal lobe",
          pbr.get("specular", {}).get("source_semantic")
          == "openpbr_specular_scales_metal",
          pbr.get("specular", {}).get("source_semantic"))
    check("fuzz roughness read from fuzzRoughness",
          pbr.get("sheen_roughness", {}).get("maya_attr") == "fuzzRoughness")
    # OpenPBR's fuzz is the model Blender already implements, so this record
    # must arrive untagged. Tagging it would remap a lobe that already agrees.
    check("and left untagged, unlike standard surface's sheen",
          "source_semantic" not in (pbr.get("sheen_roughness") or {}),
          pbr.get("sheen_roughness", {}).get("source_semantic"))

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

    print("\nnative Maya shaders and the transparency conversion")
    by_material = {}
    for mesh in payload["meshes"]:
        for material in mesh["materials"]:
            by_material[material.get("material")] = material

    lam_channels = (by_material.get("lambertCube_shd") or {}).get("channels", {})
    lam_opacity = lam_channels.get("opacity") or {}
    check("lambert exported", bool(lam_channels), sorted(by_material))
    # Transparency 0.25 is opacity 0.75, and the exporter does that itself.
    check("a flat transparency is inverted into opacity",
          abs(lam_opacity.get("value", [0])[0] - 0.75) < 1e-6,
          lam_opacity.get("value"))
    check("and its invert flag is cleared so nobody inverts twice",
          lam_opacity.get("invert") is False, lam_opacity.get("invert"))
    check("the conversion is labelled",
          lam_opacity.get("semantic") == "maya_transparency_to_opacity",
          lam_opacity.get("semantic"))

    blinn_opacity = (
        (by_material.get("blinnCube_shd") or {}).get("channels", {})
        .get("opacity") or {}
    )
    check("a textured transparency keeps the flag for the importer",
          blinn_opacity.get("invert") is True, blinn_opacity.get("invert"))
    check("and carries the texture rather than a value",
          blinn_opacity.get("texture", {}).get("path", "").endswith(".tx"),
          blinn_opacity.get("texture"))

    # Each legacy shader's own gloss control, rather than one pinned number
    # per type. Before this a blinn arrived at 0.1 whatever the artist set.
    def roughness_of(material):
        channels = (by_material.get(material) or {}).get("channels", {})
        return (channels.get("roughness") or {}).get("value")

    check("blinn roughness comes from its eccentricity",
          abs(roughness_of("blinnCube_shd") - 0.45) < 1e-6,
          roughness_of("blinnCube_shd"))
    # cosinePower 30 through r = sqrt(2 / (n + 2)) is 0.25.
    check("phong roughness comes from its cosinePower",
          abs(roughness_of("phongCube_shd") - 0.25) < 1e-6,
          roughness_of("phongCube_shd"))
    check("phongE roughness comes from its own roughness attribute",
          abs(roughness_of("phongECube_shd") - 0.8) < 1e-6,
          roughness_of("phongECube_shd"))
    # Lambert has no gloss control at all, so it must keep the constant.
    check("lambert still uses the approximation",
          abs(roughness_of("lambertCube_shd") - 0.7) < 1e-6,
          roughness_of("lambertCube_shd"))
    for name in ("phongCube_shd", "phongECube_shd"):
        check("{0} is reported as supported".format(name),
              (by_material.get(name) or {}).get("supported") is True,
              (by_material.get(name) or {}).get("supported"))

    print("\nramp shader")
    ramp_channels = (by_material.get("rampCube_shd") or {}).get("channels", {})
    colour_ramp = (ramp_channels.get("base_color") or {}).get("ramp") or {}
    entries = colour_ramp.get("entries") or []
    check("the colour ramp travelled", len(entries) == 3, len(entries))
    if len(entries) == 3:
        # Written 0.0, 1.0, 0.5 and returned in creation order by Maya; a
        # gradient that is not sorted is not the one the artist drew.
        check("its stops are sorted by position",
              [round(item["position"], 3) for item in entries]
              == [0.0, 0.5, 1.0],
              [item["position"] for item in entries])
        check("position 0 is the colour Maya put there",
              entries[0]["color"] == [1.0, 0.0, 0.0], entries[0]["color"])
        check("and position 1 too",
              entries[2]["color"] == [0.0, 0.0, 1.0], entries[2]["color"])
        check("per stop interpolation is carried",
              entries[1]["interp"] == "Spline", entries[1]["interp"])
    # One enum drives every ramp; there is no per ramp input attribute.
    check("the ramp input mode is recorded",
          colour_ramp.get("input") == "Facing Angle", colour_ramp.get("input"))
    # The fallback value is the facing end, so a build that cannot use the
    # gradient still shows the colour the surface has head on.
    check("a flat fallback value comes with it",
          (ramp_channels.get("base_color") or {}).get("value")
          == [0.0, 0.0, 1.0],
          (ramp_channels.get("base_color") or {}).get("value"))

    opacity_record = ramp_channels.get("opacity") or {}
    opacity_ramp = (opacity_record.get("ramp") or {}).get("entries") or []
    check("the transparency ramp became opacity",
          bool(opacity_ramp)
          and abs(opacity_ramp[0]["color"][0] - 0.75) < 1e-6,
          opacity_ramp[0]["color"] if opacity_ramp else None)
    check("and its invert flag is cleared so nobody inverts twice",
          opacity_record.get("invert") is False, opacity_record.get("invert"))
    # eccentricity still drives roughness; the ramps do not replace it.
    check("eccentricity still drives roughness",
          abs((ramp_channels.get("roughness") or {}).get("value", -1) - 0.6)
          < 1e-6,
          (ramp_channels.get("roughness") or {}).get("value"))

    print("\nramp texture")

    def base_texture(payload_by_material, material):
        return (
            (payload_by_material.get(material) or {}).get("channels", {})
            .get("base_color") or {}
        ).get("texture") or {}

    # Bake Procedurals is on for this export, and it is the user's choice, so
    # it wins: baking a ramp also applies its place2dTexture, which the
    # native rebuild cannot.
    tex_record = base_texture(by_material, "rampTexCube_shd")
    check("with baking on, a V ramp is baked like any other procedural",
          tex_record.get("baked") is True, tex_record.get("baked"))
    radial = base_texture(by_material, "radialRampCube_shd")
    check("and so is a circular one", radial.get("baked") is True,
          radial.get("baked"))

    baked_stack = base_texture(by_material, "layerTexCube_shd")
    check("with baking on, a layered texture is baked like any other network",
          baked_stack.get("baked") is True and "layered" not in baked_stack,
          dict((key, baked_stack.get(key)) for key in ("baked", "layered")))

    # With baking off there is nothing to reference, and this is where the
    # gradient itself has to travel. Its own folder, so the package the
    # Blender import test reads from is left alone.
    unbaked_result = za.export_scene(
        os.path.join(OUT, "unbaked"), bake_procedurals=False
    )
    with open(unbaked_result["json_path"], "r") as handle:
        unbaked_payload = json.load(handle)
    unbaked_by_material = {}
    for mesh in unbaked_payload["meshes"]:
        for material in mesh.get("materials") or []:
            unbaked_by_material[material["material"]] = material

    cpv_unbaked = base_texture(unbaked_by_material, "cpvCube_shd") or {}
    check("an unbaked colour set channel names its set",
          cpv_unbaked.get("color_set") == "paintCol", cpv_unbaked)
    check("and is no longer an unsupported network",
          not cpv_unbaked.get("unsupported_network"), cpv_unbaked)

    tex_record = base_texture(unbaked_by_material, "rampTexCube_shd")
    tex_ramp = tex_record.get("ramp") or {}
    tex_entries = tex_ramp.get("entries") or []
    check("with baking off it is not baked",
          not tex_record.get("baked") and not (tex_record.get("path") or ""),
          (tex_record.get("baked"), tex_record.get("path")))
    # The record stays marked unresolvable; what changed is that the stops
    # now come with it instead of the channel collapsing to one colour.
    check("and is still reported as unresolvable",
          tex_record.get("unsupported_network") is True,
          tex_record.get("unsupported_network"))
    check("but its gradient travels", len(tex_entries) == 3, len(tex_entries))
    if len(tex_entries) == 3:
        check("with the stops sorted by position",
              [round(item["position"], 3) for item in tex_entries]
              == [0.0, 0.5, 1.0],
              [item["position"] for item in tex_entries])
        check("and the colours Maya had at each end",
              tex_entries[0]["color"] == [1.0, 0.0, 0.0]
              and tex_entries[2]["color"] == [0.0, 0.0, 1.0],
              [tex_entries[0]["color"], tex_entries[2]["color"]])
    check("the ramp type is recorded", tex_ramp.get("type") == "V Ramp",
          tex_ramp.get("type"))
    # One interpolation per node here, unlike a rampShader's per stop.
    check("and its single interpolation",
          tex_ramp.get("interpolation") == "Smooth",
          tex_ramp.get("interpolation"))
    # A circular ramp travels the same way; the importer is the one that
    # knows it cannot draw it, and says so.
    unbaked_radial = base_texture(unbaked_by_material, "radialRampCube_shd")
    check("a circular ramp travels too, for the importer to refuse",
          (unbaked_radial.get("ramp") or {}).get("type") == "Circular Ramp",
          (unbaked_radial.get("ramp") or {}).get("type"))

    print("\ncoverage")
    export_warnings = payload.get("export_warnings") or []
    coverage = [w for w in export_warnings if "were not exported" in w]
    check("an unsupported geometry kind is reported",
          any("aiLightPortal" in item for item in coverage), coverage)
    if coverage:
        # A count and an example, so a scene with four hundred of them says
        # so in a line rather than four hundred.
        check("with a count and an example path",
              any(item.startswith("1 ") and "|aiPortal" in item
                  for item in coverage),
              coverage)
    # And the kind that used to be the example here is carried now, so it
    # must not appear: a surface cannot be both tessellated and missing.
    check("a carried kind is not also called missing",
          not any("nurbsSurface" in item or "subdiv" in item
                  for item in coverage),
          coverage)
    # The false positive guard, and it has already earned its keep: lights
    # travel through the JSON rather than as geometry, and the first version
    # of the scan reported every one of them as lost.
    for travelled in ("mesh", "aiAreaLight", "camera", "nurbsCurve",
                      "particle", "aiVolume"):
        check('nothing that did travel is called lost: "{0}"'.format(travelled),
              not any('"{0}"'.format(travelled) in item for item in coverage),
              [item for item in coverage if travelled in item])

    print("\ntexture projection")
    # With baking on the projection is evaluated onto the UVs, which is
    # correct and is what the option is for.
    baked_proj = base_texture(by_material, "projCube_shd")
    check("with baking on a projection is baked",
          baked_proj.get("baked") is True, baked_proj.get("baked"))

    proj_tex = base_texture(unbaked_by_material, "projCube_shd")
    proj = proj_tex.get("projection") or {}
    # The bug this replaces: the walk found the file behind the projection
    # and shipped its path, so the texture arrived wrapped on the UVs.
    check("with baking off the file path is not handed over",
          not (proj_tex.get("path") or ""), proj_tex.get("path"))
    check("the projection is described instead",
          proj.get("type") == "Planar", proj.get("type"))
    check("its place3dTexture travels with it",
          proj.get("placement") == "projPlacement", proj.get("placement"))
    # Without the matrix the other side has nothing to project from.
    check("and so does the placement's world matrix",
          len(proj.get("world_matrix") or []) == 16,
          len(proj.get("world_matrix") or []))
    check("the placement's offset is in that matrix",
          abs((proj.get("world_matrix") or [0] * 16)[13] - 4.0) < 1e-6,
          (proj.get("world_matrix") or [0] * 16)[12:15])
    # The image itself is an ordinary file; only its mapping differs.
    check("the projected image path travels",
          str((proj.get("image") or {}).get("path") or "").endswith(".tx"),
          (proj.get("image") or {}).get("path"))

    sph_proj = (base_texture(unbaked_by_material, "sphProjCube_shd")
                .get("projection") or {})
    check("a Spherical projection travels with its type",
          sph_proj.get("type") == "Spherical", sph_proj.get("type"))

    cyl_proj = (base_texture(unbaked_by_material, "cylProjCube_shd")
                .get("projection") or {})
    check("a Cylindrical projection travels with its type",
          cyl_proj.get("type") == "Cylindrical", cyl_proj.get("type"))

    for label, expected in (("tri", "TriPlanar"), ("persp", "Perspective")):
        found = (base_texture(unbaked_by_material, label + "ProjCube_shd")
                 .get("projection") or {})
        check("a {0} projection travels with its type".format(expected),
              found.get("type") == expected, found.get("type"))

    ball_proj = (base_texture(unbaked_by_material, "ballProjCube_shd")
                 .get("projection") or {})
    check("a Ball projection travels too, for the importer to refuse",
          ball_proj.get("type") == "Ball", ball_proj.get("type"))

    print("\nlayered texture, unbaked package")
    stack = base_texture(
        unbaked_by_material, "layerTexCube_shd").get("layered") or {}
    layers = stack.get("layers") or []
    check("the stack was described rather than walked past",
          bool(stack), stack)
    # Three, not four: Maya is not drawing the hidden one.
    check("the hidden layer was dropped", len(layers) == 3,
          [layer.get("index") for layer in layers])
    check("layers arrive top first, as Maya orders them",
          [layer.get("blend_mode") for layer in layers]
          == ["saturate", "multiply", "over"],
          [layer.get("blend_mode") for layer in layers])
    check("each layer carries its own texture",
          len(layers) == 3
          and all((layer.get("color") or {}).get("texture", {}).get("path")
                  for layer in layers),
          [(layer.get("color") or {}).get("texture", {}).get("node")
           for layer in layers])
    check("and its own alpha",
          len(layers) > 1
          and abs(((layers[1].get("alpha") or {}).get("value") or 0) - 0.5)
          < 1e-5,
          layers[1].get("alpha") if len(layers) > 1 else None)
    check("the hidden layer's texture is nowhere in the record",
          "layerHiddenTex" not in json.dumps(stack), stack)

    # The crossing: a layeredTexture driving a channel of a shader that is
    # itself a layer of a layeredShader. Both features were written alone.
    crossed = (unbaked_by_material.get("mayaLayerCube_shd") or {}).get(
        "layers") or []
    crossed_top = (crossed or [{}, {}])[-1]
    crossed_stack = (
        ((crossed_top.get("channels") or {}).get("base_color") or {})
        .get("texture") or {}
    ).get("layered") or {}
    check("a layered texture survives inside a layered shader",
          len((crossed_stack.get("layers") or [])) == 2,
          crossed_stack.get("layers"))
    check("with its blend modes intact",
          [item.get("blend_mode")
           for item in (crossed_stack.get("layers") or [])]
          == ["multiply", "over"],
          [item.get("blend_mode")
           for item in (crossed_stack.get("layers") or [])])

    print("\nstandins")
    standins = payload.get("standins") or []
    by_standin = dict((item.get("standin"), item) for item in standins)
    check("4 standins exported", payload.get("standin_count") == 4,
          payload.get("standin_count"))
    real = by_standin.get("standinCube") or {}
    check("the Alembic standin carries its path",
          str(real.get("file_path") or "").endswith("standin_source.abc"),
          real.get("file_path"))
    check("and the file is actually on disk, since it is referenced",
          os.path.isfile(real.get("file_path") or ""), real.get("file_path"))
    check("its node type travels", real.get("node_type") == "aiStandIn",
          real.get("node_type"))
    check("and the transform Maya put it at",
          abs((real.get("world_matrix") or [0] * 16)[12] - 7.0) < 1e-4,
          (real.get("world_matrix") or [])[12:15])
    missing = by_standin.get("standinMissing") or {}
    check("the unreadable standin travels too, path and all",
          str(missing.get("file_path") or "").endswith(".ass"),
          missing.get("file_path"))
    proxy = by_standin.get("cacheProxy") or {}
    check("a gpuCache is read through its own attribute name",
          str(proxy.get("file_path") or "").endswith(".abc")
          and proxy.get("node_type") == "gpuCache",
          (proxy.get("node_type"), proxy.get("file_path")))
    # Bounds are the proxy Maya draws, not a claim about the file: measured,
    # the viewport fills them in and a headless export reads the default.
    check("the bounds travel as Maya has them",
          len(real.get("bounds_min") or []) == 3
          and len(real.get("bounds_max") or []) == 3,
          (real.get("bounds_min"), real.get("bounds_max")))
    check("and the coverage scan no longer reports them",
          not [item for item in (result.get("warnings") or [])
               if "aiStandIn" in item or "gpuCache" in item],
          [item for item in (result.get("warnings") or [])
           if "aiStandIn" in item or "gpuCache" in item])

    print("\npose bridge")
    from mlender_exporter.posebridge import pose_message

    bind_pose = pose_message()
    bridge_names = sorted(
        entry["name"] for entry in bind_pose["pose"]["joints"]
    )
    # Namespaces stay in the sampled names: FBX keeps them in the bone names
    # (measured), so stripping them here would leave the NSRig joints
    # unmatched in Blender -- and collide them with the root rig's.
    check("the pose samples exactly the bound chains, namespaces kept",
          bridge_names == ["Elbow_L", "NSRig:Elbow_L", "NSRig:Shoulder_L",
                           "NSRig:Wrist_L", "Shoulder_L", "Wrist_L",
                           "bridgeMid", "bridgeRoot", "bridgeTip",
                           "rootMotionRoot", "rootMotionTip"],
          bridge_names)
    check("the unbound decoy joint does not travel",
          "bridgeDecoy" not in bridge_names, bridge_names)
    check("every joint carries a 16 float world matrix",
          all(len(entry["matrix"]) == 16
              for entry in bind_pose["pose"]["joints"]))
    check("and the scene unit rides along",
          abs(bind_pose["pose"]["meters_per_maya_unit"] - 0.01) < 1e-9,
          bind_pose["pose"]["meters_per_maya_unit"])

    # A driven pose, evaluated by Maya, recorded with its expected result so
    # the Blender side can assert parity rather than plausibility.
    cmds.setAttr("bridgeMid.rotateZ", 35)
    posed_pose = pose_message()
    tip_world = cmds.xform("bridgeTip", query=True, worldSpace=True,
                           translation=True)
    cmds.setAttr("bridgeMid.rotateZ", 0)
    tip_bind = cmds.xform("bridgeTip", query=True, worldSpace=True,
                          translation=True)
    check("the driven pose moved the tip in Maya",
          abs(tip_world[0] - tip_bind[0]) > 1.0,
          (tip_bind, tip_world))
    print("\nskeleton root motion")
    root_records = payload.get("skeleton_root_motion") or []
    # Only the grouped skeleton: a root joint parented to the world has
    # nothing above it for the FBX fold to lose, so it gets no record.
    check("exactly the grouped skeleton travels with its group's truth",
          [r.get("joint") for r in root_records] == ["rootMotionRoot"]
          and root_records[0].get("parent_path", "").endswith(
              "rootMotionGrp"),
          [(r.get("joint"), r.get("parent_path")) for r in root_records])
    motion_record = root_records[0] if root_records else {}
    check("sampled on every frame of the range",
          len(motion_record.get("samples") or []) == 25,
          len(motion_record.get("samples") or []))
    check("joint and group truth in every sample",
          all(len(s.get("matrix") or []) == 16
              and len(s.get("parent_matrix") or []) == 16
              for s in motion_record.get("samples") or []))
    reference = motion_record.get("reference") or {}
    check("with the calibration anchor at the export frame",
          abs(reference.get("frame", 0) - 7.0) < 1e-6
          and len(reference.get("matrix") or []) == 16
          and len(reference.get("parent_matrix") or []) == 16,
          reference.get("frame"))
    # The Maya-evaluated truth for the Blender side to assert parity
    # against; frame 13 sits mid-curve where the spline shape differs
    # from a straight line between the keys.
    root_motion_expected = {}
    for frame in (1, 13, 25):
        cmds.currentTime(frame, edit=True)
        root_motion_expected[str(frame)] = cmds.xform(
            "rootMotionTip", query=True, worldSpace=True, translation=True)
    cmds.currentTime(restored_frame, edit=True)

    with open(os.path.join(result["package_folder"],
                           "pose_bridge_test.json"), "w") as handle:
        json.dump({
            "bind": bind_pose,
            "posed": posed_pose,
            "expected_cm": {"tip_bind": tip_bind, "tip_posed": tip_world},
            "root_motion_expected": root_motion_expected,
        }, handle)

    print("\nadvanced skeleton manifest")
    as_rigs = payload.get("as_rigs") or []
    check("both rigs detected, the referenced-style one by its namespace",
          [r.get("namespace") for r in as_rigs] == ["", "NSRig:"],
          [r.get("namespace") for r in as_rigs])
    as_rig = as_rigs[0] if as_rigs else {}
    check("the AS scene was detected from its own sets",
          as_rig.get("detected") is True, as_rig.get("detected"))
    as_chains = as_rig.get("chains") or []
    check("one declared chain travelled", len(as_chains) == 1,
          [c.get("switch") for c in as_chains])
    if as_chains:
        as_chain = as_chains[0]
        check("with its joints resolved to full names, side included",
              (as_chain.get("start"), as_chain.get("middle"),
               as_chain.get("end"))
              == ("Shoulder_L", "Elbow_L", "Wrist_L"), as_chain)
        check("its IK and pole controls named",
              as_chain.get("ik_control") == "IKArm_L"
              and as_chain.get("pole_control") == "PoleArm_L", as_chain)
        check("and the blend carried",
              abs(as_chain.get("blend", 0) - 10.0) < 1e-6,
              as_chain.get("blend"))
    fk_pairs = dict((p["control"], p["joint"])
                    for p in as_rig.get("fk_controls") or [])
    check("FK pairs verified by convention, switcher excluded",
          fk_pairs == {"FKShoulder_L": "Shoulder_L",
                       "FKElbow_L": "Elbow_L"}, fk_pairs)
    ns_rig = as_rigs[1] if len(as_rigs) > 1 else {}
    ns_chains = ns_rig.get("chains") or []
    check("the namespaced rig declares its own chain, fully qualified",
          len(ns_chains) == 1
          and (ns_chains[0].get("start"), ns_chains[0].get("end"))
          == ("NSRig:Shoulder_L", "NSRig:Wrist_L")
          and ns_chains[0].get("ik_control") == "NSRig:IKArm_L"
          and ns_chains[0].get("pole_control") == "NSRig:PoleArm_L",
          ns_chains)
    ns_pairs = dict((p["control"], p["joint"])
                    for p in ns_rig.get("fk_controls") or [])
    check("its FK pairs stay inside the namespace",
          ns_pairs == {"NSRig:FKShoulder_L": "NSRig:Shoulder_L",
                       "NSRig:FKElbow_L": "NSRig:Elbow_L"}, ns_pairs)

    print("\ninstancers")
    instancers = payload.get("instancers") or []
    check("1 instancer exported", payload.get("instancer_count") == 1,
          payload.get("instancer_count"))
    scatter = instancers[0] if instancers else {}
    # The connection arrives from the particle *shape*, and the record has to
    # name the transform: that is what the importer's particle objects are
    # keyed by, and matching shape to transform later would be guesswork.
    check("it names the particle transform, not the shape",
          str(scatter.get("points_path") or "").endswith("scatterParticle"),
          scatter.get("points_path"))
    check("and the source geometry it places",
          any(str(item).endswith("instancedGeo")
              for item in (scatter.get("sources") or [])),
          scatter.get("sources"))
    check("with one source in this fixture",
          scatter.get("source_count") == 1, scatter.get("source_count"))

    print("\nanimated visibility")
    blink_record = by_mesh.get("blinkCube") or {}
    blink_samples = blink_record.get("visibility_samples") or []
    check("a blinking mesh carries a sample per frame",
          len(blink_samples) > 1, len(blink_samples))
    if blink_samples:
        states = {
            int(item["frame"]): item.get("visible")
            for item in blink_samples if item.get("frame") is not None
        }
        check("visible at the start", states.get(1) is True, states.get(1))
        check("hidden where Maya hides it", states.get(10) is False,
              states.get(10))
        check("and visible again at the end", states.get(20) is True,
              states.get(20))
    # Sampling every mesh over the range would be slow and pointless, so a
    # mesh with no visibility curve must carry nothing at all.
    steady = by_mesh.get("stdSurfCube") or {}
    check("a mesh that does not blink carries no samples",
          "visibility_samples" not in steady,
          len(steady.get("visibility_samples") or []))

    print("\nblend shaders")
    for cube, mode, transparency in (("mayaLayerCube", "layer_shaders", 0.4),
                                     ("mayaLayerTexCube", "layer_texture",
                                      0.25)):
        record = by_material.get(cube + "_shd") or {}
        stack_layers = record.get("layers") or []
        check("{0} is supported".format(cube),
              record.get("supported") is True, record.get("supported"))
        # A blend shader describes no surface itself; reading it as one used
        # to reach for ".color" and take the whole export down.
        check("and carries no channels of its own",
              not (record.get("channels") or {}),
              sorted((record.get("channels") or {}).keys()))
        check("both layers travel", len(stack_layers) == 2,
              [item.get("shader") for item in stack_layers])
        if len(stack_layers) == 2:
            # Maya's index 0 is the top, and this list is bottom first.
            check("the bottom layer comes first",
                  str(stack_layers[0].get("shader") or "").endswith("Base"),
                  [item.get("shader") for item in stack_layers])
            check("the compositing mode travels",
                  stack_layers[1].get("compositing") == mode,
                  stack_layers[1].get("compositing"))
            value = (stack_layers[1].get("transparency") or {}).get("value")
            components = value if isinstance(value, list) else [value]
            check("and the layer's transparency, uninverted",
                  abs((components[0] or 0) - transparency) < 1e-5, value)

    cross_layers = (by_material.get("mayaLayerCube_shd") or {}).get("layers")
    cross_top = (cross_layers or [{}, {}])[-1]
    cross_base = ((cross_top.get("channels") or {}).get("base_color") or {})
    check("a layered texture inside a layered shader is baked when baking is "
          "on",
          (cross_base.get("texture") or {}).get("baked") is True,
          cross_base.get("texture"))

    mix_record = by_material.get("mixCube_shd") or {}
    mix_layers = mix_record.get("layers") or []
    check("aiMixShader is supported", mix_record.get("supported") is True,
          mix_record.get("supported"))
    check("and carries both sub shaders", len(mix_layers) == 2,
          len(mix_layers))
    if len(mix_layers) == 2:
        # shader1 is the base and must come first; a swapped pair would
        # invert the blend and is exactly what the two distinct roughnesses
        # make visible.
        check("shader1 is the bottom layer",
              mix_layers[0].get("shader", "").endswith("mixLower"),
              mix_layers[0].get("shader"))
        check("and shader2 is the one on top",
              mix_layers[1].get("shader", "").endswith("mixUpper"),
              mix_layers[1].get("shader"))
        check("the base layer has no weight of its own",
              "mix" not in mix_layers[0], mix_layers[0].get("mix"))
        check("the upper layer carries the mix as its weight",
              abs((mix_layers[1].get("mix") or {}).get("value", -1) - 0.25)
              < 1e-6,
              (mix_layers[1].get("mix") or {}).get("value"))
        # The sub shaders are real materials, not names.
        check("each layer carries its own channels",
              abs((mix_layers[0]["channels"]["roughness"]["value"] - 0.15))
              < 1e-6
              and abs((mix_layers[1]["channels"]["roughness"]["value"] - 0.65))
              < 1e-6,
              [mix_layers[0]["channels"]["roughness"]["value"],
               mix_layers[1]["channels"]["roughness"]["value"]])

    layer_record = by_material.get("layerCube_shd") or {}
    layers = layer_record.get("layers") or []
    check("aiLayerShader is supported",
          layer_record.get("supported") is True, layer_record.get("supported"))
    # Three inputs are connected but one is disabled, so a count that ignores
    # enable3 would put a shader on top that Maya was not rendering.
    check("a disabled slot does not travel", len(layers) == 2,
          [item.get("shader") for item in layers])
    if len(layers) == 2:
        check("its enabled layer keeps its own mix",
              abs((layers[1].get("mix") or {}).get("value", -1) - 0.4) < 1e-6,
              (layers[1].get("mix") or {}).get("value"))
        check("and the disabled one is not in the list",
              not any("layerDisabled" in item.get("shader", "")
                      for item in layers),
              [item.get("shader") for item in layers])
    # An ordinary shader must not grow a layer list.
    check("a plain shader carries no layers",
          not (by_material.get("stdSurfCube_shd") or {}).get("layers"),
          (by_material.get("stdSurfCube_shd") or {}).get("layers"))

    surface_channels = (
        (by_material.get("surfaceCube_shd") or {}).get("channels", {})
    )
    check("surfaceShader drives emission, not base colour",
          abs((surface_channels.get("emission") or {}).get("value", [0])[0]
              - 0.9) < 1e-6,
          (surface_channels.get("emission") or {}).get("value"))
    check("its outTransparency becomes opacity 0.8",
          abs((surface_channels.get("opacity") or {}).get("value", [0])[0]
              - 0.8) < 1e-6,
          (surface_channels.get("opacity") or {}).get("value"))

    print("\nglossiness inversion, the other half of the same decision")
    # Redshift is not installed here, but the conversion only asks whether the
    # flag attribute exists, so a real Maya shader carrying a real flag name
    # exercises it honestly. What is under test is which branch a record takes,
    # and that is the branch that shipped a textured transparency uninverted.
    from mlender_exporter.constants import REDSHIFT_GLOSSINESS_FLAGS
    from mlender_exporter.shaders import apply_glossiness_conversion

    probe = cmds.shadingNode("blinn", asShader=True, name="glossProbe")
    cmds.addAttr(probe, longName=REDSHIFT_GLOSSINESS_FLAGS[0],
                 attributeType="bool")
    cmds.setAttr(probe + "." + REDSHIFT_GLOSSINESS_FLAGS[0], True)

    flat = {"value": 0.9}
    apply_glossiness_conversion(probe, flat)
    check("a flat glossiness of 0.9 becomes roughness 0.1",
          abs(flat["value"] - 0.1) < 1e-6, flat.get("value"))
    check("and carries no invert flag, having been inverted already",
          not flat.get("invert"), flat.get("invert"))

    mapped = {"value": 0.9, "texture": {"path": "/nowhere/gloss.tx"}}
    apply_glossiness_conversion(probe, mapped)
    check("a mapped glossiness sends the flag instead",
          mapped.get("invert") is True, mapped.get("invert"))
    check("and leaves the stale value alone", abs(mapped["value"] - 0.9) < 1e-6,
          mapped.get("value"))

    # A procedural the bake could not resolve: a texture record with no file
    # in it. The importer will fall through to the value, so the value is the
    # only place left that can be inverted.
    procedural = {"value": 0.9, "texture": {"node": "ramp1",
                                            "node_type": "ramp"}}
    apply_glossiness_conversion(probe, procedural)
    check("a texture record with no file behind it inverts the value",
          abs(procedural["value"] - 0.1) < 1e-6, procedural.get("value"))
    check("and does not send a flag nothing will act on",
          not procedural.get("invert"), procedural.get("invert"))

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
          udim.get("original_path", "").endswith("tile.1001.png"),
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
    check("sheen roughness 0.25 sent raw",
          abs(tiled.get("sheen_roughness", {}).get("value", 0) - 0.25) < 1e-5)
    check("and tagged as being on the Arnold standard surface scale",
          tiled.get("sheen_roughness", {}).get("source_semantic")
          == "arnold_standard_sheen_roughness",
          tiled.get("sheen_roughness", {}).get("source_semantic"))
    check("subsurface weight 0.3",
          abs(tiled.get("subsurface", {}).get("value", 0) - 0.3) < 1e-5)
    check("subsurface scale 2.5",
          abs(tiled.get("subsurface_scale", {}).get("value", 0) - 2.5) < 1e-5)
    check("anisotropy 0.35",
          abs(tiled.get("anisotropic", {}).get("value", 0) - 0.35) < 1e-5)

    print("\nuv sets")
    uv_channels = channels("uvLinkCube")
    default_texture = (
        uv_channels.get("base_color", {}).get("texture", {})
    )
    second_texture = (
        uv_channels.get("coat_tint", {}).get("texture", {})
    )
    check("the default-linked texture records no uv set",
          "uv_set" not in default_texture, default_texture.get("uv_set"))
    check("the linked texture records its uv set",
          (second_texture.get("uv_set") or {}).get("name") == "secondUV",
          second_texture.get("uv_set"))
    check("one mesh, so no conflict is claimed",
          "conflict" not in (second_texture.get("uv_set") or {}),
          second_texture.get("uv_set"))

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
