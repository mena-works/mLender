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
    PLACEMENT_3D_NODE_TYPE,
    PROJECTION_IMAGE_ATTR,
    PROJECTION_NODE_TYPE,
    PROJECTION_PLACEMENT_ATTR,
    PROJECTION_TYPES,
    PROJECTION_TYPE_ATTR,
    RAMP_TEXTURE_ENTRIES,
    RAMP_TEXTURE_INTERPOLATIONS,
    RAMP_TEXTURE_TYPE,
    RAMP_TEXTURE_TYPES,
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
    world_matrix,
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
    # A file behind a projection is not UV mapped, so handing its path over
    # would produce a wrong result that looks like a right one: measured, a
    # planar projected texture arrived wrapped on the UVs with nothing said.
    # The walk stops here and the record describes the projection instead.
    projection = projection_info(candidates)
    if projection:
        record = {
            "path": "",
            "node": node_label(source_node),
            "node_type": node_type(source_node),
            "source_plug": source_plug,
            "unsupported_network": True,
            "projection": projection,
        }
        image = projection_image(projection["node_path"])
        if image:
            record["projection"]["image"] = image
        return record

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
    record = {
        "path": "",
        "node": node_label(source_node),
        "node_type": node_type(source_node),
        "source_plug": source_plug,
        "unsupported_network": True,
    }
    # A ramp texture is a gradient, and Blender has a Color Ramp; baking it to
    # an image loses resolution and editability for nothing. The stops travel
    # so the importer can rebuild it, and the record stays marked unsupported
    # so a type this cannot reproduce still falls back to the bake.
    ramp = texture_ramp(source_node)
    if ramp:
        record["ramp"] = ramp
    return record


def projection_info(candidates):
    """The projection node between the shader and its file, if there is one.

    ``candidates`` runs from the shader end towards the texture, so the first
    projection found is the one actually driving the channel.

    The place3dTexture comes with it: a projection has no position of its own,
    it reads the placement's inverse world matrix, and without that matrix the
    other side has nothing to project from.
    """
    for node in candidates:
        if node_type(node) != PROJECTION_NODE_TYPE:
            continue
        record = {
            "node": node_label(node),
            "node_path": node,
            "type": _enum_label(
                node, PROJECTION_TYPE_ATTR, PROJECTION_TYPES
            ),
        }
        placement = projection_placement(node)
        if placement:
            record.update(placement)
        return record
    return {}


def projection_placement(node):
    """The place3dTexture feeding a projection, as a name and a world matrix."""
    try:
        sources = cmds.listConnections(
            node + "." + PROJECTION_PLACEMENT_ATTR,
            source=True, destination=False,
        ) or []
    except Exception:
        return {}
    for source in sources:
        resolved = (cmds.ls(source, long=True) or [source])[0]
        if node_type(resolved) != PLACEMENT_3D_NODE_TYPE:
            continue
        return {
            "placement": node_label(resolved),
            "placement_path": resolved,
            "world_matrix": world_matrix(resolved),
        }
    return {}


def projection_image(node):
    """The file the projection projects, as an ordinary texture record.

    The path still travels: the image itself is a normal texture, it is only
    the mapping that differs, and re-reading it on the other side would be
    the same file.
    """
    try:
        sources = cmds.listConnections(
            node + "." + PROJECTION_IMAGE_ATTR,
            source=True, destination=False,
        ) or []
    except Exception:
        return {}
    for source in sources:
        resolved = (cmds.ls(source, long=True) or [source])[0]
        path = texture_path_from_node(resolved)
        if not path:
            continue
        udim = udim_texture_info(resolved, path)
        image = {
            "path": maya_path(udim.get("pattern") or path),
            "original_path": maya_path(path),
            "node": node_label(resolved),
            "color_space": texture_color_space(resolved),
        }
        if udim.get("is_udim"):
            image["udim"] = True
            image["udim_pattern"] = maya_path(udim["pattern"])
        return image
    return {}


def texture_ramp(node):
    """A ramp texture node as stops plus its type, or None.

    Unlike a rampShader, the interpolation here belongs to the node rather
    than to each stop, and the entry list of a freshly created node is empty
    rather than holding defaults.
    """
    if node_type(node) != RAMP_TEXTURE_TYPE:
        return {}
    try:
        indices = cmds.getAttr(
            node + "." + RAMP_TEXTURE_ENTRIES, multiIndices=True
        ) or []
    except Exception:
        return {}

    entries = []
    for index in indices:
        base = "{0}.{1}[{2}]".format(node, RAMP_TEXTURE_ENTRIES, index)
        try:
            position = float(cmds.getAttr(base + ".position"))
            raw = cmds.getAttr(base + ".color")
            values = list(raw[0]) if isinstance(raw, list) else list(raw)
        except Exception:
            continue
        entries.append({
            "position": position,
            "color": [float(item) for item in values[:3]],
        })
    if len(entries) < 2:
        return {}
    # Maya returns the indices in creation order, so an edited ramp comes
    # back shuffled; sorting is what makes it the gradient the artist drew.
    entries.sort(key=lambda item: item["position"])

    return {
        "type": _enum_label(node, "type", RAMP_TEXTURE_TYPES),
        "interpolation": _enum_label(
            node, "interpolation", RAMP_TEXTURE_INTERPOLATIONS
        ),
        "entries": entries,
    }


def _enum_label(node, attr, labels):
    if not attr_exists(node, attr):
        return labels[0]
    try:
        index = int(cmds.getAttr(node + "." + attr))
    except Exception:
        return labels[0]
    if 0 <= index < len(labels):
        return labels[index]
    return labels[0]


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
