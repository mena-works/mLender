# -*- coding: utf-8 -*-
"""Frame range resolution and timeline sampling.

Meshes do not come through here. Their animation is baked into the FBX, which
is what the exchange format is for and what carries deformers correctly. Only
lights and cameras are sampled, because those are rebuilt from JSON and would
otherwise arrive frozen at the current frame.

The timeline is stepped once for every sampler together rather than once per
object: changing the current frame forces a scene evaluation, which is the
expensive part, and doing it per object would multiply that by the object
count.
"""
from __future__ import absolute_import

import array
import math

import maya.cmds as cmds
import maya.mel as mel

from .constants import (
    DEFAULT_FPS,
    MAX_ANIMATION_FRAMES,
    TIME_UNIT_FPS,
    TRANSFORM_VISIBILITY_ATTRS,
    UNSTABLE_REVERSAL_COS,
    UNSTABLE_RUN,
    UNSTABLE_STEP_METRES,
)
from .mayautils import (
    current_frame,
    node_label,
    parent_of,
    plug_value,
)


def scene_fps():
    """Frames per second, asked of Maya before falling back to the table."""
    try:
        fps = float(mel.eval("currentTimeUnitToFPS"))
        if fps > 0.0:
            return fps
    except Exception:
        pass
    try:
        unit = str(cmds.currentUnit(query=True, time=True) or "")
    except Exception:
        unit = ""
    return TIME_UNIT_FPS.get(unit, DEFAULT_FPS)


def playback_range():
    """The range the artist is looking at, not the outer animation range."""
    try:
        start = float(cmds.playbackOptions(query=True, minTime=True))
        end = float(cmds.playbackOptions(query=True, maxTime=True))
        return start, end
    except Exception:
        frame = current_frame()
        return frame, frame


def animation_info(enabled, start=None, end=None, step=None):
    """Resolve the frame range to export, or report a single frame."""
    fps = scene_fps()
    frame = current_frame()
    if not enabled:
        return {
            "enabled": False,
            "fps": fps,
            "start": frame,
            "end": frame,
            "step": 1.0,
            "frame_count": 1,
            "truncated": False,
        }

    play_start, play_end = playback_range()
    start = play_start if start is None else _number(start, play_start)
    end = play_end if end is None else _number(end, play_end)
    step = max(0.001, _number(step, 1.0))
    if end < start:
        start, end = end, start

    count = int(math.floor((end - start) / step + 1e-6)) + 1
    truncated = count > MAX_ANIMATION_FRAMES
    if truncated:
        count = MAX_ANIMATION_FRAMES
        end = start + (count - 1) * step

    return {
        "enabled": True,
        "fps": fps,
        "start": start,
        "end": end,
        "step": step,
        "frame_count": count,
        "truncated": truncated,
    }


def frame_list(settings):
    if not settings.get("enabled"):
        return []
    start = _number(settings.get("start"), 0.0)
    step = max(0.001, _number(settings.get("step"), 1.0))
    count = int(settings.get("frame_count") or 0)
    return [start + index * step for index in range(count)]


def sample_records(settings, entries, visitors=()):
    """Attach a ``samples`` list to each record by stepping the timeline.

    ``entries`` is a sequence of ``(record, sampler)`` pairs, where sampler is
    called with no arguments at each frame and returns a plain dict. Keeping
    the samplers opaque is what lets this module stay independent of lights
    and cameras.

    ``visitors`` are called once per frame after the samplers, with nothing,
    and keep their own state: that is how the movers ride this walk instead
    of making one of their own. Stepping the timeline is what an export of a
    simulation pays for -- measured 0.4 s a frame on a shot of 12 028 meshes
    and a Bullet solver, and the shot was walked twice, once for the lights
    and once for the movers, at three and a half minutes a walk.

    The current frame is always restored, including when a sampler raises;
    leaving the user's scene parked on a different frame would be a visible
    side effect of exporting.
    """
    frames = frame_list(settings)
    if not frames or (not entries and not visitors):
        return 0

    for record, _sampler in entries:
        record["samples"] = []

    original = current_frame()
    try:
        for frame in frames:
            try:
                cmds.currentTime(frame, edit=True)
            except Exception:
                continue
            for record, sampler in entries:
                try:
                    sample = sampler()
                except Exception:
                    continue
                sample["frame"] = frame
                record["samples"].append(sample)
            for visitor in visitors:
                try:
                    visitor()
                except Exception:
                    continue
    finally:
        try:
            cmds.currentTime(original, edit=True)
        except Exception:
            pass
    return len(frames)


