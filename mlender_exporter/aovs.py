# -*- coding: utf-8 -*-
"""Render passes and AOV extraction."""
from __future__ import absolute_import

import maya.cmds as cmds


# Arnold's AI_TYPE values for an AOV, measured on MtoA 5.4.8 rather than
# guessed. Only RGB is needed as a fallback, but the set is written down
# because the exporter records this number raw and a reader needs it.
ARNOLD_AOV_TYPE_FLOAT = 4
ARNOLD_AOV_TYPE_RGB = 5
ARNOLD_AOV_TYPE_RGBA = 6
ARNOLD_AOV_TYPE_VECTOR = 7


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
                    
                # Arnold's AOV type is its AI_TYPE enum. The values below
                # were read off a live MtoA session rather than assumed; the
                # comment here used to say "5=RGBA usually" and that was
                # wrong. Measured: Z=4, N=7, a custom AOV=6, everything else
                # in the fixture=5.
                #
                #     4  FLOAT    single channel, e.g. Z
                #     5  RGB      most colour AOVs
                #     6  RGBA     what an unrecognised name defaults to
                #     7  VECTOR   e.g. N
                #
                # The fallback is RGB, which is what the common case measured
                # as; it is only reached when the attribute is missing.
                records.append({
                    "engine": "arnold",
                    "name": name,
                    "type": cmds.getAttr(aov + ".type") if cmds.attributeQuery("type", node=aov, exists=True) else ARNOLD_AOV_TYPE_RGB
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
