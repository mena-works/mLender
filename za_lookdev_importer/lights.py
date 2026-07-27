# -*- coding: utf-8 -*-
"""Rebuild Maya/Redshift lights as native Blender lights.

Lights never travel inside the FBX; they arrive as current-frame JSON records
so they can be rebuilt with real Blender light data instead of FBX
approximations. Original Redshift values are preserved in ``za_source_*``
custom properties, which are the reference when calibration is questioned.
"""

import json
import math
import os

import bpy

from .constants import (
    AREA_SIZE_PER_SCALE,
    DEFAULT_LIGHT_POWER_SCALE,
    LIGHT_COLLECTION_NAME,
    LUMENS_PER_WATT,
    NODE_TREE_UNIT_STRENGTH,
    WATTS_PER_INTENSITY,
)
from .animation import animate_object, key_data_value
from .images import load_image
from .transforms import (
    maya_matrix_to_blender,
    source_scale as source_light_scale,
)
from .utils import color4, namespace_free_name, scalar


def import_lights(
    package_data,
    root_collection,
    import_scale,
    warnings,
    power_scale=None,
):
    records = list(package_data.get("lights") or [])
    if not records:
        bpy.context.scene.world = None
        return {
            "light_count": 0,
            "object_count": 0,
            "dome_count": 0,
        }

    light_collection = bpy.data.collections.new(LIGHT_COLLECTION_NAME)
    root_collection.children.link(light_collection)
    meters_per_unit = scalar(package_data.get("meters_per_maya_unit"), 0.01)
    position_scale = meters_per_unit * max(scalar(import_scale, 1.0), 0.000001)
    object_count = 0
    dome_records = []

    for record in records:
        if str(record.get("light_kind") or "").upper() == "DOME":
            dome_records.append(record)
            continue
        try:
            create_light_object(
                record,
                light_collection,
                position_scale,
                warnings,
                power_scale,
            )
            object_count += 1
        except Exception as exc:
            warnings.append(
                'Light "{0}" could not be created: {1}'.format(
                    record.get("full_name") or record.get("name") or "Light",
                    exc,
                )
            )

    dome_count = create_dome_world(
        dome_records,
        light_collection,
        position_scale,
        warnings,
    )
    return {
        "light_count": object_count + dome_count,
        "object_count": object_count,
        "dome_count": dome_count,
    }


def resolve_blender_light_type(source_kind, area_shape):
    """Map an exporter light kind to the closest Blender light type."""
    if source_kind == "IES":
        return "SPOT"
    if source_kind == "AREA" and area_shape == "SPHERE":
        return "POINT"
    if source_kind in ("AREA", "POINT", "SPOT", "SUN"):
        return source_kind
    return "AREA"


