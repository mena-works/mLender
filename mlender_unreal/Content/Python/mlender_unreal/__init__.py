# -*- coding: utf-8 -*-
"""mLender -- Unreal receiver.

Reads the packages the Maya exporter writes and rebuilds them in Unreal:
meshes with their hierarchy through Interchange, materials as Material
Instances, lights as Unreal light actors and cameras as cine cameras.

This package never imports the Maya exporter or the Blender importer. The three
run in three different Python runtimes and their only contract is the LiveLink
protocol and the package JSON schema.

Reloading during development:

    import mlender_unreal
    mlender_unreal.reload_package()

Every module must appear in SUBMODULES below, in dependency order. A module
left out keeps running its old code through a reload, which at development time
looks exactly like the edit not having worked.
"""

import importlib

from .constants import (  # noqa: F401
    BUILD_VERSION,
    LIVELINK_HOST,
    LIVELINK_PORT,
    LIVELINK_PROTOCOL,
    LIVELINK_VERSION,
    SUPPORTED_SCHEMA_VERSIONS,
)

# Import order is dependency order: a module may only import ones before it.
SUBMODULES = (
    "constants",
    "utils",
    "transforms",
    "objects",
    "images",
    "materials",
    "lights",
    "cameras",
    "meshes",
    "alembic",
    "empties",
    "curves",
    "volumes",
    "standins",
    "particles",
    "instancers",
    "sets",
    "asrig",
    "animation",
    "scene",
    "report",
    "importer",
    "livelink",
    "ui",
)

from . import constants  # noqa: E402,F401
from . import utils  # noqa: E402,F401
from . import transforms  # noqa: E402,F401
from . import objects  # noqa: E402,F401
from . import images  # noqa: E402,F401
from . import materials  # noqa: E402,F401
from . import lights  # noqa: E402,F401
from . import cameras  # noqa: E402,F401
from . import meshes  # noqa: E402,F401
from . import alembic  # noqa: E402,F401
from . import empties  # noqa: E402,F401
from . import curves  # noqa: E402,F401
from . import volumes  # noqa: E402,F401
from . import standins  # noqa: E402,F401
from . import particles  # noqa: E402,F401
from . import instancers  # noqa: E402,F401
from . import sets  # noqa: E402,F401
from . import asrig  # noqa: E402,F401
from . import animation  # noqa: E402,F401
from . import scene  # noqa: E402,F401
from . import report  # noqa: E402,F401
from . import importer  # noqa: E402,F401
from . import livelink  # noqa: E402,F401
from . import ui  # noqa: E402,F401

from .importer import import_scene_package  # noqa: E402
from .livelink import (  # noqa: E402
    configure,
    get_status,
    is_running,
    start_listener,
    stop_listener,
)
from .ui import print_status, register, unregister  # noqa: E402


__all__ = [
    "BUILD_VERSION",
    "configure",
    "get_status",
    "import_scene_package",
    "is_running",
    "print_status",
    "register",
    "reload_package",
    "start_listener",
    "stop_listener",
    "unregister",
]


def reload_package():
    """Re-import every module in dependency order, then re-register the menu."""
    try:
        unregister()
    except Exception:
        pass
    package = importlib.import_module(__name__)
    for name in SUBMODULES:
        module = importlib.import_module("{0}.{1}".format(__name__, name))
        importlib.reload(module)
    importlib.reload(package)
    return importlib.import_module(__name__)
