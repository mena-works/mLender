# -*- coding: utf-8 -*-
"""LiveLink listener for Unreal.

The unreal module is no more thread safe than bpy is. The socket thread does
nothing but read bytes and push them onto a queue; every unreal call happens in
:func:`process_messages`, which the editor calls on the game thread through a
Slate post-tick callback. Never add an unreal call to the listener thread.

The Blender receiver uses bpy.app.timers for the same job. The hook differs,
the rule does not.
"""

import inspect
import json
import queue
import socket
import threading

import unreal

from .constants import (
    LIVELINK_HOST,
    MENU_WARNING_LIMIT,
    LIVELINK_PACKAGE_EVENT,
    LIVELINK_POSE_EVENT,
    LIVELINK_PORT,
    LIVELINK_PROTOCOL,
    LIVELINK_VERSION,
    MAX_MESSAGE_BYTES,
    SOCKET_POLL_SECONDS,
)
from . import settings
from .importer import import_scene_package


_server = None
_server_thread = None
_stop_event = None
_tick_handle = None
_messages = queue.Queue()
_status = "Listener is stopped."
_last_result = None
# What redraws a menu whose labels carry the settings' state. livelink is
# earlier in the dependency order than ui, so it cannot import it; ui hands
# its refresh in instead. A direct import here would make the reload lists
# reload in a cycle.
_state_hook = None


def set_state_hook(callback):
    """Register what to call when a setting changes. ui.register installs it."""
    global _state_hook
    _state_hook = callback


def _state_changed():
    if _state_hook is None:
        return
    try:
        _state_hook()
    except Exception as exc:
        unreal.log_warning("mLender: the menu could not redraw: {0}".format(exc))


def last_result():
    """The last import's result dict, or None. Read by the panel and menu."""
    return _last_result


def remember_result(result):
    global _last_result
    _last_result = result
    return result


def get_status():
    """Current listener status. A function, so callers see the live value."""
    return _status


def is_running():
    return _server is not None


def configure(**kwargs):
    """Set what the next package does when it lands.

    Kept as the public name it has always had, and still in ``__all__`` and in
    the README, but the values now live in :mod:`settings` so that a menu, a
    panel and a script all read one place and so that they survive a restart.
    Every argument is optional and named, because these are set one at a time.
    """
    return settings.update(**kwargs)


def toggle_keep_existing_lights():
    """Flip it and say which way it went."""
    state = settings.toggle("keep_existing_lights")
    unreal.log(
        "mLender: existing lighting will be {0} on the next import.".format(
            "kept" if state else "cleared with everything else"
        )
    )
    _state_changed()
    return state


def toggle_import_lights():
    state = settings.toggle("import_lights")
    unreal.log(
        "mLender: the package's lights will {0} on the next import.".format(
            "be built" if state else "not be built"
        )
    )
    _state_changed()
    return state


def toggle(key):
    """Flip any switch and redraw whatever shows it."""
    state = settings.toggle(key)
    unreal.log("mLender: {0}".format(settings.label_for(key)))
    _state_changed()
    return state


def start_listener(host=None, port=None):
    global _server, _server_thread, _stop_event, _tick_handle, _status
    if _server is not None:
        _status = "Listener is already running."
        return _status

    host = str(host or LIVELINK_HOST)
    port = int(port or LIVELINK_PORT)
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind((host, port))
    server.listen(4)
    server.settimeout(SOCKET_POLL_SECONDS)

    _drain_messages()
    stop_event = threading.Event()
    _server = server
    _stop_event = stop_event
    _server_thread = threading.Thread(
        target=_listener_loop,
        args=(server, stop_event),
        name="mLenderLiveLink",
    )
    _server_thread.daemon = True
    _server_thread.start()

    _tick_handle = unreal.register_slate_post_tick_callback(_on_tick)
    _status = "Listening on {0}:{1}".format(host, port)
    return _status


def stop_listener():
    global _server, _server_thread, _stop_event, _tick_handle, _status
    server, server_thread, stop_event = _server, _server_thread, _stop_event

    if stop_event:
        stop_event.set()
    if server:
        try:
            server.close()
        except Exception:
            pass
    _server = None
    _server_thread = None
    _stop_event = None

    if _tick_handle is not None:
        try:
            unreal.unregister_slate_post_tick_callback(_tick_handle)
        except Exception:
            pass
        _tick_handle = None

    if (
        server_thread
        and server_thread.is_alive()
        and server_thread is not threading.current_thread()
    ):
        server_thread.join(timeout=1.0)

    _drain_messages()
    _status = "Listener is stopped."
    return _status


def _drain_messages():
    """Discard queued messages so a restart never replays a stale package."""
    while True:
        try:
            _messages.get_nowait()
        except queue.Empty:
            return


