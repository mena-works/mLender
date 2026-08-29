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
import re

import unreal

from .constants import (
    GENERATED_TAG,
    HIDDEN_LAYER_NAME,
    MESH_CONTENT_PATH,
    PIPELINE_CONTENT_PATH,
    SCENE_IMPORT_PIPELINES,
)
from .utils import decoded_name, fbx_style_name, safe_asset_name, scalar

# What Interchange appends to a material name it had to make unique.
_NCL_SUFFIX = re.compile(r"_ncl_\d+$")


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


def keep_source_normals(warnings, import_scale=1.0):
    """Copies of the scene import pipelines that keep the file's normals.

    They also carry the import scale. Everything else in this package is
    placed from the JSON and multiplied by ``position_scale``, but the meshes
    come through Interchange and nothing here touches their transforms -- so
    an import scale that did not reach these pipelines would move the motion,
    the cameras and the locators while leaving the geometry where it was.
    Interchange's own knob is a global offset transform, and the scene
    pipeline reads it (InterchangeGenericScenesPipeline.cpp:234), so the
    actors move with their meshes.

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
    scale = max(scalar(import_scale, 1.0), 1e-6)
    scaled = 0
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
            else:
                copy = unreal.load_asset(target)
            # Written on every send, not only when the copy is created: the
            # copy is kept between sends, so a scale set once would be
            # whatever the previous send asked for.
            if copy is not None:
                try:
                    copy.set_editor_property(
                        "import_offset_uniform_scale", scale)
                    scaled += 1
                except Exception:
                    # Only one pipeline in the stack carries the offset; the
                    # other refusing it is the normal case, and the warning
                    # below covers the case where none of them took it.
                    pass
            unreal.EditorAssetLibrary.save_asset(target)
            copies.append("{0}.ML_{1}".format(target, name))
        except Exception as exc:
            warnings.append(
                "The import pipeline could not be prepared ({0}), so Unreal "
                "recomputes the normals and smooth surfaces arrive "
                "faceted.".format(exc)
            )
            return []
    if abs(scale - 1.0) > 1e-6 and not scaled:
        warnings.append(
            "An import scale of {0} was asked for, but no import pipeline "
            "accepted it, so the meshes arrived at their file size while "
            "everything placed from the JSON was scaled. Positions and "
            "geometry disagree by that factor.".format(scale)
        )
    return copies


def import_fbx_scene(fbx_path, warnings, package_name="", import_scale=1.0):
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
    overrides = keep_source_normals(warnings, import_scale)
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


def share_static_mesh(actor, key, canonical_by_key, duplicates):
    """Point an actor at the asset an identical mesh already brought.

    The first actor to arrive with a key keeps its own asset and becomes the
    one the rest point at; every later one hands its asset to ``duplicates``
    and takes the shared one. True when this actor now shares.

    Materials are untouched here on purpose: they go on the component, not
    the asset, so a red block and a blue block share the mesh and keep their
    colours. The slot *structure* is part of the key, so the shared asset
    has the slots every actor pointing at it expects.
    """
    if not key:
        return False
    component = mesh_component(actor)
    mesh = getattr(component, "static_mesh", None) if component else None
    if mesh is None:
        return False
    canonical = canonical_by_key.get(key)
    if canonical is None:
        canonical_by_key[key] = mesh
        return False
    try:
        if canonical.get_path_name() == mesh.get_path_name():
            return False
        if not component.set_static_mesh(canonical):
            return False
    except Exception:
        return False
    duplicates.append(mesh)
    return True


def discard_duplicate_meshes(duplicates, warnings):
    """Delete the assets nothing points at any more. Returns how many went.

    They are unsaved at this point -- the FBX import creates them in memory
    and nothing has written them -- so a delete that is refused costs
    nothing but the memory until the editor closes. It is still said, so an
    unsaved-assets prompt on exit has an explanation.
    """
    unique = {}
    for mesh in duplicates:
        try:
            unique[mesh.get_path_name()] = mesh
        except Exception:
            continue
    if not unique:
        return 0
    # Through the compiled module when it is there. The editor's delete walks
    # every object in memory looking for referencers, per asset -- measured,
    # 7960 of them cost nine minutes of a fourteen minute import -- and the
    # answer is known: nothing points at them, the components that did were
    # just pointed elsewhere. The module moves them out of their packages,
    # off the asset registry and onto the garbage list, measured instant.
    utility = getattr(unreal, "MLAssetUtility", None)
    if utility is not None:
        try:
            parked = int(utility.discard_unsaved_assets(list(unique.values())))
        except Exception:
            parked = 0
        if parked == len(unique):
            return parked
    # Without the module, the editor's own delete, batched: measured 30 ms an
    # asset against 190 ms one at a time.
    try:
        gone = bool(unreal.EditorAssetLibrary.delete_loaded_assets(
            list(unique.values())))
    except Exception:
        gone = False
    if not gone:
        warnings.append(
            "{0} duplicate mesh asset(s) were replaced by a shared one but "
            "could not be removed; they are unsaved and harmless, and go when "
            "the editor closes.".format(len(unique))
        )
        return 0
    return len(unique)


def is_mesh_actor(actor):
    static = getattr(unreal, "StaticMeshActor", None)
    skeletal = getattr(unreal, "SkeletalMeshActor", None)
    kinds = tuple(cls for cls in (static, skeletal) if cls is not None)
    return bool(kinds) and isinstance(actor, kinds)


def actor_identities():
    """A stable identity per actor in the level, for before/after comparison.

    The object path, not id(). Every call into the editor builds fresh Python
    wrappers, so an id is the address of a temporary that is freed the moment
    the list goes out of scope -- and the next wrappers land on those same
    addresses. Measured while importing into a level that already held twelve
    thousand actors: every one of the 11,014 that Interchange had just placed
    was matched against a stale id and reported as "already there", so the
    import looked like it had produced nothing at all.
    """
    subsystem = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
    identities = set()
    for actor in subsystem.get_all_level_actors() or []:
        try:
            identities.add(actor.get_path_name())
        except Exception:
            continue
    return identities


def imported_mesh_actors(before):
    """Mesh actors that were not in the level before the import.

    ``before`` is a set of object paths from :func:`actor_identities`.

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
        try:
            if actor.get_path_name() in before:
                continue
        except Exception:
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
            # The spelling the actor actually arrives under: escapes decoded,
            # punctuation replaced, doubled underscores kept. Without it the
            # only bridge from an FBXASC name to its actor is the sanitised
            # one, which collapses "__" and files two objects together.
            fbx_style_name(record.get("mesh") or ""),
            fbx_style_name(record.get("mesh_full_name") or ""),
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

    An exact name wins over a sanitised one, and that is not a nicety.
    safe_asset_name collapses repeated underscores, so "broken__shard" and
    "broken_shard" -- two different objects with two different shapes -- are
    filed under one key, and a bucket reached by an exact label can hold the
    other object's record. Measured on a real shot: 169 such collisions over
    324 meshes, every one of them between genuinely different geometry, and
    the object that lost the race was drawn with the winner's mesh 93 cm from
    where Maya put it. It read as a shard floating in mid air.
    """
    label = str(actor.get_actor_label())
    candidates = []
    seen = set()
    for key in (label, safe_asset_name(label)):
        for record in record_index.get(str(key), []):
            if id(record) in used or id(record) in seen:
                continue
            seen.add(id(record))
            candidates.append(record)
    if not candidates:
        return None
    for record in candidates:
        if label in (str(record.get("mesh") or ""),
                     str(record.get("mesh_full_name") or "")):
            return record
    for record in candidates:
        if label in (fbx_style_name(record.get("mesh") or ""),
                     fbx_style_name(record.get("mesh_full_name") or "")):
            return record
    for record in candidates:
        if label in (decoded_name(str(record.get("mesh") or "")),
                     decoded_name(str(record.get("mesh_full_name") or ""))):
            return record
    return candidates[0]


def slot_lookup_key(name):
    """The key a slot label is looked up by.

    Interchange appends ``_ncl_N`` when it has to make a material name unique,
    so the label an actor carries is not always the name the package stored --
    measured: three of a character's slots arrived as ``lambert18_ncl_1``,
    ``lambert20_ncl_1`` and ``lambert22_ncl_1`` for materials the package calls
    ``lambert18``, ``lambert20`` and ``lambert22``.
    """
    text = safe_asset_name(str(name or ""), fallback="")
    return _NCL_SUFFIX.sub("", text)


def package_material_index(package_data):
    """Every Maya material in the package, keyed by name.

    A skinned character arrives from Interchange as **one** skeletal mesh
    carrying a slot per shading group, while the package still describes it as
    the many meshes Maya had. Matching a slot only against the record whose
    name the actor took then leaves every other slot on a placeholder.
    Measured on a character: the actor had 33 slots, the record it matched
    held 1, and 30 of the 33 slot names were materials the package did carry --
    on other records.

    A slot name says which **material** it is, not which object it belongs to,
    so this lookup is package-wide.

    Each key holds the **candidates**, not one answer. A referenced rig brings
    its own copy of a shader under a namespace, so a scene really can hold two
    different materials called "lambert20" -- measured on a character: five
    such names, and Interchange hit the same collision, spelling the second
    one "lambert20_ncl_1". Nothing here can tell which slot wants which, so
    the caller is handed both and says so rather than guessing; this project
    has already shipped one name collision that drew the wrong shape.
    """
    index = {}
    for record in (package_data or {}).get("meshes") or []:
        for item in record.get("materials") or []:
            name = item.get("material")
            if not name:
                continue
            identity = item.get("material_full_name") or name
            for key in (slot_lookup_key(name), slot_lookup_key(identity)):
                if not key:
                    continue
                candidates = index.setdefault(key, [])
                known = [
                    c.get("material_full_name") or c.get("material")
                    for c in candidates
                ]
                if identity not in known:
                    candidates.append(item)
    return index


def assign_materials(actor, record, material_cache, package_folder,
                     build_material, warnings, package_index=None):
    """Replace the FBX's placeholder materials with the rebuilt ones.

    Slots are matched by the material's own name rather than by index: the FBX
    importer names each material asset after the Maya shader that produced it,
    and an index is only right while nothing reorders.

    ``package_index`` is the whole package's materials by name, consulted only
    after this mesh's own records and after the positional cases below -- a
    shared asset carries the slot names of the mesh that brought it, so there
    the index is the evidence and the name is not.
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
            elif len(records) == max(count, 1):
                # A shared asset carries the slot names of the mesh that
                # brought it. This actor has the same slot structure -- that
                # is what sharing was keyed on -- and its Maya materials come
                # in slot order, so the index is the match.
                item = records[index]
            else:
                # Last: the package's other records. Interchange collapses a
                # skinned character into one skeletal mesh holding a slot per
                # shading group, and the record it matched describes only one
                # of the meshes Maya had -- so the rest of the slots name
                # materials that are in the package, just filed elsewhere.
                candidates = (package_index or {}).get(
                    slot_lookup_key(slot_label)) or []
                if len(candidates) == 1:
                    item = candidates[0]
                elif candidates:
                    # Naming them is the difference between a grey slot the
                    # user can act on and one they cannot.
                    warnings.append(
                        'Mesh "{0}" slot {1} ("{2}") names {3} different Maya '
                        "materials ({4}); nothing was assigned because the "
                        "slot does not say which. Renaming one of them in "
                        "Maya resolves it.".format(
                            actor.get_actor_label(), index, slot_label,
                            len(candidates),
                            ", ".join(sorted(
                                str(c.get("material_full_name")
                                    or c.get("material"))
                                for c in candidates)),
                        )
                    )
                    continue
            if item is None:
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


def apply_visibility(actor, record, blinks=False):
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
    if blinks:
        # Its visibility is the sequence's to drive, so it is left alone. The
        # layer below is an editor switch and a Sequencer visibility track
        # cannot lift one: measured on a shot, 98 of 300 objects that blink on
        # when they break were parked in it at the frame the package was
        # anchored to, and never appeared again however far the ruler was
        # dragged. What is left on screen is the blocks that have not broken,
        # which is why the shot was reported as not moving at all.
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
