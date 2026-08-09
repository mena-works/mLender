# -*- coding: utf-8 -*-
"""Copy the textures a package references into the package folder.

Off by default. The package normally points at the Maya paths, which is right
when both applications run on the same machine and avoids duplicating a
texture library. It breaks the moment the package moves, so collecting is
offered as a choice rather than assumed either way.

Rewriting happens in place on the payload, after it is fully built: every
texture record's ``path`` is repointed at the copy and the original is kept in
``original_path`` so the source is never lost.
"""
from __future__ import absolute_import

import os
import shutil

from .constants import (
    COLLECT_FOLDER_NAME,
    FILE_COLLECT_FOLDER_NAME,
    UDIM_TOKEN,
)
from .mayautils import maya_path


def collect_package_files(payload, package_folder, warnings=None):
    """Copy every file the package references into it, and repoint the JSON.

    Textures were the only thing this collected for a long time, which made
    the option a half promise: measured, a package built with collecting on
    carried its texture and left the VDB and the Alembic standin sitting
    outside it. Both are collected now, into their own folder.

    Returns a summary rather than raising: a missing file is a scene problem
    the user needs told about, not a reason to lose the whole export.
    """
    warnings = warnings if warnings is not None else []
    textures = collect_textures(payload, package_folder, warnings)
    files = collect_referenced_files(payload, package_folder, warnings)
    return {
        "collected": textures["collected"] + files["collected"],
        "missing": textures["missing"] + files["missing"],
        "textures": textures["collected"],
        "files": files["collected"],
        "folder": textures["folder"] or files["folder"],
    }


def collect_textures(payload, package_folder, warnings=None):
    """Copy every referenced texture into the package and repoint the JSON."""
    warnings = warnings if warnings is not None else []
    folder = os.path.join(package_folder, COLLECT_FOLDER_NAME)
    records = list(_texture_records(payload))
    if not records:
        return {"collected": 0, "missing": 0, "folder": ""}

    if not os.path.isdir(folder):
        os.makedirs(folder)

    # One source path can be referenced by many channels; copying it once and
    # remembering where it went keeps the package small and the copies stable.
    copied = {}
    missing = 0
    for record in records:
        source = str(record.get("path") or "")
        if not source:
            continue
        if source in copied:
            record["path"] = copied[source]
            continue

        destination = _copy_texture(source, folder, warnings)
        if not destination:
            missing += 1
            continue
        copied[source] = destination
        record["path"] = destination

    return {
        "collected": len(copied),
        "missing": missing,
        "folder": maya_path(folder),
    }


def collect_referenced_files(payload, package_folder, warnings=None):
    """Copy the non-texture files a package points at: VDBs and standins.

    These carry a plain path string rather than a texture record, which is
    why the texture walk never saw them. A standin is routinely gigabytes, so
    this only runs when the user asked for a self-contained package.
    """
    warnings = warnings if warnings is not None else []
    entries = list(_referenced_files(payload))
    if not entries:
        return {"collected": 0, "missing": 0, "folder": ""}

    folder = os.path.join(package_folder, FILE_COLLECT_FOLDER_NAME)
    if not os.path.isdir(folder):
        os.makedirs(folder)

    copied = {}
    missing = 0
    for record, key in entries:
        source = str(record.get(key) or "")
        if not source:
            continue
        if source not in copied:
            destination = _copy_referenced_file(source, folder, warnings)
            if not destination:
                missing += 1
                continue
            copied[source] = destination
        # The original is kept the way texture records keep theirs, so the
        # source is still readable after the package has been repointed.
        record.setdefault("original_file_path", maya_path(source))
        record[key] = copied[source]

    return {
        "collected": len(copied),
        "missing": missing,
        "folder": maya_path(folder),
    }


def _referenced_files(payload):
    """Every (record, key) holding a path to a file outside the package."""
    for volume in payload.get("volumes") or []:
        if volume.get("file_path"):
            yield volume, "file_path"
    for standin in payload.get("standins") or []:
        if standin.get("file_path"):
            yield standin, "file_path"


def _copy_referenced_file(source, folder, warnings):
    if not os.path.isfile(source):
        warnings.append(
            "Referenced file not found, so not collected: {0}".format(source)
        )
        return ""
    destination = os.path.join(folder, os.path.basename(source))
    return _copy_file(source, destination, warnings)


def _texture_records(payload):
    """Every texture record in a payload, wherever it lives.

    Materials, light colour textures, dome HDRs and IES profiles all carry the
    same shape, so they are all yielded and the caller does not need to know
    the payload layout.
    """
    for mesh in payload.get("meshes") or []:
        for material in mesh.get("materials") or []:
            for channel in (material.get("channels") or {}).values():
                texture = channel.get("texture")
                if isinstance(texture, dict):
                    yield texture
            displacement = material.get("displacement") or {}
            texture = displacement.get("texture")
            if isinstance(texture, dict):
                yield texture

    for light in payload.get("lights") or []:
        for key in ("color_texture", "ies_profile"):
            texture = light.get(key)
            if isinstance(texture, dict):
                yield texture


def _copy_texture(source, folder, warnings):
    """Copy one texture, expanding a UDIM pattern into its tiles.

    A UDIM path is a pattern, not a file: copying it verbatim would copy
    nothing. The tiles beside it are found on disk and copied instead, and the
    returned path keeps the token so the importer still resolves the sequence.
    """
    if UDIM_TOKEN in source:
        return _copy_udim_tiles(source, folder, warnings)

    if not os.path.isfile(source):
        warnings.append("Texture not found, so not collected: {0}".format(source))
        return ""
    destination = os.path.join(folder, os.path.basename(source))
    return _copy_file(source, destination, warnings)


def _copy_udim_tiles(pattern, folder, warnings):
    source_folder, name = os.path.split(pattern)
    prefix, _token, suffix = name.partition(UDIM_TOKEN)
    if not os.path.isdir(source_folder):
        warnings.append(
            "UDIM folder not found, so not collected: {0}".format(source_folder)
        )
        return ""

    tiles = 0
    for entry in sorted(os.listdir(source_folder)):
        if not entry.startswith(prefix) or not entry.endswith(suffix):
            continue
        middle = entry[len(prefix):len(entry) - len(suffix) or None]
        if not middle.isdigit():
            continue
        if _copy_file(
            os.path.join(source_folder, entry),
            os.path.join(folder, entry),
            warnings,
        ):
            tiles += 1

    if not tiles:
        warnings.append("No UDIM tiles found for {0}".format(pattern))
        return ""
    return maya_path(os.path.join(folder, name))


def _copy_file(source, destination, warnings):
    try:
        # An existing copy from an earlier channel is already correct.
        if not os.path.isfile(destination):
            shutil.copy2(source, destination)
        return maya_path(destination)
    except Exception as error:
        warnings.append(
            "Could not collect {0}: {1}".format(source, error)
        )
        return ""
