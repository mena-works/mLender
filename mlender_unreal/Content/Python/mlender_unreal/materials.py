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
    CHANNEL_WEIGHT_GATES,
    CORRECTION_CLAMP_MAX_SUFFIX,
    CORRECTION_CLAMP_MIN_SUFFIX,
    CORRECTION_CLAMP_SWITCH_SUFFIX,
    CORRECTION_GAMMA_SUFFIX,
    CORRECTION_REMAP_SUFFIX,
    CORRECTION_REMAP_SWITCH_SUFFIX,
    REMAP_LUT_SAMPLES,
    CORRECTION_OFFSET_SUFFIX,
    CORRECTION_SCALE_SUFFIX,
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
from .graphs import build_blend_material, has_layered_channel
from .images import load_texture, ramp_lut_texture
from .utils import (
    channel_texture_path,
    colour,
    is_colour_data,
    remap_curve_samples,
    safe_asset_name,
    scalar,
)


# A texture each sampler can default to. A TextureSampleParameter2D with no
# texture will not compile -- and neither will one whose texture does not
# match the sampler type it declares, which is the harder half. Measured, in a
# real editor: giving the normal and grayscale samplers a colour texture
# produced
#
#   (Node TextureSampleParameter2D) Sampler type is Linear Grayscale, should
#   be Color for /Engine/EngineResources/WhiteSquareTexture
#
# and with it "Failed to compile Material Instance with Base ML_Master_Opaque
# ... Default Material will be used in game". Every object in the level then
# wears the engine's grey checker, which reads as a transfer that dropped all
# its materials -- while every material asset in the project is correct.
#
# These are engine assets, so nothing has to ship with the plugin. Their
# compression settings are what the sampler types demand: TC_NORMALMAP for
# normal, TC_GRAYSCALE for the scalar channels, colour for the rest.
DEFAULT_TEXTURE_PATH = "/Engine/EngineResources/WhiteSquareTexture"
DEFAULT_NORMAL_TEXTURE_PATH = "/Engine/EngineMaterials/BaseFlattenNormalMap"
DEFAULT_GRAYSCALE_TEXTURE_PATH = (
    "/Engine/EngineMaterials/BaseFlattenGrayscaleMap"
)

SURFACE_OPAQUE = "opaque"
SURFACE_MASKED = "masked"
SURFACE_TRANSLUCENT = "translucent"
SURFACE_UNLIT = "unlit"
# Coat is a modifier, not a surface of its own. Unreal keeps blend mode and
# shading model apart, so a masked cutout can wear a clear coat as happily as
# an opaque surface can -- and the first version, which only coated opaque
# materials, silently dropped the coat off a half-opacity one.
COAT_SUFFIX = "|coat"

# The two metadata channels a coat master turns into real parameters.
COAT_INSTANCE_CHANNELS = ("coat", "coat_roughness")


def is_coated(surface_class):
    return str(surface_class or "").endswith(COAT_SUFFIX)


def base_surface(surface_class):
    return str(surface_class or "").split("|")[0]

