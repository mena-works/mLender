# -*- coding: utf-8 -*-
bl_info = {
    "name": "Z-A Exporter - Lookdev",
    "author": "Z-A Exporter",
    "version": (1, 2, 1),
    "blender": (3, 6, 0),
    "location": "View3D > Sidebar > Z-A Exporter",
    "description": "Live FBX lookdev transfer from Maya with Principled material rebuilding.",
    "category": "Import-Export",
}

import glob
import json
import math
import os
import re
import socket
import threading
try:
    import queue
except ImportError:
    import Queue as queue

import bpy
from mathutils import Matrix, Vector


LIVELINK_HOST = "127.0.0.1"
LIVELINK_PORT = 50505
LIVELINK_PROTOCOL = "za_lookdev_livelink"
LIVELINK_VERSION = 1
MAX_MESSAGE_BYTES = 32 * 1024 * 1024
ROOT_COLLECTION_NAME = "Z-A Lookdev Import"
LIGHT_COLLECTION_NAME = "Z-A Lights"
BUILD_VERSION = "1.2.1"

_server = None
_server_thread = None
_stop_event = None
_messages = queue.Queue()
_status = "Listener is stopped."


def import_lookdev_package(package_folder, package_data=None, import_scale=1.0):
    package_folder = _normalize_folder(package_folder)
    if package_data is None:
        package_data = _read_package_json(package_folder)
    fbx_path = _resolve_fbx_path(package_folder, package_data)

    if bpy.data.filepath:
        bpy.ops.wm.save_mainfile()
    _clear_scene_and_purge()

    before_objects = set(bpy.data.objects)
    before_materials = set(bpy.data.materials)
    _import_fbx(fbx_path, import_scale)
    imported_objects = [obj for obj in bpy.data.objects if obj not in before_objects]
    imported_meshes = [obj for obj in imported_objects if obj.type == "MESH"]
    if not imported_meshes:
        raise RuntimeError("FBX import produced no mesh objects.")

    root_collection = _organize_imported_objects(imported_objects)
    material_cache = {}
    assignments = []
    warnings = []
    mesh_records = list(package_data.get("meshes") or [])
    used_record_ids = set()

    for obj in imported_meshes:
        mesh_record = _find_mesh_record(obj, mesh_records, used_record_ids)
        if not mesh_record:
            warnings.append('No Maya mesh record matched "{0}".'.format(obj.name))
            obj.data.materials.clear()
            _remove_object_namespace(obj)
            continue
        used_record_ids.add(id(mesh_record))
        _rename_mesh_from_record(obj, mesh_record)
        assignment = _assign_mesh_materials(
            obj,
            mesh_record,
            material_cache,
            warnings,
        )
        assignments.append(assignment)

    namespace_prefixes = _package_namespace_prefixes(package_data)
    for obj in imported_objects:
        _remove_object_namespace(obj, namespace_prefixes)

    # The scene was cleared before the FBX import, so scanning the active scene
    # is the most reliable way to include every imported mesh object.
    scene_meshes = [
        obj for obj in bpy.context.scene.objects
        if obj.type == "MESH"
    ]
    subdivision_count = _add_subdivision_modifiers(scene_meshes, warnings)
    light_result = _import_lights(
        package_data,
        root_collection,
        import_scale,
        warnings,
    )

    for material in list(bpy.data.materials):
        if material in before_materials:
            continue
        if material.get("za_generated"):
            continue
        if material.users == 0:
            bpy.data.materials.remove(material)
    _purge_orphans()

    return {
        "package_folder": package_folder,
        "fbx_path": fbx_path,
        "root_collection": root_collection.name,
        "object_count": len(imported_objects),
        "mesh_count": len(imported_meshes),
        "material_count": len(material_cache),
        "subdivision_count": subdivision_count,
        "light_count": light_result["light_count"],
        "light_object_count": light_result["object_count"],
        "dome_count": light_result["dome_count"],
        "assignments": assignments,
        "warnings": warnings,
    }


def _add_subdivision_modifiers(mesh_objects, warnings=None):
    modifier_name = "Z-A Subdivision"
    modified_count = 0
    warnings = warnings if warnings is not None else []

    for obj in mesh_objects:
        if obj.type != "MESH":
            continue

        try:
            modifier = obj.modifiers.get(modifier_name)
            if modifier is not None and modifier.type != "SUBSURF":
                obj.modifiers.remove(modifier)
                modifier = None
            if modifier is None:
                modifier = obj.modifiers.new(name=modifier_name, type="SUBSURF")

            modifier.subdivision_type = "CATMULL_CLARK"
            modifier.levels = 2
            modifier.render_levels = 2
            modifier.boundary_smooth = "PRESERVE_CORNERS"
            modifier.use_limit_surface = True
            modifier.quality = 3
            modifier.uv_smooth = "PRESERVE_BOUNDARIES"
            modifier.use_creases = True
            modifier.use_custom_normals = False
            modifier.show_viewport = True
            modifier.show_render = True

            if (
                modifier.type != "SUBSURF"
                or modifier.levels != 2
                or modifier.render_levels != 2
                or modifier.boundary_smooth != "PRESERVE_CORNERS"
                or not modifier.use_limit_surface
                or modifier.quality != 3
                or modifier.uv_smooth != "PRESERVE_BOUNDARIES"
                or not modifier.use_creases
                or modifier.use_custom_normals
            ):
                raise RuntimeError("modifier settings could not be verified")
            modified_count += 1
        except Exception as exc:
            warnings.append(
                'Subdivision could not be added to "{0}": {1}'.format(
                    obj.name,
                    exc,
                )
            )

    return modified_count


def _rename_mesh_from_record(obj, mesh_record):
    clean_name = (
        mesh_record.get("mesh")
        or _namespace_free_name(mesh_record.get("mesh_full_name"))
        or _namespace_free_name(obj.name)
    )
    if clean_name:
        obj.name = clean_name
        if obj.data:
            obj.data.name = clean_name


