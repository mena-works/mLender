# -*- coding: utf-8 -*-
"""Package creation: folder numbering, FBX + JSON writing, atomic cleanup."""
from __future__ import absolute_import

import datetime
import io
import json
import os
import re
import shutil
import zipfile

import maya.cmds as cmds

from .bake import BakeContext
from .constants import (
    BUILD_VERSION,
    ALEMBIC_FILE_SUFFIX,
    BAKE_FOLDER_NAME,
    DEFAULT_BAKE_RESOLUTION,
    EXPORT_SCHEMA_VERSION,
    PACKAGE_PREFIX,
    TOOL_NAME,
)
from .animation import (
    animated_material_channels,
    animation_info,
    frozen_animation_kinds,
    material_animation_entries,
    sample_records,
)
from .cameras import camera_record, camera_sample, scene_camera_shapes
from .curves import curve_records, scene_curve_shapes
from .report import write_report
from .render import render_record
from .particles import (
    particle_records,
    particle_sample,
    resolve_samples,
    scene_particle_shapes,
)
from .alembic import (
    animated_cache_roots,
    deformed_shapes,
    triangulated,
    cache_roots,
    cache_only_shapes,
    export_alembic,
    rig_deformed,
    under_roots,
)
from .instancers import instancer_records, scene_instancers
from .coverage import coverage_warnings
from .standins import scene_standin_shapes, standin_records
from .volumes import scene_volume_shapes, volume_records
from .aovs import scene_aovs
from .asrig import as_rig_records
from .rigging import (
    constraint_records,
    root_motion_sample,
    scene_joints,
    skeleton_root_records,
)
from .tessellate import (
    restore as restore_tessellation,
    tessellate_scene,
)
from .sets import (
    display_layer_records,
    scene_display_layers,
    scene_selection_sets,
    selection_set_records,
)
from .transforms import scene_transforms, transform_records
from .collect import collect_package_files
from .fbx import export_fbx
from .lights import (
    light_record,
    light_sample,
    linked_mesh_names,
    scene_light_shapes,
    scene_uses_light_linking,
    scene_uses_shadow_linking,
    shadow_linked_mesh_names,
)
from .mayautils import (
    color_management_info,
    current_frame,
    maya_linear_unit,
    maya_path,
    meters_per_maya_unit,
    parent_of,
)
from .meshes import (
    mesh_records as mesh_records_for,
    mesh_transforms,
    scene_mesh_shapes,
    selected_light_count,
    visibility_animated,
    visibility_sample,
)


PACKAGE_PATTERN = re.compile(
    r"^" + re.escape(PACKAGE_PREFIX) + r"(\d+)$",
    re.IGNORECASE,
)


def maya_version():
    try:
        return str(cmds.about(version=True))
    except Exception:
        return ""


def renderer_name():
    """Which renderer the scene is set to, for the report header."""
    try:
        return str(cmds.getAttr("defaultRenderGlobals.currentRenderer") or "")
    except Exception:
        return ""


