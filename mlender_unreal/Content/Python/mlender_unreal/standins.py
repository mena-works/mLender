# -*- coding: utf-8 -*-
"""aiStandIn and gpuCache references, rebuilt where Unreal can read the file.

The package references these rather than copying them -- a standin is routinely
gigabytes -- so what arrives is a path and a bounding box. Three cases, and the
difference is which of them Unreal can actually open:

* ``.abc`` imports as a **GeometryCache**, and ``GeometryCacheActor`` already
  carries the component for it, so no component plumbing is needed. Probed:
  the actor exposes ``geometry_cache_component``.
* ``.usd`` has no stage actor in this engine build (``UsdStageActor`` is absent,
  probed), so it is anchored and reported.
* ``.ass`` nothing outside Arnold reads, which is also true on the Blender side.

An unreadable or missing file leaves an **anchor** at the standin's transform,
sized to the bounding box Maya drew, with the path on it as a tag. That is the
same decision the Blender receiver makes, and for the same reason: a package
opened on another machine legitimately lands here, and an empty space with no
explanation is worse than a box with a path on it.
"""

import os

import unreal

from .constants import CONTENT_ROOT
from .objects import record_metadata, spawn
from .utils import resolve_recorded_path, safe_asset_name, scalar


FOLDER = "mLender Standins"
CACHE_CONTENT_PATH = CONTENT_ROOT + "/Caches"


def _import_alembic(path, warnings):
    """Import an .abc as a GeometryCache asset, or return None."""
    name = safe_asset_name(
        os.path.splitext(os.path.basename(path))[0], "Cache"
    )
    destination = "{0}/{1}".format(CACHE_CONTENT_PATH, name)
    if unreal.EditorAssetLibrary.does_asset_exist(destination):
        existing = unreal.EditorAssetLibrary.load_asset(destination)
        if existing is not None:
            return existing

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
        return None

    task = unreal.AssetImportTask()
    task.filename = path
    task.destination_path = CACHE_CONTENT_PATH
    task.destination_name = name
    task.automated = True
    task.replace_existing = True
    task.save = False
    task.options = settings
    unreal.AssetToolsHelpers.get_asset_tools().import_asset_tasks([task])

    for imported in task.imported_object_paths or []:
        asset = unreal.EditorAssetLibrary.load_asset(imported)
        if asset is not None:
            return asset
    return None


def _anchor_extent(record, unreal_scale):
    """Half-size of the box Maya drew, in Unreal units.

    Maya's bounding box, not the file's real size. Measured on the Blender side:
    a headless export reads the default +-1 because nothing has evaluated the
    procedural, and showing a unit box is exactly what Maya shows then.
    """
    low = [scalar(v, -1.0) for v in (record.get("bounds_min") or [-1, -1, -1])]
    high = [scalar(v, 1.0) for v in (record.get("bounds_max") or [1, 1, 1])]
    while len(low) < 3:
        low.append(-1.0)
    while len(high) < 3:
        high.append(1.0)
    # Maya Y and Z swap on the way to Unreal, like every other axis pair here.
    return (
        abs(high[0] - low[0]) * 0.5 * unreal_scale,
        abs(high[2] - low[2]) * 0.5 * unreal_scale,
        abs(high[1] - low[1]) * 0.5 * unreal_scale,
    )


def import_standins(package_data, unreal_scale, package_folder, warnings):
    records = list((package_data or {}).get("standins") or [])
    created = 0
    loaded = 0

    for record in records:
        label = (
            record.get("standin_full_name") or record.get("standin")
            or "Standin"
        )
        raw_path = str(record.get("file_path") or "").strip()
        path, _repointed = resolve_recorded_path(raw_path, package_folder)
        extension = os.path.splitext(path)[1].lower()
        asset = None

        try:
            if extension == ".abc" and os.path.isfile(path):
                asset = _import_alembic(path, warnings)
            elif extension in (".usd", ".usda", ".usdc", ".usdz"):
                warnings.append(
                    'Standin "{0}" is USD; this engine build has no stage '
                    "actor, so it arrived as an anchor at its transform "
                    "with the path recorded.".format(label)
                )
            elif extension == ".ass":
                warnings.append(
                    'Standin "{0}" is an Arnold .ass, which nothing outside '
                    "Arnold reads; it arrived as an anchor.".format(label)
                )
            elif not os.path.isfile(path):
                warnings.append(
                    'Standin "{0}" points at "{1}", which is not on disk; it '
                    "arrived as an anchor.".format(label, raw_path)
                )

            if asset is not None:
                actor = spawn(
                    unreal.GeometryCacheActor, record, unreal_scale, label,
                    FOLDER,
                )
                component = actor.geometry_cache_component
                if component is None:
                    component = actor.get_component_by_class(
                        unreal.GeometryCacheComponent
                    )
                applied = False
                if component is not None:
                    for setter in ("set_geometry_cache",):
                        function = getattr(component, setter, None)
                        if callable(function):
                            try:
                                function(asset)
                                applied = True
                                break
                            except Exception:
                                pass
                    if not applied:
                        try:
                            component.set_editor_property(
                                "geometry_cache", asset
                            )
                            applied = True
                        except Exception:
                            pass
                if not applied:
                    warnings.append(
                        'Standin "{0}" imported its cache but the actor would '
                        "not take it.".format(label)
                    )
                else:
                    loaded += 1
            else:
                actor = spawn(
                    unreal.Actor, record, unreal_scale, label, FOLDER
                )
                extent = _anchor_extent(record, unreal_scale)
                record_metadata(actor, (
                    ("standin_extent", ",".join(
                        "{0:.3f}".format(v) for v in extent
                    )),
                ))

            record_metadata(actor, (
                ("standin_file", raw_path),
                ("standin_node_type", record.get("node_type")),
                ("standin_frame", record.get("frame")),
                ("standin_object_path", record.get("object_path")),
            ))
            created += 1
        except Exception as exc:
            warnings.append(
                'Standin "{0}" could not be created: {1}'.format(label, exc)
            )

    return {"standin_count": created, "standin_loaded": loaded}