def _remove_object_namespace(obj, namespace_prefixes=None):
    clean_name = _namespace_free_import_name(obj.name, namespace_prefixes)
    if clean_name:
        obj.name = clean_name
    if obj.data:
        clean_data_name = _namespace_free_import_name(
            obj.data.name,
            namespace_prefixes,
        )
        if clean_data_name:
            obj.data.name = clean_data_name


def _assign_mesh_materials(obj, mesh_record, material_cache, warnings):
    material_records = [
        record for record in (mesh_record.get("materials") or [])
        if record.get("material")
    ]
    obj.data.materials.clear()
    assigned_names = []

    for material_record in material_records:
        cache_key = (
            material_record.get("material_full_name")
            or material_record.get("material")
            or ""
        )
        material = material_cache.get(cache_key)
        if material is None:
            material = _build_principled_material(material_record, warnings)
            material_cache[cache_key] = material
        obj.data.materials.append(material)
        assigned_names.append(material.name)

    _apply_face_assignments(obj, material_records)
    return {
        "mesh": obj.name,
        "maya_mesh": mesh_record.get("mesh_full_name") or mesh_record.get("mesh"),
        "materials": assigned_names,
    }


def _build_principled_material(material_record, warnings):
    maya_name = (
        material_record.get("material_full_name")
        or material_record.get("material")
        or "Material"
    )
    display_name = (
        material_record.get("material")
        or _namespace_free_name(maya_name)
        or "Material"
    )
    material_name = _unique_material_name("ZA_" + _safe_name(display_name))
    material = bpy.data.materials.new(material_name)
    material["za_generated"] = True
    material["za_maya_material"] = maya_name
    material["za_shader_type"] = material_record.get("shader_type") or ""
    material.use_nodes = True

    nodes = material.node_tree.nodes
    links = material.node_tree.links
    nodes.clear()
    channels = material_record.get("channels") or {}

    if material_record.get("shader_type") == "surfaceShader":
        _build_surface_shader_material(material, channels, warnings)
        return material

    output = nodes.new("ShaderNodeOutputMaterial")
    output.location = (520, 0)
    bsdf = nodes.new("ShaderNodeBsdfPrincipled")
    bsdf.location = (220, 0)
    links.new(bsdf.outputs.get("BSDF"), output.inputs.get("Surface"))

    _apply_channel(material, bsdf, "base_color", channels.get("base_color"), warnings)
    _apply_channel(material, bsdf, "roughness", channels.get("roughness"), warnings)
    _apply_channel(material, bsdf, "metallic", channels.get("metallic"), warnings)
    _apply_channel(material, bsdf, "opacity", channels.get("opacity"), warnings)
    _apply_channel(material, bsdf, "normal", channels.get("normal"), warnings)
    _apply_channel(material, bsdf, "emission", channels.get("emission"), warnings)
    _apply_channel(
        material,
        bsdf,
        "emission_strength",
        channels.get("emission_strength"),
        warnings,
    )

    if not material_record.get("supported", True):
        warnings.append(
            'Unsupported Maya shader "{0}" on "{1}"; available channels were approximated.'.format(
                material_record.get("shader_type") or "",
                maya_name,
            )
        )
    return material


def _build_surface_shader_material(material, channels, warnings):
    nodes = material.node_tree.nodes
    links = material.node_tree.links
    output = nodes.new("ShaderNodeOutputMaterial")
    output.location = (520, 0)
    emission = nodes.new("ShaderNodeEmission")
    emission.location = (20, 80)
    transparent = nodes.new("ShaderNodeBsdfTransparent")
    transparent.location = (20, -130)
    mix = nodes.new("ShaderNodeMixShader")
    mix.location = (280, 0)
    links.new(transparent.outputs["BSDF"], mix.inputs[1])
    links.new(emission.outputs["Emission"], mix.inputs[2])
    links.new(mix.outputs["Shader"], output.inputs["Surface"])

    emission_record = channels.get("emission") or {}
    emission_texture = emission_record.get("texture") or {}
    if emission_texture.get("path"):
        image = _load_image(emission_texture, "emission", warnings)
        if image:
            image_node = nodes.new("ShaderNodeTexImage")
            image_node.name = "ZA_SurfaceShader_Color"
            image_node.image = image
            links.new(
                image_node.outputs["Color"],
                emission.inputs["Color"],
            )
    elif "value" in emission_record:
        emission.inputs["Color"].default_value = _color4(
            emission_record.get("value")
        )

    strength_record = channels.get("emission_strength") or {}
    emission.inputs["Strength"].default_value = max(
        0.0,
        _scalar(strength_record.get("value"), 1.0),
    )

    opacity_record = channels.get("opacity") or {}
    opacity_texture = opacity_record.get("texture") or {}
    if opacity_texture.get("path"):
        image = _load_image(opacity_texture, "opacity", warnings)
        if image:
            image_node = nodes.new("ShaderNodeTexImage")
            image_node.name = "ZA_SurfaceShader_Opacity"
            image_node.image = image
            rgb_to_bw = nodes.new("ShaderNodeRGBToBW")
            links.new(image_node.outputs["Color"], rgb_to_bw.inputs["Color"])
            opacity_output = rgb_to_bw.outputs["Val"]
            if opacity_record.get("invert"):
                invert = nodes.new("ShaderNodeMath")
                invert.operation = "SUBTRACT"
                invert.inputs[0].default_value = 1.0
                links.new(opacity_output, invert.inputs[1])
                opacity_output = invert.outputs[0]
            links.new(opacity_output, mix.inputs[0])
    else:
        mix.inputs[0].default_value = max(
            0.0,
            min(1.0, _scalar(opacity_record.get("value"), 1.0)),
        )
    _enable_alpha(material)


