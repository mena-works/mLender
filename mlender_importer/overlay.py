# -*- coding: utf-8 -*-
"""A GPU-drawn outliner overlay: the Maya feel the panel API cannot give.

The panel outliner stops where Blender's layout widgets stop: no
drag-and-drop, no double-click. This draws its own tree into the 3D
viewport with the ``gpu`` module and runs a modal operator that reads raw
mouse events, so the missing gestures exist here:

* click selects, Shift-click toggles;
* double-click renames (a small dialog -- text editing inside the GPU
  canvas would mean writing a text widget, and a dialog does the job);
* **dragging a row onto another row parents it there**, world transform
  kept, and dropping it on the header bar unparents -- Maya's
  middle-drag, actually as a drag;
* the wheel scrolls, the fold triangles collapse and expand.

It shares its tree, order and fold state with the panel outliner
(``outliner.py``), so the two views never disagree. The overlay lives in
the one viewport it was opened over; ESC or the toggle button closes it.

Geometry and hit-testing are plain functions over numbers, kept free of
``bpy`` so the host test can exercise them headless -- the drawing and the
modal loop are the only parts that need a real window, and those are the
parts a human verifies by eye.
"""

import bpy
import blf
import gpu
from gpu_extras.batch import batch_for_shader

from .outliner import (
    is_open,
    outliner_rows,
    parent_objects,
    set_open,
    unparent_objects,
)

PANEL_X = 12.0
PANEL_TOP = 40.0
PANEL_WIDTH = 300.0
HEADER_HEIGHT = 26.0
FOOTER_HEIGHT = 18.0
ROW_HEIGHT = 21.0
INDENT = 15.0
ARROW_ZONE = 16.0
DRAG_THRESHOLD = 5.0
FONT_ID = 0

COLOR_CARD = (0.09, 0.09, 0.10, 0.92)
COLOR_HEADER = (0.16, 0.16, 0.18, 1.0)
COLOR_ROW_SELECTED = (0.21, 0.35, 0.55, 0.9)
COLOR_ROW_HOVER = (1.0, 1.0, 1.0, 0.07)
COLOR_DROP_TARGET = (0.95, 0.65, 0.15, 0.85)
COLOR_TEXT = (0.90, 0.90, 0.90, 1.0)
COLOR_TEXT_DIM = (0.55, 0.55, 0.55, 1.0)
COLOR_ARROW = (0.65, 0.65, 0.65, 1.0)
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
    "dragging": False,
    "rows": [],
}


# ------------------------------------------------------------ pure geometry
def card_rect(region_width, region_height):
    """The overlay card in region pixels: (x0, y0, x1, y1), y up."""
    x0 = PANEL_X
    x1 = min(x0 + PANEL_WIDTH, region_width - PANEL_X)
    y1 = region_height - PANEL_TOP
    y0 = PANEL_X
    return (x0, y0, x1, y1)


