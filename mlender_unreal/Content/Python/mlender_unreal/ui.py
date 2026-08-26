# -*- coding: utf-8 -*-
"""Editor menu entries, carrying their own state.

Unreal has no sidebar panel a Python plugin can add cheaply, so the controls
live in a Tools menu section. The menu class names were probed on 5.8.1 rather
than assumed -- a wrong menu name registers nothing and reports no error, which
is the same failure mode as a panel whose buttons do nothing.

``MultiBlockType`` on this build has no ``TOGGLE_BUTTON`` and ``ToolMenuEntry``
exposes only label, icon, tooltip and command, so a menu cannot draw a tick.
The state goes in the **label** instead -- "Build The Package's Lights: ON" --
and the section is rebuilt whenever a setting changes. Before this, four
settings were blind flips and two more could only be reached by typing into
the Python console.

Everything here is probed once, in :func:`probe`, and what is missing is
reported once rather than at every click.
"""

import unreal

from .constants import BUILD_VERSION, TOOL_NAME
from . import actions
from . import livelink
from . import settings


MENU_OWNER = "mLender"
MENU_PATH = "LevelEditor.MainMenu.Tools"
SECTION = "mLender"

CAPABILITIES = {}

# Import scale has no dialog yet, so it is offered as the values a shot
# actually uses: a centimetre scene, a metre scene, and the ten times a
# 200 m shot wanted.
SCALE_CHOICES = (0.1, 1.0, 10.0, 100.0)

TOGGLES = (
    "update_materials",
    "import_lights",
    "keep_existing_lights",
    "import_cameras",
    "import_animation",
    "import_sets",
    "reveal_hidden_layer",
)


def probe():
    """What this build lets a Python menu do. Logged once, not per click."""
    if CAPABILITIES:
        return CAPABILITIES
    menus = unreal.ToolMenus.get()
    CAPABILITIES["submenus"] = hasattr(unreal.ToolMenu, "add_sub_menu")
    CAPABILITIES["remove_section"] = hasattr(menus, "remove_section")
    CAPABILITIES["heading"] = getattr(
        unreal.MultiBlockType, "HEADING", None) is not None
    missing = sorted(name for name, ok in CAPABILITIES.items() if not ok)
    if missing:
        unreal.log_warning(
            "mLender: this build has no {0}; the menu falls back to a flat "
            "list.".format(", ".join(missing))
        )
    return CAPABILITIES


def _command(python):
    return "import mlender_unreal; " + python


def _entry(menu, section, name, label, tooltip, command):
    entry = unreal.ToolMenuEntry(
        name=name,
        type=unreal.MultiBlockType.MENU_ENTRY,
    )
    entry.set_label(label)
    entry.set_tool_tip(tooltip)
    entry.set_string_command(
        unreal.ToolMenuStringCommandType.PYTHON,
        "",
        string=command,
    )
    menu.add_menu_entry(section, entry)


def _heading(menu, name, text):
    """A line of text in the section. Silently skipped where unsupported."""
    if not CAPABILITIES.get("heading"):
        return
    try:
        entry = unreal.ToolMenuEntry(
            name=name, type=unreal.MultiBlockType.HEADING)
        entry.set_label(text)
        menu.add_menu_entry(SECTION, entry)
    except Exception:
        pass


def _submenu(menu, name, label, tooltip):
    """A submenu, or this same menu when the build has none.

    Returning the parent is what makes the fallback free: the caller adds its
    entries the same way either way, and a flat list with prefixed labels is
    no worse than what the menu was before.
    """
    if not CAPABILITIES.get("submenus"):
        return menu, SECTION, label + " -- "
    try:
        sub = menu.add_sub_menu(MENU_OWNER, SECTION, name, label, tooltip)
        sub.add_section(name, label)
        return sub, name, ""
    except Exception as exc:
        unreal.log_warning(
            "mLender: submenu {0} could not be made ({1}); using a flat "
            "entry.".format(name, exc)
        )
        return menu, SECTION, label + " -- "


def _summary_line():
    """What the last import did, in one line, or an invitation to do one."""
    result = livelink.last_result()
    if not result:
        return "No import yet this session."
    warnings = len(result.get("warnings") or [])
    return "Last import: {0} mesh(es), {1} material(s), {2} warning(s)".format(
        result.get("mesh_count", 0),
        result.get("material_count", 0),
        warnings,
    )


def register():
    """Add the menu. Safe to call twice; the section is replaced."""
    menus = unreal.ToolMenus.get()
    menu = menus.find_menu(MENU_PATH)
    if menu is None:
        unreal.log_warning(
            "mLender: could not find the menu {0}; the plugin still works "
            "from Python.".format(MENU_PATH)
        )
        return False
    probe()

    # Rebuilt rather than amended: the labels carry the settings' values, so
    # a stale entry would state a value that is no longer true.
    if CAPABILITIES.get("remove_section"):
        try:
            menus.remove_section(MENU_PATH, SECTION)
        except Exception:
            pass
    menu.add_section(SECTION, "{0} {1}".format(TOOL_NAME, BUILD_VERSION))

    _heading(menu, "mLenderStatus", livelink.get_status())
    _heading(menu, "mLenderLast", _summary_line())

    _link_entries(menu)
    _import_entries(menu)
    _after_entries(menu)

    livelink.set_state_hook(refresh)
    menus.refresh_all_widgets()
    return True


def refresh():
    """Redraw the menu so the labels state what the settings now are."""
    try:
        register()
    except Exception as exc:
        unreal.log_warning("mLender: the menu could not redraw: {0}".format(exc))


