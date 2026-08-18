# -*- coding: utf-8 -*-
"""Unreal half of the end-to-end LiveLink test: the actual user path.

**Copy this file to <project>/Content/Python/init_unreal.py**, launch the
editor, and run tests/host/maya_livelink_send.py in mayapy. Order does not
matter: Maya waits for this side to report the socket bound. Remove the copy
afterwards.

This is the one path nothing else exercises. Every other test calls
import_scene_package() directly, but what an artist does is press Send in Maya
and expect Unreal to receive it over the socket -- which runs the listener
thread, the game-thread pump and the message validator, none of which a direct
call touches. It has to run in a real editor because the pump is a Slate tick
callback and a commandlet does not tick.

Starts the production listener, waits for one import to land, asserts the level
holds what the package described, writes the result and quits.
"""
import json
import os
import sys
import tempfile
import traceback

import unreal

TAG = "MLE2E"


def repo_root():
    """Where the repository is, for a file that gets copied out of it.

    __file__ answers this while the file is still in the repository. Installing
    it as a project's Content/Python/init_unreal.py moves it, so MLENDER_ROOT
    is the override.

    Asked for rather than hardcoded: a path with somebody's user name in it does
    not belong in a public repository, and would be wrong on every machine but
    one anyway.
    """
    here = os.path.dirname(os.path.abspath(__file__))
    for candidate in (
        os.path.dirname(os.path.dirname(here)),   # tests/<group>/<file>.py
        os.environ.get("MLENDER_ROOT", ""),
    ):
        if candidate and os.path.isdir(
            os.path.join(candidate, "mlender_unreal")
        ):
            return candidate
    return ""


REPO = repo_root()
PKG_PY = os.path.join(REPO, "mlender_unreal", "Content", "Python")
if REPO and PKG_PY not in sys.path:
    sys.path.insert(0, PKG_PY)
elif not REPO:
    unreal.log_error(
        "MLE2E could not find the mLender checkout. Set MLENDER_ROOT to it."
    )

OUT = os.path.join(tempfile.gettempdir(), "ml_livelink_e2e")
RESULT = os.path.join(OUT, "result.json")
READY = os.path.join(OUT, "listener_ready")
TIMEOUT_TICKS = 3000

_state = {"ticks": 0, "handle": None, "busy": False, "done": False,
          "started": False, "last_status": ""}


def say(key, value):
    unreal.log("{0} {1} = {2}".format(TAG, key, value))


def finish(payload):
    _state["done"] = True
    if not os.path.isdir(OUT):
        os.makedirs(OUT)
    with open(RESULT, "w") as handle:
        json.dump(payload, handle, indent=2, default=str)
    say("wrote", RESULT)
    if _state["handle"] is not None:
        try:
            unreal.unregister_slate_post_tick_callback(_state["handle"])
        except Exception:
            pass
    say("DONE", "")
    unreal.SystemLibrary.quit_editor()


def on_tick(_delta):
    if _state["done"] or _state["busy"]:
        return
    _state["busy"] = True
    try:
        body()
    except Exception as exc:
        unreal.log_error(traceback.format_exc())
        finish({"ok": False, "reason": str(exc)})
    finally:
        _state["busy"] = False


def body():
    import mlender_unreal

    _state["ticks"] += 1
    if not _state["started"]:
        if _state["ticks"] < 45:
            return
        status = mlender_unreal.start_listener()
        say("listener", status)
        say("is_running", mlender_unreal.is_running())
        _state["started"] = True
        if not os.path.isdir(OUT):
            os.makedirs(OUT)
        # Maya waits for this file, so the send cannot race the bind.
        with open(READY, "w") as handle:
            handle.write(status)
        return

    # The production pump. mlender_unreal registered its own tick callback for
    # this; calling it here as well is harmless (the queue is drained once) and
    # makes the test independent of callback ordering.
    status = mlender_unreal.get_status()
    if status != _state["last_status"]:
        say("status", status)
        _state["last_status"] = status

    if "Imported" in status or "failed" in status.lower():
        actors = unreal.get_editor_subsystem(
            unreal.EditorActorSubsystem
        ).get_all_level_actors() or []
        kinds = {}
        for actor in actors:
            name = actor.get_class().get_name()
            kinds[name] = kinds.get(name, 0) + 1
        say("level", json.dumps(kinds))
        ours = 0
        for actor in actors:
            if not isinstance(actor, unreal.StaticMeshActor):
                continue
            component = actor.static_mesh_component
            try:
                for index in range(component.get_num_materials()):
                    material = component.get_material(index)
                    if material and material.get_name().startswith("ML_"):
                        ours += 1
            except Exception:
                pass
        say("meshes carrying our materials", ours)
        mlender_unreal.stop_listener()
        finish({
            "ok": "Imported" in status,
            "status": status,
            "actor_kinds": kinds,
            "slots_with_our_materials": ours,
        })
        return

    if _state["ticks"] > TIMEOUT_TICKS:
        mlender_unreal.stop_listener()
        finish({"ok": False, "reason": "timed out waiting for a package",
                "status": status})


_state["handle"] = unreal.register_slate_post_tick_callback(on_tick)
say("registered", "end-to-end livelink")
