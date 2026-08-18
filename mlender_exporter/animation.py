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

import math

import maya.cmds as cmds
import maya.mel as mel

from .constants import DEFAULT_FPS, MAX_ANIMATION_FRAMES, TIME_UNIT_FPS
from .mayautils import current_frame, plug_value


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


def sample_records(settings, entries):
    """Attach a ``samples`` list to each record by stepping the timeline.

    ``entries`` is a sequence of ``(record, sampler)`` pairs, where sampler is
    called with no arguments at each frame and returns a plain dict. Keeping
    the samplers opaque is what lets this module stay independent of lights
    and cameras.

    The current frame is always restored, including when a sampler raises;
    leaving the user's scene parked on a different frame would be a visible
    side effect of exporting.
    """
    frames = frame_list(settings)
    if not frames or not entries:
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
    finally:
        try:
            cmds.currentTime(original, edit=True)
        except Exception:
            pass
    return len(frames)


def is_animated(node):
    """Whether anything upstream of a node is driven by an animation curve."""
    if not node:
        return False
    try:
        return bool(cmds.listConnections(node, type="animCurve") or [])
    except Exception:
        return False


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
