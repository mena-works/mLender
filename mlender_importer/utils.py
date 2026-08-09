# -*- coding: utf-8 -*-
"""Value coercion and Maya/Blender name normalisation helpers.

Package JSON is user-scene derived and loosely typed: a channel value may be a
float, an RGB list or an RGBA list. These helpers coerce whatever arrives into
the shape Blender sockets expect instead of trusting the payload.
"""

import glob
import os
import re

import bpy

from .constants import COLLECTED_FOLDERS, UDIM_TOKEN


def resolve_package_paths(package_data, package_folder):
    """Repoint every recorded file that is missing but sits in the package.

    A package records absolute paths, written by whichever machine exported
    it. Collecting copies the files inside the package but keeps writing the
    absolute path to the copy, so a collected package that is opened anywhere
    else -- another machine, another drive letter, a folder someone moved --
    resolved none of them and reported every texture as not found.

    The FBX and the Alembic already solved this for themselves, each with the
    same three candidates. This does it once for everything else, in one pass
    over the payload before anything reads it, so the readers stay unaware.

    A path that still exists is left exactly as it is: the common case is both
    applications on one machine, and repointing there would be a change with
    nothing to gain.
    """
    if not package_folder or not os.path.isdir(package_folder):
        return 0
    repointed = 0
    for record, key in _recorded_paths(package_data):
        original = str(record.get(key) or "")
        if not original:
            continue
        found = _find_in_package(original, package_folder)
        if not found or found == original:
            continue
        record[key] = found
        # Kept the way the exporter keeps its own originals, so what the Maya
        # scene said is still readable after the move.
        record.setdefault("original_package_path", original)
        repointed += 1
    return repointed


def _recorded_paths(package_data):
    """Every (record, key) in a payload that names a file on disk."""
    for mesh in package_data.get("meshes") or []:
        for material in mesh.get("materials") or []:
            for channel in (material.get("channels") or {}).values():
                for entry in _texture_dicts(channel.get("texture")):
                    yield entry
            displacement = material.get("displacement") or {}
            for entry in _texture_dicts(displacement.get("texture")):
                yield entry
    for light in package_data.get("lights") or []:
        for key in ("color_texture", "ies_profile"):
            for entry in _texture_dicts(light.get(key)):
                yield entry
    for section in ("volumes", "standins"):
        for record in package_data.get(section) or []:
            if record.get("file_path"):
                yield record, "file_path"


def _texture_dicts(texture):
    """A texture record's own paths, and those of any layer beneath it.

    A layered texture holds a whole stack of records, and a projection holds
    the image behind it; neither is reachable by looking at the top record.
    """
    if not isinstance(texture, dict):
        return
    for key in ("path", "udim_pattern"):
        if texture.get(key):
            yield texture, key
    projection = texture.get("projection")
    if isinstance(projection, dict):
        for entry in _texture_dicts(projection.get("image")):
            yield entry
    layered = texture.get("layered") or {}
    for layer in layered.get("layers") or []:
        for side in ("color", "alpha"):
            for entry in _texture_dicts((layer.get(side) or {}).get("texture")):
                yield entry


def _find_in_package(original, package_folder):
    """The same file inside the package, or "" when it needs no help."""
    expanded = os.path.expandvars(os.path.expanduser(original))
    if UDIM_TOKEN in expanded or "<udim>" in expanded.lower():
        return _find_pattern_in_package(expanded, package_folder)
    if os.path.isfile(expanded):
        return ""
    name = os.path.basename(expanded)
    if not name:
        return ""
    for folder in _candidate_folders(package_folder):
        candidate = os.path.join(folder, name)
        if os.path.isfile(candidate):
            return candidate.replace("\\", "/")
    return ""


def _find_pattern_in_package(pattern, package_folder):
    """A UDIM pattern is not a file, so its tiles are what gets looked for."""
    name = os.path.basename(pattern)
    if not name:
        return ""
    tokenized = re.sub("(?i)" + re.escape(UDIM_TOKEN), "[1-9][0-9][0-9][0-9]",
                       name)
    if glob.glob(os.path.join(os.path.dirname(pattern), tokenized)):
        return ""
    for folder in _candidate_folders(package_folder):
        if glob.glob(os.path.join(folder, tokenized)):
            return os.path.join(folder, name).replace("\\", "/")
    return ""


def _candidate_folders(package_folder):
    yield package_folder
    for name in COLLECTED_FOLDERS:
        yield os.path.join(package_folder, name)