# Which Unreal material input each channel reaches. Anything not here is
# metadata, and UNREAL_METADATA_CHANNELS says so explicitly.
# Clear coat lives in CustomData0/1, and the Python MaterialProperty enum does
# not expose those -- measured, MP_CUSTOMDATA0 simply is not there. The way in
# is MakeMaterialAttributes: its ClearCoat and ClearCoatRoughness pins do
# accept a connection, and a nonsense pin name is refused, so the True those
# two return means something. Everything else then has to go through the same
# node, which is why a coat master is wired differently from the other four.
PROPERTY_TO_ATTRIBUTE_PIN = {
    "MP_BASE_COLOR": "BaseColor",
    "MP_ROUGHNESS": "Roughness",
    "MP_METALLIC": "Metallic",
    "MP_SPECULAR": "Specular",
    "MP_NORMAL": "Normal",
    "MP_EMISSIVE_COLOR": "EmissiveColor",
    "MP_OPACITY": "Opacity",
    "MP_OPACITY_MASK": "OpacityMask",
    "MP_ANISOTROPY": "Anisotropy",
    "MP_SUBSURFACE_COLOR": "SubsurfaceColor",
}

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
        # An unlit surface answers no light, so a coat on it would be a
        # parameter nobody can see. Reported rather than built.
        return SURFACE_UNLIT
    coated = scalar((channels.get("coat") or {}).get("value"), 0.0) > 0.0
    transmission = scalar(
        (channels.get("transmission") or {}).get("value"), 0.0
    )
    if transmission > 0.0:
        # Translucent clear coat is a different lighting argument in Unreal,
        # and guessing at it would be worse than saying so.
        return SURFACE_TRANSLUCENT
    opacity_record = channels.get("opacity") or {}
    opacity = scalar(opacity_record.get("value"), 1.0)
    masked = (channel_texture_path(opacity_record)
              or opacity < OPACITY_MASKED_THRESHOLD)
    base = SURFACE_MASKED if masked else SURFACE_OPAQUE
    return base + COAT_SUFFIX if coated else base


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


def _default_texture_path(sampler_type):
    """The stand-in texture a sampler of this type will compile with."""
    types = unreal.MaterialSamplerType
    if sampler_type == types.SAMPLERTYPE_NORMAL:
        return DEFAULT_NORMAL_TEXTURE_PATH
    if sampler_type == types.SAMPLERTYPE_LINEAR_GRAYSCALE:
        return DEFAULT_GRAYSCALE_TEXTURE_PATH
    return DEFAULT_TEXTURE_PATH


def _texture_parameter(material, name, x, y, sampler_type=None):
    node = _expression(
        material, "MaterialExpressionTextureSampleParameter2D", x, y
    )
    if node is None:
        return None
    node.set_editor_property("parameter_name", name)
    default = unreal.EditorAssetLibrary.load_asset(
        _default_texture_path(sampler_type))
    if default is None:
        default = unreal.EditorAssetLibrary.load_asset(DEFAULT_TEXTURE_PATH)
    if default is not None:
        node.set_editor_property("texture", default)
    if sampler_type is not None:
        try:
            node.set_editor_property("sampler_type", sampler_type)
        except Exception:
            pass
    return node


# Pins that would not connect while a master was being built. A wrong pin
# name is answered with False rather than an exception, so without this the
# graph looks built and the material simply never compiles.
_UNWIRED = []


def _wire(source, node, pin):
    """Connect two expressions and record it when the pin refuses.

    Two names were wrong here for months, and both were read off the engine
    only after a whole level came in grey: the main input of a Clamp is called
    "" rather than "Input", and a Power's exponent is "Exp" rather than
    "Exponent". Each silently unconnected pin left the master uncompilable,
    which shows up as the engine's default material on every object and as
    nothing at all in any log this tool writes.
    """
    if source is None or node is None:
        return False
    try:
        joined = bool(unreal.MaterialEditingLibrary
                      .connect_material_expressions(source, "", node, pin))
    except Exception:
        joined = False
    if not joined:
        _UNWIRED.append(pin or "<the unnamed input>")
    return joined


def _lerp(material, flat, texture, switch, x, y):
    """flat when the switch is 0, the texture when it is 1."""
    node = _expression(
        material, "MaterialExpressionLinearInterpolate", x, y
    )
    if node is None:
        return None
    _wire(flat, node, "A")
    _wire(texture, node, "B")
    _wire(switch, node, "Alpha")
    return node


def _connect(material, node, property_name, attributes=None):
    """Wire a node to a material output, directly or through attributes.

    A coat master routes everything through MakeMaterialAttributes, because
    that is the only node whose ClearCoat pins Python can reach. The pin names
    differ from the property names, so the mapping is explicit rather than
    derived from the enum name.
    """
    if node is None:
        return False
    if attributes is not None:
        pin = PROPERTY_TO_ATTRIBUTE_PIN.get(property_name)
        if pin is None:
            return False
        try:
            return bool(
                unreal.MaterialEditingLibrary.connect_material_expressions(
                    node, "", attributes, pin
                )
            )
        except Exception:
            return False
    prop = getattr(unreal.MaterialProperty, property_name, None)
    if prop is None:
        return False
    try:
        unreal.MaterialEditingLibrary.connect_material_property(
            node, "", prop
        )
        return True
    except Exception:
        return False