def export_scene(
    output_folder,
    selected_only=False,
    bake_procedurals=True,
    bake_resolution=DEFAULT_BAKE_RESOLUTION,
    collect_textures_into_package=False,
    export_animation=False,
    frame_start=None,
    frame_end=None,
    frame_step=None,
    export_alembic_cache=False,
    cache_animated_meshes=False,
    archive_package=False,
):
    """Write a numbered package folder holding the FBX and the scene JSON.

    Package creation is atomic: any failure removes both files and the folder
    so a half written package is never picked up by the importer.
    """
    output_folder = normalize_folder(output_folder)
    if not os.path.isdir(output_folder):
        os.makedirs(output_folder)

    package_name = next_package_name(output_folder)
    package_folder = os.path.join(output_folder, package_name)
    os.makedirs(package_folder)
    fbx_path = os.path.join(package_folder, package_name + ".fbx")
    json_path = os.path.join(package_folder, package_name + "_scene.json")
    alembic_path = os.path.join(
        package_folder, package_name + ALEMBIC_FILE_SUFFIX
    )
    # Named before the try, so the cleanup can remove it whether or not the
    # export got as far as writing one.
    archive_path = ""

    warnings = []
    bake_context = BakeContext(
        os.path.join(package_folder, BAKE_FOLDER_NAME),
        resolution=bake_resolution,
        enabled=bake_procedurals,
        warnings=warnings,
    )

    # Before discovery, because discovery starts at ls(type="mesh") and a
    # NURBS surface is not one. The stand-ins are ordinary meshes by the time
    # anything looks, so materials, groups, sets and coverage all treat them
    # as the surfaces they stand in for.
    tessellation = tessellate_scene(warnings)
    try:
        mesh_shapes = scene_mesh_shapes(selected_only)
        if not mesh_shapes:
            raise RuntimeError(
                "Nothing selected contains an exportable mesh."
                if selected_only
                else "The Maya scene contains no exportable mesh."
            )
        if selected_only:
            lights_in_selection = selected_light_count()
            if lights_in_selection:
                warnings.append(
                    "Selection held {0} light(s); lighting is always exported "
                    "in full, so they were not filtered.".format(
                        lights_in_selection
                    )
                )
        # One material usually covers many meshes, so its channels are read
        # once and shared. A shader that baked is deliberately not cached:
        # a bake belongs to the mesh whose UVs it was made against.
        export_cache = {}
        # One record per instance transform, so an instanced shape is not
        # reduced to whichever transform Maya happens to list first.
        mesh_records = [
            record
            for shape in mesh_shapes
            for record in mesh_records_for(shape, bake_context,
                                           export_cache)
        ]
        # Locators and empty nulls ride the JSON: the FBX only carries
        # what sits above an exported mesh, so on their own they were
        # dropped entirely.
        transform_list = transform_records(scene_transforms(selected_only))
        curve_list = curve_records(scene_curve_shapes(selected_only))
        joints = scene_joints(mesh_shapes, selected_only=selected_only)
        root_motion_list = skeleton_root_records(joints)
        all_transforms = (
            [r.get("transform_path") for r in mesh_records if r.get("transform_path")] +
            [r.get("transform_path") for r in transform_list if r.get("transform_path")] +
            joints
        )
        constraint_list = constraint_records(all_transforms)
        volume_list = volume_records(scene_volume_shapes(selected_only))
        standin_list = standin_records(
            scene_standin_shapes(selected_only)
        )
        particle_shapes = scene_particle_shapes(selected_only)
        particle_list = particle_records(particle_shapes)
        instancer_list = instancer_records(
            scene_instancers(selected_only)
        )
        aov_list = scene_aovs() if not selected_only else []
        as_rigs = as_rig_records()
        # Sets and layers may only name what this export carries. A scoped
        # export otherwise sent sets whose members were never in it.
        exported_paths = set(mesh_transforms(mesh_shapes))
        exported_paths.update(
            record["transform_path"] for record in transform_list
        )
        exported_paths.update(
            record["curve_path"] for record in curve_list
        )
        exported_paths.update(
            record["volume_path"] for record in volume_list
        )
        exported_paths.update(
            record["standin_path"] for record in standin_list
        )
        exported_paths.update(
            record["particle_path"] for record in particle_list
        )
        set_list = selection_set_records(
            scene_selection_sets(), warnings, exported_paths
        )
        layer_list = display_layer_records(
            scene_display_layers(), exported_paths
        )
        # Referenced assets repeat their names, so the ones that clash keep
        # their namespace rather than arriving as body.001.
        disambiguate_names(mesh_records, "mesh", "mesh_full_name")
        disambiguate_names(curve_list, "curve", "curve_full_name")
        disambiguate_names(volume_list, "volume", "volume_full_name")
        disambiguate_names(
            standin_list, "standin", "standin_full_name"
        )
        disambiguate_names(
            particle_list, "particle", "particle_full_name"
        )
        disambiguate_names(
            transform_list, "transform", "transform_full_name"
        )
        light_shapes = scene_light_shapes()
        camera_shapes = scene_camera_shapes()
        light_records = [light_record(shape) for shape in light_shapes]
        camera_records = [camera_record(shape) for shape in camera_shapes]

        # Said, not lost: anything renderable the export did not account
        # for. A discovery module per kind fixes the kinds already known and
        # leaves the next one silent, so the leftovers are counted instead.
        # Lights and cameras travel through the JSON rather than as geometry,
        # so their transforms count as accounted for.
        warnings.extend(coverage_warnings(
            exported_paths
            | set(parent_of(shape) for shape in light_shapes)
            | set(parent_of(shape) for shape in camera_shapes)
        ))

        _apply_light_linking(light_records, light_shapes, mesh_records)

        animation = animation_info(
            export_animation, frame_start, frame_end, frame_step
        )
        if animation["truncated"]:
            warnings.append(
                "Frame range clamped to {0} frames, ending at {1:g}.".format(
                    animation["frame_count"], animation["end"]
                )
            )
        # Keyed shader parameters with animation switched off freeze at the
        # export frame. That is a legitimate choice, but it was a silent one:
        # the package looked the same as one whose materials never moved.
        if not animation["enabled"]:
            # The rest of the scene's animation, which had no line of its own
            # until a real scene arrived with a flying camera and blinking
            # props and produced a package that mentioned neither.
            frozen = frozen_animation_kinds(
                camera_shapes, light_shapes, mesh_records
            )
            if frozen:
                warnings.append(
                    "This export is a single frame, so the scene's animation "
                    "did not travel: {0}. Tick Export Animation to carry "
                    "it.".format("; ".join(frozen))
                )
            keyed = animated_material_channels(mesh_records)
            if keyed:
                warnings.append(
                    "{0} material channel(s) are keyed in Maya and this export "
                    "is a single frame, so they arrive frozen at frame {1:g}: "
                    "{2}{3}. Tick Export Animation to carry them.".format(
                        len(keyed), current_frame(),
                        ", ".join(keyed[:6]),
                        " and others" if len(keyed) > 6 else "",
                    )
                )

        # Sampling steps the timeline, so it runs after the static records are
        # read and before the FBX, which bakes its own animation.
        sample_records(
            animation,
            [
                (record, _sampler(light_sample, shape))
                for record, shape in zip(light_records, light_shapes)
            ]
            + [
                (record, _sampler(camera_sample, shape))
                for record, shape in zip(camera_records, camera_shapes)
            ]
            + [
                (record, _sampler(particle_sample, shape))
                for record, shape in zip(particle_list, particle_shapes)
            ]
            # Only the meshes that actually blink. Visibility is a getAttr per
            # frame, cheap for a few objects and not for a whole scene over a
            # long range, and almost nothing in a scene is keyed this way.
            + [
                (record, _sampler(visibility_sample, record["mesh_path"]))
                for record in mesh_records
                if visibility_animated(record.get("mesh_path"))
            ]
            # Root joints' evaluated worlds: the FBX bake cannot be trusted
            # above the skeleton (an unexported group's connection-driven
            # motion is folded at its static value), so the truth travels
            # and the importer keys it onto the root bones directly.
            # Keyed shader parameters. Without these a keyframed roughness
            # or base colour froze at the export frame with nothing said.
            + material_animation_entries(mesh_records)
            + [
                (record, _sampler(root_motion_sample, record))
                for record in root_motion_list
            ],
        )
        root_motion_list = [
            record for record in root_motion_list
            if len(record.get("samples") or []) >= 2
        ]
        # The importer's calibration anchor: at the frame the scene sat on
        # during the FBX export, both fold failures are clean -- a static
        # fold holds this very frame's value, and a curve fold's error
        # lives on the armature object, which the anchor never touches.
        for record in root_motion_list:
            reference = root_motion_sample(record)
            reference["frame"] = current_frame()
            record["reference"] = reference
        # Renamed off the shared key: for a light this is a lighting sample
        # and for a particle object a set of positions, and a mesh carrying
        # something different under the same name invites a wrong reader.
        for record in mesh_records:
            samples = record.pop("samples", None)
            if samples:
                record["visibility_samples"] = samples
        # Particles are the one sampled thing that can refuse the bake, so
        # the samples are judged before they are written out.
        baked_particles = resolve_samples(particle_list)
        for record in particle_list:
            if record.get("count_varies"):
                warnings.append(
                    'Particle object "{0}" changes count over the frame '
                    "range, so only the exported frame travels.".format(
                        record.get("particle") or "?"
                    )
                )
            elif record.get("bake_too_large"):
                warnings.append(
                    'Particle object "{0}" is too dense to bake over this '
                    "range, so only the exported frame travels.".format(
                        record.get("particle") or "?"
                    )
                )
        # Alembic covers what FBX cannot: meshes whose points move, and
        # particle systems the vertex bake refused. A cached mesh leaves the
        # FBX entirely, or the same object would arrive twice, frozen once.
        # Caching everything that moves needs the cache itself, so the option
        # carries its own prerequisite rather than doing nothing when only one
        # of two checkboxes is ticked.
        use_cache = export_alembic_cache or cache_animated_meshes
        alembic = _write_alembic(
            alembic_path,
            mesh_shapes if use_cache else [],
            particle_list if use_cache else [],
            particle_shapes,
            animation,
            warnings,
            cache_animated_meshes=cache_animated_meshes,
        )
        cached = list(alembic.get("roots") or [])
        # The flag is what stops the importer building a second, frozen copy
        # of an object the cache already carries. Membership, not equality: a
        # root carries its whole subtree, so a still prop inside a moving
        # group travels in the cache with it.
        for record in mesh_records:
            if under_roots(record.get("mesh_path"), cached):
                record["alembic"] = True
        for record in particle_list:
            if under_roots(record.get("particle_path"), cached):
                record["alembic"] = True
        fbx_shapes = [
            shape for shape in mesh_shapes
            if not under_roots(parent_of(shape), cached)
        ]
        export_fbx(
            [
                transform
                for transform in mesh_transforms(mesh_shapes)
                if not under_roots(transform, cached)
            ] + joints,
            fbx_path,
            _fbx_animation(
                animation,
                cache_animated_meshes and not alembic.get("failed"),
                fbx_shapes,
                joints,
            ),
        )

        payload = {
            "schema_version": EXPORT_SCHEMA_VERSION,
            "tool_name": TOOL_NAME,
            "profile": "scene",
            "exported_at_utc": utc_timestamp(),
            "maya_scene": cmds.file(query=True, sceneName=True) or "",
            "package_name": package_name,
            "package_folder": maya_path(package_folder),
            "fbx_file": maya_path(fbx_path),
            "selected_only": bool(selected_only),
            "mesh_count": len(mesh_records),
            "meshes": mesh_records,
            "transform_count": len(transform_list),
            "render": render_record(),
            "selection_sets": set_list,
            "display_layers": layer_list,
            "object_sets": set_list,
            "aovs": aov_list,
            "as_rigs": as_rigs,
            "skeleton_root_motion": root_motion_list,
            "constraints": constraint_list,
            "curve_count": len(curve_list),
            "curves": curve_list,
            "volume_count": len(volume_list),
            "volumes": volume_list,
            "standin_count": len(standin_list),
            "standins": standin_list,
            "particle_count": len(particle_list),
            "particle_baked_count": baked_particles,
            "instancer_count": len(instancer_list),
            "instancers": instancer_list,
            "alembic": {
                "file": alembic.get("file") or "",
                "mesh_count": alembic.get("mesh_count") or 0,
                "particle_count": alembic.get("particle_count") or 0,
                "animated_count": alembic.get("animated_count") or 0,
            },
            "particles": particle_list,
            "transforms": transform_list,
            "light_count": len(light_records),
            "lights": light_records,
            "camera_count": len(camera_records),
            "cameras": camera_records,
            "baked_texture_count": len(bake_context.baked_files),
            "export_warnings": warnings,
            "maya_linear_unit": maya_linear_unit(),
            "meters_per_maya_unit": meters_per_maya_unit(),
            "animation": animation,
            "color_management": color_management_info(),
        }
        collected = {"collected": 0, "missing": 0, "textures": 0,
                     "files": 0, "folder": ""}
        if collect_textures_into_package:
            # After the payload is complete, so every record that names a
            # file exists and can be repointed at its copy in one pass.
            collected = collect_package_files(
                payload, package_folder, warnings
            )
            payload["collected_textures"] = collected
        write_json(json_path, payload)
        if archive_package:
            # One file to hand over. Written beside the folder rather than
            # instead of it: LiveLink and the importer both read the folder,
            # and an export that only produced an archive would break the
            # thing the tool does most.
            archive_path = archive_folder(package_folder)
    except Exception:
        remove_file(fbx_path)
        remove_file(json_path)
        remove_file(alembic_path)
        remove_file(archive_path)
        try:
            # rmtree rather than rmdir: baking may already have written
            # textures into the package, and a half written package must
            # not survive.
            shutil.rmtree(package_folder, ignore_errors=True)
        except Exception:
            pass
        raise
    finally:
        # The scene gets its surfaces and its names back whatever happened.
        restore_tessellation(tessellation)

    # Last, and never allowed to fail the export: the report is a
    # convenience, and losing a good package because its report could not be
    # written would be the tail wagging the dog.
    result = {
        "package_name": package_name,
        "package_folder": package_folder,
        "fbx_path": fbx_path,
        "json_path": json_path,
        "package_json": payload,
        "mesh_count": len(mesh_records),
        "light_count": len(light_records),
        "camera_count": len(camera_records),
        "baked_texture_count": len(bake_context.baked_files),
        "frame_count": animation["frame_count"],
        "collected_texture_count": collected.get("textures", 0),
        "collected_file_count": collected.get("files", 0),
        "archive_path": archive_path,
        "animated": animation["enabled"],
        "warnings": warnings,
    }
    result["report_path"] = write_report(
        result, BUILD_VERSION, maya_version(), renderer_name()
    )
    return result


