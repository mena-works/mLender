# -*- coding: utf-8 -*-
"""Every knob the receiver has, in one place, readable and persistent.

Before this, four values lived in a module-level dict inside livelink and two
of them could only be changed by typing into the Python console. A setting
nobody can see the value of is a setting nobody trusts, and one that resets
every time the editor restarts is one nobody uses twice.

The dict is the truth. When the compiled module is present its ``MLSettings``
object mirrors the same values so a details panel can edit them, but the
reading direction is always **pull**: ``values()`` asks the object and falls back
to the dict. Pushing instead would need a change notification from C++ and
would leave two writers on one value -- the same shape of bug that made a
level's movers fight their own animation.

The plugin has to work with no compiled module at all, so every ``unreal``
symbol here is fetched through ``getattr`` and every failure falls back rather
than raising. That is the rule ``MLMotionPlayer`` already follows.
"""

import json
import os

import unreal

from .constants import (
    FILTER_KINDS,
    LIVELINK_HOST,
    LIVELINK_PORT,
    SETTINGS_FILE_NAME,
)


# key, default, label. The label is what the menu writes before the value,
# so it reads as a sentence rather than as a variable name.
SETTING_SPECS = (
    ("import_scale", 1.0, "Import Scale"),
    ("power_scale", 1.0, "Light Power Scale"),
    ("keep_existing_lights", False, "Keep Existing Lighting"),
    ("import_lights", True, "Build The Package's Lights"),
    ("import_cameras", True, "Build Cameras"),
    ("import_animation", True, "Build Animation"),
    ("import_sets", True, "Build Sets And Layers"),
    ("update_materials", True, "Update Materials"),
    ("active_camera", "", "Active Camera"),
    ("reveal_hidden_layer", False, "Show Hidden Objects"),
    ("filter_kind", "none", "Filter By"),
    ("filter_names", [], "Filter Names"),
    ("filter_invert", False, "Invert The Filter"),
    ("last_package_folder", "", "Last Package"),
    ("open_report_when_done", False, "Open The Report After An Import"),
    ("toolbar_visible", True, "Show The Toolbar"),
    ("toolbar_x", -1.0, "Toolbar X"),
    ("toolbar_y", -1.0, "Toolbar Y"),
    ("livelink_host", LIVELINK_HOST, "LiveLink Host"),
    ("livelink_port", LIVELINK_PORT, "LiveLink Port"),
)

SETTING_DEFAULTS = dict((key, default) for key, default, _label in SETTING_SPECS)
SETTING_LABELS = dict((key, label) for key, _default, label in SETTING_SPECS)
SETTING_ORDER = tuple(key for key, _default, _label in SETTING_SPECS)

# The class the compiled module declares. Absent is a valid installation.
SETTINGS_CLASS_NAME = "MLSettings"

_values = dict(SETTING_DEFAULTS)


def _coerce(key, value):
    """A value from JSON or from a panel, shaped like the default.

    A settings file is a text file a person can edit, so it can hand back a
    string where a float belongs. Coercing here means the rest of the package
    never has to ask what it is holding.
    """
    default = SETTING_DEFAULTS.get(key)
    if isinstance(default, bool):
        if isinstance(value, str):
            return value.strip().lower() in ("1", "true", "yes", "on")
        return bool(value)
    if isinstance(default, float):
        try:
            return float(value)
        except (TypeError, ValueError):
            return default
    if isinstance(default, int):
        try:
            return int(value)
        except (TypeError, ValueError):
            return default
    if isinstance(default, list):
        if isinstance(value, str):
            value = [part for part in value.split(",")]
        try:
            return [str(item).strip() for item in value if str(item).strip()]
        except TypeError:
            return list(default)
    # A panel's folder picker hands back an FDirectoryPath, not a string.
    inner = getattr(value, "path", None)
    if inner is not None and not isinstance(value, str):
        value = inner
    text = "" if value is None else str(value)
    if key == "filter_kind" and text not in FILTER_KINDS:
        return default
    return text


def settings_object():
    """The compiled module's settings object, or None.

    Probed rather than imported: a build with no C++ module is a build that
    still has to run.
    """
    klass = getattr(unreal, SETTINGS_CLASS_NAME, None)
    if klass is None:
        return None
    try:
        return unreal.get_default_object(klass)
    except Exception:
        return None


def values():
    """Every setting, preferring the panel's object when one exists."""
    current = dict(_values)
    obj = settings_object()
    if obj is None:
        return current
    for key in SETTING_ORDER:
        try:
            current[key] = _coerce(key, obj.get_editor_property(key))
        except Exception:
            # A property the compiled module does not carry -- an older
            # binary against newer Python. The dict still answers.
            pass
    return current


def get(key, fallback=None):
    return values().get(key, fallback)


def update(**kwargs):
    """Write settings, mirror them to the panel object, and persist."""
    unknown = [key for key in kwargs if key not in SETTING_DEFAULTS]
    if unknown:
        unreal.log_warning(
            "mLender: ignoring unknown setting(s) {0}".format(
                ", ".join(sorted(unknown))
            )
        )
    for key, value in kwargs.items():
        if key not in SETTING_DEFAULTS or value is None:
            # None means "not said", never "back to the default" -- the same
            # rule the exporter's presets follow.
            continue
        _values[key] = _coerce(key, value)
    _mirror()
    save()
    return dict(_values)


