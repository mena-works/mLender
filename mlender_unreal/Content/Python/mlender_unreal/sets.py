# -*- coding: utf-8 -*-
"""Maya selection sets and display layers as Unreal layers.

Unreal's Layers are the exact analogue: a named, cross-cutting membership that
does not move an actor in the outliner, which is what a Maya set is. The Blender
receiver uses collections for this and has to work around a collection being a
place rather than a label; here no workaround is needed.

Verified against a live editor before this was written: create a layer, add an
actor, ask the layer back and it reports the actor.

Membership is by name, so this runs after everything that creates actors.
"""

import unreal

from .constants import ASSET_PREFIX
from .utils import safe_asset_name


def _subsystem():
    return unreal.get_editor_subsystem(unreal.LayersSubsystem)


def _actor_index():
    """Every actor in the level, keyed by the names Maya might call it.

    Both the label and its sanitised form are keys: Unreal strips a namespace
    colon from a label, so a set naming ``ns:body`` has to find ``ns_body``.
    """
    subsystem = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
    index = {}
    for actor in subsystem.get_all_level_actors() or []:
        try:
            label = actor.get_actor_label()
        except Exception:
            continue
        for key in (label, safe_asset_name(label)):
            index.setdefault(str(key), actor)
    return index


def _add(layer_name, members, index, warnings, kind):
    layers = _subsystem()
    actors = []
    missing = []
    for member in members or []:
        name = str(member or "").strip()
        if not name:
            continue
        # A set can name a full Maya path; the leaf is what became the label.
        leaf = name.split("|")[-1]
        actor = (
            index.get(name)
            or index.get(leaf)
            or index.get(safe_asset_name(leaf))
        )
        if actor is None:
            missing.append(leaf)
            continue
        actors.append(actor)

    if not actors:
        warnings.append(
            '{0} "{1}" matched no actors in the level, so no layer was '
            "made for it.".format(kind, layer_name)
        )
        return 0
    try:
        layers.add_actors_to_layer(actors, layer_name)
    except Exception as exc:
        warnings.append(
            '{0} "{1}" could not be made into a layer: {2}'.format(
                kind, layer_name, exc
            )
        )
        return 0
    if missing:
        # Named but absent members are reported rather than counted: a set
        # listing a curve this build did not carry is worth knowing about.
        warnings.append(
            '{0} "{1}" names {2} member(s) that are not in the level: '
            "{3}".format(
                kind, layer_name, len(missing), ", ".join(sorted(missing)[:6])
            )
        )
    return 1


def import_sets(package_data, warnings):
    """Selection sets and display layers, each as one Unreal layer."""
    data = package_data or {}
    index = _actor_index()
    set_count = 0
    layer_count = 0

    for record in data.get("selection_sets") or data.get("object_sets") or []:
        name = record.get("set_full_name") or record.get("set") or "Set"
        layer = "{0}Set_{1}".format(ASSET_PREFIX, safe_asset_name(name, "Set"))
        set_count += _add(
            layer, record.get("members"), index, warnings, "Selection set"
        )
        if record.get("component_members"):
            warnings.append(
                'Selection set "{0}" also holds component members (faces or '
                "vertices), which an Unreal layer cannot express.".format(name)
            )

    for record in data.get("display_layers") or []:
        name = record.get("layer_full_name") or record.get("layer") or "Layer"
        layer = "{0}Layer_{1}".format(
            ASSET_PREFIX, safe_asset_name(name, "Layer")
        )
        made = _add(
            layer, record.get("members"), index, warnings, "Display layer"
        )
        layer_count += made
        if made and not record.get("visible", True):
            try:
                _subsystem().set_layer_visibility(layer, False)
            except Exception:
                # Not every version exposes the setter; the layer itself is
                # the part that matters and it is there.
                warnings.append(
                    'Display layer "{0}" was hidden in Maya; this engine did '
                    "not let the layer be hidden.".format(name)
                )

    return {"set_count": set_count, "layer_count": layer_count}
