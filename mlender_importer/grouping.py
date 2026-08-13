# -*- coding: utf-8 -*-
"""Maya groups for Blender: a collection you can actually move.

A Maya group is a transform that owns its contents, so moving the group
moves everything under it. A Blender collection is only a container --
measured, it has no transform at all, not even a hidden one, so no amount
of add-on code can make a collection itself movable.

What can be done is to give a collection the transform it lacks: an empty
that lives in the collection and parents its top-level objects. From then
on the collection behaves the way an artist coming from Maya expects,
because the thing they grab is a real parent. The two are marked as a
pair, so the tool can find one from the other.

Nothing here is specific to an imported package. Group any selection, or
turn any collection you already have into a group; the import path just
happens to use the same function to finish the job on the groups it
rebuilt.
"""

import bpy
from mathutils import Vector

GROUP_PROP = "ml_group"
# Collections the tool keeps for its own purposes -- light linking, Maya
# sets and display layers. Grouping must not move objects out of these:
# membership is what makes those features work.
AUXILIARY_PREFIXES = ("ML_Link_", "ML_Shadow_")
AUXILIARY_MARKERS = ("ml_maya_set", "ml_maya_layer")


def is_auxiliary(collection):
    if collection.name.startswith(AUXILIARY_PREFIXES):
        return True
    return any(marker in collection.keys() for marker in AUXILIARY_MARKERS)


def group_empty_for(collection):
    """The empty standing in as this collection's transform, or None."""
    if collection is None:
        return None
    marker = collection.get(GROUP_PROP)
    for obj in collection.objects:
        if obj.type != "EMPTY":
            continue
        if obj.get(GROUP_PROP) and obj.get(GROUP_PROP) == marker:
            return obj
    return None


def collection_for(empty):
    """The collection an empty is the group transform of, or None."""
    marker = (empty or {}).get(GROUP_PROP) if empty else None
    if not marker:
        return None
    for collection in empty.users_collection:
        if collection.get(GROUP_PROP) == marker:
            return collection
    return None


def parent_collections(collection):
    """Every collection that holds this one, the scene's root included."""
    holders = []
    scenes = [scene.collection for scene in bpy.data.scenes]
    for candidate in list(bpy.data.collections) + scenes:
        if candidate is collection:
            continue
        if collection.name in candidate.children:
            holders.append(candidate)
    return holders


def top_level(objects):
    """Objects whose parent is not itself in the set.

    Parenting only the tops is what keeps a hierarchy intact: reparenting
    a child that already hangs off another member would flatten it.
    """
    members = set(objects)
    return [obj for obj in objects if obj.parent not in members]


def selection_centre(objects):
    total = Vector((0.0, 0.0, 0.0))
    for obj in objects:
        total += obj.matrix_world.translation
    return total / max(1, len(objects))


def attach_to_empty(empty, objects):
    """Parent objects under the empty, keeping their world transforms.

    Counts what actually moved: an object already hanging off this empty
    is left alone, so running over a group twice reports nothing rather
    than re-parenting everything to where it already is.
    """
    attached = 0
    for obj in objects:
        if obj is empty or obj.parent is empty or _is_ancestor(obj, empty):
            continue
        world = obj.matrix_world.copy()
        obj.parent = empty
        obj.matrix_parent_inverse = empty.matrix_world.inverted_safe()
        obj.matrix_world = world
        attached += 1
    return attached


def make_collection_group(collection, centre_pivot=False, empty_name=None):
    """Give a collection a transform, so it behaves like a Maya group.

    Returns (empty, attached). An existing group's empty is reused rather
    than doubled, which is what lets this run over an import that already
    has its own group empties without disturbing them.
    """
    if collection is None or is_auxiliary(collection):
        return (None, 0)
    empty = group_empty_for(collection)
    members = [obj for obj in collection.objects if obj is not empty]
    if empty is None:
        empty = _adopt_or_create(collection, members, centre_pivot,
                                 empty_name)
    return (empty, attach_to_empty(empty, top_level(members)))


def _adopt_or_create(collection, members, centre_pivot, empty_name):
    """Reuse the transform a collection already has, or make one.

    An imported Maya group arrives as an empty named after the group with
    the collection's own objects already under it. Adopting that one
    instead of adding a second is what keeps the tool from building a
    group on top of a group.
    """
    named = bpy.data.objects.get(collection.name)
    if (named is not None and named.type == "EMPTY"
            and named in set(collection.objects)):
        empty = named
    else:
        empty = bpy.data.objects.new(empty_name or collection.name, None)
        empty.empty_display_type = "PLAIN_AXES"
        empty.empty_display_size = 0.5
        if centre_pivot and members:
            empty.location = selection_centre(members)
        collection.objects.link(empty)
    empty["ml_generated"] = True
    empty[GROUP_PROP] = collection.name
    collection[GROUP_PROP] = collection.name
    return empty


