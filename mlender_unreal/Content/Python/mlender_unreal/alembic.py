# -*- coding: utf-8 -*-
"""The package's Alembic cache, which holds what the FBX deliberately does not.

This is not an optional extra. When the export caches, the deforming meshes and
the emitting particles go into the .abc **instead of** the FBX, so without this
module those objects are simply absent from the level -- the exact silent loss
this project exists to avoid.

Unreal reads .abc as a **GeometryCache**, and ``GeometryCacheActor`` already
carries the component for it, so no component plumbing is needed.

The axis and scale conversion is Unreal's own ``AbcConversionPreset.MAYA``:
probed, that preset is scale (1, -1, 1) with a 90 degree rotation about X and
flip_v on. It is set explicitly rather than left to the default, because a
default that differs between engine versions is how the same package comes in
looking different -- the same rule that makes the Blender receiver set
Subsurface Scale by hand.
"""

import os

import unreal

from .constants import CONTENT_ROOT, GENERATED_TAG
from .utils import resolve_recorded_path, safe_asset_name


FOLDER = "mLender Import/mLender Cache"
CACHE_CONTENT_PATH = CONTENT_ROOT + "/Caches"

# What the importer calls a slot the Alembic gave no face set name. Measured:
# a mesh with a single shading group produces exactly one of these, and a mesh
# split between shaders produces named slots instead.
NO_FACE_SET = "NoFaceSetName"


def _conversion(settings, warnings):
    """Ask for Maya's conversion by name rather than writing the numbers.

    Unreal ships the preset, so the numbers have one authority. Writing
    (1, -1, 1) and 90 degrees here as literals would be a second copy to keep
    in step with the engine.
    """
    preset = getattr(unreal, "AbcConversionPreset", None)
    if preset is None or not hasattr(preset, "MAYA"):
        warnings.append(
            "This engine exposes no Maya Alembic conversion preset, so the "
            "cache may arrive on the wrong axis."
        )
        return
    try:
        conversion = settings.get_editor_property("conversion_settings")
        conversion.set_editor_property("preset", preset.MAYA)
        settings.set_editor_property("conversion_settings", conversion)
    except Exception as exc:
        warnings.append(
            "The Alembic conversion preset could not be set ({0}); the cache "
            "may arrive on the wrong axis.".format(exc)
        )


def _import_cache(path, warnings):
    name = safe_asset_name(
        os.path.splitext(os.path.basename(path))[0], "Cache"
    )
    settings = unreal.AbcImportSettings()
    try:
        settings.set_editor_property(
            "import_type", unreal.AlembicImportType.GEOMETRY_CACHE
        )
    except Exception as exc:
        warnings.append(
            "This engine would not accept the Alembic import type: "
            "{0}".format(exc)
        )
        return []
    _conversion(settings, warnings)
    # One track per object rather than the default, which flattens the whole
    # file into a single track with a single material slot. Measured: a cache
    # of six objects arrived as one slot, so every object in it would wear
    # whichever material happened to be assigned to that slot.
    try:
        geometry = settings.get_editor_property("geometry_cache_settings")
        geometry.set_editor_property("flatten_tracks", False)
        settings.set_editor_property("geometry_cache_settings", geometry)
    except Exception as exc:
        warnings.append(
            "The Alembic cache could not be kept as one track per object "
            "({0}); its objects share a single material slot.".format(exc)
        )

    task = unreal.AssetImportTask()
    task.filename = path
    task.destination_path = CACHE_CONTENT_PATH
    task.destination_name = name
    task.automated = True
    task.replace_existing = True
    task.save = False
    task.options = settings
    unreal.AssetToolsHelpers.get_asset_tools().import_asset_tasks([task])

    caches = []
    seen = set()
    for imported in task.imported_object_paths or []:
        # The task reports the same asset more than once; measured.
        if imported in seen:
            continue
        seen.add(imported)
        asset = unreal.EditorAssetLibrary.load_asset(imported)
        if asset is None:
            continue
        if asset.get_class().get_name() == "GeometryCache":
            caches.append(asset)
    return caches


def cache_component(actor):
    """The component holding the cache, however this engine exposes it."""
    component = getattr(actor, "geometry_cache_component", None)
    if component is not None:
        return component
    try:
        return actor.get_component_by_class(unreal.GeometryCacheComponent)
    except Exception:
        return None


def track_key(name):
    """A track name reduced to the Maya shape it came from.

    Measured: ``simCubeShape`` arrives as ``simCubeShape_0``. The trailing
    index is the importer's, not Maya's.
    """
    text = str(name or "")
    parts = text.rsplit("_", 1)
    if len(parts) == 2 and parts[1].isdigit():
        text = parts[0]
    return safe_asset_name(text)


def cached_records(package_data):
    """The mesh records the cache carries, keyed by the shape name it uses."""
    index = {}
    for record in (package_data or {}).get("meshes") or []:
        if not record.get("alembic"):
            continue
        for key in (record.get("shape"), record.get("mesh"),
                    record.get("mesh_full_name")):
            if key:
                index.setdefault(safe_asset_name(str(key)), record)
    return index


def _slot_names(cache, component):
    try:
        return [str(name) for name in
                (cache.get_editor_property("material_slot_names") or [])]
    except Exception:
        pass
    try:
        return [""] * component.get_num_materials()
    except Exception:
        return []


def _track_keys(cache):
    try:
        return [track_key(track.get_name())
                for track in (cache.get_editor_property("tracks") or [])]
    except Exception:
        return []


