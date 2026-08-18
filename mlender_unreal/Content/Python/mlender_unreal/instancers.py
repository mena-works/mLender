# -*- coding: utf-8 -*-
"""Maya particle instancers as repeated Unreal actors.

Unreal's exact match for this is an InstancedStaticMeshComponent, and the class
exists with add_instances -- but a component cannot be added to a level actor
from Python in this engine: ``Actor.add_component_by_class`` is absent, probed,
and the only route is authoring a Blueprint through
``SubobjectDataSubsystem``. So instances arrive as one StaticMeshActor per
point, all sharing the one imported mesh asset.

That is real instancing at the asset level -- the geometry exists once -- and
costs one actor per point in the outliner. Above INSTANCE_WARN_LIMIT the count
is reported, because a scatter of ten thousand points would make a level nobody
can open, and truncating it silently is worse than saying so.
"""

import unreal

from .objects import place_in_folder, record_metadata
from .transforms import maya_vector_to_unreal, unreal_object_transform
from .utils import safe_asset_name, scalar


FOLDER = "mLender Instancers"
# Beyond this many points the outliner becomes the problem rather than the
# geometry. Reported, never silently truncated.
INSTANCE_WARN_LIMIT = 2000


def _source_meshes(record, mesh_actors, warnings, label):
    """The static meshes named by the instancer's source list."""
    meshes = []
    for source in record.get("sources") or []:
        name = str(source or "").split("|")[-1]
        actor = (
            mesh_actors.get(str(source))
            or mesh_actors.get(name)
            or mesh_actors.get(safe_asset_name(name))
        )
        mesh = None
        if actor is not None:
            component = getattr(actor, "static_mesh_component", None)
            mesh = component.static_mesh if component else None
        if mesh is None:
            warnings.append(
                'Instancer "{0}" names source "{1}", which is not a mesh in '
                "the level, so those points have nothing to place.".format(
                    label, name
                )
            )
            continue
        meshes.append((mesh, actor))
    return meshes


def import_instancers(package_data, unreal_scale, warnings, mesh_actors,
                      particle_positions):
    """One actor per instanced point, sharing the source mesh asset.

    ``particle_positions`` is the points object the instancer scatters onto,
    which the particle records carry; an instancer with no points object has
    nothing to place and says so.
    """
    records = list((package_data or {}).get("instancers") or [])
    created = 0
    instances = 0

    for record in records:
        label = record.get("instancer") or "Instancer"
        try:
            meshes = _source_meshes(record, mesh_actors, warnings, label)
            points = particle_positions.get(record.get("points_path")) or []
            if not meshes:
                continue
            if not points:
                warnings.append(
                    'Instancer "{0}" has no point positions in the package, so '
                    "nothing was scattered.".format(label)
                )
                continue
            if len(points) > INSTANCE_WARN_LIMIT:
                warnings.append(
                    'Instancer "{0}" scatters {1} points; this build makes one '
                    "actor per point, which is a lot of actors. All of them "
                    "were created.".format(label, len(points))
                )

            # The instancer's own transform, which the points sit inside.
            base_location, base_rotation, _scale = unreal_object_transform(
                record, unreal_scale
            )
            # One anchor per instancer, so the Maya originals have somewhere to
            # live and the instances have a parent to be moved by.
            anchor = unreal.EditorLevelLibrary.spawn_actor_from_class(
                unreal.Actor, base_location, base_rotation
            )
            anchor.set_actor_label(safe_asset_name(label, "Instancer"))
            place_in_folder(anchor, record, FOLDER)
            record_metadata(anchor, (
                ("instancer_points", record.get("points_path")),
                ("instancer_sources", ",".join(
                    str(s) for s in record.get("sources") or [])),
                ("instancer_point_count", len(points)),
            ))

            for index, point in enumerate(points):
                mesh, _source_actor = meshes[index % len(meshes)]
                offset = maya_vector_to_unreal(point)
                location = unreal.Vector(
                    base_location.x + offset[0] * unreal_scale,
                    base_location.y + offset[1] * unreal_scale,
                    base_location.z + offset[2] * unreal_scale,
                )
                actor = unreal.EditorLevelLibrary.spawn_actor_from_class(
                    unreal.StaticMeshActor, location, base_rotation
                )
                actor.static_mesh_component.set_static_mesh(mesh)
                actor.set_actor_label(
                    "{0}_{1}".format(safe_asset_name(label, "Instance"), index)
                )
                place_in_folder(actor, record, FOLDER)
                instances += 1
            record_metadata(
                unreal.EditorLevelLibrary.spawn_actor_from_class(
                    unreal.Actor, base_location, base_rotation
                ),
                (("instancer_points", record.get("points_path")),
                 ("instancer_sources", ",".join(
                     str(s) for s in record.get("sources") or []))),
            )
            created += 1
        except Exception as exc:
            warnings.append(
                'Instancer "{0}" could not be created: {1}'.format(label, exc)
            )

    return {"instancer_count": created, "instance_count": instances}
