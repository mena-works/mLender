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
from .mayautils import current_frame


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
