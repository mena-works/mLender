# -*- coding: utf-8 -*-
"""Maya's particle instancer, rebuilt as vertex instancing.

Measured on 4.1, 4.5 and 5.2: setting ``instance_type = "VERTS"`` on the
points object and parenting the geometry to it gives one evaluated instance
per vertex on all three. Geometry nodes could carry more -- per point index,
rotation and scale -- but this route needs no node tree and behaves the same
on every version the tool claims.

The source object itself is never re-parented. It came through the FBX with
its own place in the scene and moving it would edit the user's geometry to
make the instancer work; a linked copy sharing the same mesh data is created
instead, so the original stays where Maya had it.
"""

import bpy
from mathutils import Matrix

from .scene import place_in_group
from .utils import safe_name


def import_instancers(package_data, root_collection, warnings, group_cache,
                      object_by_path=None):
    """Wire up every instancer record. Returns how many were built."""
    records = list(package_data.get("instancers") or [])
    if not records:
        return 0

    built = 0
    for record in records:
        try:
            if _build_instancer(record, root_collection, warnings,
                                group_cache, object_by_path or {}):
                built += 1
        except Exception as exc:
            warnings.append(
                'Instancer "{0}" could not be rebuilt: {1}'.format(
                    record.get("instancer") or "?", exc
                )
            )
    return built


def _build_instancer(record, root_collection, warnings, group_cache,
                     object_by_path):
    name = safe_name(record.get("instancer") or "Instancer")
    holder = object_by_path.get(record.get("points_path"))
    if holder is None:
        warnings.append(
            'Instancer "{0}" places geometry on points that did not arrive, '
            "so nothing was instanced.".format(name)
        )
        return False

    sources = list(record.get("sources") or [])
    source = None
    for path in sources:
        source = object_by_path.get(path)
        if source is not None:
            break
    if source is None:
        warnings.append(
            'Instancer "{0}" has no source geometry in this package.'.format(
                name
            )
        )
        return False

    # Maya cycles its sources with a per particle index, which vertex
    # instancing has no room for. With no index set every particle uses the
    # first source, which is what this reproduces; anything else is said out
    # loud rather than silently approximated.
    if len(sources) > 1:
        warnings.append(
            'Instancer "{0}" cycles {1} objects; vertex instancing carries '
            "only the first.".format(name, len(sources))
        )

    template = bpy.data.objects.new(
        name + "_Instance", getattr(source, "data", None)
    )
    template["ml_generated"] = True
    template["ml_maya_instancer"] = record.get("instancer") or name
    template["ml_source_object"] = getattr(source, "name", "")
    root_collection.objects.link(template)

    # Identity, both of them: a leftover parent inverse offsets every
    # instance by wherever the points object happened to be.
    template.parent = holder
    template.matrix_parent_inverse = Matrix.Identity(4)
    template.matrix_basis = Matrix.Identity(4)

    try:
        holder.instance_type = "VERTS"
    except Exception as exc:
        warnings.append(
            'Instancer "{0}" could not switch its points object to vertex '
            "instancing: {1}".format(name, exc)
        )
        return False
    # The points object keeps its own geometry hidden the way Maya does: a
    # particle object is not renderable, it is where the copies go.
    if hasattr(holder, "show_instancer_for_render"):
        holder.show_instancer_for_render = False
    if hasattr(holder, "show_instancer_for_viewport"):
        holder.show_instancer_for_viewport = False

    place_in_group(template, record, root_collection, group_cache)
    return True
