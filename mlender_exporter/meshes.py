# -*- coding: utf-8 -*-
"""Scene mesh discovery and per-mesh material records."""
from __future__ import absolute_import

import maya.cmds as cmds

from .constants import (
    BAKE_SEMANTIC,
    DISPLACEMENT_ENGINE_PLUG,
    DISPLACEMENT_MESH_ATTRS,
    DISPLACEMENT_MODES,
    DISPLACEMENT_MODE_ATTR,
    DISPLACEMENT_SPACES,
    DISPLACEMENT_SPACE_ATTR,
    DISPLACEMENT_NODE_INPUT,
    DISPLACEMENT_NODE_SCALE,
    DISPLACEMENT_NODE_TYPES,
    DISPLACEMENT_NODE_VECTOR,
    DISPLACEMENT_REDSHIFT_ENABLE,
    DISPLACEMENT_REDSHIFT_SCALE,
    MAX_SUBDIV_ITERATIONS,
    MESH_VISIBILITY_ATTRS,
    TRANSFORM_VISIBILITY_ATTRS,
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
    parents_of,
    plug_value,
    unique,
    without_namespace,
)
from .bake import bake_channel
from .shaders import shader_channels
from .textures import texture_from_plug


def scene_mesh_shapes(selected_only=False):
    """Every renderable mesh shape in the scene, or under the selection."""
    if selected_only:
        return selected_mesh_shapes()
    return unique([
        shape for shape in cmds.ls(type="mesh", long=True) or []
        if usable_mesh_shape(shape)
    ])


def selected_mesh_shapes():
    """Mesh shapes under the current selection, with groups expanded.

    Selecting the group that holds an asset is the normal way to pick it, so
    the selection is expanded to its descendants rather than taken literally;
    a literal reading would export nothing for the most common selection.
    """
    selection = cmds.ls(selection=True, long=True) or []
    if not selection:
        return []
    nodes = list(selection)
    try:
        nodes.extend(
            cmds.listRelatives(
                selection, allDescendents=True, fullPath=True
            ) or []
        )
    except Exception:
        pass
    return unique([
        node for node in nodes
        if node_type(node) == "mesh" and usable_mesh_shape(node)
    ])


def usable_mesh_shape(shape):
    """Whether a mesh shape can be exported at all.

    Intermediate objects belong to construction history and parentless shapes
    cannot be exported, so both are skipped.
    """
    try:
        if cmds.getAttr(shape + ".intermediateObject"):
            return False
    except Exception:
        pass
    return bool(parent_of(shape))


def selected_light_count():
    """Lights in the selection, so the user can be told they are not filtered.

    Lighting always travels whole: an asset exported without its lighting is
    not a scene package, it is a dark one.
    """
    selection = cmds.ls(selection=True, long=True) or []
    if not selection:
        return 0
    nodes = list(selection)
    try:
        nodes.extend(
            cmds.listRelatives(
                selection, allDescendents=True, fullPath=True
            ) or []
        )
    except Exception:
        pass
    return len([
        node for node in unique(nodes)
        if "light" in node_type(node).lower()
    ])


def mesh_transforms(mesh_shapes):
    """Transform paths for a list of mesh shapes, for FBX selection.

    Every transform, not just the first: an instanced shape hangs under
    several, and selecting only one left the rest out of the FBX.
    """
    transforms = unique([
        transform
        for shape in mesh_shapes
        for transform in parents_of(shape)
    ])
    return [item for item in transforms if item]


def mesh_records(mesh_shape, bake_context=None, cache=None):
    """One record per transform the shape hangs under.

    Instances share a shape, so everything read off the shape — materials,
    subdivision — is read once and reused, while the parts that belong to the
    transform are read per instance: its name, its group trail, its
    visibility. ``shape_path`` is the same on all of them, which is how the
    importer recognises them as instances of one another.
    """
    transforms = parents_of(mesh_shape) or [""]
    materials = mesh_materials(mesh_shape, bake_context, cache)
    subdivision = subdivision_info(mesh_shape)
    shape_label = node_label(mesh_shape)
    records = []
    for transform in transforms:
        full_name = node_label(transform or mesh_shape)
        records.append({
            "mesh": without_namespace(full_name),
            "mesh_full_name": full_name,
            "mesh_path": transform,
            "shape": shape_label,
            "shape_path": mesh_shape,
            "groups": group_path(transform),
            "visibility": visibility_info(mesh_shape, transform),
            "subdivision": subdivision,
            "materials": materials,
        })
    return records