def reset():
    _values.clear()
    _values.update(SETTING_DEFAULTS)
    _mirror()
    save()
    return dict(_values)


def toggle(key):
    """Flip a boolean and return what it became."""
    if not isinstance(SETTING_DEFAULTS.get(key), bool):
        raise ValueError("{0} is not a switch".format(key))
    state = not values().get(key)
    update(**{key: state})
    return state


def _mirror():
    obj = settings_object()
    if obj is None:
        return
    for key, value in _values.items():
        try:
            obj.set_editor_property(key, _for_object(key, value))
        except Exception:
            pass


def _for_object(key, value):
    """A value shaped the way the panel's property expects it.

    The package folder is an FDirectoryPath so the panel gets a browse
    button, and a struct property refuses a plain string without saying why.
    """
    if key != "last_package_folder":
        return value
    wrapper = getattr(unreal, "DirectoryPath", None)
    if wrapper is None:
        return value
    try:
        return wrapper(path=value)
    except Exception:
        return value


def set_summary(text):
    """What the last import did, for the panel to draw.

    Deliberately not one of the stored settings: a summary read back from a
    previous session describes a level that may no longer be open.
    """
    obj = settings_object()
    if obj is None:
        return ""
    try:
        obj.set_editor_property("last_summary", str(text or ""))
    except Exception as exc:
        # Not swallowed: a VisibleAnywhere property is read-only to Python and
        # throws, and the first version of this caught that and drew a panel
        # that said nothing had been imported.
        unreal.log_warning(
            "mLender: the panel's summary could not be written: {0}".format(exc)
        )
        return ""
    return str(text or "")


def render(key, value):
    """One setting as the text a menu entry or a status line shows."""
    default = SETTING_DEFAULTS.get(key)
    if isinstance(default, bool):
        return "ON" if value else "OFF"
    if isinstance(default, list):
        return ", ".join(value) if value else "any"
    if isinstance(default, float):
        return "{0:g}".format(value)
    text = str(value)
    if not text:
        return "any" if key == "active_camera" else "none"
    return text


def label_for(key):
    """"Build The Package's Lights: ON" -- the state is in the label.

    MultiBlockType on 5.8.1 has no TOGGLE_BUTTON and ToolMenuEntry cannot draw
    a tick, so this is the only way a menu can say what it is set to.
    """
    return "{0}: {1}".format(
        SETTING_LABELS.get(key, key), render(key, values().get(key))
    )


def describe():
    return [label_for(key) for key in SETTING_ORDER]


def saved_file_path(name):
    """A file of ours under <project>/Saved/mLender, or "" with no project."""
    paths = getattr(unreal, "Paths", None)
    if paths is None:
        return ""
    try:
        saved = str(paths.project_saved_dir())
    except Exception:
        return ""
    if not saved:
        return ""
    return os.path.join(os.path.abspath(saved), "mLender", name)


def settings_path():
    return saved_file_path(SETTINGS_FILE_NAME)


def save():
    path = settings_path()
    if not path:
        return ""
    try:
        folder = os.path.dirname(path)
        if not os.path.isdir(folder):
            os.makedirs(folder)
        with open(path, "w") as handle:
            json.dump(_values, handle, indent=2, sort_keys=True)
    except Exception as exc:
        # Settings that cannot be written are an inconvenience; an import that
        # stops because of it is not. The same rule the export report follows.
        unreal.log_warning(
            "mLender: could not write {0}: {1}".format(path, exc)
        )
        return ""
    return path


def load():
    """Read the stored settings. A missing or broken file is the defaults."""
    path = settings_path()
    if not path or not os.path.isfile(path):
        return dict(_values)
    try:
        with open(path, "r") as handle:
            stored = json.load(handle)
    except Exception as exc:
        unreal.log_warning(
            "mLender: {0} could not be read ({1}); using the defaults."
            .format(path, exc)
        )
        return dict(_values)
    if not isinstance(stored, dict):
        return dict(_values)
    for key, value in stored.items():
        if key in SETTING_DEFAULTS:
            _values[key] = _coerce(key, value)
    _mirror()
    return dict(_values)


def import_kwargs():
    """The subset import_scene_package takes, by the names it takes them by."""
    current = values()
    return {
        "import_scale": current["import_scale"],
        "power_scale": current["power_scale"],
        "keep_existing_lights": current["keep_existing_lights"],
        "import_lights": current["import_lights"],
        "import_cameras": current["import_cameras"],
        "import_animation": current["import_animation"],
        "import_sets": current["import_sets"],
        "update_materials": current["update_materials"],
        "active_camera": current["active_camera"],
        "reveal_hidden_layer": current["reveal_hidden_layer"],
        "filter_kind": current["filter_kind"],
        "filter_names": list(current["filter_names"]),
        "filter_invert": current["filter_invert"],
    }