def create_light_object(
    record,
    collection,
    position_scale,
    warnings,
    power_scale=None,
):
    source_kind = str(record.get("light_kind") or "AREA").upper()
    area_shape = str(record.get("area_shape") or "RECTANGLE").upper()
    blender_type = resolve_blender_light_type(source_kind, area_shape)

    clean_name = (
        record.get("name")
        or namespace_free_name(record.get("full_name"))
        or "Light"
    )
    data = bpy.data.lights.new(clean_name, blender_type)
    obj = bpy.data.objects.new(clean_name, data)
    collection.objects.link(obj)
    obj.matrix_world = maya_matrix_to_blender(
        record.get("transform") or {},
        position_scale,
    )
    # Size travels through the light data, so the object stays unscaled.
    obj.scale = (1.0, 1.0, 1.0)

    parameters = record.get("parameters") or {}
    data.color = light_color(record)
    apply_light_temperature(data, record, warnings)
    data.energy = light_energy(
        record,
        blender_type,
        position_scale,
        power_scale,
    )
    if not bool(record.get("enabled", True)):
        data.energy = 0.0

    # light_energy always returns total flux, so Power must mean flux. The
    # source's own normalize flag was already consumed there; passing it
    # through as well would apply the light's area a second time.
    if hasattr(data, "normalize"):
        data.normalize = True

    if hasattr(data, "use_shadow"):
        data.use_shadow = bool(parameters.get("cast_shadows", True))
    if hasattr(data, "diffuse_factor"):
        data.diffuse_factor = max(0.0, scalar(parameters.get("diffuse"), 1.0))
    if hasattr(data, "specular_factor"):
        data.specular_factor = max(0.0, scalar(parameters.get("specular"), 1.0))
    if hasattr(data, "volume_factor"):
        data.volume_factor = max(0.0, scalar(parameters.get("volume"), 1.0))

    size_x, size_y, size_z = emitting_dimensions(record, position_scale)

    if blender_type == "AREA":
        configure_area_light(
            data,
            area_shape,
            size_x,
            size_y,
            size_z,
            parameters,
            warnings,
            clean_name,
        )
    elif blender_type == "SPOT":
        configure_spot_light(data, parameters, position_scale)
    elif blender_type == "POINT":
        radius = scalar(parameters.get("shadow_softness"), 0.0) * position_scale
        if source_kind == "AREA" and area_shape == "SPHERE":
            radius = max(size_x, size_y, size_z) * 0.5
        data.shadow_soft_size = max(0.0, radius)
    elif blender_type == "SUN" and hasattr(data, "angle"):
        softness = max(0.0, scalar(parameters.get("shadow_softness"), 0.0))
        data.angle = min(math.pi, softness)

    configure_light_texture_nodes(data, record, warnings)
    _animate_light(obj, data, record, blender_type, position_scale, power_scale)
    store_light_metadata(obj, data, record)
    return obj


def _animate_light(obj, data, record, blender_type, position_scale, power_scale):
    """Key the transform, and the energy and colour that move with it.

    Energy is re-derived per sample through light_energy rather than
    interpolated, so every frame goes through the same measured conversion the
    static record does.
    """
    if not bool(record.get("enabled", True)):
        return 0

    parameters = record.get("parameters") or {}
    mode = str((record.get("enum_labels") or {}).get("color_mode") or "").lower()
    temperature_driven = (
        bool(parameters.get("use_temperature", False)) or "temperature" in mode
    )

    def apply_sample(sample, frame):
        if "effective_intensity" in sample:
            frame_record = dict(record)
            frame_record["effective_intensity"] = sample["effective_intensity"]
            frame_record["intensity"] = sample.get(
                "intensity", record.get("intensity")
            )
            frame_record["exposure"] = sample.get(
                "exposure", record.get("exposure")
            )
            key_data_value(
                data,
                "energy",
                light_energy(
                    frame_record, blender_type, position_scale, power_scale
                ),
                frame,
            )
        # A temperature driven light takes its colour from the temperature
        # input, so keying the swatch would fight it.
        if "color" in sample and not temperature_driven:
            key_data_value(data, "color", light_color(sample), frame)

    return animate_object(obj, record, position_scale, apply_sample)


def configure_area_light(
    data,
    area_shape,
    size_x,
    size_y,
    size_z,
    parameters,
    warnings,
    light_name,
):
    if area_shape == "DISK":
        data.shape = "DISK"
        data.size = max(size_x, size_y)
    else:
        data.shape = "RECTANGLE"
        data.size = size_x
        data.size_y = size_y

    if area_shape in ("CYLINDER", "MESH"):
        warnings.append(
            '{0} area shape on "{1}" was approximated with a rectangular '
            "Blender Area light.".format(area_shape.title(), light_name)
        )
        if area_shape == "CYLINDER":
            data.size_y = max(size_y, size_z)

    if hasattr(data, "spread") and "spread" in parameters:
        spread = max(0.0, min(1.0, scalar(parameters.get("spread"), 1.0)))
        data.spread = max(0.0001, spread * math.pi)


def configure_spot_light(data, parameters, position_scale):
    cone_angle = max(0.1, min(179.0, scalar(parameters.get("cone_angle"), 45.0)))
    falloff_angle = abs(
        scalar(parameters.get("falloff_angle"), cone_angle * 0.15)
    )
    data.spot_size = math.radians(cone_angle)
    data.spot_blend = max(
        0.0,
        min(1.0, falloff_angle / max(cone_angle * 0.5, 0.0001)),
    )
    data.shadow_soft_size = max(
        0.0,
        scalar(parameters.get("shadow_softness"), 0.0) * position_scale,
    )


