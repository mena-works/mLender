# -*- coding: utf-8 -*-
"""Defensive wrappers around maya.cmds plus small value helpers.

Every Maya query here swallows exceptions and falls back to a sane default.
Scene content is user authored, so a missing attribute or an unreadable node
must never abort a whole export.
"""
from __future__ import absolute_import

import os

import maya.cmds as cmds
import maya.mel as mel

from .constants import (
    COLOR_MANAGEMENT_FLAGS,
    MAYA_RESOURCES_TOKEN,
    METERS_PER_LINEAR_UNIT,
)


def attr_exists(node, attr):
    try:
        return cmds.attributeQuery(attr, node=node, exists=True)
    except Exception:
        return False


def node_type(node):
    try:
        return cmds.nodeType(node)
    except Exception:
        return ""


def node_label(node):
    """Return the short node name from a full DAG path."""
    return str(node or "").split("|")[-1]


def without_namespace(value):
    return str(value or "").rsplit(":", 1)[-1]


def namespace_of(value):
    """The namespace a node sits in, or an empty string.

    A referenced asset carries its namespace as the only thing telling it
    apart from another reference of the same file: two references of one asset
    give two meshes both called ``body``, in groups both called ``assetGrp``.
    Stripping it left a scene of ``body.001``, ``body.002`` and no way to say
    which reference any of them came from.
    """
    tail = str(value or "").split("|")[-1]
    if ":" not in tail:
        return ""
    return tail.rsplit(":", 1)[0]


def unique(items):
    """Order preserving de-duplication."""
    result = []
    seen = set()
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result


def raw_attr_value(plug):
    """Read a plug into a JSON friendly value, unwrapping Maya's nesting."""
    try:
        value = cmds.getAttr(plug)
    except Exception:
        return None
    while isinstance(value, (list, tuple)) and len(value) == 1:
        value = value[0]
    if isinstance(value, (list, tuple)):
        result = []
        for item in value:
            try:
                result.append(float(item))
            except Exception:
                result.append(str(item))
        return result
    if isinstance(value, bool):
        return bool(value)
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, (str, bytes)):
        return str(value)
    return None


def plug_value(plug):
    """Read a plug as a numeric value; strings are dropped."""
    try:
        value = cmds.getAttr(plug)
    except Exception:
        return None
    while isinstance(value, (list, tuple)) and len(value) == 1:
        value = value[0]
    if isinstance(value, (list, tuple)):
        return [float(item) for item in value]
    if isinstance(value, bool):
        return bool(value)
    if isinstance(value, (int, float)):
        return float(value)
    return None


def enum_attr_label(node, attr, value):
    """Resolve an enum attribute's integer value to its authored label.

    Enum indices are not stable across Redshift versions, so downstream code
    matches on the label text rather than on the raw number.
    """
    try:
        definitions = cmds.attributeQuery(attr, node=node, listEnum=True) or []
    except Exception:
        return ""
    if not definitions or not isinstance(value, (int, float)):
        return ""

    target = int(value)
    current_value = 0
    for token in str(definitions[0]).split(":"):
        label = token
        if "=" in token:
            label, raw_value = token.rsplit("=", 1)
            try:
                current_value = int(raw_value)
            except Exception:
                pass
        if current_value == target:
            return label
        current_value += 1
    return ""


def first_existing_attr(node, aliases):
    """Return (value, attr, enum_label) for the first alias present on node."""
    for attr in aliases:
        if not attr_exists(node, attr):
            continue
        value = raw_attr_value(node + "." + attr)
        return value, attr, enum_attr_label(node, attr, value)
    return None, "", ""


def user_attributes(node):
    """Attributes the user added to a node, as a JSON friendly dict.

    Pipelines hang their own data off Maya nodes -- an asset id, a variant
    name, a LOD level -- and none of it reached Blender, which has exactly the
    same idea in custom properties.

    Two things measured rather than assumed. A compound attribute is listed
    together with its children, so a double3 appears four times over; only the
    parent is kept, recognised by the children having one. And an enum reads
    back as an integer, so the label is stored instead: this codebase already
    matches enums on their label because the indices are not stable across
    versions.
    """
    if not node:
        return {}
    try:
        names = cmds.listAttr(node, userDefined=True) or []
    except Exception:
        return {}

    found = {}
    for name in names:
        try:
            if cmds.attributeQuery(name, node=node, listParent=True):
                # A child of a compound; the parent already carries the value.
                continue
        except Exception:
            pass
        plug = node + "." + name
        try:
            attr_type = cmds.getAttr(plug, type=True)
        except Exception:
            continue
        value = raw_attr_value(plug)
        if value is None:
            continue
        if attr_type == "enum":
            label = enum_attr_label(node, name, value)
            value = label if label else value
        found[name] = value
    return found


