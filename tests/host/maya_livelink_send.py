# -*- coding: utf-8 -*-
"""Maya half of the end-to-end LiveLink test: export and press send.

    "C:\\Program Files\\Autodesk\\Maya2023\\bin\\mayapy.exe" ^
        tests/host/maya_livelink_send.py

Pairs with tests/host/unreal_livelink_test.py, which must be installed as the
Unreal project's Content/Python/init_unreal.py. Order does not matter: this
waits for the listener to report the socket bound before sending, so the test
cannot pass or fail on a race.

The send goes through the production client, so this is the button an artist
presses rather than a reimplementation of it.
"""
from __future__ import print_function

import os
import shutil
import sys
import tempfile
import time

import maya.standalone

maya.standalone.initialize(name="python")

import maya.cmds as cmds  # noqa: E402

# Three levels up: tests/<group>/<file>.py
TOOL_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)
if TOOL_ROOT not in sys.path:
    sys.path.insert(0, TOOL_ROOT)

OUT = os.path.join(tempfile.gettempdir(), "ml_livelink_e2e")
READY = os.path.join(OUT, "listener_ready")


def main():
    deadline = time.time() + 420.0
    while not os.path.isfile(READY):
        if time.time() > deadline:
            print("MAYA_SEND listener never reported ready")
            return 1
        time.sleep(2.0)
    print("MAYA_SEND listener is ready:", open(READY).read().strip())

    cmds.loadPlugin("mtoa", quiet=True)
    for name in ("mLender_01",):
        folder = os.path.join(OUT, name)
        if os.path.isdir(folder):
            shutil.rmtree(folder)

    cmds.file(new=True, force=True)
    cmds.currentUnit(linear="cm")

    cube = cmds.polyCube(width=40, height=40, depth=40, name="sendCube")[0]
    cmds.setAttr(cube + ".translateY", 20.0)
    shader = cmds.shadingNode(
        "aiStandardSurface", asShader=True, name="sendShader"
    )
    cmds.setAttr(shader + ".baseColor", 0.2, 0.6, 0.9, type="double3")
    cmds.setAttr(shader + ".specularRoughness", 0.35)
    engine = cmds.sets(
        renderable=True, noSurfaceShader=True, empty=True, name="sendSG"
    )
    cmds.connectAttr(shader + ".outColor", engine + ".surfaceShader", force=True)
    cmds.sets(cube, edit=True, forceElement=engine)

    light = cmds.createNode("aiAreaLight", name="sendLightShape")
    light_tf = cmds.listRelatives(light, parent=True, fullPath=True)[0]
    cmds.setAttr(light + ".aiTranslator", "quad", type="string")
    cmds.setAttr(light + ".intensity", 60.0)
    cmds.setAttr(light + ".exposure", 1.0)
    cmds.setAttr(light_tf + ".translate", 0.0, 200.0, 0.0, type="double3")
    cmds.setAttr(light_tf + ".rotateX", -90.0)

    camera_tf = cmds.rename(cmds.camera()[0], "sendCam")
    cmds.setAttr(camera_tf + ".translate", 0.0, 120.0, 300.0, type="double3")
    cmds.setAttr(camera_tf + ".rotateX", -18.0)

    import mlender_exporter as ml

    result = ml.export_scene(OUT)
    print("MAYA_SEND exporter build:", ml.BUILD_VERSION)
    print("MAYA_SEND package:", result["package_folder"])

    # The real send, through the real client. This is the button.
    ml.livelink.send_package(result)
    print("MAYA_SEND sent to 127.0.0.1:50505")
    return 0


if __name__ == "__main__":
    sys.exit(main())
