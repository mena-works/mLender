# -*- coding: utf-8 -*-
"""What aiColorCorrect actually computes, measured one parameter at a time.

Not a test. This is the rig that produces the numbers the Unreal receiver
rebuilds the node from, in the same way the layeredTexture table was produced.

**An Arnold node has to be measured by Arnold.** The first version of this rig
used ``convertSolidTx``, the way the layeredTexture measurement did, and every
row came back 0.5 grey -- including the identity row, which is what gave it
away. That bake runs Maya's own texture evaluation, which knows nothing about
``aiColorCorrect``; it works for ``layeredTexture`` because that node is
Maya's. So this exports an ass and renders it with kick, and the surface is an
``aiFlat``, whose pixel is its colour with no lighting in the way.

Run it in mayapy, then read the result with color_correct_read.py in Blender:

    "C:\\Program Files\\Autodesk\\Maya2023\\bin\\mayapy.exe" \\
        tests/calibration/color_correct_maya.py
    "C:\\Program Files\\Blender Foundation\\Blender 5.2\\blender.exe" \\
        --background --factory-startup --python \\
        tests/calibration/color_correct_read.py

The input is a flat colour whose three channels all differ (0.2, 0.5, 0.8).
Equal channels would hide anything that works per channel, and 0.5 everywhere
would make a multiply and a gamma agree.
"""
from __future__ import print_function

import json
import os
import re
import subprocess
import tempfile

import maya.standalone

maya.standalone.initialize("python")

import maya.cmds as cmds          # noqa: E402


OUT = os.path.join(tempfile.gettempdir(), "ml_colorcorrect")
KICK = r"C:\Program Files\Autodesk\Arnold\maya2023\bin\kick.exe"
INPUT = (0.2, 0.5, 0.8)
RESOLUTION = 8

# One parameter at a time, each set to a value that cannot be confused with
# another parameter's effect on this input, plus one pair so the composition
# order can be told apart from either alone.
TRIALS = [
    ("identity", {}),
    ("gamma2", {"gamma": 2.0}),
    ("exposure1", {"exposure": 1.0}),
    ("saturation0", {"saturation": 0.0}),
    ("contrast2", {"contrast": 2.0}),
    ("hueshift25", {"hueShift": 0.25}),
    ("invert", {"invert": True}),
    ("multiply", {"multiply": (2.0, 1.0, 0.5)}),
    ("add", {"add": (0.1, 0.0, -0.1)}),
    ("multiply2_gamma2", {"multiply": (2.0, 2.0, 2.0), "gamma": 2.0}),
    ("add1_gamma2", {"add": (0.1, 0.1, 0.1), "gamma": 2.0}),
    ("multiply2_add1", {"multiply": (2.0, 2.0, 2.0), "add": (0.1, 0.1, 0.1)}),
    # Where the rest sit relative to gamma, which is the pivot of the chain.
    ("contrast2_gamma2", {"contrast": 2.0, "gamma": 2.0}),
    ("exposure1_gamma2", {"exposure": 1.0, "gamma": 2.0}),
    ("invert_gamma2", {"invert": True, "gamma": 2.0}),
    ("invert_multiply2", {"invert": True, "multiply": (2.0, 2.0, 2.0)}),
    ("saturation0_gamma2", {"saturation": 0.0, "gamma": 2.0}),
    ("contrast2_multiply2", {"contrast": 2.0,
                             "multiply": (2.0, 2.0, 2.0)}),
    ("contrast2_add1", {"contrast": 2.0, "add": (0.1, 0.1, 0.1)}),
]


