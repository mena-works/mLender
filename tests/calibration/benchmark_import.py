# -*- coding: utf-8 -*-
"""Measure how the importer scales on the package benchmark_export.py wrote.

    "C:\\Program Files\\Autodesk\\Maya2023\\bin\\mayapy.exe" ^
        tests/calibration/benchmark_export.py 1600 60
    "C:\\Program Files\\Blender Foundation\\Blender 5.2\\blender.exe" ^
        --background --factory-startup --python tests/calibration/benchmark_import.py

Like its export counterpart this produces numbers, not a verdict.
"""
import cProfile
import glob
import os
import pstats
import sys
import tempfile
import time

import bpy

TOOL_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)
OUT = os.path.join(tempfile.gettempdir(), "ml_lookdev_benchmark")

if TOOL_ROOT not in sys.path:
    sys.path.insert(0, TOOL_ROOT)


def main():
    packages = sorted(glob.glob(os.path.join(OUT, "mLender_*")))
    if not packages:
        raise SystemExit(
            "No benchmark package in {0}. Run benchmark_export.py first.".format(
                OUT
            )
        )

    import mlender_importer as zi

    print("Blender {0}, importer build {1}".format(
        bpy.app.version_string, zi.BUILD_VERSION))

    profiler = cProfile.Profile()
    started = time.time()
    profiler.enable()
    result = zi.import_scene_package(packages[-1], import_scale=1.0)
    profiler.disable()
    elapsed = time.time() - started

    print("\nimport took {0:.1f}s for {1} meshes and {2} materials"
          "  ({3:.1f} ms per mesh)".format(
              elapsed, result["mesh_count"], result["material_count"],
              1000.0 * elapsed / max(1, result["mesh_count"])))
    print("warnings: {0}".format(len(result["warnings"])))

    print("\nhottest fifteen by cumulative time")
    stats = pstats.Stats(profiler)
    stats.sort_stats("cumulative")
    stats.print_stats(15)
    return 0


if __name__ == "__main__":
    sys.exit(main())
