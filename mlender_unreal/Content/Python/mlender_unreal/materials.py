# -*- coding: utf-8 -*-
"""Maya shaders rebuilt as Unreal materials.

Two facts about Unreal shaped this, and both are the opposite of how the
Blender receiver works:

* **Blend mode and shading model belong to the Material, not the instance.**
  A Material Instance can override a parameter but not whether the surface is
  opaque, masked, translucent or unlit. So a single master material cannot
  cover a scene containing glass, a cutout and an unlit shader. This module
  generates one master per surface class and instances the right one.
* **There is no Principled BSDF.** Unreal's material inputs are read off
  ``unreal.MaterialProperty``, and probing it on 5.8.1 returns no coat and no
  sheen input at all. Those channels therefore cannot be wired, and are
  reported and kept as metadata rather than folded into something they are not.

Optional textures use a lerp against a flat value driven by a scalar
parameter, rather than a static switch. It costs a texture sample that is then
discarded, and it buys an instance that needs no shader permutation and no
per-material compile -- which is the whole reason to use instances.
"""

import unreal

from .constants import (
    ASSET_PREFIX,
    BLEND_MODE_MASKED,
    BLEND_MODE_OPAQUE,
    BLEND_MODE_TRANSLUCENT,
    COLOUR_CHANNELS,
    MATERIAL_CONTENT_PATH,
    MASTER_SCALAR_PARAMETERS,
    MASTER_TEXTURE_PARAMETERS,
    MASTER_VECTOR_PARAMETERS,
    MASTER_SWITCH_SUFFIX,
    OPACITY_MASKED_THRESHOLD,
    SPECULAR_WEIGHT_TO_LEVEL,
    UNREAL_METADATA_CHANNELS,
)
from .images import load_texture
from .utils import (
    channel_texture_path,
    colour,
    is_colour_data,
    safe_asset_name,
    scalar,
)


# A white texture the master's samplers can default to. A
# TextureSampleParameter2D with no texture will not compile, and this is an
# engine asset so nothing has to ship with the plugin.
DEFAULT_TEXTURE_PATH = "/Engine/EngineResources/WhiteSquareTexture"

SURFACE_OPAQUE = "opaque"
SURFACE_MASKED = "masked"
SURFACE_TRANSLUCENT = "translucent"
SURFACE_UNLIT = "unlit"

# Which Unreal material input each channel reaches. Anything not here is
# metadata, and UNREAL_METADATA_CHANNELS says so explicitly.
CHANNEL_TO_PROPERTY = {
    "base_color": "MP_BASE_COLOR",
    "roughness": "MP_ROUGHNESS",
    "metallic": "MP_METALLIC",
    "specular": "MP_SPECULAR",
    "normal": "MP_NORMAL",
    "emission": "MP_EMISSIVE_COLOR",
    "opacity": "MP_OPACITY",
    "anisotropic": "MP_ANISOTROPY",
    "subsurface_color": "MP_SUBSURFACE_COLOR",
}

_master_cache = {}


def reset_cache():
    _master_cache.clear()


# --------------------------------------------------------------- surface class
def resolve_surface_class(record, warnings):
    """Which master material a Maya shader belongs to.

    Mirrors the Blender receiver's three build paths, with masked split out of
    translucent because Unreal treats them as different surfaces and the cost
    difference is real.
    """
    channels = record.get("channels") or {}
    mode = str(record.get("material_mode") or "").lower()
    if mode in ("unlit", "emission") or record.get("unlit"):
        return SURFACE_UNLIT
    transmission = scalar(
        (channels.get("transmission") or {}).get("value"), 0.0
    )
    if transmission > 0.0:
        return SURFACE_TRANSLUCENT
    opacity_record = channels.get("opacity") or {}
    opacity = scalar(opacity_record.get("value"), 1.0)
    if channel_texture_path(opacity_record):
        return SURFACE_MASKED
    if opacity < OPACITY_MASKED_THRESHOLD:
        return SURFACE_MASKED
    return SURFACE_OPAQUE


# --------------------------------------------------------------- master build
def _expression(material, class_name, x, y):
    cls = getattr(unreal, class_name, None)
    if cls is None:
        return None
    return unreal.MaterialEditingLibrary.create_material_expression(
        material, cls, x, y
    )


def _scalar_parameter(material, name, default, x, y):
    node = _expression(material, "MaterialExpressionScalarParameter", x, y)
    if node is None:
        return None
    node.set_editor_property("parameter_name", name)
    node.set_editor_property("default_value", float(default))
    return node


