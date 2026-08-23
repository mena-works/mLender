# -*- coding: utf-8 -*-
"""FBX import and material assignment.

Interchange brings the meshes, their hierarchy, their transforms and the unit
conversion, all measured correct: a cube exported at Maya (0, 40, 0) arrives at
Unreal (0, 0, 40) with no help from this package. So there is deliberately no
transform code here -- doing the conversion again on top of a correct one is
the double-application mistake this project has already made once with light
energy.

What the FBX cannot bring is the materials, which is the same division of
labour the Blender receiver uses.
"""

import os

import unreal

from .constants import (
    GENERATED_TAG,
    HIDDEN_LAYER_NAME,
    MESH_CONTENT_PATH,
    PIPELINE_CONTENT_PATH,
    SCENE_IMPORT_PIPELINES,
)
from .utils import decoded_name, safe_asset_name


def resolve_fbx_path(package_folder, package_data):
    """The package's FBX, found inside the package before it is given up on.

    A package records the absolute path its exporting machine wrote, so a
    package that has moved resolves nothing unless it is looked for here.
    """
    recorded = str((package_data or {}).get("fbx_file") or "").strip()
    if recorded and os.path.isfile(recorded):
        return recorded
    if package_folder and os.path.isdir(package_folder):
        name = str((package_data or {}).get("package_name") or "").strip()
        if name:
            candidate = os.path.join(package_folder, name + ".fbx")
            if os.path.isfile(candidate):
                return candidate
        for entry in sorted(os.listdir(package_folder)):
            if entry.lower().endswith(".fbx"):
                return os.path.join(package_folder, entry)
    raise RuntimeError(
        "The package has no FBX this build can find: {0}".format(
            recorded or package_folder
        )
    )


def send_content_path(package_name):
    """Where this send's meshes go: a folder of its own.

    Importing twice into the same folder is not a second import to
    Interchange, it is a re-import. Measured on a level that had been saved
    after an earlier send: the second one logged "Failed to find object
    /Game/mLender/Meshes/..." for every asset the purge had just removed, then
    imported 3722 meshes and placed **no actors at all** -- it was updating a
    scene whose assets and actors were both gone.

    So the folder has to be one nothing has been imported into yet -- not
    merely one named after the package. Two sends of the same package name
    land in the same folder, and the second is a re-import again; and the
    purge that used to clear the way is skipped when there are thousands of
    assets, because deleting those one at a time in an open editor does not
    finish. A free name costs a folder and settles both.
    """
    name = safe_asset_name(str(package_name or ""), "") or "Send"
    base = MESH_CONTENT_PATH + "/" + name
    try:
        if not unreal.EditorAssetLibrary.does_directory_exist(base):
            return base
        for index in range(2, 1000):
            candidate = "{0}_{1}".format(base, index)
            if not unreal.EditorAssetLibrary.does_directory_exist(candidate):
                return candidate
    except Exception:
        pass
    return base


def keep_source_normals(warnings):
    """Copies of the scene import pipelines that keep the file's normals.

    Interchange recomputes normals by default, from the file's edge smoothing
    rather than from its normals. Maya writes both, and they disagree:
    measured on a shot, a sphere's normals are smooth -- 98 vertices for 96
    faces -- while every one of its 192 edges is marked hard. Recomputing
    from the second delivered 576 vertices for 192 triangles, which is a
    faceted ball.

    The stack is copied whole rather than replaced by one pipeline of ours:
    it holds two, and the second is what creates the actors. Overriding with
    a single pipeline returns True and produces a level with nothing in it.

    Returns the paths to pass as overrides, or an empty list, in which case
    the import proceeds the way it always did.
    """
    copies = []
    for source in SCENE_IMPORT_PIPELINES:
        name = source.rsplit(".", 1)[-1]
        target = "{0}/ML_{1}".format(PIPELINE_CONTENT_PATH, name)
        try:
            if not unreal.EditorAssetLibrary.does_asset_exist(target):
                # Loaded first: duplicate_asset returns None for an engine
                # asset that is not already in memory, and this one is not
                # loadable through EditorAssetLibrary at all.
                unreal.load_asset(source)
                copy = unreal.EditorAssetLibrary.duplicate_asset(
                    source, target)
                if copy is None:
                    warnings.append(
                        "The import pipeline could not be copied from {0}, "
                        "so Unreal recomputes the normals and smooth "
                        "surfaces arrive faceted.".format(source)
                    )
                    return []
                try:
                    common = copy.get_editor_property(
                        "common_meshes_properties")
                except Exception:
                    common = None
                if common is not None:
                    # Mutated in place: assigning the property back is
                    # refused, and the refusal is silent enough to look like
                    # it worked.
                    common.set_editor_property("recompute_normals", False)
                unreal.EditorAssetLibrary.save_asset(target)
            copies.append("{0}.ML_{1}".format(target, name))
        except Exception as exc:
            warnings.append(
                "The import pipeline could not be prepared ({0}), so Unreal "
                "recomputes the normals and smooth surfaces arrive "
                "faceted.".format(exc)
            )
            return []
    return copies