def _api_readers(pairs, read_visibility=True):
    """Per mover, what the API needs to read it each frame, or None.

    A ``cmds`` call is a command round trip -- parse, resolve the name,
    evaluate, marshal a list back -- and the sampler makes one per mover per
    frame: 3.9 million of them on a shot of 7500 movers over 520 frames,
    which was most of a sixteen minute export. The API resolves the node
    once and reads the same plugs directly after that.

    Visibility is read the same way, and only where it can change: a plug
    with an incoming connection (an animation curve, an expression, a
    driver) is read every frame, while one that nothing drives is read once.
    A hidden object whose plug is static is hidden on every frame, which is
    what reading it 520 times would have said.

    None when any mover cannot be resolved, so the sampler runs one code
    path or the other for the whole shot rather than a mixture nothing has
    measured. Both paths produce the same numbers: measured on the fixture,
    every matrix identical and every visibility channel identical.
    """
    try:
        from maya.api import OpenMaya
    except Exception:
        return None
    attrs = []
    for candidates in TRANSFORM_VISIBILITY_ATTRS.values():
        attrs.extend(candidates)
    readers = {}
    for key, path in pairs:
        try:
            selection = OpenMaya.MSelectionList()
            selection.add(path)
            dag = selection.getDagPath(0)
            node = OpenMaya.MFnDependencyNode(dag.node())
            dynamic = []
            hidden = False
            # No reader given means the caller wants every frame visible,
            # which is what the command path answers without one.
            for attr in (attrs if read_visibility else ()):
                if not node.hasAttribute(attr):
                    continue
                plug = node.findPlug(attr, False)
                if plug.isDestination:
                    dynamic.append(plug)
                elif not plug.asBool():
                    hidden = True
        except Exception:
            return None
        readers[key] = (dag, tuple(dynamic), hidden)
    return readers


def _api_sample(reader, track):
    """One frame of one mover through the API. False when it could not be read."""
    dag, dynamic, hidden = reader
    try:
        matrix = dag.inclusiveMatrix()
    except Exception:
        return False
    values = track["matrix"]
    # Row major with the translation in the last row, which is the order
    # cmds.xform -matrix hands back; the constant fourth column is dropped.
    for row in range(4):
        for column in range(3):
            values.append(matrix.getElement(row, column))
    visible = not hidden
    if visible:
        for plug in dynamic:
            try:
                if not plug.asBool():
                    visible = False
                    break
            except Exception:
                continue
    track["visible"].append(1 if visible else 0)
    return True


def sample_motion(settings, entries, visible_at=None):
    """World matrices and visibility per frame, for movers that only move.

    A rigid body needs a transform per frame, not a mesh per frame, so this
    is what replaces a geometry cache for everything that does not deform.

    Matrices rather than translate/rotate/scale, because every receiver
    already has a measured way to turn a Maya world matrix into its own
    frame, and Maya's Euler angles would need a second, unmeasured one --
    Unreal's object axes are not its light axes, and getting that wrong is a
    silent mirror rather than an error.

    Flat arrays rather than a record per frame: the shot this was written for
    has 3384 movers over 520 frames, and a dict per sample spends more on
    repeating the word "matrix" than on the motion. The fourth column is
    dropped because Maya never varies it -- it is 0, 0, 0, 1 on every sample
    of every object -- and a quarter of a shot's motion is worth not writing.

    World space, matching what the cache did, so a prop inside a moving group
    carries its journey without the group having to travel with it.

    This walks the timeline itself. An export that also samples lights and
    cameras hands motion_sampler's visitor to sample_records instead, so the
    shot is walked once; the numbers are the same either way.
    """
    visit, finish = motion_sampler(settings, entries, visible_at)
    frames = frame_list(settings)
    if visit is None or not frames:
        return {}
    original = current_frame()
    try:
        for frame in frames:
            try:
                cmds.currentTime(frame, edit=True)
            except Exception:
                continue
            visit()
    finally:
        try:
            cmds.currentTime(original, edit=True)
        except Exception:
            pass
    return finish()


