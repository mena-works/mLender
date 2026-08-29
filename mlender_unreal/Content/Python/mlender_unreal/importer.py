# -*- coding: utf-8 -*-
"""Package import orchestration for Unreal.

The order matters in one place above all others: the schema is validated
**before** the level is cleared. An incompatible package must cost the user
nothing, and this receiver is as destructive as the Blender one.
"""

import json
import os
import time

import unreal

from .constants import (
    ACTOR_FOLDER_ROOT,
    CONTENT_ROOT,
    HIDDEN_LAYER_NAME,
    SUPPORTED_SCHEMA_VERSIONS,
)
from .alembic import import_alembic
from .asrig import apply_as_rigs
from .animation import import_animation as build_animation
from .animation import read_motion
from .aovs import build_render_config
from .cameras import import_cameras as build_cameras
from .curves import import_curves
from .empties import import_transforms
from .images import reset_cache as reset_texture_cache
from .instancers import import_instancers
from .lights import import_lights as build_lights
from .materials import (
    build_material,
    reset_cache as reset_material_cache,
    reused_count as reused_material_count,
    set_update_mode as set_material_update,
)
from .particles import import_particles
from .report import write_report
from .selection import (
    build_include_index,
    prune_motion,
    prune_package_data,
)
from .sets import import_sets as build_sets
from .standins import import_standins
from .volumes import import_volumes
from .meshes import (
    apply_visibility,
    assign_materials,
    build_record_index,
    discard_duplicate_meshes,
    find_mesh_record,
    actor_identities,
    package_material_index,
    import_fbx_scene,
    imported_mesh_actors,
    mesh_component,
    share_static_mesh,
    skeletal_actors,
    organise_actor,
    resolve_fbx_path,
)
from .scene import clear_level, level_actors, purge_generated_content
from .transforms import position_scale
from .utils import normalize_folder, scalar


def read_package_json(package_folder):
    """The package's JSON sidecar, under either the 2.x or the 1.x name."""
    folder = normalize_folder(package_folder)
    if not os.path.isdir(folder):
        raise RuntimeError(
            "Package folder does not exist: {0}".format(package_folder)
        )
    candidates = [
        name for name in sorted(os.listdir(folder))
        if name.endswith("_scene.json") or name.endswith("_lookdev.json")
    ]
    if not candidates:
        raise RuntimeError(
            "No package JSON found in {0}".format(folder)
        )
    with open(os.path.join(folder, candidates[0]), "r") as handle:
        return json.load(handle)


def validate_schema_version(package_data):
    """Reject a package this build cannot read, before anything is touched."""
    if not isinstance(package_data, dict):
        raise ValueError("Package JSON must be an object.")
    version = package_data.get("schema_version", 1)
    try:
        version = int(version)
    except (TypeError, ValueError):
        raise ValueError(
            "Package schema version is not a number: {0!r}".format(version)
        )
    if version not in SUPPORTED_SCHEMA_VERSIONS:
        raise ValueError(
            "Package schema version {0} is not supported by this build; "
            "expected one of {1}. Update the Unreal plugin to match the Maya "
            "exporter.".format(
                version,
                ", ".join(str(item) for item in SUPPORTED_SCHEMA_VERSIONS),
            )
        )
    return version


def _component_asset(actor):
    """The mesh asset an actor's component holds, or None."""
    component = mesh_component(actor)
    if component is None:
        return None
    for prop in ("static_mesh", "skeletal_mesh_asset"):
        try:
            asset = component.get_editor_property(prop)
        except Exception:
            asset = None
        if asset is not None:
            return asset
    return None


class _Phases(object):
    """Where an import's time goes, phase by phase, for the report.

    The Maya report has the same. A fourteen minute import names nothing;
    measured on a shot, the guess was the FBX and the truth was deleting the
    duplicate mesh assets, which only the phases could show.
    """

    def __init__(self):
        self.started = time.time()
        self.last = self.started
        self.marks = []

    def done(self, label):
        now = time.time()
        self.marks.append((label, now - self.last))
        self.last = now

    def total(self):
        return time.time() - self.started


