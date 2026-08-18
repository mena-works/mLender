# -*- coding: utf-8 -*-
"""Build the two installable artefacts, from a plain Python 3 interpreter.

    python packaging/build_release.py

The tool ships as two folders a user copies by hand, which is how it has always
been installed. That works and is documented, but it puts the burden of the
Maya side on editing ``userSetup.py`` -- a shared file, in the user's own
preferences, that a mistake can break for every other tool at once.

So this writes what the two hosts already know how to install:

    dist/mLender-<version>-blender-addon.zip   Preferences > Add-ons > Install
    dist/mLender-<version>-maya-module.zip     unzip into a Maya modules folder

The Blender zip keeps ``mlender_importer`` as its top folder on purpose. That
folder name **is** the add-on's module name: change it and Blender treats the
result as a different add-on and copies it alongside the old one rather than
updating it.

The Maya zip is a module, which is Maya's own answer to the same problem: a
``.mod`` file naming a folder, dropped anywhere on MAYA_MODULE_PATH. Nothing
shared is edited, and removing the tool is deleting two things.

Nothing here imports either package: the exporter needs ``maya.cmds`` and the
importer needs ``bpy``, so the versions are read out of the source text. That
also means this can be run in CI without a DCC.
"""
import os
import re
import shutil
import sys
import zipfile


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIST = os.path.join(ROOT, "dist")
EXPORTER = "mlender_exporter"
IMPORTER = "mlender_importer"
UNREAL = "mlender_unreal"
MODULE_NAME = "mLender"
# The Unreal plugin folder is renamed to match its .uplugin on the way out.
# Unreal keys the plugin on the .uplugin's basename, and a folder that
# disagrees with it works but reads as a mistake in the plugin browser.
UNREAL_PLUGIN_NAME = "mLender"
# Everything Python leaves behind that must not travel to a user.
IGNORED = shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo", ".DS_Store")


def read_versions():
    """The three version numbers, or raise if they disagree.

    The same contract ``tests/check_contracts.py`` enforces, checked again
    here because a release is exactly the moment a mismatch stops being a
    developer's problem and becomes a user's.
    """
    # constants.py, not __init__.py: the exporter's build number moved there
    # so package.py could reach it without importing the package root.
    exporter = _match(
        os.path.join(ROOT, EXPORTER, "constants.py"),
        r'BUILD_VERSION\s*=\s*"([^"]+)"',
    )
    importer = _match(
        os.path.join(ROOT, IMPORTER, "constants.py"),
        r'BUILD_VERSION\s*=\s*"([^"]+)"',
    )
    manifest = _match(
        os.path.join(ROOT, IMPORTER, "__init__.py"),
        r'"version"\s*:\s*\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*\)',
        groups=3,
    )
    manifest = ".".join(manifest)
    receiver = _match(
        os.path.join(ROOT, UNREAL, "Content", "Python", UNREAL,
                     "constants.py"),
        r'BUILD_VERSION\s*=\s*"([^"]+)"',
    )
    # The .uplugin's VersionName is what an artist reads in Unreal's plugin
    # browser, so it is the Unreal counterpart of bl_info and drifts the same
    # way if nothing checks it.
    uplugin = _match(
        os.path.join(ROOT, UNREAL, "mLender.uplugin"),
        r'"VersionName"\s*:\s*"([^"]+)"',
    )
    if not exporter == importer == manifest == receiver == uplugin:
        raise SystemExit(
            "Version mismatch, refusing to build:\n"
            "  {0}/__init__.py         {1}\n"
            "  {2}/constants.py        {3}\n"
            "  {2} bl_info              {4}\n"
            "  {5} constants.py         {6}\n"
            "  {5} mLender.uplugin      {7}".format(
                EXPORTER, exporter, IMPORTER, importer, manifest,
                UNREAL, receiver, uplugin,
            )
        )
    return exporter


def _match(path, pattern, groups=1):
    with open(path, "r", encoding="utf-8") as handle:
        found = re.search(pattern, handle.read())
    if not found:
        raise SystemExit("Could not read a version from {0}".format(path))
    return found.group(1) if groups == 1 else found.groups()


