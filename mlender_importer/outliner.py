# -*- coding: utf-8 -*-
"""A Maya-style outliner: one tree, manual order, quick parenting.

Blender's own outliner shows collections and sorts siblings alphabetically.
This panel shows what a Maya artist expects instead: the transform hierarchy
as a single tree, siblings in an order the user controls, one-click
parenting with the world transform kept, and per-row visibility.

A Python add-on cannot add an editor type or real drag-and-drop, so the
tree lives in a panel and moving things is buttons -- the logic here is
kept free of operator context so the host test can exercise it headless,
the same split the AS rig panel uses.

Order and fold state persist as ID properties (``ml_outliner_index``,
``ml_outliner_open``) so they survive a save; an object that never was
reordered sorts by name after every object that was, which keeps fresh
imports stable and user intent sticky.
"""

ORDER_PROP = "ml_outliner_index"
OPEN_PROP = "ml_outliner_open"
# A row budget, not a truncation of the scene: a panel drawing tens of
# thousands of rows stalls the UI thread. The draw says how many were held
# back and the search reaches everything regardless.
MAX_ROWS = 400
UNORDERED = 1 << 30


def sort_key(obj):
    """Manual index first, name second: reordered objects keep their place,
    untouched ones stay alphabetical after them."""
    try:
        index = int(obj.get(ORDER_PROP, UNORDERED))
    except (TypeError, ValueError):
        index = UNORDERED
    return (index, obj.name.lower())


def children_by_parent(scene):
    """Every scene object grouped under its parent, siblings sorted.

    One pass over the scene: asking each object for ``obj.children`` is a
    scan of all objects per call, which is quadratic over a whole tree.
    """
    groups = {}
    for obj in scene.objects:
        groups.setdefault(obj.parent, []).append(obj)
    for siblings in groups.values():
        siblings.sort(key=sort_key)
    return groups


def is_open(obj):
    return bool(obj.get(OPEN_PROP, False))


def set_open(obj, state):
    obj[OPEN_PROP] = bool(state)


def outliner_rows(scene, search=""):
    """The rows the panel draws: (object, depth, has_children, open).

    A search flattens the tree to every match, the way Maya's outliner
    filter does -- a hit deep inside a collapsed group must still appear.
    """
    groups = children_by_parent(scene)
    needle = str(search or "").strip().lower()
    if needle:
        found = [obj for obj in scene.objects
                 if needle in obj.name.lower()]
        found.sort(key=sort_key)
        return [(obj, 0, False, False) for obj in found]

    rows = []
    stack = [(obj, 0) for obj in reversed(groups.get(None, []))]
    while stack:
        obj, depth = stack.pop()
        children = groups.get(obj, [])
        opened = is_open(obj)
        rows.append((obj, depth, bool(children), opened))
        if children and opened:
            for child in reversed(children):
                stack.append((child, depth + 1))
    return rows


def move_object(scene, obj, direction):
    """Swap an object with its neighbouring sibling. Returns success.

    The whole sibling group is renumbered first: fresh imports carry no
    index at all, and swapping against UNORDERED would jump the object to
    an arbitrary place instead of one step.
    """
    groups = children_by_parent(scene)
    siblings = groups.get(obj.parent, [])
    if obj not in siblings:
        return False
    index = siblings.index(obj)
    other = index + (1 if direction > 0 else -1)
    if other < 0 or other >= len(siblings):
        return False
    siblings[index], siblings[other] = siblings[other], siblings[index]
    for position, sibling in enumerate(siblings):
        sibling[ORDER_PROP] = position
    return True


def parent_objects(target, objects):
    """Parent objects under target, world transforms kept. Returns count.

    Maya's middle-drag, as a click: the target cannot be parented under
    itself or under anything about to move with it, so those are skipped
    rather than allowed to knot the hierarchy.
    """
    moved = 0
    for obj in objects:
        if obj is target or _is_descendant(target, obj):
            continue
        world = obj.matrix_world.copy()
        obj.parent = target
        obj.matrix_parent_inverse = target.matrix_world.inverted_safe()
        obj.matrix_world = world
        moved += 1
    return moved


def unparent_objects(objects):
    """Clear parents, world transforms kept. Returns count."""
    freed = 0
    for obj in objects:
        if obj.parent is None:
            continue
        world = obj.matrix_world.copy()
        obj.parent = None
        obj.matrix_world = world
        freed += 1
    return freed


# Object types whose OUTLINER_OB_* icon exists on every supported Blender;
# anything else falls back to a neutral icon rather than raising in draw.
KNOWN_ICON_TYPES = frozenset((
    "MESH", "CURVE", "SURFACE", "META", "FONT", "ARMATURE", "LATTICE",
    "EMPTY", "LIGHT", "CAMERA", "SPEAKER", "VOLUME", "GPENCIL",
    "POINTCLOUD",
))


def object_icon(obj):
    """The outliner icon for an object's type, or a neutral one."""
    if obj.type in KNOWN_ICON_TYPES:
        return "OUTLINER_OB_" + obj.type
    return "OBJECT_DATA"


def _is_descendant(candidate, ancestor):
    node = candidate.parent
    while node is not None:
        if node is ancestor:
            return True
        node = node.parent
    return False
