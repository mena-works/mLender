# -*- coding: utf-8 -*-
"""Maya window for the lookdev exporter."""
from __future__ import absolute_import

import re

import maya.cmds as cmds

from .constants import (
    DEFAULT_BAKE_RESOLUTION,
    LIVELINK_HOST,
    LIVELINK_PORT,
    PACKAGE_PREFIX,
    TOOL_NAME,
    WINDOW_NAME,
)
from .livelink import send_package
from .package import default_export_folder, export_lookdev


def show_ui():
    if cmds.window(WINDOW_NAME, exists=True):
        cmds.deleteUI(WINDOW_NAME)

    window = cmds.window(
        WINDOW_NAME,
        title=TOOL_NAME,
        sizeable=False,
        widthHeight=(620, 330),
    )
    cmds.columnLayout(
        adjustableColumn=True,
        rowSpacing=10,
        columnAttach=("both", 12),
    )
    cmds.text(label=TOOL_NAME, align="left", font="boldLabelFont")
    cmds.text(
        label=(
            "All renderable scene meshes are exported as FBX. Materials, original "
            "texture paths and current-frame Maya/Redshift lights are sent to Blender."
        ),
        align="left",
        wordWrap=True,
        height=45,
    )

    export_folder = cmds.textFieldButtonGrp(
        label="Export Location",
        text=default_export_folder(),
        buttonLabel="Browse",
        adjustableColumn=2,
        columnWidth3=(120, 390, 75),
    )
    cmds.textFieldButtonGrp(
        export_folder,
        edit=True,
        buttonCommand=lambda *_: browse_folder(export_folder),
    )
    host_field = cmds.textFieldGrp(
        label="Blender Host",
        text=LIVELINK_HOST,
        adjustableColumn=2,
        columnWidth2=(120, 400),
    )
    port_field = cmds.intFieldGrp(
        label="Blender Port",
        value1=LIVELINK_PORT,
        adjustableColumn=2,
        columnWidth2=(120, 120),
    )
    bake_field = cmds.checkBoxGrp(
        label="Bake Procedurals",
        label1="Bake shading networks that have no texture file",
        value1=True,
        columnWidth2=(120, 400),
    )
    bake_resolution_field = cmds.intFieldGrp(
        label="Bake Resolution",
        value1=DEFAULT_BAKE_RESOLUTION,
        adjustableColumn=2,
        columnWidth2=(120, 120),
    )
    animation_field = cmds.checkBoxGrp(
        label="Export Animation",
        label1="Bake the frame range instead of the current frame",
        value1=False,
        columnWidth2=(120, 400),
    )
    # Blank means the playback range, which is what the artist is looking at.
    frame_range_field = cmds.textFieldGrp(
        label="Frame Range",
        text="",
        annotation=(
            "Blank uses the playback range. Otherwise start-end, "
            "optionally with a step: 1-120 or 1-120x2"
        ),
        adjustableColumn=2,
        columnWidth2=(120, 200),
    )
    cmds.text(
        label="Packages: {0}01, {0}02, {0}03...".format(PACKAGE_PREFIX),
        align="left",
    )
    cmds.button(
        label="Send To Blender",
        height=42,
        command=lambda *_: export_from_ui(
            export_folder,
            host_field,
            port_field,
            bake_field,
            bake_resolution_field,
            animation_field,
            frame_range_field,
        ),
    )
    cmds.showWindow(window)
    return window


def parse_frame_range(text):
    """Read "1-120" or "1-120x2" into start, end and step.

    Anything unparseable returns all None, which means the playback range;
    guessing at a half typed range would silently export the wrong frames.
    """
    text = str(text or "").strip().lower().replace(" ", "")
    if not text:
        return None, None, None
    step = None
    if "x" in text:
        text, _sep, step_text = text.partition("x")
        try:
            step = float(step_text)
        except ValueError:
            step = None
    # Split on the last '-' that is not a leading sign, so -10--5 works.
    match = re.match(r"^(-?[\d.]+)[-:](-?[\d.]+)$", text)
    if not match:
        return None, None, None
    try:
        return float(match.group(1)), float(match.group(2)), step
    except ValueError:
        return None, None, None


def export_from_ui(
    export_folder,
    host_field,
    port_field,
    bake_field=None,
    bake_resolution_field=None,
    animation_field=None,
    frame_range_field=None,
):
    """Export, then notify Blender, reporting each failure mode separately.

    A successful export with a failed send is recoverable by hand, so the two
    steps get distinct dialogs.
    """
    output_folder = cmds.textFieldButtonGrp(
        export_folder,
        query=True,
        text=True,
    )
    host = cmds.textFieldGrp(host_field, query=True, text=True).strip()
    port = cmds.intFieldGrp(port_field, query=True, value1=True)
    bake = True
    bake_resolution = DEFAULT_BAKE_RESOLUTION
    if bake_field is not None:
        bake = bool(cmds.checkBoxGrp(bake_field, query=True, value1=True))
    if bake_resolution_field is not None:
        bake_resolution = cmds.intFieldGrp(
            bake_resolution_field, query=True, value1=True
        )

    export_animation = False
    if animation_field is not None:
        export_animation = bool(
            cmds.checkBoxGrp(animation_field, query=True, value1=True)
        )
    frame_start = frame_end = frame_step = None
    if frame_range_field is not None:
        frame_start, frame_end, frame_step = parse_frame_range(
            cmds.textFieldGrp(frame_range_field, query=True, text=True)
        )

    try:
        result = export_lookdev(
            output_folder,
            bake_procedurals=bake,
            bake_resolution=bake_resolution,
            export_animation=export_animation,
            frame_start=frame_start,
            frame_end=frame_end,
            frame_step=frame_step,
        )
    except Exception as exc:
        cmds.warning("Z-A Lookdev export failed: {0}".format(exc))
        cmds.confirmDialog(
            title="Export Failed",
            message=str(exc),
            button=["OK"],
            icon="critical",
        )
        return

    try:
        send_package(result, host, port)
    except Exception as exc:
        cmds.warning("LiveLink send failed: {0}".format(exc))
        cmds.confirmDialog(
            title="Export Complete, LiveLink Failed",
            message=(
                "FBX and JSON were exported, but Blender could not be notified.\n\n"
                "{0}\n\nPackage:\n{1}"
            ).format(exc, result["package_folder"]),
            button=["OK"],
            icon="warning",
        )
        return

    cmds.confirmDialog(
        title="Z-A Lookdev Export Complete",
        message=(
            "Meshes: {0}\nLights: {1}\nCameras: {2}\nBaked textures: {3}\n"
            "Frames: {7}\n\nPackage:\n{4}\n\nFBX:\n{5}{6}"
        ).format(
            result["mesh_count"],
            result["light_count"],
            result["camera_count"],
            result["baked_texture_count"],
            result["package_folder"],
            result["fbx_path"],
            _warning_summary(result.get("warnings")),
            result.get("frame_count", 1),
        ),
        button=["OK"],
        icon="information",
    )


def _warning_summary(warnings):
    """Surface export warnings in the dialog rather than only the log."""
    warnings = list(warnings or [])
    if not warnings:
        return ""
    shown = warnings[:5]
    text = "\n\nWarnings:\n" + "\n".join("- " + item for item in shown)
    if len(warnings) > len(shown):
        text += "\n- ...and {0} more".format(len(warnings) - len(shown))
    return text


def browse_folder(field):
    result = cmds.fileDialog2(
        dialogStyle=2,
        fileMode=3,
        caption="Choose Z-A Lookdev Export Location",
    )
    if result:
        cmds.textFieldButtonGrp(field, edit=True, text=result[0])
