# -*- coding: utf-8 -*-
"""Editor menu entries.

Unreal has no sidebar panel a Python plugin can add cheaply, so the controls
live in a Tools menu section. The menu class names were probed on 5.8.1 rather
than assumed -- a wrong menu name registers nothing and reports no error, which
is the same failure mode as a panel whose buttons do nothing.
"""

import unreal

from .constants import BUILD_VERSION, LIVELINK_HOST, LIVELINK_PORT, TOOL_NAME
from . import livelink


MENU_OWNER = "mLender"
MENU_PATH = "LevelEditor.MainMenu.Tools"
SECTION = "mLender"


def _entry(menu, name, label, tooltip, command):
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
    menu.add_menu_entry(SECTION, entry)


def register():
    """Add the menu. Safe to call twice; Unreal replaces the section."""
    menus = unreal.ToolMenus.get()
    menu = menus.find_menu(MENU_PATH)
    if menu is None:
        unreal.log_warning(
            "mLender: could not find the menu {0}; the plugin still works "
            "from Python.".format(MENU_PATH)
        )
        return False
    menu.add_section(SECTION, "{0} {1}".format(TOOL_NAME, BUILD_VERSION))

    _entry(
        menu, "mLenderStart", "Start LiveLink",
        "Listen for a package from Maya on {0}:{1}".format(
            LIVELINK_HOST, LIVELINK_PORT
        ),
        "import mlender_unreal; mlender_unreal.start_listener()",
    )
    _entry(
        menu, "mLenderStop", "Stop LiveLink",
        "Stop listening",
        "import mlender_unreal; mlender_unreal.stop_listener()",
    )
    _entry(
        menu, "mLenderStatus", "LiveLink Status",
        "Print the listener status and build number to the log",
        "import mlender_unreal; mlender_unreal.print_status()",
    )
    menus.refresh_all_widgets()
    return True


def unregister():
    try:
        menus = unreal.ToolMenus.get()
        menus.unregister_owner_by_name(MENU_OWNER)
        menus.refresh_all_widgets()
    except Exception:
        pass
    livelink.stop_listener()


def print_status():
    unreal.log(
        "mLender {0} -- {1}".format(BUILD_VERSION, livelink.get_status())
    )
