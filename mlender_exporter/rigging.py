# -*- coding: utf-8 -*-
"""Rigging and constraint discovery."""
from __future__ import absolute_import

import maya.cmds as cmds
from .mayautils import unique


def scene_joints(mesh_shapes, selected_only=False):
    """Find joints bound to the given mesh shapes and selected/all joints."""
    joints = []
    
    for shape in mesh_shapes:
        try:
            history = cmds.listHistory(shape, pruneDagObjects=True) or []
            skin_clusters = [node for node in history if cmds.nodeType(node) == "skinCluster"]
            for skin in skin_clusters:
                influences = cmds.skinCluster(skin, query=True, influence=True) or []
                joints.extend(influences)
        except Exception:
            pass
            
    if selected_only:
        selection = cmds.ls(selection=True, type="joint", long=True) or []
        joints.extend(selection)
    else:
        all_joints = cmds.ls(type="joint", long=True) or []
        joints.extend(all_joints)
        
    return unique(joints)


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