def disambiguate_names(records, name_key, full_key):
    """Keep the namespace on names that would otherwise collide.

    A single referenced asset keeps clean short names. Two references of
    the same asset would both be "body", so both become "heroA:body" and
    "heroB:body" instead -- otherwise Blender numbers them body.001 and
    nothing says which reference either came from.

    Only the colliding ones change, so the common scene is untouched.
    """
    seen = {}
    for record in records:
        seen.setdefault(record.get(name_key), []).append(record)
    for name, group in seen.items():
        if len(group) < 2:
            continue
        for record in group:
            full = str(record.get(full_key) or "")
            if ":" in full:
                record[name_key] = full
    return records


def _apply_light_linking(light_records, light_shapes, mesh_records):
    """Record which meshes each light lights, when that is not all of them.

    Nothing is written for a scene that never broke a link, and nothing is
    written for a light that still lights everything: the importer's job is
    only to reproduce restrictions, and an absent field means no restriction.
    """
    uses_light = scene_uses_light_linking()
    uses_shadow = scene_uses_shadow_linking()
    if not uses_light and not uses_shadow:
        return 0

    lookup = {}
    every_mesh = set()
    for record in mesh_records:
        name = record.get("mesh") or ""
        if not name:
            continue
        every_mesh.add(name)
        for key in (
            record.get("mesh_full_name"),
            record.get("shape"),
            name,
        ):
            if key:
                lookup[str(key)] = name

    restricted = 0
    for record, shape in zip(light_records, light_shapes):
        transform = parent_of(shape)
        if uses_light:
            linked = linked_mesh_names(transform, lookup)
            if linked is not None and set(linked) != every_mesh:
                record["linked_meshes"] = linked
                restricted += 1
        if uses_shadow:
            casting = shadow_linked_mesh_names(transform, lookup)
            if casting is not None and set(casting) != every_mesh:
                record["shadow_meshes"] = casting
    return restricted