def _apply_channel(material, bsdf, channel, record, warnings):
    if not record:
        return
    target = _principled_input(bsdf, channel)
    if target is None:
        return

    texture = record.get("texture") or {}
    texture_path = texture.get("path") or ""
    if texture_path:
        image = _load_image(texture, channel, warnings)
        if image:
            _connect_image_channel(
                material,
                bsdf,
                target,
                channel,
                image,
                bool(record.get("invert")),
            )
            return

    if "value" not in record:
        return
    value = record.get("value")
    if channel in ("base_color", "emission"):
        target.default_value = _color4(value)
    elif channel == "opacity":
        target.default_value = _scalar(value, 1.0)
        _enable_alpha(material)
    elif channel == "normal":
        return
    else:
        target.default_value = _scalar(value, target.default_value)


def _connect_image_channel(material, bsdf, target, channel, image, invert):
    nodes = material.node_tree.nodes
    links = material.node_tree.links
    image_node = nodes.new("ShaderNodeTexImage")
    image_node.name = "ZA_{0}_Texture".format(channel)
    image_node.label = channel.replace("_", " ").title()
    image_node.image = image

    if channel == "normal":
        normal_map = nodes.new("ShaderNodeNormalMap")
        links.new(image_node.outputs.get("Color"), normal_map.inputs.get("Color"))
        links.new(normal_map.outputs.get("Normal"), target)
        return

    if channel == "opacity":
        rgb_to_bw = nodes.new("ShaderNodeRGBToBW")
        links.new(image_node.outputs.get("Color"), rgb_to_bw.inputs.get("Color"))
        output = rgb_to_bw.outputs.get("Val")
        if invert:
            invert_node = nodes.new("ShaderNodeMath")
            invert_node.operation = "SUBTRACT"
            invert_node.inputs[0].default_value = 1.0
            links.new(output, invert_node.inputs[1])
            output = invert_node.outputs[0]
        links.new(output, target)
        _enable_alpha(material)
        return

    output = image_node.outputs.get("Color")
    if invert:
        invert_node = nodes.new("ShaderNodeInvert")
        links.new(output, invert_node.inputs.get("Color"))
        output = invert_node.outputs.get("Color")
    links.new(output, target)


def _principled_input(bsdf, channel):
    names = {
        "base_color": ("Base Color",),
        "roughness": ("Roughness",),
        "metallic": ("Metallic",),
        "opacity": ("Alpha",),
        "normal": ("Normal",),
        "emission": ("Emission Color", "Emission"),
        "emission_strength": ("Emission Strength",),
    }
    for name in names.get(channel, ()):
        socket = bsdf.inputs.get(name)
        if socket is not None:
            return socket
    return None


def _load_image(texture_record, channel, warnings):
    path = texture_record.get("path") or ""
    path = os.path.abspath(os.path.expandvars(os.path.expanduser(path)))
    resolved_path, tiled = _resolve_image_path(path)
    if not resolved_path:
        warnings.append('Texture not found for {0}: {1}'.format(channel, path))
        return None
    try:
        image = bpy.data.images.load(resolved_path, check_existing=True)
        if tiled:
            try:
                image.source = "TILED"
                image.filepath = path
            except Exception:
                pass
        maya_color_space = str(texture_record.get("color_space") or "").lower()
        if (
            channel not in ("base_color", "emission")
            or "raw" in maya_color_space
            or "non-color" in maya_color_space
        ):
            try:
                image.colorspace_settings.name = "Non-Color"
            except Exception:
                pass
        return image
    except Exception as exc:
        warnings.append(
            'Texture could not be loaded for {0}: {1} ({2})'.format(
                channel,
                path,
                exc,
            )
        )
        return None


def _resolve_image_path(path):
    if os.path.isfile(path):
        return path, False
    tokenized = (
        path.replace("<UDIM>", "*")
        .replace("<udim>", "*")
        .replace("####", "*")
    )
    matches = sorted(glob.glob(tokenized))
    return (matches[0], "<UDIM>" in path.upper()) if matches else ("", False)


def _enable_alpha(material):
    for attr, value in (
        ("blend_method", "BLEND"),
        ("surface_render_method", "DITHERED"),
        ("shadow_method", "HASHED"),
    ):
        if hasattr(material, attr):
            try:
                setattr(material, attr, value)
            except Exception:
                pass


def _apply_face_assignments(obj, material_records):
    if not material_records:
        return
    if not any(record.get("face_assignment") for record in material_records):
        return
    polygon_count = len(obj.data.polygons)
    for slot_index, record in enumerate(material_records):
        assignment = record.get("face_assignment") or {}
        if assignment.get("all_faces"):
            for polygon in obj.data.polygons:
                polygon.material_index = slot_index
        for index in _face_indices(assignment.get("face_components") or []):
            if 0 <= index < polygon_count:
                obj.data.polygons[index].material_index = slot_index


def _face_indices(components):
    result = []
    seen = set()
    for component in components:
        for part in str(component).split(","):
            part = part.strip()
            if not part:
                continue
            if ":" in part:
                values = part.split(":")
                try:
                    start = int(values[0])
                    stop = int(values[1])
                    step = int(values[2]) if len(values) > 2 else 1
                except Exception:
                    continue
                indices = range(start, stop + 1, max(1, step))
            else:
                try:
                    indices = (int(part),)
                except Exception:
                    continue
            for index in indices:
                if index not in seen:
                    seen.add(index)
                    result.append(index)
    return result


def _find_mesh_record(obj, records, used_record_ids):
    object_keys = _name_keys(obj.name)
    if obj.data:
        object_keys.update(_name_keys(obj.data.name))

    best = None
    best_score = -1
    for record in records:
        if id(record) in used_record_ids:
            continue
        full_name = record.get("mesh_full_name") or ""
        base_name = record.get("mesh") or ""
        full_keys = _name_keys(full_name)
        base_keys = _name_keys(base_name)
        score = -1
        if object_keys.intersection(full_keys):
            score = 100
        elif object_keys.intersection(base_keys):
            score = 10
        if score > best_score:
            best = record
            best_score = score
    return best if best_score >= 0 else None


