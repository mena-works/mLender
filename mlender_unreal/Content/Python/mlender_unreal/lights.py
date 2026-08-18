# -*- coding: utf-8 -*-
"""Maya lights rebuilt as Unreal light actors.

The energy model is not re-derived here. The Blender receiver's conversion was
measured by rendering Arnold against Cycles and solving for the ratio, and it
lands on total luminous flux in watts. Unreal states intensity in lumens, and
lumens are watts times the photopic efficacy, so this module reuses that
measured chain and multiplies at the end:

    Maya intensity -> flux in watts (measured, pi anchor) -> lumens (x683)

Two traps live in that sentence, both of which this project has paid for once:

* The squared unit term inside the flux conversion must use **metres** per Maya
  unit, because that is what the anchor was measured against. Unreal positions
  are in centimetres, so the two scales are different numbers here and using
  the Unreal one would be wrong by 100^2.
* The area must be applied exactly once. It is consumed inside the flux
  conversion, so nothing below multiplies by area again.
"""

import math

import unreal

from .constants import (
    AREA_SIZE_PER_SCALE,
    DEFAULT_LIGHT_POWER_SCALE,
    DIRECTIONAL_LIGHT_UNIT_IS_LUX,
    GENERATED_TAG,
    LIGHT_FOLDER,
    LUMENS_PER_WATT,
    WATTS_PER_INTENSITY,
)
from .transforms import source_scale, unreal_transform
from .utils import colour, safe_asset_name, scalar


def resolve_unreal_light_class(source_kind, area_shape):
    """Map an exporter light kind onto the closest Unreal light actor.

    Unreal has no cylinder or mesh area light, so those approximate to a rect
    light exactly as they approximate to a rectangle on the Blender side. A
    spherical area light is a point light, which is what it physically is.
    """
    kind = str(source_kind or "AREA").upper()
    shape = str(area_shape or "RECTANGLE").upper()
    if kind == "IES":
        return unreal.SpotLight
    if kind == "AREA" and shape == "SPHERE":
        return unreal.PointLight
    if kind == "POINT":
        return unreal.PointLight
    if kind == "SPOT":
        return unreal.SpotLight
    if kind == "SUN":
        return unreal.DirectionalLight
    return unreal.RectLight


def renderer_key(record):
    """Which renderer's conventions a light record follows."""
    node_type = str(record.get("node_type") or "").lower()
    if "redshift" in node_type:
        return "redshift"
    if node_type.startswith("ai"):
        return "arnold"
    return "maya"


def source_is_normalized(record):
    """Whether the source intensity already means total output."""
    parameters = record.get("parameters") or {}
    if "normalize" not in parameters:
        return True
    return bool(parameters.get("normalize"))


def emitting_dimensions(record, metre_scale):
    """The light's emitting size in metres, on each Maya axis."""
    scale = source_scale(record)
    factor = AREA_SIZE_PER_SCALE.get(renderer_key(record), 1.0) * metre_scale
    return tuple(max(0.0001, value * factor) for value in scale[:3])


def emitting_surface_area(record, metre_scale):
    """Emitting area in square metres, matching the shape actually built."""
    width, height, depth = emitting_dimensions(record, metre_scale)
    shape = str(record.get("area_shape") or "RECTANGLE").upper()
    if shape == "DISK":
        radius = max(width, height) * 0.5
        return math.pi * radius * radius
    if shape == "SPHERE":
        radius = max(width, height, depth) * 0.5
        return 4.0 * math.pi * radius * radius
    return width * height


def light_flux_watts(record, light_class, metre_scale, power_scale=None):
    """Total radiant flux in watts, the same quantity the Blender receiver uses.

    Kept as its own function so the contract checks can exercise it without an
    editor, and so the Unreal-specific lumen step below stays one line.
    """
    if power_scale is None:
        power_scale = DEFAULT_LIGHT_POWER_SCALE
    power_scale = max(0.0, scalar(power_scale, DEFAULT_LIGHT_POWER_SCALE))

    effective = max(0.0, scalar(
        record.get("effective_intensity"),
        scalar(record.get("intensity"), 1.0)
        * (2.0 ** scalar(record.get("exposure"), 0.0)),
    ))
    units = str((record.get("enum_labels") or {}).get("units") or "").lower()

    # A sun states irradiance on the surface, so neither area nor the
    # normalize convention applies to it.
    if light_class is unreal.DirectionalLight:
        return effective * power_scale
    if "lumen" in units:
        return effective / LUMENS_PER_WATT
    if "candela" in units:
        return effective * (4.0 * math.pi) / LUMENS_PER_WATT
    if "watt" in units:
        return effective
    if "nit" in units or "radiance" in units or "exitance" in units:
        area = max(0.000001, emitting_surface_area(record, metre_scale))
        return effective * area * math.pi / LUMENS_PER_WATT

    watts_per_intensity = WATTS_PER_INTENSITY.get(renderer_key(record), math.pi)
    unit_scale = max(1e-12, scalar(metre_scale, 1.0)) ** 2
    flux = effective * watts_per_intensity * unit_scale * power_scale
    if light_class is unreal.RectLight and not source_is_normalized(record):
        flux *= max(0.000001, emitting_surface_area(record, metre_scale))
    return flux


