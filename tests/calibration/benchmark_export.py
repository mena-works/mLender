# -*- coding: utf-8 -*-
"""Measure how the exporter scales, and show where the time goes.

Not a pass/fail test: it produces numbers. A lookdev scene is not five cubes,
and nothing here had ever been run against a scene big enough to say whether
the tool is usable at production size.

    "C:\\Program Files\\Autodesk\\Maya2023\\bin\\mayapy.exe" ^
        tests/calibration/benchmark_export.py [meshes] [materials]

Prints a phase breakdown and the twenty hottest functions by cumulative time,
which is what actually points at the bottleneck.
"""
from __future__ import print_function

import cProfile
import os
import pstats
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
OUT = os.path.join(tempfile.gettempdir(), "za_lookdev_benchmark")

if TOOL_ROOT not in sys.path:
    sys.path.insert(0, TOOL_ROOT)

MESH_COUNT = int(sys.argv[1]) if len(sys.argv) > 1 else 400
MATERIAL_COUNT = int(sys.argv[2]) if len(sys.argv) > 2 else 60
LIGHT_COUNT = 20
GROUP_COUNT = 12


def build_scene():
    """A scene shaped like a real one: many meshes sharing fewer materials."""
    cmds.file(new=True, force=True)
    cmds.loadPlugin("mtoa", quiet=True)

    texture_path = os.path.join(OUT, "bench.tx").replace("\\", "/")
    with open(texture_path, "w") as handle:
        handle.write("only the path is read")

    materials = []
    for index in range(MATERIAL_COUNT):
        shader = cmds.shadingNode(
            "aiStandardSurface", asShader=True, name="benchShd{0}".format(index)
        )
        engine = cmds.sets(
            renderable=True, noSurfaceShader=True, empty=True,
            name="benchSG{0}".format(index),
        )
        cmds.connectAttr(
            shader + ".outColor", engine + ".surfaceShader", force=True
        )
        # A texture behind a correction node, which is what makes the upstream
        # walk do real work on every channel.
        file_node = cmds.shadingNode(
            "file", asTexture=True, name="benchTex{0}".format(index)
        )
        cmds.setAttr(
            file_node + ".fileTextureName", texture_path, type="string"
        )
        correct = cmds.shadingNode(
            "aiColorCorrect", asUtility=True, name="benchCC{0}".format(index)
        )
        cmds.connectAttr(file_node + ".outColor", correct + ".input", force=True)
        cmds.connectAttr(correct + ".outColor", shader + ".baseColor", force=True)
        materials.append(engine)

    groups = [cmds.group(empty=True, name="benchGrp{0}".format(i))
              for i in range(GROUP_COUNT)]

    for index in range(MESH_COUNT):
        mesh = cmds.polyCube(name="benchMesh{0}".format(index))[0]
        cmds.sets(mesh, edit=True, forceElement=materials[index % MATERIAL_COUNT])
        cmds.parent(mesh, groups[index % GROUP_COUNT])
        if index % 4 == 0:
            shape = cmds.listRelatives(mesh, shapes=True, fullPath=True)[0]
            cmds.setAttr(shape + ".aiSubdivType", 1)

    for index in range(LIGHT_COUNT):
        shape = cmds.createNode(
            "aiAreaLight", name="benchLightShape{0}".format(index)
        )
        transform = cmds.listRelatives(shape, parent=True, fullPath=True)[0]
        cmds.setAttr(transform + ".translateY", 10.0 + index)

    camera = cmds.rename(cmds.camera()[0], "benchCam")
    cmds.setAttr(camera + ".translateZ", 40.0)


def main():
    if os.path.isdir(OUT):
        shutil.rmtree(OUT)
    os.makedirs(OUT)

    print("building a scene with {0} meshes, {1} materials, {2} lights".format(
        MESH_COUNT, MATERIAL_COUNT, LIGHT_COUNT))
    started = time.time()
    build_scene()
    print("  scene built in {0:.1f}s".format(time.time() - started))

    import za_lookdev_exporter as za

    print("\nexporter build {0}".format(za.BUILD_VERSION))
    profiler = cProfile.Profile()
    started = time.time()
    profiler.enable()
    result = za.export_lookdev(OUT, bake_procedurals=False)
    profiler.disable()
    elapsed = time.time() - started

    size = os.path.getsize(result["json_path"]) / 1024.0
    print("\nexport took {0:.1f}s for {1} meshes  ({2:.1f} ms per mesh)".format(
        elapsed, result["mesh_count"],
        1000.0 * elapsed / max(1, result["mesh_count"])))
    print("JSON is {0:.0f} KB".format(size))

    print("\nhottest twenty by cumulative time")
    stats = pstats.Stats(profiler)
    stats.sort_stats("cumulative")
    stats.print_stats(20)
    return 0


if __name__ == "__main__":
    sys.exit(main())