def _name_keys(value):
    value = _strip_duplicate(str(value or ""))
    tail = value.split("|")[-1].split("/")[-1].split("\\")[-1]
    base = tail.rsplit(":", 1)[-1]
    variants = (
        value,
        tail,
        base,
        value.replace(":", "_"),
        tail.replace(":", "_"),
    )
    return set(_normalize_name(item) for item in variants if item)


def _organize_imported_objects(objects):
    root = bpy.data.collections.new(ROOT_COLLECTION_NAME)
    bpy.context.scene.collection.children.link(root)
    for obj in objects:
        for collection in list(obj.users_collection):
            collection.objects.unlink(obj)
        root.objects.link(obj)
    return root


def _import_lights(package_data, root_collection, import_scale, warnings):
    records = list(package_data.get("lights") or [])
    if not records:
        bpy.context.scene.world = None
        return {
            "light_count": 0,
            "object_count": 0,
            "dome_count": 0,
        }

    light_collection = bpy.data.collections.new(LIGHT_COLLECTION_NAME)
    root_collection.children.link(light_collection)
    meters_per_unit = _scalar(
        package_data.get("meters_per_maya_unit"),
        0.01,
    )
    position_scale = meters_per_unit * max(_scalar(import_scale, 1.0), 0.000001)
    object_count = 0
    dome_records = []

    for record in records:
        if str(record.get("light_kind") or "").upper() == "DOME":
            dome_records.append(record)
            continue
        try:
            _create_light_object(
                record,
                light_collection,
                position_scale,
                warnings,
            )
            object_count += 1
        except Exception as exc:
            warnings.append(
                'Light "{0}" could not be created: {1}'.format(
                    record.get("full_name") or record.get("name") or "Light",
                    exc,
                )
            )

    dome_count = _create_dome_world(
        dome_records,
        light_collection,
        position_scale,
        warnings,
    )
    return {
        "light_count": object_count + dome_count,
        "object_count": object_count,
        "dome_count": dome_count,
    }


def _create_light_object(record, collection, position_scale, warnings):
    source_kind = str(record.get("light_kind") or "AREA").upper()
    area_shape = str(record.get("area_shape") or "RECTANGLE").upper()
    blender_type = source_kind
    if source_kind == "IES":
        blender_type = "SPOT"
    elif source_kind == "AREA" and area_shape == "SPHERE":
        blender_type = "POINT"
    elif blender_type not in ("AREA", "POINT", "SPOT", "SUN"):
        blender_type = "AREA"

    clean_name = (
        record.get("name")
        or _namespace_free_name(record.get("full_name"))
        or "Light"
    )
    data = bpy.data.lights.new(clean_name, blender_type)
    obj = bpy.data.objects.new(clean_name, data)
    collection.objects.link(obj)
    obj.matrix_world = _maya_light_matrix(
        record.get("transform") or {},
        position_scale,
    )
    obj.scale = (1.0, 1.0, 1.0)

    parameters = record.get("parameters") or {}
    enabled = bool(record.get("enabled", True))
    color = _light_color(record)
    data.color = color
    _apply_light_temperature(data, record)
    data.energy = _light_energy(record, blender_type, position_scale)
    if not enabled:
        data.energy = 0.0

    if hasattr(data, "use_shadow"):
        data.use_shadow = bool(parameters.get("cast_shadows", True))
    if hasattr(data, "diffuse_factor"):
        data.diffuse_factor = max(0.0, _scalar(parameters.get("diffuse"), 1.0))
    if hasattr(data, "specular_factor"):
        data.specular_factor = max(0.0, _scalar(parameters.get("specular"), 1.0))
    if hasattr(data, "volume_factor"):
        data.volume_factor = max(0.0, _scalar(parameters.get("volume"), 1.0))
    if hasattr(data, "normalize") and "normalize" in parameters:
        data.normalize = bool(parameters.get("normalize"))

    source_scale = _source_light_scale(record)
    size_x = max(0.0001, source_scale[0] * position_scale)
    size_y = max(0.0001, source_scale[1] * position_scale)
    size_z = max(0.0001, source_scale[2] * position_scale)

    if blender_type == "AREA":
        _configure_area_light(
            data,
            area_shape,
            size_x,
            size_y,
            size_z,
            parameters,
            warnings,
            clean_name,
        )
    elif blender_type == "SPOT":
        cone_angle = max(
            0.1,
            min(179.0, _scalar(parameters.get("cone_angle"), 45.0)),
        )
        falloff_angle = abs(
            _scalar(parameters.get("falloff_angle"), cone_angle * 0.15)
        )
        data.spot_size = math.radians(cone_angle)
        data.spot_blend = max(
            0.0,
            min(1.0, falloff_angle / max(cone_angle * 0.5, 0.0001)),
        )
        data.shadow_soft_size = max(
            0.0,
            _scalar(parameters.get("shadow_softness"), 0.0) * position_scale,
        )
    elif blender_type == "POINT":
        radius = _scalar(parameters.get("shadow_softness"), 0.0) * position_scale
        if source_kind == "AREA" and area_shape == "SPHERE":
            radius = max(size_x, size_y, size_z) * 0.5
        data.shadow_soft_size = max(0.0, radius)
    elif blender_type == "SUN" and hasattr(data, "angle"):
        softness = max(0.0, _scalar(parameters.get("shadow_softness"), 0.0))
        data.angle = min(math.pi, softness)

    _configure_light_texture_nodes(data, record, warnings)
    _store_light_metadata(obj, data, record)
    return obj


