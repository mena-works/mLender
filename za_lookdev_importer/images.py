# -*- coding: utf-8 -*-
"""Texture loading from the original Maya paths.

Textures are never copied into the package; the image node opens the same file
Maya referenced. A missing texture is reported as a warning and the material
falls back to its flat value rather than aborting the import.
"""

import glob
import os

import bpy

from .constants import COLOR_CHANNELS


def load_image(texture_record, channel, warnings):
    """Load a texture and set its colour space from the channel's role."""
    path = texture_record.get("path") or ""
    path = os.path.abspath(os.path.expandvars(os.path.expanduser(path)))
    resolved_path, tiled = resolve_image_path(path)
    if not resolved_path:
        warnings.append("Texture not found for {0}: {1}".format(channel, path))
        return None

    try:
        image = bpy.data.images.load(resolved_path, check_existing=True)
        if tiled:
            try:
                image.source = "TILED"
                image.filepath = path
            except Exception:
                pass
        if _is_non_color(texture_record, channel):
            try:
                image.colorspace_settings.name = "Non-Color"
            except Exception:
                pass
        return image
    except Exception as exc:
        warnings.append(
            "Texture could not be loaded for {0}: {1} ({2})".format(
                channel,
                path,
                exc,
            )
        )
        return None


def _is_non_color(texture_record, channel):
    """Data channels are always Non-Color; colour channels follow Maya."""
    if channel not in COLOR_CHANNELS:
        return True
    maya_color_space = str(texture_record.get("color_space") or "").lower()
    return "raw" in maya_color_space or "non-color" in maya_color_space


def resolve_image_path(path):
    """Resolve a path that may carry UDIM or frame tokens.

    Returns ``(resolved_path, is_tiled)``. The tiled flag is only set for real
    UDIM tokens; ``####`` sequences resolve to their first match as a still.
    """
    if os.path.isfile(path):
        return path, False
    tokenized = (
        path.replace("<UDIM>", "*")
        .replace("<udim>", "*")
        .replace("####", "*")
    )
    matches = sorted(glob.glob(tokenized))
    if not matches:
        return "", False
    return matches[0], "<UDIM>" in path.upper()
