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


def animation_options(animation):
    """Bake the frame range into the FBX when the export asked for animation.

    Mesh animation rides the FBX rather than the JSON: that is what the format
    is for, and it is the only path that carries deformers. Lights and cameras
    are sampled into JSON instead, because they are rebuilt from scratch.
    """
    if not animation or not animation.get("enabled"):
        return ("FBXExportBakeComplexAnimation -v false;",)
    return (
        "FBXExportBakeComplexAnimation -v true;",
        "FBXExportBakeComplexStart -v {0};".format(
            int(round(float(animation.get("start") or 0)))
        ),
        "FBXExportBakeComplexEnd -v {0};".format(
            int(round(float(animation.get("end") or 0)))
        ),
        "FBXExportBakeComplexStep -v {0};".format(
            max(1, int(round(float(animation.get("step") or 1))))
        ),
    )


def export_fbx(mesh_transforms, fbx_path, animation=None):
    """Export the given transforms, restoring the user's selection afterwards."""
    load_fbx_plugin()
    previous_selection = cmds.ls(selection=True, long=True) or []
    try:
        cmds.select(mesh_transforms, replace=True)
        for option in FBX_EXPORT_OPTIONS:
            mel_eval_safe(option)
        for option in animation_options(animation):
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
