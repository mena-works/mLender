# -*- coding: utf-8 -*-
"""The package's Alembic cache, for what the FBX could not carry.

Three readings were measured on 4.1, 4.5 and 5.2 rather than assumed.

The importer applies the same axis change the rest of this tool does:
Maya ``(13, 5, 7)`` arrives as ``(13, -7, 5)``, which is ``(x, -z, y)``.
So nothing here converts anything; doing it again would undo it.

There is no unit metadata in an Alembic the way there is in an FBX, so the
scale has to be supplied. ``scale`` multiplies uniformly, and the value that
matches the FBX path is the one the rest of the importer already computes.

And a deforming object arrives carrying a ``MESH_SEQUENCE_CACHE`` modifier
pointed at the file, while a static one is flattened -- which is why a cache
is a side channel and not a transport for the whole scene. On 4.5 and later
an emitting particle system arrives as a ``POINTCLOUD``, the datablock that
cannot be built from Python at all; on 4.1 it arrives as a mesh.
"""

import os

import bpy

from .constants import ALEMBIC_FILE_KEY
from .utils import safe_name, scalar


def resolve_alembic_path(package_folder, package_data):
    """Find the package's cache, tolerating a package folder that has moved.

    The same three candidates the FBX gets, for the same reason: a package
    is routinely opened from somewhere other than where it was written.
    """
    section = package_data.get("alembic") or {}
    raw = section.get(ALEMBIC_FILE_KEY) or ""
    if not raw:
        return ""
    for candidate in (
        raw,
        os.path.join(package_folder, raw),
        os.path.join(package_folder, os.path.basename(raw)),
    ):
        if candidate and os.path.isfile(candidate):
            return os.path.abspath(candidate)
    return ""


def import_alembic(package_folder, package_data, import_scale, warnings):
    """Import the cache if the package has one. Returns how many objects came.

    A missing cache is a warning, not a failure: the JSON still describes the
    scene, and losing the deforming objects beats losing everything.
    """
    section = package_data.get("alembic") or {}
    if not section.get(ALEMBIC_FILE_KEY):
        return 0

    path = resolve_alembic_path(package_folder, package_data)
    if not path:
        warnings.append(
            "The package names an Alembic cache that is not next to it, so "
            "deforming objects are missing."
        )
        return 0

    meters_per_unit = scalar(package_data.get("meters_per_maya_unit"), 0.01)
    scale = meters_per_unit * max(scalar(import_scale, 1.0), 0.000001)

    before = set(bpy.data.objects)
    try:
        _run_import(path, scale)
    except Exception as exc:
        warnings.append("Alembic cache could not be read: {0}".format(exc))
        return 0

    fresh = [obj for obj in bpy.data.objects if obj not in before]
    for obj in fresh:
        obj["ml_generated"] = True
        obj["ml_alembic"] = os.path.basename(path)
    return len(fresh)


def cached_particle_names(package_data):
    """Names of the particle objects the cache carries, not the FBX.

    Both the Maya name and the name Blender will settle on, since the two
    differ whenever the Maya name held a character Blender rejects.
    """
    names = set()
    for record in package_data.get("particles") or []:
        if not record.get("alembic"):
            continue
        for key in ("particle", "particle_full_name"):
            raw = record.get(key)
            if raw:
                names.add(raw)
                names.add(safe_name(raw))
    return names


def _run_import(path, scale):
    """Call the operator, dropping arguments an older build rejects."""
    kwargs = {
        "filepath": path,
        "scale": scale,
        # The frame range comes from the JSON, which the scene is already
        # set to; letting the cache move it would override the export.
        "set_frame_range": False,
        "as_background_job": False,
    }
    try:
        bpy.ops.wm.alembic_import(**kwargs)
        return
    except TypeError:
        pass
    kwargs.pop("set_frame_range", None)
    try:
        bpy.ops.wm.alembic_import(**kwargs)
    except TypeError:
        kwargs.pop("as_background_job", None)
        bpy.ops.wm.alembic_import(**kwargs)