def module_file(version):
    """A Maya module definition.

    The path is relative to the .mod file itself, so the folder can be dropped
    anywhere on MAYA_MODULE_PATH without editing anything. ``PYTHONPATH+:=``
    appends rather than replaces -- a module that overwrote it would take the
    rest of the user's pipeline down with it.
    """
    return (
        "+ {0} {1} .\\{0}\n"
        "PYTHONPATH+:=scripts\n"
    ).format(MODULE_NAME, version)


def install_notes(version):
    """The install instructions, generated so the version cannot drift.

    Written rather than kept as a static file for the same reason the build
    refuses to run on mismatched versions: a number in a document nobody
    regenerates is a number that will be wrong.
    """
    return """# Installing mLender {version}

`mLender_Setup.exe`, if it came with these archives, does all of the below for
you: it finds the Maya and Blender versions you have and the Unreal projects
under `Documents\\Unreal Projects`, installs what you tick, and enables the
plugin in the project file. The steps below are the same install by hand.

Install the Maya exporter, then whichever receiver you send to. The exporter is
required; Blender and Unreal are alternative destinations and you can install
either, or both. Every part checks the others' version.

    mLender-{version}-maya-module.zip      required, the sender
    mLender-{version}-blender-addon.zip    receiver
    mLender-{version}-unreal-plugin.zip    receiver

## Blender  (4.1 and later, tested on 4.1, 4.3, 4.5 and 5.2)

1. `Edit > Preferences > Add-ons > Install...` (in 4.2+ the button is under
   the dropdown at the top right of the Add-ons list).
2. Pick `mLender-{version}-blender-addon.zip`. Do not unzip it first.
3. Tick **mLender** in the list to enable it.

Check it worked: press `N` in the 3D viewport and open the **mLender** tab.
The panel shows `Build {version}`.

## Maya  (2022 and later, tested on 2023 with MtoA 5.4.8)

1. Unzip `mLender-{version}-maya-module.zip`.
2. Move both the `mLender.mod` file **and** the `mLender` folder next to it
   into a Maya modules folder. Create the folder if it is not there:

       Windows   %USERPROFILE%\\Documents\\maya\\modules\\
       macOS     ~/Library/Preferences/Autodesk/maya/modules/
       Linux     ~/maya/modules/

   Any folder on `MAYA_MODULE_PATH` works; that one needs no setup.
3. Restart Maya.

Check it worked, in the Script Editor's Python tab:

    import mlender_exporter as ml
    ml.show_ui()

Nothing shared is edited by this. Removing the tool is deleting the `.mod`
file and the folder.

## Unreal  (5.8, tested on 5.8.1)

The plugin installs into a project or into the engine. A project is the usual
choice: it travels with the project and needs no administrator rights.

1. Unzip `mLender-{version}-unreal-plugin.zip`.
2. Move the `mLender` folder into **one** of:

       <YourProject>/Plugins/mLender/                    per project
       <Engine>/Engine/Plugins/mLender/                  every project

   The engine folder is under `Program Files` on Windows, so it needs
   administrator rights, and an engine update removes it. Prefer the project.
3. Restart the editor. Enable **mLender** in `Edit > Plugins` if it is not on
   already, and restart once more.

Check it worked: `Tools > mLender` shows `mLender {version}` with
**Start LiveLink** under it.

The plugin needs Unreal's **Python Editor Script Plugin** and
**Interchange Editor**, both shipped with the engine; the .uplugin asks for
them, so enabling mLender enables them too.

Unreal import replaces the level's actors and this build does not save first.
Save your level before sending.

## Both sides have to match

The package the exporter writes carries a schema version, and the importer
refuses one it does not know -- before it touches your Blender scene, so a
mismatch costs you nothing but a message. If you update one side, update the
other from the same release.

## Upgrading

Blender: install the new zip over the old one; it replaces it, because the
add-on's module name is the folder name inside the archive and that does not
change between releases.

Maya: replace the `mLender` folder and the `.mod` file, then restart Maya.

## Usage

See README.md in the repository: https://github.com/mena-works/mLender
""".format(version=version)