def build_scene():
    cmds.file(new=True, force=True)
    cmds.loadPlugin("mtoa", quiet=True)

    plane = cmds.polyPlane(name="ccPlane", width=4, height=4,
                           subdivisionsX=1, subdivisionsY=1)[0]
    cmds.setAttr(plane + ".rotateX", 90)

    source = cmds.shadingNode("aiFlat", asShader=True, name="ccSource")
    cmds.setAttr(source + ".color", INPUT[0], INPUT[1], INPUT[2],
                 type="double3")
    node = cmds.shadingNode("aiColorCorrect", asUtility=True, name="ccNode")
    cmds.connectAttr(source + ".outColor", node + ".input", force=True)
    # aiFlat again on the way out: it returns its colour as the pixel, so the
    # render is the node's output and nothing else.
    surface = cmds.shadingNode("aiFlat", asShader=True, name="ccSurface")
    cmds.connectAttr(node + ".outColor", surface + ".color", force=True)

    engine = cmds.sets(renderable=True, noSurfaceShader=True, empty=True,
                       name="ccSG")
    cmds.connectAttr(surface + ".outColor", engine + ".surfaceShader",
                     force=True)
    cmds.sets(plane, edit=True, forceElement=engine)

    camera = cmds.camera(name="ccCam")[0]
    cmds.setAttr(camera + ".translateZ", 6)
    cmds.setAttr(camera + ".orthographic", 1)
    cmds.setAttr(camera + ".orthographicWidth", 2)
    return node, cmds.listRelatives(camera, shapes=True, fullPath=True)[0]


def render(camera, label):
    if not os.path.isdir(OUT):
        os.makedirs(OUT)
    cmds.setAttr("defaultRenderGlobals.currentRenderer", "arnold",
                 type="string")
    try:
        import mtoa.core as core

        core.createOptions()
    except Exception:
        pass
    for plug, value in (
        ("defaultArnoldRenderOptions.AASamples", 1),
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

    ass_path = os.path.join(OUT, "{0}.ass".format(label)).replace("\\", "/")
    cmds.arnoldExportAss(filename=ass_path, selected=False, mask=255,
                         boundingBox=True, cam=camera,
                         lightLinks=0, shadowLinks=0)
    with open(ass_path, "r") as handle:
        text = handle.read()
    text = re.sub(r'^ input "defaultArnoldDenoiser"\n', "", text, flags=re.M)
    with open(ass_path, "w") as handle:
        handle.write(text)

    exr = os.path.join(OUT, "{0}.exr".format(label))
    process = subprocess.Popen(
        [KICK, "-i", ass_path, "-o", exr, "-r", str(RESOLUTION),
         str(RESOLUTION), "-dw", "-nostdin", "-v", "0"],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
    )
    output = process.communicate()[0]
    if isinstance(output, bytes):
        output = output.decode("utf-8", "replace")
    for line in output.splitlines():
        if "ERROR" in line or "licen" in line.lower():
            print("  kick: {0}".format(line.strip()))
    return exr if os.path.isfile(exr) else ""


def main():
    node, camera = build_scene()
    manifest = {"input": list(INPUT), "renders": []}
    for label, settings in TRIALS:
        restore = []
        for attr, value in settings.items():
            if not cmds.attributeQuery(attr, node=node, exists=True):
                print("MLCC {0}: {1} absent".format(label, attr))
                continue
            if isinstance(value, tuple):
                restore.append((attr, cmds.getAttr(node + "." + attr)[0]))
                cmds.setAttr(node + "." + attr, value[0], value[1], value[2],
                             type="double3")
            else:
                restore.append((attr, cmds.getAttr(node + "." + attr)))
                cmds.setAttr(node + "." + attr, value)
        path = render(camera, label)
        print("MLCC rendered {0:<18} -> {1}".format(label, path or "FAILED"))
        manifest["renders"].append({
            "label": label,
            "settings": {k: list(v) if isinstance(v, tuple) else v
                         for k, v in settings.items()},
            "path": path,
        })
        for attr, value in restore:
            if isinstance(value, tuple):
                cmds.setAttr(node + "." + attr, value[0], value[1], value[2],
                             type="double3")
            else:
                cmds.setAttr(node + "." + attr, value)

    manifest_path = os.path.join(OUT, "manifest.json")
    with open(manifest_path, "w") as handle:
        json.dump(manifest, handle, indent=2)
    print("MLCC manifest = {0}".format(manifest_path))


if __name__ == "__main__":
    main()