def group_objects(objects, name="group", centre_pivot=False, parent=None):
    """Maya's Ctrl+G: a new group holding the given objects.

    The group is both an empty and a collection of the same name, marked
    as a pair: the empty is what moves, the collection is what Blender's
    own outliner shows as a folder. Members move into the collection, but
    never out of the tool's own auxiliary collections -- light linking and
    Maya sets are membership, and dropping them would break both.

    Maya puts a fresh group's transform at the origin, so that is the
    default here; ``centre_pivot`` puts it at the selection's centre
    instead, which is what most artists reach for next.
    """
    objects = [obj for obj in objects if obj is not None]
    if not objects:
        return (None, None, 0)

    collection = bpy.data.collections.new(name)
    collection["ml_generated"] = True
    collection[GROUP_PROP] = collection.name
    (parent or bpy.context.scene.collection).children.link(collection)

    empty = bpy.data.objects.new(collection.name, None)
    empty.empty_display_type = "PLAIN_AXES"
    empty.empty_display_size = 0.5
    if centre_pivot:
        empty.location = selection_centre(objects)
    empty["ml_generated"] = True
    empty[GROUP_PROP] = collection.name
    collection.objects.link(empty)

    for obj in objects:
        for current in list(obj.users_collection):
            if is_auxiliary(current):
                continue
            current.objects.unlink(obj)
        if obj.name not in collection.objects:
            collection.objects.link(obj)
    return (empty, collection, attach_to_empty(empty, top_level(objects)))


def ungroup(empty, remove_collection=True):
    """Undo a group: children keep their place, the transform goes.

    Returns how many objects were freed. The collection goes with it by
    default, because a folder left behind after its group is gone is the
    kind of leftover that accumulates.
    """
    if empty is None:
        return 0
    collection = collection_for(empty)
    children = list(empty.children)
    for child in children:
        world = child.matrix_world.copy()
        child.parent = empty.parent
        if empty.parent is not None:
            child.matrix_parent_inverse = (
                empty.parent.matrix_world.inverted_safe())
        child.matrix_world = world
    if collection is not None and remove_collection:
        targets = [obj for obj in collection.objects if obj is not empty]
        # A collection has no users_collection -- that is an object's
        # field -- so the ones holding it are found by looking.
        for parent_collection in parent_collections(collection):
            for obj in targets:
                if obj.name not in parent_collection.objects:
                    parent_collection.objects.link(obj)
        bpy.data.collections.remove(collection)
    elif collection is not None:
        del collection[GROUP_PROP]
    bpy.data.objects.remove(empty, do_unlink=True)
    return len(children)


def finish_imported_groups(warnings=None):
    """Make every rebuilt Maya group behave like one.

    The FBX brings a group's meshes in already parented to the empty it
    made for the group, but everything rebuilt from the JSON beside them
    -- curves, locators, volumes, standins -- only lands in the matching
    collection. Measured on the test package: moving ``curveGroup`` moved
    the meshes and left the curve behind, which is not what the Maya
    scene says.

    An animated group is left alone and reported instead: lights, cameras
    and the rest are sampled in **world** space, so their keys already
    carry the group's motion and parenting them to it would apply that
    motion twice.
    """
    attached = 0
    for collection in bpy.data.collections:
        if not collection.get("ml_maya_group") or is_auxiliary(collection):
            continue
        empty = bpy.data.objects.get(collection.name)
        if empty is None or empty.type != "EMPTY":
            continue
        if _is_animated(empty):
            loose = [obj for obj in collection.objects
                     if obj is not empty and obj.parent is None]
            if loose and warnings is not None:
                warnings.append(
                    'Group "{0}" is animated, so {1} object(s) in it were '
                    "left unparented; their own keys already carry the "
                    "group's motion.".format(collection.name, len(loose))
                )
            continue
        empty[GROUP_PROP] = collection.name
        collection[GROUP_PROP] = collection.name
        members = [obj for obj in collection.objects
                   if obj is not empty and obj.parent is None]
        attached += attach_to_empty(empty, members)
    return attached


def _is_animated(obj):
    action = getattr(getattr(obj, "animation_data", None), "action", None)
    return action is not None


def _is_ancestor(candidate, node):
    """True when candidate sits above node in the parent chain."""
    walker = node.parent if node is not None else None
    while walker is not None:
        if walker is candidate:
            return True
        walker = walker.parent
    return False


