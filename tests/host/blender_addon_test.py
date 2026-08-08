# -*- coding: utf-8 -*-
"""Add-on registration test against a real headless Blender.

Covers what the import test does not: that the add-on registers, that its
operators can actually be called, and that registering repeatedly leaves a
working add-on. That last case is what "Reload Scripts" does, and it is where
a broken register silently leaves a panel whose buttons do nothing.

    "C:\\Program Files\\Blender Foundation\\Blender 5.2\\blender.exe" ^
        --background --factory-startup --python tests/host/blender_addon_test.py

Needs no installation; the package is imported straight from the repository.
"""
import os
import sys

import bpy

# Three levels up: tests/<group>/<file>.py
TOOL_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)
if TOOL_ROOT not in sys.path:
    sys.path.insert(0, TOOL_ROOT)

RELOAD_ROUNDS = 3

failures = []


def check(label, condition, detail=""):
    if condition:
        print("  ok    {0}".format(label))
    else:
        failures.append("{0} {1}".format(label, detail))
        print("  FAIL  {0}  {1}".format(label, detail))


def operators_callable():
    """Operators are reached through bpy.ops, not through bpy.types.

    Blender does not expose operator classes on bpy.types by class name, so
    checking there reports a false negative and hides a real failure.
    """
    namespace = getattr(bpy.ops, "ml_lookdev", None)
    if namespace is None:
        return False
    return all(
        getattr(namespace, name, None) is not None
        for name in ("start_listener", "stop_listener")
    )


def unregistered_classes(classes):
    return [cls.__name__ for cls in classes if not cls.is_registered]


def main():
    import mlender_importer as zi

    print("Blender {0}, importer build {1}".format(
        bpy.app.version_string, zi.BUILD_VERSION))
    classes = zi.ui.CLASSES

    print("\nregistration")
    zi.register()
    check("every class registered", not unregistered_classes(classes),
          unregistered_classes(classes))
    check("operators callable", operators_callable())
    check("panel sits in the mLender sidebar tab",
          bpy.types.ML_PT_lookdev.bl_category == "mLender",
          bpy.types.ML_PT_lookdev.bl_category)

    print("\nscene properties")
    scene = bpy.context.scene
    for prop, expected in (
        ("ml_import_scale", 1.0),
        ("ml_light_power_scale", 1.0),
        ("ml_livelink_host", "127.0.0.1"),
        ("ml_livelink_port", 50505),
    ):
        check("{0} defaults to {1!r}".format(prop, expected),
              getattr(scene, prop, None) == expected,
              getattr(scene, prop, "MISSING"))

    print("\nlistener round trip")
    check("start returns FINISHED",
          bpy.ops.mlender.start_listener() == {"FINISHED"})
    check("status reports the bound port",
          "50505" in zi.get_status(), zi.get_status())
    check("stop returns FINISHED",
          bpy.ops.mlender.stop_listener() == {"FINISHED"})
    check("status reports stopped", "stopped" in zi.get_status().lower(),
          zi.get_status())

    print("\nrepeated registration, the Reload Scripts case")
    for round_number in range(1, RELOAD_ROUNDS + 1):
        zi.register()
        check("round {0}: classes survive".format(round_number),
              not unregistered_classes(classes),
              unregistered_classes(classes))
        check("round {0}: operators survive".format(round_number),
              operators_callable())
        check("round {0}: scene properties survive".format(round_number),
              hasattr(bpy.context.scene, "ml_light_power_scale"))
    check("operators still run after re-registering",
          bpy.ops.mlender.start_listener() == {"FINISHED"})
    bpy.ops.mlender.stop_listener()

    print("\nunregistration")
    zi.unregister()
    check("classes cleared",
          all(not cls.is_registered for cls in classes),
          [cls.__name__ for cls in classes if cls.is_registered])
    check("scene properties removed",
          not hasattr(bpy.types.Scene, "ml_light_power_scale"))
    check("listener released", "stopped" in zi.get_status().lower(),
          zi.get_status())

    print()
    if failures:
        print("FAILURES ({0}):".format(len(failures)))
        for item in failures:
            print("  - {0}".format(item))
        return 1
    print("all add-on assertions passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
