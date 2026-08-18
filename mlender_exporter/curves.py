# -*- coding: utf-8 -*-
"""NURBS and bezier curves.

Curves never rode the FBX: the export selects mesh transforms, so a curve was
not even offered to it. They travel as their own records instead, carrying the
control points in local space plus the transform's world matrix, exactly as
lights and cameras do.

Two things here were measured on a live Maya rather than assumed:

``cv[*]`` returns **local** coordinates. Asking a curve translated ten units up
for its first CV still gives the origin, while ``pointPosition -world`` gives
the moved one. Local is what is wanted, since the world matrix travels
separately.

``cv[*]`` also returns only the **unique** control points. A periodic circle
reports ``controlPoints`` of 11 while ``cv[*]`` gives 8; Maya repeats degree
many points to close the loop and the query hides them. Eight is what Blender
wants for a cyclic spline, so reading controlPoints instead would have stacked
three duplicates on the seam.
"""
from __future__ import absolute_import

import maya.cmds as cmds

from .constants import CURVE_ON_SURFACE_MARK
from .mayautils import (
    node_label,
    parent_of,
    unique,
    user_attributes,
    without_namespace,
    world_matrix,
)
from .meshes import expanded_selection, group_path

# Maya form: 0 open, 1 closed, 2 periodic. Both of the latter close the loop.
CURVE_FORM_OPEN = 0


def scene_curve_shapes(selected_only=False):
    """Every curve shape in the scene, intermediates excluded.

    ``bezierCurve`` inherits from ``nurbsCurve``, so listing the base type
    catches both and listing them separately would count beziers twice.

    Export Scope applies. It did not once, and a scoped export sent every
    curve in the scene alongside the one asset that had been selected.
    """
    shapes = cmds.ls(type="nurbsCurve", long=True, noIntermediate=True) or []
    # Curves on surface are construction data, not scene curves: a trim leaves
    # one boundary curve per region, and a trimmed model would arrive buried in
    # them. Maya writes them with an arrow in the DAG path
    # (|plane|planeShape->|projectionCurve1|...), which is the only handle on
    # them -- the node type is plain nurbsCurve and the parent is a transform
    # like any other.
    shapes = [shape for shape in shapes if CURVE_ON_SURFACE_MARK not in shape]
    if selected_only:
        allowed = set(expanded_selection())
        shapes = [shape for shape in shapes if shape in allowed]
    return unique([shape for shape in shapes if parent_of(shape)])


def curve_control_points(shape):
    """Local control points, as a flat list of triples.

    Read one at a time through ``pointPosition``, not in one go through
    ``getAttr(".cv[*]")``. Measured: getAttr returns **zeros** for any curve
    with construction history, because the controlPoints attribute is unused
    and the geometry arrives through the input connection instead. A circle
    from ``cmds.circle`` came back as eight points at the origin, which would
    have collapsed every procedurally built curve in the scene to a dot.

    ``ls`` with flatten gives the unique control points: Maya repeats degree
    many of them to close a periodic curve, and both this and getAttr hide the
    repeats, which is what Blender wants for a cyclic spline.
    """
    try:
        components = cmds.ls(shape + ".cv[*]", flatten=True) or []
    except Exception:
        return []
    points = []
    for component in components:
        try:
            values = cmds.pointPosition(component, local=True)
        except Exception:
            continue
        values = list(values)[:3]
        while len(values) < 3:
            values.append(0.0)
        points.append([float(value) for value in values])
    return points


def curve_record(shape):
    transform = parent_of(shape)
    full_name = node_label(transform or shape)
    return {
        "curve": without_namespace(full_name),
        "curve_full_name": full_name,
        "curve_path": transform,
        "shape": node_label(shape),
        "shape_path": shape,
        "curve_type": _node_type(shape),
        "degree": _int_attr(shape, "degree", 3),
        "form": _int_attr(shape, "form", CURVE_FORM_OPEN),
        "control_points": curve_control_points(shape),
        "groups": group_path(transform),
        "world_matrix": world_matrix(transform),
        "visible": _visible(transform),
        "custom_attributes": user_attributes(transform),
    }


def curve_records(shapes):
    return [curve_record(shape) for shape in shapes]


def _node_type(shape):
    try:
        return cmds.nodeType(shape)
    except Exception:
        return "nurbsCurve"


def _int_attr(shape, attr, fallback):
    try:
        return int(cmds.getAttr(shape + "." + attr))
    except Exception:
        return fallback


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
