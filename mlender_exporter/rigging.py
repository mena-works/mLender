# -*- coding: utf-8 -*-
"""Rigging and constraint discovery."""
from __future__ import absolute_import

import maya.cmds as cmds
from .mayautils import node_label, unique


def scene_joints(mesh_shapes, selected_only=False):
    """The joints the exported meshes are actually bound to, plus their chain.

    Only the influences, which is not the same set as every joint in the
    scene. Measured on a production character: 1014 joints in the file, of
    which 372 drive the skin. Sending all of them made Blender build **132
    armatures** -- FBX makes one out of every group that holds a joint, and a
    rig keeps hundreds of joints inside offset groups that drive nothing.
    One of the 132 was the skeleton; the rest were scaffolding the lookdev
    artist has no use for.

    The chain of joint ancestors comes with them. An influence without its
    parents arrives detached from the skeleton, and the hierarchy is what the
    bind pose is expressed against.
    """
    influences = []
    for shape in mesh_shapes:
        for skin in skin_clusters(shape):
            try:
                found = cmds.skinCluster(skin, query=True, influence=True)
            except Exception:
                continue
            for node in found or []:
                influences.extend(cmds.ls(node, long=True) or [])

    if selected_only:
        # An explicitly selected joint travels even if nothing is bound to
        # it: the user pointing at it is the intent.
        influences.extend(cmds.ls(selection=True, type="joint", long=True)
                          or [])
    if not influences:
        return []
    return unique(_with_joint_ancestors(unique(influences)))


def skeleton_root_records(joints):
    """One record per root joint that sits under a group, for per-frame
    sampling of the joint's world truth alongside its group's.

    The FBX bake drops motion that is not an animCurve on an exported node
    -- measured twice: a group above the skeleton with its own curves is
    folded onto the armature object with its key shape flattened to linear,
    and connection-driven motion, the way Advanced Skeleton's Main drives
    the root, is frozen at its static value. The joint's evaluated world
    per frame is the complete truth; the group's world rides along because
    the importer calibrates the bone-axes convention at the export frame
    against ``group truth @ baked pose``, which both fold failures leave
    clean there.

    A root joint parented to the world has nothing above it to lose, so it
    gets no record.
    """
    records = []
    for joint in joints:
        try:
            parents = cmds.listRelatives(joint, parent=True,
                                         fullPath=True) or []
        except Exception:
            parents = []
        if not parents:
            continue
        try:
            if cmds.nodeType(parents[0]) == "joint":
                continue
        except Exception:
            continue
        records.append({
            "joint": node_label(joint),
            "joint_path": joint,
            "parent_path": parents[0],
        })
    return records


def root_motion_sample(record):
    """The root joint's and its group's world matrices, current frame."""
    joint = cmds.xform(record["joint_path"], query=True, worldSpace=True,
                       matrix=True)
    parent = cmds.xform(record["parent_path"], query=True, worldSpace=True,
                        matrix=True)
    return {
        "matrix": [float(value) for value in joint],
        "parent_matrix": [float(value) for value in parent],
    }


def skin_clusters(shape):
    """The skinClusters upstream of a shape, or an empty list."""
    try:
        history = cmds.listHistory(shape, pruneDagObjects=True) or []
        return cmds.ls(history, type="skinCluster") or []
    except Exception:
        return []


def _with_joint_ancestors(joints):
    """Each joint and every joint above it, so no chain arrives broken."""
    chain = []
    for joint in joints:
        node = joint
        while node:
            chain.append(node)
            try:
                parents = cmds.listRelatives(node, parent=True,
                                             fullPath=True) or []
            except Exception:
                break
            if not parents:
                break
            parent = parents[0]
            try:
                if cmds.nodeType(parent) != "joint":
                    break
            except Exception:
                break
            node = parent
    return chain


def constraint_records(transforms):
    """Records for constraints acting on the given transforms (meshes and joints)."""
    constraint_types = [
        "parentConstraint",
        "pointConstraint",
        "orientConstraint",
        "scaleConstraint",
        "aimConstraint"
    ]
    
    records = []
    
    for transform in transforms:
        for ctype in constraint_types:
            try:
                relatives = cmds.listRelatives(transform, type=ctype, fullPath=True) or []
                for constraint in relatives:
                    targets = cmds.listConnections(constraint + ".target", source=True, destination=False, fullPath=True) or []
                    targets = unique(targets)
                    if not targets:
                        continue
                        
                    # Extract weight attributes
                    attrs = cmds.listAttr(constraint, keyable=True) or []
                    weights = []
                    for attr in attrs:
                        if "W" in attr and attr[-1].isdigit():
                            val = cmds.getAttr(constraint + "." + attr)
                            weights.append(val)
                            
                    properties = {}
                    if ctype == "aimConstraint":
                        for prop in ["aimVector", "upVector", "worldUpVector", "worldUpType"]:
                            try:
                                properties[prop] = cmds.getAttr(constraint + "." + prop)
                            except Exception:
                                pass
                                
                    records.append({
                        "type": ctype,
                        "owner": transform,
                        "targets": targets,
                        "weights": weights,
                        "properties": properties
                    })
            except Exception:
                pass
                
    return records
