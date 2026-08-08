# -*- coding: utf-8 -*-
"""Maya half of the texture projection measurement.

    "C:\\Program Files\\Autodesk\\Maya2023\\bin\\mayapy.exe" ^
        tests/calibration/projection_match_maya.py

Bakes every one of Maya's nine projection types onto one sphere's UVs and
writes the package next to them. The Blender half then builds its candidate
node tree on the same mesh, bakes it into the same UV space, and compares.

A rig, not a test: it produces the mapping table rather than checking it.
Baking is what makes the comparison possible at all, because a bake is
already in UV space and the two applications share the mesh through the FBX,
so the same pixel means the same surface point on both sides.
"""
from __future__ import absolute_import

import json
import os
import shutil
import sys
import tempfile

import maya.standalone

maya.standalone.initialize("Python")

import maya.cmds as cmds  # noqa: E402

TOOL_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)
if TOOL_ROOT not in sys.path:
    sys.path.insert(0, TOOL_ROOT)

OUT = os.path.join(tempfile.gettempdir(), "mlender_projection_match")
# Index into Maya's projType enum, which was read from a live node.
PROJECTION_TYPES = (
    (1, "Planar"),
    (2, "Spherical"),
    (3, "Cylindrical"),
    (4, "Ball"),
    (5, "Cubic"),
    (6, "TriPlanar"),
    (7, "Concentric"),
    (8, "Perspective"),
)
RESOLUTION = 128


def quad_texture():
    """The four quadrant image, written by the Blender half."""
    return os.path.join(OUT, "quad.png").replace("\\", "/")


def build_scene():
    cmds.loadPlugin("mtoa", quiet=True)
    import mtoa.core

    mtoa.core.createOptions()

    # One sphere, unrotated and at the origin, so the placement's local space
    # and the world are the same thing and nothing else can explain a
    # difference between the two sides.
    sphere = cmds.polySphere(name="projSphere", r=1, sx=32, sy=16)[0]
    placement = cmds.shadingNode("place3dTexture", asUtility=True,
                                 name="projPlacement")

    shaders = []
    for index, label in PROJECTION_TYPES:
        shader = cmds.shadingNode("aiStandardSurface", asShader=True,
                                  name="proj{0}Shd".format(label))
        projection = cmds.shadingNode("projection", asTexture=True,
                                      name="proj{0}".format(label))
        cmds.setAttr(projection + ".projType", index)
        image = cmds.shadingNode("file", asTexture=True,
                                 name="proj{0}File".format(label))
        cmds.setAttr(image + ".fileTextureName", quad_texture(), type="string")
        cmds.connectAttr(image + ".outColor", projection + ".image",
                         force=True)
        cmds.connectAttr(placement + ".worldInverseMatrix[0]",
                         projection + ".placementMatrix", force=True)
        cmds.connectAttr(projection + ".outColor", shader + ".baseColor",
                         force=True)
        shaders.append((label, shader, projection))
    return sphere, placement, shaders


def main():
    if not os.path.isfile(quad_texture()):
        raise SystemExit(
            "Run the Blender half first; it writes {0}.".format(quad_texture())
        )

    sphere, placement, shaders = build_scene()

    from mlender_exporter.bake import BakeContext, bake_channel

    results = {}
    for label, shader, projection in shaders:
        context = BakeContext(
            os.path.join(OUT, "maya"), resolution=RESOLUTION, enabled=True,
            warnings=[],
        )
        context.mesh = cmds.ls(sphere, long=True)[0]
        record = bake_channel(
            context, shader, "base_color", projection + ".outColor"
        )
        path = (record or {}).get("path") or ""
        results[label] = path
        print("  {0:12} -> {1}".format(label, os.path.basename(path) or "FAILED"))

    # The sphere itself, so the Blender half compares against the same
    # geometry and the same UVs rather than a rebuild that might differ.
    import mlender_exporter as exporter

    package = exporter.export_scene(
        os.path.join(OUT, "package"), bake_procedurals=False
    )
    manifest = {
        "baked": results,
        "package_folder": package["package_folder"],
        "resolution": RESOLUTION,
    }
    with open(os.path.join(OUT, "manifest.json"), "w") as handle:
        json.dump(manifest, handle, indent=2)
    print("\nwrote {0}".format(os.path.join(OUT, "manifest.json")))
    return 0


if __name__ == "__main__":
    sys.exit(main())
