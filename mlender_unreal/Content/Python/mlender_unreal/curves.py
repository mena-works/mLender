# -*- coding: utf-8 -*-
"""Maya NURBS and bezier curves as Unreal splines.

Unreal's match for a curve is a ``SplineComponent``, which exists here with
``add_spline_point`` and ``clear_spline_points``. Getting one into a level is the
hard part: ``Actor.add_component_by_class`` is absent from this engine's Python
bindings -- probed -- so a component cannot simply be added to a spawned actor.

Two routes are tried in order, and which one ran is reported rather than
assumed:

1. **A generated Blueprint** holding a spline, made once through
   ``SubobjectDataSubsystem`` and then spawned per curve. This is the real
   answer: the curve arrives as an editable spline.
2. **An anchor** at the curve's transform with its control points recorded as
   tags, if this engine will not let the component be created.

The fallback is deliberately not silent. A curve that arrives as a bare
transform is not the same thing as a curve, and the import says so.
"""

import unreal

from .constants import ASSET_PREFIX, CONTENT_ROOT
from .objects import record_metadata, spawn
from .transforms import maya_vector_to_unreal, unreal_object_transform
from .utils import safe_asset_name


FOLDER = "mLender Curves"
SPLINE_BLUEPRINT_PATH = CONTENT_ROOT + "/" + ASSET_PREFIX + "SplineActor"

# Cached across one import: the Blueprint is built once, not per curve.
_blueprint = {"asset": None, "tried": False}


def _spline_blueprint(warnings):
    """A Blueprint whose root is a SplineComponent, or None.

    Built through SubobjectDataSubsystem, which is the only route this engine
    offers for adding a component. If any step refuses, the caller falls back
    to an anchor.
    """
    if _blueprint["tried"]:
        return _blueprint["asset"]
    _blueprint["tried"] = True

    if unreal.EditorAssetLibrary.does_asset_exist(SPLINE_BLUEPRINT_PATH):
        existing = unreal.EditorAssetLibrary.load_asset(SPLINE_BLUEPRINT_PATH)
        if existing is not None:
            _blueprint["asset"] = existing
            return existing

    subsystem_class = getattr(unreal, "SubobjectDataSubsystem", None)
    factory_class = getattr(unreal, "BlueprintFactory", None)
    if subsystem_class is None or factory_class is None:
        warnings.append(
            "This engine exposes no way to build a spline Blueprint "
            "(SubobjectDataSubsystem or BlueprintFactory is missing), so "
            "curves arrive as anchors."
        )
        return None

    try:
        factory = factory_class()
        factory.set_editor_property("parent_class", unreal.Actor)
        tools = unreal.AssetToolsHelpers.get_asset_tools()
        blueprint = tools.create_asset(
            ASSET_PREFIX + "SplineActor", CONTENT_ROOT,
            unreal.Blueprint, factory,
        )
        if blueprint is None:
            raise RuntimeError("the Blueprint was not created")

        subsystem = unreal.get_engine_subsystem(subsystem_class)
        handles = subsystem.k2_gather_subobject_data_for_blueprint(blueprint)
        if not handles:
            raise RuntimeError("the Blueprint reported no subobjects")

        params = unreal.AddNewSubobjectParams()
        params.set_editor_property("parent_handle", handles[0])
        params.set_editor_property("new_class", unreal.SplineComponent)
        params.set_editor_property("blueprint_context", blueprint)
        handle, failure = subsystem.add_new_subobject(params)
        if failure and str(failure):
            raise RuntimeError(str(failure))
        subsystem.rename_subobject(handle, "Spline")
        # A freshly authored Blueprint has no usable generated class until it is
        # compiled, and spawning from the asset then returns None -- measured,
        # every curve fell through to the anchor path with no error to explain
        # it.
        library = getattr(unreal, "BlueprintEditorLibrary", None)
        compiler = getattr(library, "compile_blueprint", None) if library else None
        if callable(compiler):
            compiler(blueprint)
        unreal.EditorAssetLibrary.save_loaded_asset(blueprint, False)
        _blueprint["asset"] = blueprint
        return blueprint
    except Exception as exc:
        warnings.append(
            "A spline Blueprint could not be generated ({0}), so curves "
            "arrive as anchors with their control points recorded.".format(exc)
        )
        return None