def light_intensity_for_unreal(record, light_class, metre_scale, power_scale):
    """Return (intensity, units) ready for the component.

    A directional light has no intensity_units property at all -- measured, the
    reflection exposes it on point, rect and spot only -- and Unreal states its
    intensity in lux. Everything else is given lumens and Unreal converts from
    there, so the engine stays the single authority for its own units.
    """
    flux = light_flux_watts(record, light_class, metre_scale, power_scale)
    if light_class is unreal.DirectionalLight:
        # Irradiance in W/m^2 to illuminance in lux.
        return flux * LUMENS_PER_WATT, None
    return flux * LUMENS_PER_WATT, unreal.LightUnits.LUMENS


def apply_intensity(component, lumens, units, label, warnings):
    """Set the intensity in whatever unit the component actually accepted.

    Measured on 5.8.1: the setter is honoured, and point, rect and spot lights
    all keep LightUnits.LUMENS once set. So the read-back below is a guard, not
    a workaround for observed behaviour -- if some light type or some future
    version refuses lumens, the value is converted into whatever unit did stick
    using the engine's own factor, rather than being left as a number in the
    wrong unit.

    Unreal stays the authority for its own units. Writing a conversion constant
    here instead would be a second authority to keep in step with the engine.
    """
    if units is None:
        # A directional light has no intensity_units at all; its intensity is
        # lux and the caller already produced lux.
        if not _set_if_present(component, "intensity", lumens):
            warnings.append(
                'Light "{0}" would not accept an intensity, so it kept '
                "Unreal's default.".format(label)
            )
        return lumens, None

    _set_if_present(component, "intensity_units", units)
    accepted = getattr(component, "intensity_units", units)
    value = lumens
    if accepted != units:
        factor = None
        converter = getattr(component, "get_units_conversion_factor", None)
        if converter is not None:
            try:
                factor = converter(units, accepted)
            except Exception:
                factor = None
        if factor is None:
            warnings.append(
                'Light "{0}" would not take lumens and this engine offered no '
                "conversion factor, so its intensity may be wrong.".format(
                    label
                )
            )
        else:
            value = lumens * factor
    if not _set_if_present(component, "intensity", value):
        warnings.append(
            'Light "{0}" would not accept an intensity, so it kept Unreal\'s '
            "default rather than the value Maya exported.".format(label)
        )
    return value, accepted


def light_colour(record):
    """Maya light colour as an Unreal LinearColor, never clipped."""
    parameters = record.get("parameters") or {}
    values = colour(
        parameters.get("color", record.get("color")), (1.0, 1.0, 1.0)
    )
    return unreal.LinearColor(values[0], values[1], values[2], 1.0)


def _set_if_present(component, name, value):
    """Set a light component property, by its setter where one exists.

    A light component's intensity and units are read-only to Python -- measured,
    the assignment raises "Property 'Intensity' ... is read-only and cannot be
    set" -- with a setter function beside them. An earlier version assigned the
    attribute inside a bare try/except: the write raised, the exception was
    swallowed, and every light silently kept a spawned component's default of 8
    candelas while the test that only asked "is the intensity positive" passed.

    So the setter is preferred, the property is the fallback, and the caller is
    told when neither worked. Returning False rather than raising keeps one
    stubborn property from costing the whole light.
    """
    setter = getattr(component, "set_" + name, None)
    if callable(setter):
        try:
            setter(value)
            return True
        except Exception:
            pass
    if not hasattr(component, name):
        return False
    try:
        setattr(component, name, value)
        return True
    except Exception:
        return False


def apply_temperature(component, record):
    parameters = record.get("parameters") or {}
    if not parameters.get("use_temperature"):
        return
    temperature = scalar(parameters.get("temperature"), 6500.0)
    if temperature <= 0.0:
        return
    _set_if_present(component, "use_temperature", True)
    _set_if_present(component, "temperature", temperature)


def apply_shape(component, record, light_class, unreal_scale, metre_scale):
    """Emitting size, in the units each component wants.

    Rect light source width and height are in Unreal units, so they use the
    centimetre scale rather than the metre one the energy model uses. Mixing
    those two up is a factor of 100 that looks like a light of the wrong size
    rather than a bug.
    """
    width, height, depth = emitting_dimensions(record, metre_scale)
    if light_class is unreal.RectLight:
        _set_if_present(component, "source_width", width * 100.0)
        _set_if_present(component, "source_height", height * 100.0)
    elif light_class is unreal.PointLight:
        radius = max(width, height, depth) * 0.5 * 100.0
        _set_if_present(component, "source_radius", radius)
    if light_class in (unreal.PointLight, unreal.SpotLight, unreal.RectLight):
        # Maya lights have no attenuation radius; an unlit far field is worse
        # than a generous one, so the radius follows the scene rather than
        # Unreal's 1000 unit default.
        _set_if_present(
            component, "attenuation_radius", max(1000.0, unreal_scale * 5000.0)
        )


