# -*- coding: utf-8 -*-
"""Referenced assets, which need their own scene to exist at all.

A reference has to be a file on disk before it can be referenced, so this
builds an asset, saves it, and references it twice into a fresh scene. That is
the case the rest of the suite cannot reach: two references of one asset give
two meshes both called "body", inside groups both called "assetGrp", with the
same material name. Everything that tells them apart is the namespace.

    "C:\\Program Files\\Autodesk\\Maya2023\\bin\\mayapy.exe" ^
        tests/host/maya_reference_test.py

Writes its package to <temp>/mlender_reference_test, which
blender_reference_test.py then reads.
"""
from __future__ import print_function

import glob
import json
import os
import shutil
import sys
import tempfile

import maya.standalone

maya.standalone.initialize(name="python")

import maya.cmds as cmds  # noqa: E402

TOOL_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)
OUT = os.path.join(tempfile.gettempdir(), "mlender_reference_test")

if TOOL_ROOT not in sys.path:
    sys.path.insert(0, TOOL_ROOT)

failures = []


def check(label, condition, detail=""):
    if condition:
        print("  ok    {0}".format(label))
    else:
        failures.append("{0} {1}".format(label, detail))
        print("  FAIL  {0}  {1}".format(label, detail))


def build_asset_file():
    cmds.file(new=True, force=True)
    cmds.currentUnit(linear="cm")
    cmds.loadPlugin("mtoa", quiet=True)
    shader = cmds.shadingNode("aiStandardSurface", asShader=True,
                              name="assetShader")
    engine = cmds.sets(renderable=True, noSurfaceShader=True, empty=True,
                       name="assetSG")
    cmds.connectAttr(shader + ".outColor", engine + ".surfaceShader",
                     force=True)
    body = cmds.polyCube(name="body")[0]
    cmds.sets(body, edit=True, forceElement=engine)
    cmds.group(body, name="assetGrp")

    path = os.path.join(OUT, "asset.ma").replace("\\", "/")
    cmds.file(rename=path)
    cmds.file(save=True, type="mayaAscii", force=True)
    return path


def main():
    if os.path.isdir(OUT):
        shutil.rmtree(OUT)
    os.makedirs(OUT)

    asset = build_asset_file()

    cmds.file(new=True, force=True)
    cmds.currentUnit(linear="cm")
    cmds.loadPlugin("mtoa", quiet=True)
    cmds.file(asset, reference=True, namespace="heroA")
    cmds.file(asset, reference=True, namespace="heroB")
    # Moved apart so a swap between the two would be visible as a position.
    cmds.setAttr("heroB:assetGrp.translateX", 20)

    import mlender_exporter as ml

    print("exporter build:", ml.BUILD_VERSION)
    result = ml.export_scene(OUT, bake_procedurals=False)
    with open(result["json_path"], "r") as handle:
        payload = json.load(handle)

    print("\nreferenced meshes")
    by_mesh = {record.get("mesh"): record for record in payload["meshes"]}
    check("both references were exported", len(payload["meshes"]) == 2,
          len(payload["meshes"]))
    # Without the namespace both are "body" and Blender numbers the second
    # one, leaving nothing to say which reference either came from.
    check("colliding names keep their namespace",
          set(by_mesh) == {"heroA:body", "heroB:body"}, sorted(by_mesh))
    check("the group trail leads with the namespace",
          (by_mesh.get("heroA:body") or {}).get("groups")
          == ["heroA", "assetGrp"],
          (by_mesh.get("heroA:body") or {}).get("groups"))
    check("so the two references do not share a trail",
          (by_mesh.get("heroB:body") or {}).get("groups")
          == ["heroB", "assetGrp"],
          (by_mesh.get("heroB:body") or {}).get("groups"))
    # The material cache keys on the full name, so these were already distinct.
    materials = [
        material.get("material_full_name")
        for record in payload["meshes"]
        for material in record.get("materials") or []
    ]
    check("each reference keeps its own material",
          set(materials) == {"heroA:assetShader", "heroB:assetShader"},
          sorted(materials))

    print("\npackage: {0}".format(result["package_folder"]))
    print()
    if failures:
        print("FAILURES ({0}):".format(len(failures)))
        for item in failures:
            print("  - {0}".format(item))
        return 1
    print("all reference export assertions passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