def import_fbx_scene(fbx_path, warnings, package_name=""):
    """Import the FBX into the open level, hierarchy and all.

    Uses Interchange's scene import, which was measured to spawn one
    StaticMeshActor per Maya transform under a single RootNode actor, carrying
    the Maya transform names. import_level is a Level object rather than a
    flag -- the engine rejects a bool -- so it is left unset and the open world
    is the target.
    """
    manager = unreal.InterchangeManager.get_interchange_manager_scripted()
    source = manager.create_source_data(fbx_path)
    parameters = unreal.ImportAssetParameters()
    parameters.is_automated = True
    overrides = keep_source_normals(warnings)
    if overrides:
        parameters.override_pipelines = [
            unreal.SoftObjectPath(path) for path in overrides]
    if not manager.import_scene(
            send_content_path(package_name), source, parameters):
        raise RuntimeError(
            "Interchange refused to import {0}".format(fbx_path)
        )
    return True


def mesh_component(actor):
    """The mesh component of a static or a skeletal mesh actor.

    Both kinds arrive from one scene import and everything downstream -- record
    matching, material assignment, counting -- wants to treat them alike.
    """
    for name in ("static_mesh_component", "skeletal_mesh_component"):
        component = getattr(actor, name, None)
        if component is not None:
            return component
    for cls_name in ("StaticMeshComponent", "SkeletalMeshComponent"):
        cls = getattr(unreal, cls_name, None)
        if cls is None:
            continue
        try:
            component = actor.get_component_by_class(cls)
        except Exception:
            component = None
        if component is not None:
            return component
    return None


def is_mesh_actor(actor):
    static = getattr(unreal, "StaticMeshActor", None)
    skeletal = getattr(unreal, "SkeletalMeshActor", None)
    kinds = tuple(cls for cls in (static, skeletal) if cls is not None)
    return bool(kinds) and isinstance(actor, kinds)


def imported_mesh_actors(before_labels):
    """Mesh actors that were not in the level before the import.

    **Skeletal actors count too.** Interchange's scene import already brings
    skinned meshes in as SkeletalMesh with a Skeleton and a PhysicsAsset --
    measured on this fixture: 4 skeletal meshes beside 47 static ones, with no
    pipeline override of any kind. An earlier version of this function filtered
    on StaticMeshActor alone, so those four arrived in the level and were then
    ignored: unmatched to their Maya record, unnamed, and left holding the
    FBX's placeholder materials.
    """
    subsystem = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
    actors = []
    for actor in subsystem.get_all_level_actors() or []:
        if not is_mesh_actor(actor):
            continue
        if id(actor) in before_labels:
            continue
        actors.append(actor)
    return actors


def skeletal_actors(actors):
    cls = getattr(unreal, "SkeletalMeshActor", None)
    if cls is None:
        return []
    return [actor for actor in actors if isinstance(actor, cls)]


def build_record_index(mesh_records):
    """Maya mesh records keyed by every name an actor might arrive under.

    Indexed once rather than scanned per actor: on the Blender side the same
    per-object scan was quadratic and cost sixty seconds on 1600 meshes.

    Both the short name and the namespace-qualified one are keys, because a
    referenced asset arrives with its namespace and two references of one asset
    are otherwise indistinguishable.
    """
    index = {}
    for record in mesh_records:
        for key in (
            record.get("mesh"),
            record.get("mesh_full_name"),
            safe_asset_name(record.get("mesh") or ""),
            safe_asset_name(record.get("mesh_full_name") or ""),
            # And the same names with their FBX escapes decoded: the actor
            # arrives spelled the way the format spells it, not the way Maya
            # stored it.
            decoded_name(record.get("mesh") or ""),
            safe_asset_name(decoded_name(record.get("mesh") or "")),
            safe_asset_name(decoded_name(record.get("mesh_full_name") or "")),
        ):
            if not key:
                continue
            index.setdefault(str(key), []).append(record)
    return index


def find_mesh_record(actor, record_index, used):
    """The Maya record for an actor, by label.

    Unreal strips the namespace colon from an actor label, so the sanitised
    forms are in the index as well. A record is only used once, which is what
    keeps two meshes of the same short name in different groups apart.
    """
    label = actor.get_actor_label()
    for key in (label, safe_asset_name(label)):
        for record in record_index.get(str(key), []):
            if id(record) in used:
                continue
            return record
    return None


