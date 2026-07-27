# -*- coding: utf-8 -*-
"""Texture discovery across Maya shading networks.

A material input is rarely wired straight to a file node; colour correction,
bump and utility nodes sit in between. These helpers walk the upstream history
and return the first resolvable texture file, which is the closest thing to
the network's result that can be rebuilt in Blender without baking.
"""
from __future__ import absolute_import

import os
import re

import maya.cmds as cmds

from .constants import (
    BUMP_DEPTH_ATTR,
    BUMP_INTERP_ATTR,
    BUMP_NODE_TYPES,
    PLACEMENT_NODE_TYPE,
    PLACEMENT_NUMERIC_ATTRS,
    TEXTURE_PATH_ATTRS,
    UDIM_FIRST_TILE,
    UDIM_TILING_MODE,
    UDIM_TOKEN,
    UDIM_TOKEN_PATTERN,
)
from .mayautils import (
    absolute_user_path,
    attr_exists,
    first_existing_attr,
    plug_value,
    maya_path,
    node_label,
    node_type,
    raw_attr_value,
    unique,
)


def texture_from_plug(plug):
    """Return a texture record for a plug, or None when nothing is connected.

    When the plug is connected but no file path can be found anywhere upstream
    the record is still returned with an empty path and ``unsupported_network``
    set, so the importer can fall back to the material's flat value.
    """
    source_plugs = cmds.listConnections(
        plug,
        source=True,
        destination=False,
        plugs=True,
    ) or []
    if not source_plugs:
        return None

    source_plug = source_plugs[0]
    source_node = source_plug.split(".", 1)[0]
    candidates = [source_node]
    candidates.extend(cmds.listHistory(source_node, pruneDagObjects=True) or [])
    for node in unique(candidates):
        path = texture_path_from_node(node)
        if path:
            udim = udim_texture_info(node, path)
            record = {
                "path": maya_path(udim.get("pattern") or path),
                "original_path": maya_path(path),
                "node": node_label(node),
                "node_type": node_type(node),
                "source_plug": source_plug,
                "color_space": texture_color_space(node),
            }
            if udim.get("is_udim"):
                record["udim"] = True
                record["udim_pattern"] = maya_path(udim["pattern"])
                record["udim_mode"] = udim.get("mode") or "detected"
            placement = placement_info(node)
            if placement:
                record["placement"] = placement
            bump = bump_info(candidates)
            if bump:
                record["bump"] = bump
            return record
    return {
        "path": "",
        "node": node_label(source_node),
        "node_type": node_type(source_node),
        "source_plug": source_plug,
        "unsupported_network": True,
    }


def placement_info(texture_node):
    """Read the place2dTexture feeding a file node, if there is one.

    Maya expresses tiling as repeat/offset/rotate on a separate node, which the
    upstream walk would otherwise step straight past. Dropping it silently
    turns a texture tiled four times into a single stretched one.
    """
    placements = [
        node for node in (
            cmds.listConnections(texture_node, source=True, destination=False)
            or []
        )
        if node_type(node) == PLACEMENT_NODE_TYPE
    ]
    if not placements:
        return None

    placement = placements[0]
    values = {}
    for semantic, attr in PLACEMENT_NUMERIC_ATTRS.items():
        if not attr_exists(placement, attr):
            continue
        value = plug_value(placement + "." + attr)
        if value is not None:
            values[semantic] = value
    if not values:
        return None
    values["node"] = node_label(placement)
    return values


def bump_info(candidates):
    """Strength and mode of a bump2d sitting between the file and the shader."""
    for node in candidates:
        if node_type(node) not in BUMP_NODE_TYPES:
            continue
        depth = plug_value(node + "." + BUMP_DEPTH_ATTR)
        _value, _attr, label = first_existing_attr(node, (BUMP_INTERP_ATTR,))
        return {
            "node": node_label(node),
            "depth": 1.0 if depth is None else float(depth),
            # Bump : Tangent Space Normals : Object Space Normals
            "interpretation": str(label or ""),
        }
    return None


