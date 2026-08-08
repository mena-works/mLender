# -*- coding: utf-8 -*-
"""Maya particles, rebuilt as a vertex-only mesh.

Blender's own particle systems are driven by emitters and physics, not by
explicit positions, so they cannot receive a Maya particle object. A point
cloud would be the truer analogue, but measured on 4.1, 4.5 and 5.2 its points
collection has no ``add``: a point cloud cannot be built from Python at all.

A mesh of loose vertices works everywhere, shows the particles where they are,
and is what geometry nodes instance onto -- which is how a Blender artist
would put geometry back on them.

Per particle radius, colour and opacity arrive as mesh attributes on the point
domain when Maya had them, under their own names, so they can drive that
instancing rather than being lost as trivia.
"""

import bpy
from mathutils import Matrix, Vector

from .attributes import apply_custom_attributes
from .scene import place_in_group
from .transforms import maya_matrix_to_blender
from .utils import safe_name, scalar

# semantic -> (Blender attribute type, numbers per point)
POINT_ATTRIBUTES = {
    "radius": ("FLOAT", 1),
    "opacity": ("FLOAT", 1),
    "color": ("FLOAT_COLOR", 3),
}


def import_particles(package_data, root_collection, import_scale, warnings,
                     group_cache, object_by_path=None):
    """Rebuild every particle record. Returns how many were built."""
    records = list(package_data.get("particles") or [])
    if not records:
        return 0

    meters_per_unit = scalar(package_data.get("meters_per_maya_unit"), 0.01)
    position_scale = meters_per_unit * max(scalar(import_scale, 1.0), 0.000001)

    built = 0
    for record in records:
        try:
            obj = _build_particles(record, position_scale, warnings)
        except Exception as exc:
            warnings.append(
                'Particle object "{0}" could not be built: {1}'.format(
                    record.get("particle") or "?", exc
                )
            )
            continue
        if obj is None:
            continue
        root_collection.objects.link(obj)
        place_in_group(obj, record, root_collection, group_cache)
        if object_by_path is not None and record.get("particle_path"):
            object_by_path[record["particle_path"]] = obj
        built += 1
    return built


def _build_particles(record, position_scale, warnings):
    name = safe_name(record.get("particle") or "Particles")
    positions = record.get("positions") or []
    count = int(scalar(record.get("count"), 0))
    if not positions or count <= 0:
        warnings.append(
            'Particle object "{0}" had no positions to rebuild.'.format(name)
        )
        return None

    # No axis swap: the matrix conversion turns the object's basis, so the
    # local coordinates stand as they are, exactly as for curve points.
    vertices = [
        (
            positions[index * 3] * position_scale,
            positions[index * 3 + 1] * position_scale,
            positions[index * 3 + 2] * position_scale,
        )
        for index in range(count)
    ]

    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata(vertices, [], [])
    mesh.update()

    obj = bpy.data.objects.new(name, mesh)
    obj["ml_generated"] = True
    obj["ml_maya_particles"] = record.get("particle_full_name") or name
    obj["ml_source_count"] = count
    obj["ml_source_render_type"] = str(record.get("render_type") or "")

    _apply_point_attributes(mesh, record, count, warnings)

    scale = _world_scale(record)
    basis = maya_matrix_to_blender(record, position_scale)
    obj.matrix_world = basis @ Matrix.Diagonal(Vector(scale)).to_4x4()
    if not record.get("visible", True):
        obj.hide_viewport = True
        obj.hide_render = True
    apply_custom_attributes(obj, record, warnings)
    return obj


def _apply_point_attributes(mesh, record, count, warnings):
    for semantic, (kind, stride) in POINT_ATTRIBUTES.items():
        values = record.get(semantic) or []
        if len(values) != count * stride:
            continue
        try:
            attribute = mesh.attributes.new(semantic, kind, "POINT")
        except Exception as exc:
            warnings.append(
                'Particle attribute "{0}" could not be created: {1}'.format(
                    semantic, exc
                )
            )
            continue
        try:
            if stride == 1:
                for index, item in enumerate(attribute.data):
                    item.value = values[index]
            else:
                for index, item in enumerate(attribute.data):
                    base = index * stride
                    item.color = (
                        values[base], values[base + 1], values[base + 2], 1.0
                    )
        except Exception as exc:
            warnings.append(
                'Particle attribute "{0}" could not be filled: {1}'.format(
                    semantic, exc
                )
            )


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