def _correction_stack(material, parameter, sampler, x, y):
    """Gamma and clamp, sitting between a texture sample and the channel.

    Identity by default: the gamma exponent is 1 and the clamp is switched
    off, so a material with no corrections builds exactly the picture it built
    before this existed. Returns the end of the chain, or the sample itself if
    this engine will not give one of the expressions -- losing a correction is
    bad, losing the texture is worse.
    """
    library = unreal.MaterialEditingLibrary
    if sampler is None:
        return None

    # remapValue first, because in Maya it sits on the raw input. It is a
    # curve, and a curve cannot fold into a number the way the rest of the
    # chain does, so it rides as a one row texture sampled by the value.
    source = sampler
    curve = _texture_parameter(
        material, parameter + CORRECTION_REMAP_SUFFIX, x - 400, y + 300,
        unreal.MaterialSamplerType.SAMPLERTYPE_LINEAR_GRAYSCALE,
    )
    coordinate = _expression(
        material, "MaterialExpressionAppendVector", x - 260, y + 300
    )
    half = _expression(material, "MaterialExpressionConstant", x - 400, y + 360)
    remap_use = _scalar_parameter(
        material, parameter + CORRECTION_REMAP_SWITCH_SUFFIX, 0.0,
        x - 400, y + 420
    )
    if None not in (curve, coordinate, half, remap_use):
        try:
            half.set_editor_property("r", 0.5)
        except Exception:
            pass
        _wire(sampler, coordinate, "A")
        _wire(half, coordinate, "B")
        _wire(coordinate, curve, "UVs")
        remapped = _lerp(material, sampler, curve, remap_use, x - 120, y + 300)
        if remapped is not None:
            source = remapped

    exponent = _scalar_parameter(
        material, parameter + CORRECTION_GAMMA_SUFFIX, 1.0, x - 200, y + 60
    )
    power = _expression(material, "MaterialExpressionPower", x, y)
    if exponent is None or power is None:
        return source
    _wire(source, power, "Base")
    _wire(exponent, power, "Exp")

    # Everything a colour correct node does after its gamma -- contrast,
    # exposure, multiply, add -- is affine, so the whole tail is one multiply
    # and one add. Identity until a material sets them.
    head = power
    scale = _scalar_parameter(
        material, parameter + CORRECTION_SCALE_SUFFIX, 1.0, x - 200, y - 60
    )
    times = _expression(material, "MaterialExpressionMultiply", x + 100, y)
    if scale is not None and times is not None:
        _wire(head, times, "A")
        _wire(scale, times, "B")
        head = times
    offset = _scalar_parameter(
        material, parameter + CORRECTION_OFFSET_SUFFIX, 0.0, x - 200, y - 120
    )
    plus = _expression(material, "MaterialExpressionAdd", x + 160, y)
    if offset is not None and plus is not None:
        _wire(head, plus, "A")
        _wire(offset, plus, "B")
        head = plus

    low = _scalar_parameter(
        material, parameter + CORRECTION_CLAMP_MIN_SUFFIX, 0.0,
        x - 200, y + 120
    )
    high = _scalar_parameter(
        material, parameter + CORRECTION_CLAMP_MAX_SUFFIX, 1.0,
        x - 200, y + 180
    )
    clamp = _expression(material, "MaterialExpressionClamp", x + 200, y)
    use = _scalar_parameter(
        material, parameter + CORRECTION_CLAMP_SWITCH_SUFFIX, 0.0,
        x - 200, y + 240
    )
    if None in (low, high, clamp, use):
        return head
    _wire(head, clamp, "")
    _wire(low, clamp, "Min")
    _wire(high, clamp, "Max")
    # Switched rather than always on: a clamp to 0..1 is not identity for a
    # channel that legitimately goes past one, and emission does.
    return _lerp(material, head, clamp, use, x + 400, y) or clamp


