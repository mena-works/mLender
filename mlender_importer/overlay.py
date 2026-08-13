# -*- coding: utf-8 -*-
"""A GPU-drawn outliner overlay: the Maya feel the panel API cannot give.

The panel outliner stops where Blender's layout widgets stop: no
drag-and-drop, no double-click, no in-place editing. This draws its own
tree into the 3D viewport with the ``gpu`` module and runs a modal
operator over raw mouse and key events, so the missing gestures exist:

* click selects, Ctrl-click toggles, Shift-click takes the range;
* double-click renames **in the row**, with a caret, the way Maya does;
* dragging a row onto another parents it there, dragging *between* rows
  reorders, dropping on the header unparents -- all with the world
  transform kept;
* the eye and camera squares on each row hide it in the viewport and in
  renders;
* right-click opens the actions menu, ``F`` reveals the active object,
  ``X`` deletes the selection, the wheel scrolls, and the card itself is
  moved by its header and resized by its corner.

Every change goes through ``ed.undo_push``, so Ctrl+Z steps back through
drags the same way it does through anything else -- measured, a parenting
change made this way is restored by one undo.

It shares its tree, order and fold state with the panel outliner
(``outliner.py``), so the two views never disagree. Geometry and
hit-testing are plain functions over numbers, kept free of scene state so
the host test can exercise them headless; the drawing and the modal loop
are what a human verifies by eye.
"""

import bpy
import blf
import gpu
from gpu_extras.batch import batch_for_shader

from .outliner import (
    is_open,
    outliner_rows,
    parent_objects,
    reorder_objects,
    reveal_object,
    select_range,
    set_open,
    unparent_objects,
)

# Layout numbers are in unscaled pixels; every geometry function takes the
# interface scale and applies it, so a 4K screen at 150% draws a card the
# same physical size as Blender's own panels.
PANEL_X = 12.0
PANEL_TOP = 40.0
PANEL_WIDTH = 300.0
MIN_WIDTH = 170.0
HEADER_HEIGHT = 26.0
FOOTER_HEIGHT = 18.0
ROW_HEIGHT = 21.0
INDENT = 15.0
ARROW_ZONE = 16.0
TOGGLE_WIDTH = 18.0
SCROLLBAR_WIDTH = 6.0
GRIP_SIZE = 14.0
DRAG_THRESHOLD = 5.0
# How close to a row's edge counts as "between the rows" rather than "on
# this row". Wide enough to hit without aiming, narrow enough that the
# middle of a row is still comfortably a parenting drop.
EDGE_BAND = 6.0
FONT_ID = 0

OFFSET_PROP = "ml_outliner_offset"
SIZE_PROP = "ml_outliner_size"

COLOR_CARD = (0.09, 0.09, 0.10, 0.92)
COLOR_HEADER = (0.16, 0.16, 0.18, 1.0)
COLOR_ROW_SELECTED = (0.21, 0.35, 0.55, 0.9)
COLOR_ROW_HOVER = (1.0, 1.0, 1.0, 0.07)
COLOR_DROP_TARGET = (0.95, 0.65, 0.15, 0.85)
COLOR_DROP_LINE = (1.0, 0.78, 0.30, 1.0)
COLOR_EDIT_FIELD = (0.05, 0.05, 0.06, 1.0)
COLOR_TEXT = (0.90, 0.90, 0.90, 1.0)
COLOR_TEXT_DIM = (0.55, 0.55, 0.55, 1.0)
COLOR_ARROW = (0.65, 0.65, 0.65, 1.0)
COLOR_ON = (0.82, 0.82, 0.82, 1.0)
COLOR_OFF = (0.34, 0.34, 0.36, 1.0)
COLOR_SCROLL = (0.42, 0.42, 0.45, 0.9)
TYPE_COLORS = {
    "MESH": (0.75, 0.75, 0.75, 1.0),
    "EMPTY": (0.95, 0.65, 0.25, 1.0),
    "LIGHT": (0.98, 0.90, 0.40, 1.0),
    "CAMERA": (0.45, 0.70, 0.95, 1.0),
    "ARMATURE": (0.55, 0.90, 0.55, 1.0),
    "CURVE": (0.45, 0.90, 0.90, 1.0),
}
TYPE_COLOR_DEFAULT = (0.6, 0.6, 0.6, 1.0)

