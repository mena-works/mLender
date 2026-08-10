# -*- coding: utf-8 -*-
"""Render passes and AOV extraction."""
from __future__ import absolute_import

import maya.cmds as cmds


def scene_aovs():
    """Extract enabled render passes/AOVs for Arnold and Redshift."""
    records = []
    
    # Arnold AOVs
    try:
        arnold_aovs = cmds.ls(type="aiAOV") or []
        for aov in arnold_aovs:
            # Check if aov is enabled
            enabled = True
            try:
                enabled = cmds.getAttr(aov + ".enabled")
            except Exception:
                pass
            
            if enabled:
                name = ""
                try:
                    name = cmds.getAttr(aov + ".name")
                except Exception:
                    name = aov
                    
                records.append({
                    "engine": "arnold",
                    "name": name,
                    "type": cmds.getAttr(aov + ".type") if cmds.attributeQuery("type", node=aov, exists=True) else 5 # 5=RGBA usually
                })
    except Exception:
        pass
        
    # Redshift AOVs
    try:
        rs_aovs = cmds.ls(type="RedshiftAOV") or []
        for aov in rs_aovs:
            enabled = True
            try:
                enabled = cmds.getAttr(aov + ".enabled")
            except Exception:
                pass
                
            if enabled:
                aov_type = ""
                try:
                    aov_type = cmds.getAttr(aov + ".aovType")
                except Exception:
                    pass
                name = ""
                try:
                    name = cmds.getAttr(aov + ".name")
                except Exception:
                    name = aov
                    
                records.append({
                    "engine": "redshift",
                    "name": name,
                    "type": aov_type
                })
    except Exception:
        pass
        
    return records
