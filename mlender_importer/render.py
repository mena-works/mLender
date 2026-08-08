# -*- coding: utf-8 -*-
"""Render resolution and motion blur applied to the Blender scene.

The scene datablock survives the wipe, so its render settings are whatever the
last file left behind. Every value here is therefore set explicitly rather than
trusted: a resolution percentage left at 50 from an earlier session would
silently halve the render of a package that never mentioned it.
"""

import bpy

from .utils import scalar


def apply_render_settings(package_data, warnings):
    """Apply the package's render record. Returns what was applied."""
    record = package_data.get("render") or {}
    if not record:
        return {}

    render = bpy.context.scene.render
    applied = {}

    width = int(scalar(record.get("width"), 0))
    height = int(scalar(record.get("height"), 0))
    if width > 0 and height > 0:
        render.resolution_x = width
        render.resolution_y = height
        # Not carried by Maya, and a leftover value is a silent scale factor.
        render.resolution_percentage = 100
        applied["resolution"] = (width, height)

    pixel_aspect = scalar(record.get("pixel_aspect"), 0.0)
    if pixel_aspect > 0.0:
        # Maya states one number against a square pixel; Blender states a
        # ratio between two.
        render.pixel_aspect_x = pixel_aspect
        render.pixel_aspect_y = 1.0
        applied["pixel_aspect"] = pixel_aspect

    motion = record.get("motion_blur") or {}
    if motion:
        applied.update(_apply_motion_blur(render, motion, warnings))
    return applied


def _apply_motion_blur(render, motion, warnings):
    applied = {}
    if not hasattr(render, "use_motion_blur"):
        warnings.append(
            "This Blender has no motion blur setting, so the Maya one was "
            "not applied."
        )
        return applied

    enabled = bool(motion.get("enabled"))
    try:
        render.use_motion_blur = enabled
        applied["motion_blur"] = enabled
    except Exception as exc:
        warnings.append("Motion blur could not be set: {0}".format(exc))
        return applied

    shutter = scalar(motion.get("shutter_frames"), 0.0)
    # Arnold and Blender both state the shutter as a length in frames, so the
    # number carries across untouched.
    if shutter > 0.0 and hasattr(render, "motion_blur_shutter"):
        try:
            render.motion_blur_shutter = shutter
            applied["shutter"] = shutter
        except Exception as exc:
            warnings.append("Shutter could not be set: {0}".format(exc))
    return applied
