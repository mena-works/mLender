# -*- coding: utf-8 -*-
"""Shared placement for everything the JSON rebuilds rather than the FBX.

Locators, curves, volumes, standins, particles and instancers all need the same
four things done to them: spawn, place from a Maya world matrix, put in a folder
mirroring the Maya group trail, and tag as ours. Doing that in one place is what
keeps a volume and a locator from drifting into two conventions.

Nothing here converts a transform itself; that lives in transforms.py, which is
the one place the measured axis mapping is written down.
"""

import unreal

from .constants import ACTOR_FOLDER_ROOT, GENERATED_TAG
from .transforms import unreal_object_transform
from .utils import safe_asset_name


def spawn(actor_class, record, unreal_scale, label, folder_suffix=""):
    """Spawn and place one actor from a record carrying a Maya world matrix."""
    location, rotation, scale = unreal_object_transform(record, unreal_scale)
    actor = unreal.EditorLevelLibrary.spawn_actor_from_class(
        actor_class, location, rotation
    )
    if actor is None:
        raise RuntimeError(
            "Unreal refused to spawn {0}".format(actor_class)
        )
    try:
        actor.set_actor_scale3d(scale)
    except Exception:
        pass
    actor.set_actor_label(safe_asset_name(label, "Object"))
    place_in_folder(actor, record, folder_suffix)
    return actor


def place_in_folder(actor, record, folder_suffix=""):
    """Mirror the Maya group trail as an Unreal actor folder path."""
    groups = [
        str(part) for part in (record or {}).get("groups") or []
        if str(part).strip()
    ]
    parts = [ACTOR_FOLDER_ROOT]
    if folder_suffix:
        parts.append(folder_suffix)
    parts.extend(groups)
    try:
        actor.set_folder_path("/".join(parts))
    except Exception:
        pass
    try:
        actor.tags = [GENERATED_TAG]
    except Exception:
        pass
    return actor


def record_metadata(actor, pairs):
    """Keep the Maya originals on the actor, as tags.

    An Unreal actor has no custom properties the way a Blender object does, so
    the source values ride along as ``ml_key=value`` tags. That is the same job
    the ml_source_* properties do on the Blender side: when a number is
    disputed, this is the reference.
    """
    try:
        tags = [str(tag) for tag in (actor.tags or [])]
    except Exception:
        tags = []
    for key, value in pairs:
        if value is None or value == "":
            continue
        tags.append("ml_{0}={1}".format(key, value))
    try:
        actor.tags = tags
    except Exception:
        pass
    return actor


def parent_to(child, parent):
    """Attach keeping the world transform, the way a Maya parent behaves."""
    if child is None or parent is None:
        return False
    try:
        child.attach_to_actor(
            parent, "",
            unreal.AttachmentRule.KEEP_WORLD,
            unreal.AttachmentRule.KEEP_WORLD,
            unreal.AttachmentRule.KEEP_WORLD,
            False,
        )
        return True
    except Exception:
        return False
