# -*- coding: utf-8 -*-
"""aiVolume VDB references as Unreal sparse volume textures.

Unreal reads .vdb as a **SparseVolumeTexture** and renders it through a
``HeterogeneousVolume`` actor, both of which this engine build has -- probed
rather than assumed, because neither existed before 5.2 and the receiver claims
5.8.

As with standins the file is referenced, not copied, so a VDB that is not on
disk leaves an anchor with its path on it instead of nothing.

Unreal needs a material to shade a heterogeneous volume and this build does not
generate one, so the volume arrives with its asset attached and its shading left
at whatever the actor defaults to. That is reported: a volume that renders as
nothing looks identical to a volume that did not arrive.
"""

import os

import unreal

from .constants import CONTENT_ROOT
from .objects import record_metadata, spawn
from .utils import resolve_recorded_path, safe_asset_name


FOLDER = "mLender Volumes"
VOLUME_CONTENT_PATH = CONTENT_ROOT + "/Volumes"


def _import_vdb(path, warnings):
    name = safe_asset_name(
        os.path.splitext(os.path.basename(path))[0], "Volume"
    )
    destination = "{0}/{1}".format(VOLUME_CONTENT_PATH, name)
    if unreal.EditorAssetLibrary.does_asset_exist(destination):
        existing = unreal.EditorAssetLibrary.load_asset(destination)
        if existing is not None:
            return existing

    task = unreal.AssetImportTask()
    task.filename = path
    task.destination_path = VOLUME_CONTENT_PATH
    task.destination_name = name
    task.automated = True
    task.replace_existing = True
    task.save = False
    unreal.AssetToolsHelpers.get_asset_tools().import_asset_tasks([task])
    for imported in task.imported_object_paths or []:
        asset = unreal.EditorAssetLibrary.load_asset(imported)
        if asset is not None:
            return asset
    return None


def _attach_volume(actor, asset, warnings, label):
    """Put the sparse volume texture on the actor's volume component."""
    component = None
    for name in ("HeterogeneousVolumeComponent",):
        cls = getattr(unreal, name, None)
        if cls is None:
            continue
        try:
            component = actor.get_component_by_class(cls)
        except Exception:
            component = None
        if component is not None:
            break
    if component is None:
        warnings.append(
            'Volume "{0}" has no volume component on its actor, so its VDB '
            "could not be attached.".format(label)
        )
        return False
    for key in ("volume", "sparse_volume_texture", "volume_texture"):
        try:
            component.set_editor_property(key, asset)
            return True
        except Exception:
            continue
    warnings.append(
        'Volume "{0}" imported its VDB but the component would not take it; '
        "this engine names that property something else.".format(label)
    )
    return False


def import_volumes(package_data, unreal_scale, package_folder, warnings):
    records = list((package_data or {}).get("volumes") or [])
    created = 0
    loaded = 0

    for record in records:
        label = (
            record.get("volume_full_name") or record.get("volume") or "Volume"
        )
        raw_path = str(record.get("file_path") or "").strip()
        path, _repointed = resolve_recorded_path(raw_path, package_folder)
        asset = None
        try:
            if os.path.isfile(path):
                asset = _import_vdb(path, warnings)
                if asset is None:
                    warnings.append(
                        'Volume "{0}" could not import "{1}" as a sparse '
                        "volume texture; it arrived as an anchor.".format(
                            label, raw_path
                        )
                    )
            else:
                warnings.append(
                    'Volume "{0}" points at "{1}", which is not on disk; it '
                    "arrived as an anchor.".format(label, raw_path)
                )

            if asset is not None:
                actor_class = getattr(unreal, "HeterogeneousVolume", None)
                if actor_class is None:
                    actor_class = unreal.Actor
                actor = spawn(
                    actor_class, record, unreal_scale, label, FOLDER
                )
                if _attach_volume(actor, asset, warnings, label):
                    loaded += 1
                    warnings.append(
                        'Volume "{0}" arrived with its VDB attached but no '
                        "volume material; this build does not generate one, so "
                        "check its shading.".format(label)
                    )
            else:
                actor = spawn(unreal.Actor, record, unreal_scale, label, FOLDER)

            record_metadata(actor, (
                ("volume_file", raw_path),
                ("volume_grids", record.get("grids")),
                ("volume_frame", record.get("frame")),
                ("volume_step_size", record.get("step_size")),
                ("volume_velocity_grids", record.get("velocity_grids")),
            ))
            if record.get("use_frame_extension"):
                warnings.append(
                    'Volume "{0}" is a per-frame VDB sequence in Maya; this '
                    "build attaches the single frame the package "
                    "recorded.".format(label)
                )
            created += 1
        except Exception as exc:
            warnings.append(
                'Volume "{0}" could not be created: {1}'.format(label, exc)
            )

    return {"volume_count": created, "volume_loaded": loaded}
