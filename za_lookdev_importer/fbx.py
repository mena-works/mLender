# -*- coding: utf-8 -*-
"""Package file resolution and FBX import."""

import glob
import json
import os

import bpy


def import_fbx(path, scale):
    """Import an FBX, retrying without options older Blender builds reject."""
    try:
        scale = float(scale)
    except Exception:
        scale = 1.0
    kwargs = {
        "filepath": path,
        "global_scale": scale,
        # Textures are wired from the Maya paths in the JSON, so Blender's own
        # texture search would only produce duplicates.
        "use_image_search": False,
    }
    try:
        bpy.ops.import_scene.fbx(**kwargs)
    except TypeError:
        kwargs.pop("use_image_search", None)
        bpy.ops.import_scene.fbx(**kwargs)


def resolve_fbx_path(package_folder, package_data):
    """Find the package FBX, tolerating a package folder that has moved."""
    raw = package_data.get("fbx_file") or ""
    candidates = [
        raw,
        os.path.join(package_folder, raw),
        os.path.join(package_folder, os.path.basename(raw)),
    ]
    for path in candidates:
        if path and os.path.isfile(path):
            return os.path.abspath(path)
    files = glob.glob(os.path.join(package_folder, "*.fbx"))
    if len(files) == 1:
        return os.path.abspath(files[0])
    raise ValueError("Package FBX file was not found.")


def read_package_json(package_folder):
    files = glob.glob(os.path.join(package_folder, "*_lookdev.json"))
    if len(files) != 1:
        raise ValueError("Package must contain exactly one *_lookdev.json file.")
    with open(files[0], "r", encoding="utf-8") as handle:
        return json.load(handle)
