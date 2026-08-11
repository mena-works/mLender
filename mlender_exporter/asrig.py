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


def rig_namespaces():
    """Namespace prefixes ('' or 'Chubs:') that carry both AS sets.

    A referenced character keeps its manifest sets inside its namespace, so
    the bare names never exist and a plain objExists misses the rig entirely
    -- measured, both on one referenced rig and on two. ls with recursive
    finds the sets wherever they live; the prefix is everything before the
    set's own name, which keeps nested namespaces ('a:b:') intact.
    """
    prefixes = []
    try:
        found = cmds.ls(AS_DEFORM_SET, recursive=True) or []
    except Exception:
        return prefixes
    for deform in found:
        prefix = deform[:-len(AS_DEFORM_SET)]
        if cmds.objExists(prefix + AS_CONTROL_SET):
            prefixes.append(prefix)
    return sorted(prefixes)


def is_advanced_skeleton_scene():
    """True when any namespace in the scene carries AS's manifest sets."""
    return bool(rig_namespaces())


def as_rig_records():
    """One AS description per rig in the scene, possibly none.

    Every name written is fully namespace-qualified, because FBX carries the
    namespace into Blender verbatim, colon included -- measured on 5.2: the
    bone arrives as 'NS:probeRoot'. Qualified names on both sides means no
    translation table anywhere between them.
    """
    records = []
    for prefix in rig_namespaces():
        controls = set(
            cmds.sets(prefix + AS_CONTROL_SET, query=True) or []
        )
        deform = list(cmds.sets(prefix + AS_DEFORM_SET, query=True) or [])
        records.append({
            "detected": True,
            "namespace": prefix,
            "deform_set": deform,
            "chains": _chains(prefix, controls),
            "fk_controls": _fk_controls(prefix, controls),
        })
    return records


def _chains(prefix, controls):
    """One entry per limb switcher that declares a complete, real chain."""
    chains = []
    for switch in sorted(cmds.ls(prefix + AS_FKIK_PREFIX + "*",
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
            # The switcher declares base names; the joints live beside it
            # in the same namespace.
            joint = prefix + base + "_" + side if base else ""
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
        for key, control_prefix in (("ik_control", AS_IK_PREFIX),
                                    ("pole_control", AS_POLE_PREFIX)):
            name = prefix + control_prefix + limb + "_" + side
            if name in controls and cmds.objExists(name):
                entry[key] = name
        chains.append(entry)
    return chains


def _fk_controls(prefix, controls):
    """Verified FK-control-to-joint pairs, by AS's naming convention.

    Verified, not assumed: each pair is only written when both the control
    and the joint it names actually exist. FKExtra and FKIK nodes share the
    prefix and are filtered by the joint check failing for them.
    """
    pairs = []
    for control in sorted(controls):
        short = _short_name(control)
        if not short.startswith(AS_FK_PREFIX):
            continue
        if short.startswith(AS_FKIK_PREFIX):
            continue
        joint = prefix + short[len(AS_FK_PREFIX):]
        try:
            if not cmds.objExists(joint):
                continue
            if cmds.nodeType(joint) != "joint":
                continue
        except Exception:
            continue
        pairs.append({"control": control, "joint": joint})
    return pairs


def _short_name(node):
    return node.rsplit("|", 1)[-1].rsplit(":", 1)[-1]


def _side_of(switch):
    for side in ("L", "R", "M"):
        if switch.endswith("_" + side):
            return side
    return None


def _limb_of(switch):
    stem = _short_name(switch)[len(AS_FKIK_PREFIX):]
    return stem.rsplit("_", 1)[0]