def _configure_area_light(
    data,
    area_shape,
    size_x,
    size_y,
    size_z,
    parameters,
    warnings,
    light_name,
):
    if area_shape == "DISK":
        data.shape = "DISK"
        data.size = max(size_x, size_y)
    else:
        data.shape = "RECTANGLE"
        data.size = size_x
        data.size_y = size_y

    if area_shape in ("CYLINDER", "MESH"):
        warnings.append(
            '{0} area shape on "{1}" was approximated with a rectangular '
            "Blender Area light.".format(area_shape.title(), light_name)
        )
        if area_shape == "CYLINDER":
            data.size_y = max(size_y, size_z)

    if hasattr(data, "spread") and "spread" in parameters:
        spread = max(0.0, min(1.0, _scalar(parameters.get("spread"), 1.0)))
        data.spread = max(0.0001, spread * math.pi)


def _light_energy(record, blender_type, position_scale):
    effective = _scalar(
        record.get("effective_intensity"),
        _scalar(record.get("intensity"), 1.0)
        * (2.0 ** _scalar(record.get("exposure"), 0.0)),
    )
    effective = max(0.0, effective)
    labels = record.get("enum_labels") or {}
    units = str(labels.get("units") or "").lower()

    if blender_type == "SUN":
        return effective
    if "lumen" in units:
        return effective / 683.0
    if "candela" in units:
        return effective * (4.0 * math.pi) / 683.0
    if "watt" in units:
        return effective
    if "nit" in units or "radiance" in units or "exitance" in units:
        scale = _source_light_scale(record)
        area = max(
            0.000001,
            scale[0] * scale[1] * position_scale * position_scale,
        )
        return effective * area * math.pi / 683.0

    # Redshift's Image unit defaults to intensity 100, while native Maya lights
    # commonly default to 1. They therefore need separate visual calibration.
    node_type = str(record.get("node_type") or "").lower()
    calibration = 10.0 if "redshift" in node_type else 1000.0
    return effective * calibration


def _light_color(record):
    value = record.get("color") or (1.0, 1.0, 1.0)
    color = _color4(value)
    return color[:3]


def _apply_light_temperature(data, record):
    parameters = record.get("parameters") or {}
    labels = record.get("enum_labels") or {}
    mode = str(labels.get("color_mode") or "").lower()
    use_temperature = bool(parameters.get("use_temperature", False))
    if "temperature" in mode:
        use_temperature = True
        if "color and" not in mode and "color+" not in mode:
            data.color = (1.0, 1.0, 1.0)
    temperature = max(
        800.0,
        min(20000.0, _scalar(parameters.get("temperature"), 6500.0)),
    )
    if hasattr(data, "use_temperature"):
        data.use_temperature = use_temperature
    if hasattr(data, "temperature"):
        data.temperature = temperature


def _configure_light_texture_nodes(data, record, warnings):
    color_texture = record.get("color_texture") or {}
    ies_record = record.get("ies_profile") or {}
    color_path = color_texture.get("path") or ""
    ies_path = ies_record.get("path") or ""
    decay_label = str(
        (record.get("enum_labels") or {}).get("decay") or ""
    ).lower()
    custom_decay = "linear" in decay_label or any(
        token in decay_label for token in ("none", "constant")
    )
    if not color_path and not ies_path and not custom_decay:
        return
    if not hasattr(data, "use_nodes"):
        return

    try:
        data.use_nodes = True
        nodes = data.node_tree.nodes
        links = data.node_tree.links
        emission = next(
            (node for node in nodes if node.bl_idname == "ShaderNodeEmission"),
            None,
        )
        if emission is None:
            return
        strength_output = None

        if color_path:
            image = _load_image(color_texture, "base_color", warnings)
            if image:
                image_node = nodes.new("ShaderNodeTexImage")
                image_node.name = "ZA_Light_Color_Texture"
                image_node.image = image
                links.new(
                    image_node.outputs.get("Color"),
                    emission.inputs.get("Color"),
                )

        if custom_decay:
            falloff = nodes.new("ShaderNodeLightFalloff")
            falloff.inputs["Strength"].default_value = max(0.0, data.energy)
            output_name = "Linear" if "linear" in decay_label else "Constant"
            strength_output = falloff.outputs.get(output_name)

        if ies_path and os.path.isfile(ies_path):
            try:
                ies_node = nodes.new("ShaderNodeTexIES")
                if hasattr(ies_node, "mode"):
                    ies_node.mode = "EXTERNAL"
                ies_node.filepath = ies_path
                multiply = nodes.new("ShaderNodeMath")
                multiply.operation = "MULTIPLY"
                links.new(ies_node.outputs.get("Fac"), multiply.inputs[0])
                if strength_output is not None:
                    links.new(strength_output, multiply.inputs[1])
                else:
                    multiply.inputs[1].default_value = max(0.0, data.energy)
                strength_output = multiply.outputs[0]
            except Exception as exc:
                warnings.append(
                    'IES profile could not be connected on "{0}": {1}'.format(
                        data.name,
                        exc,
                    )
                )
        elif ies_path:
            warnings.append(
                'IES profile was not found for "{0}": {1}'.format(
                    data.name,
                    ies_path,
                )
            )
        if strength_output is not None:
            links.new(
                strength_output,
                emission.inputs.get("Strength"),
            )
    except Exception as exc:
        warnings.append(
            'Light texture nodes could not be built for "{0}": {1}'.format(
                data.name,
                exc,
            )
        )


