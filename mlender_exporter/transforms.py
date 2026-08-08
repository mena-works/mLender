# -*- coding: utf-8 -*-
"""Transforms that carry no geometry: locators and empty nulls.

The FBX only carries what hangs above an exported mesh, so a locator used as a
placement control, or a group holding nothing but locators, never reached
Blender at all. Measured on a real scene: neither the locators nor the groups
without meshes under them appeared, with no warning either.

Transforms that *do* have a mesh below them are deliberately not recorded here.
FBX already brings those as empties because they are ancestors of an exported
mesh, and recording them a second time would build two objects for one Maya
node.
"""
from __future__ import absolute_import

import maya.cmds as cmds

from .mayautils import (
    node_label,
    node_type,
    unique,
    without_namespace,
    world_matrix,
)
from .meshes import expanded_selection, group_path


# Shape types that make a transform worth carrying on its own. A transform
# holding a camera or a light is not one of these: those travel as their own
# records and would otherwise arrive twice.
STANDALONE_SHAPE_TYPES = ("locator",)


def scene_transforms(selected_only=False):
    """Locators and empty nulls, as full paths, outermost first.

    Sorted by depth so a parent is always created before its children on the
    Blender side, which lets parenting be applied in one pass.

    Export Scope applies here too. It did not once, and a scoped export
    sent every locator in the scene alongside the one asset that had been
    selected.
    """
    candidates = (
        expanded_selection() if selected_only
        else cmds.ls(type="transform", long=True) or []
    )
    found = []
    for transform in candidates:
        if node_type(transform) != "transform":
            continue
        if is_standalone_transform(transform):
            found.append(transform)
    return sorted(unique(found), key=lambda path: path.count("|"))


def is_standalone_transform(transform):
    """Whether this transform would otherwise be lost.

    Two kinds qualify: a locator, and a transform with no shape and no mesh
    anywhere beneath it. Anything with a mesh below already rides the FBX.
    """
    shapes = cmds.listRelatives(transform, shapes=True, fullPath=True) or []
    if shapes:
        types = {cmds.nodeType(shape) for shape in shapes}
        return bool(types & set(STANDALONE_SHAPE_TYPES))
    return not has_mesh_below(transform)


def has_mesh_below(transform):
    try:
        below = cmds.listRelatives(
            transform, allDescendents=True, type="mesh", fullPath=True
        )
    except Exception:
        below = None
    return bool(below)


def transform_type(transform):
    shapes = cmds.listRelatives(transform, shapes=True, fullPath=True) or []
    if shapes:
        try:
            return cmds.nodeType(shapes[0])
        except Exception:
            return "locator"
    return "group"


def parent_transform(transform):
    """The transform above this one, or an empty string at the root."""
    parents = cmds.listRelatives(transform, parent=True, fullPath=True) or []
    return parents[0] if parents else ""


def transform_record(transform):
    full_name = node_label(transform)
    return {
        "transform": without_namespace(full_name),
        "transform_full_name": full_name,
        "transform_path": transform,
        "transform_type": transform_type(transform),
        "parent_path": parent_transform(transform),
        # The group trail excludes the transform's own name, exactly as it
        # does for meshes, so the importer can reuse the same placement.
        "groups": group_path(transform),
        "world_matrix": world_matrix(transform),
        "visible": _visible(transform),
    }


def transform_records(transforms):
    return [transform_record(transform) for transform in transforms]


def _visible(transform):
    for attr in ("visibility", "lodVisibility"):
        try:
            if not bool(cmds.getAttr(transform + "." + attr)):
                return False
        except Exception:
            continue
    return True