def visible_row_count(rect):
    height = (rect[3] - rect[1]) - HEADER_HEIGHT - FOOTER_HEIGHT
    return max(0, int(height // ROW_HEIGHT))


def clamp_scroll(scroll, total_rows, rect):
    return max(0, min(int(scroll), max(0, total_rows - visible_row_count(rect))))


def row_rect(rect, slot):
    """The rectangle of the visible slot (0 = topmost row)."""
    top = rect[3] - HEADER_HEIGHT - slot * ROW_HEIGHT
    return (rect[0], top - ROW_HEIGHT, rect[2], top)


def hit_test(rect, scroll, total_rows, x, y):
    """What sits under a region-space point.

    Returns ("row", absolute_index), ("header", None), or None for a point
    outside the card. Rows past the end of the list report None too, so a
    click in the empty tail is not a click on anything.
    """
    if not (rect[0] <= x <= rect[2] and rect[1] <= y <= rect[3]):
        return None
    if y >= rect[3] - HEADER_HEIGHT:
        return ("header", None)
    slot = int((rect[3] - HEADER_HEIGHT - y) // ROW_HEIGHT)
    index = slot + int(scroll)
    if slot < 0 or slot >= visible_row_count(rect) or index >= total_rows:
        return None
    return ("row", index)


def in_arrow_zone(rect, depth, x):
    start = rect[0] + 6.0 + depth * INDENT
    return start <= x <= start + ARROW_ZONE


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


def _draw():
    context = bpy.context
    if not _state["running"] or context.region != _state["region"]:
        return
    scene = context.scene
    search = str(getattr(scene, "ml_outliner_search", "") or "")
    rows = outliner_rows(scene, search)
    _state["rows"] = rows

    region = context.region
    rect = card_rect(region.width, region.height)
    _state["scroll"] = clamp_scroll(_state["scroll"], len(rows), rect)
    scroll = _state["scroll"]

    shader = gpu.shader.from_builtin("UNIFORM_COLOR")
    gpu.state.blend_set("ALPHA")
    _quad(shader, rect[0], rect[1], rect[2], rect[3], COLOR_CARD)
    _quad(shader, rect[0], rect[3] - HEADER_HEIGHT, rect[2], rect[3],
          COLOR_HEADER)
    if _state["dragging"] and _state["hover"] == ("header", None):
        _quad(shader, rect[0], rect[3] - HEADER_HEIGHT, rect[2], rect[3],
              COLOR_DROP_TARGET)

    count = visible_row_count(rect)
    for slot in range(min(count, len(rows) - scroll)):
        index = slot + scroll
        obj, depth, has_children, opened = rows[index]
        x0, y0, x1, y1 = row_rect(rect, slot)
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

        base = x0 + 6.0 + depth * INDENT
        mid = (y0 + y1) / 2.0
        if has_children:
            if opened:
                points = [(base + 2, mid + 3), (base + 12, mid + 3),
                          (base + 7, mid - 4)]
            else:
                points = [(base + 3, mid + 5), (base + 3, mid - 5),
                          (base + 11, mid)]
            _triangle(shader, points, COLOR_ARROW)
        swatch = base + ARROW_ZONE
        _quad(shader, swatch, mid - 4, swatch + 8, mid + 4,
              TYPE_COLORS.get(obj.type, TYPE_COLOR_DEFAULT))

        _set_font_size(12)
        blf.color(FONT_ID, *COLOR_TEXT)
        blf.position(FONT_ID, swatch + 14, y0 + 6.0, 0)
        blf.draw(FONT_ID, obj.name)

    _set_font_size(11)
    blf.color(FONT_ID, *COLOR_TEXT)
    blf.position(FONT_ID, rect[0] + 8, rect[3] - HEADER_HEIGHT + 8, 0)
    title = "mLender Outliner"
    if _state["dragging"]:
        title = "Drop on a row to parent, here to unparent"
    blf.draw(FONT_ID, title)

    blf.color(FONT_ID, *COLOR_TEXT_DIM)
    blf.position(FONT_ID, rect[0] + 8, rect[1] + 5, 0)
    if len(rows) > count:
        footer = "{0}/{1} rows - wheel scrolls - Esc closes".format(
            min(count + scroll, len(rows)), len(rows))
    else:
        footer = "drag: parent - double-click: rename - Esc closes"
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
                  hover=None, press=None, press_pos=None, dragging=False)


def _select(context, obj, extend):
    if extend and obj.select_get():
        obj.select_set(False)
        return
    if not extend:
        for other in context.selected_objects:
            other.select_set(False)
    try:
        obj.select_set(True)
        context.view_layer.objects.active = obj
    except RuntimeError:
        pass


class ML_OT_overlay_rename(bpy.types.Operator):
    bl_idname = "mlender.overlay_rename"
    bl_label = "Rename"
    bl_description = "Rename the object, the way Maya's double-click does"
    bl_options = {"REGISTER", "UNDO", "INTERNAL"}

    target: bpy.props.StringProperty()
    new_name: bpy.props.StringProperty(name="Name")

    def invoke(self, context, event):
        self.new_name = self.target
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
        "A Maya-style outliner drawn over the viewport: drag rows to "
        "parent, double-click to rename, Esc to close"
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
        _state.update(area=area, region=region, running=True, scroll=0,
                      hover=None, press=None, press_pos=None, dragging=False)
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
        rect = card_rect(region.width, region.height)
        rows = _state["rows"]
        hit = hit_test(rect, _state["scroll"], len(rows), x, y)

        if event.type == "ESC" and event.value == "PRESS":
            _stop()
            area.tag_redraw()
            return {"FINISHED"}

        if event.type == "MOUSEMOVE":
            _state["hover"] = hit
            if (_state["press"] is not None and not _state["dragging"]
                    and _state["press_pos"] is not None):
                px, py = _state["press_pos"]
                if abs(x - px) > DRAG_THRESHOLD or abs(y - py) > DRAG_THRESHOLD:
                    _state["dragging"] = True
            area.tag_redraw()
            return {"PASS_THROUGH"}

        inside = hit is not None
        if event.type in ("WHEELUPMOUSE", "WHEELDOWNMOUSE") and inside:
            step = -3 if event.type == "WHEELUPMOUSE" else 3
            _state["scroll"] = clamp_scroll(
                _state["scroll"] + step, len(rows), rect)
            area.tag_redraw()
            return {"RUNNING_MODAL"}

        if event.type == "LEFTMOUSE" and event.value == "DOUBLE_CLICK":
            if hit and hit[0] == "row" and hit[1] < len(rows):
                bpy.ops.mlender.overlay_rename(
                    "INVOKE_DEFAULT", target=rows[hit[1]][0].name)
                return {"RUNNING_MODAL"}
            return {"PASS_THROUGH"}

        if event.type == "LEFTMOUSE" and event.value == "PRESS":
            if not inside:
                return {"PASS_THROUGH"}
            if hit[0] == "row" and hit[1] < len(rows):
                obj, depth, has_children, _opened = rows[hit[1]]
                if has_children and in_arrow_zone(rect, depth, x):
                    set_open(obj, not is_open(obj))
                    area.tag_redraw()
                    return {"RUNNING_MODAL"}
                _state["press"] = hit
                _state["press_pos"] = (x, y)
            return {"RUNNING_MODAL"}

        if event.type == "LEFTMOUSE" and event.value == "RELEASE":
            press = _state["press"]
            dragging = _state["dragging"]
            _state["press"] = None
            _state["press_pos"] = None
            _state["dragging"] = False
            if press is None:
                return {"PASS_THROUGH"}
            source = (rows[press[1]][0]
                      if press[0] == "row" and press[1] < len(rows) else None)
            if source is None:
                return {"RUNNING_MODAL"}
            if not dragging:
                _select(context, source, event.shift)
                area.tag_redraw()
                return {"RUNNING_MODAL"}
            # A drag moves the selection when the grabbed row is part of
            # it, the single row otherwise -- Maya's rule.
            moved = list(context.selected_objects)
            if source not in moved:
                moved = [source]
            if hit is not None and hit[0] == "header":
                unparent_objects(moved)
            elif (hit is not None and hit[0] == "row"
                    and hit[1] < len(rows)):
                target = rows[hit[1]][0]
                if parent_objects(target, moved):
                    set_open(target, True)
            area.tag_redraw()
            return {"RUNNING_MODAL"}

        return {"PASS_THROUGH"}


CLASSES = (
    ML_OT_overlay_rename,
    ML_OT_overlay_outliner,
)