def build_blender_addon(version):
    target = os.path.join(DIST, "mLender-{0}-blender-addon.zip".format(version))
    source = os.path.join(ROOT, IMPORTER)
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
        for path, arcname in _walk(source, IMPORTER):
            archive.write(path, arcname)
    return target


def build_unreal_plugin(version):
    """The Unreal plugin, as the folder both install routes want.

        mLender/mLender.uplugin
        mLender/Content/Python/init_unreal.py
        mLender/Content/Python/mlender_unreal/

    One archive serves both targets: dropped in a project's ``Plugins/`` or in
    ``Engine/Plugins/``, the layout is identical. The top folder is named after
    the .uplugin rather than after the repository folder, because that is the
    name Unreal shows.
    """
    staging = os.path.join(DIST, "mLender-{0}-unreal".format(version))
    if os.path.isdir(staging):
        shutil.rmtree(staging)
    shutil.copytree(
        os.path.join(ROOT, UNREAL),
        os.path.join(staging, UNREAL_PLUGIN_NAME),
        ignore=IGNORED,
    )
    target = os.path.join(
        DIST, "mLender-{0}-unreal-plugin.zip".format(version)
    )
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
        for path, arcname in _walk(staging, ""):
            archive.write(path, arcname)
    return target, staging


def build_maya_module(version):
    """The module layout, staged on disk and then zipped.

        mLender.mod
        mLender/scripts/mlender_exporter/
    """
    staging = os.path.join(DIST, "mLender-{0}-maya".format(version))
    if os.path.isdir(staging):
        shutil.rmtree(staging)
    scripts = os.path.join(staging, MODULE_NAME, "scripts")
    os.makedirs(scripts)
    shutil.copytree(
        os.path.join(ROOT, EXPORTER),
        os.path.join(scripts, EXPORTER),
        ignore=IGNORED,
    )
    with open(os.path.join(staging, MODULE_NAME + ".mod"), "w",
              encoding="utf-8", newline="\n") as handle:
        handle.write(module_file(version))
    # Beside the .mod, where somebody who has just unzipped it is looking.
    # Maya only reads .mod files out of a modules folder, so this is inert
    # there. It is deliberately *not* put inside the Blender archive: that
    # archive's top folder is installed as the add-on itself, and anything
    # added to it lands in the user's add-ons directory.
    with open(os.path.join(staging, "INSTALL.md"), "w",
              encoding="utf-8", newline="\n") as handle:
        handle.write(install_notes(version))

    target = os.path.join(DIST, "mLender-{0}-maya-module.zip".format(version))
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
        for path, arcname in _walk(staging, ""):
            archive.write(path, arcname)
    return target, staging


def _walk(source, prefix):
    """Every file under a folder, with the arcname it should keep.

    Sorted, so two builds of the same source produce the same archive order.
    """
    for folder, folders, names in os.walk(source):
        folders[:] = sorted(f for f in folders if f != "__pycache__")
        for name in sorted(names):
            if name.endswith((".pyc", ".pyo")) or name == ".DS_Store":
                continue
            path = os.path.join(folder, name)
            relative = os.path.relpath(path, source)
            arcname = os.path.join(prefix, relative) if prefix else relative
            yield path, arcname.replace("\\", "/")


def main():
    version = read_versions()
    if os.path.isdir(DIST):
        shutil.rmtree(DIST)
    os.makedirs(DIST)

    addon = build_blender_addon(version)
    module, staging = build_maya_module(version)
    plugin, plugin_staging = build_unreal_plugin(version)
    # And loose beside the archives, for whoever is looking at the download
    # before they have unzipped anything.
    notes = os.path.join(DIST, "INSTALL.md")
    with open(notes, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(install_notes(version))

    print("mLender {0}".format(version))
    for path in (addon, module, plugin, notes):
        print("  {0}  ({1:,} bytes)".format(
            os.path.relpath(path, ROOT), os.path.getsize(path)
        ))
    print("  {0}  (unzipped module, for MAYA_MODULE_PATH)".format(
        os.path.relpath(staging, ROOT)
    ))
    print("  {0}  (unzipped plugin, for Plugins/ or Engine/Plugins/)".format(
        os.path.relpath(plugin_staging, ROOT)
    ))
    return 0


if __name__ == "__main__":
    sys.exit(main())