def apply_cone(component, record, light_class, warnings):
    if light_class is not unreal.SpotLight:
        return
    parameters = record.get("parameters") or {}
    cone = scalar(parameters.get("cone_angle"), 0.0)
    if cone <= 0.0:
        cone = scalar(parameters.get("spread"), 0.0)
    if cone <= 0.0:
        return
    # Maya states a full cone angle; Unreal states the half angle.
    outer = max(1.0, min(89.0, cone * 0.5))
    penumbra = scalar(parameters.get("penumbra_angle"), 0.0)
    inner = max(0.0, min(outer, outer - abs(penumbra)))
    _set_if_present(component, "outer_cone_angle", outer)
    _set_if_present(component, "inner_cone_angle", inner)


def create_light_actor(
    record, unreal_scale, metre_scale, power_scale, warnings
):
    source_kind = str(record.get("light_kind") or "AREA").upper()
    area_shape = str(record.get("area_shape") or "RECTANGLE").upper()
    light_class = resolve_unreal_light_class(source_kind, area_shape)

    location, rotation = unreal_transform(
        record.get("transform") or {}, unreal_scale
    )
    actor = unreal.EditorLevelLibrary.spawn_actor_from_class(
        light_class, location, rotation
    )
    if actor is None:
        raise RuntimeError("Unreal refused to spawn the light actor.")

    label = safe_asset_name(record.get("name") or "Light", "Light")
    actor.set_actor_label(label)
    actor.set_folder_path(LIGHT_FOLDER)
    actor.tags = [GENERATED_TAG]

    component = actor.light_component
    intensity, units = light_intensity_for_unreal(
        record, light_class, metre_scale, power_scale
    )
    apply_intensity(component, intensity, units, label, warnings)
    _set_if_present(component, "light_color", light_colour(record))
    apply_temperature(component, record)
    apply_shape(component, record, light_class, unreal_scale, metre_scale)
    apply_cone(component, record, light_class, warnings)

    parameters = record.get("parameters") or {}
    if "cast_shadows" in parameters:
        _set_if_present(
            component, "cast_shadows", bool(parameters.get("cast_shadows"))
        )

    if record.get("ies_profile"):
        warnings.append(
            'Light "{0}" carries an IES profile, which this build does not '
            "load in Unreal; it arrived as a plain spot light.".format(label)
        )
    return actor


def create_sky_light(dome_records, unreal_scale, warnings):
    """The first active dome drives a Sky Light; the rest are reported.

    Unreal has one sky light per level in the same way Blender has one world,
    so the same rule applies: first active one wins and the others are named
    rather than silently dropped.
    """
    if not dome_records:
        return 0
    record = dome_records[0]
    actor = unreal.EditorLevelLibrary.spawn_actor_from_class(
        unreal.SkyLight, unreal.Vector(0.0, 0.0, 0.0), unreal.Rotator(0, 0, 0)
    )
    actor.set_actor_label(safe_asset_name(record.get("name") or "SkyLight"))
    actor.set_folder_path(LIGHT_FOLDER)
    actor.tags = [GENERATED_TAG]

    component = actor.light_component
    _set_if_present(component, "intensity", max(0.0, scalar(
        record.get("effective_intensity"), scalar(record.get("intensity"), 1.0)
    )))
    _set_if_present(component, "light_color", light_colour(record))

    texture = str(record.get("dome_texture") or "").strip()
    if texture:
        warnings.append(
            'Dome light "{0}" references "{1}"; this build sets the sky light '
            "intensity and colour but does not load the HDR cubemap.".format(
                record.get("name") or "Dome", texture
            )
        )
    for extra in dome_records[1:]:
        warnings.append(
            'Dome light "{0}" was not applied: Unreal has one sky light per '
            "level and the first active dome drives it.".format(
                extra.get("name") or "Dome"
            )
        )
    return 1


def import_lights(package_data, unreal_scale, metre_scale, power_scale,
                  warnings):
    records = list((package_data or {}).get("lights") or [])
    dome_records = [
        record for record in records
        if str(record.get("light_kind") or "").upper() == "DOME"
    ]
    object_count = 0
    for record in records:
        if record in dome_records:
            continue
        if not record.get("enabled", True):
            continue
        try:
            create_light_actor(
                record, unreal_scale, metre_scale, power_scale, warnings
            )
            object_count += 1
        except Exception as exc:
            warnings.append(
                'Light "{0}" could not be created: {1}'.format(
                    record.get("full_name") or record.get("name") or "Light",
                    exc,
                )
            )
    dome_count = 0
    try:
        dome_count = create_sky_light(dome_records, unreal_scale, warnings)
    except Exception as exc:
        warnings.append("Sky light could not be created: {0}".format(exc))
    return {
        "light_count": object_count + dome_count,
        "object_count": object_count,
        "dome_count": dome_count,
    }