# One overlay at a time, in the viewport it was opened over. Module state
# rather than operator state so the draw callback and the panel button can
# both see it.
_state = {
    "running": False,
    "handle": None,
    "area": None,
    "region": None,
    "scroll": 0,
    "hover": None,
    "press": None,
    "press_pos": None,
    "press_offset": (0.0, 0.0),
    "press_size": None,
    "mode": None,
    "dragging": False,
    "offset": (0.0, 0.0),
    "size": None,
    "anchor": None,
    "editing": None,
    "rows": [],
}


def ui_scale():
    """Blender's interface scale, or 1.0 where it cannot be read."""
    try:
        return float(bpy.context.preferences.system.ui_scale) or 1.0
    except Exception:
        return 1.0


# ------------------------------------------------------------ pure geometry
def card_rect(region_width, region_height, offset=(0.0, 0.0), size=None,
              scale=1.0):
    """The overlay card in region pixels: (x0, y0, x1, y1), y up.

    ``offset`` and ``size`` are what the user dragged the card to. Both are
    clamped rather than trusted: a card dragged past the edge of a viewport
    that is later resized, or sized larger than the viewport it now sits
    in, would otherwise be unreachable with no way to drag it back.
    """
    margin = PANEL_X * scale
    if size is None:
        width = PANEL_WIDTH * scale
        height = region_height - (PANEL_TOP * scale) - margin
    else:
        width, height = size
    min_height = (HEADER_HEIGHT + FOOTER_HEIGHT + ROW_HEIGHT) * scale
    width = max(MIN_WIDTH * scale, min(float(width), region_width))
    height = max(min_height, min(float(height), region_height))
    x0 = max(0.0, min(margin + offset[0], region_width - width))
    y0 = max(0.0, min(margin + offset[1], region_height - height))
    return (x0, y0, x0 + width, y0 + height)


