# -*- coding: utf-8 -*-
"""Level clearing and verification.

Importing a package replaces the level, the same destructive design the Blender
receiver has and for the same reason: the Maya scene is the single source of
truth. The clear is verified and raises if anything survived -- importing into a
half cleared level is worse than not importing.
"""

import unreal

from .constants import (
    ACTOR_FOLDER_ROOT,
    CONTENT_ROOT,
    GENERATED_TAG,
    LIGHTING_ACTOR_CLASSES,
)


def _actor_subsystem():
    return unreal.get_editor_subsystem(unreal.EditorActorSubsystem)


def level_actors():
    subsystem = _actor_subsystem()
    return list(subsystem.get_all_level_actors() or [])


def is_generated(actor):
    """Whether this tool made the actor.

    Unreal actors have no custom properties, so the marker is a tag. It is the
    same job ml_generated does on the Blender side: telling our own output from
    whatever else is in the level.
    """
    try:
        return GENERATED_TAG in [str(tag) for tag in (actor.tags or [])]
    except Exception:
        return False


def is_lighting_actor(actor):
    """Whether an actor is part of the level's own lighting setup."""
    try:
        name = actor.get_class().get_name()
    except Exception:
        return False
    if name in LIGHTING_ACTOR_CLASSES:
        return True
    # Reflection captures and light kinds a future engine adds are still
    # lighting; the class list is the fast path, not the whole answer.
    for base in ("Light", "ReflectionCapture"):
        if name.endswith(base):
            return True
    return False


def is_ours(actor):
    """Whether a previous send made this actor."""
    try:
        return GENERATED_TAG in [str(tag) for tag in (actor.tags or [])]
    except Exception:
        return False


def clear_level(warnings, keep_lighting=False):
    """Delete every actor in the level, then check that it worked.

    Actors that refuse to go are named rather than counted, because "3 actors
    survived" is not something a user can act on.

    ``keep_lighting`` spares the lighting the level already had -- the lights,
    the sky, the fog, the post process volume. What it does **not** spare is
    the lighting a previous send made: those carry this tool's tag, and
    keeping them would pile a new copy on top of the old one every time.
    """
    subsystem = _actor_subsystem()
    kept = 0
    for actor in level_actors():
        if keep_lighting and is_lighting_actor(actor) and not is_ours(actor):
            kept += 1
            continue
        try:
            subsystem.destroy_actor(actor)
        except Exception:
            pass
    if keep_lighting:
        warnings.append(
            "Kept {0} lighting actor(s) the level already had; the package's "
            "own lights were still rebuilt on top of them.".format(kept)
            if kept else
            "Keep existing lighting was on, but the level had none to keep."
        )

    survivors = []
    for actor in level_actors():
        try:
            # A level's own built-in actors cannot be destroyed and are not
            # scene content; anything else surviving is a real failure.
            if actor.get_class().get_name() in _PERMANENT_CLASSES:
                continue
            if keep_lighting and is_lighting_actor(actor) and not is_ours(actor):
                continue
            survivors.append(actor.get_actor_label())
        except Exception:
            survivors.append("<unnamed>")
    if survivors:
        raise RuntimeError(
            "The level could not be cleared; these actors survived: "
            "{0}".format(", ".join(sorted(survivors)[:10]))
        )
    return True


# Actors every level has and which are not scene content. Names read off a
# real level rather than assumed; anything unknown is treated as content, so a
# surviving actor is reported rather than quietly excused.
_PERMANENT_CLASSES = (
    "WorldSettings",
    "Brush",
    "LevelBounds",
    "WorldDataLayers",
    "WorldPartitionMiniMap",
)


def purge_generated_content(warnings):
    """Remove the assets a previous send left behind.

    Only under this tool's own content root, and only when nothing references
    them. A user who built something on top of a generated material keeps it.
    """
    if not unreal.EditorAssetLibrary.does_directory_exist(CONTENT_ROOT):
        return 0
    removed = 0
    try:
        removed = unreal.EditorAssetLibrary.delete_directory(CONTENT_ROOT)
    except Exception as exc:
        warnings.append(
            "Previously generated assets under {0} could not be removed: "
            "{1}".format(CONTENT_ROOT, exc)
        )
        return 0
    return 1 if removed else 0


def ensure_folders():
    """Nothing to create: Unreal actor folders exist by being referenced."""
    return ACTOR_FOLDER_ROOT
