# -*- coding: utf-8 -*-
"""Advanced Skeleton recognition: describe the rig the way AS declares it.

Nothing here is inferred from geometry. Advanced Skeleton writes its own
manifest into the scene, measured identical across five production rigs:

* ``DeformSet`` names the bind skeleton (34-36 body joints).
* ``ControlSet`` holds the controls -- exactly 121 on all five.
* FK controls map to deform joints **by name**: ``FKElbow_L`` drives
  ``Elbow_L``. No translation table exists because none is needed.
* Every limb switcher ``FKIK<Limb>_<Side>`` carries ``startJoint``,
  ``middleJoint`` and ``endJoint`` string attributes naming the chain's base
  names -- the IK chains are declared, not discovered -- plus ``FKIKBlend``
  (0 is FK, 10 is IK).

The record this writes is what the Blender side builds a native control layer
from: custom shapes on the FK bones, real IK constraints on the declared
chains, and a per-limb property standing in for FKIKBlend. Only what was
verified to exist in the scene is written; a convention the rig breaks
becomes an absent entry, never a guessed one.
"""
from __future__ import absolute_import

import maya.cmds as cmds

from .constants import (
    AS_CONTROL_SET,
    AS_DEFORM_SET,
    AS_FK_PREFIX,
    AS_FKIK_BLEND_ATTR,
    AS_FKIK_CHAIN_ATTRS,
    AS_FKIK_PREFIX,
    AS_IK_PREFIX,
    AS_POLE_PREFIX,
)
from .mayautils import attr_exists


def is_advanced_skeleton_scene():
    """True when the scene carries AS's own manifest sets."""
    try:
        return bool(
            cmds.objExists(AS_DEFORM_SET) and cmds.objExists(AS_CONTROL_SET)
        )
    except Exception:
        return False


def as_rig_record():
    """The AS description, or an empty dict for a scene that is not one."""
    if not is_advanced_skeleton_scene():
        return {}
    controls = set(cmds.sets(AS_CONTROL_SET, query=True) or [])
    deform = list(cmds.sets(AS_DEFORM_SET, query=True) or [])
    return {
        "detected": True,
        "deform_set": deform,
        "chains": _chains(controls),
        "fk_controls": _fk_controls(controls),
    }


def _chains(controls):
    """One entry per limb switcher that declares a complete, real chain."""
    chains = []
    for switch in sorted(cmds.ls(AS_FKIK_PREFIX + "*",
                                 type="transform") or []):
        if not attr_exists(switch, AS_FKIK_BLEND_ATTR):
            continue
        side = _side_of(switch)
        if side is None:
            continue
        names = []
        for attr in AS_FKIK_CHAIN_ATTRS:
            if not attr_exists(switch, attr):
                names = []
                break
            try:
                base = str(cmds.getAttr(switch + "." + attr) or "")
            except Exception:
                base = ""
            joint = base + "_" + side if base else ""
            if not joint or not cmds.objExists(joint):
                names = []
                break
            names.append(joint)
        if len(names) != 3:
            continue

        limb = _limb_of(switch)
        entry = {
            "switch": switch,
            "limb": limb,
            "side": side,
            "start": names[0],
            "middle": names[1],
            "end": names[2],
        }
        try:
            entry["blend"] = float(
                cmds.getAttr(switch + "." + AS_FKIK_BLEND_ATTR)
            )
        except Exception:
            entry["blend"] = 10.0
        # The IK and pole controls travel as curves already; naming them here
        # is what lets the importer promote those curves into live targets.
        for key, prefix in (("ik_control", AS_IK_PREFIX),
                            ("pole_control", AS_POLE_PREFIX)):
            name = prefix + limb + "_" + side
            if name in controls and cmds.objExists(name):
                entry[key] = name
        chains.append(entry)
    return chains


def _fk_controls(controls):
    """Verified FK-control-to-joint pairs, by AS's naming convention.

    Verified, not assumed: each pair is only written when both the control
    and the joint it names actually exist. FKExtra and FKIK nodes share the
    prefix and are filtered by the joint check failing for them.
    """
    pairs = []
    for control in sorted(controls):
        if not control.startswith(AS_FK_PREFIX):
            continue
        if control.startswith(AS_FKIK_PREFIX):
            continue
        joint = control[len(AS_FK_PREFIX):]
        try:
            if not cmds.objExists(joint):
                continue
            if cmds.nodeType(joint) != "joint":
                continue
        except Exception:
            continue
        pairs.append({"control": control, "joint": joint})
    return pairs


def _side_of(switch):
    for side in ("L", "R", "M"):
        if switch.endswith("_" + side):
            return side
    return None


def _limb_of(switch):
    stem = switch[len(AS_FKIK_PREFIX):]
    return stem.rsplit("_", 1)[0]
