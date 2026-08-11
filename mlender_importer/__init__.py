# -*- coding: utf-8 -*-
"""mLender, Blender side.

Install this folder as a Blender add-on. Public API::

    import mlender_importer
    mlender_importer.import_scene_package(package_folder)

Keep ``bl_info["version"]`` and ``constants.BUILD_VERSION`` in step; the panel
shows BUILD_VERSION and it is how a user confirms which build is loaded.
"""

bl_info = {
    "name": "mLender",
    "author": "mena-works",
    "version": (2, 35, 0),
    # 4.1 is the oldest build this is actually tested on, and the code
    # relies on APIs that arrived in 4.0. Claiming 3.6 was untrue.
    "blender": (4, 1, 0),
    "location": "View3D > Sidebar > mLender",
    "description": (
        "Live scene transfer from Maya: meshes, materials, lights and "
        "cameras rebuilt natively in Blender."
    ),
    "category": "Import-Export",
}

# Blender re-executes this file on "Reload Scripts" but leaves submodules
# cached, so they are reloaded here in dependency order.
if "bpy" in locals():
    import importlib

    from . import (
        constants,
        utils,
        attributes,
        asrig,
        transforms,
        colormanagement,
        animation,
        images,
        corrections,
        materials,
        lights,
        cameras,
        scene,
        empties,
        curves,
        volumes,
        standins,
        constraints,
        particles,
        instancers,
        render,
        aovs,
        sets,
        merge,
        posebridge,
        fbx,
        alembic,
        importer,
        livelink,
        ui,
    )

    for _module in (
        constants,
        utils,
        attributes,
        asrig,
        transforms,
        colormanagement,
        animation,
        images,
        corrections,
        materials,
        lights,
        cameras,
        scene,
        empties,
        curves,
        volumes,
        standins,
        constraints,
        particles,
        instancers,
        render,
        aovs,
        sets,
        merge,
        posebridge,
        fbx,
        alembic,
        importer,
        livelink,
        ui,
    ):
        importlib.reload(_module)

# Not used directly. Its presence in this module's globals is what the reload
# block above tests to tell a fresh import from a "Reload Scripts" re-execution,
# so it must be imported here and after that block.
import bpy  # noqa: E402,F401

from .constants import (  # noqa: E402
    BUILD_VERSION,
    LIVELINK_HOST,
    LIVELINK_PORT,
    LIVELINK_PROTOCOL,
    LIVELINK_VERSION,
)
from .importer import import_scene_package  # noqa: E402
from .livelink import (  # noqa: E402
    get_status,
    is_running,
    start_listener,
    stop_listener,
)
from .ui import register_ui, unregister_ui  # noqa: E402


__all__ = [
    "BUILD_VERSION",
    "LIVELINK_HOST",
    "LIVELINK_PORT",
    "LIVELINK_PROTOCOL",
    "LIVELINK_VERSION",
    "bl_info",
    "get_status",
    "import_scene_package",
    "is_running",
    "register",
    "start_listener",
    "stop_listener",
    "unregister",
]


def register():
    register_ui()


def unregister():
    # The listener holds a socket and a timer; both must go before the
    # operators and properties it reports through.
    stop_listener()
    unregister_ui()


if __name__ == "__main__":
    register()
