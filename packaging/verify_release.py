# -*- coding: utf-8 -*-
"""Install the built artefacts into the real hosts and check they work.

    python packaging/build_release.py
    python packaging/verify_release.py

A zip that unpacks correctly is not the same claim as a zip a host will
install, and each has its own failure mode: a Maya module resolves its paths
relative to the .mod file, a Blender add-on is identified by the folder name
inside the archive, and Unreal identifies a plugin by the name in its .uplugin
while only putting <Plugin>/Content/Python on sys.path. All three were wrong at
least once while this was being written, and only installing them showed it.

Nothing here touches the user's own configuration. Maya is given a
MAYA_MODULE_PATH pointing at the staged module, Blender is given a throwaway
user-resources directory, and Unreal is given a project made here and deleted
afterwards, so an install here cannot leave anything behind in any of them.
"""
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIST = os.path.join(ROOT, "dist")
MAYAPY = r"C:\Program Files\Autodesk\Maya2023\bin\mayapy.exe"


def _unreal_editor():
    """The 5.8 editor, wherever the launcher put it.

    The launcher records every install in LauncherInstalled.dat, and an
    engine on another drive is ordinary -- the machine this was extended on
    keeps it on D:. The Program Files path stays as the fallback for a
    machine without the launcher's record.
    """
    tail = os.path.join("Engine", "Binaries", "Win64", "UnrealEditor-Cmd.exe")
    record = os.path.join(
        os.environ.get("ProgramData", r"C:\ProgramData"),
        "Epic", "UnrealEngineLauncher", "LauncherInstalled.dat")
    try:
        import json
        with open(record, encoding="utf-8") as handle:
            installs = json.load(handle).get("InstallationList") or []
        for install in installs:
            if str(install.get("AppName")) == "UE_5.8":
                candidate = os.path.join(
                    str(install.get("InstallLocation")), tail)
                if os.path.isfile(candidate):
                    return candidate
    except Exception:
        pass
    return os.path.join(r"C:\Program Files\Epic Games\UE_5.8", tail)


UNREAL = _unreal_editor()
# A project of our own, made here and thrown away. Installing into one of the
# developer's projects would prove less and leave more behind.
#
# mLender is listed as enabled because that is the documented install: the
# plugin ships EnabledByDefault false, so dropping it into Plugins/ and
# restarting does nothing until the user turns it on. A first version of this
# check left it out and read the result as a broken package -- it was a broken
# check, skipping a step INSTALL.md spells out. PythonScriptPlugin is listed
# too, since the probe is Python and needs it before mLender is reached.
UPROJECT = """{
  "FileVersion": 3,
  "EngineAssociation": "5.8",
  "Category": "",
  "Description": "mLender release check",
  "Plugins": [
    { "Name": "PythonScriptPlugin", "Enabled": true },
    { "Name": "mLender", "Enabled": true }
  ]
}
"""

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


UNREAL_PROBE = r'''
import os, sys
import unreal

def say(key, value):
    unreal.log("MLV {0}={1}".format(key, value))

# Whether the plugin's own startup script ran. Unreal executes
# init_unreal.py for an enabled plugin before anything here, so the package
# being in sys.modules already is the proof -- importing it below would not
# tell the two apart.
say("PRELOADED", "mlender_unreal" in sys.modules)
say("DEPENDENCIES", hasattr(unreal, "InterchangeManager"))
# The compiled module: the archive carries it prebuilt, and a plugin whose
# Binaries did not travel still imports its Python and only falls back later,
# in front of a user, with a warning. So the class is asked for by name here.
say("MODULE", hasattr(unreal, "MLMotionPlayer"))
# INSTALL.md tells the user to look for Tools > mLender, and that cannot be
# checked here: a commandlet has no editor UI to hang a menu on, which the
# plugin's own startup script says out loud rather than failing. What is
# checkable is that register() answers at all, which is done below once the
# package is imported.
try:
    import mlender_unreal as ml
    say("IMPORTED", ml.BUILD_VERSION)
    say("WHERE", os.path.dirname(ml.__file__))
    say("API", ",".join(sorted(
        a for a in ("import_scene_package", "start_listener", "stop_listener",
                    "reload_package") if hasattr(ml, a))))
    say("REGISTER", repr(ml.register()))
except Exception as exc:
    say("IMPORT_FAILED", repr(exc))
unreal.SystemLibrary.quit_editor()
'''


def unreal_field(output, key):
    """Read a MLV key from the log, which is where Unreal puts a print."""
    marker = "MLV {0}=".format(key)
    for line in output.splitlines():
        if marker in line:
            return line.split(marker, 1)[1].strip()
    return ""


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


