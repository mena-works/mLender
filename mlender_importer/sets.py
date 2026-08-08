# -*- coding: utf-8 -*-
"""Maya selection sets and display layers.

Both become collections, gathered under their own parent so they never get
mistaken for the group hierarchy. An object is **added** to them rather than
moved: a Blender object can belong to several collections, and a set is a
second way of naming the same objects, not a different place for them.

A display layer also carries state a collection cannot. Maya's visibility
becomes the collection's, and its reference and template display types become
hide_select, because in both of those Maya means "you are not meant to grab
this".
"""

import bpy

from .constants import (
    LAYER_COLLECTION_NAME,
    MAYA_DISPLAY_TYPE_NORMAL,
    SET_COLLECTION_NAME,
)
from .utils import safe_name


def import_sets(package_data, root_collection, object_by_maya_path, warnings):
    """Rebuild selection sets and display layers. Returns what was built."""
    sets_built = _build_selection_sets(
        package_data.get("selection_sets") or [],
        root_collection,
        object_by_maya_path,
        warnings,
    )
    layers_built = _build_display_layers(
        package_data.get("display_layers") or [],
        root_collection,
        object_by_maya_path,
        warnings,
    )
    return {"set_count": sets_built, "layer_count": layers_built}


def _parent_collection(root_collection, name):
    existing = bpy.data.collections.get(name)
    if existing is None:
        existing = bpy.data.collections.new(name)
        existing["ml_generated"] = True
        root_collection.children.link(existing)
    return existing


def _build_selection_sets(records, root_collection, object_by_maya_path,
                          warnings):
    if not records:
        return 0
    parent = _parent_collection(root_collection, SET_COLLECTION_NAME)
    built = 0
    for record in records:
        objects = _resolve(record.get("members"), object_by_maya_path)
        if not objects:
            warnings.append(
                'Set "{0}" matched none of the imported objects.'.format(
                    record.get("set") or "?"
                )
            )
            continue
        collection = bpy.data.collections.new(
            safe_name(record.get("set") or "Set")
        )
        collection["ml_generated"] = True
        collection["ml_maya_set"] = record.get("set_full_name") or ""
        parent.children.link(collection)
        for obj in objects:
            if obj.name not in collection.objects:
                collection.objects.link(obj)
        built += 1
    return built


def _build_display_layers(records, root_collection, object_by_maya_path,
                          warnings):
    if not records:
        return 0
    parent = _parent_collection(root_collection, LAYER_COLLECTION_NAME)
    built = 0
    for record in records:
        objects = _resolve(record.get("members"), object_by_maya_path)
        if not objects:
            continue
        collection = bpy.data.collections.new(
            safe_name(record.get("layer") or "Layer")
        )
        collection["ml_generated"] = True
        collection["ml_maya_layer"] = record.get("layer_full_name") or ""
        collection["ml_source_display_type"] = int(
            record.get("display_type") or MAYA_DISPLAY_TYPE_NORMAL
        )
        parent.children.link(collection)
        for obj in objects:
            if obj.name not in collection.objects:
                collection.objects.link(obj)

        if not record.get("visible", True):
            # Set on the objects, not only the collection: an object in a
            # hidden layer is hidden in Maya however else it is reached, and
            # it is in its group collection too.
            collection.hide_viewport = True
            collection.hide_render = True
            for obj in objects:
                obj.hide_viewport = True
                obj.hide_render = True
        if int(record.get("display_type") or 0) != MAYA_DISPLAY_TYPE_NORMAL:
            for obj in objects:
                obj.hide_select = True
        built += 1
    return built


def _resolve(members, object_by_maya_path):
    found = []
    for path in members or []:
        obj = object_by_maya_path.get(path)
        if obj is not None and obj not in found:
            found.append(obj)
    return found