def renderer_key(record):
    """Which renderer's conventions a light record follows."""
    node_type = str(record.get("node_type") or "").lower()
    if "redshift" in node_type:
        return "redshift"
    if node_type.startswith("ai"):
        return "arnold"
    return "maya"


def source_is_normalized(record):
    """Whether the source intensity already means total output.

    Arnold, Redshift and native Maya all default this on, and Blender's Power
    means total flux, so an absent flag is treated as normalized.
    """
    parameters = record.get("parameters") or {}
    if "normalize" not in parameters:
        return True
    return bool(parameters.get("normalize"))


def light_energy(record, blender_type, position_scale, power_scale=None):
    """Total radiant flux for a source light, in the watts Blender Power wants.

    Every branch returns flux, because the caller leaves Blender's normalize
    on. The photometric branches are exact conversions, and so is the Arnold
    one: its dimensionless intensity converts through a measured factor of pi.
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

    # Sun Strength is irradiance on the surface, so neither area nor the
    # normalize convention applies to it.
    if blender_type == "SUN":
        return effective
    if "lumen" in units:
        return effective / LUMENS_PER_WATT
    if "candela" in units:
        return effective * (4.0 * math.pi) / LUMENS_PER_WATT
    if "watt" in units:
        return effective
    if "nit" in units or "radiance" in units or "exitance" in units:
        # Radiance is per unit area by definition, so this conversion always
        # needs the area regardless of the normalize flag.
        area = max(0.000001, emitting_surface_area(record, position_scale))
        return effective * area * math.pi / LUMENS_PER_WATT

    # A dimensionless intensity illuminates according to the scene's raw
    # numbers, because Arnold and Redshift are unit agnostic: a light 150
    # units away falls off as 1/150 squared whatever those units mean. Blender
    # works in metres, so the same light sits 1.5 m away and would be ten
    # thousand times brighter unless the unit scale is folded in as well.
    watts_per_intensity = WATTS_PER_INTENSITY.get(renderer_key(record), math.pi)
    unit_scale = max(1e-12, scalar(position_scale, 1.0)) ** 2
    flux = effective * watts_per_intensity * unit_scale * power_scale
    if blender_type == "AREA" and not source_is_normalized(record):
        # A non-normalized source states intensity per unit area; Blender
        # Power does not, so the area is folded in here exactly once.
        flux *= max(0.000001, emitting_surface_area(record, position_scale))
    return flux


def area_size_factor(record):
    """Emitting size per unit of transform scale, by renderer convention."""
    return AREA_SIZE_PER_SCALE.get(renderer_key(record), 1.0)


def emitting_dimensions(record, position_scale):
    """The light's emitting size in metres, on each axis."""
    scale = source_light_scale(record)
    factor = area_size_factor(record) * position_scale
    return tuple(max(0.0001, value * factor) for value in scale[:3])


def emitting_surface_area(record, position_scale):
    """Emitting area in square metres, matching the shape actually built.

    Only radiance style units need this. The dimensions follow what
    ``configure_area_light`` puts on the light data: rectangles use width by
    height, while discs and spheres treat the larger dimension as a diameter.
    """
    width, height, depth = emitting_dimensions(record, position_scale)
    shape = str(record.get("area_shape") or "RECTANGLE").upper()

    if shape == "DISK":
        radius = max(width, height) * 0.5
        return math.pi * radius * radius
    if shape == "SPHERE":
        radius = max(width, height, depth) * 0.5
        return 4.0 * math.pi * radius * radius
    return width * height


def light_color(record):
    return color4(record.get("color") or (1.0, 1.0, 1.0))[:3]


