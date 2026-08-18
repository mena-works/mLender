# -*- coding: utf-8 -*-
"""Package import orchestration for Unreal.

The order matters in one place above all others: the schema is validated
**before** the level is cleared. An incompatible package must cost the user
nothing, and this receiver is as destructive as the Blender one.
"""

import json
import os

import unreal

from .constants import (
    ACTOR_FOLDER_ROOT,
    SUPPORTED_SCHEMA_VERSIONS,
)
from .alembic import import_alembic
from .asrig import apply_as_rigs
from .animation import import_animation
from .aovs import build_render_config
from .cameras import import_cameras
from .curves import import_curves
from .empties import import_transforms
from .images import reset_cache as reset_texture_cache
from .instancers import import_instancers
from .lights import import_lights
from .materials import build_material, reset_cache as reset_material_cache
from .particles import import_particles
from .report import write_report
from .sets import import_sets
from .standins import import_standins
from .volumes import import_volumes
from .meshes import (
    assign_materials,
    build_record_index,
    find_mesh_record,
    import_fbx_scene,
    imported_mesh_actors,
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


def import_scene_package(
    package_folder,
    package_data=None,
    import_scale=1.0,
    power_scale=None,
):
    package_folder = normalize_folder(package_folder)
    if package_data is None:
        package_data = read_package_json(package_folder)
    # First, and deliberately: an incompatible package must not cost a level.
    validate_schema_version(package_data)
    fbx_path = resolve_fbx_path(package_folder, package_data)

    warnings = []
    reset_material_cache()
    reset_texture_cache()

    # Unreal has no "save if the file has a path" equivalent that is safe to
    # call unattended, so the level is cleared without saving. The tool's
    # destructiveness is documented; silently overwriting a user's save is not
    # something to add on top of it.
    clear_level(warnings)
    purge_generated_content(warnings)

    before = {id(actor) for actor in level_actors()}
    import_fbx_scene(fbx_path, warnings)

    actors = imported_mesh_actors(before)
    if not actors:
        raise RuntimeError("The FBX import produced no static mesh actors.")

    unreal_scale = position_scale(package_data, import_scale)
    # The energy model was measured against metres, so it keeps the metre
    # scale. Positions are in Unreal centimetres. Two different numbers on
    # purpose; using one for both is a factor of 100 or of 10,000.
    metre_scale = (
        scalar(package_data.get("meters_per_maya_unit"), 0.01)
        * max(scalar(import_scale, 1.0), 1e-6)
    )

    mesh_records = list(package_data.get("meshes") or [])
    record_index = build_record_index(mesh_records)
    used = set()
    material_cache = {}
    assignments = []
    matched = 0

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
        organise_actor(actor, record, ACTOR_FOLDER_ROOT)
        names = assign_materials(
            actor, record, material_cache, package_folder,
            build_material, warnings,
        )
        assignments.append({
            "actor": actor.get_actor_label(),
            "maya_mesh": record.get("mesh_full_name") or record.get("mesh"),
            "materials": names,
        })

    light_result = import_lights(
        package_data, unreal_scale, metre_scale, power_scale, warnings
    )
    camera_result = import_cameras(package_data, unreal_scale, warnings)

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
        package_data, package_folder, material_cache, warnings
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

    # Sets name actors, so this runs after everything that creates them.
    set_result = import_sets(package_data, warnings)

    # Last, and it has to be: every track binds an actor by its label, so
    # nothing that spawns one may run after this.
    animation_result = import_animation(
        package_data, unreal_scale, metre_scale, power_scale, warnings
    )

    # Render passes are Movie Render Queue configuration, not level contents,
    # so this produces the config the user renders with rather than an actor.
    aov_result = build_render_config(
        package_data, animation_result.get("sequence_path"), warnings
    )

    _report_uncarried(package_data, warnings)

    result = {
        "package_folder": package_folder,
        "fbx_path": fbx_path,
        "actor_count": len(actors),
        "mesh_count": matched,
        "material_count": len(material_cache),
        "light_count": light_result["light_count"],
        "dome_count": light_result["dome_count"],
        "camera_count": camera_result["camera_count"],
        "active_camera": camera_result["active"],
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
        "render_config_path": aov_result["render_config_path"],
        "aov_passes": aov_result["aov_passes"],
        "aov_reported": aov_result["aov_reported"],
        "set_count": set_result["set_count"],
        "layer_count": set_result["layer_count"],
        "assignments": assignments,
        "warnings": warnings,
    }
    # Last: one file to hand over instead of scrolling the Output Log.
    try:
        engine = unreal.SystemLibrary.get_engine_version()
    except Exception:
        engine = ""
    result["report_path"] = write_report(result, engine)
    return result


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

