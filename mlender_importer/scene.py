# -*- coding: utf-8 -*-
"""Scene teardown, object organisation and mesh record matching."""

import bpy

from .constants import (
    DEFAULT_SUBDIV_ITERATIONS,
    HOLDOUT_ATTR,
    MAX_SUBDIV_ITERATIONS,
    OBJECT_VISIBILITY_ATTRS,
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
    safe_name,
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


def organize_imported_objects(objects, reuse=False):
    """Move every imported object under a single root collection.

    ``reuse`` picks up the root an earlier import left, which is what Merge
    wants: a fresh one each time would stack "mLender Import.001" on every
    send. Add deliberately does not reuse, since a new root per package is
    the whole point of that mode.
    """
    root = bpy.data.collections.get(ROOT_COLLECTION_NAME) if reuse else None
    if root is None:
        root = bpy.data.collections.new(ROOT_COLLECTION_NAME)
    if root.name not in bpy.context.scene.collection.children:
        try:
            bpy.context.scene.collection.children.link(root)
        except RuntimeError:
            pass
    for obj in objects:
        for collection in list(obj.users_collection):
            collection.objects.unlink(obj)
        root.objects.link(obj)
    return root


def seed_group_cache(root):
    """Group collections an earlier import made, keyed as the cache keys them.

    Without this a merge builds "props.001" beside the "props" already
    holding the same meshes, because the cache starts empty every import.
    """
    cache = {}
    for collection in bpy.data.collections:
        key = collection.get("ml_maya_group")
        if key:
            cache[key] = collection
    return cache


def group_collection(root, groups, cache):
    """Collection for a Maya group path, creating the trail as needed.

    ``groups`` is outermost first, so "|set|props" nests props inside set.
    ``cache`` maps a path to the collection already made for it, which is what
    stops two meshes in the same Maya group landing in two collections that
    share a name.
    """
    parent = root
    path = []
    for name in groups:
        if not str(name or "").strip():
            continue
        name = safe_name(name)
        path.append(name)
        key = "/".join(path)
        collection = cache.get(key)
        if collection is None:
            collection = bpy.data.collections.new(name)
            collection["ml_generated"] = True
            collection["ml_maya_group"] = key
            parent.children.link(collection)
            cache[key] = collection
        parent = collection
    return parent


def place_in_group(obj, record, root, cache):
    """Link a mesh into the collection mirroring its Maya group path."""
    groups = (record or {}).get("groups") or []
    if not groups:
        return False
    target = group_collection(root, groups, cache)
    if target is root:
        return False
    for collection in list(obj.users_collection):
        collection.objects.unlink(obj)
    target.objects.link(obj)
    return True


def place_group_empties(imported_objects, group_cache):
    """Move an FBX-brought group empty into the collection that mirrors it.

    A Maya group holding meshes arrives twice over: the FBX brings the
    transform as an empty, because it is an ancestor of an exported mesh, and
    the importer builds a collection of the same name for the organisation.
    Both are wanted — a collection cannot hold a transform, and the empty is
    what lets the group still be moved as a unit — but the empty was being
    left at the root while everything it holds sat a level down.

    Returns the number of empties moved.
    """
    moved = 0
    for obj in imported_objects:
        if obj.type != "EMPTY":
            continue
        collection = group_cache.get(safe_name(obj.name))
        if collection is None or collection in obj.users_collection:
            continue
        for current in list(obj.users_collection):
            current.objects.unlink(obj)
        collection.objects.link(obj)
        obj["ml_maya_group"] = obj.name
        moved += 1
    return moved


def link_instance_duplicates(matched_meshes, mesh_records=None):
    """Point every instance of one Maya shape at a single mesh datablock.

    Maya instances share their shape; FBX writes the geometry out once per
    transform, so they arrive as separate meshes holding identical vertices.
    Records carrying the same ``shape_path`` came from the same shape, which
    is what makes them recognisable here.

    Only the datablock is shared. Transform, visibility and collection stay
    per object, exactly as they are in Maya.

    Returns the number of objects re-pointed.
    """
    # Which object owns the shared datablock decides its name, so it is
    # chosen by the record's position in the package, which is Maya's parent
    # order. Taking whichever object the FBX importer happened to create
    # first would name the shared mesh differently between runs.
    rank = {}
    for index, record in enumerate(mesh_records or []):
        rank[id(record)] = index

    by_shape = {}
    for obj, record in matched_meshes:
        shape_path = (record or {}).get("shape_path")
        if not shape_path:
            continue
        by_shape.setdefault(shape_path, []).append(
            (rank.get(id(record), len(rank)), obj)
        )

    linked = 0
    for entries in by_shape.values():
        if len(entries) < 2:
            continue
        objects = [obj for _, obj in sorted(entries, key=lambda e: e[0])]
        master = objects[0].data
        for obj in objects[1:]:
            if obj.data is master:
                continue
            stale = obj.data
            obj.data = master
            obj["ml_instance_of"] = objects[0].name
            linked += 1
            if stale.users == 0:
                bpy.data.meshes.remove(stale)
    return linked


def apply_visibility(obj, record):
    """Rebuild Maya's per-ray visibility and holdout flags on an object.

    The exporter only writes flags that differ from Maya's default, so an
    empty record means "leave Blender's defaults alone" rather than "set
    everything to on".
    """
    visibility = (record or {}).get("visibility") or {}
    if not visibility:
        return False

    changed = False
    for semantic, attr in OBJECT_VISIBILITY_ATTRS.items():
        if semantic not in visibility or not hasattr(obj, attr):
            continue
        try:
            setattr(obj, attr, bool(visibility[semantic]))
            changed = True
        except Exception:
            pass

    if visibility.get("matte") and hasattr(obj, HOLDOUT_ATTR):
        try:
            setattr(obj, HOLDOUT_ATTR, True)
            changed = True
        except Exception:
            pass

    # A mesh hidden in Maya is hidden in both the viewport and the render;
    # hiding only the viewport would still show it in a render.
    if visibility.get("visible") is False:
        obj.hide_render = True
        obj.hide_viewport = True
        changed = True
    elif visibility.get("lod_visible") is False:
        obj.hide_viewport = True
        changed = True
    return changed


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
    obj.data["ml_subdivision_source"] = str(subdivision.get("source") or "")
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


def build_record_index(records):
    """Index mesh records by every name they might be matched on.

    Built once for the whole import. Scanning every record for every object,
    and re-deriving each record's name keys on every scan, was quadratic:
    measured at 1600 meshes, matching alone took 58 of the import's 61
    seconds. Indexing turns the scan into a dictionary lookup.
    """
    index = {}
    for record in records:
        entry = {
            "record": record,
            "full": name_keys(record.get("mesh_full_name") or ""),
            "base": name_keys(record.get("mesh") or ""),
            "groups": [
                name_keys(group) for group in record.get("groups") or []
            ],
        }
        for key in entry["full"] | entry["base"]:
            index.setdefault(key, []).append(entry)
    return index


def find_mesh_record(obj, index, used_record_ids):
    """Match an imported object to its Maya mesh record.

    A full-path match outranks a short-name match, because short names repeat
    across namespaces. Records already claimed by another object are skipped.

    Names alone are not enough. Two meshes called "twin" under different Maya
    groups is ordinary, and both records score identically on name, so an
    arbitrary one used to win: the meshes arrived swapped, each carrying the
    other's materials, visibility and group. The parent chain the FBX brought
    in is what tells them apart, so it breaks the tie.
    """
    object_keys = name_keys(obj.name)
    if obj.data:
        object_keys.update(name_keys(obj.data.name))

    candidates = []
    seen = set()
    for key in object_keys:
        for entry in index.get(key, ()):
            if id(entry) in seen or id(entry["record"]) in used_record_ids:
                continue
            seen.add(id(entry))
            candidates.append(entry)
    if not candidates:
        return None
    if len(candidates) == 1:
        return candidates[0]["record"]

    # Only an ambiguous name needs the parent chain, which is the expensive
    # part; the overwhelmingly common case is a single candidate.
    ancestor_keys = ancestor_name_keys(obj)
    best = None
    best_score = -1
    for entry in candidates:
        score = 100 if object_keys & entry["full"] else 10
        score += group_trail_score(ancestor_keys, entry["groups"])
        if score > best_score:
            best = entry["record"]
            best_score = score
    return best


def ancestor_name_keys(obj):
    """Every spelling of an object's parent names, for group matching."""
    keys = set()
    parent = getattr(obj, "parent", None)
    depth = 0
    # Bounded rather than while-true: a corrupt file with a parent cycle
    # should not hang the import.
    while parent is not None and depth < 64:
        keys.update(name_keys(parent.name))
        parent = getattr(parent, "parent", None)
        depth += 1
    return keys


def group_trail_score(ancestor_keys, group_key_sets):
    """How much of a record's Maya group trail the object's parents confirm.

    ``group_key_sets`` is the record's group names already turned into key
    sets by build_record_index, so this stays out of the hot path.

    Deliberately capped well below the gap between a full-path match and a
    name match, so a deep hierarchy can break a tie without ever outvoting a
    genuine full-path match.
    """
    if not group_key_sets or not ancestor_keys:
        return 0
    matched = sum(
        1 for keys in group_key_sets if keys & ancestor_keys
    )
    return min(matched, 5) * 5


def rename_mesh_from_record(obj, mesh_record):
    """Name the object after its Maya node, and record where it came from.

    The marker and the Maya path are what let a later merge find this same
    object again. Keyed on the path rather than the name because a name can
    be changed in Blender and two meshes can share a short one.
    """
    obj["ml_generated"] = True
    if mesh_record.get("mesh_path"):
        obj["ml_maya_path"] = mesh_record["mesh_path"]
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