def apply_light_temperature(data, record, warnings=None):
    """Apply colour temperature, honouring Maya's colour/temperature modes.

    Blender only grew light temperature sockets in 4.2; on older builds the
    value cannot be represented, so the caller is warned rather than left with
    a silently white light.
    """
    parameters = record.get("parameters") or {}
    mode = str((record.get("enum_labels") or {}).get("color_mode") or "").lower()
    use_temperature = bool(parameters.get("use_temperature", False))
    if "temperature" in mode:
        use_temperature = True
        # Temperature-only mode ignores the colour swatch entirely.
        if "color and" not in mode and "color+" not in mode:
            data.color = (1.0, 1.0, 1.0)
    temperature = max(
        800.0,
        min(20000.0, scalar(parameters.get("temperature"), 6500.0)),
    )

    if not hasattr(data, "temperature"):
        if use_temperature and warnings is not None:
            warnings.append(
                'Colour temperature {0:.0f}K on "{1}" was dropped; this '
                "Blender version has no light temperature input.".format(
                    temperature,
                    data.name,
                )
            )
        return

    if hasattr(data, "use_temperature"):
        data.use_temperature = use_temperature
    data.temperature = temperature


def configure_light_texture_nodes(data, record, warnings):
    """Build light node trees for colour textures, IES profiles and decay."""
    color_texture = record.get("color_texture") or {}
    ies_record = record.get("ies_profile") or {}
    color_path = color_texture.get("path") or ""
    ies_path = ies_record.get("path") or ""
    decay_label = str((record.get("enum_labels") or {}).get("decay") or "").lower()
    custom_decay = "linear" in decay_label or any(
        token in decay_label for token in ("none", "constant")
    )
    if not color_path and not ies_path and not custom_decay:
        return
    if not hasattr(data, "use_nodes"):
        return

    try:
        data.use_nodes = True
        nodes = data.node_tree.nodes
        links = data.node_tree.links
        emission = next(
            (node for node in nodes if node.bl_idname == "ShaderNodeEmission"),
            None,
        )
        if emission is None:
            return
        strength_output = None

        if color_path:
            image = load_image(color_texture, "base_color", warnings)
            if image:
                image_node = nodes.new("ShaderNodeTexImage")
                image_node.name = "ZA_Light_Color_Texture"
                image_node.image = image
                links.new(
                    image_node.outputs.get("Color"),
                    emission.inputs.get("Color"),
                )

        if custom_decay:
            falloff = nodes.new("ShaderNodeLightFalloff")
            # Unit strength on purpose: data.energy already scales the light's
            # node tree, so feeding energy in here would apply it twice.
            falloff.inputs["Strength"].default_value = NODE_TREE_UNIT_STRENGTH
            output_name = "Linear" if "linear" in decay_label else "Constant"
            strength_output = falloff.outputs.get(output_name)

        if ies_path and os.path.isfile(ies_path):
            try:
                ies_node = nodes.new("ShaderNodeTexIES")
                if hasattr(ies_node, "mode"):
                    ies_node.mode = "EXTERNAL"
                ies_node.filepath = ies_path
                multiply = nodes.new("ShaderNodeMath")
                multiply.operation = "MULTIPLY"
                links.new(ies_node.outputs.get("Fac"), multiply.inputs[0])
                if strength_output is not None:
                    links.new(strength_output, multiply.inputs[1])
                else:
                    multiply.inputs[1].default_value = NODE_TREE_UNIT_STRENGTH
                strength_output = multiply.outputs[0]
            except Exception as exc:
                warnings.append(
                    'IES profile could not be connected on "{0}": {1}'.format(
                        data.name,
                        exc,
                    )
                )
        elif ies_path:
            warnings.append(
                'IES profile was not found for "{0}": {1}'.format(
                    data.name,
                    ies_path,
                )
            )

        if strength_output is not None:
            links.new(strength_output, emission.inputs.get("Strength"))
    except Exception as exc:
        warnings.append(
            'Light texture nodes could not be built for "{0}": {1}'.format(
                data.name,
                exc,
            )
        )