def _vector_parameter(material, name, default, x, y):
    node = _expression(material, "MaterialExpressionVectorParameter", x, y)
    if node is None:
        return None
    node.set_editor_property("parameter_name", name)
    node.set_editor_property(
        "default_value",
        unreal.LinearColor(default[0], default[1], default[2], 1.0),
    )
    return node


def _texture_parameter(material, name, x, y, sampler_type=None):
    node = _expression(
        material, "MaterialExpressionTextureSampleParameter2D", x, y
    )
    if node is None:
        return None
    node.set_editor_property("parameter_name", name)
    default = unreal.EditorAssetLibrary.load_asset(DEFAULT_TEXTURE_PATH)
    if default is not None:
        node.set_editor_property("texture", default)
    if sampler_type is not None:
        try:
            node.set_editor_property("sampler_type", sampler_type)
        except Exception:
            pass
    return node


def _lerp(material, flat, texture, switch, x, y):
    """flat when the switch is 0, the texture when it is 1."""
    node = _expression(
        material, "MaterialExpressionLinearInterpolate", x, y
    )
    if node is None:
        return None
    library = unreal.MaterialEditingLibrary
    library.connect_material_expressions(flat, "", node, "A")
    library.connect_material_expressions(texture, "", node, "B")
    library.connect_material_expressions(switch, "", node, "Alpha")
    return node


def _connect(material, node, property_name):
    prop = getattr(unreal.MaterialProperty, property_name, None)
    if prop is None or node is None:
        return False
    try:
        unreal.MaterialEditingLibrary.connect_material_property(
            node, "", prop
        )
        return True
    except Exception:
        return False


def _build_master(surface_class, warnings):
    """Create one master material for a surface class.

    Built from Python rather than shipped as a .uasset: a binary asset in the
    repository is a thing nobody can review, and it would have to be rebuilt
    for every engine version anyway.
    """
    name = "{0}Master_{1}".format(ASSET_PREFIX, surface_class.capitalize())
    path = "{0}/{1}".format(MATERIAL_CONTENT_PATH, name)
    if unreal.EditorAssetLibrary.does_asset_exist(path):
        existing = unreal.EditorAssetLibrary.load_asset(path)
        if existing is not None:
            return existing

    tools = unreal.AssetToolsHelpers.get_asset_tools()
    material = tools.create_asset(
        name, MATERIAL_CONTENT_PATH, unreal.Material,
        unreal.MaterialFactoryNew()
    )
    if material is None:
        raise RuntimeError(
            "Unreal refused to create the master material {0}".format(name)
        )

    if surface_class == SURFACE_UNLIT:
        material.set_editor_property(
            "shading_model", unreal.MaterialShadingModel.MSM_UNLIT
        )
    blend = {
        SURFACE_OPAQUE: BLEND_MODE_OPAQUE,
        SURFACE_MASKED: BLEND_MODE_MASKED,
        SURFACE_TRANSLUCENT: BLEND_MODE_TRANSLUCENT,
        SURFACE_UNLIT: BLEND_MODE_OPAQUE,
    }[surface_class]
    blend_value = getattr(unreal.BlendMode, blend, None)
    if blend_value is not None:
        material.set_editor_property("blend_mode", blend_value)
    if surface_class == SURFACE_TRANSLUCENT:
        try:
            material.set_editor_property(
                "translucency_lighting_mode",
                unreal.TranslucencyLightingMode.TLM_SURFACE_PER_PIXEL_LIGHTING,
            )
        except Exception:
            pass

    row = 0

    def place(offset=0):
        return -900, -700 + (row + offset) * 150

    # Colour and scalar channels that can also carry a texture.
    for channel, parameter in sorted(MASTER_TEXTURE_PARAMETERS.items()):
        x, y = place()
        switch = _scalar_parameter(
            material, parameter + MASTER_SWITCH_SUFFIX, 0.0, x - 400, y + 80
        )
        sampler = (
            unreal.MaterialSamplerType.SAMPLERTYPE_NORMAL
            if channel == "normal"
            else unreal.MaterialSamplerType.SAMPLERTYPE_COLOR
            if channel in COLOUR_CHANNELS
            else unreal.MaterialSamplerType.SAMPLERTYPE_LINEAR_GRAYSCALE
        )
        texture = _texture_parameter(material, parameter, x - 400, y, sampler)
        if channel in MASTER_VECTOR_PARAMETERS:
            flat = _vector_parameter(
                material, MASTER_VECTOR_PARAMETERS[channel],
                (0.5, 0.5, 0.5), x - 400, y - 90
            )
        elif channel == "normal":
            flat = _expression(
                material, "MaterialExpressionConstant3Vector", x - 400, y - 90
            )
            if flat is not None:
                flat.set_editor_property(
                    "constant", unreal.LinearColor(0.0, 0.0, 1.0, 1.0)
                )
        else:
            flat = _scalar_parameter(
                material, MASTER_SCALAR_PARAMETERS.get(channel, parameter),
                0.5, x - 400, y - 90
            )
        if None in (switch, texture, flat):
            warnings.append(
                'Master material "{0}" could not build the "{1}" channel; '
                "this engine did not provide one of its expression "
                "types.".format(name, channel)
            )
            row += 1
            continue
        mixed = _lerp(material, flat, texture, switch, x, y)
        target = CHANNEL_TO_PROPERTY.get(channel)
        if channel == "emission":
            strength = _scalar_parameter(
                material, MASTER_SCALAR_PARAMETERS["emission_strength"],
                1.0, x + 150, y + 120
            )
            multiply = _expression(
                material, "MaterialExpressionMultiply", x + 350, y
            )
            if strength is not None and multiply is not None:
                library = unreal.MaterialEditingLibrary
                library.connect_material_expressions(mixed, "", multiply, "A")
                library.connect_material_expressions(
                    strength, "", multiply, "B"
                )
                mixed = multiply
        if target:
            _connect(material, mixed, target)
        # Masked surfaces drive the mask from the same opacity chain.
        if channel == "opacity" and surface_class == SURFACE_MASKED:
            _connect(material, mixed, "MP_OPACITY_MASK")
        row += 1

    # Scalar-only channels: no texture slot, so a plain parameter is enough.
    for channel, parameter in sorted(MASTER_SCALAR_PARAMETERS.items()):
        if channel in MASTER_TEXTURE_PARAMETERS or channel == "emission_strength":
            continue
        x, y = place()
        node = _scalar_parameter(material, parameter, 0.0, x - 400, y)
        target = CHANNEL_TO_PROPERTY.get(channel)
        if target:
            _connect(material, node, target)
        row += 1

    unreal.MaterialEditingLibrary.recompile_material(material)
    unreal.EditorAssetLibrary.save_loaded_asset(material, False)
    return material


