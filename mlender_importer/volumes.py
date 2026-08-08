# -*- coding: utf-8 -*-
"""Arnold volumes rebuilt as Blender volume objects.

Both read the same VDB, so nothing is converted: the path travels and Blender
opens the file itself.

A missing file is built anyway, unlike a missing image plane. Measured on 4.1
and 5.2: Blender accepts the path, reports no grids and raises nothing, so the
volume still marks where it belongs and can be re-pointed. Refusing it would
throw away the placement as well as the file, and VDB paths are routinely
per-frame sequences that resolve elsewhere. The missing file is reported.

Arnold's step size, velocity scale and motion blur are render settings with no
Blender datablock equivalent. They are kept as ``ml_source_*`` so the
difference is visible rather than silently dropped.
"""

import os

import bpy
from mathutils import Matrix, Vector

from .attributes import apply_custom_attributes
from .scene import place_in_group
from .transforms import maya_matrix_to_blender
from .utils import safe_name, scalar


def import_volumes(package_data, root_collection, import_scale, warnings,
                   group_cache, object_by_path=None):
    """Rebuild every volume record. Returns how many were built."""
    records = list(package_data.get("volumes") or [])
    if not records:
        return 0

    meters_per_unit = scalar(package_data.get("meters_per_maya_unit"), 0.01)
    position_scale = meters_per_unit * max(scalar(import_scale, 1.0), 0.000001)

    built = 0
    for record in records:
        try:
            obj = _build_volume(record, root_collection, position_scale,
                                warnings)
        except Exception as exc:
            warnings.append(
                'Volume "{0}" could not be built: {1}'.format(
                    record.get("volume") or "?", exc
                )
            )
            continue
        place_in_group(obj, record, root_collection, group_cache)
        if object_by_path is not None and record.get("volume_path"):
            object_by_path[record["volume_path"]] = obj
        built += 1
    return built


def _build_volume(record, root_collection, position_scale, warnings):
    name = safe_name(record.get("volume") or "Volume")
    data = bpy.data.volumes.new(name)

    path = str(record.get("file_path") or "")
    if path:
        data.filepath = path
        if not os.path.isfile(path):
            warnings.append(
                'Volume file was not found, so "{0}" arrived empty: {1}'.format(
                    name, path
                )
            )
    else:
        warnings.append(
            'Volume "{0}" names no VDB file, so it arrived empty.'.format(name)
        )

    if record.get("use_frame_extension"):
        data.is_sequence = True
        data.frame_start = int(scalar(record.get("frame"), 0))

    obj = bpy.data.objects.new(name, data)
    obj["ml_generated"] = True
    obj["ml_maya_volume"] = record.get("volume_full_name") or name
    obj["ml_maya_path"] = record.get("volume_path") or ""
    # Arnold render settings Blender's volume datablock has no place for.
    data["ml_source_grids"] = str(record.get("grids") or "")
    data["ml_source_step_size"] = scalar(record.get("step_size"), 0.0)
    data["ml_source_step_scale"] = scalar(record.get("step_scale"), 1.0)
    data["ml_source_velocity_scale"] = scalar(
        record.get("velocity_scale"), 1.0
    )
    data["ml_source_motion_blur"] = bool(record.get("motion_blur"))

    root_collection.objects.link(obj)
    # Scale composed into the matrix in one assignment, for the reason the
    # curves need it: writing matrix_world and then obj.scale halves the size.
    scale = _world_scale(record)
    basis = maya_matrix_to_blender(record, position_scale)
    obj.matrix_world = basis @ Matrix.Diagonal(Vector(scale)).to_4x4()
    if not record.get("visible", True):
        obj.hide_viewport = True
        obj.hide_render = True
    apply_custom_attributes(obj, record, warnings)
    return obj


def _world_scale(record):
    values = record.get("world_matrix") or []
    if len(values) != 16:
        return (1.0, 1.0, 1.0)
    lengths = []
    for start in (0, 4, 8):
        axis = values[start:start + 3]
        length = sum(float(item) * float(item) for item in axis) ** 0.5
        lengths.append(length if length > 1e-9 else 1.0)
    return tuple(lengths)