def _link_entries(menu):
    sub, section, prefix = _submenu(
        menu, "mLenderLiveLink", "LiveLink",
        "Listen for a package sent from Maya",
    )
    _entry(sub, section, "mLenderStart", prefix + "Start Listening",
           "Listen on {0}:{1}".format(
               settings.get("livelink_host"), settings.get("livelink_port")),
           _command("mlender_unreal.start_listener()"))
    _entry(sub, section, "mLenderStop", prefix + "Stop Listening",
           "Stop listening and free the port",
           _command("mlender_unreal.stop_listener()"))
    _entry(sub, section, "mLenderPrint", prefix + "Print Status To The Log",
           "Every setting and the listener's state, in the Output Log",
           _command("mlender_unreal.print_status()"))


def _import_entries(menu):
    sub, section, prefix = _submenu(
        menu, "mLenderWhat", "What Comes In",
        "What the next package builds when it lands",
    )
    for key in TOGGLES:
        _entry(
            sub, section, "mLenderToggle_" + key,
            prefix + settings.label_for(key),
            "Click to switch it the other way",
            _command("mlender_unreal.livelink.toggle({0!r})".format(key)),
        )

    scale, scale_section, scale_prefix = _submenu(
        sub, "mLenderScale",
        settings.label_for("import_scale"),
        "Multiplies everything: the meshes through Interchange and the "
        "motion, cameras and locators through the JSON",
    )
    for value in SCALE_CHOICES:
        _entry(
            scale, scale_section, "mLenderScale_{0:g}".format(value),
            scale_prefix + "{0:g}x".format(value),
            "Set the import scale to {0:g}".format(value),
            _command(
                "mlender_unreal.configure(import_scale={0!r}); "
                "mlender_unreal.ui.refresh()".format(value)
            ),
        )

    power, power_section, power_prefix = _submenu(
        sub, "mLenderPower",
        settings.label_for("power_scale"),
        "An artistic multiplier over the measured light conversion. The "
        "conversion is exact, so 1.0 matches the Maya render.",
    )
    for value in (0.5, 1.0, 2.0, 4.0):
        _entry(
            power, power_section, "mLenderPower_{0:g}".format(value),
            power_prefix + "{0:g}x".format(value),
            "Set the light power scale to {0:g}".format(value),
            _command(
                "mlender_unreal.configure(power_scale={0!r}); "
                "mlender_unreal.ui.refresh()".format(value)
            ),
        )

    _entry(sub, section, "mLenderReset", prefix + "Back To The Defaults",
           "Every setting to what it ships as",
           _command("mlender_unreal.settings.reset(); "
                    "mlender_unreal.ui.refresh()"))


def _after_entries(menu):
    """What to do with what arrived. Every one of these was a script.

    The same functions the panel's buttons call, so a build with no compiled
    module -- which is a valid installation -- still has all of them.
    """
    sub, section, prefix = _submenu(
        menu, "mLenderAfter", "Import And After",
        "Bring a package in, and work with what came",
    )
    for name, label, tooltip, call in (
        ("Folder", "Import a Package Folder...",
         "Pick a package written by Maya and build it here",
         "actions.import_package_folder()"),
        ("Again", "Import the Last One Again",
         "Build the last package again with the settings as they are now",
         "actions.reimport_last()"),
        ("Summary", "Summary To The Log",
         "The counts, the phase timings and the first warnings",
         "actions.show_last_summary()"),
        ("Report", "Open The Import Report",
         "The file written beside every package; it holds every warning",
         "actions.open_report()"),
        ("Folder2", "Open The Package Folder",
         "The folder the last import read",
         "actions.open_package_folder()"),
        ("Hidden", "Show / Hide The Hidden Objects",
         "Objects Maya had hidden live in a layer, because a layer is the "
         "only hiding the editor keeps across reopening the level",
         "actions.toggle_hidden_layer()"),
        ("Made", "Select What mLender Made",
         "Everything tagged by this tool, in this level",
         "actions.select_generated_actors()"),
    ):
        _entry(sub, section, "mLenderAfter" + name, prefix + label, tooltip,
               _command("mlender_unreal." + call))

    cameras = []
    try:
        cameras = actions.level_cameras()
    except Exception:
        cameras = []
    if cameras:
        look, look_section, look_prefix = _submenu(
            sub, "mLenderLook", "Look Through",
            "Pilot a camera in this level",
        )
        for index, label in enumerate(cameras[:12]):
            _entry(
                look, look_section, "mLenderLook_{0}".format(index),
                look_prefix + label,
                "Look through {0}".format(label),
                _command(
                    "mlender_unreal.actions.pilot_camera({0!r})".format(label)
                ),
            )
        _entry(look, look_section, "mLenderLookOff", look_prefix + "Stop",
               "Back to the free camera",
               _command("mlender_unreal.actions.pilot_camera()"))


def unregister():
    try:
        menus = unreal.ToolMenus.get()
        menus.unregister_owner_by_name(MENU_OWNER)
        if hasattr(menus, "remove_section"):
            menus.remove_section(MENU_PATH, SECTION)
        menus.refresh_all_widgets()
    except Exception:
        pass
    livelink.set_state_hook(None)
    livelink.stop_listener()


def print_status():
    """Every setting in one place, for when the menu cannot be trusted.

    The labels now carry the state, but a menu that failed to redraw states a
    value that is not true, and this is the readout that cannot go stale.
    """
    unreal.log(
        "mLender {0} -- {1}".format(BUILD_VERSION, livelink.get_status())
    )
    unreal.log("  {0}".format(_summary_line()))
    for line in settings.describe():
        unreal.log("  {0}".format(line))
    path = settings.settings_path()
    if path:
        unreal.log("  settings file: {0}".format(path))
