# -*- coding: utf-8 -*-
"""Operators, scene properties and the View3D sidebar panel."""

import bpy

from .constants import (
    BUILD_VERSION,
    LIVELINK_HOST,
    LIVELINK_PORT,
    DEFAULT_LIGHT_POWER_SCALE,
)
from .asrig import as_armatures, select_chain, select_fk_bones
from .livelink import get_status, start_listener, stop_listener
from .merge import count_stale_objects, remove_stale_objects


SCENE_PROPERTIES = (
    "ml_import_scale",
    "ml_light_power_scale",
    "ml_livelink_host",
    "ml_livelink_port",
)


class ML_OT_start_listener(bpy.types.Operator):
    bl_idname = "mlender.start_listener"
    bl_label = "Start LiveLink"
    bl_description = "Listen for scene packages sent from Maya"

    def execute(self, context):
        try:
            start_listener(
                context.scene.ml_livelink_host,
                context.scene.ml_livelink_port,
            )
        except Exception as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        self.report({"INFO"}, get_status())
        return {"FINISHED"}


class ML_OT_stop_listener(bpy.types.Operator):
    bl_idname = "mlender.stop_listener"
    bl_label = "Stop LiveLink"
    bl_description = "Stop listening and release the LiveLink port"

    def execute(self, context):
        stop_listener()
        self.report({"INFO"}, get_status())
        return {"FINISHED"}


class ML_OT_remove_stale(bpy.types.Operator):
    """Delete what a merge found no longer in the package.

    A separate button on purpose. An import arriving over a socket is no
    place to destroy work unasked, so a merge marks and counts these and
    the decision stays with the user.
    """
    bl_idname = "mlender.remove_stale"
    bl_label = "Remove Stale Objects"
    bl_description = (
        "Delete objects an earlier import created that the last package "
        "no longer contains"
    )
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        removed = remove_stale_objects()
        self.report({"INFO"}, "Removed {0} stale object(s).".format(removed))
        return {"FINISHED"}


def _chain_label(chain):
    """The manifest's ready-made label, or limb+side for one written by
    an older build."""
    label = chain.get("label") or ""
    if label:
        return label
    return "{0} {1}".format(chain.get("limb") or "",
                            chain.get("side") or "").strip()


class ML_OT_as_select_chain(bpy.types.Operator):
    bl_idname = "mlender.as_select_chain"
    bl_label = "Select Limb"
    bl_description = "Select this limb's bones and its IK/pole controls"
    bl_options = {"REGISTER", "UNDO"}

    armature_name: bpy.props.StringProperty()
    # The FKIK property name is the chain's identity: limb and side repeat
    # when two referenced rigs share one armature, the property never does.
    prop: bpy.props.StringProperty()

    def execute(self, context):
        armature = bpy.data.objects.get(self.armature_name)
        manifest = armature.get("ml_as_rig") if armature else None
        if not manifest:
            self.report({"ERROR"}, "No AS rig on that armature.")
            return {"CANCELLED"}
        for chain in manifest.get("chains") or []:
            if chain.get("prop") == self.prop:
                count = select_chain(armature, chain)
                self.report(
                    {"INFO"},
                    "Selected {0} item(s) for {1}.".format(
                        count, _chain_label(chain),
                    ),
                )
                return {"FINISHED"}
        self.report({"ERROR"}, "Chain {0} not found.".format(self.prop))
        return {"CANCELLED"}


class ML_OT_as_select_fk(bpy.types.Operator):
    bl_idname = "mlender.as_select_fk"
    bl_label = "Select FK Controls"
    bl_description = "Select every FK-dressed bone of this armature"
    bl_options = {"REGISTER", "UNDO"}

    armature_name: bpy.props.StringProperty()

    def execute(self, context):
        armature = bpy.data.objects.get(self.armature_name)
        if not armature or not armature.get("ml_as_rig"):
            self.report({"ERROR"}, "No AS rig on that armature.")
            return {"CANCELLED"}
        count = select_fk_bones(armature)
        self.report({"INFO"}, "Selected {0} FK bone(s).".format(count))
        return {"FINISHED"}


