# -*- coding: utf-8 -*-
"""Maya to Unreal transform conversion.

Shared by lights and cameras, which both need a Maya world matrix expressed in
Unreal's axes and units. Meshes do not come through here at all: Interchange
converts them while importing the FBX, measured correct, and doing it twice
would be worse than doing it once.

The conversion is a measured Y/Z swap with no sign flip, which is not the rule
the Blender receiver uses. See constants.MAYA_TO_UNREAL_AXES.
"""

import math

import unreal

from .constants import UNREAL_UNITS_PER_METRE
from .utils import scalar


def maya_vector_to_unreal(value):
    """Maya Y-up right-handed to Unreal Z-up left-handed: (x, y, z) -> (x, z, y).

    Measured, not derived: cubes exported at Maya (30,0,0), (0,40,0) and
    (0,0,50) arrived at Unreal (30,0,0), (0,0,40) and (0,50,0).
    """
    values = list(value or (0.0, 0.0, 0.0))
    while len(values) < 3:
        values.append(0.0)
    return (
        scalar(values[0], 0.0),
        scalar(values[2], 0.0),
        scalar(values[1], 0.0),
    )


def position_scale(package_data, import_scale=1.0):
    """Maya linear units to Unreal centimetres.

    Unreal's world unit is a centimetre, so this is metres-per-unit times 100,
    not metres-per-unit. Getting that wrong is a factor of 100, which in a
    centimetre scene looks like nothing happening and in a metre scene looks
    like the scene exploding.
    """
    metres = scalar((package_data or {}).get("meters_per_maya_unit"), 0.01)
    return metres * UNREAL_UNITS_PER_METRE * max(scalar(import_scale, 1.0), 1e-6)


def _normalized(vector, fallback):
    length = math.sqrt(sum(component * component for component in vector))
    if length <= 1e-6:
        return fallback
    return tuple(component / length for component in vector)


def _cross(a, b):
    return (
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    )


def maya_basis_to_unreal(transform_record):
    """The three Unreal axis vectors for a Maya world matrix.

    Maya lights and cameras look down local -Z with +Y up; Unreal's look down
    local +X with +Z up. So the object's viewing direction becomes Unreal's
    forward rather than its own -Z surviving as -Z:

        Unreal +X (forward) = -S . maya_z
        Unreal +Y (right)   =  S . maya_x
        Unreal +Z (up)      =  S . maya_y

    where S is the Y/Z swap. S flips handedness, and the assignment above is
    what keeps the frame consistent afterwards: with x cross y = z in Maya,
    forward cross right = up holds in Unreal.
    """
    values = transform_record.get("world_matrix") or []
    if len(values) != 16:
        return None

    maya_x = maya_vector_to_unreal(values[0:3])
    maya_y = maya_vector_to_unreal(values[4:7])
    maya_z = maya_vector_to_unreal(values[8:11])

    forward = _normalized(
        (-maya_z[0], -maya_z[1], -maya_z[2]), (1.0, 0.0, 0.0)
    )
    up = _normalized(maya_y, (0.0, 0.0, 1.0))
    right = _normalized(maya_x, (0.0, 1.0, 0.0))

    # A zero length or non perpendicular axis would otherwise produce a
    # rotator that is quietly not a rotation. Rebuild the odd one out from the
    # other two rather than trusting all three.
    if abs(sum(f * u for f, u in zip(forward, up))) > 0.001:
        right = _normalized(_cross(up, forward), right)
        up = _normalized(_cross(forward, right), up)
    return forward, right, up


def unreal_location(transform_record, scale):
    """A Maya world translation as an Unreal Vector in centimetres."""
    values = transform_record.get("world_matrix") or []
    source = (
        values[12:15] if len(values) == 16
        else (transform_record.get("translation") or (0.0, 0.0, 0.0))
    )
    x, y, z = maya_vector_to_unreal(source)
    return unreal.Vector(x * scale, y * scale, z * scale)


def unreal_rotation(transform_record):
    """A Maya world basis as an Unreal Rotator.

    Unreal's Rotator convention is not worth deriving by hand, so the engine's
    own helper does it. The names differ between versions, so this asks which
    one exists rather than calling one and hoping -- the same defensive
    pattern the Blender receiver uses for renamed sockets.
    """
    basis = maya_basis_to_unreal(transform_record)
    if basis is None:
        return unreal.Rotator(0.0, 0.0, 0.0)
    forward, _right, up = basis
    forward_vector = unreal.Vector(*forward)
    up_vector = unreal.Vector(*up)

    library = getattr(unreal, "MathLibrary", None)
    for name in ("make_rot_from_xz", "make_rot_from_x"):
        function = getattr(library, name, None) if library else None
        if function is None:
            continue
        try:
            if name == "make_rot_from_xz":
                return function(forward_vector, up_vector)
            return function(forward_vector)
        except TypeError:
            continue

    return _rotator_from_basis(forward, up)