def _build_master(surface_class, warnings):
    """Create one master material for a surface class.

    Built from Python rather than shipped as a .uasset: a binary asset in the
    repository is a thing nobody can review, and it would have to be rebuilt
    for every engine version anyway.
    """
    # "masked|coat" is a surface class, not an asset name -- the separator
    # would be rejected, so each part is capitalised and joined with an
    # underscore: ML_Master_Masked_Coat.
    name = "{0}Master_{1}".format(
        ASSET_PREFIX,
        "_".join(part.capitalize() for part in surface_class.split("|")),
    )
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

    if base_surface(surface_class) == SURFACE_UNLIT:
        material.set_editor_property(
            "shading_model", unreal.MaterialShadingModel.MSM_UNLIT
        )
    attributes = None
    if is_coated(surface_class):
        material.set_editor_property(
            "shading_model", unreal.MaterialShadingModel.MSM_CLEAR_COAT
        )
        material.set_editor_property("use_material_attributes", True)
        attributes = _expression(
            material, "MaterialExpressionMakeMaterialAttributes", -300, 0
        )
        if attributes is None:
            warnings.append(
                "This engine has no MakeMaterialAttributes expression, so a "
                "coated material was built without its coat."
            )
        else:
            prop = getattr(
                unreal.MaterialProperty, "MP_MATERIAL_ATTRIBUTES", None
            )
            if prop is not None:
                unreal.MaterialEditingLibrary.connect_material_property(
                    attributes, "", prop
                )
    blend = {
        SURFACE_OPAQUE: BLEND_MODE_OPAQUE,
        SURFACE_MASKED: BLEND_MODE_MASKED,
        SURFACE_TRANSLUCENT: BLEND_MODE_TRANSLUCENT,
        SURFACE_UNLIT: BLEND_MODE_OPAQUE,
    }[base_surface(surface_class)]
    blend_value = getattr(unreal.BlendMode, blend, None)
    if blend_value is not None:
        material.set_editor_property("blend_mode", blend_value)
    if base_surface(surface_class) == SURFACE_TRANSLUCENT:
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
        corrected = _correction_stack(
            material, parameter, texture, x - 200, y
        )
        if corrected is not None:
            texture = corrected
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
            _connect(material, mixed, target, attributes)
        # Masked surfaces drive the mask from the same opacity chain.
        if channel == "opacity" and base_surface(surface_class) == SURFACE_MASKED:
            _connect(material, mixed, "MP_OPACITY_MASK", attributes)
        row += 1

    # Scalar-only channels: no texture slot, so a plain parameter is enough.
    for channel, parameter in sorted(MASTER_SCALAR_PARAMETERS.items()):
        if channel in MASTER_TEXTURE_PARAMETERS or channel == "emission_strength":
            continue
        x, y = place()
        node = _scalar_parameter(material, parameter, 0.0, x - 400, y)
        target = CHANNEL_TO_PROPERTY.get(channel)
        if target:
            _connect(material, node, target, attributes)
        row += 1

    if attributes is not None:
        # The coat itself. Its tint and IOR have no Unreal input at all, so
        # they stay in the report rather than being approximated here.
        library = unreal.MaterialEditingLibrary
        for parameter, pin, default in (
            (MASTER_SCALAR_PARAMETERS["coat"], "ClearCoat", 0.0),
            (MASTER_SCALAR_PARAMETERS["coat_roughness"],
             "ClearCoatRoughness", 0.1),
        ):
            x, y = place()
            node = _scalar_parameter(material, parameter, default, x - 400, y)
            if node is not None:
                _wire(node, attributes, pin)
            row += 1

    # Any pin that refused, said out loud. A master with an unconnected input
    # does not compile, and a material that does not compile is drawn as the
    # engine's grey default on every object that wears it -- which is a whole
    # scene looking broken, from a mistyped pin name.
    if _UNWIRED:
        warnings.append(
            'Master material "{0}" could not connect {1} input(s) ({2}); it '
            "will not compile, and everything using it will draw with the "
            "engine's default material.".format(
                name, len(_UNWIRED), ", ".join(sorted(set(_UNWIRED))[:6])
            )
        )
        del _UNWIRED[:]

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


