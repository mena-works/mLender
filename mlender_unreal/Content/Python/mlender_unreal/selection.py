# -*- coding: utf-8 -*-
"""Per-object import selection: the pure half.

The Import window shows a package as a checkbox tree and the importer builds
only what is ticked. Everything that can be computed without ``unreal`` lives
here -- path tests, the manifest the tree loads, the pruning of a package's
records -- so ``check_contracts.py`` exercises all of it host-free, at the
same altitude as ``utils``.

The identity everything hangs on: every record kind carries a full Maya DAG
path (``|grp|sub|mesh``), verified in the exporter (``listRelatives`` with
``fullPath``) and in a real 11,008-mesh package. Motion objects and the
importer's ``actors_by_path`` are keyed by the same paths, so one include
test covers records, movers and set membership alike.

A selection is a list of paths; a listed path includes its descendants. Two
deliberate asymmetries:

- A **transform** that is an ancestor of a ticked path is kept even when it
  is not ticked itself, because locator parent chains wire silently and a
  pruned parent would drop the wiring without a word.
- A **mesh** is never ancestor-kept: an unticked parent mesh must not bring
  its geometry along.
"""

import json
import os


# (record list, path field, manifest kind). Lights, cameras, sets, animation,
# AOVs and the alembic cache are global switches, not tree nodes -- lighting
# always travels whole, and a cache cannot be pruned per object.
KIND_FIELDS = (
    ("meshes", "mesh_path", "mesh"),
    ("transforms", "transform_path", "transform"),
    ("curves", "curve_path", "curve"),
    ("volumes", "volume_path", "volume"),
    ("standins", "standin_path", "standin"),
    ("particles", "particle_path", "particle"),
    ("instancers", "instancer_path", "instancer"),
)

COUNT_MIRRORS = {
    "meshes": "mesh_count",
    "transforms": "transform_count",
    "curves": "curve_count",
    "volumes": "volume_count",
    "standins": "standin_count",
    "particles": "particle_count",
    "instancers": "instancer_count",
}

MANIFEST_VERSION = 1
SELECTION_VERSION = 1

# The tree's kind vocabulary, index 0 first. "group" is a DAG component with
# no record of its own -- the same rule the mesh importer uses for folders.
MANIFEST_KINDS = ("group", "mesh", "transform", "curve", "volume",
                  "standin", "particle", "instancer")


def normalize_include_paths(include_paths):
    """Selection paths as the exporter writes them: ``|a|b``, no dupes.

    ``None`` stays ``None`` -- it means "everything", which is a different
    thing from an empty selection.
    """
    if include_paths is None:
        return None
    seen = set()
    cleaned = []
    for path in include_paths:
        text = str(path or "").strip().rstrip("|")
        if not text:
            continue
        if not text.startswith("|"):
            text = "|" + text
        if text in seen:
            continue
        seen.add(text)
        cleaned.append(text)
    return cleaned


def build_include_index(include_paths):
    """The two sets every include test needs, built once.

    ``included`` holds the listed paths; ``ancestors`` every proper prefix of
    a listed path. Returns ``None`` for ``None``, so the default path costs
    nothing.
    """
    paths = normalize_include_paths(include_paths)
    if paths is None:
        return None
    included = set(paths)
    ancestors = set()
    for path in paths:
        parts = path.split("|")
        prefix = ""
        for part in parts[1:-1]:
            prefix += "|" + part
            ancestors.add(prefix)
    return {"included": included, "ancestors": ancestors}


def path_included(path, index):
    """Is this path a listed path or a descendant of one? O(depth)."""
    if index is None:
        return True
    text = str(path or "")
    if not text:
        return False
    included = index["included"]
    prefix = ""
    for part in text.split("|")[1:]:
        prefix += "|" + part
        if prefix in included:
            return True
    return False


def _stats():
    return {"kept": {}, "dropped": {}, "total_kept": 0, "total_dropped": 0}


def prune_package_data(package_data, include_paths):
    """A copy of the package holding only what the selection names.

    Returns ``(pruned, stats, dropped_meshes)``. ``include_paths=None``
    returns the input **by identity** -- the everyday full import must not
    pay for a feature it is not using. An empty or matchless selection
    raises ``ValueError``: the caller checks the selection *before* the
    level is cleared, and a selection that builds nothing must cost nothing.

    The caller's dict is never mutated; only the replaced lists are new.
    """
    if include_paths is None:
        return package_data, _stats(), []
    index = build_include_index(include_paths)
    if not index or not index["included"]:
        raise ValueError(
            "The selection is empty; nothing was imported and the level "
            "was not touched."
        )

    pruned = dict(package_data or {})
    stats = _stats()
    dropped_meshes = []
    kept_transform_paths = set()

    for list_key, path_field, _kind in KIND_FIELDS:
        records = list((package_data or {}).get(list_key) or [])
        kept = []
        dropped = 0
        for record in records:
            path = str((record or {}).get(path_field) or "")
            keep = path_included(path, index)
            if not keep and list_key == "transforms":
                # An ancestor of a ticked path: parent chains wire silently,
                # so the locator above a ticked mesh has to exist.
                keep = path in index["ancestors"]
            if keep:
                kept.append(record)
                if list_key == "transforms":
                    kept_transform_paths.add(path)
            else:
                dropped += 1
                if list_key == "meshes":
                    dropped_meshes.append(record)
        pruned[list_key] = kept
        stats["kept"][list_key] = len(kept)
        stats["dropped"][list_key] = dropped
        stats["total_kept"] += len(kept)
        stats["total_dropped"] += dropped
        mirror = COUNT_MIRRORS.get(list_key)
        if mirror and mirror in pruned:
            pruned[mirror] = len(kept)

    if not stats["total_kept"]:
        raise ValueError(
            "The selection matches nothing in this package; nothing was "
            "imported and the level was not touched."
        )

    if "particle_baked_count" in pruned:
        pruned["particle_baked_count"] = sum(
            1 for record in pruned.get("particles") or []
            if (record or {}).get("samples")
        )

    def member_kept(member):
        path = str(member or "")
        return path_included(path, index) or path in kept_transform_paths

    # The exporter's own rule: members filtered to what exists, a record
    # whose member list empties is dropped entirely.
    for set_key in ("selection_sets", "object_sets", "display_layers"):
        records = list((package_data or {}).get(set_key) or [])
        kept_records = []
        for record in records:
            if not isinstance(record, dict):
                continue
            members = [m for m in (record.get("members") or [])
                       if member_kept(m)]
            if not members:
                continue
            copy = dict(record)
            copy["members"] = members
            kept_records.append(copy)
        if set_key in pruned or kept_records:
            pruned[set_key] = kept_records

    return pruned, stats, dropped_meshes


