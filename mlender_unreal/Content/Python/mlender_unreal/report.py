# -*- coding: utf-8 -*-
"""A human readable import report, written beside the package.

The Unreal receiver produces more warnings than either of the other two -- more
than sixty on the test fixture -- because it reports every kind Unreal has no
equivalent for. The Output Log is not a good place to read sixty lines, and it
cannot be handed to anybody.

Written into the package folder next to the Blender receiver's, so one package
carries what was sent and what each host made of it.

Never allowed to fail the import: a package folder can legitimately be read
only, and losing a good import over a log file would be absurd.
"""

import os

from .constants import BUILD_VERSION, TOOL_NAME


REPORT_SUFFIX = "_import_unreal.txt"
MAX_LISTED = 400


def report_path(package_folder, package_name):
    return os.path.join(package_folder, package_name + REPORT_SUFFIX)


def build_report(result, engine_version=""):
    warnings = list(result.get("warnings") or [])
    lines = []
    lines.append("{0} Unreal import report".format(TOOL_NAME))
    lines.append("=" * 60)
    lines.append("")
    lines.append("build            {0}".format(BUILD_VERSION))
    if engine_version:
        lines.append("unreal           {0}".format(engine_version))
    lines.append("package          {0}".format(
        result.get("package_folder") or "?"))
    lines.append("")

    lines.append("what arrived")
    lines.append("-" * 60)
    for label, key in (
        ("static meshes", "mesh_count"),
        ("  distinct assets", "mesh_asset_count"),
        ("  sharing one", "mesh_shared_count"),
        ("  filtered out by selection", "filtered_out_count"),
        ("skeletal meshes", "skeletal_count"),
        ("materials", "material_count"),
        ("lights", "light_count"),
        ("cameras", "camera_count"),
        ("locators", "transform_count"),
        ("curves", "curve_count"),
        ("  as splines", "curve_splines"),
        ("volumes", "volume_count"),
        ("  with a VDB", "volume_loaded"),
        ("standins", "standin_count"),
        ("  with a cache", "standin_loaded"),
        ("particle systems", "particle_count"),
        ("instancers", "instancer_count"),
        ("  instances", "instance_count"),
        ("alembic caches", "alembic_count"),
        ("movers on the player", "motion_object_count"),
        ("  samples kept", "motion_key_count"),
        ("layers", "layer_count"),
        ("sets", "set_count"),
        ("AS rigs", "as_rig_count"),
    ):
        value = result.get(key)
        if value:
            lines.append("  {0:18s} {1}".format(label, value))
    lines.append("")

    timings = list(result.get("timings") or [])
    total = float(result.get("total_seconds") or 0.0)
    if timings and total > 0.0:
        # Where the time went. A long import names nothing; a phase does.
        lines.append("time ({0})".format(_duration(total)))
        lines.append("-" * 60)
        for label, seconds in timings:
            lines.append("  {0:44s} {1:>10s}".format(
                str(label)[:44], _duration(seconds)))
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
    lines.append("")
    lines.append(
        "A warning is not a failure. It is the part of the Maya scene that "
        "did not"
    )
    lines.append(
        "travel the way you might assume, named so you can decide whether it "
        "matters."
    )
    return lines


def _duration(seconds):
    """Seconds as a person reads them: 4.2 s, 3 min 12 s, 1 h 05 min."""
    try:
        seconds = float(seconds)
    except (TypeError, ValueError):
        return "?"
    if seconds < 60.0:
        return "{0:.1f} s".format(seconds)
    minutes, rest = divmod(int(round(seconds)), 60)
    if minutes < 60:
        return "{0} min {1:02d} s".format(minutes, rest)
    hours, minutes = divmod(minutes, 60)
    return "{0} h {1:02d} min".format(hours, minutes)


def write_report(result, engine_version=""):
    folder = result.get("package_folder")
    if not folder or not os.path.isdir(folder):
        return ""
    name = os.path.basename(os.path.normpath(folder))
    path = report_path(folder, name)
    try:
        with open(path, "w", encoding="utf-8", newline="\n") as handle:
            for line in build_report(result, engine_version):
                handle.write(line)
                handle.write("\n")
    except Exception:
        return ""
    return path
