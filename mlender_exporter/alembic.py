# -*- coding: utf-8 -*-
"""An Alembic side channel for the two things FBX cannot carry.

Both cases were measured rather than assumed.

A mesh deformed by anything that is not a transform arrives **frozen**
through the FBX path: a cluster that moves vertices six units in Maya moved
them zero in Blender, with no warning. The same mesh through an Alembic
cache reproduced the motion exactly.

And an emitting particle system grows its count as it runs, which no
fixed-vertex-count mesh can represent. Alembic carries it, and Blender
rebuilds the varying counts exactly: 0, 3, 7 and 15 points at frames 1, 5,
10 and 20, the same numbers Maya reported.

So this is not a second exporter. It is a narrow side channel for those two
cases; everything else still travels as FBX plus JSON, and a package with
no cacheable object writes no Alembic file at all.
"""
from __future__ import absolute_import

import os

import maya.cmds as cmds

from .constants import (
    ALEMBIC_EXPORT_FLAGS,
    ALEMBIC_EXPORT_PLUGIN,
    DEFORMER_NODE_TYPE,
)
from .mayautils import parent_of, unique

# Deformers whose result is a rig's, not a shape edit's. They are listed so
# the caller can say what it found, not so they are treated differently:
# a cache of a skinned mesh is a cache of its result, never its rig.
RIG_DEFORMER_TYPES = ("skinCluster", "blendShape")


def plugin_loaded():
    """Load AbcExport, reporting whether it is actually available.

    Alembic ships with Maya but the plugin is not loaded by default, and a
    machine without it must degrade to the FBX path rather than fail the
    export outright.
    """
    try:
        if cmds.pluginInfo(ALEMBIC_EXPORT_PLUGIN, query=True, loaded=True):
            return True
    except Exception:
        pass
    try:
        cmds.loadPlugin(ALEMBIC_EXPORT_PLUGIN, quiet=True)
        return True
    except Exception:
        return False


def shape_deformers(shape):
    """Deformers upstream of a shape, nearest first, or an empty list.

    ``pruneDagObjects`` keeps the history to nodes, so a shape whose input
    happens to pass through another transform does not drag it in.
    """
    try:
        history = cmds.listHistory(shape, pruneDagObjects=True) or []
    except Exception:
        return []
    try:
        return cmds.ls(history, type=DEFORMER_NODE_TYPE) or []
    except Exception:
        return []


def deformed_shapes(shapes):
    """The shapes whose points move, which is what FBX loses."""
    return [shape for shape in shapes if shape_deformers(shape)]


def cache_only_shapes(shapes):
    """The deformed shapes the cache is genuinely the only route for.

    A shape whose deformers are all rig deformers does not belong here: FBX
    carries a skin as an armature binding and a blendShape as shape keys, so
    it arrives *posable* -- measured, a production character poses in Blender
    through exactly that path. Putting it in the cache instead freezes the
    result and throws the rig away.

    A shape with any other deformer -- cluster, wire, lattice, nonlinear --
    still needs the cache, and when a rig deformer sits on the same shape the
    cache wins: it carries the final result, skin included, where FBX would
    carry the skin and lose the rest.
    """
    kept = []
    for shape in shapes:
        deformers = shape_deformers(shape)
        if not deformers:
            continue
        kinds = set()
        for node in deformers:
            try:
                kinds.add(cmds.nodeType(node))
            except Exception:
                kinds.add("")
        if kinds - set(RIG_DEFORMER_TYPES):
            kept.append(shape)
    return kept


def cache_root(shape):
    """The transform an Alembic root should name for a shape."""
    return parent_of(shape)


def cache_roots(shapes):
    return unique([root for root in map(cache_root, shapes) if root])


def export_alembic(roots, path, animation):
    """Write one Alembic holding every root. True when a file was written.

    A single file rather than one per object: Blender makes one cache
    datablock per file, and a scene of twenty caches would otherwise carry
    twenty readers pointing at the same directory.
    """
    if not roots:
        return False
    if not plugin_loaded():
        return False

    folder = os.path.dirname(path)
    if folder and not os.path.isdir(folder):
        os.makedirs(folder)

    job = list(ALEMBIC_EXPORT_FLAGS)
    job.append("-frameRange {0:g} {1:g}".format(
        _number(animation.get("start"), 1.0),
        _number(animation.get("end"), 1.0),
    ))
    step = _number(animation.get("step"), 1.0)
    if step and step != 1.0:
        job.append("-step {0:g}".format(step))
    for root in roots:
        job.append("-root {0}".format(root))
    # Forward slashes: the job string is parsed by the plugin, which reads a
    # backslash as an escape rather than as a separator.
    job.append("-file {0}".format(path.replace("\\", "/")))

    try:
        cmds.AbcExport(j=" ".join(job))
    except Exception:
        return False
    return os.path.isfile(path)


def rig_deformed(shapes):
    """Shapes whose motion comes from a rig, for the caller to report.

    A cache carries the deformed result and nothing that drives it, so a
    user who caches a skinned character gets geometry in Blender and no way
    to pose it. That is worth saying out loud rather than discovering.
    """
    found = []
    for shape in shapes:
        deformers = shape_deformers(shape)
        if not deformers:
            continue
        try:
            kinds = set(cmds.nodeType(node) for node in deformers)
        except Exception:
            continue
        if kinds.intersection(RIG_DEFORMER_TYPES):
            found.append(shape)
    return found


def _number(value, default):
    try:
        return float(value)
    except Exception:
        return default
