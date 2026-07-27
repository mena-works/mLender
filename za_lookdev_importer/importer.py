# -*- coding: utf-8 -*-
"""Package import orchestration.

Importing a package replaces the entire Blender file. That is the tool's
design, not an accident: the Maya scene is the single source of truth and a
merge would leave stale materials and lights behind.
"""

import bpy

from .constants import SUPPORTED_SCHEMA_VERSIONS
from .cameras import import_cameras
from .fbx import import_fbx, read_package_json, resolve_fbx_path
from .lights import import_lights
from .materials import apply_face_assignments, build_material
from .scene import (
    add_subdivision_modifiers,
    clear_scene_and_purge,
    find_mesh_record,
    organize_imported_objects,
    purge_orphans,
    remove_object_namespace,
    rename_mesh_from_record,
)
from .utils import normalize_folder, package_namespace_prefixes


def validate_schema_version(package_data):
    """Reject a package this build cannot read.

    Checked before the scene is cleared, so an incompatible package costs the
    user nothing.
    """
    if not isinstance(package_data, dict):
        raise ValueError("Package JSON must be an object.")
    # Packages written before the field existed are schema version 1.
    version = package_data.get("schema_version", 1)
    try:
        version = int(version)
    except (TypeError, ValueError):
        raise ValueError(
            "Package schema version is not a number: {0!r}".format(version)
        )
    if version not in SUPPORTED_SCHEMA_VERSIONS:
        raise ValueError(
            "Package schema version {0} is not supported by this build; "
            "expected one of {1}. Update the Blender add-on to match the "
            "Maya exporter.".format(
                version,
                ", ".join(str(item) for item in SUPPORTED_SCHEMA_VERSIONS),
            )
        )
    return version


def import_lookdev_package(
    package_folder,
    package_data=None,
    import_scale=1.0,
    power_scale=None,
):
    package_folder = normalize_folder(package_folder)
    if package_data is None:
        package_data = read_package_json(package_folder)
    validate_schema_version(package_data)
    fbx_path = resolve_fbx_path(package_folder, package_data)

    if bpy.data.filepath:
        bpy.ops.wm.save_mainfile()
    clear_scene_and_purge()

    # Materials carrying a fake user survive the purge, so the pre-import set
    # is recorded and those materials are left alone afterwards.
    before_objects = set(bpy.data.objects)
    before_materials = set(bpy.data.materials)
    import_fbx(fbx_path, import_scale)
    imported_objects = [
        obj for obj in bpy.data.objects if obj not in before_objects
    ]
    imported_meshes = [obj for obj in imported_objects if obj.type == "MESH"]
    if not imported_meshes:
        raise RuntimeError("FBX import produced no mesh objects.")

    root_collection = organize_imported_objects(imported_objects)
    material_cache = {}
    assignments = []
    warnings = []
    mesh_records = list(package_data.get("meshes") or [])
    used_record_ids = set()
    matched_meshes = []

    for obj in imported_meshes:
        mesh_record = find_mesh_record(obj, mesh_records, used_record_ids)
        if not mesh_record:
            warnings.append('No Maya mesh record matched "{0}".'.format(obj.name))
            obj.data.materials.clear()
            remove_object_namespace(obj)
            continue
        used_record_ids.add(id(mesh_record))
        rename_mesh_from_record(obj, mesh_record)
        matched_meshes.append((obj, mesh_record))
        assignments.append(
            assign_mesh_materials(obj, mesh_record, material_cache, warnings)
        )

    namespace_prefixes = package_namespace_prefixes(package_data)
    for obj in imported_objects:
        remove_object_namespace(obj, namespace_prefixes)

    # Only meshes that matched a Maya record can say whether they want to be
    # subdivided, so unmatched objects are deliberately left alone.
    subdivision_count = add_subdivision_modifiers(matched_meshes, warnings)
    light_result = import_lights(
        package_data,
        root_collection,
        import_scale,
        warnings,
        power_scale,
    )

    camera_result = import_cameras(
        package_data,
        root_collection,
        import_scale,
        warnings,
    )

    _remove_fbx_placeholder_materials(before_materials)
    purge_orphans()

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
        "camera_count": camera_result["camera_count"],
        "active_camera": camera_result["active"],
        "assignments": assignments,
        "warnings": warnings,
    }


def assign_mesh_materials(obj, mesh_record, material_cache, warnings):
    """Replace an object's material slots with the rebuilt Maya materials."""
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
            material = build_material(material_record, warnings)
            material_cache[cache_key] = material
        obj.data.materials.append(material)
        assigned_names.append(material.name)

    apply_face_assignments(obj, material_records)
    return {
        "mesh": obj.name,
        "maya_mesh": mesh_record.get("mesh_full_name") or mesh_record.get("mesh"),
        "materials": assigned_names,
    }


def _remove_fbx_placeholder_materials(before_materials):
    """Drop the unused materials the FBX importer created.

    Only untouched, unused datablocks are removed; anything this tool built
    is tagged with za_generated and kept.
    """
    for material in list(bpy.data.materials):
        if material in before_materials:
            continue
        if material.get("za_generated"):
            continue
        if material.users == 0:
            bpy.data.materials.remove(material)