def master_material(surface_class, warnings):
    if surface_class not in _master_cache:
        _master_cache[surface_class] = _build_master(surface_class, warnings)
    return _master_cache[surface_class]


# --------------------------------------------------------------- instances
def _set_scalar(instance, name, value):
    try:
        unreal.MaterialEditingLibrary.set_material_instance_scalar_parameter_value(
            instance, name, float(value)
        )
    except Exception:
        pass


def _set_vector(instance, name, values):
    try:
        unreal.MaterialEditingLibrary.set_material_instance_vector_parameter_value(
            instance, name,
            unreal.LinearColor(values[0], values[1], values[2], 1.0)
        )
    except Exception:
        pass


def _set_texture(instance, name, texture):
    try:
        unreal.MaterialEditingLibrary.set_material_instance_texture_parameter_value(
            instance, name, texture
        )
        return True
    except Exception:
        return False


def _channel_value(channel, record):
    """The flat value for a channel, with the exporter's semantics applied."""
    if channel in MASTER_VECTOR_PARAMETERS:
        value = colour(record.get("value"), (0.5, 0.5, 0.5))
    else:
        value = scalar(record.get("value"), 0.5)
        if channel == "specular":
            # Arnold and Redshift state a 0..1 weight; Unreal's Specular is a
            # level where 0.5 is an ordinary dielectric, the same as Blender's.
            value = value * SPECULAR_WEIGHT_TO_LEVEL
    # An inversion the exporter could not apply itself, because a texture
    # cannot be inverted in Python. With no texture the flat value is the only
    # place it can still happen.
    if record.get("invert") and not isinstance(value, tuple):
        value = 1.0 - value
    return value