def _listener_loop(server, stop_event):
    """Socket thread. Reads one newline terminated JSON message per client."""
    while not stop_event.is_set():
        try:
            connection, _address = server.accept()
        except socket.timeout:
            continue
        except OSError:
            break
        try:
            data = b""
            while len(data) <= MAX_MESSAGE_BYTES:
                chunk = connection.recv(65536)
                if not chunk:
                    break
                data += chunk
                if b"\n" in data:
                    break
            if len(data) > MAX_MESSAGE_BYTES:
                raise ValueError("LiveLink message is too large.")
            message = json.loads(data.split(b"\n", 1)[0].decode("utf-8"))
            _messages.put(("message", message))
        except Exception as exc:
            _messages.put(("error", str(exc)))
        finally:
            try:
                connection.close()
            except Exception:
                pass


def _on_tick(_delta_seconds):
    """Slate post-tick, so this runs on the game thread."""
    process_messages()


def process_messages():
    """Game thread pump. One message per call, so a tick is never long."""
    global _status
    try:
        kind, payload = _messages.get_nowait()
    except queue.Empty:
        return

    if kind == "error":
        _status = "Message rejected: {0}".format(payload)
        unreal.log_warning("mLender: {0}".format(_status))
        return

    try:
        validate_message(payload)
        if payload.get("event") == LIVELINK_POSE_EVENT:
            # Rejected explicitly rather than ignored: a pose that silently
            # does nothing looks like a broken rig on the Maya side.
            _status = (
                "A pose update arrived; this build's Unreal receiver does not "
                "apply poses."
            )
            unreal.log_warning("mLender: {0}".format(_status))
            return
        result = remember_result(import_scene_package(
            payload.get("package_folder") or "",
            package_data=payload.get("package_json"),
            **accepted_kwargs(settings.import_kwargs())
        ))
        _status = (
            "Imported {0} mesh(es), {1} material(s), {2} light(s), "
            "{3} camera(s)."
        ).format(
            result["mesh_count"],
            result["material_count"],
            result["light_count"],
            result["camera_count"],
        )
        unreal.log("mLender: {0}".format(_status))
        report_warnings(result)
        _state_changed()
    except Exception as exc:
        _status = "Import failed: {0}".format(exc)
        unreal.log_error("mLender: {0}".format(_status))


def accepted_kwargs(candidates):
    """Only the settings this build's importer actually takes.

    The settings list grows a phase ahead of the importer, and a keyword the
    receiver does not take does not raise politely -- it drops the whole
    import. The exporter learned the same thing about preset keys.
    """
    try:
        allowed = set(
            inspect.signature(import_scene_package).parameters
        )
    except (TypeError, ValueError):
        return dict(candidates)
    dropped = sorted(
        key for key in candidates
        if key not in allowed
        and candidates[key] != settings.SETTING_DEFAULTS.get(key)
    )
    if dropped:
        unreal.log_warning(
            "mLender: this build's importer does not take {0}; "
            "those settings had no effect.".format(", ".join(dropped))
        )
    return dict(
        (key, value) for key, value in candidates.items() if key in allowed
    )


def report_warnings(result):
    """Say how many, show the first few, and point at the file with the rest.

    One warning per log line put sixty-plus lines in the Output Log on a real
    shot, which is how a warning stops being read. The report already holds
    every one of them, and until now nothing ever said where it was.
    """
    warnings = list(result.get("warnings") or [])
    if not warnings:
        return 0
    shown = warnings[:MENU_WARNING_LIMIT]
    unreal.log_warning(
        "mLender: {0} warning(s) from this import; the first {1} follow."
        .format(len(warnings), len(shown))
    )
    for warning in shown:
        unreal.log_warning("  {0}".format(warning))
    report = result.get("report_path") or ""
    if len(warnings) > len(shown):
        unreal.log_warning(
            "  ... and {0} more.".format(len(warnings) - len(shown))
        )
    if report:
        unreal.log_warning("  All of them are in {0}".format(report))
    return len(warnings)


def validate_message(message):
    if not isinstance(message, dict):
        raise ValueError("LiveLink message must be a JSON object.")
    if message.get("protocol") != LIVELINK_PROTOCOL:
        raise ValueError("Unsupported LiveLink protocol.")
    if message.get("protocol_version") != LIVELINK_VERSION:
        raise ValueError("Unsupported LiveLink protocol version.")
    event = message.get("event")
    if event not in (LIVELINK_PACKAGE_EVENT, LIVELINK_POSE_EVENT):
        raise ValueError("Unsupported LiveLink event.")
    if event == LIVELINK_POSE_EVENT:
        if not isinstance(message.get("pose"), dict):
            raise ValueError("LiveLink pose payload is missing.")
        return
    if not str(message.get("package_folder") or "").strip():
        raise ValueError("LiveLink package folder is missing.")
    embedded = message.get("package_json")
    if embedded is not None and not isinstance(embedded, dict):
        raise ValueError("LiveLink package JSON must be an object.")