def _create_dome_world(
    dome_records,
    collection,
    position_scale,
    warnings,
):
    bpy.context.scene.world = None
    if not dome_records:
        return 0

    enabled_records = [
        record for record in dome_records
        if bool(record.get("enabled", True))
    ]
    selected = enabled_records[0] if enabled_records else dome_records[0]
    if len(dome_records) > 1:
        warnings.append(
            "Blender has one active World environment; the first enabled "
            "Redshift Dome light was used and the remaining domes were kept "
            "as metadata empties."
        )

    world = bpy.data.worlds.new("Z-A Dome World")
    world.use_nodes = True
    bpy.context.scene.world = world
    nodes = world.node_tree.nodes
    links = world.node_tree.links
    nodes.clear()
    output = nodes.new("ShaderNodeOutputWorld")
    background = nodes.new("ShaderNodeBackground")
    background.inputs["Color"].default_value = _color4(
        selected.get("color") or (1.0, 1.0, 1.0)
    )
    background.inputs["Strength"].default_value = (
        _scalar(selected.get("effective_intensity"), 1.0)
        if bool(selected.get("enabled", True))
        else 0.0
    )
    links.new(background.outputs["Background"], output.inputs["Surface"])

    texture_record = selected.get("dome_texture") or {}
    if texture_record.get("path"):
        image = _load_image(texture_record, "base_color", warnings)
        if image:
            environment = nodes.new("ShaderNodeTexEnvironment")
            environment.image = image
            texcoord = nodes.new("ShaderNodeTexCoord")
            mapping = nodes.new("ShaderNodeMapping")
            vector_output = (
                texcoord.outputs.get("Generated")
                or texcoord.outputs.get("Normal")
            )
            links.new(vector_output, mapping.inputs["Vector"])
            links.new(mapping.outputs["Vector"], environment.inputs["Vector"])

            tint = nodes.new("ShaderNodeMixRGB")
            tint.blend_type = "MULTIPLY"
            tint.inputs[0].default_value = 1.0
            tint.inputs[2].default_value = _color4(
                selected.get("color") or (1.0, 1.0, 1.0)
            )
            links.new(environment.outputs["Color"], tint.inputs[1])
            links.new(tint.outputs["Color"], background.inputs["Color"])

            matrix = _maya_light_matrix(
                selected.get("transform") or {},
                position_scale,
            )
            mapping.inputs["Rotation"].default_value = matrix.to_euler()

    for record in dome_records:
        name = (
            record.get("name")
            or _namespace_free_name(record.get("full_name"))
            or "Dome"
        )
        empty = bpy.data.objects.new(name, None)
        empty.empty_display_type = "SPHERE"
        empty.empty_display_size = 1.0
        collection.objects.link(empty)
        empty.matrix_world = _maya_light_matrix(
            record.get("transform") or {},
            position_scale,
        )
        empty.scale = (1.0, 1.0, 1.0)
        _store_light_metadata(empty, None, record)
    return len(dome_records)


def _maya_light_matrix(transform_record, position_scale):
    values = transform_record.get("world_matrix") or []
    if len(values) != 16:
        translation = transform_record.get("translation") or (0.0, 0.0, 0.0)
        converted = _maya_vector_to_blender(translation) * position_scale
        matrix = Matrix.Identity(4)
        matrix.translation = converted
        return matrix

    x_axis = _maya_vector_to_blender(values[0:3])
    y_axis = _maya_vector_to_blender(values[4:7])
    z_axis = _maya_vector_to_blender(values[8:11])
    x_axis = _normalized_axis(x_axis, Vector((1.0, 0.0, 0.0)))
    y_axis = _normalized_axis(y_axis, Vector((0.0, 0.0, 1.0)))
    z_axis = _normalized_axis(z_axis, Vector((0.0, -1.0, 0.0)))
    translation = _maya_vector_to_blender(values[12:15]) * position_scale
    return Matrix(
        (
            (x_axis.x, y_axis.x, z_axis.x, translation.x),
            (x_axis.y, y_axis.y, z_axis.y, translation.y),
            (x_axis.z, y_axis.z, z_axis.z, translation.z),
            (0.0, 0.0, 0.0, 1.0),
        )
    )


def _normalized_axis(axis, fallback):
    if axis.length <= 0.000001:
        return fallback.copy()
    return axis.normalized()


def _maya_vector_to_blender(value):
    values = list(value or (0.0, 0.0, 0.0))
    while len(values) < 3:
        values.append(0.0)
    return Vector(
        (
            _scalar(values[0], 0.0),
            -_scalar(values[2], 0.0),
            _scalar(values[1], 0.0),
        )
    )


def _source_light_scale(record):
    transform = record.get("transform") or {}
    value = transform.get("scale") or (1.0, 1.0, 1.0)
    values = [abs(_scalar(item, 1.0)) for item in list(value)[:3]]
    while len(values) < 3:
        values.append(1.0)
    return values


def _store_light_metadata(obj, data, record):
    target = data if data is not None else obj
    target["za_generated"] = True
    target["za_source_full_name"] = str(record.get("full_name") or "")
    target["za_source_node_type"] = str(record.get("node_type") or "")
    target["za_source_light_kind"] = str(record.get("light_kind") or "")
    target["za_source_intensity"] = _scalar(record.get("intensity"), 1.0)
    target["za_source_exposure"] = _scalar(record.get("exposure"), 0.0)
    target["za_source_json"] = json.dumps(record, ensure_ascii=False)


def _clear_scene_and_purge():
    try:
        if bpy.context.object and bpy.context.object.mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")
    except Exception:
        pass

    # Context deletion clears objects linked to the active view layer.
    try:
        bpy.ops.object.select_all(action="SELECT")
        bpy.ops.object.delete(use_global=True, confirm=False)
    except Exception:
        pass

    # Datablock deletion also clears hidden, excluded and other-scene objects.
    for obj in list(bpy.data.objects):
        try:
            bpy.data.objects.remove(obj, do_unlink=True)
        except Exception:
            pass
    for collection in list(bpy.data.collections):
        try:
            bpy.data.collections.remove(collection)
        except Exception:
            pass

    remaining_ids = list(bpy.data.objects) + list(bpy.data.collections)
    if remaining_ids and hasattr(bpy.data, "batch_remove"):
        try:
            bpy.data.batch_remove(ids=remaining_ids)
        except Exception:
            pass

    if bpy.data.objects or bpy.data.collections:
        raise RuntimeError(
            "The previous Blender scene could not be cleared completely "
            "({0} object(s), {1} collection(s) remain).".format(
                len(bpy.data.objects),
                len(bpy.data.collections),
            )
        )

    for scene in bpy.data.scenes:
        scene.world = None

    for data_name in (
        "meshes",
        "curves",
        "cameras",
        "lights",
        "worlds",
        "materials",
        "images",
        "textures",
        "actions",
        "armatures",
    ):
        data_collection = getattr(bpy.data, data_name, None)
        if data_collection is None:
            continue
        for item in list(data_collection):
            if getattr(item, "users", 0) == 0:
                try:
                    data_collection.remove(item)
                except Exception:
                    pass
    _purge_orphans()