def channel_value(channel, record):
    """The flat value for a channel, with the exporter semantics applied.

    Public because the animation module keys the same channels and has to
    apply the same rules -- a keyed specular that skipped the weight-to-level
    conversion would animate to a different place than frame one sits.
    """
    return _channel_value(channel, record)


def build_material(record, package_folder, warnings):
    """One Material Instance Constant for one Maya shader."""
    # A blend shader is a stack of surfaces, which a Material Instance cannot
    # express: an instance shares one master and can only change its numbers.
    # That case gets a graph of its own -- the other half of the hybrid.
    if len(record.get("layers") or []) > 1 or has_layered_channel(record):
        graph = build_blend_material(record, package_folder, warnings)
        if graph is not None:
            _report_unsupported(record, safe_asset_name(
                record.get("material") or "Material", "Material"), warnings,
                carried_layers=True)
            return graph

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

    unrebuilt_corrections = []
    for channel, channel_record in sorted(channels.items()):
        # Metadata channels have no socket to reach -- except on a coat
        # master, where coat and its roughness became real parameters. Left
        # in place, this skip built the coat master, parented the instance to
        # it and then set nothing, so a coated material arrived with a coat
        # weight of zero: all the plumbing and none of the water.
        if channel in UNREAL_METADATA_CHANNELS and not (
                is_coated(surface_class)
                and channel in COAT_INSTANCE_CHANNELS):
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
        # The Maya nodes that sat between this texture and the shader. What
        # cannot be rebuilt is reported whether or not the texture loaded: a
        # chain that did not travel did not travel either way, and a first
        # version that only reported alongside a working texture said nothing
        # at all about the scene's one colour correct node.
        applied = apply_corrections(
            instance, channel_record, parameter if texture is not None else ""
        )
        for kind in applied:
            unrebuilt_corrections.append((channel, kind))
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

    if unrebuilt_corrections:
        warnings.append(
            'Material "{0}" has Maya correction nodes this build cannot '
            "rebuild in Unreal: {1}. Gamma and clamp travel; the rest left "
            "the texture uncorrected. Use Bake Procedurals to carry "
            "them.".format(
                name,
                ", ".join(sorted(set(
                    '{0} on "{1}"'.format(kind, channel)
                    for channel, kind in unrebuilt_corrections
                ))),
            )
        )
    _report_unsupported(record, name, warnings, surface_class)
    unreal.EditorAssetLibrary.save_loaded_asset(instance, False)
    return instance


def _channel_is_live(channels, channel):
    """Whether a channel is doing anything at all.

    A value or a texture makes it live, but only if whatever weights it is
    also on: a coat IOR under a coat weight of zero is a number in a record,
    not something the image would show.
    """
    record = channels.get(channel)
    if record is None:
        return False
    if (scalar((record or {}).get("value"), 0.0) == 0.0
            and not channel_texture_path(record)):
        return False
    gate = CHANNEL_WEIGHT_GATES.get(channel)
    if gate is None:
        return True
    gate_record = channels.get(gate)
    if gate_record is None:
        return False
    return (scalar((gate_record or {}).get("value"), 0.0) != 0.0
            or bool(channel_texture_path(gate_record)))


def _first(value, fallback):
    """A Maya colour attribute arrives as a triple; a scalar arrives alone."""
    if isinstance(value, (list, tuple)):
        return scalar(value[0], fallback) if value else fallback
    return scalar(value, fallback)


def _is_uniform(value):
    """Whether a colour attribute holds the same number in all channels.

    The correction stack carries one scalar per slot, so a gain of
    (2, 1, 0.5) cannot ride on it. Taking the red channel and going quiet
    would be a silent loss of the other two.
    """
    if not isinstance(value, (list, tuple)) or len(value) < 2:
        return True
    first = scalar(value[0], 0.0)
    return all(abs(scalar(item, 0.0) - first) < 1e-6 for item in value[1:])