def group_path(transform):
    """Names of the group transforms above a mesh, outermost first.

    Only a transform with no shape of its own counts as a group. A transform
    that carries geometry is an object, and turning it into a folder would
    invent a level of nesting the artist never made.

    The mesh's own transform is the last element of the path and is excluded;
    the result is the folder trail, which the importer mirrors as collections.
    """
    parts = [part for part in str(transform or "").split("|") if part]
    groups = []
    path = ""
    for part in parts[:-1]:
        path = path + "|" + part
        try:
            shapes = cmds.listRelatives(path, shapes=True, fullPath=True)
        except Exception:
            shapes = None
        if shapes:
            continue
        groups.append(without_namespace(part))
    return groups


def visibility_info(mesh_shape, transform):
    """Per-ray visibility and holdout flags, shape and transform together.

    Only flags that differ from Maya's default are written. Everything here
    defaults to on, so an ordinary mesh produces an empty record and the
    importer leaves Blender's own defaults alone.
    """
    result = {}
    for semantic, attrs in MESH_VISIBILITY_ATTRS.items():
        value, attr, _label = first_existing_attr(mesh_shape, attrs)
        if not attr or not isinstance(value, bool):
            continue
        # matte defaults to off, the rest default to on.
        default = semantic != "matte"
        if bool(value) != default:
            result[semantic] = bool(value)

    for semantic, attrs in TRANSFORM_VISIBILITY_ATTRS.items():
        value, attr, _label = first_existing_attr(transform, attrs)
        if attr and isinstance(value, bool) and not value:
            result[semantic] = False
    return result


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


def baked_channels(channels):
    """Whether any channel was baked against a particular mesh's UVs.

    A baked result belongs to the mesh it was baked for, so a shader that
    baked must be read again for the next mesh rather than reused.
    """
    for record in (channels or {}).values():
        if (record.get("texture") or {}).get("semantic") == BAKE_SEMANTIC:
            return True
    return False


def mesh_materials(mesh_shape, bake_context=None, cache=None):
    # One dict per export holding the shader reads and the shading engine
    # memberships, both of which are shared across meshes.
    cache = {} if cache is None else cache
    shader_cache = cache.setdefault("shaders", {})
    set_cache = cache.setdefault("sets", {})
    # Baking needs this mesh's UVs, so the context is pointed at it
    # before any of its shaders are read.
    if bake_context is not None:
        bake_context.for_mesh(parent_of(mesh_shape))
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
            # One material usually covers many meshes, and re-reading it per
            # mesh was the single largest cost in the export: with 60 shaders
            # across 400 meshes each shader was read about seven times.
            channels = None
            if shader_cache is not None:
                channels = shader_cache.get(shader)
            if channels is None:
                channels = shader_channels(shader, shader_type, bake_context)
                if shader_cache is not None and not baked_channels(channels):
                    shader_cache[shader] = channels
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
                        set_cache,
                    ),
                    "channels": channels,
                    "displacement": displacement_info(
                        mesh_shape,
                        shading_engine,
                        bake_context,
                    ),
                }
            )
    return result


