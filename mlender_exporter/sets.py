# -*- coding: utf-8 -*-
"""Selection sets and display layers.

Both were measured on a live Maya rather than assumed, and both had a trap:

``shadingEngine`` is its own node type, so filtering on ``objectSet`` keeps
material assignments out of the way. ``defaultLightSet`` and
``defaultObjectSet`` are *not* -- they are genuine object sets and have to be
excluded by name.

Set membership comes back as **short** names. This scene already has two
meshes sharing the short name "twin" under different groups, which is exactly
the case that made mesh matching need a tie-break, so members are resolved to
full paths before they are written.

A set can also hold components rather than objects. Blender has no equivalent
for "these three faces", so such a set is reported rather than half-built.
"""
from __future__ import absolute_import

import maya.cmds as cmds

from .constants import EXCLUDED_SET_NAMES
from .mayautils import node_label, unique, without_namespace


def scene_selection_sets():
    """Object sets worth transferring, in scene order."""
    found = []
    for node in cmds.ls(type="objectSet", long=False) or []:
        # shadingEngine inherits from objectSet; nodeType tells them apart.
        try:
            if cmds.nodeType(node) != "objectSet":
                continue
        except Exception:
            continue
        if node in EXCLUDED_SET_NAMES:
            continue
        found.append(node)
    return unique(found)


def selection_set_record(node, warnings=None):
    raw = cmds.sets(node, query=True) or []
    objects = []
    components = 0
    for member in raw:
        if "." in member:
            components += 1
            continue
        # Short names are ambiguous when two meshes share one; resolve them.
        resolved = cmds.ls(member, long=True) or []
        objects.extend(resolved)
    if components and warnings is not None:
        warnings.append(
            'Set "{0}" holds {1} component selection(s), which Blender has '
            "no equivalent for; only its objects were transferred.".format(
                node, components
            )
        )
    return {
        "set": without_namespace(node_label(node)),
        "set_full_name": node_label(node),
        "members": unique(objects),
        "component_members": components,
    }


def selection_set_records(nodes, warnings=None):
    records = []
    for node in nodes:
        record = selection_set_record(node, warnings)
        # A set with nothing but components would arrive as an empty
        # collection, which says less than the warning already does.
        if record["members"]:
            records.append(record)
    return records


def scene_display_layers():
    layers = []
    for node in cmds.ls(type="displayLayer", long=False) or []:
        if node in EXCLUDED_SET_NAMES:
            continue
        layers.append(node)
    return unique(layers)


def display_layer_record(node):
    try:
        members = cmds.editDisplayLayerMembers(
            node, query=True, fullNames=True
        ) or []
    except Exception:
        members = []
    # Members come back as a mix of transforms and shapes; the transform is
    # what Blender has an object for.
    transforms = []
    for member in members:
        if cmds.nodeType(member) == "transform":
            transforms.append(member)
            continue
        parents = cmds.listRelatives(member, parent=True, fullPath=True) or []
        if parents:
            transforms.append(parents[0])
    return {
        "layer": without_namespace(node_label(node)),
        "layer_full_name": node_label(node),
        "members": unique(transforms),
        "visible": bool(_attr(node, "visibility", True)),
        # 0 normal, 1 template, 2 reference. Both of the latter mean the
        # objects are not meant to be selected.
        "display_type": int(_attr(node, "displayType", 0) or 0),
    }


def display_layer_records(nodes):
    return [display_layer_record(node) for node in nodes]


def _attr(node, attr, fallback):
    try:
        return cmds.getAttr(node + "." + attr)
    except Exception:
        return fallback