def apply_corrections(instance, channel_record, parameter):
    """Set the correction parameters from a Maya chain.

    Returns the correction kinds this build did not rebuild, so the caller can
    name them rather than report a count.

    The model is deliberately small: one gamma, then one affine. That is
    exactly what a measured aiColorCorrect collapses to -- its chain runs
    invert, gamma, contrast, exposure, multiply, add, and everything after the
    gamma is affine (tests/docs/color_correct.md). A gammaCorrect folds into
    the same gamma and a clamp rides on the end.

    What will not fold says so instead of being approximated:

    * saturation and hue work in HSV, not on channels
    * a second gamma arriving after an affine step cannot be composed with it
    * invert sits before the gamma, so it only folds when the gamma is idle
    """
    texture = (channel_record or {}).get("texture") or {}
    chain = texture.get("corrections") or []
    if not chain:
        return []

    unhandled = []
    gamma = 1.0
    scale = 1.0
    shift = 0.0
    remap = None
    clamp_low = None
    clamp_high = None
    # A one item list so the closures below can read it without rebinding.
    identity_so_far = [True]

    def affine_is_identity():
        return abs(scale - 1.0) < 1e-6 and abs(shift) < 1e-6

    for entry in chain:
        kind = str((entry or {}).get("type") or "")
        parameters = (entry or {}).get("parameters") or {}

        identity_so_far[0] = (affine_is_identity()
                              and abs(gamma - 1.0) < 1e-6
                              and remap is None)

        if kind == "gammaCorrect":
            value = _first(parameters.get("gamma"), 1.0)
            if not value:
                continue
            if not affine_is_identity():
                unhandled.append("gammaCorrect after another correction")
                continue
            gamma = gamma * value

        elif kind == "remapValue":
            if not identity_so_far[0]:
                unhandled.append("remapValue after another correction")
                continue
            curve_values = remap_curve_samples(parameters, REMAP_LUT_SAMPLES)
            if curve_values is None:
                unhandled.append("remapValue with no usable curve")
            else:
                remap = curve_values

        elif kind == "clamp":
            clamp_low = _first(parameters.get("clamp_min"), 0.0)
            clamp_high = _first(parameters.get("clamp_max"), 1.0)

        elif kind == "aiColorCorrect":
            for name, identity in (("saturation", 1.0), ("hue_shift", 0.0)):
                value = scalar(parameters.get(name), identity)
                if abs(value - identity) > 1e-4:
                    unhandled.append("aiColorCorrect " + name)

            node_gamma = scalar(parameters.get("gamma"), 1.0)
            if node_gamma and abs(node_gamma - 1.0) > 1e-6:
                if not affine_is_identity():
                    unhandled.append("aiColorCorrect gamma after another "
                                     "correction")
                else:
                    gamma = gamma * node_gamma

            if parameters.get("invert"):
                if abs(gamma - 1.0) > 1e-6 or not affine_is_identity():
                    unhandled.append("aiColorCorrect invert before a gamma")
                else:
                    # out = a*(1-x) + b, which is (-a)*x + (a+b).
                    scale = -scale
                    shift = shift - scale

            for name in ("multiply", "add"):
                if not _is_uniform(parameters.get(name)):
                    unhandled.append(
                        "aiColorCorrect per-channel " + name
                    )
            contrast = scalar(parameters.get("contrast"), 1.0)
            pivot = scalar(parameters.get("contrast_pivot"), 0.18)
            exposure = 2.0 ** scalar(parameters.get("exposure"), 0.0)
            multiply = _first(parameters.get("multiply"), 1.0)
            offset = _first(parameters.get("add"), 0.0)
            step_scale = contrast * exposure * multiply
            step_shift = pivot * (1.0 - contrast) * exposure * multiply + offset
            scale = scale * step_scale
            shift = shift * step_scale + step_shift

        else:
            unhandled.append(kind or "unknown")

    if not parameter:
        # No texture slot to correct; the caller still wants the names.
        return unhandled

    if gamma and abs(gamma - 1.0) > 1e-6:
        # Unreal's Power is in^exponent, so the exponent is the reciprocal.
        _set_scalar(instance, parameter + CORRECTION_GAMMA_SUFFIX,
                    1.0 / float(gamma))
    if abs(scale - 1.0) > 1e-6:
        _set_scalar(instance, parameter + CORRECTION_SCALE_SUFFIX, scale)
    if abs(shift) > 1e-6:
        _set_scalar(instance, parameter + CORRECTION_OFFSET_SUFFIX, shift)
    if remap is not None:
        curve = ramp_lut_texture(parameter, remap, [])
        if curve is None:
            unhandled.append("remapValue curve could not be built")
        elif _set_texture(instance, parameter + CORRECTION_REMAP_SUFFIX,
                          curve):
            _set_scalar(instance,
                        parameter + CORRECTION_REMAP_SWITCH_SUFFIX, 1.0)
    if clamp_low is not None:
        _set_scalar(instance, parameter + CORRECTION_CLAMP_MIN_SUFFIX,
                    clamp_low)
        _set_scalar(instance, parameter + CORRECTION_CLAMP_MAX_SUFFIX,
                    clamp_high if clamp_high is not None else 1.0)
        _set_scalar(instance, parameter + CORRECTION_CLAMP_SWITCH_SUFFIX, 1.0)
    return unhandled