def prune_motion(motion, index):
    """The motion dict reduced to the selection, and how many movers left.

    Pruned rather than left to fail: the player's "no actor matched" warning
    is for loss, and reporting deliberate filtering as loss would teach the
    reader to ignore it. A mover that is an *ancestor* of a ticked path is
    kept -- a moving group above a ticked mesh still travels.
    """
    if index is None or not isinstance(motion, dict):
        return motion, 0
    objects = motion.get("objects") or {}
    kept = {}
    for path, track in objects.items():
        if path_included(path, index) or path in index["ancestors"]:
            kept[path] = track
    dropped = len(objects) - len(kept)
    if not dropped:
        return motion, 0
    pruned = dict(motion)
    pruned["objects"] = kept
    if "object_count" in pruned:
        pruned["object_count"] = len(kept)
    return pruned, dropped


def manifest_payload(package_data, package_folder, source_name="",
                     source_mtime=0.0, source_size=0):
    """The outliner's food: the hierarchy as parallel arrays.

    ``names``/``parents``/``kinds``, with every parent strictly before its
    children, so the window builds the tree in one forward pass and
    reconstructs each full path by walking ``parents`` -- exactly, because
    the names are raw DAG components with escapes untouched. Nothing here
    stores full paths per node; at 11k nodes that is the difference between
    hundreds of KB and several MB.
    """
    data = package_data or {}
    names = []
    parents = []
    kinds = []
    by_path = {}
    kind_index = dict((kind, i) for i, kind in enumerate(MANIFEST_KINDS))

    def node_for(path, kind_name):
        node = by_path.get(path)
        if node is not None:
            # A path that is both an ancestor and a record keeps the record's
            # kind: a locator with children is a transform, not a folder.
            if kind_name != "group" and kinds[node] == kind_index["group"]:
                kinds[node] = kind_index[kind_name]
            return node
        parent = -1
        cut = path.rfind("|")
        if cut > 0:
            parent = node_for(path[:cut], "group")
        index = len(names)
        names.append(path[cut + 1:])
        parents.append(parent)
        kinds.append(kind_index[kind_name])
        by_path[path] = index
        return index

    for list_key, path_field, kind_name in KIND_FIELDS:
        for record in (data.get(list_key) or []):
            path = str((record or {}).get(path_field) or "")
            if path.startswith("|"):
                node_for(path, kind_name)

    animation = data.get("animation") or {}
    alembic = data.get("alembic") or {}
    motion = data.get("motion") or {}
    return {
        "manifest_version": MANIFEST_VERSION,
        "package_folder": str(package_folder or ""),
        "package_name": str(data.get("package_name") or ""),
        "schema_version": data.get("schema_version"),
        "source_json": str(source_name or ""),
        "source_mtime": float(source_mtime or 0.0),
        "source_size": int(source_size or 0),
        "kind_names": list(MANIFEST_KINDS),
        "node_count": len(names),
        "names": names,
        "parents": parents,
        "kinds": kinds,
        "globals": {
            "light_count": len(data.get("lights") or []),
            "camera_count": len(data.get("cameras") or []),
            "selection_set_count": (
                len(data.get("selection_sets") or [])
                + len(data.get("object_sets") or [])
            ),
            "display_layer_count": len(data.get("display_layers") or []),
            "animation_enabled": bool(animation.get("enabled")),
            "alembic_mesh_count": int(alembic.get("mesh_count") or 0),
            "motion_object_count": int(motion.get("object_count") or 0),
            "export_warning_count": len(data.get("export_warnings") or []),
        },
    }


def read_selection_file(path):
    """The window's ticked paths, validated. Raises on anything unusable.

    The file is how C++ hands 5,000 paths to Python without pushing them
    through a command string -- DAG names carry escapes that would need
    quoting, and a command line that long is an injection surface.
    """
    if not path or not os.path.isfile(path):
        raise ValueError("No selection file at {0!r}.".format(path))
    with open(path, "r") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError("The selection file is not an object.")
    if data.get("selection_version") != SELECTION_VERSION:
        raise ValueError(
            "Selection file version {0!r} is not {1}; the window and the "
            "plugin are out of step.".format(
                data.get("selection_version"), SELECTION_VERSION
            )
        )
    folder = str(data.get("package_folder") or "")
    if not folder:
        raise ValueError("The selection file names no package folder.")
    if data.get("include_all"):
        return folder, None
    include_paths = normalize_include_paths(data.get("include_paths") or [])
    if not include_paths:
        raise ValueError(
            "The selection is empty; nothing was imported and the level "
            "was not touched."
        )
    return folder, include_paths
