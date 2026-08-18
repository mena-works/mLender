# -*- coding: utf-8 -*-
"""
mLender Complete Installer

This script automatically builds the release packages and installs them
to your local Maya and Blender configurations on Windows.
"""
import json
import os
import sys
import tempfile
import shutil
import zipfile
import subprocess
import glob

# Ensure we are in the project root
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIST = os.path.join(ROOT, "dist")

def run_build():
    print("Building release packages...")
    build_script = os.path.join(ROOT, "packaging", "build_release.py")
    result = subprocess.run([sys.executable, build_script], capture_output=True, text=True)
    if result.returncode != 0:
        print("Failed to build release packages:")
        print(result.stderr)
        sys.exit(1)
    print("Build successful.\n")

def get_version():
    sys.path.insert(0, os.path.join(ROOT, "packaging"))
    import build_release
    version = build_release.read_versions()
    sys.path.pop(0)
    return version

def install_maya(version):
    maya_zip = os.path.join(DIST, "mLender-{0}-maya-module.zip".format(version))
    if not os.path.exists(maya_zip):
        print("Error: Maya module zip not found at {0}".format(maya_zip))
        return False

    documents = os.path.join(os.path.expanduser("~"), "Documents")
    maya_modules_dir = os.path.join(documents, "maya", "modules")
    
    if not os.path.exists(maya_modules_dir):
        os.makedirs(maya_modules_dir)
        
    print("Installing Maya module to: {0}".format(maya_modules_dir))
    with zipfile.ZipFile(maya_zip, 'r') as zip_ref:
        zip_ref.extractall(maya_modules_dir)
        
    print("Maya installation complete.\n")
    return True

def install_blender(version):
    blender_zip = os.path.join(DIST, "mLender-{0}-blender-addon.zip".format(version))
    if not os.path.exists(blender_zip):
        print("Error: Blender addon zip not found at {0}".format(blender_zip))
        return False

    appdata = os.environ.get("APPDATA")
    if not appdata:
        appdata = os.path.join(os.path.expanduser("~"), "AppData", "Roaming")
        
    blender_foundation = os.path.join(appdata, "Blender Foundation", "Blender")
    
    if not os.path.exists(blender_foundation):
        print("Blender Foundation folder not found in APPDATA. Ensure Blender is installed and has been run at least once.")
        return False
        
    # Find all Blender version folders (e.g., "4.1", "4.3")
    installed_versions = []
    for item in os.listdir(blender_foundation):
        item_path = os.path.join(blender_foundation, item)
        if os.path.isdir(item_path) and item.replace(".", "").isdigit():
            installed_versions.append(item)
            
    if not installed_versions:
        print("No Blender versions found in {0}".format(blender_foundation))
        return False
        
    installed = False
    for b_version in installed_versions:
        addons_dir = os.path.join(blender_foundation, b_version, "scripts", "addons")
        if not os.path.exists(addons_dir):
            os.makedirs(addons_dir)
            
        print("Installing Blender addon to: {0}".format(addons_dir))
        with zipfile.ZipFile(blender_zip, 'r') as zip_ref:
            zip_ref.extractall(addons_dir)
        installed = True
        
    if installed:
        print("Blender installation complete.\n")
    return installed

def verify_installer(exe):
    """Run the built exe and read what it found.

    A windowed build has no stdout, so it is asked for a report file instead.
    This is the check that was missing: the first build embedded all three
    archives correctly and could not start, and looking inside it said
    nothing about that.
    """
    if not os.path.isfile(exe):
        print("No installer at {0}".format(exe))
        return False
    report = os.path.join(tempfile.gettempdir(), "mlender_setup_selftest.json")
    if os.path.isfile(report):
        os.remove(report)
    result = subprocess.run([exe, "--selftest", report], timeout=300)
    if result.returncode != 0:
        print("The installer exited {0}".format(result.returncode))
        return False
    if not os.path.isfile(report):
        print("The installer wrote no report, so it did not get that far.")
        return False
    with open(report, encoding="utf-8") as handle:
        found = json.load(handle)
    print("  installer runs: python {0}, tk {1}, frozen {2}".format(
        found.get("python"), found.get("tk"), found.get("frozen")))
    print("  it carries: {0}".format(", ".join(
        name for name in (found.get("maya_zip"), found.get("blender_zip"),
                          found.get("unreal_zip")) if name)))
    print("  it can see: Maya {0}, Blender {1}, Unreal {2}".format(
        found.get("maya_versions"), found.get("blender_versions"),
        found.get("unreal_projects")))
    # Three receivers, three archives. A build that quietly dropped one would
    # otherwise look like a success.
    missing = [name for name, key in (
        ("maya", "maya_zip"), ("blender", "blender_zip"),
        ("unreal", "unreal_zip")) if not found.get(key)]
    if missing:
        print("  but it is missing the {0} archive(s)".format(
            ", ".join(missing)))
        return False
    return True


def main():
    print("=== mLender Setup Compiler ===\n")
    run_build()
    
    version = get_version()
    print("Detected version: {0}\n".format(version))
    
    # The interpreter doing the building is the one whose runtime gets
    # frozen into the exe, so its tkinter is the exe's tkinter. Blender's
    # bundled Python has none -- an installer built with it compiles, embeds
    # every archive, and dies on launch with "no module named tkinter". That
    # happened, and it reached a release, because the check was that the
    # archives were inside rather than that the thing ran.
    try:
        import tkinter  # noqa: F401
    except Exception as exc:
        print("This Python cannot build the installer: {0}".format(exc))
        print("  {0}".format(sys.executable))
        print("It has no tkinter, which customtkinter is built on, so the")
        print("exe would compile and then fail to start. Use a Python that")
        print("has it -- a python.org install, or mayapy, or the one Unreal")
        print("ships -- and run this again.")
        sys.exit(1)

    print("Compiling Modern Installer with PyInstaller...")
    
    # We will build setup_gui.py using PyInstaller and bundle the 'dist' folder
    # Note: the command is cross-platform, but handles windows correctly here.
    dist_dir = os.path.join(ROOT, "dist")
    
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm",
        "--onefile",
        "--windowed",
        "--name", "mLender_Setup",
        "--add-data", f"{dist_dir};dist",
        os.path.join(ROOT, "packaging", "setup_gui.py")
    ]
    
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print("PyInstaller compilation failed:")
        print(result.stderr)
    else:
        exe = os.path.join(ROOT, "dist", "mLender_Setup.exe")
        if not verify_installer(exe):
            print("The installer was built but does not run. Not shipping it.")
            sys.exit(1)
        print("=== Compilation completed successfully! ===")
        print("Your installer is ready at: " + exe)

if __name__ == "__main__":
    main()