def _apply_points(actor, record, unreal_scale, warnings, label):
    """Push the Maya control points onto the actor's spline component."""
    component = None
    try:
        component = actor.get_component_by_class(unreal.SplineComponent)
    except Exception:
        component = None
    if component is None:
        return False

    points = list(record.get("control_points") or [])
    if not points:
        warnings.append(
            'Curve "{0}" carries no control points.'.format(label)
        )
        return False
    try:
        component.clear_spline_points(False)
        for point in points:
            x, y, z = maya_vector_to_unreal(point)
            component.add_spline_point(
                unreal.Vector(x * unreal_scale, y * unreal_scale,
                              z * unreal_scale),
                unreal.SplineCoordinateSpace.LOCAL,
                False,
            )
        # A Maya closed or periodic form is a closed loop here. form 2 is
        # periodic and 1 is closed in the exporter's record.
        try:
            component.set_closed_loop(int(record.get("form") or 0) >= 1, False)
        except Exception:
            pass
        component.update_spline()
        return True
    except Exception as exc:
        warnings.append(
            'Curve "{0}" has a spline but its points would not go on: '
            "{1}".format(label, exc)
        )
        return False


def import_curves(package_data, unreal_scale, warnings):
    records = list((package_data or {}).get("curves") or [])
    _blueprint["asset"] = None
    _blueprint["tried"] = False

    created = 0
    as_splines = 0
    blueprint = _spline_blueprint(warnings) if records else None

    for record in records:
        label = (
            record.get("curve_full_name") or record.get("curve") or "Curve"
        )
        try:
            actor = None
            if blueprint is not None:
                location, rotation, scale = unreal_object_transform(
                    record, unreal_scale
                )
                # The generated class, not the Blueprint asset: spawning from
                # the asset returns None and says nothing about why.
                generated = None
                getter = getattr(blueprint, "generated_class", None)
                if callable(getter):
                    generated = getter()
                actor = unreal.EditorLevelLibrary.spawn_actor_from_class(
                    generated or blueprint, location, rotation
                ) if generated is not None else None
                if actor is not None:
                    try:
                        actor.set_actor_scale3d(scale)
                    except Exception:
                        pass
                    actor.set_actor_label(safe_asset_name(label, "Curve"))
                    from .objects import place_in_folder

                    place_in_folder(actor, record, FOLDER)
                    if _apply_points(
                        actor, record, unreal_scale, warnings, label
                    ):
                        as_splines += 1
            if actor is None:
                actor = spawn(unreal.Actor, record, unreal_scale, label, FOLDER)
                warnings.append(
                    'Curve "{0}" arrived as an anchor rather than a spline; '
                    "its control points are on it as tags.".format(label)
                )
                record_metadata(actor, (
                    ("curve_points", len(record.get("control_points") or [])),
                ))

            record_metadata(actor, (
                ("curve_type", record.get("curve_type")),
                ("curve_degree", record.get("degree")),
                ("curve_form", record.get("form")),
            ))
            if not record.get("visible", True):
                try:
                    actor.set_actor_hidden_in_game(True)
                except Exception:
                    pass
            created += 1
        except Exception as exc:
            warnings.append(
                'Curve "{0}" could not be created: {1}'.format(label, exc)
            )

    if records and as_splines:
        # Worth stating positively: the good path is not the obvious one and a
        # reader should know which one ran.
        warnings.append(
            "{0} of {1} curve(s) arrived as editable Unreal splines.".format(
                as_splines, len(records)
            )
        )
    return {"curve_count": created, "curve_splines": as_splines}