def motion_sampler(settings, entries, visible_at=None):
    """The mover sampler as a per-frame visitor, for a shared timeline walk.

    Returns ``(visit, finish)``: call ``visit()`` with the timeline parked on
    each frame in turn, then ``finish()`` for what sample_motion returns.
    ``(None, finish)`` when there is nothing to sample, and finish then
    returns ``{}``.

    Split from the walk so the movers can ride the same pass as the lights
    and cameras. Measured on a shot of 12 028 meshes and a Bullet solver,
    a frame step is 0.4 s whatever is read at it, and the shot was being
    walked twice.
    """
    frames = frame_list(settings)
    pairs = [(key, path) for key, path in (entries or []) if key and path]
    if not frames or not pairs:
        return None, (lambda: {})

    tracks = {}
    for key, _path in pairs:
        tracks[key] = {
            "matrix": array.array("f"),
            "visible": array.array("b"),
        }

    readers = _api_readers(pairs, read_visibility=visible_at is not None)

    def visit():
        for key, path in pairs:
            track = tracks[key]
            reader = readers.get(key) if readers else None
            if reader is not None:
                _api_sample(reader, track)
                continue
            try:
                matrix = cmds.xform(path, query=True, worldSpace=True,
                                    matrix=True)
            except Exception:
                matrix = None
            if not matrix or len(matrix) < 16:
                continue
            for index, value in enumerate(matrix):
                if index % 4 != 3:
                    track["matrix"].append(value)
            visible = True
            if visible_at is not None:
                try:
                    visible = bool(visible_at(path))
                except Exception:
                    visible = True
            track["visible"].append(1 if visible else 0)

    def finish():
        objects = {}
        for key, track in tracks.items():
            if len(track["matrix"]) < 24:
                continue
            written = {"matrix": track["matrix"]}
            # A run that never changes is not animation, and a visibility
            # channel of 520 identical ones is the common case.
            if not _channel_constant(track["visible"], 1):
                written["visible"] = track["visible"]
            objects[key] = written
        if not objects:
            return {}
        return {"frames": frames, "objects": objects}

    return visit, finish


def anchor_motion(motion, paths, warnings):
    """Move to the first sampled frame and record the pose found there.

    Called immediately before the FBX is written, and it leaves the timeline
    where it put it, because that is the pose the FBX must carry: the
    receivers apply every sample as a delta from this reference, and they see
    the FBX's first frame. The caller restores the user's frame afterwards.

    The reference is stored per object rather than as a frame number alone,
    so a receiver never has to find it among the samples or trust that the
    frame it was told about was sampled at all.
    """
    objects = (motion or {}).get("objects") or {}
    frames = (motion or {}).get("frames") or []
    if not objects or not frames:
        return motion
    try:
        cmds.currentTime(frames[0], edit=True)
    except Exception:
        warnings.append(
            "The timeline could not be moved to frame {0:g}, so sampled "
            "motion may start from the wrong pose.".format(frames[0])
        )
    lost = 0
    for key in list(objects):
        path = paths.get(key) if hasattr(paths, "get") else key
        try:
            matrix = cmds.xform(path, query=True, worldSpace=True, matrix=True)
        except Exception:
            matrix = None
        if not matrix or len(matrix) < 16:
            del objects[key]
            lost += 1
            continue
        reference = array.array("f")
        for index, value in enumerate(matrix):
            if index % 4 != 3:
                reference.append(value)
        objects[key]["reference"] = reference
    if lost:
        warnings.append(
            "{0} moving object(s) could not be read at the reference frame, "
            "so they arrive still.".format(lost)
        )
    if not objects:
        return {}
    motion["reference_frame"] = frames[0]
    return motion