# ---------------------------------------------------------------- operators
class ML_OT_group_selected(bpy.types.Operator):
    bl_idname = "mlender.group_selected"
    bl_label = "Group Selected"
    bl_description = (
        "Maya's Ctrl+G: put the selection under a new group that can be "
        "moved as one, shown as a collection in Blender's outliner"
    )
    bl_options = {"REGISTER", "UNDO"}

    name: bpy.props.StringProperty(name="Name", default="group")
    centre_pivot: bpy.props.BoolProperty(
        name="Pivot at Centre",
        description=(
            "Put the group's transform at the selection's centre. Maya "
            "puts a new group at the origin, which is the default here"
        ),
        default=False,
    )

    @classmethod
    def poll(cls, context):
        return bool(context.selected_objects)

    def execute(self, context):
        empty, collection, attached = group_objects(
            list(context.selected_objects), self.name or "group",
            self.centre_pivot,
        )
        if empty is None:
            self.report({"WARNING"}, "Nothing selected to group.")
            return {"CANCELLED"}
        for obj in context.selected_objects:
            obj.select_set(False)
        empty.select_set(True)
        context.view_layer.objects.active = empty
        self.report({"INFO"}, "Grouped {0} object(s) under {1}.".format(
            attached, empty.name))
        return {"FINISHED"}


class ML_OT_ungroup(bpy.types.Operator):
    bl_idname = "mlender.ungroup"
    bl_label = "Ungroup"
    bl_description = (
        "Dissolve the selected group, leaving its contents where they are"
    )
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        empties = [obj for obj in context.selected_objects
                   if obj.type == "EMPTY" and obj.get(GROUP_PROP)]
        if not empties:
            self.report({"WARNING"}, "Select a group to ungroup.")
            return {"CANCELLED"}
        freed = 0
        for empty in empties:
            freed += ungroup(empty)
        self.report({"INFO"}, "Freed {0} object(s).".format(freed))
        return {"FINISHED"}


def _menu_collection(context):
    """The collection a menu was opened on, or the active one."""
    found = getattr(context, "collection", None)
    if found is not None:
        return found
    layer = getattr(context.view_layer, "active_layer_collection", None)
    return getattr(layer, "collection", None)


class ML_OT_collection_group(bpy.types.Operator):
    bl_idname = "mlender.collection_group"
    bl_label = "Make Group (Movable)"
    bl_description = (
        "Give this collection a transform so moving it moves its "
        "contents, the way a Maya group does"
    )
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        collection = _menu_collection(context)
        if collection is None:
            self.report({"WARNING"}, "No collection here.")
            return {"CANCELLED"}
        if is_auxiliary(collection):
            self.report({"WARNING"},
                        "That collection is one mLender keeps for itself.")
            return {"CANCELLED"}
        empty, attached = make_collection_group(collection)
        if empty is None:
            return {"CANCELLED"}
        self.report({"INFO"}, "{0} now moves {1} object(s).".format(
            empty.name, attached))
        return {"FINISHED"}


class ML_OT_collection_select_group(bpy.types.Operator):
    bl_idname = "mlender.collection_select_group"
    bl_label = "Select Group Transform"
    bl_description = (
        "Select the transform that moves this collection, so it can be "
        "grabbed straight away"
    )
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        collection = _menu_collection(context)
        empty = group_empty_for(collection)
        if empty is None:
            empty = bpy.data.objects.get(getattr(collection, "name", ""))
        if empty is None or empty.type != "EMPTY":
            self.report({"WARNING"},
                        "This collection has no group transform yet.")
            return {"CANCELLED"}
        for obj in context.selected_objects:
            obj.select_set(False)
        empty.select_set(True)
        context.view_layer.objects.active = empty
        return {"FINISHED"}


def _draw_collection_menu(self, context):
    layout = self.layout
    layout.separator()
    layout.operator(ML_OT_collection_group.bl_idname, icon="OUTLINER_OB_EMPTY")
    layout.operator(ML_OT_collection_select_group.bl_idname,
                    icon="RESTRICT_SELECT_OFF")


def _draw_object_menu(self, context):
    layout = self.layout
    layout.separator()
    layout.operator(ML_OT_group_selected.bl_idname, icon="OUTLINER_OB_EMPTY")
    layout.operator(ML_OT_ungroup.bl_idname, icon="X")


# The menus this hangs itself on, all measured present on 4.1 and 5.2.
MENU_APPENDS = (
    ("OUTLINER_MT_collection", _draw_collection_menu),
    ("VIEW3D_MT_object", _draw_object_menu),
)


def register_menus():
    for name, function in MENU_APPENDS:
        menu = getattr(bpy.types, name, None)
        if menu is not None:
            menu.append(function)


def unregister_menus():
    for name, function in MENU_APPENDS:
        menu = getattr(bpy.types, name, None)
        if menu is not None:
            try:
                menu.remove(function)
            except Exception:
                pass


CLASSES = (
    ML_OT_group_selected,
    ML_OT_ungroup,
    ML_OT_collection_group,
    ML_OT_collection_select_group,
)
