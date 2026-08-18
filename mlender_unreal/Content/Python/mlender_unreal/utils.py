# -*- coding: utf-8 -*-
"""Value and path helpers. Nothing here touches the unreal module.

Kept import-free of unreal on purpose: these are the functions the contract
checks exercise, and a helper that needs a live editor cannot be checked
without one.
"""

import os
import re


def scalar(value, default=0.0):
    """A float from whatever the JSON carried, or the default."""
    try:
        if value is None:
            return float(default)
        if isinstance(value, bool):
            return 1.0 if value else 0.0
        if isinstance(value, (list, tuple)):
            if not value:
                return float(default)
            return scalar(value[0], default)
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def colour(value, default=(0.0, 0.0, 0.0)):
    """Three floats from a JSON colour, padded and never clipped.

    Not clamped to 0..1 on purpose: emission and light colours legitimately
    exceed 1, and clipping them silently darkens albedos and tints.
    """
    values = list(value or ())
    if not isinstance(value, (list, tuple)):
        values = [scalar(value, default[0])] * 3
    out = [scalar(item, 0.0) for item in values[:3]]
    while len(out) < 3:
        out.append(scalar(default[len(out)], 0.0))
    return tuple(out)


def normalize_folder(path):
    """A package folder as an absolute path with native separators."""
    text = str(path or "").strip().strip('"')
    if not text:
        return ""
    return os.path.normpath(os.path.abspath(text))


def safe_asset_name(name, fallback="Unnamed"):
    """An Unreal object name from a Maya node name.

    Unreal rejects most punctuation in an asset name. A namespace colon is
    replaced rather than kept -- the opposite of the Blender side, where object
    names carry colons happily and stripping them broke referenced rigs. Here
    the colon cannot survive, so it becomes an underscore and the full Maya
    name is stored on the asset for reference instead.
    """
    text = str(name or "").strip()
    if not text:
        return fallback
    text = text.replace("|", "_").replace(":", "_")
    text = re.sub(r"[^A-Za-z0-9_]", "_", text)
    text = re.sub(r"_+", "_", text).strip("_")
    if not text:
        return fallback
    # An asset name may not begin with a digit.
    if text[0].isdigit():
        text = "_" + text
    return text


def package_relative_candidates(path, package_folder):
    """Where a recorded file might be if the package has moved.

    Same three places the Blender receiver looks, and for the same reason: a
    collected package records absolute paths written by the exporting machine,
    so a package opened anywhere else resolves none of them.
    """
    if not path or not package_folder:
        return []
    name = os.path.basename(str(path).replace("\\", "/"))
    if not name:
        return []
    return [
        os.path.join(package_folder, name),
        os.path.join(package_folder, "textures_collected", name),
        os.path.join(package_folder, "files_collected", name),
        os.path.join(package_folder, "textures", name),
    ]


def resolve_recorded_path(path, package_folder):
    """Return (resolved_path, repointed).

    A path that still resolves is returned untouched -- the common case is one
    machine running both applications, and rewriting there would change
    something for nothing.
    """
    text = str(path or "").strip()
    if not text:
        return "", False
    if os.path.isfile(text):
        return text, False
    for candidate in package_relative_candidates(text, package_folder):
        if os.path.isfile(candidate):
            return candidate, True
    return text, False


def channel_texture_path(record):
    """The file behind a channel record, or "".

    A record can carry a value and a texture at once: first_channel_record
    fills value even when a connection exists. Reading value alone and calling
    it a flat colour is on the project's forbidden list, so the texture is
    identified by its path and nothing else.
    """
    texture = (record or {}).get("texture") or {}
    return str(texture.get("path") or "").strip()


def is_colour_data(channel, record, colour_channels):
    """Whether a texture for this channel should be read as sRGB.

    Baked maps are the exception and they are not a small one: Maya's
    convertSolidTx writes linear values whatever the colour management says, so
    a baked base colour read as sRGB arrives visibly darkened.
    """
    if (record or {}).get("baked_from"):
        return False
    return channel in colour_channels
