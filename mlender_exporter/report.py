# -*- coding: utf-8 -*-
"""A human readable report written into the package.

The warnings are the most useful thing an export produces and until now the
only way to read them was the Script Editor, which scrolls away. A package that
carries its own report can be handed to somebody else -- or back to whoever
wrote the tool -- without anybody having to copy console lines.

Written last and never allowed to fail the export: a report is a convenience,
and losing a good package because its report could not be written would be the
tail wagging the dog.
"""
from __future__ import absolute_import

import os

from .constants import TOOL_NAME


REPORT_SUFFIX = "_report.txt"
# Long enough to be useful, short enough that a file is not the problem.
MAX_LISTED = 400


def report_path(package_folder, package_name):
    return os.path.join(package_folder, package_name + REPORT_SUFFIX)


def _line(handle, text=""):
    handle.write(text)
    handle.write("\n")


def build_report(result, build_version, maya_version="", renderer=""):
    """The report body as a list of lines, so it can be tested without a disk."""
    payload = result.get("package_json") or {}
    warnings = list(result.get("warnings") or [])
    lines = []
    lines.append("{0} export report".format(TOOL_NAME))
    lines.append("=" * 60)
    lines.append("")
    lines.append("build            {0}".format(build_version))
    lines.append("package          {0}".format(result.get("package_name")))
    lines.append("exported at      {0}".format(
        payload.get("exported_at_utc") or "?"))
    lines.append("maya scene       {0}".format(payload.get("maya_scene") or "?"))
    if maya_version:
        lines.append("maya             {0}".format(maya_version))
    if renderer:
        lines.append("renderer         {0}".format(renderer))
    lines.append("schema           {0}".format(
        payload.get("schema_version") or "?"))
    lines.append("linear unit      {0} ({1} m per unit)".format(
        payload.get("maya_linear_unit") or "?",
        payload.get("meters_per_maya_unit") or "?"))
    lines.append("")

    lines.append("contents")
    lines.append("-" * 60)
    for label, key in (
        ("meshes", "mesh_count"),
        ("lights", "light_count"),
        ("cameras", "camera_count"),
        ("curves", "curve_count"),
        ("volumes", "volume_count"),
        ("standins", "standin_count"),
        ("particles", "particle_count"),
        ("instancers", "instancer_count"),
        ("transforms", "transform_count"),
    ):
        value = payload.get(key)
        if value:
            lines.append("  {0:14s} {1}".format(label, value))
    for label, key in (
        ("selection sets", "selection_sets"),
        ("display layers", "display_layers"),
        ("AOVs", "aovs"),
        ("AS rigs", "as_rigs"),
        ("constraints", "constraints"),
    ):
        items = payload.get(key) or []
        if items:
            lines.append("  {0:14s} {1}".format(label, len(items)))
    if result.get("baked_texture_count"):
        lines.append("  {0:14s} {1}".format(
            "baked maps", result.get("baked_texture_count")))
    if result.get("animated"):
        lines.append("  {0:14s} {1} frame(s)".format(
            "animation", result.get("frame_count")))
    lines.append("")

    timings = list(result.get("timings") or [])
    total = float(result.get("total_seconds") or 0.0)
    if timings and total > 0.0:
        # Where the time went. A long export names nothing; a phase does.
        lines.append("time ({0})".format(_duration(total)))
        lines.append("-" * 60)
        for label, seconds in timings:
            lines.append("  {0:40s} {1:>10s}".format(
                str(label)[:40], _duration(seconds)))
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
        "Every line above is something the exporter noticed. A warning is not "
        "a failure;"
    )
    lines.append(
        "it is the part of the scene that did not travel the way you might "
        "assume."
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


def write_report(result, build_version, maya_version="", renderer=""):
    """Write the report beside the package JSON. Returns the path, or ""."""
    folder = result.get("package_folder")
    name = result.get("package_name")
    if not folder or not name or not os.path.isdir(folder):
        return ""
    path = report_path(folder, name)
    try:
        lines = build_report(result, build_version, maya_version, renderer)
        with open(path, "w") as handle:
            for line in lines:
                _line(handle, line)
    except Exception:
        # Never at the cost of the export.
        return ""
    return path
