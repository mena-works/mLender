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
    ALEMBIC_MOTION_PROBES,
    ALEMBIC_MOTION_TOLERANCE,
    DEFORMER_NODE_TYPE,
)
from .mayautils import current_frame, parent_of, unique, world_matrix

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


def ancestor_paths(path):
    """Every transform above a full DAG path, outermost first."""
    parts = [part for part in (path or "").split("|") if part]
    return [
        "|" + "|".join(parts[:index]) for index in range(1, len(parts))
    ]


def probe_frames(animation, count):
    """Up to ``count`` frames spread across the range, both ends included."""
    try:
        start = float(animation.get("start"))
        end = float(animation.get("end"))
    except Exception:
        return []
    if end < start:
        start, end = end, start
    span = end - start
    if span <= 0.0:
        return []
    count = max(2, int(count))
    step = span / float(count - 1)
    return [start + step * index for index in range(count)]


def moving_transforms(transforms, animation):
    """Which transforms actually move, measured rather than inferred.

    A rigid body simulation has no animation curve, no keyed plug and no
    upstream connection worth walking: Bullet solves the transform each frame
    and writes the answer. So does an expression, and so does a constraint
    whose driver sits outside the export. Asking "is anything keyed above
    this" answers a different question, and answers it wrong for exactly the
    objects this option exists for -- the scene that prompted it had every one
    of its rigid bodies reported still.

    Stepping the timeline and reading the world matrix asks the real question.
    World, not local, because a prop that never moves in its own right still
    travels when the group holding it does.
    """
    paths = [path for path in unique(transforms or []) if path]
    frames = probe_frames(animation, ALEMBIC_MOTION_PROBES)
    if not paths or len(frames) < 2:
        return []

    original = current_frame()
    first = {}
    moving = set()
    try:
        for frame in frames:
            try:
                cmds.currentTime(frame, edit=True)
            except Exception:
                continue
            for path in paths:
                if path in moving:
                    continue
                matrix = world_matrix(path)
                if not matrix:
                    continue
                reference = first.get(path)
                if reference is None:
                    first[path] = matrix
                    continue
                for before, now in zip(reference, matrix):
                    if abs(before - now) > ALEMBIC_MOTION_TOLERANCE:
                        moving.add(path)
                        break
    finally:
        # The user's frame is restored whatever happened; parking their scene
        # somewhere else is not something an export may leave behind.
        try:
            cmds.currentTime(original, edit=True)
        except Exception:
            pass
    return [path for path in paths if path in moving]


def topmost_moving(path, moving):
    """The highest ancestor that also moves, or the path itself.

    A root has to be the top of the moving hierarchy. AbcExport records a
    root's own matrix and nothing above it, so rooting the cache at a prop
    inside a moving group would write the prop's local transform and leave the
    journey behind -- the object arrives, in the wrong place, holding still.
    """
    for ancestor in ancestor_paths(path):
        if ancestor in moving:
            return ancestor
    return path


def animated_cache_roots(shapes, animation):
    """Roots covering every mesh whose world transform moves.

    Deformation is not the question here: this is the option that carries a
    simulation, and a rigid body deforms nothing.
    """
    transforms = unique([
        transform for transform in
        (cache_root(shape) for shape in (shapes or [])) if transform
    ])
    if not transforms:
        return []
    candidates = unique(transforms + [
        ancestor
        for transform in transforms
        for ancestor in ancestor_paths(transform)
    ])
    moving = set(moving_transforms(candidates, animation))
    return unique([
        topmost_moving(transform, moving)
        for transform in transforms if transform in moving
    ])


def under_roots(path, roots):
    """Whether a path is one of the roots or hangs inside one.

    A root carries its whole subtree, so membership is not equality. Testing
    equality would leave a static prop inside a moving group in the FBX as
    well as the cache, and the receiver would build it twice.
    """
    if not path:
        return False
    for root in roots or ():
        if path == root or path.startswith(root + "|"):
            return True
    return False


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
