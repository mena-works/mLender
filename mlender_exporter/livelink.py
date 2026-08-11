# -*- coding: utf-8 -*-
"""LiveLink client: notifies the Blender listener that a package is ready.

Wire format is a single UTF-8 JSON object terminated by a newline. The
protocol constants below must stay identical to the importer's; bump
LIVELINK_VERSION on both sides together when the message shape changes.
"""
from __future__ import absolute_import

import json
import socket

from .constants import (
    LIVELINK_HOST,
    LIVELINK_PACKAGE_EVENT,
    LIVELINK_PORT,
    LIVELINK_PROTOCOL,
    LIVELINK_VERSION,
)
from .mayautils import maya_path


CONNECT_TIMEOUT_SECONDS = 5.0


def send_package(result, host=None, port=None):
    host = host or LIVELINK_HOST
    try:
        port = int(port if port is not None else LIVELINK_PORT)
    except Exception:
        raise ValueError("Blender port must be a number.")

    # Protocol 2 sends only the package location. The JSON is already on disk
    # and the importer reads it from there, so putting a copy on the wire only
    # duplicated it: measured at about 225 bytes per animation sample, a long
    # range with many animated lights could approach the importer's 32 MB
    # message ceiling for no reason.
    #
    # This assumes the listener can see the package folder, which was already
    # true: the FBX and the textures are referenced by path too.
    message = {
        "protocol": LIVELINK_PROTOCOL,
        "protocol_version": LIVELINK_VERSION,
        "event": LIVELINK_PACKAGE_EVENT,
        "package_folder": maya_path(result["package_folder"]),
        "package_name": result.get("package_name") or "",
    }
    send_message(message, host, port)


def send_message(message, host=None, port=None):
    """Write one newline-terminated JSON message to the Blender listener.

    Shared by the package notification and the pose bridge, so the two events
    cannot drift apart in framing.
    """
    host = host or LIVELINK_HOST
    try:
        port = int(port if port is not None else LIVELINK_PORT)
    except Exception:
        raise ValueError("Blender port must be a number.")
    payload = (json.dumps(message, ensure_ascii=False) + "\n").encode("utf-8")

    try:
        connection = socket.create_connection(
            (host, port),
            timeout=CONNECT_TIMEOUT_SECONDS,
        )
        try:
            connection.sendall(payload)
        finally:
            connection.close()
    except socket.error as exc:
        raise RuntimeError(
            "Could not connect to Blender at {0}:{1}. ({2})".format(
                host,
                port,
                exc,
            )
        )
