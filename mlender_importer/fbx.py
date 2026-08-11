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
        # Measured on 4.1 through 5.2: the importer's default is 1.0, which
        # places FBX time zero at frame 1. Maya's frame N is written at time
        # N/fps, so every baked key landed on frame N+1 -- a spine joint keyed
        # 1..10 arrived keyed 2..11, one frame behind the lights, cameras and
        # visibility this tool keys from the JSON at Maya's own frame numbers.
        # Zero puts Maya's frame N on Blender's frame N.
        "anim_offset": 0.0,
    }
    try:
        bpy.ops.import_scene.fbx(**kwargs)
    except TypeError:
        kwargs.pop("use_image_search", None)
        try:
            bpy.ops.import_scene.fbx(**kwargs)
        except TypeError:
            kwargs.pop("anim_offset", None)
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
    """Find the package's JSON, under either the current or the old name.

    Packages written before the tool was renamed carry ``*_lookdev.json``.
    Reading them costs one extra glob and the schema is unchanged, so there is
    no reason to refuse a package that is still perfectly readable.
    """
    files = glob.glob(os.path.join(package_folder, "*_scene.json"))
    if not files:
        files = glob.glob(os.path.join(package_folder, "*_lookdev.json"))
    if len(files) != 1:
        raise ValueError(
            "Package must contain exactly one *_scene.json file."
        )
    with open(files[0], "r", encoding="utf-8") as handle:
        return json.load(handle)