def _purge_orphans():
    try:
        bpy.data.orphans_purge(do_recursive=True)
        return
    except Exception:
        pass
    try:
        bpy.ops.outliner.orphans_purge(do_recursive=True)
    except Exception:
        pass


def _import_fbx(path, scale):
    try:
        scale = float(scale)
    except Exception:
        scale = 1.0
    kwargs = {
        "filepath": path,
        "global_scale": scale,
        "use_image_search": False,
    }
    try:
        bpy.ops.import_scene.fbx(**kwargs)
    except TypeError:
        kwargs.pop("use_image_search", None)
        bpy.ops.import_scene.fbx(**kwargs)


def _resolve_fbx_path(package_folder, package_data):
    raw = package_data.get("fbx_file") or ""
    candidates = [
        raw,
        os.path.join(package_folder, raw),
        os.path.join(package_folder, os.path.basename(raw)),
    ]
    for path in candidates:
        if path and os.path.isfile(path):
            return os.path.abspath(path)
    files = glob.glob(os.path.join(package_folder, "*.fbx"))
    if len(files) == 1:
        return os.path.abspath(files[0])
    raise ValueError("Package FBX file was not found.")


def _read_package_json(package_folder):
    files = glob.glob(os.path.join(package_folder, "*_lookdev.json"))
    if len(files) != 1:
        raise ValueError("Package must contain exactly one *_lookdev.json file.")
    with open(files[0], "r", encoding="utf-8") as handle:
        return json.load(handle)


def _normalize_folder(folder):
    if not folder:
        raise ValueError("Package folder is empty.")
    folder = os.path.abspath(os.path.expanduser(bpy.path.abspath(folder)))
    if not os.path.isdir(folder):
        raise ValueError("Package folder does not exist: {0}".format(folder))
    return folder


def _color4(value):
    if isinstance(value, (list, tuple)):
        values = [float(item) for item in value]
    else:
        values = [float(value)] * 3
    while len(values) < 3:
        values.append(values[-1] if values else 1.0)
    alpha = values[3] if len(values) > 3 else 1.0
    return (
        max(0.0, min(1.0, values[0])),
        max(0.0, min(1.0, values[1])),
        max(0.0, min(1.0, values[2])),
        max(0.0, min(1.0, alpha)),
    )


def _scalar(value, default=0.0):
    if isinstance(value, (list, tuple)):
        values = [float(item) for item in value[:3]]
        return sum(values) / float(len(values)) if values else float(default)
    try:
        return float(value)
    except Exception:
        return float(default)


def _safe_name(value):
    value = re.sub(r'[<>:"/\\|?*\s]+', "_", str(value or "").strip())
    return value.strip("_") or "Material"


def _namespace_free_name(value):
    value = str(value or "")
    value = value.split("|")[-1].split("/")[-1].split("\\")[-1]
    return value.rsplit(":", 1)[-1].strip()


def _package_namespace_prefixes(package_data):
    prefixes = set()
    records = list(package_data.get("meshes") or [])
    records.extend(package_data.get("lights") or [])
    for record in records:
        for field in (
            "mesh_full_name",
            "mesh_path",
            "shape",
            "shape_path",
            "full_name",
            "shape_full_name",
        ):
            if field not in record:
                continue
            value = str(record.get(field) or "")
            tail = value.split("|")[-1].split("/")[-1].split("\\")[-1]
            if ":" in tail:
                prefixes.add(tail.rsplit(":", 1)[0])
    return sorted(prefixes, key=len, reverse=True)


def _namespace_free_import_name(value, namespace_prefixes=None):
    value = str(value or "")
    tail = value.split("|")[-1].split("/")[-1].split("\\")[-1]
    if ":" in tail:
        return tail.rsplit(":", 1)[-1].strip()

    for prefix in namespace_prefixes or []:
        candidates = (
            prefix + "_",
            prefix.replace(":", "_") + "_",
            prefix.replace(":", "__") + "__",
        )
        for candidate in candidates:
            if tail.startswith(candidate):
                return tail[len(candidate):].strip()
    return tail.strip()


def _normalize_name(value):
    return _strip_duplicate(str(value or "")).strip().lower()


def _strip_duplicate(value):
    return re.sub(r"\.\d{3}$", "", value)


def _unique_material_name(base):
    if bpy.data.materials.get(base) is None:
        return base
    index = 1
    while True:
        candidate = "{0}_{1:03d}".format(base, index)
        if bpy.data.materials.get(candidate) is None:
            return candidate
        index += 1


def _start_listener(host, port):
    global _server, _server_thread, _stop_event, _status
    if _server is not None:
        _status = "Listener is already running."
        return
    host = str(host or LIVELINK_HOST)
    port = int(port)
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind((host, port))
    server.listen(4)
    server.settimeout(0.5)
    stop_event = threading.Event()
    _server = server
    _stop_event = stop_event
    _server_thread = threading.Thread(
        target=_listener_loop,
        args=(server, stop_event),
        name="ZALookdevLiveLink",
    )
    _server_thread.daemon = True
    _server_thread.start()
    _status = "Listening on {0}:{1}".format(host, port)
    if not bpy.app.timers.is_registered(_process_messages):
        bpy.app.timers.register(_process_messages, first_interval=0.1)