def color4(value, clamp=True):
    """Coerce a scalar, RGB or RGBA value into an RGBA tuple.

    Clamping to 0..1 is right for an albedo or a tint and wrong for anything
    that is not a reflectance. Measured: an emission colour of 50 in Maya
    arrived in Blender as 1, so a bright emissive material was silently
    flattened. Light colours are used as multipliers above one too, and a
    subsurface radius is a distance rather than a colour at all.
    """
    if isinstance(value, (list, tuple)):
        values = [float(item) for item in value]
    else:
        values = [float(value)] * 3
    while len(values) < 3:
        values.append(values[-1] if values else 1.0)
    alpha = values[3] if len(values) > 3 else 1.0
    if not clamp:
        return (
            max(0.0, values[0]),
            max(0.0, values[1]),
            max(0.0, values[2]),
            max(0.0, alpha),
        )
    return (
        max(0.0, min(1.0, values[0])),
        max(0.0, min(1.0, values[1])),
        max(0.0, min(1.0, values[2])),
        max(0.0, min(1.0, alpha)),
    )


def scalar(value, default=0.0):
    """Coerce a value to a float, averaging colour components when needed."""
    if isinstance(value, (list, tuple)):
        values = [float(item) for item in value[:3]]
        return sum(values) / float(len(values)) if values else float(default)
    try:
        return float(value)
    except Exception:
        return float(default)


def safe_name(value):
    """Strip characters Blender datablock names cannot hold."""
    value = re.sub(r'[<>:"/\\|?*\s]+', "_", str(value or "").strip())
    return value.strip("_") or "Material"


def strip_duplicate_suffix(value):
    """Remove Blender's ".001" style uniquifying suffix."""
    return re.sub(r"\.\d{3}$", "", value)


def normalize_name(value):
    return strip_duplicate_suffix(str(value or "")).strip().lower()


def namespace_free_name(value):
    """Short name without DAG path or Maya namespace."""
    value = str(value or "")
    value = value.split("|")[-1].split("/")[-1].split("\\")[-1]
    return value.rsplit(":", 1)[-1].strip()


def name_keys(value):
    """Every spelling a name might take, for matching FBX objects to records.

    The FBX exchange mangles Maya namespaces differently depending on version,
    so both ':' and '_' separated variants are produced.
    """
    value = strip_duplicate_suffix(str(value or ""))
    tail = value.split("|")[-1].split("/")[-1].split("\\")[-1]
    base = tail.rsplit(":", 1)[-1]
    variants = (
        value,
        tail,
        base,
        value.replace(":", "_"),
        tail.replace(":", "_"),
    )
    return set(normalize_name(item) for item in variants if item)


def package_namespace_prefixes(package_data):
    """Maya namespaces present in a package, longest first.

    Used to strip namespace prefixes that the FBX round trip flattened into
    the object name.
    """
    prefixes = set()
    records = list(package_data.get("meshes") or [])
    records.extend(package_data.get("lights") or [])
    for record in records:
        for field in (
            "mesh_full_name",
            "mesh_path",
            "shape",
            "shape_path",
            "full_name",
            "shape_full_name",
        ):
            if field not in record:
                continue
            value = str(record.get(field) or "")
            tail = value.split("|")[-1].split("/")[-1].split("\\")[-1]
            if ":" in tail:
                prefixes.add(tail.rsplit(":", 1)[0])
    return sorted(prefixes, key=len, reverse=True)


def namespace_free_import_name(value, namespace_prefixes=None):
    """Strip a namespace from an imported object name.

    Handles both a surviving ':' separator and the flattened forms the FBX
    importer produces ("ns_name", "ns__name").
    """
    value = str(value or "")
    tail = value.split("|")[-1].split("/")[-1].split("\\")[-1]
    if ":" in tail:
        return tail.rsplit(":", 1)[-1].strip()

    for prefix in namespace_prefixes or []:
        candidates = (
            prefix + "_",
            prefix.replace(":", "_") + "_",
            prefix.replace(":", "__") + "__",
        )
        for candidate in candidates:
            if tail.startswith(candidate):
                return tail[len(candidate):].strip()
    return tail.strip()


def unique_material_name(base):
    """Reserve an unused material name, avoiding Blender's ".001" suffixes."""
    if bpy.data.materials.get(base) is None:
        return base
    index = 1
    while True:
        candidate = "{0}_{1:03d}".format(base, index)
        if bpy.data.materials.get(candidate) is None:
            return candidate
        index += 1


def normalize_folder(folder):
    if not folder:
        raise ValueError("Package folder is empty.")
    folder = os.path.abspath(os.path.expanduser(bpy.path.abspath(folder)))
    if not os.path.isdir(folder):
        raise ValueError("Package folder does not exist: {0}".format(folder))
    return folder
