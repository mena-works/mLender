# -*- coding: utf-8 -*-
"""Scene mesh discovery and per-mesh material records."""
from __future__ import absolute_import

import maya.cmds as cmds

from .constants import (
    MAX_SUBDIV_ITERATIONS,
    SUBDIV_ARNOLD_ITERATIONS,
    SUBDIV_ARNOLD_TYPE,
    SUBDIV_ARNOLD_UV_SMOOTHING,
    SUBDIV_MAYA_DISPLAY,
    SUBDIV_MAYA_RENDER_LEVEL,
    SUBDIV_MAYA_USE_PREVIEW_FOR_RENDER,
    SUBDIV_MAYA_VIEWPORT_LEVEL,
    SUBDIV_REDSHIFT_ENABLE,
    SUBDIV_REDSHIFT_ITERATIONS,
    SUBDIV_SCHEME_CATMULL_CLARK,
    SUBDIV_SCHEME_LINEAR,
    SUPPORTED_SHADER_TYPES,
)
from .mayautils import (
    attr_exists,
    first_existing_attr,
    node_label,
    node_type,
    parent_of,
    plug_value,
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
        "subdivision": subdivision_info(mesh_shape),
        "materials": mesh_materials(mesh_shape),
    }


def subdivision_info(mesh_shape):
    """Report whether this mesh actually asks to be subdivided, and how.

    Checked in order of authority: the Arnold and Redshift mesh settings are
    what a render would use, and Maya's smooth mesh preview is the fallback.
    A mesh that asks for nothing gets nothing; blanket subdivision would round
    off hard surface geometry that was never modelled to be smooth.
    """
    for reader in (
        _arnold_subdivision,
        _redshift_subdivision,
        _maya_smooth_preview,
    ):
        found = reader(mesh_shape)
        if found:
            return found
    return {"enabled": False, "source": "none"}


def _arnold_subdivision(mesh_shape):
    if not attr_exists(mesh_shape, SUBDIV_ARNOLD_TYPE):
        return None
    value, _attr, label = first_existing_attr(
        mesh_shape,
        (SUBDIV_ARNOLD_TYPE,),
    )
    label = str(label or "").lower()
    if not label and isinstance(value, (int, float)):
        label = {0: "none", 1: "catclark", 2: "linear"}.get(int(value), "none")
    if not label or label == "none":
        return None

    iterations = _clamp_iterations(
        plug_value(mesh_shape + "." + SUBDIV_ARNOLD_ITERATIONS)
    )
    _uv_value, _uv_attr, uv_label = first_existing_attr(
        mesh_shape,
        (SUBDIV_ARNOLD_UV_SMOOTHING,),
    )
    return {
        "enabled": True,
        "scheme": (
            SUBDIV_SCHEME_LINEAR if "linear" in label
            else SUBDIV_SCHEME_CATMULL_CLARK
        ),
        "render_iterations": iterations,
        "viewport_iterations": iterations,
        "uv_smoothing": str(uv_label or ""),
        "source": "arnold",
        "maya_attr": SUBDIV_ARNOLD_TYPE,
    }


def _redshift_subdivision(mesh_shape):
    enabled_value, enabled_attr, _label = first_existing_attr(
        mesh_shape,
        SUBDIV_REDSHIFT_ENABLE,
    )
    if not enabled_attr or not enabled_value:
        return None
    iterations = _clamp_iterations(
        _first_numeric(mesh_shape, SUBDIV_REDSHIFT_ITERATIONS)
    )
    return {
        "enabled": True,
        # Redshift's subdivision rule is Catmull-Clark for polygon meshes.
        "scheme": SUBDIV_SCHEME_CATMULL_CLARK,
        "render_iterations": iterations,
        "viewport_iterations": iterations,
        "uv_smoothing": "",
        "source": "redshift",
        "maya_attr": enabled_attr,
    }


def _maya_smooth_preview(mesh_shape):
    """Maya's smooth mesh preview, the "3" key, which is Catmull-Clark."""
    if not attr_exists(mesh_shape, SUBDIV_MAYA_DISPLAY):
        return None
    display = plug_value(mesh_shape + "." + SUBDIV_MAYA_DISPLAY)
    if not display:
        return None

    viewport = _clamp_iterations(
        plug_value(mesh_shape + "." + SUBDIV_MAYA_VIEWPORT_LEVEL)
    )
    render = viewport
    use_preview = plug_value(
        mesh_shape + "." + SUBDIV_MAYA_USE_PREVIEW_FOR_RENDER
    )
    if not use_preview:
        render = _clamp_iterations(
            plug_value(mesh_shape + "." + SUBDIV_MAYA_RENDER_LEVEL)
        )
    return {
        "enabled": True,
        "scheme": SUBDIV_SCHEME_CATMULL_CLARK,
        "render_iterations": render,
        "viewport_iterations": viewport,
        "uv_smoothing": "",
        "source": "maya_smooth_preview",
        "maya_attr": SUBDIV_MAYA_DISPLAY,
    }


def _first_numeric(mesh_shape, attrs):
    for attr in attrs:
        if not attr_exists(mesh_shape, attr):
            continue
        value = plug_value(mesh_shape + "." + attr)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return value
    return None


def _clamp_iterations(value):
    try:
        iterations = int(value)
    except (TypeError, ValueError):
        iterations = 1
    return max(0, min(MAX_SUBDIV_ITERATIONS, iterations))


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
