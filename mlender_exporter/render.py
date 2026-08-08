# -*- coding: utf-8 -*-
"""Render resolution and motion blur.

Small, but it is most of what makes an imported scene feel ready rather than
merely present: a shot framed for 1920x804 arriving into Blender's 1920x1080
is reframed, and every camera assertion about aperture fit then looks wrong
for a reason that has nothing to do with the camera.

The frame range deliberately does not travel here. It already rides the
``animation`` record, and writing it twice would give the importer two sources
that can disagree.

Motion blur is read from Arnold only. Redshift's own attribute names cannot be
probed on this machine because the plugin is not installed, and this project
does not write attribute names it has not read off a live session -- the same
footing as the Redshift light anchor.
"""
from __future__ import absolute_import

import maya.cmds as cmds

from .constants import (
    ARNOLD_MOTION_BLUR_NODE,
    ARNOLD_MOTION_BLUR_ENABLED_ATTRS,
    ARNOLD_MOTION_BLUR_LENGTH_ATTRS,
)
from .mayautils import attr_exists, first_existing_attr


def render_record():
    """Resolution and motion blur, or an empty dict if nothing is readable."""
    record = {}
    resolution = _resolution()
    if resolution:
        record.update(resolution)
    motion_blur = _motion_blur()
    if motion_blur:
        record["motion_blur"] = motion_blur
    return record


def _resolution():
    if not cmds.objExists("defaultResolution"):
        return {}
    width = _number("defaultResolution.width")
    height = _number("defaultResolution.height")
    if not width or not height:
        return {}
    return {
        "width": int(width),
        "height": int(height),
        # Maya states the pixel aspect separately from the device aspect, and
        # it is the pixel one Blender wants.
        "pixel_aspect": _number("defaultResolution.pixelAspect") or 1.0,
        "device_aspect": _number("defaultResolution.deviceAspectRatio") or 0.0,
    }


def _motion_blur():
    node = ARNOLD_MOTION_BLUR_NODE
    if not cmds.objExists(node):
        return {}
    enabled, enabled_attr, _ = first_existing_attr(
        node, ARNOLD_MOTION_BLUR_ENABLED_ATTRS
    )
    if not enabled_attr:
        return {}
    length, length_attr, _ = first_existing_attr(
        node, ARNOLD_MOTION_BLUR_LENGTH_ATTRS
    )
    record = {
        "enabled": bool(enabled),
        "source": node,
        "enabled_attr": enabled_attr,
    }
    if length_attr:
        # Arnold states the shutter as a length in frames, which is exactly
        # what Blender's motion_blur_shutter means.
        try:
            record["shutter_frames"] = float(length)
        except (TypeError, ValueError):
            pass
        record["length_attr"] = length_attr
    return record


def _number(plug):
    value = _raw(plug)
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _raw(plug):
    node = plug.split(".")[0]
    attr = plug.split(".", 1)[1]
    if not cmds.objExists(node) or not attr_exists(node, attr):
        return None
    try:
        return cmds.getAttr(plug)
    except Exception:
        return None