def _report_unsupported(record, name, warnings, surface_class=None,
                        carried_layers=False):
    """Say what did not travel. Silence is the failure mode this repo fears."""
    channels = record.get("channels") or {}
    carried = set()
    if is_coated(surface_class):
        carried.update(("coat", "coat_roughness"))
    present = [
        channel for channel in UNREAL_METADATA_CHANNELS
        if channel not in carried and _channel_is_live(channels, channel)
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
        # A layeredTexture reports itself as an unsupported network because
        # it hands over no single file. It is rebuilt now, so saying it fell
        # back to a flat value would be the opposite of what happened.
        if (texture.get("unsupported_network") and not texture.get("path")
                and not (carried_layers
                         and (texture.get("layered") or {}).get("layers"))):
            warnings.append(
                'Material "{0}" channel "{1}" is driven by a "{2}" network '
                "Maya could not hand over; it fell back to its flat value. "
                "Use Bake Procedurals to carry it.".format(
                    name, channel, texture.get("node_type") or "procedural"
                )
            )
        if texture.get("color_set"):
            warnings.append(
                'Material "{0}" channel "{1}" reads the vertex colour set '
                "\"{2}\". This build does not wire vertex colour into the "
                "master material, so the channel kept its flat "
                "value.".format(name, channel, texture.get("color_set"))
            )

    if record.get("unsupported_corrections"):
        # The chain that *is* rebuilt reports itself per node, in
        # apply_corrections. This one is for what Maya could not hand over at
        # all, which is a different thing and has a different answer.
        warnings.append(
            'Material "{0}" has Maya correction nodes the exporter could not '
            "describe, so the texture arrived uncorrected. Use Bake "
            "Procedurals to carry them.".format(name)
        )
    if record.get("layered_texture") and not carried_layers:
        warnings.append(
            'Material "{0}" reads an unbaked layeredTexture stack, which this '
            "build does not rebuild in Unreal; the base layer's texture was "
            "used. Bake Procedurals resolves the stack into one texture, "
            "which does travel.".format(name)
        )
    if record.get("layers") and not carried_layers:
        # Not the same thing as a layeredTexture, and the advice is not the
        # same either: baking flattens a texture stack, but it cannot merge
        # two shaders into one. A blend shader needs a material graph per
        # material, which this build does not author.
        warnings.append(
            'Material "{0}" is a blend shader with {1} layer(s). Unreal '
            "instances share one master material, and a stack of shaders "
            "needs a graph of its own, so the base layer was used on its own. "
            "Baking does not help here.".format(name, len(record["layers"]))
        )
