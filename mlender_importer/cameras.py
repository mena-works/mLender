# -*- coding: utf-8 -*-
"""Rebuild Maya cameras as Blender cameras.

Both applications point a camera down its local -Z with +Y up, so the shared
Maya to Blender matrix conversion applies unchanged. The lens is where they
differ: Maya states the film back in inches and its clip planes, focus
distance and orthographic width in scene units, all of which the exporter has
already converted or carried explicitly.
"""

import os

import bpy

from .animation import animate_object, key_data_value
from .constants import (
    CAMERA_COLLECTION_NAME,
    CAMERA_SENSOR_FIT,
    IMAGE_PLANE_FIT,
    IMAGE_PLANE_HIDDEN_MODE,
)
from .transforms import maya_matrix_to_blender
from .utils import namespace_free_name, scalar


def import_cameras(package_data, root_collection, import_scale, warnings):
    records = list(package_data.get("cameras") or [])
    if not records:
        return {"camera_count": 0, "active": ""}

    collection = bpy.data.collections.new(CAMERA_COLLECTION_NAME)
    root_collection.children.link(collection)
    meters_per_unit = scalar(package_data.get("meters_per_maya_unit"), 0.01)
    position_scale = meters_per_unit * max(scalar(import_scale, 1.0), 0.000001)

    created = []
    for record in records:
        try:
            created.append(
                (record, create_camera_object(
                    record, collection, position_scale, warnings
                ))
            )
        except Exception as exc:
            warnings.append(
                'Camera "{0}" could not be created: {1}'.format(
                    record.get("full_name") or record.get("name") or "Camera",
                    exc,
                )
            )

    active = _activate_scene_camera(created, warnings)
    return {"camera_count": len(created), "active": active}


def create_camera_object(record, collection, position_scale, warnings=None):
    name = (
        record.get("name")
        or namespace_free_name(record.get("full_name"))
        or "Camera"
    )
    data = bpy.data.cameras.new(name)
    obj = bpy.data.objects.new(name, data)
    collection.objects.link(obj)
    obj.matrix_world = maya_matrix_to_blender(
        record.get("transform") or {},
        position_scale,
    )
    # A scaled camera distorts the frame in ways Maya never showed.
    obj.scale = (1.0, 1.0, 1.0)

    if record.get("orthographic"):
        data.type = "ORTHO"
        data.ortho_scale = max(
            0.000001,
            scalar(record.get("orthographic_width"), 10.0) * position_scale,
        )
    else:
        data.type = "PERSP"
        data.lens = max(1.0, scalar(record.get("focal_length_mm"), 35.0))

    data.sensor_width = max(
        0.001, scalar(record.get("sensor_width_mm"), 36.0)
    )
    data.sensor_height = max(
        0.001, scalar(record.get("sensor_height_mm"), 24.0)
    )
    fit = CAMERA_SENSOR_FIT.get(str(record.get("film_fit") or "").lower())
    if fit:
        data.sensor_fit = fit

    data.shift_x = scalar(record.get("shift_x"), 0.0)
    data.shift_y = scalar(record.get("shift_y"), 0.0)

    near = scalar(record.get("near_clip"), 0.1) * position_scale
    far = scalar(record.get("far_clip"), 10000.0) * position_scale
    data.clip_start = max(0.000001, near)
    data.clip_end = max(data.clip_start * 1.0001, far)

    _apply_depth_of_field(data, record, position_scale)
    _animate_camera(obj, data, record, position_scale)
    apply_image_planes(data, record, warnings if warnings is not None else [])
    _store_camera_metadata(obj, data, record)
    return obj


