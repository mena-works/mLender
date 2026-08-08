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
    ANIMATED_CAMERA_ATTRS,
    CAMERA_FILM_FIT_ATTR,
    CAMERA_INCHES_TO_MM,
    CAMERA_NUMERIC_ATTRS,
)
from .mayautils import (
    attr_exists,
    current_frame,
    first_existing_attr,
    maya_path,
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


def image_plane_records(camera_shape):
    """Image planes attached to a camera, as reference records.

    A plane hangs off ``camera.imagePlane`` through its own message plug,
    which is how it is found; a camera without one answers nothing at all,
    so the common case costs a single query.

    Blender has background images, which are viewport reference in the same
    way, but fewer fit modes: Maya offers Fill, Best, Horizontal, Vertical
    and To Size against Blender's stretch, fit and crop. The Maya value is
    recorded alongside so nothing is lost in the approximation.
    """
    try:
        planes = cmds.listConnections(
            camera_shape + ".imagePlane", source=True, shapes=True
        ) or []
    except Exception:
        return []

    records = []
    for plane in unique(planes):
        if not attr_exists(plane, "imageName"):
            continue
        size_x = _number(plug_value(plane + ".sizeX"), 0.0)
        size_y = _number(plug_value(plane + ".sizeY"), 0.0)
        _t, _a, type_label = first_existing_attr(plane, ("type",))
        _d, _da, display_label = first_existing_attr(plane, ("displayMode",))
        _f, _fa, fit_label = first_existing_attr(plane, ("fit",))
        records.append({
            "plane": without_namespace(node_label(plane)),
            # plug_value drops strings by design, so the file name is read
            # with the string reader; using it turned an empty result into
            # abspath("") and pointed every plane at the working directory.
            "image_path": _image_path(plane),
            "source_type": str(type_label or ""),
            "display_mode": str(display_label or ""),
            "fit": str(fit_label or ""),
            "alpha": _number(plug_value(plane + ".alphaGain"), 1.0),
            "depth": _number(plug_value(plane + ".depth"), 0.0),
            # Fractions of the plane, the same treatment the film offset
            # gets, rather than raw Maya units the importer would guess at.
            "offset_x": _ratio(plug_value(plane + ".offsetX"), size_x),
            "offset_y": _ratio(plug_value(plane + ".offsetY"), size_y),
            "size_x": size_x,
            "size_y": size_y,
            "use_frame_extension": bool(
                plug_value(plane + ".useFrameExtension")
            ),
        })
    return records


def _raw_string(node, attr):
    try:
        return str(cmds.getAttr(node + "." + attr) or "")
    except Exception:
        return ""


def _image_path(plane):
    raw = _raw_string(plane, "imageName").strip()
    return maya_path(raw) if raw else ""


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
        "image_planes": image_plane_records(camera_shape),
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


def camera_sample(camera_shape):
    """The values worth capturing per frame: where it is and what lens it has.

    Read at whatever frame the timeline is parked on; the caller steps it.
    """
    transform = parent_of(camera_shape)
    sample = {"matrix": world_matrix(transform)}
    for semantic, attr in ANIMATED_CAMERA_ATTRS.items():
        if not attr_exists(camera_shape, attr):
            continue
        value = plug_value(camera_shape + "." + attr)
        if value is not None:
            sample[semantic] = value
    return sample


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
