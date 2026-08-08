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
from .animation import animation_info, sample_records
from .cameras import camera_record, camera_sample, scene_camera_shapes
from .curves import curve_records, scene_curve_shapes
from .render import render_record
from .sets import (
    display_layer_records,
    scene_display_layers,
    scene_selection_sets,
    selection_set_records,
)
from .transforms import scene_transforms, transform_records
from .collect import collect_textures
from .fbx import export_fbx
from .lights import (
    light_record,
    light_sample,
    linked_mesh_names,
    scene_light_shapes,
    scene_uses_light_linking,
    scene_uses_shadow_linking,
    shadow_linked_mesh_names,
)
from .mayautils import (
    color_management_info,
    maya_linear_unit,
    maya_path,
    meters_per_maya_unit,
    parent_of,
)
from .meshes import (
    mesh_records as mesh_records_for,
    mesh_transforms,
    scene_mesh_shapes,
    selected_light_count,
)


PACKAGE_PATTERN = re.compile(
    r"^" + re.escape(PACKAGE_PREFIX) + r"(\d+)$",
    re.IGNORECASE,
)


def export_scene(
    output_folder,
    selected_only=False,
    bake_procedurals=True,
    bake_resolution=DEFAULT_BAKE_RESOLUTION,
    collect_textures_into_package=False,
    export_animation=False,
    frame_start=None,
    frame_end=None,
    frame_step=None,
):
    """Write a numbered package folder holding the FBX and the scene JSON.

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
    json_path = os.path.join(package_folder, package_name + "_scene.json")

    warnings = []
    bake_context = BakeContext(
        os.path.join(package_folder, BAKE_FOLDER_NAME),
        resolution=bake_resolution,
        enabled=bake_procedurals,
        warnings=warnings,
    )

    try:
        mesh_shapes = scene_mesh_shapes(selected_only)
        if not mesh_shapes:
            raise RuntimeError(
                "Nothing selected contains an exportable mesh."
                if selected_only
                else "The Maya scene contains no exportable mesh."
            )
        if selected_only:
            lights_in_selection = selected_light_count()
            if lights_in_selection:
                warnings.append(
                    "Selection held {0} light(s); lighting is always exported "
                    "in full, so they were not filtered.".format(
                        lights_in_selection
                    )
                )
        # One material usually covers many meshes, so its channels are read
        # once and shared. A shader that baked is deliberately not cached:
        # a bake belongs to the mesh whose UVs it was made against.
        export_cache = {}
        # One record per instance transform, so an instanced shape is not
        # reduced to whichever transform Maya happens to list first.
        mesh_records = [
            record
            for shape in mesh_shapes
            for record in mesh_records_for(shape, bake_context,
                                           export_cache)
        ]
        # Locators and empty nulls ride the JSON: the FBX only carries
        # what sits above an exported mesh, so on their own they were
        # dropped entirely.
        transform_list = transform_records(scene_transforms())
        curve_list = curve_records(scene_curve_shapes())
        set_list = selection_set_records(scene_selection_sets(), warnings)
        layer_list = display_layer_records(scene_display_layers())
        light_shapes = scene_light_shapes()
        camera_shapes = scene_camera_shapes()
        light_records = [light_record(shape) for shape in light_shapes]
        camera_records = [camera_record(shape) for shape in camera_shapes]

        _apply_light_linking(light_records, light_shapes, mesh_records)

        animation = animation_info(
            export_animation, frame_start, frame_end, frame_step
        )
        if animation["truncated"]:
            warnings.append(
                "Frame range clamped to {0} frames, ending at {1:g}.".format(
                    animation["frame_count"], animation["end"]
                )
            )
        # Sampling steps the timeline, so it runs after the static records are
        # read and before the FBX, which bakes its own animation.
        sample_records(
            animation,
            [
                (record, _sampler(light_sample, shape))
                for record, shape in zip(light_records, light_shapes)
            ]
            + [
                (record, _sampler(camera_sample, shape))
                for record, shape in zip(camera_records, camera_shapes)
            ],
        )
        export_fbx(mesh_transforms(mesh_shapes), fbx_path, animation)

        payload = {
            "schema_version": EXPORT_SCHEMA_VERSION,
            "tool_name": TOOL_NAME,
            "profile": "scene",
            "exported_at_utc": utc_timestamp(),
            "maya_scene": cmds.file(query=True, sceneName=True) or "",
            "package_name": package_name,
            "package_folder": maya_path(package_folder),
            "fbx_file": maya_path(fbx_path),
            "selected_only": bool(selected_only),
            "mesh_count": len(mesh_records),
            "meshes": mesh_records,
            "transform_count": len(transform_list),
            "render": render_record(),
            "selection_sets": set_list,
            "display_layers": layer_list,
            "curve_count": len(curve_list),
            "curves": curve_list,
            "transforms": transform_list,
            "light_count": len(light_records),
            "lights": light_records,
            "camera_count": len(camera_records),
            "cameras": camera_records,
            "baked_texture_count": len(bake_context.baked_files),
            "export_warnings": warnings,
            "maya_linear_unit": maya_linear_unit(),
            "meters_per_maya_unit": meters_per_maya_unit(),
            "animation": animation,
            "color_management": color_management_info(),
        }
        collected = {"collected": 0, "missing": 0, "folder": ""}
        if collect_textures_into_package:
            # After the payload is complete, so every texture record exists
            # and can be repointed at its copy in one pass.
            collected = collect_textures(payload, package_folder, warnings)
            payload["collected_textures"] = collected
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
        "frame_count": animation["frame_count"],
        "collected_texture_count": collected["collected"],
        "animated": animation["enabled"],
        "warnings": warnings,
    }


def _apply_light_linking(light_records, light_shapes, mesh_records):
    """Record which meshes each light lights, when that is not all of them.

    Nothing is written for a scene that never broke a link, and nothing is
    written for a light that still lights everything: the importer's job is
    only to reproduce restrictions, and an absent field means no restriction.
    """
    uses_light = scene_uses_light_linking()
    uses_shadow = scene_uses_shadow_linking()
    if not uses_light and not uses_shadow:
        return 0

    lookup = {}
    every_mesh = set()
    for record in mesh_records:
        name = record.get("mesh") or ""
        if not name:
            continue
        every_mesh.add(name)
        for key in (
            record.get("mesh_full_name"),
            record.get("shape"),
            name,
        ):
            if key:
                lookup[str(key)] = name

    restricted = 0
    for record, shape in zip(light_records, light_shapes):
        transform = parent_of(shape)
        if uses_light:
            linked = linked_mesh_names(transform, lookup)
            if linked is not None and set(linked) != every_mesh:
                record["linked_meshes"] = linked
                restricted += 1
        if uses_shadow:
            casting = shadow_linked_mesh_names(transform, lookup)
            if casting is not None and set(casting) != every_mesh:
                record["shadow_meshes"] = casting
    return restricted


def _sampler(function, shape):
    """Bind a shape to a sampler so the timeline loop can stay generic."""
    def sample():
        return function(shape)
    return sample


def next_package_name(folder):
    """mLender_01, mLender_02, ... continuing past the highest existing one."""
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
