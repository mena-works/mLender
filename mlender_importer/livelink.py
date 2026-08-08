# -*- coding: utf-8 -*-
"""LiveLink listener.

bpy is not thread safe. The socket thread does nothing but read bytes and push
them onto a queue; every bpy call happens in :func:`process_messages`, which
runs on the main thread through bpy.app.timers. Never add a bpy call to the
listener thread.
"""

import json
import socket
import threading

try:
    import queue
except ImportError:
    import Queue as queue

import bpy

from .constants import (
    LIVELINK_EVENT,
    LIVELINK_HOST,
    LIVELINK_PORT,
    LIVELINK_PROTOCOL,
    LIVELINK_VERSION,
    MAX_MESSAGE_BYTES,
    SOCKET_POLL_SECONDS,
    TIMER_INTERVAL_SECONDS,
)
from .importer import import_scene_package


_server = None
_server_thread = None
_stop_event = None
_messages = queue.Queue()
_status = "Listener is stopped."


def get_status():
    """Current listener status text.

    A function, not a module attribute read: the UI must see the live value
    rather than a name bound at import time.
    """
    return _status


def is_running():
    return _server is not None


def start_listener(host, port):
    global _server, _server_thread, _stop_event, _status
    if _server is not None:
        _status = "Listener is already running."
        return

    host = str(host or LIVELINK_HOST)
    port = int(port)
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind((host, port))
    server.listen(4)
    # A short timeout lets the accept loop notice the stop event.
    server.settimeout(SOCKET_POLL_SECONDS)

    _drain_messages()
    stop_event = threading.Event()
    _server = server
    _stop_event = stop_event
    _server_thread = threading.Thread(
        target=_listener_loop,
        args=(server, stop_event),
        name="ZALookdevLiveLink",
    )
    _server_thread.daemon = True
    _server_thread.start()
    _status = "Listening on {0}:{1}".format(host, port)

    if not bpy.app.timers.is_registered(process_messages):
        bpy.app.timers.register(
            process_messages,
            first_interval=TIMER_INTERVAL_SECONDS,
        )


def stop_listener():
    global _server, _server_thread, _stop_event, _status
    server = _server
    server_thread = _server_thread
    stop_event = _stop_event

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

    try:
        if bpy.app.timers.is_registered(process_messages):
            bpy.app.timers.unregister(process_messages)
    except Exception:
        pass

    if (
        server_thread
        and server_thread.is_alive()
        and server_thread is not threading.current_thread()
    ):
        server_thread.join(timeout=1.0)

    _drain_messages()
    _status = "Listener is stopped."


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


def process_messages():
    """Main thread pump. Returns the next timer interval, or None to stop."""
    global _status
    try:
        kind, payload = _messages.get_nowait()
    except queue.Empty:
        return TIMER_INTERVAL_SECONDS if _server else None

    if kind == "error":
        _status = "Message rejected: {0}".format(payload)
        return TIMER_INTERVAL_SECONDS

    try:
        validate_message(payload)
        scene = bpy.context.scene
        result = import_scene_package(
            payload.get("package_folder") or "",
            package_data=payload.get("package_json"),
            import_scale=scene.ml_import_scale,
            power_scale=scene.ml_light_power_scale,
        )
        _status = (
            "Imported {0} mesh(es), {1} material(s), "
            "{2} subdivision modifier(s), {3} light(s), {4} camera(s), "
            "{5} collection(s), {6} instance(s), {7} empty(ies), "
            "{8} curve(s), {9} set(s), {10} layer(s)."
        ).format(
            result["mesh_count"],
            result["material_count"],
            result["subdivision_count"],
            result["light_count"],
            result["camera_count"],
            result["group_collection_count"],
            result["instanced_count"],
            result["transform_count"],
            result["curve_count"],
            result["set_count"],
            result["layer_count"],
        )
        for warning in result.get("warnings") or []:
            print("mLender warning: {0}".format(warning))
    except Exception as exc:
        _status = "Import failed: {0}".format(exc)
        print("mLender: {0}".format(_status))
    return TIMER_INTERVAL_SECONDS


def validate_message(message):
    if not isinstance(message, dict):
        raise ValueError("LiveLink message must be a JSON object.")
    if message.get("protocol") != LIVELINK_PROTOCOL:
        raise ValueError("Unsupported LiveLink protocol.")
    if message.get("protocol_version") != LIVELINK_VERSION:
        raise ValueError("Unsupported LiveLink protocol version.")
    if message.get("event") != LIVELINK_EVENT:
        raise ValueError("Unsupported LiveLink event.")
    # Protocol 2 carries the package location rather than a copy of its JSON,
    # which the importer reads from disk. An embedded package_json is still
    # accepted and used when present, so a sender that wants to avoid the disk
    # read can still send one.
    if not str(message.get("package_folder") or "").strip():
        raise ValueError("LiveLink package folder is missing.")
    embedded = message.get("package_json")
    if embedded is not None and not isinstance(embedded, dict):
        raise ValueError("LiveLink package JSON must be an object.")
