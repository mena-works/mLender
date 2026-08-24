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


def decoded_name(value):
    """A Maya name with FBX character escapes turned back into characters.

    A name that once travelled through an FBX comes back with every character
    the format dislikes spelled as ``FBXASC`` and three decimal digits --
    ``FBXASC046`` for a dot. Maya keeps that spelling as the node name, so the
    package carries it too, while the receiver is handed the decoded one.

    Measured on a shot: 232 of 7106 objects matched nothing for this reason,
    arriving with placeholder materials and no motion, and decoding matched
    every one of them.
    """
    text = str(value or "")
    if "FBXASC" not in text:
        return text
    out = []
    index = 0
    while index < len(text):
        if text[index:index + 6] == "FBXASC" and text[index + 6:index + 9].isdigit():
            code = int(text[index + 6:index + 9])
            if 0 < code < 128:
                out.append(chr(code))
                index += 9
                continue
        out.append(text[index])
        index += 1
    return "".join(out)


def fbx_style_name(value):
    """The spelling an actor arrives under, from the name Maya stored.

    An FBX writes a character it dislikes as an escape, Maya keeps that as the
    node name, and the importer turns it back into a plain separator. So a
    Maya node called "polySurface123.007" is stored as
    "polySurface123FBXASC046007" and arrives as "polySurface123_007".

    Repeated underscores are **kept**, which is the whole point and the
    difference from safe_asset_name. Measured on a real shot: the scene holds
    both "broken__polySurface123.007_u11" and
    "broken_polySurface123.007_u11_r08" -- two objects, two shapes -- and
    collapsing the doubled underscore files them under one name, after which
    one is drawn with the other's mesh forty centimetres away.
    """
    text = decoded_name(str(value or ""))
    return re.sub(r"[^A-Za-z0-9_]", "_", text)


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


def sequence_label(package_data):
    """What to name this package's Level Sequence after.

    The Maya scene, not the package name. Every export writes into a fresh
    folder and is therefore called ``mLender_01``, so naming the sequence after
    the package gave two different shots one asset: sending a second shot into
    the same project overwrote the first shot's sequence, and its level was
    left with a timeline bound to nothing.

    The Maya scene is what actually distinguishes them, and it is already in
    the payload. Falls back to the package name, then to a constant, because a
    sequence under an odd name beats no sequence at all.
    """
    data = package_data or {}
    scene = str(data.get("maya_scene") or "").replace("\\", "/")
    stem = os.path.splitext(os.path.basename(scene))[0]
    for candidate in (stem, data.get("package_name"), "Scene"):
        name = safe_asset_name(candidate or "", "")
        if name:
            return name
    return "Scene"


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


def remap_curve_samples(parameters, count=256):
    """A remapValue evaluated into a row of samples, ranges and all.

    Lives here rather than beside the material builder so the contract
    test can check the curve without an engine: this is arithmetic, and
    the knee in a ramp is exactly the kind of thing worth pinning.

    The node maps its input range onto the ramp and the ramp onto its output
    range; all three are folded here so the material needs one texture sample
    and no arithmetic around it. Stops are read in position order because Maya
    stores them in the order they were created.
    """
    stops = []
    for stop in parameters.get("ramp") or []:
        position = scalar((stop or {}).get("position"), None)
        value = scalar((stop or {}).get("value"), None)
        if position is None or value is None:
            continue
        stops.append((position, value))
    if len(stops) < 2:
        return None
    stops.sort()

    low = scalar(parameters.get("input_min"), 0.0)
    high = scalar(parameters.get("input_max"), 1.0)
    out_low = scalar(parameters.get("output_min"), 0.0)
    out_high = scalar(parameters.get("output_max"), 1.0)
    span = (high - low) or 1.0

    values = []
    for index in range(count):
        u = index / float(count - 1)
        t = (u - low) / span
        t = 0.0 if t < 0.0 else (1.0 if t > 1.0 else t)
        if t <= stops[0][0]:
            value = stops[0][1]
        elif t >= stops[-1][0]:
            value = stops[-1][1]
        else:
            value = stops[-1][1]
            for (p0, v0), (p1, v1) in zip(stops, stops[1:]):
                if p0 <= t <= p1:
                    width = (p1 - p0) or 1.0
                    value = v0 + (v1 - v0) * ((t - p0) / width)
                    break
        values.append(out_low + (out_high - out_low) * value)
    return values
