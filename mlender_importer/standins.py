# -*- coding: utf-8 -*-
"""Standins: shapes that were only ever a pointer to a file on disk.

An ``aiStandIn`` or a ``gpuCache`` holds no geometry. Maya draws a proxy and
the renderer opens the file later, so what arrives here is a path, a
transform and a bounding box.

Every standin gets an **anchor** empty carrying the Maya transform, and
whatever the file yields is parented under it. That is the arrangement Maya
describes: the contents live in the file's own space and the standin's
transform is applied on top.

The file is referenced, never copied, so it can be absent -- the package may
have travelled to another machine. A file that cannot be found or cannot be
read leaves the anchor standing on its own as a box the size of the proxy
Maya was drawing, and says so. A placeholder in the right place beats a hole
in the scene with nothing to explain it.

Three formats, three different answers about units, each measured on 4.1 and
5.2 rather than assumed:

* **Alembic** carries no unit metadata, so the scale has to be supplied. It
  goes through the same call the package's own cache uses.
* **OBJ** carries none either, and ``global_scale`` does what it says: a four
  unit cube at 0.01 arrives 0.04 across.
* **USD** describes its own units, and the importer's ``scale`` argument is
  accepted and then **ignored** -- measured in world space, a four unit cube
  arrives four units across whatever is passed. So nothing is passed, and the
  file's own metadata is what decides.
"""

import os

import bpy

from .alembic import run_alembic_import
from .attributes import apply_custom_attributes
from .constants import (
    STANDIN_ALEMBIC_FORMATS,
    STANDIN_OBJ_FORMATS,
    STANDIN_PLACEHOLDER_DISPLAY,
    STANDIN_PLACEHOLDER_SIZE,
    STANDIN_USD_FORMATS,
)
from .scene import place_in_group
from .transforms import maya_matrix_to_blender
from .utils import scalar


def import_standins(package_data, root_collection, import_scale, warnings,
                    group_cache):
    """Build every standin. Returns how many were made and how many loaded."""
    records = package_data.get("standins") or []
    if not records:
        return {"standin_count": 0, "standin_loaded": 0}

    meters_per_unit = scalar(package_data.get("meters_per_maya_unit"), 0.01)
    position_scale = meters_per_unit * max(scalar(import_scale, 1.0), 0.000001)

    built = 0
    loaded = 0
    for record in records:
        try:
            anchor = _build_anchor(
                record, root_collection, position_scale, group_cache
            )
        except Exception as exc:
            warnings.append(
                'Standin "{0}" could not be built: {1}'.format(
                    record.get("standin") or "?", exc
                )
            )
            continue
        built += 1
        if _load_contents(anchor, record, position_scale, warnings):
            loaded += 1
        else:
            _draw_as_placeholder(anchor, record, position_scale)
    return {"standin_count": built, "standin_loaded": loaded}


def _build_anchor(record, root_collection, position_scale, group_cache):
    name = record.get("standin") or "Standin"
    obj = bpy.data.objects.new(name, None)
    obj.empty_display_type = STANDIN_PLACEHOLDER_DISPLAY
    obj["ml_generated"] = True
    obj["ml_maya_standin"] = record.get("standin_full_name") or name
    obj["ml_source_type"] = record.get("node_type") or ""
    obj["ml_source_file"] = record.get("file_path") or ""
    if record.get("object_path"):
        obj["ml_source_object_path"] = record.get("object_path")
    apply_custom_attributes(obj, record, [])

    root_collection.objects.link(obj)
    place_in_group(obj, record, root_collection, group_cache)
    obj.matrix_world = maya_matrix_to_blender(record, position_scale)
    if not record.get("visible", True):
        obj.hide_viewport = True
        obj.hide_render = True
    return obj


def _load_contents(anchor, record, position_scale, warnings):
    """Open the file the standin names, under the anchor. True when it came."""
    path = record.get("file_path") or ""
    if not path:
        warnings.append(
            'Standin "{0}" names no file, so a placeholder was built '
            "instead.".format(record.get("standin") or "?")
        )
        return False
    if not os.path.isfile(path):
        # Referenced, not copied: a package opened on another machine will
        # land here, and the path is the useful half of the message.
        warnings.append(
            'Standin "{0}" points at a file that is not there, so a '
            "placeholder was built instead: {1}".format(
                record.get("standin") or "?", path
            )
        )
        return False

    extension = os.path.splitext(path)[1].lower()
    before = set(bpy.data.objects)
    try:
        if extension in STANDIN_ALEMBIC_FORMATS:
            run_alembic_import(path, position_scale)
        elif extension in STANDIN_OBJ_FORMATS:
            _run_obj_import(path, position_scale)
        elif extension in STANDIN_USD_FORMATS:
            # No scale: measured, the argument is ignored and the file's own
            # metersPerUnit is what Blender honours.
            bpy.ops.wm.usd_import(filepath=path)
        else:
            warnings.append(
                'Standin "{0}" is a {1} file, which Blender cannot read; a '
                "placeholder was built where it sits: {2}".format(
                    record.get("standin") or "?",
                    extension.lstrip(".").upper() or "unknown",
                    path,
                )
            )
            return False
    except Exception as exc:
        warnings.append(
            'Standin "{0}" could not be read, so a placeholder was built '
            "instead: {1}".format(record.get("standin") or "?", exc)
        )
        return False

    fresh = [obj for obj in bpy.data.objects if obj not in before]
    if not fresh:
        warnings.append(
            'Standin "{0}" opened but held nothing.'.format(
                record.get("standin") or "?"
            )
        )
        return False

    for obj in fresh:
        obj["ml_generated"] = True
        obj["ml_source_file"] = path
        if obj.parent is None:
            _parent_keeping_local(obj, anchor)
        # The operators link into the scene collection, which would leave a
        # standin's contents outside the collection its anchor lives in.
        _move_to(obj, anchor.users_collection)
    return True


def _move_to(obj, collections):
    for collection in list(obj.users_collection):
        if collection not in collections:
            collection.objects.unlink(obj)
    for collection in collections:
        if obj.name not in collection.objects:
            collection.objects.link(obj)


def _run_obj_import(path, scale):
    """Whichever OBJ operator this build has, with the scale it accepts."""
    try:
        bpy.ops.wm.obj_import(filepath=path, global_scale=scale)
        return
    except (AttributeError, TypeError):
        pass
    bpy.ops.import_scene.obj(filepath=path, global_scale=scale)


def _parent_keeping_local(obj, anchor):
    """Parent to the anchor so the anchor's transform applies on top.

    Deliberately not the world-preserving parenting the empties use: the
    contents arrive in the file's own space and Maya puts the standin's
    transform over them, so the local matrix is the one to keep.
    """
    local = obj.matrix_world.copy()
    obj.parent = anchor
    obj.matrix_parent_inverse.identity()
    obj.matrix_basis = local


def _draw_as_placeholder(anchor, record, position_scale):
    """Size the anchor's box like the proxy Maya was drawing.

    Not a claim about the file: Maya only fills the bounds in from the
    viewport, so a headless export reads its default and the box is then a
    unit cube -- which is exactly what Maya draws in that state too.
    """
    low = record.get("bounds_min") or []
    high = record.get("bounds_max") or []
    half = STANDIN_PLACEHOLDER_SIZE
    if len(low) == 3 and len(high) == 3:
        extents = [
            abs(float(high[axis]) - float(low[axis])) / 2.0
            for axis in range(3)
        ]
        largest = max(extents) if extents else 0.0
        if largest > 1e-9:
            half = largest * position_scale
    anchor.empty_display_size = max(half, 1e-6)