def assign_materials(actor, record, material_cache, package_folder,
                     build_material, warnings):
    """Replace the FBX's placeholder materials with the rebuilt ones.

    Slots are matched by the material's own name rather than by index: the FBX
    importer names each material asset after the Maya shader that produced it,
    and an index is only right while nothing reorders.
    """
    component = mesh_component(actor)
    mesh = None
    if component is not None:
        # A skeletal component names it differently; both are asked for rather
        # than branching on the actor's class, which a future kind would break.
        for name in ("static_mesh", "skeletal_mesh"):
            mesh = getattr(component, name, None)
            if mesh is not None:
                break
    records = [
        item for item in (record.get("materials") or [])
        if item.get("material")
    ]
    if mesh is None:
        # Silence here was a real defect: a re-import into a content root that
        # already held a previous send left the actors with no static mesh, and
        # this returned an empty list, so the import reported zero materials
        # and no warning at all. A mesh actor with no mesh is exactly the kind
        # of thing the user has to be told about.
        if records:
            warnings.append(
                'Mesh "{0}" arrived with no static mesh asset, so its {1} Maya '
                "material(s) could not be assigned. Re-importing into a "
                "content root that already held a previous send is the known "
                "cause; delete {2} and send again.".format(
                    actor.get_actor_label(), len(records), MESH_CONTENT_PATH
                )
            )
        return []
    if not records:
        return []
    by_name = {}
    for item in records:
        for key in (item.get("material"), item.get("material_full_name")):
            if key:
                by_name[safe_asset_name(str(key))] = item

    assigned = []
    # A skeletal mesh has no static_materials, so the component's own count is
    # the answer that works for both kinds.
    try:
        count = component.get_num_materials() if component else 0
    except Exception:
        count = 0
    if not count:
        try:
            count = len(mesh.static_materials)
        except Exception:
            count = 0

    for index in range(max(count, 1)):
        existing = None
        try:
            existing = component.get_material(index)
        except Exception:
            existing = None
        slot_label = safe_asset_name(
            existing.get_name() if existing is not None else ""
        )
        item = by_name.get(slot_label)
        if item is None:
            # One slot and one Maya material is the unambiguous case even when
            # the names disagree, which happens when the FBX renamed a
            # material for uniqueness.
            if len(records) == 1 and max(count, 1) == 1:
                item = records[0]
            else:
                warnings.append(
                    'Mesh "{0}" slot {1} ("{2}") matched no Maya material; '
                    "the placeholder was left in place.".format(
                        actor.get_actor_label(), index, slot_label
                    )
                )
                continue
        key = (
            item.get("material_full_name") or item.get("material") or ""
        )
        material = material_cache.get(key)
        if material is None:
            material = build_material(item, package_folder, warnings)
            material_cache[key] = material
        try:
            component.set_material(index, material)
            assigned.append(material.get_name())
        except Exception as exc:
            warnings.append(
                'Mesh "{0}" slot {1} could not take its material: {2}'.format(
                    actor.get_actor_label(), index, exc
                )
            )
    return assigned


def apply_visibility(actor, record):
    """Hide an actor the Maya scene had hidden.

    The package has said so all along -- 4843 of the 7106 meshes in one shot
    carry visibility.visible false, colliders among them -- and this receiver
    never read it, so every collision hull and every hidden proxy arrived in
    the level in plain sight. The Blender side has read it from the start.

    Both flags, because they are not the same thing: hidden-in-game is saved
    with the level and is what a render obeys, and the editor's own flag is
    what stops it being drawn in the viewport. Measured: the second one is
    only exposed as "temporarily" hidden, so it holds for this session and a
    reopened level shows the actor again -- which is worth knowing rather
    than pretending.
    """
    visibility = (record or {}).get("visibility") or {}
    if visibility.get("visible") is not False:
        return False
    hidden = False
    try:
        actor.set_actor_hidden_in_game(True)
        hidden = True
    except Exception:
        pass
    # And into the layer, which is what makes it stay hidden. The actor flag
    # Python can reach for the editor is "temporarily" hidden: it holds for
    # the session and is gone when the level is opened again, so a collider
    # hidden at import time was back in view on the next open.
    try:
        unreal.get_editor_subsystem(unreal.LayersSubsystem).add_actor_to_layer(
            actor, HIDDEN_LAYER_NAME)
    except Exception:
        try:
            actor.set_is_temporarily_hidden_in_editor(True)
        except Exception:
            pass
    return hidden


def organise_actor(actor, record, folder_root):
    """Put an actor in a folder mirroring its Maya group trail."""
    groups = [
        str(part) for part in (record.get("groups") or []) if str(part).strip()
    ]
    path = "/".join([folder_root] + groups) if groups else folder_root
    try:
        actor.set_folder_path(path)
    except Exception:
        pass
    try:
        actor.tags = [GENERATED_TAG]
    except Exception:
        pass
    return path
