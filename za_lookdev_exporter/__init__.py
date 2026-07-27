# -*- coding: utf-8 -*-
"""Z-A Exporter - Lookdev, Maya side.

Public API::

    import za_lookdev_exporter as za
    za.show_ui()

Everything else is internal. Use :func:`reload_package` during development;
``importlib.reload`` on the package alone only re-executes this file and
leaves the submodules stale.
"""
from __future__ import absolute_import

import sys

from .constants import (
    EXPORT_SCHEMA_VERSION,
    LIVELINK_HOST,
    LIVELINK_PORT,
    LIVELINK_PROTOCOL,
    LIVELINK_VERSION,
    TOOL_NAME,
)
from .package import export_lookdev
from .ui import show_ui


BUILD_VERSION = "1.15.0"

# Dependency order; reloading follows this list so each module re-imports
# already refreshed dependencies.
SUBMODULES = (
    "constants",
    "mayautils",
    "textures",
    "bake",
    "shaders",
    "meshes",
    "lights",
    "cameras",
    "fbx",
    "livelink",
    "package",
    "ui",
)

__all__ = [
    "BUILD_VERSION",
    "EXPORT_SCHEMA_VERSION",
    "LIVELINK_HOST",
    "LIVELINK_PORT",
    "LIVELINK_PROTOCOL",
    "LIVELINK_VERSION",
    "TOOL_NAME",
    "export_lookdev",
    "reload_package",
    "show",
    "show_ui",
]


def show():
    """Public entry point used by Maya shelf and Script Editor launchers."""
    return show_ui()


def reload_package():
    """Reload every submodule in dependency order, then this package.

    Returns the refreshed package module, which callers should rebind::

        za = za.reload_package()
        za.show_ui()
    """
    try:
        from importlib import reload as _reload
    except ImportError:
        _reload = reload  # noqa: F821  (Python 2 builtin)

    for name in SUBMODULES:
        module = sys.modules.get(__name__ + "." + name)
        if module is not None:
            _reload(module)
    return _reload(sys.modules[__name__])