def udim_texture_info(node, path):
    """Detect a UDIM sequence and return the pattern to ship to Blender.

    Maya is asked directly rather than guessed at: uvTilingMode says whether
    the file node is tiled, and computedFileTextureNamePattern is the pattern
    Maya itself resolved. Only if neither is conclusive does the tile number
    get substituted out of the file name.
    """
    original_path = absolute_user_path(path)

    tiling_mode = 0
    if attr_exists(node, "uvTilingMode"):
        try:
            tiling_mode = int(cmds.getAttr(node + ".uvTilingMode"))
        except Exception:
            tiling_mode = 0

    pattern = ""
    if attr_exists(node, "computedFileTextureNamePattern"):
        try:
            pattern = cmds.getAttr(
                node + ".computedFileTextureNamePattern"
            ) or ""
        except Exception:
            pattern = ""
    pattern = absolute_user_path(pattern or original_path)
    pattern, has_token = normalize_udim_token(pattern)

    # uvTilingMode 3 is Maya's UDIM mode.
    if not has_token and tiling_mode == UDIM_TILING_MODE:
        pattern = replace_udim_tile_number(pattern)
        has_token = UDIM_TOKEN in pattern

    return {
        "is_udim": bool(has_token or tiling_mode == UDIM_TILING_MODE),
        "pattern": pattern if has_token else original_path,
        "mode": (
            "maya_uv_tiling_mode"
            if tiling_mode == UDIM_TILING_MODE
            else "path_token"
        ),
    }


def normalize_udim_token(path):
    """Collapse the UDIM spellings different tools write into one token."""
    normalized = re.sub(UDIM_TOKEN_PATTERN, UDIM_TOKEN, str(path))
    return normalized, UDIM_TOKEN in normalized


def replace_udim_tile_number(path):
    """Swap a concrete tile number in the file name for the UDIM token.

    Only the last four digit run of 1001 or above is treated as a tile, so
    version numbers and dates earlier in the name survive.
    """
    folder, filename = os.path.split(path)
    matches = [
        match
        for match in re.finditer(r"(?<!\d)([1-9]\d{3})(?!\d)", filename)
        if int(match.group(1)) >= UDIM_FIRST_TILE
    ]
    if not matches:
        return path
    match = matches[-1]
    filename = filename[: match.start()] + UDIM_TOKEN + filename[match.end():]
    return os.path.join(folder, filename)


def texture_path_from_node(node):
    for attr in TEXTURE_PATH_ATTRS:
        if not attr_exists(node, attr):
            continue
        try:
            value = cmds.getAttr(node + "." + attr)
        except Exception:
            continue
        if isinstance(value, (str, bytes)) and value:
            return absolute_user_path(value)
    return ""


def texture_color_space(node):
    if not attr_exists(node, "colorSpace"):
        return ""
    try:
        return str(cmds.getAttr(node + ".colorSpace") or "")
    except Exception:
        return ""


def texture_from_attrs(node, aliases):
    """First connected texture found across a tuple of candidate attributes."""
    for attr in aliases:
        if not attr_exists(node, attr):
            continue
        texture = texture_from_plug(node + "." + attr)
        if texture and texture.get("path"):
            return texture
    return None


def file_from_attrs(node, aliases):
    """Resolve a file resource that may be a connection or a plain string.

    Dome HDRs and IES profiles are stored as string attributes on some nodes
    and as texture connections on others.
    """
    for attr in aliases:
        if not attr_exists(node, attr):
            continue
        plug = node + "." + attr
        texture = texture_from_plug(plug)
        if texture and texture.get("path"):
            return texture
        value = raw_attr_value(plug)
        if isinstance(value, str) and value:
            path = absolute_user_path(value)
            return {
                "path": maya_path(path),
                "maya_attr": attr,
                "exists": os.path.isfile(path),
            }
    return None