def create_dome_world(dome_records, collection, position_scale, warnings):
    """Rebuild the first enabled Dome as the scene World environment.

    Blender has a single World, so extra domes survive only as metadata
    empties carrying their original Redshift values.
    """
    bpy.context.scene.world = None
    if not dome_records:
        return 0

    enabled_records = [
        record for record in dome_records
        if bool(record.get("enabled", True))
    ]
    selected = enabled_records[0] if enabled_records else dome_records[0]
    if len(dome_records) > 1:
        warnings.append(
            "Blender has one active World environment; the first enabled "
            "Redshift Dome light was used and the remaining domes were kept "
            "as metadata empties."
        )

    world = bpy.data.worlds.new("Z-A Dome World")
    world.use_nodes = True
    bpy.context.scene.world = world
    nodes = world.node_tree.nodes
    links = world.node_tree.links
    nodes.clear()
    output = nodes.new("ShaderNodeOutputWorld")
    background = nodes.new("ShaderNodeBackground")
    background.inputs["Color"].default_value = color4(
        selected.get("color") or (1.0, 1.0, 1.0)
    )
    background.inputs["Strength"].default_value = (
        scalar(selected.get("effective_intensity"), 1.0)
        if bool(selected.get("enabled", True))
        else 0.0
    )
    links.new(background.outputs["Background"], output.inputs["Surface"])

    texture_record = selected.get("dome_texture") or {}
    if texture_record.get("path"):
        image = load_image(texture_record, "base_color", warnings)
        if image:
            _build_dome_environment(
                nodes,
                links,
                background,
                image,
                selected,
                position_scale,
            )

    for record in dome_records:
        _create_dome_metadata_empty(record, collection, position_scale)
    return len(dome_records)


def _build_dome_environment(
    nodes,
    links,
    background,
    image,
    record,
    position_scale,
):
    environment = nodes.new("ShaderNodeTexEnvironment")
    environment.image = image
    texcoord = nodes.new("ShaderNodeTexCoord")
    mapping = nodes.new("ShaderNodeMapping")
    vector_output = (
        texcoord.outputs.get("Generated")
        or texcoord.outputs.get("Normal")
    )
    links.new(vector_output, mapping.inputs["Vector"])
    links.new(mapping.outputs["Vector"], environment.inputs["Vector"])

    tint = nodes.new("ShaderNodeMixRGB")
    tint.blend_type = "MULTIPLY"
    tint.inputs[0].default_value = 1.0
    tint.inputs[2].default_value = color4(record.get("color") or (1.0, 1.0, 1.0))
    links.new(environment.outputs["Color"], tint.inputs[1])
    links.new(tint.outputs["Color"], background.inputs["Color"])

    # The Mapping node rotates the lookup vector, not the image, so a rotated
    # dome may need the inverse of this. Unverified against a real Redshift
    # dome; if HDRs land mirrored or offset, this line is the place to look.
    matrix = maya_matrix_to_blender(record.get("transform") or {}, position_scale)
    mapping.inputs["Rotation"].default_value = matrix.to_euler()


def _create_dome_metadata_empty(record, collection, position_scale):
    name = (
        record.get("name")
        or namespace_free_name(record.get("full_name"))
        or "Dome"
    )
    empty = bpy.data.objects.new(name, None)
    empty.empty_display_type = "SPHERE"
    empty.empty_display_size = 1.0
    collection.objects.link(empty)
    empty.matrix_world = maya_matrix_to_blender(
        record.get("transform") or {},
        position_scale,
    )
    empty.scale = (1.0, 1.0, 1.0)
    store_light_metadata(empty, None, record)
    return empty






def store_light_metadata(obj, data, record):
    """Keep the original Maya values on the light data, or the empty."""
    target = data if data is not None else obj
    target["za_generated"] = True
    target["za_source_full_name"] = str(record.get("full_name") or "")
    target["za_source_node_type"] = str(record.get("node_type") or "")
    target["za_source_light_kind"] = str(record.get("light_kind") or "")
    target["za_source_intensity"] = scalar(record.get("intensity"), 1.0)
    target["za_source_exposure"] = scalar(record.get("exposure"), 0.0)
    # Kept because the flag is consumed during the flux conversion rather than
    # passed to Blender, so this is the only record of what the source said.
    target["za_source_normalized"] = source_is_normalized(record)
    target["za_source_renderer"] = renderer_key(record)
    target["za_source_json"] = json.dumps(record, ensure_ascii=False)