def _stop_listener():
    global _server, _server_thread, _stop_event, _status
    server = _server
    server_thread = _server_thread
    stop_event = _stop_event

    if stop_event:
        stop_event.set()
    if server:
        try:
            server.close()
        except Exception:
            pass
    _server = None
    _server_thread = None
    _stop_event = None

    try:
        if bpy.app.timers.is_registered(_process_messages):
            bpy.app.timers.unregister(_process_messages)
    except Exception:
        pass

    if (
        server_thread
        and server_thread.is_alive()
        and server_thread is not threading.current_thread()
    ):
        server_thread.join(timeout=1.0)

    _status = "Listener is stopped."


def _listener_loop(server, stop_event):
    while not stop_event.is_set():
        try:
            connection, _address = server.accept()
        except socket.timeout:
            continue
        except OSError:
            break
        try:
            data = b""
            while len(data) <= MAX_MESSAGE_BYTES:
                chunk = connection.recv(65536)
                if not chunk:
                    break
                data += chunk
                if b"\n" in data:
                    break
            if len(data) > MAX_MESSAGE_BYTES:
                raise ValueError("LiveLink message is too large.")
            message = json.loads(data.split(b"\n", 1)[0].decode("utf-8"))
            _messages.put(("message", message))
        except Exception as exc:
            _messages.put(("error", str(exc)))
        finally:
            try:
                connection.close()
            except Exception:
                pass


def _process_messages():
    global _status
    try:
        kind, payload = _messages.get_nowait()
    except queue.Empty:
        return 0.1 if _server else None
    if kind == "error":
        _status = "Message rejected: {0}".format(payload)
        return 0.1
    try:
        _validate_message(payload)
        scene = bpy.context.scene
        result = import_lookdev_package(
            payload.get("package_folder") or "",
            package_data=payload.get("package_json"),
            import_scale=scene.za_import_scale,
        )
        _status = (
            "Imported {0} mesh(es), {1} material(s), "
            "{2} subdivision modifier(s), {3} light(s)."
        ).format(
            result["mesh_count"],
            result["material_count"],
            result["subdivision_count"],
            result["light_count"],
        )
        for warning in result.get("warnings") or []:
            print("Z-A Lookdev warning: {0}".format(warning))
    except Exception as exc:
        _status = "Import failed: {0}".format(exc)
        print("Z-A Lookdev: {0}".format(_status))
    return 0.1


def _validate_message(message):
    if not isinstance(message, dict):
        raise ValueError("LiveLink message must be a JSON object.")
    if message.get("protocol") != LIVELINK_PROTOCOL:
        raise ValueError("Unsupported LiveLink protocol.")
    if message.get("protocol_version") != LIVELINK_VERSION:
        raise ValueError("Unsupported LiveLink protocol version.")
    if message.get("event") != "lookdev_package_ready":
        raise ValueError("Unsupported LiveLink event.")
    if not isinstance(message.get("package_json"), dict):
        raise ValueError("LiveLink package JSON is missing.")


class ZA_OT_start_listener(bpy.types.Operator):
    bl_idname = "za_lookdev.start_listener"
    bl_label = "Start LiveLink"

    def execute(self, context):
        try:
            _start_listener(
                context.scene.za_livelink_host,
                context.scene.za_livelink_port,
            )
        except Exception as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        self.report({"INFO"}, _status)
        return {"FINISHED"}


class ZA_OT_stop_listener(bpy.types.Operator):
    bl_idname = "za_lookdev.stop_listener"
    bl_label = "Stop LiveLink"

    def execute(self, context):
        _stop_listener()
        self.report({"INFO"}, _status)
        return {"FINISHED"}


class ZA_PT_lookdev(bpy.types.Panel):
    bl_label = "Z-A Lookdev Exporter"
    bl_idname = "ZA_PT_lookdev"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Z-A Exporter"

    def draw(self, context):
        layout = self.layout
        scene = context.scene
        layout.label(text="Build {0}".format(BUILD_VERSION), icon="FILE_REFRESH")
        layout.prop(scene, "za_import_scale", text="FBX Scale")
        layout.prop(scene, "za_livelink_host", text="Host")
        layout.prop(scene, "za_livelink_port", text="Port")
        row = layout.row(align=True)
        row.operator(ZA_OT_start_listener.bl_idname, icon="PLAY")
        row.operator(ZA_OT_stop_listener.bl_idname, icon="PAUSE")
        layout.label(text=_status, icon="INFO")
        layout.separator()
        layout.label(text="New packages replace the complete scene.")
        layout.label(text="Unused data is purged after every import.")


classes = (
    ZA_OT_start_listener,
    ZA_OT_stop_listener,
    ZA_PT_lookdev,
)


def register():
    for cls in classes:
        _safe_register(cls)
    _unregister_properties()
    bpy.types.Scene.za_import_scale = bpy.props.FloatProperty(
        name="Z-A FBX Scale",
        default=1.0,
        min=0.000001,
        precision=4,
    )
    bpy.types.Scene.za_livelink_host = bpy.props.StringProperty(
        name="Z-A LiveLink Host",
        default=LIVELINK_HOST,
    )
    bpy.types.Scene.za_livelink_port = bpy.props.IntProperty(
        name="Z-A LiveLink Port",
        default=LIVELINK_PORT,
        min=1,
        max=65535,
    )


def unregister():
    _stop_listener()
    _unregister_properties()
    for cls in reversed(classes):
        _safe_unregister(cls)


def _unregister_properties():
    for name in ("za_import_scale", "za_livelink_host", "za_livelink_port"):
        if hasattr(bpy.types.Scene, name):
            delattr(bpy.types.Scene, name)


def _safe_register(cls):
    old = getattr(bpy.types, cls.__name__, None)
    if old:
        try:
            bpy.utils.unregister_class(old)
        except Exception:
            pass
    try:
        bpy.utils.register_class(cls)
    except ValueError:
        pass


def _safe_unregister(cls):
    old = getattr(bpy.types, cls.__name__, cls)
    try:
        bpy.utils.unregister_class(old)
    except Exception:
        pass


if __name__ == "__main__":
    register()
