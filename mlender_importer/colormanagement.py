# -*- coding: utf-8 -*-
"""Match Blender's view transform to the one Maya was using.

This is the most common reason a correct transfer still "looks wrong": the
geometry, materials and lights all match, and the image does not, because the
two applications are tone mapping differently.

There is a hard limit here and the code is honest about it. Measured on 4.1,
4.5 and 5.2 by trying to set each name, Blender's stock OCIO config offers
Standard, Raw, Filmic, Filmic Log, False Color and AgX, plus Khronos PBR
Neutral from 4.5. It has no ACES view transform at all. A Maya scene on the
ACES config can therefore only be matched when the user has pointed Blender at
an ACES config through the OCIO environment variable.

So: try what Maya asked for, fall back to a rough equivalent, and when neither
works say so and name the config Maya used. Leaving AgX in place while
reporting success would be the one genuinely misleading outcome.
"""

import bpy

from .constants import (
    DEFAULT_VIEW_TRANSFORM,
    DISPLAY_DEVICE_FALLBACKS,
    VIEW_TRANSFORM_FALLBACKS,
)


def apply_color_management(package_data, warnings):
    """Set the scene's view transform and display from the package.

    Returns the view transform actually applied, or an empty string when the
    package carried no colour management block.
    """
    settings = package_data.get("color_management") or {}
    if not settings:
        return ""
    if not settings.get("enabled", True):
        # Maya had colour management off, so the scene is raw linear.
        applied = _try_view_transform(("Standard", "Raw"))
        return applied

    scene = bpy.context.scene
    _apply_display(scene, settings, warnings)

    wanted = str(settings.get("view_transform") or "")
    view_name = str(settings.get("view_name") or "")
    candidates = [name for name in (wanted, view_name) if name]
    candidates.extend(_fallbacks(wanted or view_name))
    candidates.append(DEFAULT_VIEW_TRANSFORM)

    applied = _try_view_transform(candidates)
    if not applied:
        warnings.append(
            'Could not set any view transform; Maya was using "{0}".'.format(
                wanted or view_name
            )
        )
        return ""

    if wanted and applied != wanted:
        warnings.append(
            'Maya was using the "{0}" view transform, which this Blender\'s '
            'colour config does not have; "{1}" was used instead. To match '
            "exactly, point Blender at the same OCIO config through the OCIO "
            "environment variable: {2}".format(
                wanted,
                applied,
                settings.get("config_path") or "(config path unknown)",
            )
        )
    return applied


def _apply_display(scene, settings, warnings):
    display = str(settings.get("display") or "")
    if not display:
        return
    candidates = [display]
    candidates.extend(DISPLAY_DEVICE_FALLBACKS.get(display.lower(), ()))
    for name in candidates:
        try:
            scene.display_settings.display_device = name
            return
        except Exception:
            continue
    warnings.append(
        'Display device "{0}" is not available in this Blender.'.format(display)
    )


def _fallbacks(name):
    """Rough equivalents, matched on the leading part of Maya's name.

    Maya spells its transforms "ACES 1.0 SDR-video (sRGB)" and
    "Un-tone-mapped (sRGB)", so the display suffix is ignored when matching.
    """
    lowered = str(name or "").lower()
    for key, values in VIEW_TRANSFORM_FALLBACKS.items():
        if lowered.startswith(key):
            return list(values)
    return []


def _try_view_transform(names):
    """Set the first view transform this build accepts.

    Blender rejects an unknown enum value by raising, and in background mode
    the enum cannot be introspected at all, so trying is the only way to know.
    """
    view = bpy.context.scene.view_settings
    for name in names:
        if not name:
            continue
        try:
            view.view_transform = name
        except Exception:
            continue
        if view.view_transform == name:
            return name
    return ""
