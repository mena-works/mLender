# -*- coding: utf-8 -*-
"""The three import modes, against a real Blender.

Reads the package maya_export_test.py wrote and imports it more than once,
which is the only way to test Merge at all: it is defined by what survives the
*second* import.

    "C:\\Program Files\\Blender Foundation\\Blender 5.2\\blender.exe" ^
        --background --factory-startup --python tests/host/blender_modes_test.py

Run maya_export_test.py first.
"""
import glob
import os
import sys
import tempfile

import bpy

TOOL_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)
TEST_ROOT = os.path.join(tempfile.gettempdir(), "mlender_test")

if TOOL_ROOT not in sys.path:
    sys.path.insert(0, TOOL_ROOT)

failures = []


def check(label, condition, detail=""):
    if condition:
        print("  ok    {0}".format(label))
    else:
        failures.append("{0} {1}".format(label, detail))
        print("  FAIL  {0}  {1}".format(label, detail))


def find_package():
    packages = sorted(glob.glob(os.path.join(TEST_ROOT, "mLender_*")))
    if not packages:
        raise SystemExit(
            "No package in {0}. Run maya_export_test.py first.".format(TEST_ROOT)
        )
    return packages[-1]


def main():
    import mlender_importer as mi
    from mlender_importer.merge import count_stale_objects, remove_stale_objects

    package = find_package()
    print("Blender {0}, importer build {1}".format(
        bpy.app.version_string, mi.BUILD_VERSION))

    print("\nreplace")
    first = mi.import_scene_package(package, import_scale=1.0,
                                    import_mode="REPLACE")
    check("replace reports its mode", first["import_mode"] == "REPLACE",
          first["import_mode"])
    baseline_meshes = first["mesh_count"]
    check("meshes arrived", baseline_meshes > 0, baseline_meshes)

    # Two things the user might have done in Blender after an import: made
    # their own object, and put a modifier on an imported one.
    own = bpy.data.objects.new("userMadeCube", bpy.data.meshes.new("userMesh"))
    bpy.context.scene.collection.objects.link(own)
    imported = bpy.data.objects.get("stdSurfCube")
    check("an imported mesh is marked as ours",
          imported is not None and imported.get("ml_generated") is True)
    check("and records the Maya node it came from",
          imported is not None and bool(imported.get("ml_maya_path")),
          imported.get("ml_maya_path") if imported else None)
    modifier = imported.modifiers.new("UserBevel", "BEVEL")
    modifier.width = 0.123
    imported_id = imported.as_pointer()
    original_mesh_name = imported.data.name

    print("\nmerge")
    second = mi.import_scene_package(package, import_scale=1.0,
                                     import_mode="MERGE")
    check("merge reports its mode", second["import_mode"] == "MERGE",
          second["import_mode"])
    check("the user's own object survived",
          bpy.data.objects.get("userMadeCube") is not None)
    again = bpy.data.objects.get("stdSurfCube")
    check("the imported object kept its identity",
          again is not None and again.as_pointer() == imported_id)
    check("and the modifier the user put on it",
          again is not None and "UserBevel" in
          [m.name for m in again.modifiers],
          [m.name for m in again.modifiers] if again else None)
    check("its width untouched",
          again is not None and abs(again.modifiers["UserBevel"].width
                                    - 0.123) < 1e-6)
    # Identity survives, but the contents are the new package's.
    check("its geometry came from the package",
          again is not None and again.data is not None
          and again.data.name.startswith("stdSurfCube"),
          again.data.name if again else None)
    check("merge did not double the scene",
          second["mesh_count"] == baseline_meshes,
          (second["mesh_count"], baseline_meshes))
    # A merge of the same package leaves nothing behind.
    check("nothing went stale re-importing the same package",
          second["stale_count"] == 0, second["stale_count"])
    check("and no second root collection was made",
          len([c for c in bpy.data.collections
               if c.name.startswith("mLender Import")]) == 1,
          [c.name for c in bpy.data.collections
           if c.name.startswith("mLender Import")])
    # Empties, curves and volumes are rebuilt rather than adopted, so a second
    # merge accumulated them: probeLocator beside probeLocator.001. The mesh
    # count alone could never have shown it, since meshes are adopted.
    for label, name in (("locator", "probeLocator"), ("curve", "probeCurve"),
                        ("volume", "smokeVolume")):
        copies = [
            obj for obj in bpy.data.objects
            if obj.name == name or obj.name.startswith(name + ".")
        ]
        check("merge did not duplicate the {0}".format(label),
              len(copies) == 1, [obj.name for obj in copies])
    check("nor duplicate group collections",
          len([c for c in bpy.data.collections if c.name.startswith("props")])
          == 1,
          [c.name for c in bpy.data.collections
           if c.name.startswith("props")])

    print("\nstale objects")
    # An object from an earlier import that this package has no record for.
    orphan = bpy.data.objects.new("goneFromMaya",
                                  bpy.data.meshes.new("goneMesh"))
    orphan["ml_generated"] = True
    orphan["ml_maya_path"] = "|goneFromMaya"
    bpy.context.scene.collection.objects.link(orphan)
    third = mi.import_scene_package(package, import_scale=1.0,
                                    import_mode="MERGE")
    check("an object no longer in the package is counted",
          third["stale_count"] == 1, third["stale_count"])
    # Counted, not deleted: an import over a socket must not destroy work.
    check("but not deleted", bpy.data.objects.get("goneFromMaya") is not None)
    check("the panel can see it", count_stale_objects() == 1,
          count_stale_objects())
    removed = remove_stale_objects()
    check("and removing it is a separate step", removed == 1, removed)
    check("which does delete it",
          bpy.data.objects.get("goneFromMaya") is None)

    print("\nadd")
    before = len(bpy.data.objects)
    fourth = mi.import_scene_package(package, import_scale=1.0,
                                     import_mode="ADD")
    check("add reports its mode", fourth["import_mode"] == "ADD",
          fourth["import_mode"])
    check("add brings the package in beside what was there",
          len(bpy.data.objects) > before, (before, len(bpy.data.objects)))
    check("the user's own object is still there",
          bpy.data.objects.get("userMadeCube") is not None)

    print()
    if failures:
        print("FAILURES ({0}):".format(len(failures)))
        for item in failures:
            print("  - {0}".format(item))
        return 1
    print("all import mode assertions passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
