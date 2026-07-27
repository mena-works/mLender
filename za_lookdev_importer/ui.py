# -*- coding: utf-8 -*-
"""Operators, scene properties and the View3D sidebar panel."""

import bpy

from .constants import (
    BUILD_VERSION,
    LIVELINK_HOST,
    LIVELINK_PORT,
    DEFAULT_LIGHT_POWER_SCALE,
)
from .livelink import get_status, start_listener, stop_listener


SCENE_PROPERTIES = (
    "za_import_scale",
    "za_light_power_scale",
    "za_livelink_host",
    "za_livelink_port",
)


class ZA_OT_start_listener(bpy.types.Operator):
    bl_idname = "za_lookdev.start_listener"
    bl_label = "Start LiveLink"
    bl_description = "Listen for lookdev packages sent from Maya"

    def execute(self, context):
        try:
            start_listener(
                context.scene.za_livelink_host,
                context.scene.za_livelink_port,
            )
        except Exception as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        self.report({"INFO"}, get_status())
        return {"FINISHED"}


class ZA_OT_stop_listener(bpy.types.Operator):
    bl_idname = "za_lookdev.stop_listener"
    bl_label = "Stop LiveLink"
    bl_description = "Stop listening and release the LiveLink port"

    def execute(self, context):
        stop_listener()
        self.report({"INFO"}, get_status())
        return {"FINISHED"}


class ZA_PT_lookdev(bpy.types.Panel):
    bl_label = "Z-A Lookdev Import"
    bl_idname = "ZA_PT_lookdev"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Z-A Exporter"

    def draw(self, context):
        layout = self.layout
        scene = context.scene
        layout.label(text="Build {0}".format(BUILD_VERSION), icon="FILE_REFRESH")
        layout.prop(scene, "za_import_scale", text="FBX Scale")
        layout.prop(scene, "za_light_power_scale", text="Light Power Scale")
        layout.prop(scene, "za_livelink_host", text="Host")
        layout.prop(scene, "za_livelink_port", text="Port")
        row = layout.row(align=True)
        row.operator(ZA_OT_start_listener.bl_idname, icon="PLAY")
        row.operator(ZA_OT_stop_listener.bl_idname, icon="PAUSE")
        layout.label(text=get_status(), icon="INFO")
        layout.separator()
        layout.label(text="New packages replace the complete scene.")
        layout.label(text="Unused data is purged after every import.")


CLASSES = (
    ZA_OT_start_listener,
    ZA_OT_stop_listener,
    ZA_PT_lookdev,
)


def register_ui():
    for cls in CLASSES:
        _safe_register(cls)
    unregister_properties()
    bpy.types.Scene.za_import_scale = bpy.props.FloatProperty(
        name="Z-A FBX Scale",
        default=1.0,
        min=0.000001,
        precision=4,
    )
    bpy.types.Scene.za_light_power_scale = bpy.props.FloatProperty(
        name="Z-A Light Power Scale",
        description=(
            "Artistic multiplier on imported light power. The underlying "
            "conversion is measured and exact, so 1.0 matches the Maya "
            "render. Scales every light uniformly, leaving light-to-light "
            "ratios untouched"
        ),
        default=DEFAULT_LIGHT_POWER_SCALE,
        min=0.0,
        soft_max=100.0,
    )
    bpy.types.Scene.za_livelink_host = bpy.props.StringProperty(
        name="Z-A LiveLink Host",
        default=LIVELINK_HOST,
    )
    bpy.types.Scene.za_livelink_port = bpy.props.IntProperty(
        name="Z-A LiveLink Port",
        default=LIVELINK_PORT,
        min=1,
        max=65535,
    )


def unregister_ui():
    unregister_properties()
    for cls in reversed(CLASSES):
        _safe_unregister(cls)


def unregister_properties():
    for name in SCENE_PROPERTIES:
        if hasattr(bpy.types.Scene, name):
            delattr(bpy.types.Scene, name)


def _safe_register(cls):
    """Register, replacing a class left behind by a previous reload.

    is_registered is the signal that matters: Blender does not expose operator
    classes on bpy.types by name, so a bpy.types lookup silently misses them
    and the reload protection would only ever cover the panel. A failure is
    reported rather than swallowed, because a half registered add-on shows a
    panel whose buttons do nothing.
    """
    if getattr(cls, "is_registered", False):
        try:
            bpy.utils.unregister_class(cls)
        except Exception:
            pass

    stale = getattr(bpy.types, cls.__name__, None)
    if stale is not None and stale is not cls:
        try:
            bpy.utils.unregister_class(stale)
        except Exception:
            pass

    try:
        bpy.utils.register_class(cls)
    except Exception as exc:
        print(
            "Z-A Lookdev: could not register {0}: {1}".format(
                cls.__name__,
                exc,
            )
        )


def _safe_unregister(cls):
    old = getattr(bpy.types, cls.__name__, cls)
    try:
        bpy.utils.unregister_class(old)
    except Exception:
        pass
