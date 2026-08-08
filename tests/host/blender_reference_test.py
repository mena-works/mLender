# -*- coding: utf-8 -*-
"""What two references of one asset become in Blender.

    "C:\\Program Files\\Blender Foundation\\Blender 5.2\\blender.exe" ^
        --background --factory-startup --python tests/host/blender_reference_test.py

Run maya_reference_test.py first.
"""
import glob
import os
import sys
import tempfile

import bpy

TOOL_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)
TEST_ROOT = os.path.join(tempfile.gettempdir(), "mlender_reference_test")

if TOOL_ROOT not in sys.path:
    sys.path.insert(0, TOOL_ROOT)

failures = []


def check(label, condition, detail=""):
    if condition:
        print("  ok    {0}".format(label))
    else:
        failures.append("{0} {1}".format(label, detail))
        print("  FAIL  {0}  {1}".format(label, detail))


def main():
    import mlender_importer as mi

    packages = sorted(glob.glob(os.path.join(TEST_ROOT, "mLender_*")))
    if not packages:
        raise SystemExit(
            "No package in {0}. Run maya_reference_test.py first.".format(
                TEST_ROOT
            )
        )
    print("Blender {0}, importer build {1}".format(
        bpy.app.version_string, mi.BUILD_VERSION))
    result = mi.import_scene_package(packages[-1], import_scale=1.0)

    print("\nreferenced assets")
    hero_a = bpy.data.objects.get("heroA:body")
    hero_b = bpy.data.objects.get("heroB:body")
    check("both references arrived under their own names",
          hero_a is not None and hero_b is not None,
          sorted(o.name for o in bpy.data.objects if o.type == "MESH"))
    check("and neither was numbered instead",
          bpy.data.objects.get("body.001") is None)
    if hero_a and hero_b:
        # Maya had heroB twenty centimetres across. A swap between two
        # identically named meshes would show up here and nowhere else.
        check("heroA is the one at the origin",
              abs(hero_a.matrix_world.translation.x) < 1e-4,
              round(hero_a.matrix_world.translation.x, 4))
        check("and heroB is the one Maya moved",
              abs(hero_b.matrix_world.translation.x - 0.2) < 1e-4,
              round(hero_b.matrix_world.translation.x, 4))
        check("they are two objects, not one reused",
              hero_a is not hero_b and hero_a.data is not hero_b.data)
        a_materials = [m.name for m in hero_a.data.materials]
        b_materials = [m.name for m in hero_b.data.materials]
        check("each carries its own material",
              a_materials and b_materials and a_materials != b_materials,
              (a_materials, b_materials))

    print("\nreference collections")
    for name in ("heroA", "heroB"):
        collection = bpy.data.collections.get(name)
        check("{0} became a collection of its own".format(name),
              collection is not None)
        if collection:
            # The asset's own group nests inside the reference, so the two
            # references are separable in the outliner rather than merged.
            check("holding the asset's group",
                  len(collection.children) == 1,
                  [c.name for c in collection.children])

    print()
    if failures:
        print("FAILURES ({0}):".format(len(failures)))
        for item in failures:
            print("  - {0}".format(item))
        return 1
    print("all reference import assertions passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
