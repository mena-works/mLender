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

from .constants import (
    CACHE_RESIDENT_BUDGET_MB,
    CONTENT_ROOT,
    GENERATED_TAG,
)
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


def _material_for(item, material_cache, package_folder, build_material,
                  warnings):
    key = item.get("material_full_name") or item.get("material") or ""
    material = material_cache.get(key)
    if material is None:
        material = build_material(item, package_folder, warnings)
        material_cache[key] = material
    return material


def ordered_cached_records(package_data):
    """The cached mesh records in the order the cache lists them.

    By full DAG path, which was fitted rather than assumed. The named slots
    are ground truth -- a slot called ``foo_shdSG`` belongs to whichever
    object carries that shading group -- so each candidate order can be scored
    by how many of them land on the right object. On a 574 object shot with
    122 named slots: by path, 122 right and none wrong; by leaf name, 34
    right and 88 wrong, whether or not case was folded, and the same for the
    order the JSON happens to list.

    The reader walks the hierarchy, in other words, and a leaf name says
    nothing about where in that walk its object sits.
    """
    records = [
        record for record in (package_data or {}).get("meshes") or []
        if record.get("alembic")
    ]
    return sorted(
        records,
        key=lambda record: str(
            record.get("mesh_path") or record.get("mesh") or ""
        ),
    )


def _record_materials(record):
    return [
        item for item in ((record or {}).get("materials") or [])
        if item.get("material")
    ]


def assign_cache_materials(actor, cache, package_data, material_cache,
                           package_folder, build_material, warnings):
    """Give a cache the materials the JSON says its objects had.

    A cached mesh never went through the FBX, so nothing has matched it to a
    Maya material record and its slots hold the world grid checker.

    Two measurements make this possible. A mesh split between shaders gets one
    slot per shading group, named after it, and a mesh with a single shader
    gets one unnamed slot; and the slots run in the order the reader walks the
    hierarchy, which is the order of the full DAG paths.

    So position places each slot and the names check the placing rather than
    driving it. Driving by name was tried and is wrong: a shading group is
    routinely shared by many objects, so a name says which *material* a slot
    holds and never which object it belongs to.
    """
    component = cache_component(actor)
    if component is None:
        return 0
    slots = _slot_names(cache, component)
    if not slots:
        return 0
    records = ordered_cached_records(package_data)

    assigned = 0
    unmatched = []
    disagreed = 0
    slot_index = 0
    for record in records:
        if slot_index >= len(slots):
            break
        items = _record_materials(record)
        span = len(items) if len(items) > 1 else 1
        for offset in range(span):
            if slot_index >= len(slots):
                break
            name = safe_asset_name(str(slots[slot_index]))
            item = None
            if name and name != NO_FACE_SET:
                for candidate in items:
                    engine = safe_asset_name(
                        str(candidate.get("shading_engine") or "")
                    )
                    if engine and engine == name:
                        item = candidate
                        break
                if item is None:
                    # The slot names a shading group this object does not
                    # carry, so the walk and the file disagree about where
                    # this slot belongs.
                    disagreed += 1
            if item is None and items:
                item = items[offset] if offset < len(items) else items[0]
            if item is None:
                unmatched.append(str(slots[slot_index]) or str(slot_index))
                slot_index += 1
                continue
            try:
                component.set_material(
                    slot_index,
                    _material_for(item, material_cache, package_folder,
                                  build_material, warnings),
                )
                assigned += 1
            except Exception as exc:
                warnings.append(
                    "The cached object in slot {0} could not take its "
                    "material: {1}".format(slot_index, exc)
                )
            slot_index += 1
    while slot_index < len(slots):
        unmatched.append(str(slots[slot_index]) or str(slot_index))
        slot_index += 1

    if unmatched:
        # Counted, not sampled. An earlier version stopped walking when the
        # tracks ran out and reported one unmatched slot while 441 of them
        # were still wearing the world grid checker.
        warnings.append(
            "{0} of the {1} slot(s) on the Alembic cache matched no Maya "
            "material and kept the placeholder: {2}".format(
                len(unmatched), len(slots),
                ", ".join(sorted(set(unmatched))[:6])
            )
        )
    if disagreed:
        warnings.append(
            "{0} material slot(s) on the cache name a shader their object "
            "does not use, so some cached objects may be wearing each "
            "other's materials.".format(disagreed)
        )
    return assigned


