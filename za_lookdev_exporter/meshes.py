# -*- coding: utf-8 -*-
"""Scene mesh discovery and per-mesh material records."""
from __future__ import absolute_import

import maya.cmds as cmds

from .constants import SUPPORTED_SHADER_TYPES
from .mayautils import (
    node_label,
    node_type,
    parent_of,
    unique,
    without_namespace,
)
from .shaders import shader_channels


def scene_mesh_shapes():
    """Every renderable mesh shape in the scene.

    Intermediate objects belong to construction history and parentless shapes
    cannot be exported, so both are skipped.
    """
    result = []
    for shape in cmds.ls(type="mesh", long=True) or []:
        try:
            if cmds.getAttr(shape + ".intermediateObject"):
                continue
        except Exception:
            pass
        if not parent_of(shape):
            continue
        result.append(shape)
    return unique(result)


def mesh_transforms(mesh_shapes):
    """Unique transform paths for a list of mesh shapes, for FBX selection."""
    transforms = unique([parent_of(shape) for shape in mesh_shapes])
    return [item for item in transforms if item]


def mesh_record(mesh_shape):
    transform = parent_of(mesh_shape)
    full_name = node_label(transform or mesh_shape)
    return {
        "mesh": without_namespace(full_name),
        "mesh_full_name": full_name,
        "mesh_path": transform,
        "shape": node_label(mesh_shape),
        "shape_path": mesh_shape,
        "materials": mesh_materials(mesh_shape),
    }


def mesh_materials(mesh_shape):
    result = []
    seen = set()
    shading_engines = unique(
        cmds.listConnections(mesh_shape, type="shadingEngine") or []
    )
    for shading_engine in shading_engines:
        shaders = cmds.listConnections(
            shading_engine + ".surfaceShader",
            source=True,
            destination=False,
        ) or []
        for shader in unique(shaders):
            key = (shading_engine, shader)
            if key in seen:
                continue
            seen.add(key)
            shader_type = node_type(shader)
            result.append(
                {
                    "material": without_namespace(node_label(shader)),
                    "material_full_name": node_label(shader),
                    "material_path": shader,
                    "shader_type": shader_type,
                    "supported": shader_type in SUPPORTED_SHADER_TYPES,
                    "shading_engine": node_label(shading_engine),
                    "face_assignment": face_assignment(
                        mesh_shape,
                        shading_engine,
                    ),
                    "channels": shader_channels(shader, shader_type),
                }
            )
    return result


def face_assignment(mesh_shape, shading_engine):
    """Face membership of a mesh inside a shading engine set.

    Returned components are Maya's raw index expressions ("0:35", "7"), which
    the importer expands into Blender polygon material indices.
    """
    transform = parent_of(mesh_shape)
    targets = set([mesh_shape, transform])
    components = []
    all_faces = False
    for member in cmds.sets(shading_engine, query=True) or []:
        text = str(member)
        node_name = text.split(".f[", 1)[0]
        resolved = cmds.ls(node_name, long=True) or []
        if not any(item in targets for item in resolved):
            continue
        if ".f[" not in text:
            all_faces = True
            continue
        component = text.split(".f[", 1)[1].rstrip("]")
        if component and component not in components:
            components.append(component)
    return {
        "all_faces": all_faces,
        "face_components": components,
    }