def _rotator_from_basis(forward, up):
    """Fallback rotator, used only if the engine exposes no helper.

    Yaw and pitch come from the forward vector; roll is the angle between the
    up vector and the un-rolled up for that yaw and pitch.
    """
    yaw = math.degrees(math.atan2(forward[1], forward[0]))
    horizontal = math.sqrt(forward[0] ** 2 + forward[1] ** 2)
    pitch = math.degrees(math.atan2(forward[2], horizontal))

    yaw_radians = math.radians(yaw)
    pitch_radians = math.radians(pitch)
    # The up vector this yaw and pitch would give with no roll.
    unrolled_up = (
        -math.sin(pitch_radians) * math.cos(yaw_radians),
        -math.sin(pitch_radians) * math.sin(yaw_radians),
        math.cos(pitch_radians),
    )
    right = (-math.sin(yaw_radians), math.cos(yaw_radians), 0.0)
    roll = math.degrees(
        math.atan2(
            sum(u * r for u, r in zip(up, right)),
            sum(u * n for u, n in zip(up, unrolled_up)),
        )
    )
    return unreal.Rotator(roll, pitch, yaw)


def unreal_transform(transform_record, scale):
    """Location and rotation together; scale is deliberately dropped.

    Lights and cameras carry their size through component properties, not
    through the actor transform. A scaled camera in Unreal is a rendering
    hazard and a scaled light is the area applied twice.
    """
    return (
        unreal_location(transform_record or {}, scale),
        unreal_rotation(transform_record or {}),
    )


def maya_object_basis_to_unreal(transform_record):
    """The Unreal axes for an ordinary object, which is not a light or a camera.

    Lights and cameras get their viewing direction moved onto Unreal's +X,
    because that is where Unreal points them. An object has no viewing
    direction: its own local axes should keep their names, mapped through the
    same Y/Z swap the positions use. So Maya's up becomes Unreal's up:

        Unreal +X = S . maya_x
        Unreal +Y = S . maya_z
        Unreal +Z = S . maya_y

    That assignment is what keeps the frame valid rather than mirrored. S flips
    handedness, so with x cross z = -y in Maya, x cross y = z holds in Unreal
    only for this pairing -- mapping each axis onto the same-named Unreal axis
    would produce a left-handed basis and a rotator that is quietly a
    reflection.
    """
    values = transform_record.get("world_matrix") or []
    if len(values) != 16:
        return None
    x_axis = _normalized(
        maya_vector_to_unreal(values[0:3]), (1.0, 0.0, 0.0)
    )
    up = _normalized(maya_vector_to_unreal(values[4:7]), (0.0, 0.0, 1.0))
    right = _normalized(maya_vector_to_unreal(values[8:11]), (0.0, 1.0, 0.0))
    return x_axis, right, up


def matrix_scale(transform_record):
    """Absolute scale from a Maya world matrix, in Unreal's axis order.

    Read from the row lengths rather than from the record's ``scale`` field,
    because the matrix is what the object actually has once its parents are
    folded in. The Y and Z components swap for the same reason the axes do.
    """
    values = transform_record.get("world_matrix") or []
    if len(values) != 16:
        return (1.0, 1.0, 1.0)

    def length(row):
        return math.sqrt(sum(scalar(v, 0.0) ** 2 for v in row))

    x_scale = length(values[0:3])
    y_scale = length(values[4:7])     # Maya's Y, which becomes Unreal's Z
    z_scale = length(values[8:11])    # Maya's Z, which becomes Unreal's Y
    return (
        x_scale if x_scale > 1e-9 else 1.0,
        z_scale if z_scale > 1e-9 else 1.0,
        y_scale if y_scale > 1e-9 else 1.0,
    )


def unreal_object_rotation(transform_record):
    """An ordinary object's Maya basis as an Unreal Rotator."""
    basis = maya_object_basis_to_unreal(transform_record or {})
    if basis is None:
        return unreal.Rotator(0.0, 0.0, 0.0)
    x_axis, _right, up = basis
    library = getattr(unreal, "MathLibrary", None)
    function = getattr(library, "make_rot_from_xz", None) if library else None
    if function is not None:
        try:
            return function(unreal.Vector(*x_axis), unreal.Vector(*up))
        except TypeError:
            pass
    return _rotator_from_basis(x_axis, up)


def unreal_object_transform(transform_record, scale):
    """Location, rotation and scale for an ordinary object from the JSON.

    Unlike the light and camera path, scale is kept: a locator or a volume that
    was scaled in Maya is scaled in Unreal, because nothing else carries its
    size.
    """
    record = transform_record or {}
    return (
        unreal_location(record, scale),
        unreal_object_rotation(record),
        unreal.Vector(*matrix_scale(record)),
    )


def source_scale(record):
    """Absolute local scale from a transform record, padded to three axes.

    Stays in Maya's axis order: it feeds light size, where the caller decides
    which Maya axis is width and which is height, and swapping here would move
    that decision somewhere it cannot be read.
    """
    transform = (record or {}).get("transform") or {}
    values = [
        abs(scalar(item, 1.0))
        for item in list(transform.get("scale") or (1.0, 1.0, 1.0))[:3]
    ]
    while len(values) < 3:
        values.append(1.0)
    return values
