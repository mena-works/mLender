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


def _assign_materials(actor, material_cache, warnings, label):
    """Give the cache our rebuilt materials where the names line up.

    A cached mesh never went through the FBX, so nothing has matched it to a
    Maya material record. Its slots carry the names Maya gave them, which is
    enough to look ours up.
    """
    component = getattr(actor, "geometry_cache_component", None)
    if component is None:
        try:
            component = actor.get_component_by_class(
                unreal.GeometryCacheComponent
            )
        except Exception:
            component = None
    if component is None:
        return 0
    assigned = 0
    try:
        count = component.get_num_materials()
    except Exception:
        return 0
    for index in range(count):
        try:
            existing = component.get_material(index)
        except Exception:
            continue
        slot = safe_asset_name(existing.get_name() if existing else "")
        for key, material in material_cache.items():
            if safe_asset_name(str(key)) == slot:
                try:
                    component.set_material(index, material)
                    assigned += 1
                except Exception:
                    pass
                break
    if count and not assigned:
        warnings.append(
            'The Alembic cache "{0}" kept its own materials; none of its {1} '
            "slot(s) matched a Maya material this import rebuilt.".format(
                label, count
            )
        )
    return assigned


def import_alembic(package_data, package_folder, material_cache, warnings):
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
            assigned += _assign_materials(
                actor, material_cache, warnings, label
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