def _fbx_animation(animation, cache_animated_meshes, fbx_shapes, joints):
    """The animation settings the FBX should be written with.

    Baking is what makes an FBX carry motion, and it costs one scene
    evaluation per frame per node. On a layout of seven thousand meshes over a
    Bullet sim that was over an hour, nearly all of it spent baking objects
    that do not move.

    When every moving object was measured and sent to the cache, the FBX holds
    what is left, and what is left provably did not move -- so there is nothing
    for the bake to find. Two things still move without moving a transform,
    and both keep it on: a skeleton, whose motion is on the joints, and a
    deformer, whose motion is in the points.

    The caller is responsible for the third: a cache that was asked for the
    movers and could not be written leaves them in the FBX, where the bake is
    the only thing that would carry them.
    """
    if not animation.get("enabled") or not cache_animated_meshes:
        return animation
    if joints:
        return animation
    if deformed_shapes(fbx_shapes):
        return animation
    frozen = dict(animation)
    frozen["enabled"] = False
    return frozen


def _write_alembic(path, mesh_shapes, particle_list, particle_shapes,
                   animation, warnings, cache_animated_meshes=False):
    """Cache what FBX loses. Returns what the payload should say about it.

    Two things qualify on their own, and both were measured to need it: a mesh
    whose points are moved by a deformer, which FBX delivers frozen, and a
    particle object whose count changes, which no fixed vertex count can hold.

    ``cache_animated_meshes`` widens that to everything that moves, which is a
    different kind of need. A simulation is not lost by the FBX so much as by
    being a simulation: the solver writes a transform per frame with nothing
    keyed behind it, so what travels depends on whether the scene happened to
    be baked first. The cache carries the result either way.
    """
    empty = {
        "roots": [],
        "file": "",
        "mesh_count": 0,
        "particle_count": 0,
        "animated_count": 0,
        # Whether the cache was *asked* for something and could not deliver,
        # which is not the same as there being nothing to cache. The FBX bake
        # decision needs the difference: skipping the bake when the cache
        # failed would drop the motion twice over, silently.
        "failed": False,
    }
    if not animation.get("enabled"):
        if cache_animated_meshes:
            warnings.append(
                "Caching animated objects needs the animation range turned "
                "on, so nothing was cached."
            )
        return empty

    deformed = cache_only_shapes(mesh_shapes)
    varying = [
        shape
        for record, shape in zip(particle_list, particle_shapes)
        if record.get("count_varies") or record.get("bake_too_large")
    ]
    mesh_roots = cache_roots(deformed)
    animated_roots = []
    if cache_animated_meshes:
        # Measured rather than inferred, and measured over the whole
        # hierarchy: see moving_transforms. A root the deformed pass already
        # names is not repeated, and a moving group swallows the deformed
        # shapes hanging inside it.
        animated_roots = [
            root for root in animated_cache_roots(mesh_shapes, animation)
            if root not in mesh_roots
        ]
        mesh_roots = [
            root for root in mesh_roots
            if not under_roots(root, animated_roots)
        ]
    particle_roots = cache_roots(varying)
    roots = mesh_roots + animated_roots + particle_roots
    if not roots:
        if cache_animated_meshes:
            warnings.append(
                "Nothing in the scene moved over the exported range, so the "
                "cache holds no animated objects."
            )
        return empty

    # Unreal's Alembic reader refuses a face with more than four sides and
    # fails the entire file over one of them, so the shapes that are about to
    # travel are triangulated first -- as history, undone below, leaving the
    # Maya scene exactly as it was.
    undo = triangulated(
        [shape for shape in mesh_shapes
         if under_roots(parent_of(shape), roots)],
        warnings,
    )
    try:
        written = export_alembic(roots, path, animation)
    finally:
        if undo:
            try:
                cmds.delete(undo)
            except Exception:
                warnings.append(
                    "The temporary triangulation could not be removed from "
                    "the Maya scene; undo it before saving."
                )
    if not written:
        warnings.append(
            "Alembic cache could not be written, so {0} object(s) that need "
            "one travel as a single frame.".format(len(roots))
        )
        empty["failed"] = True
        return empty

    # A purely rig-deformed mesh rides the FBX as a posable armature
    # binding and never reaches this list. The ones here that still carry a
    # rig deformer do so alongside something FBX cannot express, so the
    # cache wins -- and what that costs is said out loud.
    rigged = rig_deformed(deformed)
    if rigged:
        warnings.append(
            "{0} cached mesh(es) carry a rig alongside other deformers; "
            "the cache holds the deformed result, and their rig cannot be "
            "posed in Blender.".format(len(rigged))
        )
    if animated_roots:
        # Worth saying rather than discovering. A cached object is geometry
        # per frame: it arrives as a cache rather than as a mesh with a
        # transform, so it is not instanced, it is larger on disk, and nobody
        # downstream can re-time it. That is the trade this option is.
        warnings.append(
            "{0} moving object(s) travel as an Alembic cache rather than as "
            "keyed geometry, simulations included. They arrive as cached "
            "geometry, so they are not instanced and cannot be "
            "re-animated.".format(len(animated_roots))
        )
    return {
        "roots": roots,
        "file": maya_path(path),
        "mesh_count": len(mesh_roots) + len(animated_roots),
        "particle_count": len(particle_roots),
        "animated_count": len(animated_roots),
    }