def _material_for(item, material_cache, package_folder, build_material,
                  warnings):
    key = item.get("material_full_name") or item.get("material") or ""
    material = material_cache.get(key)
    if material is None:
        material = build_material(item, package_folder, warnings)
        material_cache[key] = material
    return material


def assign_cache_materials(actor, cache, package_data, material_cache,
                           package_folder, build_material, warnings):
    """Give a cache the materials the JSON says its objects had.

    A cached mesh never went through the FBX, so nothing has matched it to a
    Maya material record and its slots hold the world grid checker. Two things
    were measured to make this possible: the slot of a mesh split between
    shaders is named after the shading group, and the slots run in track
    order. So a named slot is looked up by name -- position independent -- and
    an unnamed one, which only a single-material object produces, is resolved
    by walking the tracks alongside the slots.
    """
    component = cache_component(actor)
    if component is None:
        return 0
    slots = _slot_names(cache, component)
    tracks = _track_keys(cache)
    records = cached_records(package_data)
    by_shading_engine = {}
    for record in records.values():
        for item in record.get("materials") or []:
            engine = item.get("shading_engine")
            if engine:
                by_shading_engine.setdefault(safe_asset_name(str(engine)), item)

    assigned = 0
    unmatched = []
    slot_index = 0
    track_index = 0
    while slot_index < len(slots):
        record = None
        if track_index < len(tracks):
            record = records.get(tracks[track_index])
        items = [
            item for item in ((record or {}).get("materials") or [])
            if item.get("material")
        ]
        # A mesh with one shading group writes no face set, so it owns exactly
        # one slot; a split mesh owns one per shading group.
        span = len(items) if len(items) > 1 else 1
        for offset in range(span):
            index = slot_index + offset
            if index >= len(slots):
                break
            item = by_shading_engine.get(safe_asset_name(slots[index]))
            if item is None and len(items) == 1:
                item = items[0]
            if item is None:
                unmatched.append(slots[index] or str(index))
                continue
            try:
                component.set_material(
                    index,
                    _material_for(item, material_cache, package_folder,
                                  build_material, warnings),
                )
                assigned += 1
            except Exception as exc:
                warnings.append(
                    'The cached object in slot {0} could not take its '
                    "material: {1}".format(index, exc)
                )
        slot_index += span
        track_index += 1
        if track_index > len(tracks) and slot_index < len(slots):
            break
    if unmatched:
        warnings.append(
            "{0} slot(s) on the Alembic cache matched no Maya material and "
            "kept the placeholder: {1}".format(
                len(unmatched), ", ".join(sorted(set(unmatched))[:6])
            )
        )
    return assigned


def import_alembic(package_data, package_folder, material_cache, warnings,
                   build_material=None):
    """Import the package cache and put it in the level.

    The cache is authored in world space by the exporter's AbcExport call, so
    the actor sits at the origin unscaled: placing it by a transform would move
    the geometry twice.
    """
    record = (package_data or {}).get("alembic") or {}
    raw_path = str(record.get("file") or "").strip()
    if not raw_path:
        return {"alembic_count": 0, "alembic_materials": 0}

    path, _repointed = resolve_recorded_path(raw_path, package_folder)
    if not os.path.isfile(path):
        warnings.append(
            "The package names an Alembic cache at \"{0}\" which is not on "
            "disk. The {1} cached mesh(es) and {2} cached particle system(s) "
            "are NOT in the level -- they were never in the FBX.".format(
                raw_path, record.get("mesh_count") or 0,
                record.get("particle_count") or 0,
            )
        )
        return {"alembic_count": 0, "alembic_materials": 0}

    caches = _import_cache(path, warnings)
    if not caches:
        warnings.append(
            "The Alembic cache \"{0}\" could not be imported, so the {1} "
            "cached mesh(es) it holds are missing from the level.".format(
                raw_path, record.get("mesh_count") or 0
            )
        )
        return {"alembic_count": 0, "alembic_materials": 0}

    created = 0
    assigned = 0
    for cache in caches:
        label = cache.get_name()
        try:
            actor = unreal.EditorLevelLibrary.spawn_actor_from_class(
                unreal.GeometryCacheActor,
                unreal.Vector(0.0, 0.0, 0.0),
                unreal.Rotator(0.0, 0.0, 0.0),
            )
            component = getattr(actor, "geometry_cache_component", None)
            applied = False
            if component is not None:
                setter = getattr(component, "set_geometry_cache", None)
                if callable(setter):
                    try:
                        setter(cache)
                        applied = True
                    except Exception:
                        pass
                if not applied:
                    try:
                        component.set_editor_property("geometry_cache", cache)
                        applied = True
                    except Exception:
                        pass
            if not applied:
                warnings.append(
                    'The Alembic cache "{0}" imported but the actor would not '
                    "take it.".format(label)
                )
                continue
            actor.set_actor_label(safe_asset_name(label, "Cache"))
            try:
                actor.set_folder_path(FOLDER)
                actor.tags = [GENERATED_TAG]
            except Exception:
                pass
            if build_material is not None:
                assigned += assign_cache_materials(
                    actor, cache, package_data, material_cache,
                    package_folder, build_material, warnings,
                )
            created += 1
        except Exception as exc:
            warnings.append(
                'The Alembic cache "{0}" could not be placed: {1}'.format(
                    label, exc
                )
            )

    if created and record.get("particle_count"):
        warnings.append(
            "The Alembic cache carries {0} cached particle system(s). They "
            "arrive inside the geometry cache rather than as a particle "
            "system.".format(record.get("particle_count"))
        )
    return {"alembic_count": created, "alembic_materials": assigned}
