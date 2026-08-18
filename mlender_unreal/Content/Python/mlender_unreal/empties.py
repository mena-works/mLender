# -*- coding: utf-8 -*-
"""Maya locators and empty group nulls as plain Unreal actors.

A bare ``unreal.Actor`` is the analogue of a Blender Empty: measured, spawning
one gives it a DefaultSceneRoot, so it has a transform, takes a label and can be
a parent. There is no EmptyActor class in this engine -- probed -- so the plain
Actor is the right answer rather than a compromise.

These are built before the kinds that hang off them, because a locator parented
under another locator has to find its parent already standing.
"""

import unreal

from .objects import parent_to, record_metadata, spawn
from .utils import safe_asset_name


FOLDER = "mLender Locators"


def import_transforms(package_data, unreal_scale, warnings, object_by_path):
    """One actor per locator or empty null, then the parent wiring."""
    records = list((package_data or {}).get("transforms") or [])
    created = {}
    count = 0

    for record in records:
        try:
            label = (
                record.get("transform")
                or record.get("transform_full_name")
                or "Locator"
            )
            actor = spawn(
                unreal.Actor,
                {
                    "world_matrix": record.get("world_matrix"),
                    "groups": record.get("groups"),
                },
                unreal_scale,
                label,
                FOLDER,
            )
            record_metadata(actor, (
                ("source_type", record.get("transform_type")),
                ("source_path", record.get("transform_path")),
            ))
            if not record.get("visible", True):
                _hide(actor)
            path = record.get("transform_path")
            if path:
                created[path] = actor
            count += 1
        except Exception as exc:
            warnings.append(
                'Locator "{0}" could not be created: {1}'.format(
                    record.get("transform_full_name")
                    or record.get("transform") or "Locator",
                    exc,
                )
            )

    # Parenting runs second so a locator under another locator finds it. The
    # parent may equally be a mesh the FBX brought, which is what
    # object_by_path carries.
    parented = 0
    for record in records:
        path = record.get("transform_path")
        parent_path = record.get("parent_path")
        if not path or not parent_path:
            continue
        child = created.get(path)
        parent = created.get(parent_path) or (object_by_path or {}).get(
            parent_path
        )
        if child is not None and parent is not None:
            if parent_to(child, parent):
                parented += 1

    return {"transform_count": count, "parented": parented,
            "actors_by_path": created}


def _hide(actor):
    """Hidden in Maya means hidden here, in editor and in game."""
    try:
        actor.set_actor_hidden_in_game(True)
    except Exception:
        pass
    try:
        actor.set_editor_property("is_temporarily_hidden_in_editor", True)
    except Exception:
        pass


def label_for(record, key, fallback):
    return safe_asset_name(
        record.get(key) or record.get(key + "_full_name") or fallback, fallback
    )