def import_scene_package(
    package_folder,
    package_data=None,
    import_scale=1.0,
    power_scale=None,
    keep_existing_lights=False,
    import_lights=True,
    import_cameras=True,
    import_animation=True,
    import_sets=True,
    active_camera="",
    reveal_hidden_layer=False,
    include_paths=None,
    update_materials=True,
):
    package_folder = normalize_folder(package_folder)
    if package_data is None:
        package_data = read_package_json(package_folder)
    # First, and deliberately: an incompatible package must not cost a level.
    validate_schema_version(package_data)
    # The selection next, for the same reason: an empty or matchless
    # selection raises here, before anything is cleared. Everything
    # downstream reads the pruned copy, so the builders need no guards.
    package_data, selection_stats, dropped_meshes = prune_package_data(
        package_data, include_paths
    )
    include_index = build_include_index(include_paths)
    fbx_path = resolve_fbx_path(package_folder, package_data)

    warnings = []
    phases = _Phases()
    reset_material_cache()
    reset_texture_cache()
    set_material_update(update_materials)

    # Unreal has no "save if the file has a path" equivalent that is safe to
    # call unattended, so the level is cleared without saving. The tool's
    # destructiveness is documented; silently overwriting a user's save is not
    # something to add on top of it.
    clear_level(warnings, keep_lighting=keep_existing_lights)
    purge_generated_content(warnings, keep_materials=not update_materials)
    phases.done("clearing the level and the previous send")

    before = actor_identities()
    import_fbx_scene(
        fbx_path, warnings, package_data.get("package_name") or "",
        import_scale)

    actors = imported_mesh_actors(before)
    phases.done("fbx import ({0} mesh actors)".format(len(actors)))
    if not actors:
        raise RuntimeError(
            "The FBX import produced no static mesh actors. Assets from a "
            "previous send under {0} that could not be removed are the known "
            "cause: the importer reuses assets of the same name and places "
            "nothing. Delete that folder and send again.".format(CONTENT_ROOT)
        )

    unreal_scale = position_scale(package_data, import_scale)
    # The energy model was measured against metres, so it keeps the metre
    # scale. Positions are in Unreal centimetres. Two different numbers on
    # purpose; using one for both is a factor of 100 or of 10,000.
    metre_scale = (
        scalar(package_data.get("meters_per_maya_unit"), 0.01)
        * max(scalar(import_scale, 1.0), 1e-6)
    )

    mesh_records = list(package_data.get("meshes") or [])
    # Which objects have their visibility driven per frame. Read here rather
    # than inside the animation pass because the mesh loop below has to know:
    # an object the sequence will show later must not be parked in the hidden
    # layer, which no track can lift.
    motion = read_motion(package_folder, package_data, warnings)
    # Pruned rather than left to fail: the motion player's "no actor
    # matched" warning is for loss, and a deliberately filtered mover
    # reported as loss teaches the reader to ignore that warning.
    motion, motion_dropped = prune_motion(motion, include_index)
    blinking_paths = set()
    for path, track in (motion.get("objects") or {}).items():
        if track.get("visible"):
            blinking_paths.add(path)
    for record in mesh_records:
        if record.get("visibility_samples"):
            blinking_paths.add(record.get("mesh_path"))

    record_index = build_record_index(mesh_records)

    # The FBX imports whole -- Interchange has no per-object filter -- so the
    # selection is applied to the level: actors whose record the selection
    # dropped are destroyed and their assets handed to the same discard pass
    # that removes duplicate meshes. The kept index is probed first, with a
    # throwaway set, so nothing a ticked record claims can ever be destroyed:
    # a label collision errs toward keeping, and an extra survivor surfaces
    # as the ordinary "no record matched" warning below.
    filtered_out = 0
    orphan_assets = []
    if include_paths is not None:
        if dropped_meshes:
            dropped_index = build_record_index(dropped_meshes)
            survivors = []
            doomed = []
            kept_probe = set()
            dropped_probe = set()
            subsystem = unreal.get_editor_subsystem(
                unreal.EditorActorSubsystem)
            for actor in actors:
                if find_mesh_record(actor, record_index,
                                    kept_probe) is not None:
                    survivors.append(actor)
                    continue
                if find_mesh_record(actor, dropped_index,
                                    dropped_probe) is None:
                    survivors.append(actor)
                    continue
                asset = _component_asset(actor)
                if asset is not None:
                    orphan_assets.append(asset)
                doomed.append(actor)
                filtered_out += 1
            # One call for the lot: destroy_actors is the batch the editor
            # provides for exactly this, and eleven thousand one-by-one
            # destroys were measured at 6.2 s.
            if doomed:
                try:
                    subsystem.destroy_actors(doomed)
                except Exception:
                    for actor in doomed:
                        subsystem.destroy_actor(actor)
            keep_asset_paths = set()
            for actor in survivors:
                asset = _component_asset(actor)
                if asset is not None:
                    keep_asset_paths.add(asset.get_path_name())
            orphan_assets = [
                asset for asset in orphan_assets
                if asset.get_path_name() not in keep_asset_paths
            ]
            actors = survivors
        per_kind = ", ".join(
            "{0} {1}".format(count, kind)
            for kind, count in sorted(selection_stats["dropped"].items())
            if count
        )
        movers_note = ""
        if motion_dropped:
            movers_note = " and {0} mover(s)".format(motion_dropped)
        cache_note = ""
        alembic_count = int(
            ((package_data or {}).get("alembic") or {}).get("mesh_count") or 0
        )
        if alembic_count:
            cache_note = (
                " The Alembic cache imports whole and was not filtered "
                "({0} cached mesh(es)).".format(alembic_count)
            )
        warnings.append(
            "The selection left out {0} object(s) ({1}){2}; {3} mesh "
            "actor(s) the FBX brought were removed.{4}".format(
                selection_stats["total_dropped"], per_kind or "none",
                movers_note, filtered_out, cache_note,
            )
        )
        phases.done(
            "selection filter ({0} actors removed)".format(filtered_out)
        )

    used = set()
    material_cache = {}
    assignments = []
    # Built once: a slot whose name is not on the mesh record it matched is
    # looked up here. Interchange gives a skinned character one skeletal mesh
    # with a slot per shading group, so most of those slots name materials the
    # package filed under the other meshes Maya had.
    material_index = package_material_index(package_data)
    # Keyed on the Maya DAG path, which is what the sampled motion names its
    # objects by. A label would have to be guessed back into a path, and two
    # meshes of one short name in different groups would be indistinguishable.
    actors_by_path = {}
    hidden_actors = 0
    matched = 0
    # One asset per distinct geometry. The FBX brings a mesh asset per
    # object and a layout is mostly copies of a few blocks: measured, 12028
    # meshes over 4068 shapes, and every one of the 7960 copies was an asset
    # to build, save and load. The exporter keys each mesh on what it looks
    # like; actors with the same key point at the first asset that arrived
    # and the rest are dropped before anything saves them.
    canonical_meshes = {}
    duplicate_meshes = []
    shared = 0

    for actor in actors:
        record = find_mesh_record(actor, record_index, used)
        if record is None:
            warnings.append(
                'No Maya mesh record matched "{0}".'.format(
                    actor.get_actor_label()
                )
            )
            continue
        used.add(id(record))
        matched += 1
        if record.get("mesh_path"):
            actors_by_path[record["mesh_path"]] = actor
        # Before the materials: they go on the component, and the slot names
        # they are matched by come from whichever asset the component holds.
        if share_static_mesh(actor, record.get("geometry_key"),
                             canonical_meshes, duplicate_meshes):
            shared += 1
        organise_actor(actor, record, ACTOR_FOLDER_ROOT)
        if apply_visibility(actor, record,
                            record.get("mesh_path") in blinking_paths):
            hidden_actors += 1
        names = assign_materials(
            actor, record, material_cache, package_folder,
            build_material, warnings, package_index=material_index,
        )
        assignments.append({
            "actor": actor.get_actor_label(),
            "maya_mesh": record.get("mesh_full_name") or record.get("mesh"),
            "materials": names,
        })
    if not update_materials:
        reused = reused_material_count()
        # Asked for, so said plainly -- and with the count, so "my tweak
        # survived" is a fact the report states rather than a hope.
        warnings.append(
            "Material update is off: {0} existing material(s) were kept as "
            "they are; anything new was still built.".format(reused)
        )
    phases.done("records, sharing and materials ({0} meshes)".format(matched))
    discarded = discard_duplicate_meshes(
        duplicate_meshes + orphan_assets, warnings)
    phases.done("discarding {0} duplicate mesh assets".format(
        len(duplicate_meshes) + len(orphan_assets)))

    if import_lights:
        light_result = build_lights(
            package_data, unreal_scale, metre_scale, power_scale, warnings
        )
    else:
        # Asked for, so said plainly: a scene sent without its lights looks
        # like a scene whose lights failed to arrive.
        wanted = len((package_data or {}).get("lights") or [])
        if wanted:
            warnings.append(
                "Lighting transfer is off, so the package's {0} light(s) were "
                "not built. The level keeps whatever lighting it "
                "had.".format(wanted)
            )
        light_result = {"light_count": 0, "object_count": 0, "dome_count": 0}
    # What was switched off is counted and said. A kind disabled in silence
    # looks identical to a kind that failed to arrive.
    skipped_kinds = []
    if import_cameras:
        camera_result = build_cameras(
            package_data, unreal_scale, warnings, wanted=active_camera
        )
    else:
        skipped_kinds.append("cameras")
        wanted_cameras = len((package_data or {}).get("cameras") or [])
        if wanted_cameras:
            warnings.append(
                "Camera transfer is off, so the package's {0} camera(s) "
                "were not built.".format(wanted_cameras)
            )
        camera_result = {"camera_count": 0, "active": ""}
    phases.done("lights and cameras")

    # Everything the JSON rebuilds rather than the FBX. Order is dependency
    # order: locators first, because other kinds may hang under them, and the
    # instancers last, because they need both their points and their source
    # meshes to exist.
    # Mesh actors by label, which is the name a Maya record's leaf becomes.
    # Both the instancer sources and the locator parents look themselves up
    # here, so it is built once.
    mesh_actors = {}
    for actor in actors:
        try:
            mesh_actors[actor.get_actor_label()] = actor
        except Exception:
            continue

    # The cache first among the rebuilt kinds: it holds meshes the FBX does not
    # carry at all, and its materials come from the same cache the FBX meshes
    # filled, so it has to run after those are built and before anything that
    # counts what is in the level.
    alembic_result = import_alembic(
        package_data, package_folder, material_cache, warnings,
        build_material=build_material,
    )

    empty_result = import_transforms(
        package_data, unreal_scale, warnings, mesh_actors
    )
    curve_result = import_curves(package_data, unreal_scale, warnings)
    volume_result = import_volumes(
        package_data, unreal_scale, package_folder, warnings
    )
    standin_result = import_standins(
        package_data, unreal_scale, package_folder, warnings
    )
    particle_result = import_particles(package_data, unreal_scale, warnings)
    instancer_result = import_instancers(
        package_data, unreal_scale, warnings, mesh_actors,
        particle_result["positions"],
    )
    # After the meshes are named and materialled: the manifest is attached to
    # the skeletal actors the FBX brought.
    as_result = apply_as_rigs(package_data, actors, warnings)

    # The layer holding what Maya hid, switched off once everything is in
    # it -- unless the user asked to see those objects, in which case
    # switching it off would undo the one thing they set.
    if hidden_actors and not reveal_hidden_layer:
        try:
            unreal.get_editor_subsystem(
                unreal.LayersSubsystem).set_layer_visibility(
                    HIDDEN_LAYER_NAME, False)
        except Exception as exc:
            warnings.append(
                "{0} object(s) Maya had hidden are in the \"{1}\" layer but "
                "it could not be switched off ({2}); hide it by hand in the "
                "Layers panel.".format(hidden_actors, HIDDEN_LAYER_NAME, exc)
            )

    # Sets name actors, so this runs after everything that creates them.
    if import_sets:
        set_result = build_sets(package_data, warnings)
    else:
        skipped_kinds.append("sets")
        wanted_sets = (
            len((package_data or {}).get("selection_sets") or [])
            + len((package_data or {}).get("object_sets") or [])
            + len((package_data or {}).get("display_layers") or [])
        )
        if wanted_sets:
            warnings.append(
                "Sets and layers are off, so {0} of them were not rebuilt "
                "as Unreal layers.".format(wanted_sets)
            )
        set_result = {"set_count": 0, "layer_count": 0}
    phases.done("caches, locators, curves, volumes, particles, sets")

    # Last, and it has to be: every track binds an actor by its label, so
    # nothing that spawns one may run after this.
    if import_animation:
        animation_result = build_animation(
            package_data, unreal_scale, metre_scale, power_scale, warnings,
            package_folder=package_folder, actors_by_path=actors_by_path,
            motion=motion, discard_unresolved=include_paths is not None,
            # Which camera the cut points at. The cameras pass already chose
            # it -- the one Maya marks renderable, or the one asked for -- and
            # a second choice here would be a second opinion nobody asked for.
            active_camera=camera_result.get("active", ""),
        )
    else:
        skipped_kinds.append("animation")
        if ((package_data or {}).get("animation") or {}).get("enabled"):
            warnings.append(
                "Animation is off, so nothing was keyed and no sequence was "
                "built; everything stands at the pose the FBX placed it in."
            )
        animation_result = {
            "sequence_path": "", "track_count": 0, "key_count": 0,
            "skeletal_animated": 0, "motion_objects": 0, "motion_keys": 0,
            "motion_player": "", "motion_asset": "",
        }
    phases.done("animation ({0} movers on the player)".format(
        animation_result.get("motion_objects", 0)))

    # Render passes are Movie Render Queue configuration, not level contents,
    # so this produces the config the user renders with rather than an actor.
    aov_result = build_render_config(
        package_data, animation_result.get("sequence_path"), warnings
    )
    phases.done("render config")

    # Maya's own warnings first: they describe what never left the scene,
    # which is a different thing from what this build could not rebuild.
    carried_warnings = carry_export_warnings(package_data, warnings)
    _report_uncarried(package_data, warnings)

    result = {
        "package_folder": package_folder,
        "export_warning_count": carried_warnings,
        "fbx_path": fbx_path,
        "actor_count": len(actors),
        "mesh_count": matched,
        "mesh_asset_count": len(canonical_meshes),
        "mesh_shared_count": shared,
        "mesh_discarded_count": discarded,
        "hidden_count": hidden_actors,
        "material_count": len(material_cache),
        "light_count": light_result["light_count"],
        "dome_count": light_result["dome_count"],
        "camera_count": camera_result["camera_count"],
        "active_camera": camera_result["active"],
        # Which camera the sequence is cut to, which is not the same
        # question: a shot can hold a camera the cut never names.
        "cut_camera": animation_result.get("cut_camera", ""),
        "skeletal_count": len(skeletal_actors(actors)),
        "as_rig_count": as_result["as_rig_count"],
        "as_skeletal_actors": as_result["as_skeletal_actors"],
        "alembic_count": alembic_result["alembic_count"],
        "alembic_materials": alembic_result["alembic_materials"],
        "transform_count": empty_result["transform_count"],
        "transform_parented": empty_result["parented"],
        "curve_count": curve_result["curve_count"],
        "curve_splines": curve_result["curve_splines"],
        "volume_count": volume_result["volume_count"],
        "volume_loaded": volume_result["volume_loaded"],
        "standin_count": standin_result["standin_count"],
        "standin_loaded": standin_result["standin_loaded"],
        "particle_count": particle_result["particle_count"],
        "instancer_count": instancer_result["instancer_count"],
        "instance_count": instancer_result["instance_count"],
        "sequence_path": animation_result["sequence_path"],
        "animation_track_count": animation_result["track_count"],
        "animation_key_count": animation_result["key_count"],
        "skeletal_animated": animation_result.get("skeletal_animated", 0),
        "motion_object_count": animation_result.get("motion_objects", 0),
        "motion_key_count": animation_result.get("motion_keys", 0),
        "motion_player": animation_result.get("motion_player", ""),
        "motion_asset_path": animation_result.get("motion_asset", ""),
        "render_config_path": aov_result["render_config_path"],
        "aov_passes": aov_result["aov_passes"],
        "aov_reported": aov_result["aov_reported"],
        "set_count": set_result["set_count"],
        "layer_count": set_result["layer_count"],
        "skipped_kinds": skipped_kinds,
        "selection_active": include_paths is not None,
        "selection_dropped_count": selection_stats["total_dropped"],
        "filtered_out_count": filtered_out,
        "materials_reused": reused_material_count(),
        "assignments": assignments,
        "warnings": warnings,
        "timings": list(phases.marks),
        "total_seconds": phases.total(),
    }
    # Last: one file to hand over instead of scrolling the Output Log.
    try:
        engine = unreal.SystemLibrary.get_engine_version()
    except Exception:
        engine = ""
    result["report_path"] = write_report(result, engine)
    return result


