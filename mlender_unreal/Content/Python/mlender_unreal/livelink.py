# -*- coding: utf-8 -*-
"""LiveLink listener for Unreal.

The unreal module is no more thread safe than bpy is. The socket thread does
nothing but read bytes and push them onto a queue; every unreal call happens in
:func:`process_messages`, which the editor calls on the game thread through a
Slate post-tick callback. Never add an unreal call to the listener thread.

The Blender receiver uses bpy.app.timers for the same job. The hook differs,
the rule does not.
"""

import json
import queue
import socket
import threading

import unreal

from .constants import (
    LIVELINK_HOST,
    LIVELINK_PACKAGE_EVENT,
    LIVELINK_POSE_EVENT,
    LIVELINK_PORT,
    LIVELINK_PROTOCOL,
    LIVELINK_VERSION,
    MAX_MESSAGE_BYTES,
    SOCKET_POLL_SECONDS,
)
from .importer import import_scene_package


_server = None
_server_thread = None
_stop_event = None
_tick_handle = None
_messages = queue.Queue()
_status = "Listener is stopped."
_settings = {"import_scale": 1.0, "power_scale": 1.0}


def get_status():
    """Current listener status. A function, so callers see the live value."""
    return _status


def is_running():
    return _server is not None


def configure(import_scale=None, power_scale=None):
    if import_scale is not None:
        _settings["import_scale"] = float(import_scale)
    if power_scale is not None:
        _settings["power_scale"] = float(power_scale)
    return dict(_settings)


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
        result = import_scene_package(
            payload.get("package_folder") or "",
            package_data=payload.get("package_json"),
            import_scale=_settings["import_scale"],
            power_scale=_settings["power_scale"],
        )
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
        for warning in result.get("warnings") or []:
            unreal.log_warning("mLender warning: {0}".format(warning))
    except Exception as exc:
        _status = "Import failed: {0}".format(exc)
        unreal.log_error("mLender: {0}".format(_status))


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
