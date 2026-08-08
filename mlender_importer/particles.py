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

A simulation travels as keyframed vertex positions when the exporter could bake
it. Measured on 4.1 and 5.2: a vertex's ``co`` takes keyframes, while an
object's mesh datablock does not, which is why a bake is only possible at all
for a particle count that never changes -- and why the exporter, not this side,
decides whether there is one.
"""

import bpy
from mathutils import Matrix, Vector

from .animation import set_linear_interpolation
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
    """Rebuild every particle record. Returns (built, baked) counts."""
    records = list(package_data.get("particles") or [])
    if not records:
        return 0, 0

    meters_per_unit = scalar(package_data.get("meters_per_maya_unit"), 0.01)
    position_scale = meters_per_unit * max(scalar(import_scale, 1.0), 0.000001)

    built = 0
    baked = 0
    for record in records:
        # An emitting system the Alembic cache carries must not also be
        # rebuilt here, or the frozen snapshot would sit inside the cached
        # one under a numbered name.
        if record.get("alembic"):
            continue
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
        if bake_positions(obj.data, record, position_scale, warnings):
            baked += 1
    return built, baked


def bake_positions(mesh, record, position_scale, warnings):
    """Key every vertex to its sampled position. True when a bake happened.

    The exporter only sends samples for a count that never changes, so the
    vertex list built from the first frame stays valid for all of them. A
    length that disagrees would move the wrong points, so it stops instead.
    """
    samples = record.get("samples") or []
    if len(samples) < 2:
        return False

    vertices = mesh.vertices
    keyed = 0
    for sample in samples:
        frame = sample.get("frame")
        positions = sample.get("positions") or []
        if frame is None or len(positions) != len(vertices) * 3:
            warnings.append(
                'Particle object "{0}" has a frame that does not match its '
                "point count, so its bake stops there.".format(
                    record.get("particle") or "?"
                )
            )
            break
        for index, vertex in enumerate(vertices):
            base = index * 3
            vertex.co = (
                positions[base] * position_scale,
                positions[base + 1] * position_scale,
                positions[base + 2] * position_scale,
            )
            vertex.keyframe_insert("co", frame=frame)
        keyed += 1

    if keyed < 2:
        return False
    set_linear_interpolation(mesh)
    # The loop leaves every vertex parked on the last frame it keyed. The
    # animation overrides that the moment the frame changes, but until then
    # the mesh would sit at the end of the simulation rather than at the
    # snapshot the rest of the record describes.
    _apply_first_sample(vertices, samples[0], position_scale)
    return True


def _apply_first_sample(vertices, sample, position_scale):
    positions = sample.get("positions") or []
    for index, vertex in enumerate(vertices):
        base = index * 3
        vertex.co = (
            positions[base] * position_scale,
            positions[base + 1] * position_scale,
            positions[base + 2] * position_scale,
        )


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