def carry_export_warnings(package_data, warnings):
    """Repeat what Maya said, where the person who has to act on it is.

    The exporter writes its warnings into the package -- what did not travel,
    what was tessellated, what froze because the frame range was not exported
    -- and until now nothing read them. Every one of them was written for
    somebody sitting in front of this application, and none of them arrived
    here. A scene sent with Export Animation off produced no sequence, no
    visibility keys and no explanation on either side.
    """
    said = [
        str(line) for line in
        ((package_data or {}).get("export_warnings") or []) if line
    ]
    for line in said:
        warnings.append("Maya said: {0}".format(line))
    return len(said)


def _report_uncarried(package_data, warnings):
    """Name every kind this build leaves behind.

    The lookdev core is meshes, materials, lights and cameras. Everything else
    the package can carry is listed here with its count, because the failure
    this project fears most is the user believing something arrived when it did
    not. This is the coverage.py idea applied to the receiver.
    """
    kinds = (
        ("skeleton_root_motion", "skeleton root motion tracks",
         "the FBX take is assigned to the skeletal actor and plays, but the "
         "sampled world truth is not re-keyed on top of it -- doing that "
         "wrongly would double the motion rather than correct it"),
        ("constraints", "Maya constraints",
         "Unreal has no equivalent; the FBX bake already carries the motion "
         "they produced"),
    )
    for key, label, reason in kinds:
        items = package_data.get(key) or []
        try:
            count = len(items)
        except TypeError:
            count = 0
        if count:
            warnings.append(
                "{0} {1} were in the package and did not travel: {2}.".format(
                    count, label, reason
                )
            )

