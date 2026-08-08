# -*- coding: utf-8 -*-
"""Maya to Blender transform conversion.

Shared by lights and cameras, which both need a Maya world matrix expressed in
Blender's axes and units. Keeping it in one place means the two cannot drift
apart, which would put a camera and the lights it sees in different worlds.
"""

from mathutils import Matrix, Vector

from .utils import scalar


def maya_vector_to_blender(value):
    """Maya Y-up to Blender Z-up: (x, y, z) becomes (x, -z, y)."""
    values = list(value or (0.0, 0.0, 0.0))
    while len(values) < 3:
        values.append(0.0)
    return Vector(
        (
            scalar(values[0], 0.0),
            -scalar(values[2], 0.0),
            scalar(values[1], 0.0),
        )
    )


def normalized_axis(axis, fallback):
    if axis.length <= 0.000001:
        return fallback.copy()
    return axis.normalized()


def maya_matrix_to_blender(transform_record, position_scale):
    """Convert a Maya world matrix into a scaled, normalised Blender matrix.

    Scale is stripped from the basis because both lights and cameras carry
    their size through data properties rather than through the object
    transform, and a scaled camera in Blender is a rendering hazard.
    """
    values = transform_record.get("world_matrix") or []
    if len(values) != 16:
        translation = transform_record.get("translation") or (0.0, 0.0, 0.0)
        matrix = Matrix.Identity(4)
        matrix.translation = maya_vector_to_blender(translation) * position_scale
        return matrix

    x_axis = normalized_axis(
        maya_vector_to_blender(values[0:3]),
        Vector((1.0, 0.0, 0.0)),
    )
    y_axis = normalized_axis(
        maya_vector_to_blender(values[4:7]),
        Vector((0.0, 0.0, 1.0)),
    )
    z_axis = normalized_axis(
        maya_vector_to_blender(values[8:11]),
        Vector((0.0, -1.0, 0.0)),
    )
    translation = maya_vector_to_blender(values[12:15]) * position_scale
    return Matrix(
        (
            (x_axis.x, y_axis.x, z_axis.x, translation.x),
            (x_axis.y, y_axis.y, z_axis.y, translation.y),
            (x_axis.z, y_axis.z, z_axis.z, translation.z),
            (0.0, 0.0, 0.0, 1.0),
        )
    )


def source_scale(record):
    """Absolute local scale from a transform record, padded to three axes."""
    transform = record.get("transform") or {}
    values = [
        abs(scalar(item, 1.0))
        for item in list(transform.get("scale") or (1.0, 1.0, 1.0))[:3]
    ]
    while len(values) < 3:
        values.append(1.0)
    return values
