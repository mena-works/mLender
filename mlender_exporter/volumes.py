# -*- coding: utf-8 -*-
"""Arnold volumes.

An ``aiVolume`` points at a VDB file. Blender has a Volume object that reads
the same format, so the geometry needs no conversion at all: what travels is
the path, the frame handling and where the volume sits.

Measured: an aiVolume is neither a mesh nor a locator, so none of the existing
discovery found it and a volume simply did not arrive. It also does not leak
into the empty transfer, because that only takes transforms with a locator
shape or no shape at all.

Only Arnold is read. Redshift's volume attribute names cannot be probed on
this machine and this project does not write names it has not read off a live
session -- the same footing as the Redshift light anchor and motion blur.
"""
from __future__ import absolute_import

import maya.cmds as cmds

from .mayautils import (
    attr_exists,
    maya_path,
    node_label,
    parent_of,
    plug_value,
    unique,
    user_attributes,
    without_namespace,
    world_matrix,
)
from .meshes import expanded_selection, group_path

VOLUME_NODE_TYPE = "aiVolume"


def scene_volume_shapes(selected_only=False):
    """Every Arnold volume shape, or those under the selection."""
    try:
        shapes = cmds.ls(type=VOLUME_NODE_TYPE, long=True,
                         noIntermediate=True) or []
    except Exception:
        # The plugin is not loaded, so there are no volumes to find.
        return []
    if selected_only:
        allowed = set(expanded_selection())
        shapes = [shape for shape in shapes if shape in allowed]
    return unique([shape for shape in shapes if parent_of(shape)])


def volume_record(shape):
    transform = parent_of(shape)
    full_name = node_label(transform or shape)
    return {
        "volume": without_namespace(full_name),
        "volume_full_name": full_name,
        "volume_path": transform,
        "shape": node_label(shape),
        "shape_path": shape,
        "file_path": _file_path(shape),
        # Maya names the grids it wants; Blender loads whatever the file has,
        # so this is carried for reference rather than applied.
        "grids": _string(shape, "grids"),
        "velocity_grids": _string(shape, "velocityGrids"),
        "frame": int(_number(shape, "frame", 0.0)),
        "use_frame_extension": bool(plug_value(shape + ".useFrameExtension")),
        # Arnold render settings with no Blender datablock equivalent. Kept so
        # the difference is visible rather than silently dropped.
        "step_size": _number(shape, "stepSize", 0.0),
        "step_scale": _number(shape, "stepScale", 1.0),
        "velocity_scale": _number(shape, "velocityScale", 1.0),
        "motion_blur": bool(plug_value(shape + ".motionBlur")),
        "volume_padding": _number(shape, "volumePadding", 0.0),
        "groups": group_path(transform),
        "world_matrix": world_matrix(transform),
        "visible": _visible(transform),
        "custom_attributes": user_attributes(transform),
    }


def volume_records(shapes):
    return [volume_record(shape) for shape in shapes]


def _file_path(shape):
    raw = _string(shape, "filename").strip()
    return maya_path(raw) if raw else ""


def _string(node, attr):
    if not attr_exists(node, attr):
        return ""
    try:
        return str(cmds.getAttr(node + "." + attr) or "")
    except Exception:
        return ""


def _number(node, attr, fallback):
    value = plug_value(node + "." + attr)
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(fallback)


def _visible(transform):
    if not transform:
        return True
    for attr in ("visibility", "lodVisibility"):
        try:
            if not bool(cmds.getAttr(transform + "." + attr)):
                return False
        except Exception:
            continue
    return True
