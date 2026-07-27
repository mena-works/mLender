# -*- coding: utf-8 -*-
"""Texture loading from the original Maya paths.

Textures are never copied into the package; the image node opens the same file
Maya referenced. A missing texture is reported as a warning and the material
falls back to its flat value rather than aborting the import.
"""

import glob
import os
import re

import bpy

from .constants import (
    COLOR_CHANNELS,
    UDIM_FIRST_TILE,
    UDIM_TOKEN,
    UDIM_TOKEN_PATTERN,
)


def load_image(texture_record, channel, warnings):
    """Load a texture and set its colour space from the channel's role."""
    path = (
        texture_record.get("udim_pattern")
        or texture_record.get("path")
        or ""
    )
    path = os.path.abspath(os.path.expandvars(os.path.expanduser(path)))
    path, has_udim_token = normalize_udim_token(path)
    # The exporter flagged a tiled texture but shipped a concrete tile, which
    # happens when Maya could not resolve a pattern of its own.
    if texture_record.get("udim") and not has_udim_token:
        path = replace_udim_tile_number(path)
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
                image["za_udim"] = True
                image["za_udim_pattern"] = path
                # Blender only scans for sibling tiles on reload.
                image.reload()
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

    Returns ``(resolved_path, is_tiled)``. The globs are digit classes rather
    than ``*`` so a token cannot swallow unrelated files that happen to share
    the prefix.
    """
    if os.path.isfile(path):
        return path, False
    path, has_udim_token = normalize_udim_token(path)
    tokenized = path.replace(UDIM_TOKEN, "[1-9][0-9][0-9][0-9]")
    tokenized = tokenized.replace("####", "[0-9][0-9][0-9][0-9]")
    matches = sorted(glob.glob(tokenized))
    if not matches:
        return "", False
    return matches[0], has_udim_token


def normalize_udim_token(path):
    """Collapse the UDIM spellings different tools write into one token."""
    normalized = re.sub(UDIM_TOKEN_PATTERN, UDIM_TOKEN, str(path))
    return normalized, UDIM_TOKEN in normalized


def replace_udim_tile_number(path):
    """Swap a concrete tile number in the file name for the UDIM token.

    Only the last four digit run of 1001 or above is treated as a tile, so
    version numbers earlier in the name survive.
    """
    folder, filename = os.path.split(path)
    matches = [
        match
        for match in re.finditer(r"(?<!\d)([1-9]\d{3})(?!\d)", filename)
        if int(match.group(1)) >= UDIM_FIRST_TILE
    ]
    if not matches:
        return path
    match = matches[-1]
    filename = filename[: match.start()] + UDIM_TOKEN + filename[match.end():]
    return os.path.join(folder, filename)
