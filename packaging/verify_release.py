# -*- coding: utf-8 -*-
"""Install the built artefacts into the real hosts and check they work.

    python packaging/build_release.py
    python packaging/verify_release.py

A zip that unpacks correctly is not the same claim as a zip a host will
install, and the two have different failure modes: a Maya module resolves its
paths relative to the .mod file, and a Blender add-on is identified by the
folder name inside the archive. Both were wrong at least once while this was
being written, and only installing them showed it.

Nothing here touches the user's own configuration. Maya is given a
MAYA_MODULE_PATH pointing at the staged module, and Blender is given a
throwaway user-resources directory, so an install here cannot leave anything
behind in either application.
"""
import os
import shutil
import subprocess
import sys
import tempfile


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIST = os.path.join(ROOT, "dist")
MAYAPY = r"C:\Program Files\Autodesk\Maya2023\bin\mayapy.exe"
BLENDERS = {
    "4.1": r"C:\Program Files\Blender Foundation\Blender 4.1\blender.exe",
    "4.3": r"C:\Program Files\Blender Foundation\Blender 4.3\blender.exe",
    "4.5": r"C:\Program Files\Blender Foundation\Blender 4.5\blender.exe",
    "5.2": r"C:\Program Files\Blender Foundation\Blender 5.2\blender.exe",
}

failures = []


def check(label, condition, detail=""):
    if condition:
        print("  ok    {0}".format(label))
    else:
        failures.append("{0} {1}".format(label, detail))
        print("  FAIL  {0}  {1}".format(label, detail))


MAYA_PROBE = r'''
import os, sys
import maya.standalone
maya.standalone.initialize(name="python")
import maya.cmds as cmds
print("MODULE_PATH=" + (os.environ.get("MAYA_MODULE_PATH") or ""))
try:
    import mlender_exporter as ml
    print("IMPORTED=" + ml.BUILD_VERSION)
    print("WHERE=" + os.path.dirname(ml.__file__))
    print("API=" + ",".join(sorted(a for a in ("show_ui", "export_scene",
          "reload_package") if hasattr(ml, a))))
except Exception as exc:
    print("IMPORT_FAILED=" + repr(exc))
'''

BLENDER_PROBE = r'''
import os, sys
import addon_utils, bpy
zip_path = sys.argv[-1]
print("USER_SCRIPTS=" + bpy.utils.user_resource("SCRIPTS"))
try:
    bpy.ops.preferences.addon_install(filepath=zip_path, overwrite=True)
except Exception as exc:
    print("INSTALL_FAILED=" + repr(exc))
try:
    bpy.ops.preferences.addon_enable(module="mlender_importer")
except Exception as exc:
    print("ENABLE_FAILED=" + repr(exc))
found = [m for m in addon_utils.modules() if m.__name__ == "mlender_importer"]
print("FOUND=" + str(bool(found)))
if found:
    info = found[0].bl_info
    print("BL_INFO_VERSION=" + ".".join(str(v) for v in info.get("version", ())))
    print("ENABLED=" + str(addon_utils.check("mlender_importer")[1]))
    where = os.path.dirname(found[0].__file__)
    print("WHERE=" + where)
import mlender_importer
print("API=" + ",".join(sorted(a for a in ("import_scene_package", "register",
      "unregister") if hasattr(mlender_importer, a))))
print("BUILD_VERSION=" + mlender_importer.constants.BUILD_VERSION)
'''


def run(command, env=None, extra_args=(), cwd=None):
    result = subprocess.run(
        list(command) + list(extra_args),
        capture_output=True, text=True, env=env, cwd=cwd, timeout=900,
    )
    return (result.stdout or "") + (result.stderr or "")


def field(output, key):
    for line in output.splitlines():
        if line.startswith(key + "="):
            return line.split("=", 1)[1].strip()
    return ""