def report_unstable_motion(motion, warnings, metres_per_unit=0.01):
    """Name objects whose samples reverse direction on consecutive frames.

    A rigid body cannot turn round twice in two frames without being hit
    twice, so a run of hard reversals is a solver that has stopped converging
    rather than a piece of debris. It reaches the receivers as an object that
    vibrates across the shot, and until now nothing said so on either side:
    the transfer is faithful, the numbers match, and the result is wrong.

    Measured on a real shot before this was written: 178 of 7468 movers
    reversed every frame with an amplitude of about 1.1 metres, and every
    piece under one tower carried the *same* per-frame delta to 0.0000 -- so
    the instability was in a group transform, not in the pieces. That is why
    the warning names the ancestor: it is the node somebody has to look at.

    The floor is a real length rather than a factor of the object's own
    motion, because an object that oscillates has no calm motion to compare
    against -- its median step is the oscillation.
    """
    objects = (motion or {}).get("objects") or {}
    frames = (motion or {}).get("frames") or []
    count = len(frames)
    if not objects or count < UNSTABLE_RUN + 2:
        return 0
    floor = UNSTABLE_STEP_METRES / max(float(metres_per_unit), 1e-9)
    culprits = {}
    total = 0
    for path in objects:
        matrix = (objects[path] or {}).get("matrix") or []
        if len(matrix) < count * 12:
            continue
        onset = _reversal_onset(matrix, count, floor)
        if onset is None:
            continue
        total += 1
        parts = [part for part in str(path).split("|") if part]
        group = parts[1] if len(parts) > 1 else (parts[0] if parts else path)
        held = culprits.setdefault(group, [0, onset])
        held[0] += 1
        if frames[onset] < held[1]:
            held[1] = frames[onset]
    if not total:
        return 0
    named = sorted(culprits.items(), key=lambda item: -item[1][0])[:4]
    warnings.append(
        "{0} moving object(s) reverse direction on consecutive frames, which "
        "is a simulation that stopped converging rather than motion: they "
        "will vibrate wherever this package is opened. Worst: {1}. Re-solve "
        "or re-cache those before sending.".format(
            total,
            ", ".join(
                "{0} ({1} object(s), from frame {2:g})".format(
                    name, held[0], held[1])
                for name, held in named
            ),
        )
    )
    return total


def _reversal_onset(matrix, count, floor):
    """The first sample of a run of hard reversals, or None.

    Positions are the fourth column of each twelve float row, which is where
    sample_motion writes them.
    """
    run = 0
    previous = None
    for frame in range(1, count):
        base = frame * 12 + 9
        before = (frame - 1) * 12 + 9
        step = [matrix[base + axis] - matrix[before + axis] for axis in range(3)]
        length = math.sqrt(sum(value * value for value in step))
        if previous is None or length < floor or previous[1] < floor:
            run = 0
            previous = (step, length)
            continue
        dot = sum(step[axis] * previous[0][axis] for axis in range(3))
        if dot / (length * previous[1]) < UNSTABLE_REVERSAL_COS:
            run += 1
            if run >= UNSTABLE_RUN:
                return max(frame - run, 0)
        else:
            run = 0
        previous = (step, length)
    return None


def _channel_constant(values, width):
    """Whether every sample in a flat channel equals the first one."""
    for index in range(width, len(values)):
        if values[index] != values[index % width]:
            return False
    return True


def is_animated(node):
    """Whether anything upstream of a node is driven by an animation curve."""
    if not node:
        return False
    try:
        return bool(cmds.listConnections(node, type="animCurve") or [])
    except Exception:
        return False