def visible_row_count(rect, scale=1.0):
    height = ((rect[3] - rect[1])
              - (HEADER_HEIGHT + FOOTER_HEIGHT) * scale)
    return max(0, int(height // (ROW_HEIGHT * scale)))


def clamp_scroll(scroll, total_rows, rect, scale=1.0):
    return max(0, min(int(scroll),
                      max(0, total_rows - visible_row_count(rect, scale))))


def row_rect(rect, slot, scale=1.0):
    """The rectangle of the visible slot (0 = topmost row)."""
    top = rect[3] - HEADER_HEIGHT * scale - slot * ROW_HEIGHT * scale
    return (rect[0], top - ROW_HEIGHT * scale, rect[2], top)


def hit_test(rect, scroll, total_rows, x, y, scale=1.0):
    """What sits under a region-space point.

    Returns ("row", absolute_index), ("header", None), or None for a point
    outside the card. Rows past the end of the list report None too, so a
    click in the empty tail is not a click on anything.
    """
    if not (rect[0] <= x <= rect[2] and rect[1] <= y <= rect[3]):
        return None
    if y >= rect[3] - HEADER_HEIGHT * scale:
        return ("header", None)
    slot = int((rect[3] - HEADER_HEIGHT * scale - y) // (ROW_HEIGHT * scale))
    index = slot + int(scroll)
    if slot < 0 or slot >= visible_row_count(rect, scale) or index >= total_rows:
        return None
    return ("row", index)


def in_arrow_zone(rect, depth, x, scale=1.0):
    start = rect[0] + 6.0 * scale + depth * INDENT * scale
    return start <= x <= start + ARROW_ZONE * scale


def row_control(rect, x, scale=1.0):
    """Which of a row's right-hand toggles a point is on, if any."""
    right = rect[2] - (SCROLLBAR_WIDTH + 3.0) * scale
    render_x = right - TOGGLE_WIDTH * scale
    view_x = render_x - TOGGLE_WIDTH * scale
    if render_x <= x <= right:
        return "render"
    if view_x <= x < render_x:
        return "viewport"
    return None


def drop_zone(rect, scroll, total_rows, x, y, scale=1.0):
    """Where a drag would land: on a row, or between two of them.

    Returns ("row", i) to parent under it, ("before", i) / ("after", i) to
    insert at that place in the order, ("header", None), or None. The
    edges of a row are the insertion bands, which is how one drag does
    both jobs -- the same split Maya's outliner uses.
    """
    hit = hit_test(rect, scroll, total_rows, x, y, scale)
    if hit is None or hit[0] != "row":
        return hit
    index = hit[1]
    bounds = row_rect(rect, index - int(scroll), scale)
    if y >= bounds[3] - EDGE_BAND * scale:
        return ("before", index)
    if y <= bounds[1] + EDGE_BAND * scale:
        return ("after", index)
    return ("row", index)


def scrollbar_thumb(rect, scroll, total_rows, scale=1.0):
    """The scrollbar thumb, or None when everything already fits."""
    count = visible_row_count(rect, scale)
    if total_rows <= count or count <= 0:
        return None
    track_top = rect[3] - HEADER_HEIGHT * scale
    track_bottom = rect[1] + FOOTER_HEIGHT * scale
    track = track_top - track_bottom
    height = max(20.0 * scale, track * (float(count) / total_rows))
    span = max(1, total_rows - count)
    top = track_top - (track - height) * (float(scroll) / span)
    x1 = rect[2] - 2.0 * scale
    return (x1 - SCROLLBAR_WIDTH * scale, top - height, x1, top)


def scroll_from_thumb(rect, y, total_rows, scale=1.0):
    """The scroll position a thumb dragged to ``y`` means."""
    count = visible_row_count(rect, scale)
    if total_rows <= count or count <= 0:
        return 0
    track_top = rect[3] - HEADER_HEIGHT * scale
    track_bottom = rect[1] + FOOTER_HEIGHT * scale
    track = max(1.0, track_top - track_bottom)
    fraction = (track_top - y) / track
    return clamp_scroll(int(round(fraction * (total_rows - count))),
                        total_rows, rect, scale)


def resize_grip_rect(rect, scale=1.0):
    """The corner that resizes the card."""
    size = GRIP_SIZE * scale
    return (rect[2] - size, rect[1], rect[2], rect[1] + size)


def in_rect(rect, x, y):
    return rect[0] <= x <= rect[2] and rect[1] <= y <= rect[3]


def scroll_to_index(index, scroll, rect, total_rows, scale=1.0):
    """The scroll that brings a row into view, moving as little as it can."""
    count = visible_row_count(rect, scale)
    if count <= 0:
        return scroll
    if index < scroll:
        target = index
    elif index >= scroll + count:
        target = index - count + 1
    else:
        target = scroll
    return clamp_scroll(target, total_rows, rect, scale)


# ----------------------------------------------------------------- drawing
def _set_font_size(size):
    # blf.size lost its dpi argument along the way; try the modern
    # signature first so the legacy one stays the fallback.
    try:
        blf.size(FONT_ID, size)
    except TypeError:
        blf.size(FONT_ID, size, 72)


def _quad(shader, x0, y0, x1, y1, color):
    batch = batch_for_shader(shader, "TRIS", {"pos": [
        (x0, y0), (x1, y0), (x1, y1),
        (x0, y0), (x1, y1), (x0, y1),
    ]})
    shader.uniform_float("color", color)
    batch.draw(shader)


def _triangle(shader, points, color):
    batch = batch_for_shader(shader, "TRIS", {"pos": points})
    shader.uniform_float("color", color)
    batch.draw(shader)


def _toggle_glyph(shader, x, mid, scale, on, kind):
    """A filled mark for shown, a hollow one for hidden.

    Drawn rather than iconified: the GPU module has no icon atlas, and two
    shapes that differ in fill read at a glance at this size.
    """
    size = 4.5 * scale
    color = COLOR_ON if on else COLOR_OFF
    if on:
        if kind == "render":
            _quad(shader, x - size, mid - size * 0.7,
                  x + size, mid + size * 0.7, color)
        else:
            _triangle(shader, [(x - size, mid - size), (x + size, mid - size),
                               (x, mid + size)], color)
        return
    thickness = 1.0 * scale
    _quad(shader, x - size, mid - size, x + size, mid - size + thickness,
          color)
    _quad(shader, x - size, mid + size - thickness, x + size, mid + size,
          color)
    _quad(shader, x - size, mid - size, x - size + thickness, mid + size,
          color)
    _quad(shader, x + size - thickness, mid - size, x + size, mid + size,
          color)


def _draw():
    context = bpy.context
    if not _state["running"] or context.region != _state["region"]:
        return
    scene = context.scene
    scale = ui_scale()
    search = str(getattr(scene, "ml_outliner_search", "") or "")
    rows = outliner_rows(scene, search)
    _state["rows"] = rows

    region = context.region
    rect = card_rect(region.width, region.height, _state["offset"],
                     _state["size"], scale)
    _state["scroll"] = clamp_scroll(_state["scroll"], len(rows), rect, scale)
    scroll = _state["scroll"]
    editing = _state["editing"]

    shader = gpu.shader.from_builtin("UNIFORM_COLOR")
    gpu.state.blend_set("ALPHA")
    _quad(shader, rect[0], rect[1], rect[2], rect[3], COLOR_CARD)
    _quad(shader, rect[0], rect[3] - HEADER_HEIGHT * scale, rect[2], rect[3],
          COLOR_HEADER)
    if _state["dragging"] and _state["hover"] == ("header", None):
        _quad(shader, rect[0], rect[3] - HEADER_HEIGHT * scale, rect[2],
              rect[3], COLOR_DROP_TARGET)

    count = visible_row_count(rect, scale)
    for slot in range(min(count, max(0, len(rows) - scroll))):
        index = slot + scroll
        obj, depth, has_children, opened = rows[index]
        x0, y0, x1, y1 = row_rect(rect, slot, scale)
        try:
            selected = obj.select_get()
        except Exception:
            selected = False
        if selected:
            _quad(shader, x0, y0, x1, y1, COLOR_ROW_SELECTED)
        if _state["hover"] == ("row", index):
            highlight = (COLOR_DROP_TARGET if _state["dragging"]
                         else COLOR_ROW_HOVER)
            _quad(shader, x0, y0, x1, y1, highlight)

        base = x0 + 6.0 * scale + depth * INDENT * scale
        mid = (y0 + y1) / 2.0
        if has_children:
            step = 3.0 * scale
            if opened:
                points = [(base + step, mid + step),
                          (base + step * 4, mid + step),
                          (base + step * 2.5, mid - step * 1.4)]
            else:
                points = [(base + step, mid + step * 1.7),
                          (base + step, mid - step * 1.7),
                          (base + step * 3.5, mid)]
            _triangle(shader, points, COLOR_ARROW)
        swatch = base + ARROW_ZONE * scale
        _quad(shader, swatch, mid - 4.0 * scale, swatch + 8.0 * scale,
              mid + 4.0 * scale,
              TYPE_COLORS.get(obj.type, TYPE_COLOR_DEFAULT))

        text_x = swatch + 14.0 * scale
        right = rect[2] - (SCROLLBAR_WIDTH + 3.0) * scale
        if editing is not None and editing["name"] == obj.name:
            _quad(shader, text_x - 3.0 * scale, y0 + 2.0 * scale,
                  right - TOGGLE_WIDTH * 2 * scale, y1 - 2.0 * scale,
                  COLOR_EDIT_FIELD)
            _set_font_size(12 * scale)
            blf.color(FONT_ID, *COLOR_TEXT)
            blf.position(FONT_ID, text_x, y0 + 6.0 * scale, 0)
            blf.draw(FONT_ID, editing["buffer"])
            caret = text_x + blf.dimensions(FONT_ID, editing["buffer"])[0]
            _quad(shader, caret + 1.0 * scale, y0 + 4.0 * scale,
                  caret + 2.0 * scale, y1 - 4.0 * scale, COLOR_TEXT)
        else:
            _set_font_size(12 * scale)
            blf.color(FONT_ID, *COLOR_TEXT)
            blf.position(FONT_ID, text_x, y0 + 6.0 * scale, 0)
            blf.draw(FONT_ID, obj.name)
            _toggle_glyph(shader, right - TOGGLE_WIDTH * 1.5 * scale, mid,
                          scale, not obj.hide_viewport, "viewport")
            _toggle_glyph(shader, right - TOGGLE_WIDTH * 0.5 * scale, mid,
                          scale, not obj.hide_render, "render")

        # The insertion line: where dropping would put things in the order.
        if _state["dragging"]:
            hover = _state["hover"]
            if hover == ("before", index):
                _quad(shader, x0, y1 - 1.0 * scale, x1, y1 + 1.0 * scale,
                      COLOR_DROP_LINE)
            elif hover == ("after", index):
                _quad(shader, x0, y0 - 1.0 * scale, x1, y0 + 1.0 * scale,
                      COLOR_DROP_LINE)

    thumb = scrollbar_thumb(rect, scroll, len(rows), scale)
    if thumb:
        _quad(shader, thumb[0], thumb[1], thumb[2], thumb[3], COLOR_SCROLL)

    grip = resize_grip_rect(rect, scale)
    for step in range(3):
        shift = step * 4.0 * scale
        _quad(shader, grip[2] - 3.0 * scale - shift, grip[1] + 2.0 * scale,
              grip[2] - 2.0 * scale - shift, grip[1] + 6.0 * scale + shift,
              COLOR_TEXT_DIM)

    _set_font_size(11 * scale)
    blf.color(FONT_ID, *COLOR_TEXT)
    blf.position(FONT_ID, rect[0] + 8.0 * scale,
                 rect[3] - HEADER_HEIGHT * scale + 8.0 * scale, 0)
    if editing is not None:
        title = "Enter to rename, Esc to cancel"
    elif _state["mode"] == "move":
        title = "Moving the window"
    elif _state["mode"] == "resize":
        title = "Resizing"
    elif _state["dragging"]:
        title = "On a row parents - between rows reorders"
    else:
        title = "mLender Outliner"
    blf.draw(FONT_ID, title)
    grip_x = rect[2] - 26.0 * scale
    grip_y = rect[3] - HEADER_HEIGHT * scale / 2.0
    for step in (-4.0, 0.0, 4.0):
        _quad(shader, grip_x, grip_y + step * scale - 0.5 * scale,
              grip_x + 16.0 * scale, grip_y + step * scale + 0.5 * scale,
              COLOR_TEXT_DIM)

    blf.color(FONT_ID, *COLOR_TEXT_DIM)
    blf.position(FONT_ID, rect[0] + 8.0 * scale, rect[1] + 5.0 * scale, 0)
    if len(rows) > count:
        footer = "{0}/{1} - F reveals - X deletes - right-click: menu".format(
            min(count + scroll, len(rows)), len(rows))
    else:
        footer = "drag: parent or reorder - F reveal - X delete - Esc"
    blf.draw(FONT_ID, footer)
    gpu.state.blend_set("NONE")


# ------------------------------------------------------------- interaction
def overlay_running():
    return bool(_state["running"])


def _window_region(area):
    for region in area.regions:
        if region.type == "WINDOW":
            return region
    return None


def _stop():
    if _state["handle"] is not None:
        try:
            bpy.types.SpaceView3D.draw_handler_remove(
                _state["handle"], "WINDOW")
        except Exception:
            pass
    _state.update(handle=None, running=False, area=None, region=None,
                  hover=None, press=None, press_pos=None, dragging=False,
                  mode=None, editing=None)


def _push(message):
    """Record an undo step, so a drag is as undoable as anything else."""
    try:
        bpy.ops.ed.undo_push(message=message)
    except Exception:
        pass


def _store_geometry(scene):
    """Keep the card where the user put it, in the file."""
    try:
        scene[OFFSET_PROP] = list(_state["offset"])
        if _state["size"] is not None:
            scene[SIZE_PROP] = list(_state["size"])
    except Exception:
        pass


def _load_geometry(scene):
    try:
        offset = scene.get(OFFSET_PROP)
        if offset is not None and len(offset) == 2:
            _state["offset"] = (float(offset[0]), float(offset[1]))
        size = scene.get(SIZE_PROP)
        if size is not None and len(size) == 2:
            _state["size"] = (float(size[0]), float(size[1]))
    except Exception:
        pass


def _select(context, obj, event, rows):
    """Maya's selection rules: plain replaces, Ctrl toggles, Shift ranges."""
    scene = context.scene
    search = str(getattr(scene, "ml_outliner_search", "") or "")
    if event.ctrl:
        obj.select_set(not obj.select_get())
        if obj.select_get():
            context.view_layer.objects.active = obj
        _state["anchor"] = obj
        return
    if event.shift and _state["anchor"] is not None:
        for other in context.selected_objects:
            other.select_set(False)
        for member in select_range(scene, _state["anchor"], obj, search):
            try:
                member.select_set(True)
            except RuntimeError:
                continue
        try:
            context.view_layer.objects.active = obj
        except Exception:
            pass
        return
    for other in context.selected_objects:
        other.select_set(False)
    try:
        obj.select_set(True)
        context.view_layer.objects.active = obj
    except RuntimeError:
        return
    _state["anchor"] = obj


def _commit_edit():
    editing = _state["editing"]
    _state["editing"] = None
    if editing is None:
        return False
    obj = bpy.data.objects.get(editing["name"])
    wanted = editing["buffer"].strip()
    if obj is None or not wanted or wanted == obj.name:
        return False
    obj.name = wanted
    _push("Rename Object")
    return True


class ML_OT_overlay_rename(bpy.types.Operator):
    bl_idname = "mlender.overlay_rename"
    bl_label = "Rename"
    bl_description = "Rename the active object"
    bl_options = {"REGISTER", "UNDO"}

    target: bpy.props.StringProperty()
    new_name: bpy.props.StringProperty(name="Name")

    def invoke(self, context, event):
        if not self.target:
            active = context.view_layer.objects.active
            self.target = active.name if active else ""
        self.new_name = self.target
        if not self.target:
            self.report({"WARNING"}, "Nothing to rename.")
            return {"CANCELLED"}
        return context.window_manager.invoke_props_dialog(self)

    def execute(self, context):
        obj = bpy.data.objects.get(self.target)
        if obj is None or not self.new_name.strip():
            return {"CANCELLED"}
        obj.name = self.new_name.strip()
        return {"FINISHED"}


class ML_OT_overlay_outliner(bpy.types.Operator):
    """Toggle the GPU outliner overlay in this viewport."""
    bl_idname = "mlender.overlay_outliner"
    bl_label = "Outliner Overlay"
    bl_description = (
        "A Maya-style outliner drawn over the viewport: drag to parent or "
        "reorder, double-click to rename, right-click for the menu"
    )

    def invoke(self, context, event):
        if _state["running"]:
            # The running modal sees the flag drop and finishes itself.
            _state["running"] = False
            return {"CANCELLED"}
        area = context.area
        if area is None or area.type != "VIEW_3D":
            self.report({"WARNING"}, "Open it from a 3D viewport.")
            return {"CANCELLED"}
        region = _window_region(area)
        if region is None:
            return {"CANCELLED"}
        _load_geometry(context.scene)
        _state.update(area=area, region=region, running=True, scroll=0,
                      hover=None, press=None, press_pos=None, mode=None,
                      dragging=False, editing=None)
        _state["handle"] = bpy.types.SpaceView3D.draw_handler_add(
            _draw, (), "WINDOW", "POST_PIXEL")
        context.window_manager.modal_handler_add(self)
        area.tag_redraw()
        return {"RUNNING_MODAL"}

    def modal(self, context, event):
        if not _state["running"]:
            _stop()
            return {"FINISHED"}
        region = _state["region"]
        area = _state["area"]
        try:
            x = event.mouse_x - region.x
            y = event.mouse_y - region.y
        except Exception:
            _stop()
            return {"FINISHED"}
        scale = ui_scale()
        rect = card_rect(region.width, region.height, _state["offset"],
                         _state["size"], scale)
        rows = _state["rows"]
        hit = drop_zone(rect, _state["scroll"], len(rows), x, y, scale)

        # Renaming owns the keyboard while it is open.
        if _state["editing"] is not None:
            return self._edit_keys(context, event, area)

        if event.type == "ESC" and event.value == "PRESS":
            _stop()
            area.tag_redraw()
            return {"FINISHED"}

        if event.type == "MOUSEMOVE":
            return self._motion(context, event, x, y, hit, rect, rows,
                                scale, area)

        inside = hit is not None or in_rect(rect, x, y)
        if event.value == "PRESS" and event.type in ("F", "X", "DEL"):
            if event.type == "F":
                active = context.view_layer.objects.active
                if active is not None:
                    reveal_object(active)
                    fresh = outliner_rows(
                        context.scene,
                        getattr(context.scene, "ml_outliner_search", ""))
                    names = [entry[0].name for entry in fresh]
                    if active.name in names:
                        _state["scroll"] = scroll_to_index(
                            names.index(active.name), _state["scroll"],
                            rect, len(names), scale)
                    area.tag_redraw()
                    return {"RUNNING_MODAL"}
            elif context.selected_objects:
                bpy.ops.mlender.outliner_delete()
                area.tag_redraw()
                return {"RUNNING_MODAL"}
            return {"PASS_THROUGH"}

        if event.type in ("WHEELUPMOUSE", "WHEELDOWNMOUSE") and inside:
            step = -3 if event.type == "WHEELUPMOUSE" else 3
            _state["scroll"] = clamp_scroll(
                _state["scroll"] + step, len(rows), rect, scale)
            area.tag_redraw()
            return {"RUNNING_MODAL"}

        if event.type == "RIGHTMOUSE" and event.value == "PRESS" and inside:
            if hit is not None and hit[1] is not None and hit[1] < len(rows):
                target = rows[hit[1]][0]
                if not target.select_get():
                    _select(context, target, event, rows)
            bpy.ops.wm.call_menu(name="ML_MT_outliner")
            return {"RUNNING_MODAL"}

        if event.type == "LEFTMOUSE" and event.value == "DOUBLE_CLICK":
            if hit and hit[1] is not None and hit[1] < len(rows):
                obj = rows[hit[1]][0]
                _state["editing"] = {"name": obj.name, "buffer": obj.name}
                area.tag_redraw()
                return {"RUNNING_MODAL"}
            return {"PASS_THROUGH"}

        if event.type == "LEFTMOUSE" and event.value == "PRESS":
            return self._press(context, event, x, y, hit, rect, rows, scale,
                               inside, area)

        if event.type == "LEFTMOUSE" and event.value == "RELEASE":
            return self._release(context, event, hit, rows, area)

        return {"PASS_THROUGH"}

    # ------------------------------------------------------------- helpers
    def _edit_keys(self, context, event, area):
        editing = _state["editing"]
        if event.value != "PRESS":
            return {"RUNNING_MODAL"}
        if event.type == "ESC":
            _state["editing"] = None
        elif event.type in ("RET", "NUMPAD_ENTER"):
            _commit_edit()
        elif event.type == "BACK_SPACE":
            editing["buffer"] = editing["buffer"][:-1]
        elif event.unicode and event.unicode.isprintable():
            editing["buffer"] += event.unicode
        area.tag_redraw()
        return {"RUNNING_MODAL"}

    def _motion(self, context, event, x, y, hit, rect, rows, scale, area):
        _state["hover"] = hit
        press = _state["press"]
        if (press is not None and not _state["dragging"]
                and _state["press_pos"] is not None):
            px, py = _state["press_pos"]
            if abs(x - px) > DRAG_THRESHOLD or abs(y - py) > DRAG_THRESHOLD:
                _state["dragging"] = True
        if _state["dragging"] and _state["mode"] in ("move", "resize",
                                                     "scroll"):
            px, py = _state["press_pos"]
            if _state["mode"] == "move":
                base = _state["press_offset"]
                _state["offset"] = (base[0] + (x - px), base[1] + (y - py))
            elif _state["mode"] == "resize":
                width, height = _state["press_size"]
                # The grip is the bottom-right corner: pulling right widens,
                # pulling down shortens without moving the card's top.
                _state["size"] = (max(MIN_WIDTH * scale, width + (x - px)),
                                  max(0.0, height - (y - py)))
                _state["offset"] = (_state["press_offset"][0],
                                    _state["press_offset"][1] + (y - py))
            else:
                _state["scroll"] = scroll_from_thumb(rect, y, len(rows),
                                                     scale)
            area.tag_redraw()
            return {"RUNNING_MODAL"}
        area.tag_redraw()
        return {"PASS_THROUGH"}

    def _press(self, context, event, x, y, hit, rect, rows, scale, inside,
               area):
        if not inside:
            return {"PASS_THROUGH"}
        _state["press_pos"] = (x, y)
        _state["press_offset"] = _state["offset"]
        if in_rect(resize_grip_rect(rect, scale), x, y):
            _state["press"] = ("grip", None)
            _state["mode"] = "resize"
            _state["press_size"] = (rect[2] - rect[0], rect[3] - rect[1])
            return {"RUNNING_MODAL"}
        thumb = scrollbar_thumb(rect, _state["scroll"], len(rows), scale)
        if thumb and in_rect(thumb, x, y):
            _state["press"] = ("thumb", None)
            _state["mode"] = "scroll"
            return {"RUNNING_MODAL"}
        if hit is None:
            return {"RUNNING_MODAL"}
        if hit[0] == "header":
            _state["press"] = hit
            _state["mode"] = "move"
            return {"RUNNING_MODAL"}
        if hit[1] is not None and hit[1] < len(rows):
            obj, depth, has_children, _opened = rows[hit[1]]
            if hit[0] == "row":
                control = row_control(rect, x, scale)
                if control is not None:
                    if control == "viewport":
                        obj.hide_viewport = not obj.hide_viewport
                    else:
                        obj.hide_render = not obj.hide_render
                    _push("Toggle Visibility")
                    area.tag_redraw()
                    return {"RUNNING_MODAL"}
                if has_children and in_arrow_zone(rect, depth, x, scale):
                    set_open(obj, not is_open(obj))
                    area.tag_redraw()
                    return {"RUNNING_MODAL"}
            # A press in an edge band still grabs that row; where it is
            # dropped is what decides parent or reorder.
            _state["press"] = ("row", hit[1])
            _state["mode"] = "rows"
        return {"RUNNING_MODAL"}

    def _release(self, context, event, hit, rows, area):
        press = _state["press"]
        mode = _state["mode"]
        dragging = _state["dragging"]
        _state.update(press=None, press_pos=None, dragging=False, mode=None)
        if press is None:
            return {"PASS_THROUGH"}
        if mode in ("move", "resize"):
            _store_geometry(context.scene)
            area.tag_redraw()
            return {"RUNNING_MODAL"}
        if mode == "scroll":
            return {"RUNNING_MODAL"}
        source = (rows[press[1]][0]
                  if press[0] == "row" and press[1] < len(rows) else None)
        if source is None:
            return {"RUNNING_MODAL"}
        if not dragging:
            _select(context, source, event, rows)
            area.tag_redraw()
            return {"RUNNING_MODAL"}
        # A drag moves the selection when the grabbed row is part of it,
        # the single row otherwise -- Maya's rule.
        moved = list(context.selected_objects)
        if source not in moved:
            moved = [source]
        if hit is not None and hit[0] == "header":
            if unparent_objects(moved):
                _push("Unparent")
        elif hit is not None and hit[1] is not None and hit[1] < len(rows):
            anchor = rows[hit[1]][0]
            if hit[0] == "row":
                if parent_objects(anchor, moved):
                    set_open(anchor, True)
                    _push("Parent Objects")
            elif reorder_objects(context.scene, moved, anchor,
                                 before=hit[0] == "before"):
                _push("Reorder Objects")
        area.tag_redraw()
        return {"RUNNING_MODAL"}


CLASSES = (
    ML_OT_overlay_rename,
    ML_OT_overlay_outliner,
)
