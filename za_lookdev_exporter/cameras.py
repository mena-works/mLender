# -*- coding: utf-8 -*-
"""Scene camera discovery and per-camera records.

Maya's startup cameras (persp, top, front, side) are viewport furniture, not
scene content, so they are skipped. Everything the importer needs to rebuild
the lens is carried explicitly, because Maya states film back in inches and
clip planes in scene units while Blender wants millimetres and metres.
"""
from __future__ import absolute_import

import maya.cmds as cmds

from .constants import (
    CAMERA_FILM_FIT_ATTR,
    CAMERA_INCHES_TO_MM,
    CAMERA_NUMERIC_ATTRS,
)
from .mayautils import (
    attr_exists,
    current_frame,
    first_existing_attr,
    node_label,
    parent_of,
    plug_value,
    unique,
    without_namespace,
    world_matrix,
    xform_vector,
)


def scene_camera_shapes():
    """Every camera the user actually authored, startup cameras excluded."""
    result = []
    for shape in cmds.ls(type="camera", long=True) or []:
        if not parent_of(shape):
            continue
        try:
            if cmds.camera(shape, query=True, startupCamera=True):
                continue
        except Exception:
            # A camera that cannot answer is kept rather than silently lost.
            pass
        result.append(shape)
    return unique(result)


def camera_record(camera_shape):
    transform = parent_of(camera_shape)
    values = {}
    for semantic, attr in CAMERA_NUMERIC_ATTRS.items():
        if attr_exists(camera_shape, attr):
            value = plug_value(camera_shape + "." + attr)
            if value is not None:
                values[semantic] = value

    _fit_value, _fit_attr, fit_label = first_existing_attr(
        camera_shape,
        (CAMERA_FILM_FIT_ATTR,),
    )

    horizontal_inches = _number(values.get("film_aperture_horizontal"), 1.41732)
    vertical_inches = _number(values.get("film_aperture_vertical"), 0.94488)

    return {
        "name": without_namespace(node_label(transform or camera_shape)),
        "full_name": node_label(transform or camera_shape),
        "shape": without_namespace(node_label(camera_shape)),
        "renderable": _renderable(camera_shape),
        "orthographic": bool(values.get("orthographic")),
        "orthographic_width": _number(values.get("orthographic_width"), 10.0),
        "focal_length_mm": _number(values.get("focal_length"), 35.0),
        # Maya states the film back in inches; Blender wants millimetres.
        "sensor_width_mm": horizontal_inches * CAMERA_INCHES_TO_MM,
        "sensor_height_mm": vertical_inches * CAMERA_INCHES_TO_MM,
        "film_fit": str(fit_label or ""),
        # Blender shift is a fraction of the film back, so divide by it here
        # rather than shipping raw inches the importer would have to guess at.
        "shift_x": _ratio(values.get("film_offset_horizontal"), horizontal_inches),
        "shift_y": _ratio(values.get("film_offset_vertical"), vertical_inches),
        "near_clip": _number(values.get("near_clip"), 0.1),
        "far_clip": _number(values.get("far_clip"), 10000.0),
        "depth_of_field": bool(values.get("depth_of_field")),
        "f_stop": _number(values.get("f_stop"), 5.6),
        "focus_distance": _number(values.get("focus_distance"), 5.0),
        "parameters": values,
        "transform": {
            "world_matrix": world_matrix(transform),
            "translation": xform_vector(
                transform,
                translation=True,
                default=(0.0, 0.0, 0.0),
            ),
            "rotation_degrees": xform_vector(
                transform,
                rotation=True,
                default=(0.0, 0.0, 0.0),
            ),
        },
        "frame": current_frame(),
    }


def _renderable(camera_shape):
    if not attr_exists(camera_shape, "renderable"):
        return False
    try:
        return bool(cmds.getAttr(camera_shape + ".renderable"))
    except Exception:
        return False


def _number(value, default):
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _ratio(offset, aperture):
    try:
        aperture = float(aperture)
        if abs(aperture) < 1e-9:
            return 0.0
        return float(offset) / aperture
    except (TypeError, ValueError):
        return 0.0
