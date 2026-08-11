# -*- coding: utf-8 -*-
"""Live pose bridge: Maya stays the evaluator, Blender mirrors the skeleton.

The rig's control layer is not translated, deliberately. Measured on a
production character, the chain between a control and a bind joint runs
through motion paths, skinned ribbon curves, twist-extraction IK handles and
utility maths -- the one tool that translates that graph (Rumba's mtorba)
reimplements eighty-plus Maya node types and still calls itself a subset.
Instead the bridge does what Unreal's Live Link for Maya does: the controls
are used *in Maya*, Maya's own DG evaluates them, and only the resulting bind
joint world matrices travel. Zero approximation, because nothing is imitated.

Measured on the same character: one pose tick -- move a control, sample every
bound joint -- runs at 8 Hz interactively and 62 Hz when driven by a timeline
scrub, at about 292 KB per message. The difference is dirty propagation, not
the sampling: a ``currentTime`` set lets Maya's parallel EM evaluate the graph
in one pass.
"""
from __future__ import absolute_import

import maya.cmds as cmds

from .constants import (
    LIVELINK_HOST,
    LIVELINK_PORT,
    LIVELINK_POSE_EVENT,
    LIVELINK_PROTOCOL,
    LIVELINK_VERSION,
)
from .livelink import send_message
from .mayautils import (
    meters_per_maya_unit,
    node_label,
    unique,
    without_namespace,
)
from .meshes import scene_mesh_shapes
from .rigging import scene_joints


def pose_message(selected_only=False):
    """One pose: every bound joint's world matrix, at the current frame.

    The same joint discovery the export uses, so the skeleton sampled here is
    the skeleton the FBX carried and the Blender armature mirrors. Short
    names travel because bone names in Blender are the FBX's short names;
    the full path rides along for diagnostics only.
    """
    joints = scene_joints(scene_mesh_shapes(selected_only))
    records = []
    for joint in unique(joints):
        try:
            matrix = cmds.xform(joint, query=True, worldSpace=True,
                                matrix=True)
        except Exception:
            continue
        records.append({
            "name": without_namespace(node_label(joint)),
            "path": joint,
            "matrix": [float(value) for value in matrix],
        })
    return {
        "protocol": LIVELINK_PROTOCOL,
        "protocol_version": LIVELINK_VERSION,
        "event": LIVELINK_POSE_EVENT,
        "pose": {
            "meters_per_maya_unit": meters_per_maya_unit(),
            "frame": cmds.currentTime(query=True),
            "joints": records,
        },
    }


def send_pose(host=None, port=None, selected_only=False):
    """Sample the skeleton and send it. Returns how many joints travelled."""
    message = pose_message(selected_only)
    count = len(message["pose"]["joints"])
    if not count:
        raise RuntimeError(
            "No bound joints to send. The pose bridge mirrors the skeleton "
            "of the exported meshes; send a package first, and only a scene "
            "whose meshes are skinned has a skeleton to mirror."
        )
    send_message(message, host, port)
    return count


# The timeline sync is a scriptJob on timeChanged: scrubbing Maya streams the
# evaluated pose. Deliberately not an attribute-changed job per control --
# there are hundreds of controls and no generic way to enumerate them.
_sync_job = None


def timeline_sync_running():
    return _sync_job is not None


def start_timeline_sync(host=None, port=None):
    global _sync_job
    if _sync_job is not None:
        return

    def _tick():
        global _sync_job
        try:
            send_pose(host, port)
        except Exception as exc:
            # Blender going away must not turn every scrub into an error
            # dialog; the job removes itself and says why once.
            stop_timeline_sync()
            print("mLender pose sync stopped: {0}".format(exc))

    _sync_job = cmds.scriptJob(event=["timeChanged", _tick])


def stop_timeline_sync():
    global _sync_job
    job = _sync_job
    _sync_job = None
    if job is None:
        return
    try:
        if cmds.scriptJob(exists=job):
            cmds.scriptJob(kill=job, force=True)
    except Exception:
        pass
