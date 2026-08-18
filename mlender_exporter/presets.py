# -*- coding: utf-8 -*-
"""Export settings, saved so they survive Maya and reach a batch run.

Two problems, one answer. The UI's options are re-set by hand every session,
and a batch export had no way to be told "the same settings the artist uses".
A preset is a small JSON file holding exactly the keyword arguments
``export_scene`` takes, so the UI and a farm job cannot drift into meaning
different things by the same words.

The settings live under the user's Maya preferences rather than in the scene:
they describe how somebody works, not what the scene is, and a scene opened by
somebody else should not carry the sender's habits.

Nothing here imports maya.cmds beyond locating that folder, so the merge and
validation are testable without a Maya.
"""
from __future__ import absolute_import

import json
import os


PRESET_FOLDER_NAME = "mLender"
PRESET_SUFFIX = ".json"
DEFAULT_PRESET_NAME = "default"

# Exactly the keyword arguments export_scene takes, plus where to send. Any
# key not in here is refused on load: a preset written by a newer build must
# not quietly hand an unknown argument to an older one.
DEFAULT_SETTINGS = {
    "selected_only": False,
    "bake_procedurals": True,
    "bake_resolution": 1024,
    "collect_textures_into_package": False,
    "archive_package": False,
    "export_animation": False,
    "frame_start": None,
    "frame_end": None,
    "frame_step": None,
    "export_alembic_cache": False,
    "cache_animated_meshes": False,
    "output_folder": "",
    "livelink_host": "",
    "livelink_port": 0,
}

# The subset export_scene itself accepts. The rest are the tool's own.
EXPORT_KEYS = (
    "selected_only",
    "bake_procedurals",
    "bake_resolution",
    "collect_textures_into_package",
    "archive_package",
    "export_animation",
    "frame_start",
    "frame_end",
    "frame_step",
    "export_alembic_cache",
    "cache_animated_meshes",
)


def preset_folder():
    """Where presets live, created on demand.

    Under the user's Maya preferences when Maya can say where that is, and
    beside the module otherwise, so a headless run with no prefs still works.
    """
    folder = ""
    try:
        import maya.cmds as cmds

        folder = str(cmds.internalVar(userPrefDir=True) or "")
    except Exception:
        folder = ""
    if not folder:
        folder = os.path.expanduser("~")
    return os.path.join(folder, PRESET_FOLDER_NAME)


def preset_path(name=DEFAULT_PRESET_NAME):
    safe = "".join(
        character for character in str(name or DEFAULT_PRESET_NAME)
        if character.isalnum() or character in ("_", "-")
    ) or DEFAULT_PRESET_NAME
    return os.path.join(preset_folder(), safe + PRESET_SUFFIX)


def normalize(settings):
    """Keep the known keys, coerce their types, drop the rest.

    Unknown keys are dropped rather than passed on: they would reach
    export_scene as keyword arguments and raise, turning a preset written by a
    newer build into a failed export rather than an ignored setting.
    """
    clean = dict(DEFAULT_SETTINGS)
    for key, default in DEFAULT_SETTINGS.items():
        if key not in (settings or {}):
            continue
        value = settings[key]
        if isinstance(default, bool):
            clean[key] = bool(value)
        elif key in ("bake_resolution", "livelink_port"):
            try:
                clean[key] = int(value)
            except (TypeError, ValueError):
                clean[key] = default
        elif key in ("frame_start", "frame_end", "frame_step"):
            if value is None or value == "":
                clean[key] = None
            else:
                try:
                    clean[key] = float(value)
                except (TypeError, ValueError):
                    clean[key] = None
        else:
            clean[key] = str(value or "")
    return clean


def export_kwargs(settings):
    """Only the arguments export_scene accepts."""
    clean = normalize(settings)
    return dict((key, clean[key]) for key in EXPORT_KEYS)


def merge(*layers):
    """Later layers win, and None never overrides a real value.

    A command line that names only the output folder should keep the preset's
    other settings rather than resetting them to the defaults.
    """
    merged = dict(DEFAULT_SETTINGS)
    for layer in layers:
        for key, value in (layer or {}).items():
            if key not in DEFAULT_SETTINGS:
                continue
            if value is None and DEFAULT_SETTINGS[key] is not None:
                continue
            merged[key] = value
    return normalize(merged)


def save_preset(settings, name=DEFAULT_PRESET_NAME):
    """Write a preset. Returns the path, or "" if it could not be written."""
    path = preset_path(name)
    try:
        folder = os.path.dirname(path)
        if not os.path.isdir(folder):
            os.makedirs(folder)
        with open(path, "w") as handle:
            json.dump(normalize(settings), handle, indent=2, sort_keys=True)
    except Exception:
        return ""
    return path


def load_preset(name=DEFAULT_PRESET_NAME):
    """Read a preset, or the defaults if there is not one.

    A corrupt preset is the defaults too, not an exception: a file somebody
    hand edited must not stop them exporting.
    """
    path = preset_path(name)
    if not os.path.isfile(path):
        return dict(DEFAULT_SETTINGS)
    try:
        with open(path, "r") as handle:
            return normalize(json.load(handle))
    except Exception:
        return dict(DEFAULT_SETTINGS)


def list_presets():
    folder = preset_folder()
    if not os.path.isdir(folder):
        return []
    names = []
    for entry in sorted(os.listdir(folder)):
        if entry.endswith(PRESET_SUFFIX):
            names.append(entry[:-len(PRESET_SUFFIX)])
    return names