def build_material(record, package_folder, warnings):
    """One Material Instance Constant for one Maya shader."""
    channels = record.get("channels") or {}
    name = safe_asset_name(
        ASSET_PREFIX + str(
            record.get("material_full_name") or record.get("material") or "Mat"
        ),
        ASSET_PREFIX + "Material",
    )
    path = "{0}/{1}".format(MATERIAL_CONTENT_PATH, name)

    surface_class = resolve_surface_class(record, warnings)
    parent = master_material(surface_class, warnings)

    if unreal.EditorAssetLibrary.does_asset_exist(path):
        unreal.EditorAssetLibrary.delete_asset(path)
    tools = unreal.AssetToolsHelpers.get_asset_tools()
    instance = tools.create_asset(
        name, MATERIAL_CONTENT_PATH, unreal.MaterialInstanceConstant,
        unreal.MaterialInstanceConstantFactoryNew()
    )
    if instance is None:
        raise RuntimeError(
            "Unreal refused to create the material instance {0}".format(name)
        )
    unreal.MaterialEditingLibrary.set_material_instance_parent(
        instance, parent
    )

    for channel, channel_record in sorted(channels.items()):
        if channel in UNREAL_METADATA_CHANNELS:
            continue
        parameter = MASTER_TEXTURE_PARAMETERS.get(channel)
        texture_path = channel_texture_path(channel_record)
        texture = None
        if parameter and texture_path:
            texture = load_texture(
                channel_record,
                package_folder,
                channel,
                is_colour_data(channel, channel_record, COLOUR_CHANNELS),
                warnings,
            )
        if texture is not None and _set_texture(instance, parameter, texture):
            _set_scalar(instance, parameter + MASTER_SWITCH_SUFFIX, 1.0)
            if channel_record.get("invert"):
                warnings.append(
                    'Material "{0}" needs channel "{1}" inverted, which this '
                    "build cannot do to a texture in Unreal; the map arrived "
                    "un-inverted.".format(name, channel)
                )
            continue

        value = _channel_value(channel, channel_record)
        if channel in MASTER_VECTOR_PARAMETERS:
            _set_vector(instance, MASTER_VECTOR_PARAMETERS[channel], value)
        elif channel in MASTER_SCALAR_PARAMETERS:
            _set_scalar(instance, MASTER_SCALAR_PARAMETERS[channel], value)

    _report_unsupported(record, name, warnings)
    unreal.EditorAssetLibrary.save_loaded_asset(instance, False)
    return instance


def _report_unsupported(record, name, warnings):
    """Say what did not travel. Silence is the failure mode this repo fears."""
    channels = record.get("channels") or {}
    present = [
        channel for channel in UNREAL_METADATA_CHANNELS
        if channel in channels and (
            scalar((channels[channel] or {}).get("value"), 0.0) != 0.0
            or channel_texture_path(channels[channel])
        )
    ]
    if present:
        warnings.append(
            'Material "{0}" carries {1}, which Unreal has no material input '
            "for; the channel did not travel.".format(
                name, ", ".join(sorted(present))
            )
        )
    for channel, channel_record in sorted(channels.items()):
        texture = (channel_record or {}).get("texture") or {}
        if texture.get("unsupported_network") and not texture.get("path"):
            warnings.append(
                'Material "{0}" channel "{1}" is driven by a "{2}" network '
                "Maya could not hand over; it fell back to its flat value. "
                "Use Bake Procedurals to carry it.".format(
                    name, channel, texture.get("node_type") or "procedural"
                )
            )
        if len((channel_record or {}).get("samples") or []) >= 2:
            warnings.append(
                'Material "{0}" channel "{1}" is keyed in Maya over {2} '
                "frame(s). This build sets the first sample and does not "
                "animate it; that needs a Level Sequence.".format(
                    name, channel,
                    len((channel_record or {}).get("samples") or []),
                )
            )
        if texture.get("color_set"):
            warnings.append(
                'Material "{0}" channel "{1}" reads the vertex colour set '
                "\"{2}\". This build does not wire vertex colour into the "
                "master material, so the channel kept its flat "
                "value.".format(name, channel, texture.get("color_set"))
            )

    if record.get("corrections") or record.get("unsupported_corrections"):
        warnings.append(
            'Material "{0}" has Maya correction nodes between a texture and a '
            "channel; this build wires the texture directly, so the "
            "correction did not travel. Use Bake Procedurals to carry "
            "it.".format(name)
        )
    if record.get("layered_texture") or record.get("layers"):
        warnings.append(
            'Material "{0}" uses a layered texture stack, which this build '
            "does not rebuild in Unreal; the base layer's texture was used. "
            "Use Bake Procedurals to carry it.".format(name)
        )