def verify_unreal(plugin_zip):
    """Install the plugin into a throwaway project and import it there.

    The claim being checked is not "the zip unpacks". It is that Unreal finds
    the plugin by the name in its .uplugin, runs its startup script, and puts
    *that* copy of the package on sys.path -- the three things the layout has
    to get right and the three that cannot be seen from the archive.
    """
    print("\nUnreal plugin")
    if not os.path.isfile(UNREAL):
        print("  skipped: no editor at {0}".format(UNREAL))
        return None
    if not os.path.isfile(plugin_zip):
        check("the plugin archive was built", False, plugin_zip)
        return None

    names = zipfile.ZipFile(plugin_zip).namelist()
    # Unreal identifies a plugin by its .uplugin, not by the folder in the
    # repository -- so the archive has to carry the distribution name.
    check("the archive holds one plugin folder",
          len(set(name.split("/")[0] for name in names)) == 1,
          sorted(set(name.split("/")[0] for name in names)))
    check("with the .uplugin at its root",
          any(name.count("/") == 1 and name.endswith(".uplugin")
              for name in names),
          [n for n in names if n.endswith(".uplugin")])
    # Unreal only puts <Plugin>/Content/Python on sys.path, and only runs
    # init_unreal.py from there.
    check("and its Python where Unreal looks for it",
          any("/Content/Python/init_unreal.py" in name for name in names),
          [n for n in names if "init_unreal" in n])

    project = tempfile.mkdtemp(prefix="mlender_ue_")
    try:
        plugins = os.path.join(project, "Plugins")
        os.makedirs(plugins)
        zipfile.ZipFile(plugin_zip).extractall(plugins)
        uproject = os.path.join(project, "MLVerify.uproject")
        with open(uproject, "w", encoding="utf-8") as handle:
            handle.write(UPROJECT)
        probe = os.path.join(project, "probe.py")
        with open(probe, "w", encoding="utf-8") as handle:
            handle.write(UNREAL_PROBE)

        env = dict(os.environ)
        # Nothing of the developer's own environment may satisfy the import,
        # or this proves nothing -- the same trap the Maya check fell into.
        env.pop("PYTHONPATH", None)
        env.pop("UE_PYTHONPATH", None)
        neutral = tempfile.mkdtemp(prefix="mlender_ue_cwd_")
        try:
            output = run(
                [UNREAL, uproject, "-run=pythonscript",
                 "-script=" + probe, "-unattended", "-nosplash", "-nullrhi"],
                env=env, cwd=neutral,
            )
        finally:
            shutil.rmtree(neutral, ignore_errors=True)
        # Unreal writes Python output to the project log, not to stdout.
        log = os.path.join(project, "Saved", "Logs", "MLVerify.log")
        if os.path.isfile(log):
            with open(log, encoding="utf-8", errors="replace") as handle:
                output += handle.read()

        version = unreal_field(output, "IMPORTED")
        check("Unreal loaded the plugin and imported the package",
              bool(version),
              unreal_field(output, "IMPORT_FAILED") or output[-400:])
        where = unreal_field(output, "WHERE").replace("\\", "/")
        check("from inside the installed plugin, not from the repo",
              bool(where) and project.replace("\\", "/") in where, where)
        # The notes promise that enabling mLender brings its engine
        # dependencies with it, because the .uplugin asks for them. If that
        # stopped being true the import above would still pass and an
        # Interchange call would fail much later, in front of a user.
        check("its declared dependencies came with it",
              unreal_field(output, "DEPENDENCIES") == "True",
              unreal_field(output, "DEPENDENCIES"))
        # The archive is only a release if the module it was built with
        # loads from the unpacked folder on an engine that never compiled it.
        check("and its compiled module loaded from the archive",
              unreal_field(output, "MODULE") == "True",
              unreal_field(output, "MODULE"))
        # False here is the right answer, not a failure: there is no editor
        # UI in a commandlet. What matters is that it answered at all.
        check("its menu registration ran and said which it got",
              unreal_field(output, "REGISTER") in ("True", "False"),
              unreal_field(output, "REGISTER"))
        check("and the startup script said so in the log",
              "mLender {0} loaded".format(version or "") in output,
              [line for line in output.splitlines()
               if "mLender" in line and "loaded" in line][:1])
        check("the plugin's own startup script ran",
              unreal_field(output, "PRELOADED") == "True",
              unreal_field(output, "PRELOADED"))
        check("with its public API",
              unreal_field(output, "API") == ("import_scene_package,"
                                              "reload_package,start_listener,"
                                              "stop_listener"),
              unreal_field(output, "API"))
        return version
    finally:
        shutil.rmtree(project, ignore_errors=True)


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

    print("\ninstall notes")
    notes = os.path.join(DIST, "INSTALL.md")
    check("they are beside the archives", os.path.isfile(notes), notes)
    staged_notes = os.path.join(staging, "INSTALL.md") if staging else ""
    check("and inside the Maya archive, where the unzipper looks",
          bool(staged_notes) and os.path.isfile(staged_notes), staged_notes)
    if os.path.isfile(notes):
        with open(notes, encoding="utf-8") as handle:
            body = handle.read()
        # Generated rather than kept as a file for exactly this reason: an
        # instruction naming last release's zip sends people to a 404.
        check("naming the archives that were actually built",
              all(name in body for name in zips), zips)
    addon_names = zipfile.ZipFile(os.path.join(DIST, addon)).namelist()
    check("the Blender archive holds nothing but the add-on folder",
          all(name.startswith("mlender_importer/") for name in addon_names),
          [n for n in addon_names if not n.startswith("mlender_importer/")])

    plugin = next((z for z in zips if "unreal-plugin" in z), "")
    maya_version = verify_maya(staging) if staging else None
    unreal_version = verify_unreal(os.path.join(DIST, plugin)) if plugin \
        else None
    blender_versions = []
    for label, executable in sorted(BLENDERS.items()):
        found = verify_blender(os.path.join(DIST, addon), label, executable)
        if found:
            blender_versions.append((label, found))

    print("\nevery side")
    check("every host reports the same build version",
          bool(maya_version)
          and all(found == maya_version for _, found in blender_versions)
          and (unreal_version is None or unreal_version == maya_version),
          (maya_version, blender_versions, unreal_version))

    print()
    if failures:
        print("FAILURES ({0}):".format(len(failures)))
        for item in failures:
            print("  - {0}".format(item))
        return 1
    print("every artefact installs and loads")
    return 0


if __name__ == "__main__":
    sys.exit(main())
