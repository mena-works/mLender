# -*- coding: utf-8 -*-
"""Maya curves rebuilt as Blender curve objects.

Blender does not take an arbitrary knot vector. It offers uniform, endpoint
and bezier knots, so the transfer maps what Maya reports instead:

    degree 1        -> POLY spline
    degree 2 and up -> NURBS spline, order = degree + 1
    form 0 (open)   -> use_endpoint_u, which is the clamped curve Maya's
                       (0,0,0,1,1,1) knots describe
    form 1 or 2     -> use_cyclic_u

Measured against a real Maya: an open cubic reports knots (0,0,0,1,1,1), which
is exactly a clamped curve, and a periodic circle reports 8 unique control
points for 11 controlPoints. Both line up with what Blender wants, so the
approximation is only in the knot spacing of an unevenly parameterised curve.
"""

import bpy
from mathutils import Matrix, Vector

from .attributes import apply_custom_attributes
from .constants import CURVE_FORM_OPEN
from .scene import place_in_group
from .transforms import maya_matrix_to_blender
from .utils import safe_object_name, scalar


def import_curves(package_data, root_collection, import_scale, warnings,
                  group_cache, object_by_path=None):
    """Rebuild every curve record. Returns how many were built.

    Curves are registered by Maya path like meshes and empties, because a
    selection set can name one and would otherwise skip it silently.
    """
    meters_per_unit = scalar(package_data.get("meters_per_maya_unit"), 0.01)
    position_scale = meters_per_unit * max(scalar(import_scale, 1.0), 0.000001)

    built = 0
    for record in list(package_data.get("curves") or []):
        try:
            obj = _build_curve(record, root_collection, position_scale,
                               group_cache)
        except Exception as exc:
            warnings.append(
                'Curve "{0}" could not be built: {1}'.format(
                    record.get("curve") or "?", exc
                )
            )
            continue
        if object_by_path is not None and record.get("curve_path"):
            object_by_path[record["curve_path"]] = obj
        built += 1
    return built


def _build_curve(record, root_collection, position_scale, group_cache):
    points = record.get("control_points") or []
    if not points:
        raise ValueError("no control points")

    # The full name keeps the namespace: an AS record names its control
    # 'NS:IKArm_L' and the FBX-borne bones beside it are qualified the same
    # way, so a stripped curve name would break the lookup between them.
    name = safe_object_name(record.get("curve_full_name")
                            or record.get("curve") or "Curve")
    data = bpy.data.curves.new(name, "CURVE")
    data.dimensions = "3D"

    degree = max(1, int(record.get("degree") or 3))
    cyclic = int(record.get("form") or CURVE_FORM_OPEN) != CURVE_FORM_OPEN

    if degree == 1:
        spline = data.splines.new("POLY")
        spline.points.add(len(points) - 1)
        for point, values in zip(spline.points, points):
            point.co = _scaled(values, position_scale) + (1.0,)
    else:
        spline = data.splines.new("NURBS")
        spline.points.add(len(points) - 1)
        for point, values in zip(spline.points, points):
            point.co = _scaled(values, position_scale) + (1.0,)
        # order_u is degree + 1, and Blender clamps it to the point count
        # itself, so a two point cubic does not raise.
        spline.order_u = min(degree + 1, len(points))
        # Endpoint knots are what Maya's clamped (0,0,0,1,1,1) describes. A
        # cyclic curve must not have them: the two together leave a kink.
        spline.use_endpoint_u = not cyclic
    spline.use_cyclic_u = cyclic

    obj = bpy.data.objects.new(name, data)
    obj["ml_generated"] = True
    obj["ml_maya_curve"] = record.get("curve_full_name") or name
    obj["ml_source_type"] = record.get("curve_type") or "nurbsCurve"
    obj["ml_source_degree"] = degree
    apply_custom_attributes(obj, record, [])

    root_collection.objects.link(obj)
    place_in_group(obj, record, root_collection, group_cache)
    # One assignment, scale composed in. Setting matrix_world and then
    # obj.scale looks equivalent and is not: the matrix write already decided
    # the basis, and a curve on a transform scaled by two came through at half
    # size because of it.
    scale = _world_scale(record)
    basis = maya_matrix_to_blender(record, position_scale)
    obj.matrix_world = basis @ Matrix.Diagonal(Vector(scale)).to_4x4()
    if not record.get("visible", True):
        obj.hide_viewport = True
        obj.hide_render = True
    return obj


def _scaled(values, position_scale):
    """Maya local control point to Blender local control point.

    No axis swap. maya_matrix_to_blender converts the object's basis vectors,
    so the object's local frame already stands where Maya's did; swapping the
    components here as well would rotate every curve a second time. Only the
    unit conversion applies, because that function normalises the basis.
    """
    x, y, z = (list(values) + [0.0, 0.0, 0.0])[:3]
    return (
        float(x) * position_scale,
        float(y) * position_scale,
        float(z) * position_scale,
    )


def _world_scale(record):
    """Scale magnitudes the matrix conversion normalises away.

    maya_matrix_to_blender strips scale on purpose, because a scaled light or
    camera is a hazard. A curve's control points are local, so its transform's
    scale is real geometry and has to come back.
    """
    values = record.get("world_matrix") or []
    if len(values) != 16:
        return (1.0, 1.0, 1.0)
    lengths = []
    for start in (0, 4, 8):
        axis = values[start:start + 3]
        length = sum(float(item) * float(item) for item in axis) ** 0.5
        lengths.append(length if length > 1e-9 else 1.0)
    return tuple(lengths)
