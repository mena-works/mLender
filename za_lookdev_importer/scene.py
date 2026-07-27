# -*- coding: utf-8 -*-
"""Scene teardown, object organisation and mesh record matching."""

import bpy

from .constants import (
    DEFAULT_SUBDIV_ITERATIONS,
    MAX_SUBDIV_ITERATIONS,
    PURGED_DATA_COLLECTIONS,
    ROOT_COLLECTION_NAME,
    SUBDIVISION_MODIFIER_NAME,
    SUBDIVISION_SETTINGS,
    SUBDIV_UV_SMOOTHING,
)
from .utils import (
    name_keys,
    namespace_free_import_name,
    namespace_free_name,
)


def clear_scene_and_purge():
    """Remove everything from the file before a new package is imported.

    Three passes are needed: the operator clears the active view layer,
    datablock removal catches hidden, excluded and other-scene objects, and
    batch_remove catches whatever survives. Failing loudly beats importing
    into a half cleared scene.
    """
    try:
        if bpy.context.object and bpy.context.object.mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")
    except Exception:
        pass

    try:
        bpy.ops.object.select_all(action="SELECT")
        bpy.ops.object.delete(use_global=True, confirm=False)
    except Exception:
        pass

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

    for data_name in PURGED_DATA_COLLECTIONS:
        data_collection = getattr(bpy.data, data_name, None)
        if data_collection is None:
            continue
        for item in list(data_collection):
            if getattr(item, "users", 0) == 0:
                try:
                    data_collection.remove(item)
                except Exception:
                    pass
    purge_orphans()


def purge_orphans():
    try:
        bpy.data.orphans_purge(do_recursive=True)
        return
    except Exception:
        pass
    try:
        bpy.ops.outliner.orphans_purge(do_recursive=True)
    except Exception:
        pass


def organize_imported_objects(objects):
    """Move every imported object under a single root collection."""
    root = bpy.data.collections.new(ROOT_COLLECTION_NAME)
    bpy.context.scene.collection.children.link(root)
    for obj in objects:
        for collection in list(obj.users_collection):
            collection.objects.unlink(obj)
        root.objects.link(obj)
    return root


def add_subdivision_modifiers(mesh_records, warnings=None):
    """Subdivide only the meshes whose Maya counterpart asked to be.

    ``mesh_records`` is a sequence of ``(object, record)`` pairs. A mesh with
    no record, or one whose record says subdivision is off, is left alone:
    subdividing everything rounds off hard surface geometry that was never
    modelled smooth.
    """
    modified_count = 0
    warnings = warnings if warnings is not None else []

    for obj, record in mesh_records:
        if obj.type != "MESH":
            continue
        subdivision = (record or {}).get("subdivision") or {}
        if not subdivision.get("enabled"):
            _remove_subdivision(obj)
            continue
        try:
            _apply_subdivision(obj, subdivision)
            modified_count += 1
        except Exception as exc:
            warnings.append(
                'Subdivision could not be added to "{0}": {1}'.format(
                    obj.name,
                    exc,
                )
            )

    return modified_count


def _remove_subdivision(obj):
    modifier = obj.modifiers.get(SUBDIVISION_MODIFIER_NAME)
    if modifier is not None:
        obj.modifiers.remove(modifier)


def _apply_subdivision(obj, subdivision):
    modifier = obj.modifiers.get(SUBDIVISION_MODIFIER_NAME)
    if modifier is not None and modifier.type != "SUBSURF":
        obj.modifiers.remove(modifier)
        modifier = None
    if modifier is None:
        modifier = obj.modifiers.new(
            name=SUBDIVISION_MODIFIER_NAME,
            type="SUBSURF",
        )

    settings = dict(SUBDIVISION_SETTINGS)
    settings["subdivision_type"] = (
        "SIMPLE" if subdivision.get("scheme") == "LINEAR" else "CATMULL_CLARK"
    )
    settings["levels"] = _iterations(subdivision, "viewport_iterations")
    settings["render_levels"] = _iterations(subdivision, "render_iterations")

    uv_smooth = SUBDIV_UV_SMOOTHING.get(
        str(subdivision.get("uv_smoothing") or "").lower()
    )
    if uv_smooth:
        settings["uv_smooth"] = uv_smooth

    for attr, value in settings.items():
        setattr(modifier, attr, value)

    _verify_subdivision(modifier, settings)
    obj.data["za_subdivision_source"] = str(subdivision.get("source") or "")
    return modifier


def _iterations(subdivision, key):
    try:
        value = int(subdivision.get(key, DEFAULT_SUBDIV_ITERATIONS))
    except (TypeError, ValueError):
        value = DEFAULT_SUBDIV_ITERATIONS
    return max(0, min(MAX_SUBDIV_ITERATIONS, value))


def _verify_subdivision(modifier, settings):
    """Confirm the modifier really holds the requested settings.

    Blender silently ignores some assignments across versions, so the values
    are read back rather than assumed.
    """
    if modifier.type != "SUBSURF":
        raise RuntimeError("modifier settings could not be verified")
    for attr, value in settings.items():
        if getattr(modifier, attr, None) != value:
            raise RuntimeError(
                "{0} did not take: wanted {1!r}, got {2!r}".format(
                    attr,
                    value,
                    getattr(modifier, attr, None),
                )
            )


def find_mesh_record(obj, records, used_record_ids):
    """Match an imported object to its Maya mesh record.

    A full-path match outranks a short-name match, because short names repeat
    across namespaces. Records already claimed by another object are skipped.
    """
    object_keys = name_keys(obj.name)
    if obj.data:
        object_keys.update(name_keys(obj.data.name))

    best = None
    best_score = -1
    for record in records:
        if id(record) in used_record_ids:
            continue
        full_keys = name_keys(record.get("mesh_full_name") or "")
        base_keys = name_keys(record.get("mesh") or "")
        score = -1
        if object_keys.intersection(full_keys):
            score = 100
        elif object_keys.intersection(base_keys):
            score = 10
        if score > best_score:
            best = record
            best_score = score
    return best if best_score >= 0 else None


def rename_mesh_from_record(obj, mesh_record):
    clean_name = (
        mesh_record.get("mesh")
        or namespace_free_name(mesh_record.get("mesh_full_name"))
        or namespace_free_name(obj.name)
    )
    if clean_name:
        obj.name = clean_name
        if obj.data:
            obj.data.name = clean_name


def remove_object_namespace(obj, namespace_prefixes=None):
    clean_name = namespace_free_import_name(obj.name, namespace_prefixes)
    if clean_name:
        obj.name = clean_name
    if obj.data:
        clean_data_name = namespace_free_import_name(
            obj.data.name,
            namespace_prefixes,
        )
        if clean_data_name:
            obj.data.name = clean_data_name
