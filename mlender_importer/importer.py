# -*- coding: utf-8 -*-
"""Package import orchestration.

Importing a package replaces the entire Blender file. That is the tool's
design, not an accident: the Maya scene is the single source of truth and a
merge would leave stale materials and lights behind.
"""

import bpy

from .constants import SUPPORTED_SCHEMA_VERSIONS
from .attributes import apply_custom_attributes
from .cameras import import_cameras
from .curves import import_curves
from .empties import import_empties
from .fbx import import_fbx, read_package_json, resolve_fbx_path
from .alembic import cached_particle_names, import_alembic
from .animation import animate_visibility, apply_scene_range
from .colormanagement import apply_color_management
from .lights import import_lights
from .merge import (
    IMPORT_MODE_MERGE,
    IMPORT_MODE_REPLACE,
    adopt,
    clear_rebuilt_objects,
    generated_objects_by_path,
    mark_stale,
    normalize_mode,
)
from .render import apply_render_settings
from .sets import import_sets
from .particles import import_particles
from .volumes import import_volumes
from .materials import apply_face_assignments, build_material
from .scene import (
    add_subdivision_modifiers,
    apply_visibility,
    build_record_index,
    clear_scene_and_purge,
    find_mesh_record,
    place_group_empties,
    link_instance_duplicates,
    organize_imported_objects,
    seed_group_cache,
    place_in_group,
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


def import_scene_package(
    package_folder,
    package_data=None,
    import_scale=1.0,
    power_scale=None,
    import_mode=None,
):
    package_folder = normalize_folder(package_folder)
    if package_data is None:
        package_data = read_package_json(package_folder)
    validate_schema_version(package_data)
    fbx_path = resolve_fbx_path(package_folder, package_data)

    if bpy.data.filepath:
        bpy.ops.wm.save_mainfile()

    mode = normalize_mode(import_mode)
    # Only Replace clears. Merge and Add skip the wipe; neither weakens
    # the check inside it, which still raises if a clear leaves anything.
    existing_by_path = {}
    if mode == IMPORT_MODE_REPLACE:
        clear_scene_and_purge()
    elif mode == IMPORT_MODE_MERGE:
        # Empties, curves, volumes and cached objects are rebuilt rather
        # than adopted, so the previous ones go or they accumulate with
        # every send. This runs first: indexing before the clear left the
        # index holding objects that no longer exist, and adoption then
        # raised ReferenceError on the first one it reached.
        clear_rebuilt_objects()
        # Recorded before the FBX lands, or the new objects would be in it.
        existing_by_path = generated_objects_by_path()

    # Materials carrying a fake user survive the purge, so the pre-import set
    # is recorded and those materials are left alone afterwards.
    before_objects = set(bpy.data.objects)
    before_materials = set(bpy.data.materials)
    warnings = []
    import_fbx(fbx_path, import_scale)
    # The cache goes in before anything is matched, so its objects are
    # organised, named and given materials by the same passes as the rest.
    alembic_count = import_alembic(
        package_folder, package_data, import_scale, warnings
    )
    imported_objects = [
        obj for obj in bpy.data.objects if obj not in before_objects
    ]
    # A cached particle system is not a scene mesh, whichever datablock this
    # Blender chose for it: measured, 4.1 lands it as a MESH and 4.5 onward
    # as a POINTCLOUD, and counting by type alone made the same package
    # report a different mesh count on different versions.
    cached_particles = cached_particle_names(package_data)
    imported_meshes = [
        obj for obj in imported_objects
        if obj.type == "MESH" and obj.name not in cached_particles
    ]
    if not imported_meshes and not alembic_count:
        raise RuntimeError("FBX import produced no mesh objects.")

    # The frame range is set before anything is keyed, so the keys land inside
    # a range the user can actually scrub.
    animated = apply_scene_range(package_data)
    root_collection = organize_imported_objects(
        imported_objects, reuse=mode == IMPORT_MODE_MERGE
    )
    material_cache = {}
    assignments = []
    mesh_records = list(package_data.get("meshes") or [])
    # Indexed once: matching every object against every record, and
    # re-deriving each record's name keys each time, was quadratic.
    record_index = build_record_index(mesh_records)
    used_record_ids = set()
    matched_meshes = []
    adopted_paths = set()
    # Adoption deletes the object the FBX brought, and imported_objects
    # still holds it; touching a removed one afterwards raises.
    retired_objects = []
    # Merge reuses the collections already standing; a fresh cache would
    # build "props.001" beside the props holding the same meshes.
    group_cache = seed_group_cache(root_collection) if (
        mode == IMPORT_MODE_MERGE) else {}
    grouped_count = 0
    visibility_count = 0
    visibility_animation_count = 0
    attribute_count = 0

    for obj in imported_meshes:
        mesh_record = find_mesh_record(obj, record_index, used_record_ids)
        if not mesh_record:
            warnings.append('No Maya mesh record matched "{0}".'.format(obj.name))
            obj.data.materials.clear()
            remove_object_namespace(obj)
            continue
        used_record_ids.add(id(mesh_record))
        # In Merge the object already standing keeps its identity, so any
        # modifier or parent the user put on it survives the update.
        obj = adopt(obj, mesh_record, existing_by_path, retired_objects)
        adopted_paths.add(mesh_record.get("mesh_path"))
        rename_mesh_from_record(obj, mesh_record)
        matched_meshes.append((obj, mesh_record))
        if place_in_group(obj, mesh_record, root_collection, group_cache):
            grouped_count += 1
        if apply_visibility(obj, mesh_record):
            visibility_count += 1
        # After the static flags, so a mesh that blinks ends up keyed rather
        # than pinned to whatever it was on the exported frame.
        if animate_visibility(obj, mesh_record):
            visibility_animation_count += 1
        assignments.append(
            assign_mesh_materials(obj, mesh_record, material_cache, warnings)
        )
        attribute_count += apply_custom_attributes(
            obj, mesh_record, warnings
        )

    # After the materials, not before: the assignment writes into obj.data,
    # and instances share a shape in Maya so they share its materials anyway.
    instanced_count = link_instance_duplicates(matched_meshes, mesh_records)

    if retired_objects:
        retired = {id(item) for item in retired_objects}
        imported_objects = [
            item for item in imported_objects if id(item) not in retired
        ]

    # Only what the FBX left mangled. A mesh that matched a record already
    # carries the name the record asked for, and for a referenced asset
    # that name deliberately keeps its namespace: two references of one
    # asset are both "body" without it, and stripping it here undid the
    # only thing telling them apart.
    named_from_record = {id(obj) for obj, _record in matched_meshes}
    namespace_prefixes = package_namespace_prefixes(package_data)
    for obj in imported_objects:
        if id(obj) in named_from_record:
            continue
        remove_object_namespace(obj, namespace_prefixes)

    # Locators and empty nulls, which the FBX never carried. Built after
    # the meshes so a locator parented under one finds it, and sharing the
    # group cache so both land in the same collections.
    object_by_path = {
        record.get("mesh_path"): obj
        for obj, record in matched_meshes if record.get("mesh_path")
    }
    empty_result = import_empties(
        package_data,
        root_collection,
        import_scale,
        warnings,
        group_cache,
        object_by_path,
    )

    curve_count = import_curves(
        package_data,
        root_collection,
        import_scale,
        warnings,
        group_cache,
        object_by_path,
    )

    particle_count, particle_baked_count = import_particles(
        package_data,
        root_collection,
        import_scale,
        warnings,
        group_cache,
        object_by_path,
    )
    volume_count = import_volumes(
        package_data,
        root_collection,
        import_scale,
        warnings,
        group_cache,
        object_by_path,
    )

    # Runs after the empties so both kinds of group transform, the ones the
    # FBX brought and the ones the JSON did, end up in the same place.
    place_group_empties(imported_objects, group_cache)

    # Only meshes that matched a Maya record can say whether they want to be
    # subdivided, so unmatched objects are deliberately left alone.
    subdivision_count = add_subdivision_modifiers(matched_meshes, warnings)
    # Lights are built after the meshes are named, so light linking can
    # resolve its receivers by name.
    mesh_objects = {
        (record.get("mesh") or ""): obj for obj, record in matched_meshes
    }
    light_result = import_lights(
        package_data,
        root_collection,
        import_scale,
        warnings,
        power_scale,
        mesh_objects,
    )

    camera_result = import_cameras(
        package_data,
        root_collection,
        import_scale,
        warnings,
    )

    # Sets and layers name objects that already exist, so this runs after
    # everything that creates them.
    set_result = import_sets(
        package_data, root_collection, object_by_path, warnings
    )

    # Nothing is deleted for having left the package. It is marked and
    # counted; removing it is a button the user presses.
    stale_objects = mark_stale(existing_by_path, adopted_paths)

    view_transform = apply_color_management(package_data, warnings)
    render_applied = apply_render_settings(package_data, warnings)

    _remove_fbx_placeholder_materials(before_materials)
    purge_orphans()

    return {
        "package_folder": package_folder,
        "fbx_path": fbx_path,
        "root_collection": root_collection.name,
        "object_count": len(imported_objects),
        "mesh_count": len(imported_meshes),
        "material_count": len(material_cache),
        "animated": animated,
        "frame_count": int((package_data.get("animation") or {}).get(
            "frame_count", 1
        )),
        "group_collection_count": len(group_cache),
        "visibility_count": visibility_count,
        "visibility_animation_count": visibility_animation_count,
        "view_transform": view_transform,
        "grouped_mesh_count": grouped_count,
        "subdivision_count": subdivision_count,
        "instanced_count": instanced_count,
        "custom_attribute_count": attribute_count,
        "transform_count": empty_result["transform_count"],
        "curve_count": curve_count,
        "volume_count": volume_count,
        "particle_count": particle_count,
        "particle_baked_count": particle_baked_count,
        "alembic_count": alembic_count,
        "render": render_applied,
        "import_mode": mode,
        "stale_count": len(stale_objects),
        "set_count": set_result["set_count"],
        "layer_count": set_result["layer_count"],
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
    is tagged with ml_generated and kept.
    """
    for material in list(bpy.data.materials):
        if material in before_materials:
            continue
        if material.get("ml_generated"):
            continue
        if material.users == 0:
            bpy.data.materials.remove(material)
