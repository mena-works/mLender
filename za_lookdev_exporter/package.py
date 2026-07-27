# -*- coding: utf-8 -*-
"""Package creation: folder numbering, FBX + JSON writing, atomic cleanup."""
from __future__ import absolute_import

import datetime
import io
import json
import os
import re
import shutil

import maya.cmds as cmds

from .bake import BakeContext
from .constants import (
    BAKE_FOLDER_NAME,
    DEFAULT_BAKE_RESOLUTION,
    EXPORT_SCHEMA_VERSION,
    PACKAGE_PREFIX,
    TOOL_NAME,
)
from .cameras import camera_record, scene_camera_shapes
from .fbx import export_fbx
from .lights import light_record, scene_light_shapes
from .mayautils import maya_linear_unit, maya_path, meters_per_maya_unit
from .meshes import mesh_record, mesh_transforms, scene_mesh_shapes


PACKAGE_PATTERN = re.compile(
    r"^" + re.escape(PACKAGE_PREFIX) + r"(\d+)$",
    re.IGNORECASE,
)


def export_lookdev(
    output_folder,
    bake_procedurals=True,
    bake_resolution=DEFAULT_BAKE_RESOLUTION,
):
    """Write a numbered package folder holding the FBX and the lookdev JSON.

    Package creation is atomic: any failure removes both files and the folder
    so a half written package is never picked up by the importer.
    """
    output_folder = normalize_folder(output_folder)
    if not os.path.isdir(output_folder):
        os.makedirs(output_folder)

    package_name = next_package_name(output_folder)
    package_folder = os.path.join(output_folder, package_name)
    os.makedirs(package_folder)
    fbx_path = os.path.join(package_folder, package_name + ".fbx")
    json_path = os.path.join(package_folder, package_name + "_lookdev.json")

    warnings = []
    bake_context = BakeContext(
        os.path.join(package_folder, BAKE_FOLDER_NAME),
        resolution=bake_resolution,
        enabled=bake_procedurals,
        warnings=warnings,
    )

    try:
        mesh_shapes = scene_mesh_shapes()
        if not mesh_shapes:
            raise RuntimeError("The Maya scene contains no exportable mesh.")
        mesh_records = [
            mesh_record(shape, bake_context) for shape in mesh_shapes
        ]
        light_records = [light_record(shape) for shape in scene_light_shapes()]
        camera_records = [
            camera_record(shape) for shape in scene_camera_shapes()
        ]
        export_fbx(mesh_transforms(mesh_shapes), fbx_path)

        payload = {
            "schema_version": EXPORT_SCHEMA_VERSION,
            "tool_name": TOOL_NAME,
            "profile": "lookdev",
            "exported_at_utc": utc_timestamp(),
            "maya_scene": cmds.file(query=True, sceneName=True) or "",
            "package_name": package_name,
            "package_folder": maya_path(package_folder),
            "fbx_file": maya_path(fbx_path),
            "mesh_count": len(mesh_records),
            "meshes": mesh_records,
            "light_count": len(light_records),
            "lights": light_records,
            "camera_count": len(camera_records),
            "cameras": camera_records,
            "baked_texture_count": len(bake_context.baked_files),
            "export_warnings": warnings,
            "maya_linear_unit": maya_linear_unit(),
            "meters_per_maya_unit": meters_per_maya_unit(),
        }
        write_json(json_path, payload)
    except Exception:
        remove_file(fbx_path)
        remove_file(json_path)
        try:
            # rmtree rather than rmdir: baking may already have written
            # textures into the package, and a half written package must
            # not survive.
            shutil.rmtree(package_folder, ignore_errors=True)
        except Exception:
            pass
        raise

    return {
        "package_name": package_name,
        "package_folder": package_folder,
        "fbx_path": fbx_path,
        "json_path": json_path,
        "package_json": payload,
        "mesh_count": len(mesh_records),
        "light_count": len(light_records),
        "camera_count": len(camera_records),
        "baked_texture_count": len(bake_context.baked_files),
        "warnings": warnings,
    }


def next_package_name(folder):
    """MTB_Z_A_01, MTB_Z_A_02, ... continuing past the highest existing one."""
    highest = 0
    if os.path.isdir(folder):
        for name in os.listdir(folder):
            if not os.path.isdir(os.path.join(folder, name)):
                continue
            match = PACKAGE_PATTERN.match(name)
            if match:
                highest = max(highest, int(match.group(1)))
    return "{0}{1:02d}".format(PACKAGE_PREFIX, highest + 1)


def utc_timestamp():
    """ISO-8601 UTC timestamp; utcnow() is deprecated from Python 3.12."""
    try:
        now = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)
    except AttributeError:
        now = datetime.datetime.utcnow()
    return now.isoformat() + "Z"


def default_export_folder():
    scene = cmds.file(query=True, sceneName=True) or ""
    if scene:
        return os.path.dirname(scene)
    try:
        return (
            cmds.workspace(query=True, rootDirectory=True)
            or os.path.expanduser("~")
        )
    except Exception:
        return os.path.expanduser("~")


def normalize_folder(path):
    if not path:
        raise ValueError("Choose an export location.")
    return os.path.abspath(os.path.expanduser(path))


def write_json(path, data):
    with io.open(path, "w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2, sort_keys=True)


def remove_file(path):
    try:
        if os.path.isfile(path):
            os.remove(path)
    except Exception:
        pass