def displacement_info(mesh_shape, shading_engine, bake_context=None):
    """Displacement hanging off a shading engine, with its mesh settings.

    Maya keeps displacement on the shadingEngine rather than on the surface
    shader, so it is read here where both the engine and the mesh are known:
    the map comes from the engine, the height and zero value from the mesh.

    Both wirings are accepted. A displacementShader node in between is the
    usual one, but a texture connected straight to the engine plug renders
    identically in Arnold and has to be recognised too.
    """
    if not attr_exists(shading_engine, DISPLACEMENT_ENGINE_PLUG):
        return {"enabled": False}
    plug = shading_engine + "." + DISPLACEMENT_ENGINE_PLUG
    sources = cmds.listConnections(
        plug, source=True, destination=False
    ) or []
    if not sources:
        return {"enabled": False}

    source = sources[0]
    scale = 1.0
    vector = False
    node_label_name = node_label(source)

    space = ""
    if node_type(source) in DISPLACEMENT_NODE_TYPES:
        scale = _number_or(plug_value(source + "." + DISPLACEMENT_NODE_SCALE), 1.0)
        mode = DISPLACEMENT_MODES.get(
            int(plug_value(source + "." + DISPLACEMENT_MODE_ATTR) or 0), "scalar"
        )
        vector = mode != "scalar" or _vector_displacement_connected(source)
        if vector:
            space = mode.replace("vector_", "") if mode != "scalar" else ""
            if not space:
                space = DISPLACEMENT_SPACES.get(
                    int(plug_value(source + "." + DISPLACEMENT_SPACE_ATTR) or 1),
                    "object",
                )
            height_plug = source + "." + DISPLACEMENT_NODE_VECTOR
        else:
            height_plug = source + "." + DISPLACEMENT_NODE_INPUT
    else:
        # A texture straight into the engine plug; the engine plug itself is
        # what carries the map.
        height_plug = plug

    texture = texture_from_plug(height_plug)
    if texture and not texture.get("path"):
        baked = bake_channel(
            bake_context,
            shading_engine,
            "displacement",
            texture.get("source_plug") or "",
        )
        if baked:
            texture = baked

    record = {
        "enabled": True,
        "node": node_label_name,
        "node_type": node_type(source),
        "scale": scale,
        "vector": vector,
        "vector_space": space,
        "subdivision_enabled": bool(
            subdivision_info(mesh_shape).get("enabled")
        ),
    }
    if texture:
        record["texture"] = texture
    value = plug_value(height_plug)
    if value is not None:
        record["value"] = value

    for semantic, attrs in DISPLACEMENT_MESH_ATTRS.items():
        found, attr, _label = first_existing_attr(mesh_shape, attrs)
        if attr:
            record[semantic] = found

    enabled_value, enabled_attr, _label = first_existing_attr(
        mesh_shape, DISPLACEMENT_REDSHIFT_ENABLE
    )
    if enabled_attr:
        record["redshift_enabled"] = bool(enabled_value)
        rs_scale, rs_attr, _rs_label = first_existing_attr(
            mesh_shape, DISPLACEMENT_REDSHIFT_SCALE
        )
        if rs_attr:
            record["redshift_scale"] = rs_scale
    return record


def _vector_displacement_connected(node):
    """Whether the vector input drives the node instead of the scalar one."""
    if not attr_exists(node, DISPLACEMENT_NODE_VECTOR):
        return False
    return bool(
        cmds.listConnections(
            node + "." + DISPLACEMENT_NODE_VECTOR,
            source=True,
            destination=False,
        )
    )


def _number_or(value, default):
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    return float(default)


def shading_engine_members(shading_engine):
    """Resolve one shading engine's membership, keyed by full DAG path.

    Read once per engine, not once per mesh. The previous version walked the
    whole set and called cmds.ls for every member, for every mesh: a single
    material covering a thousand meshes therefore cost a million lookups and
    made the export time grow with the square of the scene. Measured before
    the change, 200/400/800 meshes on two materials took 1.0/2.4/7.1 seconds.
    """
    members = {}
    for member in cmds.sets(shading_engine, query=True) or []:
        text = str(member)
        node_name = text.split(".f[", 1)[0]
        component = ""
        if ".f[" in text:
            component = text.split(".f[", 1)[1].rstrip("]")
        for resolved in cmds.ls(node_name, long=True) or []:
            entry = members.setdefault(
                resolved, {"all_faces": False, "face_components": []}
            )
            if not component:
                entry["all_faces"] = True
            elif component not in entry["face_components"]:
                entry["face_components"].append(component)
    return members


def face_assignment(mesh_shape, shading_engine, cache=None):
    """Face membership of a mesh inside a shading engine set.

    Returned components are Maya's raw index expressions ("0:35", "7"), which
    the importer expands into Blender polygon material indices.
    """
    members = None
    if cache is not None:
        members = cache.get(shading_engine)
    if members is None:
        members = shading_engine_members(shading_engine)
        if cache is not None:
            cache[shading_engine] = members

    all_faces = False
    components = []
    # The set can hold the shape, the transform, or both.
    for key in (mesh_shape, parent_of(mesh_shape)):
        entry = members.get(key)
        if not entry:
            continue
        all_faces = all_faces or entry["all_faces"]
        for component in entry["face_components"]:
            if component not in components:
                components.append(component)
    return {
        "all_faces": all_faces,
        "face_components": components,
    }
