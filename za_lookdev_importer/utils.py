# -*- coding: utf-8 -*-
"""Value coercion and Maya/Blender name normalisation helpers.

Package JSON is user-scene derived and loosely typed: a channel value may be a
float, an RGB list or an RGBA list. These helpers coerce whatever arrives into
the shape Blender sockets expect instead of trusting the payload.
"""

import os
import re

import bpy


def color4(value):
    """Coerce a scalar, RGB or RGBA value into a clamped RGBA tuple."""
    if isinstance(value, (list, tuple)):
        values = [float(item) for item in value]
    else:
        values = [float(value)] * 3
    while len(values) < 3:
        values.append(values[-1] if values else 1.0)
    alpha = values[3] if len(values) > 3 else 1.0
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
