# -*- coding: utf-8 -*-
"""Import modes: Replace, Merge and Add.

Replace is the original behaviour and stays the default. It wipes the scene,
which is what makes the Maya scene the single source of truth, and the
three-pass clear that raises when anything survives is not softened here --
Merge and Add skip it, they do not weaken it.

Merge keeps the object. A mesh that came from an earlier import of the same
Maya node has its geometry, materials, transform and visibility replaced while
the Blender object itself stays, so a modifier, a parent or a driver the user
added to it survives. Anything the user made themselves is never touched,
because only objects carrying the ``ml_generated`` marker are adopted.

Nothing is deleted for having disappeared from the package. A stale object is
counted and marked instead, and removing them is a button the user presses --
an import arriving over a socket is no place to destroy work unasked.
"""

import bpy

from .constants import (
    IMPORT_MODE_ADD,
    IMPORT_MODE_MERGE,
    IMPORT_MODE_REPLACE,
    STALE_PROPERTY,
)


def normalize_mode(mode):
    mode = str(mode or IMPORT_MODE_REPLACE).upper()
    if mode not in (IMPORT_MODE_REPLACE, IMPORT_MODE_MERGE, IMPORT_MODE_ADD):
        return IMPORT_MODE_REPLACE
    return mode


def generated_objects_by_path():
    """Objects an earlier import created, keyed by the Maya node they came from.

    Keyed on the Maya path rather than the Blender name because a name can be
    changed in Blender and two meshes can share a short one, which is the same
    reason mesh matching needs more than a name.
    """
    found = {}
    for obj in bpy.data.objects:
        if not obj.get("ml_generated"):
            continue
        path = obj.get("ml_maya_path")
        if path:
            found[path] = obj
    return found


REBUILT_MARKERS = ("ml_maya_transform", "ml_maya_curve", "ml_maya_volume")


def clear_rebuilt_objects():
    """Remove the objects a merge is about to build again.

    Empties, curves and volumes are not adopted; they are constructed from
    their records every time. Left in place they accumulated, so a second
    merge of the same package produced "probeLocator.001" beside the one
    already standing. Only objects this tool made are touched.

    Returns how many went.
    """
    doomed = [
        obj for obj in bpy.data.objects
        if obj.get("ml_generated")
        and any(marker in obj.keys() for marker in REBUILT_MARKERS)
    ]
    removed = 0
    for obj in doomed:
        try:
            bpy.data.objects.remove(obj, do_unlink=True)
            removed += 1
        except Exception:
            continue
    return removed


def adopt(new_object, record, existing_by_path, retired=None):
    """Move an imported object's contents onto the object already standing.

    Returns the object to carry on with: the existing one when there was a
    match, otherwise the newly imported one unchanged.

    An adopted object is deleted, so the caller has to stop referring to
    it. ``retired`` collects those, because the import keeps a list of
    everything the FBX brought and touching a removed one afterwards
    raises ReferenceError rather than failing quietly.
    """
    path = (record or {}).get("mesh_path")
    target = existing_by_path.get(path) if path else None
    if target is None or target is new_object:
        return new_object
    if target.type != new_object.type:
        # The Maya node changed kind. Adopting would leave a mesh object
        # holding curve data, so the new object wins and the old one falls
        # out as stale.
        return new_object

    target.data = new_object.data
    target.matrix_world = new_object.matrix_world.copy()
    target.hide_viewport = new_object.hide_viewport
    target.hide_render = new_object.hide_render
    # It matched, so it is not stale however the previous import left it.
    if STALE_PROPERTY in target.keys():
        del target[STALE_PROPERTY]
    if retired is not None:
        retired.append(new_object)
    try:
        bpy.data.objects.remove(new_object, do_unlink=True)
    except Exception:
        pass
    return target


def mark_stale(existing_by_path, adopted_paths):
    """Flag what an earlier import left behind and this package no longer has.

    Marked, counted and left alone. Deleting on the user's behalf is what
    Replace is for, and this mode exists precisely because they did not want
    that.
    """
    stale = []
    for path, obj in existing_by_path.items():
        if path in adopted_paths:
            continue
        try:
            obj[STALE_PROPERTY] = True
        except Exception:
            continue
        stale.append(obj)
    return stale


def remove_stale_objects():
    """Delete everything a previous merge marked. Returns how many went."""
    doomed = [
        obj for obj in bpy.data.objects if obj.get(STALE_PROPERTY)
    ]
    removed = 0
    for obj in doomed:
        try:
            bpy.data.objects.remove(obj, do_unlink=True)
            removed += 1
        except Exception:
            continue
    return removed


def count_stale_objects():
    return len([obj for obj in bpy.data.objects if obj.get(STALE_PROPERTY)])
