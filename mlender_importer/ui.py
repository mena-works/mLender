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
import os
import webbrowser

from .livelink import get_status, start_listener, stop_listener


# A panel with hundreds of rows stops the UI; the report file has
# all of them.
PANEL_WARNING_LIMIT = 25


class ML_WarningItem(bpy.types.PropertyGroup):
    text: bpy.props.StringProperty(name="Warning", default="")

from .merge import count_stale_objects, remove_stale_objects
from .outliner import (
    MAX_ROWS,
    delete_objects,
    is_open,
    move_object,
    object_icon,
    outliner_rows,
    parent_objects,
    reset_order,
    reveal_object,
    select_range,
    set_open,
    unparent_objects,
)
from .grouping import (
    CLASSES as GROUPING_CLASSES,
    ML_OT_group_selected,
    ML_OT_ungroup,
    register_menus,
    unregister_menus,
)
from .overlay import (
    CLASSES as OVERLAY_CLASSES,
    ML_OT_overlay_outliner,
    ML_OT_overlay_rename,
    overlay_running,
)


SCENE_PROPERTIES = (
    "ml_import_scale",
    "ml_light_power_scale",
    "ml_livelink_host",
    "ml_livelink_port",
    "ml_outliner_search",
    "ml_warnings",
    "ml_report_path",
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


class ML_OT_outliner_toggle(bpy.types.Operator):
    bl_idname = "mlender.outliner_toggle"
    bl_label = "Expand or Collapse"
    bl_description = "Fold or unfold this branch of the outliner"

    name: bpy.props.StringProperty()

    def execute(self, context):
        obj = bpy.data.objects.get(self.name)
        if obj is None:
            return {"CANCELLED"}
        set_open(obj, not is_open(obj))
        return {"FINISHED"}


class ML_OT_outliner_select(bpy.types.Operator):
    bl_idname = "mlender.outliner_select"
    bl_label = "Select"
    bl_description = (
        "Select this object. Ctrl adds or removes it, Shift takes the "
        "range from the last one clicked"
    )
    bl_options = {"REGISTER", "UNDO"}

    name: bpy.props.StringProperty()

    def invoke(self, context, event):
        # The one place a panel button can read modifiers: Maya's
        # click / Ctrl-click / Shift-click selection, with no keymap.
        self.mode = ("toggle" if event.ctrl
                     else "range" if event.shift else "replace")
        return self.execute(context)

    def execute(self, context):
        obj = bpy.data.objects.get(self.name)
        if obj is None:
            return {"CANCELLED"}
        mode = getattr(self, "mode", "replace")
        search = getattr(context.scene, "ml_outliner_search", "")
        active = context.view_layer.objects.active
        try:
            if mode == "toggle":
                obj.select_set(not obj.select_get())
            elif mode == "range" and active is not None:
                for other in context.selected_objects:
                    other.select_set(False)
                for member in select_range(context.scene, active, obj,
                                           search):
                    member.select_set(True)
            else:
                for other in context.selected_objects:
                    other.select_set(False)
                obj.select_set(True)
            context.view_layer.objects.active = obj
        except RuntimeError:
            # An object hidden from the view layer cannot be selected;
            # saying so beats a button that silently does nothing.
            self.report({"WARNING"},
                        "{0} is not selectable here.".format(self.name))
            return {"CANCELLED"}
        return {"FINISHED"}


class ML_OT_outliner_reveal(bpy.types.Operator):
    bl_idname = "mlender.outliner_reveal"
    bl_label = "Reveal Active"
    bl_description = (
        "Unfold the branches above the active object so the tree shows it"
    )
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        active = context.view_layer.objects.active
        if active is None:
            self.report({"WARNING"}, "No active object.")
            return {"CANCELLED"}
        reveal_object(active)
        self.report({"INFO"}, "Showing {0}.".format(active.name))
        return {"FINISHED"}


class ML_OT_outliner_delete(bpy.types.Operator):
    bl_idname = "mlender.outliner_delete"
    bl_label = "Delete Selected"
    bl_description = "Delete the selected objects and everything under them"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        removed = delete_objects(list(context.selected_objects))
        if not removed:
            self.report({"WARNING"}, "Nothing selected to delete.")
            return {"CANCELLED"}
        self.report({"INFO"}, "Deleted {0} object(s).".format(removed))
        return {"FINISHED"}


class ML_OT_outliner_reset_order(bpy.types.Operator):
    bl_idname = "mlender.outliner_reset_order"
    bl_label = "Reset Order"
    bl_description = (
        "Drop the manual order and go back to sorting by name. Acts on the "
        "selection, or on everything when nothing is selected"
    )
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        targets = list(context.selected_objects) or list(
            context.scene.objects)
        cleared = reset_order(targets)
        self.report({"INFO"}, "Reset {0} object(s).".format(cleared))
        return {"FINISHED"}


class ML_MT_outliner(bpy.types.Menu):
    """The overlay's right-click menu."""
    bl_idname = "ML_MT_outliner"
    bl_label = "Outliner"

    def draw(self, context):
        layout = self.layout
        layout.operator(ML_OT_overlay_rename.bl_idname, icon="OUTLINER_DATA_FONT")
        layout.operator(ML_OT_outliner_reveal.bl_idname, icon="VIEWZOOM")
        layout.separator()
        layout.operator(ML_OT_outliner_unparent.bl_idname, icon="X")
        layout.operator(ML_OT_outliner_reset_order.bl_idname,
                        icon="SORTALPHA")
        layout.separator()
        layout.operator(ML_OT_outliner_delete.bl_idname, icon="TRASH")


class ML_OT_outliner_move(bpy.types.Operator):
    bl_idname = "mlender.outliner_move"
    bl_label = "Move in Outliner"
    bl_description = (
        "Move the active object one step among its siblings; the order is "
        "saved with the file"
    )
    bl_options = {"REGISTER", "UNDO"}

    direction: bpy.props.IntProperty(default=1)

    def execute(self, context):
        obj = context.view_layer.objects.active
        if obj is None:
            self.report({"WARNING"}, "No active object to move.")
            return {"CANCELLED"}
        if not move_object(context.scene, obj, self.direction):
            return {"CANCELLED"}
        return {"FINISHED"}


class ML_OT_outliner_parent(bpy.types.Operator):
    bl_idname = "mlender.outliner_parent"
    bl_label = "Parent Selected Here"
    bl_description = (
        "Parent the selected objects under this one, keeping their world "
        "positions -- Maya's middle-drag, as a click"
    )
    bl_options = {"REGISTER", "UNDO"}

    name: bpy.props.StringProperty()

    def execute(self, context):
        target = bpy.data.objects.get(self.name)
        if target is None:
            return {"CANCELLED"}
        moved = parent_objects(target, list(context.selected_objects))
        if not moved:
            self.report({"WARNING"}, "Nothing could be parented there.")
            return {"CANCELLED"}
        set_open(target, True)
        self.report({"INFO"}, "Parented {0} object(s) under {1}.".format(
            moved, target.name))
        return {"FINISHED"}


class ML_OT_outliner_unparent(bpy.types.Operator):
    bl_idname = "mlender.outliner_unparent"
    bl_label = "Unparent"
    bl_description = (
        "Clear the selected objects' parents, keeping their world positions"
    )
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        freed = unparent_objects(list(context.selected_objects))
        if not freed:
            self.report({"WARNING"}, "Nothing selected has a parent.")
            return {"CANCELLED"}
        self.report({"INFO"}, "Unparented {0} object(s).".format(freed))
        return {"FINISHED"}


class ML_PT_outliner(bpy.types.Panel):
    """The Maya outliner, as far as a panel can be one: a single transform
    tree in manual order, click / shift-click selection, one-click
    parenting, per-row visibility. No editor types or drag-and-drop exist
    for Python add-ons, so moving things is buttons."""
    bl_label = "Outliner (Maya)"
    bl_idname = "ML_PT_outliner"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "mLender"
    bl_options = {"DEFAULT_CLOSED"}

    def draw(self, context):
        layout = self.layout
        scene = context.scene

        header = layout.row(align=True)
        header.prop(scene, "ml_outliner_search", text="", icon="VIEWZOOM")
        header.operator(ML_OT_outliner_move.bl_idname, text="",
                        icon="TRIA_UP").direction = -1
        header.operator(ML_OT_outliner_move.bl_idname, text="",
                        icon="TRIA_DOWN").direction = 1
        # The overlay carries the gestures a panel cannot: real drag to
        # parent or reorder, double-click rename, drawn over this viewport.
        header.operator(ML_OT_overlay_outliner.bl_idname, text="",
                        icon="WINDOW", depress=overlay_running())

        groups = layout.row(align=True)
        groups.operator(ML_OT_group_selected.bl_idname, icon="OUTLINER_OB_EMPTY")
        groups.operator(ML_OT_ungroup.bl_idname, text="", icon="X")

        actions = layout.row(align=True)
        actions.operator(ML_OT_outliner_reveal.bl_idname, text="",
                         icon="ZOOM_SELECTED")
        actions.operator(ML_OT_overlay_rename.bl_idname, text="",
                         icon="OUTLINER_DATA_FONT")
        actions.operator(ML_OT_outliner_unparent.bl_idname, text="",
                         icon="X")
        actions.operator(ML_OT_outliner_reset_order.bl_idname, text="",
                         icon="SORTALPHA")
        actions.operator(ML_OT_outliner_delete.bl_idname, text="",
                         icon="TRASH")

        rows = outliner_rows(scene, scene.ml_outliner_search)
        selected = context.selected_objects
        column = layout.column(align=True)
        for obj, depth, has_children, opened in rows[:MAX_ROWS]:
            row = column.row(align=True)
            if depth:
                row.separator(factor=1.4 * depth)
            if has_children:
                row.operator(
                    ML_OT_outliner_toggle.bl_idname,
                    text="",
                    icon="TRIA_DOWN" if opened else "TRIA_RIGHT",
                    emboss=False,
                ).name = obj.name
            else:
                row.label(text="", icon="BLANK1")
            row.operator(
                ML_OT_outliner_select.bl_idname,
                text=obj.name,
                icon=object_icon(obj),
                depress=obj.select_get(),
            ).name = obj.name
            if selected and (len(selected) > 1 or selected[0] is not obj):
                row.operator(
                    ML_OT_outliner_parent.bl_idname,
                    text="",
                    icon="FILE_PARENT",
                ).name = obj.name
            row.prop(obj, "hide_viewport", text="", emboss=False)
            row.prop(obj, "hide_render", text="", emboss=False)
        if len(rows) > MAX_ROWS:
            column.label(
                text="{0} more row(s) -- narrow it with the search.".format(
                    len(rows) - MAX_ROWS),
                icon="INFO",
            )


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


class ML_OT_open_report(bpy.types.Operator):
    """Open the import report the last package wrote."""

    bl_idname = "mlender.open_report"
    bl_label = "Open Report"
    bl_description = "Open the import report written beside the package"

    def execute(self, context):
        path = context.scene.ml_report_path
        if not path or not os.path.isfile(path):
            self.report({"WARNING"}, "No report file from the last import.")
            return {"CANCELLED"}
        try:
            webbrowser.open(path)
        except Exception as exc:
            self.report({"ERROR"}, "Could not open it: {0}".format(exc))
            return {"CANCELLED"}
        return {"FINISHED"}


class ML_PT_warnings(bpy.types.Panel):
    """What the last import did not carry.

    A count in a status line is not readable and the System Console scrolls,
    so the warnings live here where they can be scrolled and read. The list is
    capped because a panel with six hundred rows stops the UI; the full set is
    always in the report file, which is what the button opens.
    """

    bl_label = "Last Import Warnings"
    bl_idname = "ML_PT_warnings"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "mLender"
    bl_parent_id = "ML_PT_lookdev"
    bl_options = {"DEFAULT_CLOSED"}

    def draw(self, context):
        layout = self.layout
        scene = context.scene
        warnings = list(scene.ml_warnings)
        if not warnings:
            layout.label(text="No warnings from the last import.",
                         icon="CHECKMARK")
        else:
            layout.label(
                text="{0} warning(s)".format(len(warnings)), icon="ERROR"
            )
            box = layout.box()
            column = box.column(align=True)
            for item in warnings[:PANEL_WARNING_LIMIT]:
                column.label(text=item.text[:90])
            if len(warnings) > PANEL_WARNING_LIMIT:
                column.label(text="... and {0} more, in the report".format(
                    len(warnings) - PANEL_WARNING_LIMIT))
        if scene.ml_report_path:
            layout.operator(ML_OT_open_report.bl_idname, icon="TEXT")


CLASSES = (
    ML_WarningItem,
    ML_OT_start_listener,
    ML_OT_remove_stale,
    ML_OT_stop_listener,
    ML_OT_as_select_chain,
    ML_OT_as_select_fk,
    ML_OT_outliner_toggle,
    ML_OT_outliner_select,
    ML_OT_outliner_move,
    ML_OT_outliner_parent,
    ML_OT_outliner_unparent,
    ML_OT_outliner_reveal,
    ML_OT_outliner_delete,
    ML_OT_outliner_reset_order,
    ML_MT_outliner,
    ML_OT_open_report,
    ML_PT_lookdev,
    ML_PT_warnings,
    ML_PT_as_rig,
    ML_PT_outliner,
) + OVERLAY_CLASSES + GROUPING_CLASSES


def register_ui():
    for cls in CLASSES:
        _safe_register(cls)
    # After the classes: the menu entries name operators that have to
    # exist by the time a menu is drawn.
    unregister_menus()
    register_menus()
    unregister_properties()
    # The last import's warnings, so the panel can list them and the user
    # never has to read the System Console to find out what did not travel.
    bpy.types.Scene.ml_warnings = bpy.props.CollectionProperty(
        type=ML_WarningItem
    )
    bpy.types.Scene.ml_report_path = bpy.props.StringProperty(
        name="Report", default="",
        description="The import report written beside the package",
    )
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
    bpy.types.Scene.ml_outliner_search = bpy.props.StringProperty(
        name="Outliner Search",
        description=(
            "Filter the Maya-style outliner by name; matches are shown "
            "flat, wherever they hide in the tree"
        ),
        default="",
        options={"TEXTEDIT_UPDATE"},
    )


def unregister_ui():
    unregister_menus()
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