def _console(command):
    try:
        world = unreal.EditorLevelLibrary.get_editor_world()
        unreal.SystemLibrary.execute_console_command(world, command)
        return True
    except Exception:
        return False


def keep_the_cache_resident(seconds, megabytes, warnings):
    """Widen the streaming window to the shot, now and for next time.

    Unreal streams a geometry cache five seconds ahead and two and a half
    behind. A shot longer than that plays back by teleporting between
    whichever parts happen to be resident, while scrubbing looks perfect
    because it gives the streamer time to catch up. Measured on a 431 MB,
    21.7 second cache: the log fills with "Tried to map an unavailabe
    non-requested chunk".

    The window is set to the shot rather than to a number picked here, and it
    is written into the project so the next session starts that way. Past a
    couple of gigabytes it is left alone and said out loud instead: keeping
    the whole thing resident is the fix, and it is only a fix while it fits
    in memory.
    """
    if seconds <= 0:
        return False
    if megabytes > CACHE_RESIDENT_BUDGET_MB:
        warnings.append(
            "The cache is {0} MB, too much to keep resident, so playback may "
            "jump while it streams. Scrubbing shows the truth; for a render, "
            "set GeometryCache.Streamer.BlockTillFinishStreaming 1.".format(
                megabytes)
        )
        return False

    window = round(seconds + 1.0, 2)
    settings = (
        ("GeometryCache.LookaheadSeconds", window),
        ("GeometryCache.TrailingSeconds", window),
        ("GeometryCache.PrefetchSeconds", min(window, 2.0)),
    )
    for name, value in settings:
        _console("{0} {1:g}".format(name, value))

    written = _write_project_settings(settings, warnings)
    warnings.append(
        "The cache is {0} MB over {1:g} seconds, so the streaming window was "
        "widened to cover it{2}. Without that, playback jumps between the "
        "parts that happen to be resident while scrubbing looks "
        "right.".format(megabytes, seconds,
                         " and written to DefaultEngine.ini" if written
                         else " for this session only")
    )
    return True


def _write_project_settings(settings, warnings):
    """Put the console variables in the project's own config.

    Only these keys, and only under [SystemSettings]: a config file carries
    everything else the project is, and an importer rewriting any of that
    would be a worse bargain than a cache that stutters.
    """
    try:
        path = os.path.join(
            unreal.Paths.convert_relative_path_to_full(
                unreal.Paths.project_config_dir()),
            "DefaultEngine.ini",
        )
    except Exception:
        return False
    try:
        text = ""
        if os.path.isfile(path):
            handle = open(path, "r")
            try:
                text = handle.read()
            finally:
                handle.close()
        lines = text.splitlines()
        wanted = dict(("{0}=".format(name), "{0}={1:g}".format(name, value))
                      for name, value in settings)
        kept = []
        for line in lines:
            stripped = line.strip()
            if any(stripped.startswith(key) for key in wanted):
                continue
            kept.append(line)
        if "[SystemSettings]" not in kept:
            kept.append("")
            kept.append("[SystemSettings]")
        index = kept.index("[SystemSettings]") + 1
        for line in reversed(list(wanted.values())):
            kept.insert(index, line)
        handle = open(path, "w")
        try:
            handle.write("\n".join(kept) + "\n")
        finally:
            handle.close()
        return True
    except Exception as exc:
        warnings.append(
            "The streaming settings could not be written to the project "
            "config ({0}); they hold for this session only.".format(exc)
        )
        return False


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

    if created:
        # A cache is streamed, and the default window is five seconds ahead.
        # A shot longer than that plays back by teleporting between the parts
        # that happen to be resident -- measured on a 431 MB, 21.7 second
        # cache, whose log filled with "Tried to map an unavailabe
        # non-requested chunk". Scrubbing looks right because it gives the
        # streamer time; playing does not.
        megabytes = 0
        try:
            megabytes = int(os.path.getsize(path) / 1048576)
        except Exception:
            pass
        seconds = 0.0
        for cache in caches:
            try:
                seconds = max(seconds, float(
                    cache.get_editor_property("end_frame")
                    - cache.get_editor_property("start_frame")) / 24.0)
            except Exception:
                continue
        keep_the_cache_resident(seconds, megabytes, warnings)

    if created and record.get("particle_count"):
        warnings.append(
            "The Alembic cache carries {0} cached particle system(s). They "
            "arrive inside the geometry cache rather than as a particle "
            "system.".format(record.get("particle_count"))
        )
    return {"alembic_count": created, "alembic_materials": assigned}