def node_visible(node):
    if not node or not attr_exists(node, "visibility"):
        return True
    try:
        return bool(cmds.getAttr(node + ".visibility"))
    except Exception:
        return True


def parent_of(node):
    """Return the full path of a shape's transform, or an empty string."""
    return (cmds.listRelatives(node, parent=True, fullPath=True) or [""])[0]


def parents_of(node):
    """Every transform a shape hangs under, in Maya's order.

    An instanced shape has more than one. Reading only the first dropped the
    instances from both the FBX selection and the JSON, so they did not arrive
    in Blender at all: no geometry, no object, no warning.
    """
    return [
        path for path in
        (cmds.listRelatives(node, allParents=True, fullPath=True) or [])
        if path
    ]


def world_matrix(transform):
    if not transform:
        return [
            1.0, 0.0, 0.0, 0.0,
            0.0, 1.0, 0.0, 0.0,
            0.0, 0.0, 1.0, 0.0,
            0.0, 0.0, 0.0, 1.0,
        ]
    try:
        return [
            float(item)
            for item in cmds.xform(
                transform,
                query=True,
                worldSpace=True,
                matrix=True,
            )
        ]
    except Exception:
        return []


def xform_vector(
    transform,
    translation=False,
    rotation=False,
    scale=False,
    default=None,
):
    default = list(default or (0.0, 0.0, 0.0))
    if not transform:
        return default
    kwargs = {
        "query": True,
        "worldSpace": True,
    }
    if translation:
        kwargs["translation"] = True
    elif rotation:
        kwargs["rotation"] = True
    elif scale:
        # Scale is read in local space; world space scale is not queryable
        # the same way and the light size logic expects the local value.
        kwargs["scale"] = True
        kwargs.pop("worldSpace", None)
        kwargs["relative"] = True
    try:
        return [float(item) for item in cmds.xform(transform, **kwargs)]
    except Exception:
        return default


def current_frame():
    try:
        return float(cmds.currentTime(query=True))
    except Exception:
        return 0.0


def maya_linear_unit():
    try:
        return str(cmds.currentUnit(query=True, linear=True) or "cm")
    except Exception:
        return "cm"


def meters_per_maya_unit():
    return METERS_PER_LINEAR_UNIT.get(maya_linear_unit(), 0.01)


def number(value, default=0.0):
    try:
        return float(value)
    except Exception:
        return float(default)


def invert_color(value):
    if isinstance(value, (list, tuple)):
        inverted = [1.0 - float(item) for item in value[:3]]
        return inverted + [1.0]
    return 1.0 - float(value)


def absolute_user_path(path):
    """Expand user/env tokens and return an absolute OS path."""
    return os.path.abspath(os.path.expandvars(os.path.expanduser(str(path))))


def maya_path(path):
    """Absolute path with forward slashes, the form written into JSON."""
    return os.path.abspath(path).replace("\\", "/")


def mel_path(path):
    return os.path.abspath(path).replace("\\", "/").replace('"', '\\"')


def color_management_info():
    """Maya's colour management settings, with the config path resolved.

    Maya hands the config path back with a <MAYA_RESOURCES> token in it, which
    means nothing outside Maya. It is expanded here so the importer can name a
    real file when it has to tell the user their Blender config cannot supply
    the same view transform.
    """
    result = {}
    for semantic, flag in COLOR_MANAGEMENT_FLAGS.items():
        try:
            value = cmds.colorManagementPrefs(query=True, **{flag: True})
        except Exception:
            continue
        if isinstance(value, bool):
            result[semantic] = bool(value)
        elif isinstance(value, (str, bytes)):
            result[semantic] = str(value)
    result["config_path"] = _resolve_maya_resources(
        result.get("config_path", "")
    )
    return result


def _resolve_maya_resources(path):
    path = str(path or "")
    if MAYA_RESOURCES_TOKEN not in path:
        return path.replace("\\", "/")
    root = os.environ.get("MAYA_LOCATION", "")
    if not root:
        return path.replace("\\", "/")
    resolved = path.replace(MAYA_RESOURCES_TOKEN, os.path.join(root, "resources"))
    return resolved.replace("\\", "/")


def mel_eval_safe(command):
    """Run a MEL command, ignoring failures from unavailable FBX options."""
    try:
        mel.eval(command)
    except Exception:
        pass
