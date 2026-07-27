# -*- coding: utf-8 -*-
"""Light discovery and current-frame light records.

Lights are never written into the FBX. Their values are read at the current
frame and shipped through JSON so the importer can rebuild native Blender
lights instead of importing FBX light approximations.
"""
from __future__ import absolute_import

import maya.cmds as cmds

from .constants import (
    EXCLUDED_LIGHT_NODE_TYPES,
    LIGHT_ATTR_ALIASES,
    LIGHT_COLOR_TEXTURE_ATTRS,
    LIGHT_DOME_TEXTURE_ATTRS,
    LIGHT_NODE_TYPES,
)
from .mayautils import (
    current_frame,
    first_existing_attr,
    node_label,
    node_type,
    node_visible,
    number,
    parent_of,
    unique,
    without_namespace,
    world_matrix,
    xform_vector,
)
from .textures import file_from_attrs, texture_from_attrs


def scene_light_shapes():
    """Every light shape in the scene, found three different ways.

    The known type list misses Redshift builds whose node names differ, so a
    heuristic pass over transform shapes catches anything with "light" in its
    node type. Requiring a parent transform excludes non-DAG nodes such as
    light linkers.
    """
    result = list(cmds.ls(lights=True, long=True) or [])

    for light_type in LIGHT_NODE_TYPES:
        try:
            result.extend(cmds.ls(type=light_type, long=True) or [])
        except Exception:
            pass

    for transform in cmds.ls(type="transform", long=True) or []:
        for shape in cmds.listRelatives(
            transform,
            shapes=True,
            fullPath=True,
        ) or []:
            if "light" in node_type(shape).lower():
                result.append(shape)

    return [
        shape for shape in unique(result)
        if parent_of(shape)
        and node_type(shape) not in EXCLUDED_LIGHT_NODE_TYPES
    ]


def light_record(light_shape):
    transform = parent_of(light_shape)
    source_attrs = {}
    enum_labels = {}
    values = {}

    for semantic, aliases in LIGHT_ATTR_ALIASES.items():
        value, attr, enum_label = first_existing_attr(light_shape, aliases)
        if attr:
            source_attrs[semantic] = attr
        if enum_label:
            enum_labels[semantic] = enum_label
        if value is not None:
            values[semantic] = value

    enabled = node_visible(transform) and node_visible(light_shape)
    if "on" in values:
        enabled = enabled and bool(values["on"])

    intensity = number(values.get("intensity"), 1.0)
    exposure = number(values.get("exposure"), 0.0)
    color = values.get("color")
    if not isinstance(color, (list, tuple)):
        color = [1.0, 1.0, 1.0]

    light_node_type = node_type(light_shape)
    return {
        "name": without_namespace(node_label(transform or light_shape)),
        "full_name": node_label(transform or light_shape),
        "shape": without_namespace(node_label(light_shape)),
        "shape_full_name": node_label(light_shape),
        "node_type": light_node_type,
        "light_kind": resolve_light_kind(
            light_node_type,
            values.get("light_type"),
            enum_labels.get("light_type"),
        ),
        "area_shape": resolve_area_shape(
            values.get("area_shape"),
            enum_labels.get("area_shape"),
        ),
        "enabled": enabled,
        "color": [float(item) for item in color[:3]],
        "intensity": intensity,
        "exposure": exposure,
        # Redshift treats exposure as a photographic stop on top of intensity.
        "effective_intensity": intensity * (2.0 ** exposure),
        "parameters": values,
        "source_attrs": source_attrs,
        "enum_labels": enum_labels,
        "color_texture": texture_from_attrs(
            light_shape,
            LIGHT_COLOR_TEXTURE_ATTRS,
        ),
        "dome_texture": file_from_attrs(
            light_shape,
            LIGHT_DOME_TEXTURE_ATTRS,
        ),
        "ies_profile": file_from_attrs(
            light_shape,
            LIGHT_ATTR_ALIASES["ies_profile"],
        ),
        "transform": {
            "world_matrix": world_matrix(transform),
            "translation": xform_vector(
                transform,
                translation=True,
                default=(0.0, 0.0, 0.0),
            ),
            "rotation_degrees": xform_vector(
                transform,
                rotation=True,
                default=(0.0, 0.0, 0.0),
            ),
            "scale": xform_vector(
                transform,
                scale=True,
                default=(1.0, 1.0, 1.0),
            ),
        },
        "frame": current_frame(),
    }


