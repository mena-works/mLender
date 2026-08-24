# -*- coding: utf-8 -*-
"""Export a Maya scene without opening Maya's UI.

    mayapy -m mlender_exporter.batch --scene shot.ma --out D:/packages
    mayapy path/to/batch.py --scene shot.ma --out D:/packages --send

For a farm job, an overnight publish, or a shot list: the same exporter the UI
drives, told what to do by arguments and a preset rather than by clicking.

Settings resolve in three layers, later winning: the built-in defaults, then a
named preset, then whatever the command line said. A command line that names
only the output folder therefore keeps the artist's other settings instead of
silently reverting them to the defaults -- which is the behaviour that makes a
preset worth having at all.

Nothing here initialises Maya at import time. The module is importable inside a
running Maya, where standalone.initialize() would be wrong, and only ``main``
starts one -- and only if it is not already up.
"""
from __future__ import absolute_import, print_function

import os
import sys

# Run as a plain script -- `mayapy .../batch.py` -- there is no parent package
# and every relative import below fails. A farm job types the path far more
# often than it types -m, so the package is put back on the path here rather
# than the user being told they held it wrong.
if __name__ == "__main__" and not __package__:
    sys.path.insert(
        0, os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    )
    __package__ = "mlender_exporter"
    import mlender_exporter  # noqa: F401

from .presets import (
    DEFAULT_PRESET_NAME,
    export_kwargs,
    load_preset,
    merge,
)


def _flag(argv, name, default=None):
    """A very small argument reader.

    argparse would do, but this runs under whatever Python the installed Maya
    has and the surface is four flags; a dependency-free reader is less to go
    wrong than a parser nobody configured.
    """
    if name in argv:
        index = argv.index(name)
        if index + 1 < len(argv):
            return argv[index + 1]
    return default


def _has(argv, name):
    return name in argv


def open_scene(scene_path):
    """Open a scene file, or raise with a message worth reading."""
    import maya.cmds as cmds

    if not scene_path:
        return ""
    if not os.path.isfile(scene_path):
        raise RuntimeError("Scene not found: {0}".format(scene_path))
    cmds.file(scene_path, open=True, force=True, prompt=False)
    return scene_path


def export_file(scene_path="", output_folder="", preset=DEFAULT_PRESET_NAME,
                send=False, overrides=None):
    """Open a scene, export it, optionally send it. Returns the result dict.

    Usable from inside a running Maya as well as headless, which is the point:
    a batch run and an artist's export take exactly the same path.
    """
    settings = merge(load_preset(preset), overrides or {})
    if output_folder:
        settings["output_folder"] = output_folder
    target = settings.get("output_folder") or ""
    if not target:
        raise RuntimeError(
            "No output folder: pass --out or save one into the preset."
        )

    if scene_path:
        open_scene(scene_path)

    from .package import export_scene

    result = export_scene(target, **export_kwargs(settings))

    if send:
        from .livelink import send_package

        host = settings.get("livelink_host") or None
        port = settings.get("livelink_port") or None
        send_package(result, host=host, port=port or None)
        result["sent"] = True
    return result


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if _has(argv, "--help") or _has(argv, "-h"):
        print(__doc__)
        return 0

    scene = _flag(argv, "--scene", "")
    output = _flag(argv, "--out", "")
    preset = _flag(argv, "--preset", DEFAULT_PRESET_NAME)
    send = _has(argv, "--send")

    # Only the settings actually named are passed on, so the rest come from
    # the preset. None means "not named" here, which merge() honours.
    overrides = {
        "selected_only": True if _has(argv, "--selected") else None,
        "bake_procedurals": False if _has(argv, "--no-bake") else None,
        "collect_textures_into_package": True if _has(argv, "--collect")
        else None,
        "archive_package": True if _has(argv, "--archive") else None,
        "export_animation": True if _has(argv, "--animation") else None,
        "export_alembic_cache": True if _has(argv, "--alembic") else None,
        "cache_animated_meshes": True if _has(argv, "--cache-animation")
        else None,
        "bake_resolution": _flag(argv, "--bake-resolution"),
        "frame_start": _flag(argv, "--start"),
        "frame_end": _flag(argv, "--end"),
        "frame_step": _flag(argv, "--step"),
        "livelink_host": _flag(argv, "--host"),
        "livelink_port": _flag(argv, "--port"),
    }

    started = _start_maya_if_needed()
    try:
        result = export_file(
            scene_path=scene, output_folder=output, preset=preset,
            send=send, overrides=overrides,
        )
    except Exception as exc:
        print("mLender batch export failed: {0}".format(exc))
        return 1
    finally:
        if started:
            _stop_maya()

    print("package:  {0}".format(result.get("package_folder")))
    print("report:   {0}".format(result.get("report_path") or "(none)"))
    print("meshes {0}, lights {1}, cameras {2}, warnings {3}".format(
        result.get("mesh_count"), result.get("light_count"),
        result.get("camera_count"), len(result.get("warnings") or []),
    ))
    # The phases too: a farm log that says half an hour says nothing, one
    # that says which half hour says what to fix.
    for label, seconds in result.get("timings") or []:
        print("time:     {0:40s} {1:8.1f} s".format(label, seconds))
    print("time:     {0:40s} {1:8.1f} s".format(
        "total", float(result.get("total_seconds") or 0.0)))
    # The warnings go to stdout as well as into the report: a farm log is
    # often the only thing anybody reads afterwards.
    for warning in result.get("warnings") or []:
        print("mLender warning: {0}".format(warning))
    return 0


def _start_maya_if_needed():
    """Initialise Maya standalone, unless something already has."""
    try:
        import maya.cmds as cmds

        cmds.about(version=True)
        return False
    except Exception:
        pass
    import maya.standalone

    maya.standalone.initialize(name="python")
    return True


def _stop_maya():
    try:
        import maya.standalone

        maya.standalone.uninitialize()
    except Exception:
        pass


if __name__ == "__main__":
    sys.exit(main())