def _sampler(function, shape):
    """Bind a shape to a sampler so the timeline loop can stay generic."""
    def sample():
        return function(shape)
    return sample


def next_package_name(folder):
    """mLender_01, mLender_02, ... continuing past the highest existing one."""
    highest = 0
    if os.path.isdir(folder):
        for name in os.listdir(folder):
            if not os.path.isdir(os.path.join(folder, name)):
                continue
            match = PACKAGE_PATTERN.match(name)
            if match:
                highest = max(highest, int(match.group(1)))
    return "{0}{1:02d}".format(PACKAGE_PREFIX, highest + 1)


def utc_timestamp():
    """ISO-8601 UTC timestamp; utcnow() is deprecated from Python 3.12."""
    try:
        now = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)
    except AttributeError:
        now = datetime.datetime.utcnow()
    return now.isoformat() + "Z"


def default_export_folder():
    scene = cmds.file(query=True, sceneName=True) or ""
    if scene:
        return os.path.dirname(scene)
    try:
        return (
            cmds.workspace(query=True, rootDirectory=True)
            or os.path.expanduser("~")
        )
    except Exception:
        return os.path.expanduser("~")


def normalize_folder(path):
    if not path:
        raise ValueError("Choose an export location.")
    return os.path.abspath(os.path.expanduser(path))


def archive_folder(package_folder):
    """Zip a finished package into one file beside it, and return its path.

    For handing a package to somebody else. It pairs with collecting: an
    archive of a package that still points at the exporting machine's texture
    library is a zip of some paths, so the two are offered together in the UI
    and this says so rather than assuming the user knew.

    ``zipfile`` is standard library on every Maya this supports, so this adds
    no dependency.
    """
    archive_path = package_folder + ".zip"
    remove_file(archive_path)
    name = os.path.basename(package_folder)
    with zipfile.ZipFile(archive_path, "w", zipfile.ZIP_DEFLATED) as archive:
        for folder, folders, files in os.walk(package_folder):
            folders.sort()
            for item in sorted(files):
                full = os.path.join(folder, item)
                relative = os.path.relpath(full, package_folder)
                # The package folder is kept as the archive's top level, so
                # unzipping produces the folder the importer expects rather
                # than spilling a package into the user's downloads.
                archive.write(full, os.path.join(name, relative))
    return maya_path(archive_path)


def write_json(path, data):
    with io.open(path, "w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2, sort_keys=True)


def remove_file(path):
    try:
        if os.path.isfile(path):
            os.remove(path)
    except Exception:
        pass