def light_sample(light_shape):
    """The values worth capturing per frame: where it is and how bright.

    ``effective_intensity`` is folded here exactly as the static record folds
    it, so the importer runs the same measured energy conversion on a sample
    as it does on the record.
    """
    transform = parent_of(light_shape)
    intensity, _attr, _label = first_existing_attr(
        light_shape, LIGHT_ATTR_ALIASES["intensity"]
    )
    exposure, _e_attr, _e_label = first_existing_attr(
        light_shape, LIGHT_ATTR_ALIASES["exposure"]
    )
    color, _c_attr, _c_label = first_existing_attr(
        light_shape, LIGHT_ATTR_ALIASES["color"]
    )
    intensity = number(intensity, 1.0)
    exposure = number(exposure, 0.0)
    if not isinstance(color, (list, tuple)):
        color = [1.0, 1.0, 1.0]
    return {
        "matrix": world_matrix(transform),
        "scale": xform_vector(
            transform, scale=True, default=(1.0, 1.0, 1.0)
        ),
        "intensity": intensity,
        "exposure": exposure,
        "effective_intensity": intensity * (2.0 ** exposure),
        "color": [float(item) for item in color[:3]],
    }


def scene_uses_light_linking():
    """Whether any light link has been broken anywhere in the scene.

    Maya records breaks in the lightLinker's ``ignore`` array, so an empty
    array means every light lights everything and the per-light query can be
    skipped entirely. That query is not cheap on a large scene.
    """
    for linker in cmds.ls(type="lightLinker") or []:
        try:
            if cmds.getAttr(linker + ".ignore", multiIndices=True):
                return True
        except Exception:
            continue
    return False


def linked_mesh_names(light_transform, mesh_lookup):
    """Exported meshes this light actually lights, or None if unanswerable.

    Maya answers with a mix of shapes, transforms and shading groups, so the
    result is filtered through a lookup of the meshes actually being exported
    and reported using the names the importer will see.

    The lights must be in defaultLightSet for this query to mean anything;
    Maya puts them there itself when they are created in a scene.
    """
    try:
        linked = cmds.lightlink(query=True, light=light_transform) or []
    except Exception:
        return None
    if not linked:
        # The query answers nothing for a light outside defaultLightSet. Read
        # that as unanswerable, not as "lights nothing": a light that really
        # lights nothing is vanishingly rare, and the two mistakes are not
        # equally bad. Restricting wrongly makes the light vanish in Blender;
        # not restricting only misses a restriction that was probably absent.
        return None
    names = set()
    for item in linked:
        mesh = mesh_lookup.get(node_label(item))
        if mesh:
            names.add(mesh)
    return sorted(names)


def resolve_light_kind(light_node_type, value, enum_label):
    """Reduce a Maya/Redshift light to one of the kinds Blender can rebuild.

    Enum labels are matched before raw indices because Redshift reorders its
    lightType enum between versions.
    """
    label = str(enum_label or "").lower()
    node_lower = str(light_node_type or "").lower()
    combined = label + " " + node_lower
    if "dome" in combined:
        return "DOME"
    if "ies" in combined or "photometric" in combined:
        return "IES"
    if "direction" in combined or "infinite" in combined or "sun" in combined:
        return "SUN"
    if "spot" in combined:
        return "SPOT"
    if "point" in combined or "volume" in combined or "ambient" in combined:
        return "POINT"
    if "area" in combined or "portal" in combined:
        return "AREA"
    if "redshiftphysicallight" in node_lower and isinstance(value, (int, float)):
        return {
            0: "AREA",
            1: "POINT",
            2: "SPOT",
            3: "SUN",
        }.get(int(value), "AREA")
    return "AREA"


def resolve_area_shape(value, enum_label):
    """Resolve an area light shape from an enum label, a string or an index.

    Redshift stores the shape as an enum. Arnold stores it as a plain string
    in aiTranslator ("", "quad", "disk", "cylinder"), where empty means the
    default quad, so a string value is treated as the label.
    """
    label = str(enum_label or "")
    if not label and isinstance(value, str):
        label = value
    label = label.lower()

    if "rect" in label or "quad" in label:
        return "RECTANGLE"
    if "disc" in label or "disk" in label:
        return "DISK"
    if "sphere" in label:
        return "SPHERE"
    if "cylinder" in label:
        return "CYLINDER"
    if "mesh" in label:
        return "MESH"
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return "RECTANGLE"
    return {
        0: "RECTANGLE",
        1: "DISK",
        2: "SPHERE",
        3: "CYLINDER",
        4: "MESH",
    }.get(int(value), "RECTANGLE")