class ML_PT_as_rig(bpy.types.Panel):
    """The functional stand-in for the AS picker: per-limb FK/IK sliders
    (they drive the constraint influences built at import) and one-click
    limb selection."""
    bl_label = "AS Rig"
    bl_idname = "ML_PT_as_rig"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "mLender"

    @classmethod
    def poll(cls, context):
        return bool(as_armatures())

    def draw(self, context):
        layout = self.layout
        rigs = as_armatures()
        for armature in rigs:
            box = layout.box()
            if len(rigs) > 1:
                box.label(text=armature.name, icon="ARMATURE_DATA")
            manifest = armature.get("ml_as_rig") or {}
            for chain in manifest.get("chains") or []:
                prop = chain.get("prop") or ""
                label = _chain_label(chain)
                row = box.row(align=True)
                op = row.operator(
                    ML_OT_as_select_chain.bl_idname,
                    text="",
                    icon="RESTRICT_SELECT_OFF",
                )
                op.armature_name = armature.name
                op.prop = prop
                if prop in armature.keys():
                    row.prop(
                        armature,
                        '["{0}"]'.format(prop),
                        text=label,
                        slider=True,
                    )
                else:
                    row.label(text=label)
            op = box.operator(ML_OT_as_select_fk.bl_idname, icon="BONE_DATA")
            op.armature_name = armature.name


class ML_PT_lookdev(bpy.types.Panel):
    bl_label = "mLender Import"
    bl_idname = "ML_PT_lookdev"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "mLender"

    def draw(self, context):
        layout = self.layout
        scene = context.scene
        layout.label(text="Build {0}".format(BUILD_VERSION), icon="FILE_REFRESH")
        layout.prop(scene, "ml_import_mode", text="Mode")
        layout.prop(scene, "ml_import_scale", text="FBX Scale")
        layout.prop(scene, "ml_light_power_scale", text="Light Power Scale")
        layout.prop(scene, "ml_livelink_host", text="Host")
        layout.prop(scene, "ml_livelink_port", text="Port")
        row = layout.row(align=True)
        row.operator(ML_OT_start_listener.bl_idname, icon="PLAY")
        row.operator(ML_OT_stop_listener.bl_idname, icon="PAUSE")
        layout.label(text=get_status(), icon="INFO")
        stale = count_stale_objects()
        if stale:
            box = layout.box()
            box.label(
                text="{0} object(s) left the package.".format(stale),
                icon="ERROR",
            )
            box.operator(ML_OT_remove_stale.bl_idname, icon="TRASH")
        layout.separator()
        if scene.ml_import_mode == "REPLACE":
            layout.label(text="Replace: new packages wipe the scene.")
        elif scene.ml_import_mode == "MERGE":
            layout.label(text="Merge: imported objects are updated in")
            layout.label(text="place; your own objects are untouched.")
        else:
            layout.label(text="Add: each package lands in its own")
            layout.label(text="collection and nothing is updated.")


CLASSES = (
    ML_OT_start_listener,
    ML_OT_remove_stale,
    ML_OT_stop_listener,
    ML_OT_as_select_chain,
    ML_OT_as_select_fk,
    ML_PT_lookdev,
    ML_PT_as_rig,
)


def register_ui():
    for cls in CLASSES:
        _safe_register(cls)
    unregister_properties()
    bpy.types.Scene.ml_import_mode = bpy.props.EnumProperty(
        name="Import Mode",
        description="What a new package does to the current scene",
        items=(
            ("REPLACE", "Replace",
             "Wipe the scene and rebuild it from the package"),
            ("MERGE", "Merge",
             "Update objects an earlier import made, leave your own alone"),
            ("ADD", "Add",
             "Bring the package in beside what is already there"),
        ),
        default="REPLACE",
    )
    bpy.types.Scene.ml_import_scale = bpy.props.FloatProperty(
        name="FBX Scale",
        default=1.0,
        min=0.000001,
        precision=4,
    )
    bpy.types.Scene.ml_light_power_scale = bpy.props.FloatProperty(
        name="Light Power Scale",
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
    bpy.types.Scene.ml_livelink_host = bpy.props.StringProperty(
        name="LiveLink Host",
        default=LIVELINK_HOST,
    )
    bpy.types.Scene.ml_livelink_port = bpy.props.IntProperty(
        name="LiveLink Port",
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
            "mLender: could not register {0}: {1}".format(
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
