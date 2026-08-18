# -*- coding: utf-8 -*-
"""A human readable import report, written beside the package.

An import routinely produces dozens of warnings -- the test fixture makes more
than sixty -- and until now the only place to read them was the System Console,
which scrolls and cannot be handed to anybody. The report is one file to send.

Written into the package folder, next to the export's own report, so a package
carries the whole story: what was sent, and what each receiver made of it.

Never allowed to fail the import. A package folder can legitimately be read
only -- somebody else's drive, a network share -- and losing a good import over
a log file would be absurd.
"""

import os

from .constants import BUILD_VERSION


REPORT_SUFFIX = "_import_blender.txt"
MAX_LISTED = 400


def report_path(package_folder, package_name):
    return os.path.join(package_folder, package_name + REPORT_SUFFIX)


def build_report(result, blender_version=""):
    """The report body as lines, so it is testable without a disk."""
    warnings = list(result.get("warnings") or [])
    lines = []
    lines.append("mLender Blender import report")
    lines.append("=" * 60)
    lines.append("")
    lines.append("build            {0}".format(BUILD_VERSION))
    if blender_version:
        lines.append("blender          {0}".format(blender_version))
    lines.append("package          {0}".format(
        result.get("package_folder") or "?"))
    lines.append("mode             {0}".format(result.get("import_mode") or "?"))
    lines.append("")

    lines.append("what arrived")
    lines.append("-" * 60)
    for label, key in (
        ("meshes", "mesh_count"),
        ("materials", "material_count"),
        ("lights", "light_count"),
        ("cameras", "camera_count"),
        ("collections", "group_collection_count"),
        ("empties", "transform_count"),
        ("curves", "curve_count"),
        ("volumes", "volume_count"),
        ("standins", "standin_count"),
        ("particles", "particle_count"),
        ("instancers", "instancer_count"),
        ("cached objects", "alembic_count"),
        ("subdivisions", "subdivision_count"),
        ("sets", "set_count"),
        ("layers", "layer_count"),
        ("AOV passes", "aov_mapped"),
        ("empty AOV slots", "aov_custom"),
        ("repointed paths", "repointed_paths"),
    ):
        value = result.get(key)
        if value:
            lines.append("  {0:18s} {1}".format(label, value))
    lines.append("")

    lines.append("warnings ({0})".format(len(warnings)))
    lines.append("-" * 60)
    if not warnings:
        lines.append("  none")
    else:
        for warning in warnings[:MAX_LISTED]:
            lines.append("  - {0}".format(warning))
        if len(warnings) > MAX_LISTED:
            lines.append("  ... and {0} more".format(
                len(warnings) - MAX_LISTED))
    return lines


def write_report(result, blender_version=""):
    """Write the report into the package folder. Returns the path, or ""."""
    folder = result.get("package_folder")
    if not folder or not os.path.isdir(folder):
        return ""
    name = os.path.basename(os.path.normpath(folder))
    path = report_path(folder, name)
    try:
        with open(path, "w", encoding="utf-8", newline="\n") as handle:
            for line in build_report(result, blender_version):
                handle.write(line)
                handle.write("\n")
    except Exception:
        return ""
    return path
