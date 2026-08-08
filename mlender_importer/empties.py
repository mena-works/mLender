# -*- coding: utf-8 -*-
"""Locators and empty nulls, rebuilt as Blender empties.

These do not ride the FBX. It only carries what sits above an exported mesh,
so a locator used as a placement control, and any group holding nothing but
locators, were dropped with no warning at all. They travel as their own JSON
records instead, the way lights and cameras do.
"""

import bpy

from .attributes import apply_custom_attributes
from .constants import EMPTY_DISPLAY_SIZE, EMPTY_DISPLAY_TYPES
from .scene import place_in_group
from .transforms import maya_matrix_to_blender
from .utils import scalar


def import_empties(package_data, root_collection, import_scale, warnings,
                   group_cache, object_by_path):
    """Build every recorded transform, then parent them.

    Two passes on purpose: a locator can hang under another locator, so
    nothing can be parented until all of them exist. The records arrive
    outermost first, but relying on that would break the moment the exporter's
    ordering changed.
    """
    # The same conversion lights and cameras use. Passing the raw import scale
    # instead put a locator a hundred times further out than the mesh it was
    # meant to sit on, because the FBX had already applied the unit conversion
    # to the geometry and the JSON matrix is in Maya units.
    meters_per_unit = scalar(package_data.get("meters_per_maya_unit"), 0.01)
    position_scale = meters_per_unit * max(scalar(import_scale, 1.0), 0.000001)
    records = list(package_data.get("transforms") or [])
    created = []

    for record in records:
        try:
            obj = _build_empty(record, root_collection, position_scale,
                               group_cache)
        except Exception as exc:
            warnings.append(
                'Transform "{0}" could not be built: {1}'.format(
                    record.get("transform") or "?", exc
                )
            )
            continue
        created.append((obj, record))
        path = record.get("transform_path")
        if path:
            object_by_path[path] = obj

    for obj, record in created:
        parent_path = record.get("parent_path")
        if not parent_path:
            continue
        parent = object_by_path.get(parent_path)
        if parent is None:
            # A parent outside the export is not an error: the user may have
            # exported a selection. The empty stays where its world matrix put
            # it, which is still the right place.
            continue
        _parent_keeping_world(obj, parent)

    return {"transform_count": len(created)}


def _build_empty(record, root_collection, position_scale, group_cache):
    name = record.get("transform") or "Empty"
    obj = bpy.data.objects.new(name, None)
    obj.empty_display_type = EMPTY_DISPLAY_TYPES.get(
        record.get("transform_type"), "PLAIN_AXES"
    )
    obj.empty_display_size = EMPTY_DISPLAY_SIZE
    obj["ml_generated"] = True
    obj["ml_maya_transform"] = record.get("transform_full_name") or name
    obj["ml_source_type"] = record.get("transform_type") or ""
    apply_custom_attributes(obj, record, [])

    root_collection.objects.link(obj)
    # A group's own empty belongs inside the collection that mirrors it, not
    # beside it. Otherwise the outliner shows the group's control at the root
    # while everything it holds sits one level down.
    placement = record
    if record.get("transform_type") == "group":
        placement = dict(record)
        placement["groups"] = (
            list(record.get("groups") or [])
            + [record.get("transform") or ""]
        )
    place_in_group(obj, placement, root_collection, group_cache)

    obj.matrix_world = maya_matrix_to_blender(record, position_scale)
    if not record.get("visible", True):
        obj.hide_viewport = True
        obj.hide_render = True
    return obj


def _parent_keeping_world(obj, parent):
    """Parent without moving the object.

    Assigning ``parent`` alone re-reads the existing local matrix against the
    new parent, which teleports the object. Blender's own answer is the parent
    inverse, so it is set explicitly rather than re-deriving the local matrix.
    """
    world = obj.matrix_world.copy()
    obj.parent = parent
    obj.matrix_parent_inverse = parent.matrix_world.inverted_safe()
    obj.matrix_world = world
