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
    CORRECTION_CONNECTED_INPUTS,
    CORRECTION_IGNORED_NODE_TYPES,
    CORRECTION_NODE_ATTRS,
    CORRECTION_OPERAND_INPUTS,
    MULTIPLY_DIVIDE_OPERATIONS,
    REMAP_INTERPOLATIONS,
    REMAP_RAMP_ATTR,
    REMAP_RAMP_CHILDREN,
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
    # listHistory repeats the node it started from, and a repeat would record
    # the same correction node twice and apply its maths twice.
    candidates = unique(candidates)
    for node in candidates:
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
            corrections, unsupported = correction_chain(candidates, node)
            if corrections:
                record["corrections"] = corrections
            if unsupported:
                record["unsupported_corrections"] = unsupported
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


def correction_chain(candidates, texture_node):
    """Correction nodes between the file node and the shader, in apply order.

    Returns the rebuildable ones and, separately, the node types that have no
    Blender equivalent. Reporting the second list matters: before this, a
    remapValue or a colour blend between the file and the shader was stepped
    straight past and the texture arrived uncorrected with nothing said.

    ``candidates`` runs from the shader end towards the texture, so the result
    is reversed; the importer rebuilds starting at the image.
    """
    chain = []
    unsupported = []
    for node in candidates:
        if node == texture_node:
            break
        kind = node_type(node)
        if kind in CORRECTION_NODE_ATTRS:
            chain.append(correction_record(node, kind))
        elif kind and kind not in CORRECTION_IGNORED_NODE_TYPES:
            unsupported.append({"node": node_label(node), "node_type": kind})
    chain.reverse()
    return chain, unsupported


def correction_record(node, kind):
    """Read one correction node's settings into a JSON friendly record."""
    parameters = {}
    for semantic, attr in CORRECTION_NODE_ATTRS[kind].items():
        if not attr_exists(node, attr):
            continue
        value = plug_value(node + "." + attr)
        if value is not None:
            parameters[semantic] = value

    operand = CORRECTION_OPERAND_INPUTS.get(kind)
    if operand:
        semantic, attrs = operand
        value = free_input_value(node, attrs)
        if value is not None:
            parameters[semantic] = value

    connected = CORRECTION_CONNECTED_INPUTS.get(kind)
    if connected:
        semantic, attrs = connected
        name = connected_input_name(node, attrs)
        if name:
            parameters[semantic] = name

    if kind == "multiplyDivide":
        parameters["operation_name"] = MULTIPLY_DIVIDE_OPERATIONS.get(
            int(parameters.get("operation") or 0), "none"
        )

    if kind == "remapValue":
        ramp = remap_ramp(node)
        if ramp:
            parameters["ramp"] = ramp

    return {
        "type": kind,
        "node": node_label(node),
        "parameters": parameters,
    }


def connected_input_name(node, attrs):
    """Which of a node's inputs the upstream network actually arrived on.

    blendColors is not symmetric, so rebuilding it needs to know whether the
    texture came in on color1 or color2.
    """
    for attr in attrs:
        if not attr_exists(node, attr):
            continue
        if cmds.listConnections(
            node + "." + attr, source=True, destination=False
        ):
            return attr
    return ""


def remap_ramp(node):
    """Read a remapValue curve into a plain list of stops.

    The ramp is the whole point of the node; without it the transfer can only
    reproduce a linear remap. Each stop carries its own interpolation in Maya,
    which Blender states once for the whole ramp, so both are exported and the
    importer decides.
    """
    try:
        indices = cmds.getAttr(node + "." + REMAP_RAMP_ATTR, multiIndices=True)
    except Exception:
        return []
    stops = []
    for index in indices or []:
        base = "{0}.{1}[{2}]".format(node, REMAP_RAMP_ATTR, index)
        stop = {}
        for semantic, child in REMAP_RAMP_CHILDREN.items():
            value = plug_value(base + "." + child)
            if value is None:
                continue
            if semantic == "interpolation":
                stop[semantic] = REMAP_INTERPOLATIONS.get(int(value), "linear")
            else:
                stop[semantic] = float(value)
        if "position" in stop and "value" in stop:
            stops.append(stop)
    stops.sort(key=lambda item: item["position"])
    return stops


def free_input_value(node, attrs):
    """Value of the first input carrying no upstream connection.

    On a two input maths node the texture may be wired into either side, so
    the operand is whichever one the artist left free.
    """
    for attr in attrs:
        if not attr_exists(node, attr):
            continue
        connected = cmds.listConnections(
            node + "." + attr, source=True, destination=False
        )
        if connected:
            continue
        return plug_value(node + "." + attr)
    return None


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