def frozen_animation_kinds(camera_shapes, light_shapes, mesh_records):
    """What a single frame export is leaving behind, kind by kind.

    Keyed material channels already had a line of their own. Everything else
    did not: a scene whose camera flies, whose lights fade and whose props
    blink exported as one still frame and said nothing at all, so the receiver
    built no sequence and nobody could tell whether that was the tool or the
    checkbox.

    Returns a list of readable phrases, or an empty list when the scene really
    is still.
    """
    found = []

    def _moves(shape):
        parent = parent_of(shape)
        return is_animated(shape) or (bool(parent) and is_animated(parent))

    cameras = [
        node_label(parent_of(shape) or shape)
        for shape in (camera_shapes or []) if _moves(shape)
    ]
    if cameras:
        found.append("{0} camera(s) ({1})".format(
            len(cameras), ", ".join(sorted(cameras)[:4])))

    lights = [
        node_label(parent_of(shape) or shape)
        for shape in (light_shapes or []) if _moves(shape)
    ]
    if lights:
        found.append("{0} light(s) ({1})".format(
            len(lights), ", ".join(sorted(lights)[:4])))

    blinking = []
    moving = []
    for record in (mesh_records or []):
        path = record.get("mesh_path") or ""
        if not path:
            continue
        label = record.get("mesh") or path
        if plug_animated(path + ".visibility"):
            blinking.append(label)
        elif is_animated(path):
            moving.append(label)
    if blinking:
        found.append("{0} object(s) whose visibility is keyed ({1})".format(
            len(blinking), ", ".join(sorted(blinking)[:4])))
    if moving:
        found.append("{0} moving object(s) ({1})".format(
            len(moving), ", ".join(sorted(moving)[:4])))
    return found


def _number(value, default):
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _curve_on(plug):
    try:
        return bool(cmds.listConnections(
            plug, source=True, destination=False, type="animCurve"
        ) or [])
    except Exception:
        return False


def plug_animated(plug):
    """Whether this plug, or any of its children, is driven by a curve.

    Per plug rather than per node: a shader with one keyed attribute would
    otherwise drag every other channel into the sampling, and stepping the
    timeline is the expensive part of an export.

    **The children matter.** A colour is a compound and Maya keys its children,
    so the curves hang off baseColorR and baseColorB while the compound itself
    reports no connection at all. Asking only the compound found a keyed
    roughness and missed a keyed base colour entirely -- measured, and exactly
    the sort of half-working that looks like it works.
    """
    if not plug:
        return False
    if _curve_on(plug):
        return True
    if "." not in plug:
        return False
    node, attribute = plug.split(".", 1)
    try:
        children = cmds.attributeQuery(
            attribute, node=node, listChildren=True
        ) or []
    except Exception:
        return False
    for child in children:
        if _curve_on("{0}.{1}".format(node, child)):
            return True
    return False


def _plug_sampler(plug):
    def sample():
        return {"value": plug_value(plug)}

    return sample


def material_animation_entries(mesh_records):
    """(channel record, sampler) pairs for every animated material channel.

    Only the channels that are actually keyed, on the same reasoning as
    visibility: reading every channel of every material at every frame is a
    getAttr storm for something almost nothing in a scene does.

    One entry per channel record **object**. A shader shared by forty meshes is
    one record in memory, and adding it once per mesh would append the same
    frames forty times over -- the record would look animated at forty times
    the frame rate.
    """
    entries = []
    seen = set()
    for mesh in mesh_records or []:
        for material in mesh.get("materials") or []:
            channels = (material or {}).get("channels") or {}
            for _name, channel in sorted(channels.items()):
                if not isinstance(channel, dict) or id(channel) in seen:
                    continue
                plug = channel.get("maya_plug")
                if not plug or not plug_animated(plug):
                    continue
                seen.add(id(channel))
                entries.append((channel, _plug_sampler(plug)))
    return entries


def animated_material_channels(mesh_records):
    """Names of the keyed channels, for the warning when animation is off."""
    found = []
    seen = set()
    for mesh in mesh_records or []:
        for material in mesh.get("materials") or []:
            name = material.get("material") or "?"
            for channel_name, channel in sorted(
                ((material or {}).get("channels") or {}).items()
            ):
                if not isinstance(channel, dict):
                    continue
                key = (name, channel_name)
                if key in seen:
                    continue
                plug = channel.get("maya_plug")
                if plug and plug_animated(plug):
                    seen.add(key)
                    found.append("{0}.{1}".format(name, channel_name))
    return found
