# -*- coding: utf-8 -*-
"""What the export did not account for, so it is said rather than lost.

Discovery is type by type: meshes, lights, cameras, locators, curves,
volumes, particles, instancers. Anything not on one of those lists leaves the
scene without a word, and measuring found six more kinds doing exactly that
-- NURBS surfaces, Maya subdivision surfaces, gpuCache, aiStandIn, fluids and
hair systems -- with no warning between them.

Adding a discovery module per kind fixes those six and leaves the seventh
silent. This closes the class instead: every renderable shape in the scene is
compared against what the package carries, and whatever is left over is
reported. A kind nobody has thought of yet turns from a silent loss into a
line the user can read.

The same defensive habit as ``scene_light_shapes``, which scans for unknown
light types rather than trusting its list.
"""
from __future__ import absolute_import

import maya.cmds as cmds

from .constants import (
    COVERAGE_IGNORED_SHAPE_TYPES,
    CURVE_ON_SURFACE_MARK,
    TESSELLATION_SUFFIX,
)
from .mayautils import node_type, parent_of, unique


def scene_shapes():
    """Every DAG shape that could plausibly carry something renderable."""
    try:
        shapes = cmds.ls(type="geometryShape", long=True,
                         noIntermediate=True) or []
    except Exception:
        return []
    return unique([shape for shape in shapes if parent_of(shape)])


def unaccounted_shapes(exported_paths):
    """Shapes whose transform never made it into the package.

    Matching is by transform rather than by shape: that is the path every
    record type keys itself by, and an instanced shape hangs under several.
    """
    accounted = set(exported_paths or [])
    missing = []
    for shape in scene_shapes():
        kind = node_type(shape)
        if kind in COVERAGE_IGNORED_SHAPE_TYPES:
            continue
        # A curve on surface is construction data -- a trim boundary, a
        # projection -- and the exporter drops it on purpose. Calling it lost
        # would put one warning per trim region in front of the user.
        if CURVE_ON_SURFACE_MARK in shape:
            continue
        transform = parent_of(shape)
        if not transform or transform in accounted:
            continue
        # A surface that was tessellated for this export did travel -- as the
        # polygon stand-in wearing its name. Its original is standing aside
        # under a suffix, and reporting it as missing would contradict the
        # line that says it was carried.
        if transform.endswith(TESSELLATION_SUFFIX):
            continue
        missing.append((transform, kind))
    return missing


def coverage_warnings(exported_paths):
    """One line per kind left behind, with a count and an example.

    Grouped by type rather than listed one by one: a scene with four hundred
    unsupported nodes should say so in a line, not four hundred.
    """
    by_kind = {}
    for transform, kind in unaccounted_shapes(exported_paths):
        by_kind.setdefault(kind, []).append(transform)

    warnings = []
    for kind in sorted(by_kind):
        found = by_kind[kind]
        warnings.append(
            '{0} "{1}" object(s) were not exported; this build does not '
            "carry that type. First: {2}".format(
                len(found), kind, found[0]
            )
        )
    return warnings