def _animate_camera(obj, data, record, position_scale):
    """Key the transform and whatever lens values move with it."""
    def apply_sample(sample, frame):
        if "focal_length_mm" in sample and data.type != "ORTHO":
            key_data_value(
                data, "lens", max(1.0, scalar(sample["focal_length_mm"], 35.0)),
                frame,
            )
        if "orthographic_width" in sample and data.type == "ORTHO":
            key_data_value(
                data,
                "ortho_scale",
                max(
                    0.000001,
                    scalar(sample["orthographic_width"], 10.0) * position_scale,
                ),
                frame,
            )
        dof = getattr(data, "dof", None)
        if dof is not None and "focus_distance" in sample:
            key_data_value(
                dof,
                "focus_distance",
                max(0.0, scalar(sample["focus_distance"], 5.0) * position_scale),
                frame,
            )
        if dof is not None and "f_stop" in sample:
            key_data_value(
                dof, "aperture_fstop", max(0.01, scalar(sample["f_stop"], 5.6)),
                frame,
            )

    return animate_object(obj, record, position_scale, apply_sample)


def _apply_depth_of_field(data, record, position_scale):
    dof = getattr(data, "dof", None)
    if dof is None:
        return
    dof.use_dof = bool(record.get("depth_of_field"))
    dof.focus_distance = max(
        0.0,
        scalar(record.get("focus_distance"), 5.0) * position_scale,
    )
    if hasattr(dof, "aperture_fstop"):
        dof.aperture_fstop = max(0.01, scalar(record.get("f_stop"), 5.6))


def _activate_scene_camera(created, warnings):
    """Make the Maya renderable camera the one Blender renders through."""
    if not created:
        return ""
    renderable = [pair for pair in created if pair[0].get("renderable")]
    if len(renderable) > 1:
        warnings.append(
            "Several Maya cameras are renderable; the first one was made the "
            "active Blender camera."
        )
    chosen = (renderable or created)[0][1]
    bpy.context.scene.camera = chosen
    return chosen.name


def apply_image_planes(data, record, warnings):
    """Rebuild Maya image planes as Blender camera background images.

    Both are viewport reference rather than something that renders, so the
    mapping is about the image being on the right camera at the right size.

    Two approximations, both recorded rather than hidden. Maya has five fit
    modes against Blender's three, and Maya's plane depth is a distance while
    Blender only offers front or back. The Maya values are kept on the camera
    data so the difference is visible instead of silently lost.
    """
    planes = record.get("image_planes") or []
    if not planes:
        return 0

    built = 0
    for plane in planes:
        path = str(plane.get("image_path") or "")
        if not path:
            # A texture or movie driven plane has no file to point Blender at.
            warnings.append(
                'Image plane "{0}" has no image file, so nothing was '
                "attached to the camera.".format(plane.get("plane") or "?")
            )
            continue
        if not os.path.isfile(path):
            warnings.append(
                'Image plane file was not found: {0}'.format(path)
            )
            continue
        try:
            image = bpy.data.images.load(path, check_existing=True)
        except Exception as exc:
            warnings.append(
                "Image plane could not be loaded: {0} ({1})".format(path, exc)
            )
            continue

        background = data.background_images.new()
        background.image = image
        background.alpha = max(0.0, min(1.0, scalar(plane.get("alpha"), 1.0)))
        background.display_depth = "BACK"
        background.frame_method = IMAGE_PLANE_FIT.get(
            str(plane.get("fit") or ""), "FIT"
        )
        background.offset = (
            scalar(plane.get("offset_x"), 0.0),
            scalar(plane.get("offset_y"), 0.0),
        )
        # Maya's None display mode means the plane exists but is not drawn.
        if str(plane.get("display_mode") or "") == IMAGE_PLANE_HIDDEN_MODE:
            background.show_background_image = False
        built += 1

    if built:
        data.show_background_images = True
        data["ml_source_image_plane_count"] = built
        data["ml_source_image_plane_fit"] = str(
            (planes[0] or {}).get("fit") or ""
        )
        data["ml_source_image_plane_depth"] = scalar(
            (planes[0] or {}).get("depth"), 0.0
        )
    return built


def _store_camera_metadata(obj, data, record):
    data["ml_generated"] = True
    data["ml_source_full_name"] = str(record.get("full_name") or "")
    data["ml_source_renderable"] = bool(record.get("renderable"))
    data["ml_source_focal_length_mm"] = scalar(
        record.get("focal_length_mm"), 35.0
    )
    data["ml_source_film_fit"] = str(record.get("film_fit") or "")
    obj["ml_generated"] = True