def verify_maya(staging):
    print("\nMaya module")
    if not os.path.isfile(MAYAPY):
        print("  skipped: no mayapy at {0}".format(MAYAPY))
        return
    mod = os.path.join(staging, "mLender.mod")
    check("the .mod file is in the archive root", os.path.isfile(mod), mod)

    probe = os.path.join(staging, "_probe_module.py")
    with open(probe, "w", encoding="utf-8") as handle:
        handle.write(MAYA_PROBE)

    env = dict(os.environ)
    # Only the staged module. Nothing of the developer's own environment is
    # allowed to satisfy the import, or this proves nothing.
    env["MAYA_MODULE_PATH"] = staging
    env.pop("PYTHONPATH", None)
    # And from somewhere the repo cannot be reached: Maya puts the working
    # directory on sys.path, so running this from the checkout imported the
    # repo copy and the module was never exercised. It looked like a pass.
    neutral = tempfile.mkdtemp(prefix="mlender_maya_")
    try:
        output = run([MAYAPY, probe], env=env, cwd=neutral)
    finally:
        shutil.rmtree(neutral, ignore_errors=True)

    version = field(output, "IMPORTED")
    check("Maya loaded the module and imported the exporter",
          bool(version), field(output, "IMPORT_FAILED") or output[-400:])
    check("from inside the module, not from the repo",
          "dist" in field(output, "WHERE").replace("\\", "/"),
          field(output, "WHERE"))
    check("with its public API",
          field(output, "API") == "export_scene,reload_package,show_ui",
          field(output, "API"))
    return version


def verify_blender(addon_zip, label, executable):
    print("\nBlender {0} add-on".format(label))
    if not os.path.isfile(executable):
        print("  skipped: no Blender at {0}".format(executable))
        return
    # A throwaway home, so installing here cannot touch the real preferences.
    home = tempfile.mkdtemp(prefix="mlender_verify_")
    probe = os.path.join(home, "_probe_addon.py")
    with open(probe, "w", encoding="utf-8") as handle:
        handle.write(BLENDER_PROBE)

    env = dict(os.environ)
    env["BLENDER_USER_RESOURCES"] = home
    env["BLENDER_USER_SCRIPTS"] = os.path.join(home, "scripts")
    try:
        output = run(
            [executable, "--background", "--factory-startup", "--python",
             probe, "--"],
            env=env, extra_args=[addon_zip],
        )
        check("Blender installed and enabled the add-on",
              field(output, "ENABLED") == "True",
              field(output, "INSTALL_FAILED")
              or field(output, "ENABLE_FAILED") or output[-400:])
        check("under the module name the folder gives it",
              field(output, "FOUND") == "True", output[-200:])
        check("it landed in the throwaway home, not the real one",
              home.replace("\\", "/").lower()
              in field(output, "WHERE").replace("\\", "/").lower(),
              field(output, "WHERE"))
        check("bl_info and BUILD_VERSION agree",
              field(output, "BL_INFO_VERSION")
              == field(output, "BUILD_VERSION"),
              (field(output, "BL_INFO_VERSION"),
               field(output, "BUILD_VERSION")))
        check("with its public API",
              field(output, "API")
              == "import_scene_package,register,unregister",
              field(output, "API"))
        return field(output, "BUILD_VERSION")
    finally:
        shutil.rmtree(home, ignore_errors=True)


def main():
    if not os.path.isdir(DIST):
        raise SystemExit("No dist/. Run packaging/build_release.py first.")
    zips = sorted(
        name for name in os.listdir(DIST) if name.endswith(".zip")
    )
    addon = next((z for z in zips if "blender-addon" in z), "")
    staging = next(
        (os.path.join(DIST, n) for n in os.listdir(DIST)
         if n.endswith("-maya") and os.path.isdir(os.path.join(DIST, n))), "")
    print("artefacts: {0}".format(", ".join(zips) or "none"))

    maya_version = verify_maya(staging) if staging else None
    blender_versions = []
    for label, executable in sorted(BLENDERS.items()):
        found = verify_blender(os.path.join(DIST, addon), label, executable)
        if found:
            blender_versions.append((label, found))

    print("\nboth sides")
    check("every host reports the same build version",
          bool(maya_version)
          and all(found == maya_version for _, found in blender_versions),
          (maya_version, blender_versions))

    print()
    if failures:
        print("FAILURES ({0}):".format(len(failures)))
        for item in failures:
            print("  - {0}".format(item))
        return 1
    print("both artefacts install and load")
    return 0


if __name__ == "__main__":
    sys.exit(main())
