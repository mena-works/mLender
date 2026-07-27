# -*- coding: utf-8 -*-
"""FBX export through Maya's MEL FBX commands.

Cameras and lights are deliberately excluded; lights travel through JSON so
Blender can rebuild them natively, and cameras are out of scope for lookdev.
"""
from __future__ import absolute_import

import maya.cmds as cmds
import maya.mel as mel

from .mayautils import mel_eval_safe, mel_path


FBX_EXPORT_OPTIONS = (
    "FBXResetExport;",
    "FBXExportCameras -v false;",
    "FBXExportLights -v false;",
    "FBXExportEmbeddedTextures -v false;",
    "FBXExportInputConnections -v false;",
    "FBXExportBakeComplexAnimation -v false;",
    "FBXExportSkins -v true;",
    "FBXExportShapes -v true;",
    "FBXExportSmoothingGroups -v true;",
)


def export_fbx(mesh_transforms, fbx_path):
    """Export the given transforms, restoring the user's selection afterwards."""
    load_fbx_plugin()
    previous_selection = cmds.ls(selection=True, long=True) or []
    try:
        cmds.select(mesh_transforms, replace=True)
        for option in FBX_EXPORT_OPTIONS:
            mel_eval_safe(option)
        mel.eval('FBXExport -f "{0}" -s;'.format(mel_path(fbx_path)))
    finally:
        if previous_selection:
            cmds.select(previous_selection, replace=True)
        else:
            cmds.select(clear=True)


def load_fbx_plugin():
    try:
        if cmds.pluginInfo("fbxmaya", query=True, loaded=True):
            return
    except Exception:
        pass
    try:
        cmds.loadPlugin("fbxmaya")
    except Exception:
        cmds.loadPlugin("fbxmaya.mll")
