# -*- coding: utf-8 -*-
"""Maya particles, as points.

Blender has no equivalent to a Maya particle object. Its own particle systems
are driven by emitters and physics rather than by explicit positions, and a
point cloud datablock cannot be built from Python at all: measured on 4.1, 4.5
and 5.2, ``pointclouds`` exists but its points collection has no ``add``.

So what travels is the one thing that survives the difference intact -- where
the particles are -- and the importer builds a vertex-only mesh, which every
Blender version accepts and geometry nodes can instance onto.

Two readings were measured rather than assumed. ``particle -q -position``
returns **None**; the query that works is ``getParticleAttr`` with ``array``,
which hands back a flat list of three numbers per particle. And those numbers
are **local**: moving the transform after creation leaves them unchanged, so
they pair with the world matrix exactly as curve control points do.
"""
from __future__ import absolute_import

import maya.cmds as cmds

from .mayautils import (
    attr_exists,
    first_existing_attr,
    node_label,
    parent_of,
    unique,
    user_attributes,
    without_namespace,
    world_matrix,
)
from .meshes import expanded_selection, group_path

PARTICLE_NODE_TYPE = "particle"
# Per particle arrays worth carrying, and how many numbers each holds per
# particle. Absent unless somebody added them, which is the usual case.
PARTICLE_POINT_ARRAYS = (
    ("radius", "radiusPP", 1),
    ("color", "rgbPP", 3),
    ("opacity", "opacityPP", 1),
)


def scene_particle_shapes(selected_only=False):
    """Particle shapes in the scene, or those under the selection.

    ``nParticle`` derives from ``particle``, so listing the base type catches
    both, the same way listing ``nurbsCurve`` catches bezier curves.
    """
    try:
        shapes = cmds.ls(type=PARTICLE_NODE_TYPE, long=True,
                         noIntermediate=True) or []
    except Exception:
        return []
    if selected_only:
        allowed = set(expanded_selection())
        shapes = [shape for shape in shapes if shape in allowed]
    return unique([shape for shape in shapes if parent_of(shape)])


def particle_count(shape):
    try:
        return int(cmds.particle(shape, query=True, count=True) or 0)
    except Exception:
        return 0


def read_point_array(shape, attribute, count, stride):
    """One per particle array as a flat list, or an empty list.

    Length is checked against the count rather than trusted: an array that has
    not been populated reads back a different size, and half an array of
    positions is worse than none.
    """
    if count <= 0 or not attr_exists(shape, attribute):
        return []
    try:
        values = cmds.getParticleAttr(
            "{0}.pt[0:{1}]".format(shape, count - 1),
            at=attribute,
            array=True,
        ) or []
    except Exception:
        return []
    if len(values) != count * stride:
        return []
    return [float(item) for item in values]


def particle_record(shape):
    transform = parent_of(shape)
    full_name = node_label(transform or shape)
    count = particle_count(shape)
    _value, _attr, render_label = first_existing_attr(
        shape, ("particleRenderType",)
    )

    record = {
        "particle": without_namespace(full_name),
        "particle_full_name": full_name,
        "particle_path": transform,
        "shape": node_label(shape),
        "shape_path": shape,
        "count": count,
        # Local, so they pair with the world matrix rather than replacing it.
        "positions": read_point_array(shape, "position", count, 3),
        "render_type": str(render_label or ""),
        "groups": group_path(transform),
        "world_matrix": world_matrix(transform),
        "visible": _visible(transform),
        "custom_attributes": user_attributes(transform),
    }
    for semantic, attribute, stride in PARTICLE_POINT_ARRAYS:
        values = read_point_array(shape, attribute, count, stride)
        if values:
            record[semantic] = values
    return record


def particle_records(shapes):
    return [particle_record(shape) for shape in shapes]


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
