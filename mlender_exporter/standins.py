# -*- coding: utf-8 -*-
"""Shapes that stand in for a file on disk rather than carrying geometry.

An ``aiStandIn`` and a ``gpuCache`` are the same shape of problem: neither
holds any geometry, each points at a file its renderer opens later, and the
scene only draws a proxy. Coverage already reported both as unaccounted, so
this promotes them from "named in a warning" to "carried".

The file is **referenced, not copied**. A standin is routinely gigabytes and
the package already references textures for the same reason; copying is the
kind of decision that should be the user's, not the tool's.

Attribute names were read off live Maya 2023 nodes. Two measured facts shape
what travels:

* The path attribute is ``dso`` on a standin and ``cacheFileName`` on a
  gpuCache -- different names for one idea, which is why they go in a table.
* ``Min/MaxBoundingBox`` is filled in by the viewport, not by the DG. In a
  headless export it stays at its plus-minus-one default, and
  ``exactWorldBoundingBox`` answers zero. So the bounds travel as what Maya
  is drawing, which is what a placeholder should reproduce, and not as a
  claim about the size of the file's contents.
"""
from __future__ import absolute_import

import maya.cmds as cmds

from .constants import STANDIN_NODE_TYPES
from .mayautils import (
    attr_exists,
    maya_path,
    node_label,
    node_type,
    parent_of,
    plug_value,
    unique,
    user_attributes,
    without_namespace,
    world_matrix,
)
from .meshes import expanded_selection, group_path


def scene_standin_shapes(selected_only=False):
    """Every standin shape in the scene, or those under the selection."""
    found = []
    for kind in sorted(STANDIN_NODE_TYPES):
        try:
            shapes = cmds.ls(type=kind, long=True, noIntermediate=True) or []
        except Exception:
            # The plugin that defines the type is not loaded, so the scene
            # cannot contain one.
            continue
        found.extend(shapes)
    if selected_only:
        allowed = set(expanded_selection())
        found = [shape for shape in found if shape in allowed]
    return unique([shape for shape in found if parent_of(shape)])


def standin_record(shape):
    kind = node_type(shape)
    table = STANDIN_NODE_TYPES.get(kind) or {}
    transform = parent_of(shape)
    full_name = node_label(transform or shape)
    return {
        "standin": without_namespace(full_name),
        "standin_full_name": full_name,
        "standin_path": transform,
        "shape": node_label(shape),
        "shape_path": shape,
        "node_type": kind,
        "file_path": _path(shape, table.get("path")),
        # Which object inside the file, when the node names one.
        "object_path": _string(shape, table.get("object_path")),
        "bounds_min": _vector(shape, table.get("bounds_min")),
        "bounds_max": _vector(shape, table.get("bounds_max")),
        "frame": _number(shape, table.get("frame"), 0.0),
        "frame_offset": _number(shape, table.get("frame_offset"), 0.0),
        "use_frame_extension": _flag(
            shape, table.get("use_frame_extension")
        ),
        "groups": group_path(transform),
        "world_matrix": world_matrix(transform),
        "visible": _visible(transform),
        "custom_attributes": user_attributes(transform),
    }


def standin_records(shapes):
    return [standin_record(shape) for shape in shapes]


def _first_attr(node, attrs):
    for attr in attrs or ():
        if attr_exists(node, attr):
            return attr
    return None


def _path(node, attrs):
    raw = _string(node, attrs).strip()
    return maya_path(raw) if raw else ""


def _string(node, attrs):
    attr = _first_attr(node, attrs)
    if not attr:
        return ""
    try:
        return str(cmds.getAttr(node + "." + attr) or "")
    except Exception:
        return ""


def _vector(node, attrs):
    attr = _first_attr(node, attrs)
    if not attr:
        return []
    value = plug_value(node + "." + attr)
    if isinstance(value, (list, tuple)):
        return [float(item) for item in value[:3]]
    return []


def _number(node, attrs, fallback):
    attr = _first_attr(node, attrs)
    if not attr:
        return float(fallback)
    value = plug_value(node + "." + attr)
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(fallback)


def _flag(node, attrs):
    attr = _first_attr(node, attrs)
    if not attr:
        return False
    return bool(plug_value(node + "." + attr))


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
