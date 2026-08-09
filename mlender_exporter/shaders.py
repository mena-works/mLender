# -*- coding: utf-8 -*-
"""Maya shader to Principled BSDF channel extraction.

The channel keys produced here are the contract with the Blender importer:

    base_color  roughness  metallic  opacity  normal  emission
    emission_strength  transmission  transmission_color
    transmission_roughness  ior  thin_walled  transmission_affects_alpha

The first seven drive a Principled BSDF. The transmission group drives a Glass
BSDF instead, which the importer switches to when transmission is non-zero.

Each channel record may carry ``value``, ``texture``, ``invert`` and the
``maya_attr``/``maya_plug`` the data actually came from. Adding a channel means
updating the importer's socket mapping in the same change.
"""
from __future__ import absolute_import

import maya.cmds as cmds

from .constants import (
    ARNOLD_LAMBERT_CHANNELS,
    ARNOLD_SHEEN_ROUGHNESS_SEMANTIC,
    ARNOLD_OPENPBR_CHANNELS,
    ARNOLD_STANDARD_CHANNELS,
    BLINN_ROUGHNESS,
    DEFAULT_IOR,
    FALLBACK_ROUGHNESS,
    LAMBERT_ROUGHNESS,
    LAYER_SHADER_SLOTS,
    LAYER_SHADER_TYPE,
    MAX_BLEND_DEPTH,
    MAYA_LAYERED_COMPOSITING_ATTR,
    MAYA_LAYERED_COMPOSITING_MODES,
    MAYA_LAYERED_SHADER_ENTRIES,
    MAYA_LAYERED_SHADER_TYPE,
    MIX_SHADER_INPUTS,
    MIX_SHADER_TYPE,
    MIX_SHADER_WEIGHT,
    NATIVE_ROUGHNESS_ATTRS,
    PHONG_EXPONENT_ATTRS,
    RAMP_CHANNEL_ATTRS,
    RAMP_INPUT_ATTR,
    RAMP_INPUT_MODES,
    RAMP_INTERP_MODES,
    RAMP_SHADER_TYPE,
    OPENPBR_EMISSION_SEMANTIC,
    OPENPBR_SPECULAR_SEMANTIC,
    REDSHIFT_GLOSSINESS_FLAGS,
    REDSHIFT_LEGACY_CHANNELS,
    REDSHIFT_STANDARD_CHANNELS,
    SUPPORTED_SHADER_TYPES,
)
from .bake import bake_channel
from .mayautils import attr_exists, invert_color, plug_value
from .textures import texture_from_plug


def shader_channels(shader, shader_type, bake_context=None):
    if shader_type == "RedshiftStandardMaterial":
        return redshift_channels(
            shader, REDSHIFT_STANDARD_CHANNELS, bake_context
        )
    if shader_type == "RedshiftMaterial":
        return redshift_channels(
            shader, REDSHIFT_LEGACY_CHANNELS, bake_context
        )
    if shader_type == "aiStandardSurface":
        return arnold_channels(
            shader, ARNOLD_STANDARD_CHANNELS, bake_context=bake_context
        )
    if shader_type == "aiOpenPBRSurface":
        return arnold_channels(
            shader,
            ARNOLD_OPENPBR_CHANNELS,
            openpbr=True,
            bake_context=bake_context,
        )
    if shader_type == "aiLambert":
        return arnold_channels(
            shader,
            ARNOLD_LAMBERT_CHANNELS,
            roughness=LAMBERT_ROUGHNESS,
            bake_context=bake_context,
        )
    if shader_type == "aiFlat":
        return arnold_flat_channels(shader, bake_context)
    if shader_type == RAMP_SHADER_TYPE:
        return ramp_shader_channels(shader, bake_context)
    if shader_type in NATIVE_ROUGHNESS_ATTRS:
        # blinn, phong, phongE and rampShader each carry their own gloss
        # control under a different name; the fallback only applies when the
        # attribute is missing or unreadable.
        return maya_basic_channels(
            shader,
            native_roughness(
                shader,
                shader_type,
                BLINN_ROUGHNESS if shader_type == "blinn"
                else FALLBACK_ROUGHNESS,
            ),
            bake_context,
        )
    if shader_type == "lambert":
        return maya_basic_channels(shader, LAMBERT_ROUGHNESS, bake_context)
    if shader_type == "surfaceShader":
        return surface_shader_channels(shader, bake_context)
    if is_blend_shader(shader_type):
        # A blend shader describes no surface of its own; its channels live
        # on the shaders it stacks. Reading it as a native surface used to
        # reach for ".color", which a layeredShader answers to only through
        # an index, and the whole export died on the exception.
        return {}
    return maya_basic_channels(shader, FALLBACK_ROUGHNESS, bake_context)


def arnold_channels(shader, channel_map, roughness=None, openpbr=False,
                    bake_context=None):
    """Channels for Arnold surfaces.

    Arnold's opacity is genuine opacity, so unlike the Maya shader paths it is
    passed through untouched; routing it through the transparency inversion
    would flip every Arnold material.

    The base and specular weight attributes (``base``, ``baseWeight``,
    ``specularWeight``) are not applied. Principled has no matching input and
    folding them into base colour would misreport the exported value.
    """
    result = {}
    for channel, attrs in channel_map.items():
        record = first_channel_record(shader, attrs, bake_context, channel)
        if record:
            result[channel] = record

    if openpbr and result.get("emission_strength"):
        # Not a 0..1 weight; the importer scales it.
        result["emission_strength"]["source_semantic"] = OPENPBR_EMISSION_SEMANTIC

    if not openpbr and result.get("sheen_roughness"):
        # Standard surface's sheen lobe is not OpenPBR's fuzz, and Blender
        # follows the latter, so this roughness needs remapping and OpenPBR's
        # does not.
        result["sheen_roughness"]["source_semantic"] = (
            ARNOLD_SHEEN_ROUGHNESS_SEMANTIC
        )

    if openpbr and result.get("specular"):
        # OpenPBR's metal lobe is scaled by this weight and standard surface's
        # is not, so the difference has to travel with the record.
        result["specular"]["source_semantic"] = OPENPBR_SPECULAR_SEMANTIC

    if roughness is not None:
        result["roughness"] = {"value": float(roughness)}
    _apply_surface_defaults(result)
    return result


def redshift_channels(shader, channel_map, bake_context=None):
    result = {}
    for channel, attrs in channel_map.items():
        record = first_channel_record(shader, attrs, bake_context, channel)
        if record:
            result[channel] = record
    apply_glossiness_conversion(shader, result.get("roughness"))
    _apply_surface_defaults(result)
    return result


def _apply_surface_defaults(result):
    """Fill in the channels a Principled or Glass rebuild always needs.

    Transmission defaults to zero so an absent refraction attribute never
    trips the glass path, and IOR to the usual 1.5 for dielectrics.
    """
    result.setdefault("roughness", {"value": FALLBACK_ROUGHNESS})
    result.setdefault("metallic", {"value": 0.0})
    result.setdefault("opacity", {"value": [1.0, 1.0, 1.0, 1.0]})
    result.setdefault("transmission", {"value": 0.0})
    result.setdefault("ior", {"value": DEFAULT_IOR})
    return result


def apply_glossiness_conversion(shader, roughness_record):
    """Flip the roughness record when Redshift treats the input as glossiness.

    A flat value can be inverted here; a texture cannot, so the record is
    tagged and the importer inserts an invert node instead.

    The split is on ``texture.path``, not on the texture record existing. A
    procedural that could not be baked leaves a record behind with no file in
    it; the importer falls through to the flat value, and the flat value is
    the only place an inversion can still happen. Tagging that case and
    leaving the number alone shipped glossiness as roughness.
    """
    if not roughness_record:
        return
    convert_gloss = False
    for attr in REDSHIFT_GLOSSINESS_FLAGS:
        if not attr_exists(shader, attr):
            continue
        try:
            convert_gloss = bool(cmds.getAttr(shader + "." + attr))
        except Exception:
            convert_gloss = False
        roughness_record["glossiness_flag_attr"] = attr
        break
    if not convert_gloss:
        return
    roughness_record["source_semantic"] = "glossiness"
    if (roughness_record.get("texture") or {}).get("path"):
        roughness_record["invert"] = True
    elif "value" in roughness_record:
        roughness_record["value"] = 1.0 - float(roughness_record["value"])


def ramp_entries(shader, attr):
    """One ramp's stops, sorted by position.

    Maya hands the indices back in whatever order they were created in, so a
    ramp an artist edited comes out shuffled; sorting is not tidiness, it is
    what makes the gradient the one they drew.
    """
    try:
        indices = cmds.getAttr(
            "{0}.{1}".format(shader, attr), multiIndices=True
        ) or []
    except Exception:
        return []

    entries = []
    for index in indices:
        base = "{0}.{1}[{2}].{1}_".format(shader, attr, index)
        try:
            position = float(cmds.getAttr(base + "Position"))
        except Exception:
            continue
        colour = None
        try:
            raw = cmds.getAttr(base + "Color")
            # A colour ramp reads back as [(r, g, b)]; a float ramp has no
            # Color child at all and raises, which is what selects the branch.
            values = list(raw[0]) if isinstance(raw, list) else list(raw)
            colour = [float(item) for item in values[:3]]
        except Exception:
            try:
                value = float(cmds.getAttr(base + "FloatValue"))
                colour = [value, value, value]
            except Exception:
                continue
        interp = "Linear"
        try:
            index_value = int(cmds.getAttr(base + "Interp"))
            if 0 <= index_value < len(RAMP_INTERP_MODES):
                interp = RAMP_INTERP_MODES[index_value]
        except Exception:
            pass
        entries.append({
            "position": position,
            "color": colour,
            "interp": interp,
        })
    entries.sort(key=lambda item: item["position"])
    return entries


def ramp_input_mode(shader):
    """What every ramp on this shader is a function of.

    One enum for the whole shader: there is no per ramp input attribute, and
    its default is Light Angle rather than Facing Angle.
    """
    if not attr_exists(shader, RAMP_INPUT_ATTR):
        return RAMP_INPUT_MODES[0]
    try:
        index = int(cmds.getAttr(shader + "." + RAMP_INPUT_ATTR))
    except Exception:
        return RAMP_INPUT_MODES[0]
    if 0 <= index < len(RAMP_INPUT_MODES):
        return RAMP_INPUT_MODES[index]
    return RAMP_INPUT_MODES[0]


def ramp_shader_channels(shader, bake_context=None):
    """Channels for a rampShader, gradients included.

    The flat channels come from the ordinary reader so bump, roughness and
    anything else keep working; the ramps are then attached to the three
    channels that have a Principled socket shaped to take one.
    """
    result = maya_basic_channels(
        shader, native_roughness(shader, RAMP_SHADER_TYPE, FALLBACK_ROUGHNESS),
        bake_context,
    )
    mode = ramp_input_mode(shader)
    for channel, attr, invert in RAMP_CHANNEL_ATTRS:
        entries = ramp_entries(shader, attr)
        if not entries:
            continue
        if invert:
            entries = [
                {
                    "position": item["position"],
                    "color": [1.0 - value for value in item["color"]],
                    "interp": item["interp"],
                }
                for item in entries
            ]
        record = result.setdefault(channel, {})
        record["maya_attr"] = attr
        record["maya_plug"] = "{0}.{1}".format(shader, attr)
        record["ramp"] = {"input": mode, "entries": entries}
        if invert:
            # Inverted here, exactly as a flat transparency is, so the
            # importer must not invert it a second time.
            record["invert"] = False
            record["semantic"] = "maya_transparency_to_opacity"
        # The stop nearest the facing end, so a build that cannot use the
        # gradient still shows the colour the surface has head on.
        record["value"] = list(entries[-1]["color"])
    if result.get("emission") and "emission_strength" not in result:
        result["emission_strength"] = {"value": 1.0}
    return result


def upstream_shader(shader, attr):
    """The shader feeding an input, or None.

    Arnold wires these as ``outColor`` into a float3 input, so the connection
    looks like any other colour link; what makes it a shader is the node on
    the other end, which is why the type comes back with it.
    """
    try:
        sources = cmds.listConnections(
            shader + "." + attr, source=True, destination=False,
            shapes=False, skipConversionNodes=True
        ) or []
    except Exception:
        return None
    for node in sources:
        try:
            kind = cmds.nodeType(node)
        except Exception:
            continue
        if kind in SUPPORTED_SHADER_TYPES or kind in NATIVE_ROUGHNESS_ATTRS:
            return node, kind
    return None


def is_blend_shader(shader_type):
    return shader_type in (
        MIX_SHADER_TYPE, LAYER_SHADER_TYPE, MAYA_LAYERED_SHADER_TYPE
    )


def maya_layered_compositing(shader):
    """Which of layeredShader's two compositing modes is set."""
    try:
        index = int(cmds.getAttr(shader + "." + MAYA_LAYERED_COMPOSITING_ATTR))
    except Exception:
        return MAYA_LAYERED_COMPOSITING_MODES[0]
    if 0 <= index < len(MAYA_LAYERED_COMPOSITING_MODES):
        return MAYA_LAYERED_COMPOSITING_MODES[index]
    return MAYA_LAYERED_COMPOSITING_MODES[0]


def maya_layered_layers(shader, bake_context=None, depth=0):
    """Maya's own layeredShader, bottom layer first.

    Index 0 is the top, the same way round as layeredTexture and the reverse
    of what this returns, so the list is flipped to match the contract the
    Arnold blend shaders already keep.

    The weight travels as Maya's ``transparency`` rather than as a mix, and
    the compositing mode travels with it: the two modes use that number
    differently and only the importer can act on the difference.
    """
    mode = maya_layered_compositing(shader)
    try:
        indices = cmds.getAttr(
            shader + "." + MAYA_LAYERED_SHADER_ENTRIES, multiIndices=True
        ) or []
    except Exception:
        return []

    layers = []
    for index in indices:
        element = "{0}.{1}[{2}]".format(
            shader, MAYA_LAYERED_SHADER_ENTRIES, index
        )
        found = upstream_shader(
            shader, "{0}[{1}].color".format(MAYA_LAYERED_SHADER_ENTRIES, index)
        )
        if not found:
            continue
        node, kind = found
        layers.append({
            "shader": node,
            "shader_type": kind,
            "channels": shader_channels(node, kind, bake_context),
            "layers": blend_layers(node, kind, bake_context, depth + 1),
            "compositing": mode,
            "transparency": channel_record_for_plug(
                shader, element + ".transparency", bake_context,
                "transparency",
            ) or {"value": 0.0},
        })
    layers.reverse()
    return layers


def blend_layers(shader, shader_type, bake_context=None, depth=0):
    """The shaders a mix or layer shader blends, bottom layer first.

    The first entry is the base. Every entry after it carries a ``mix``
    record holding that layer's weight over everything below, which is the
    measured meaning of Arnold's number and the same direction as Blender's
    Mix Shader factor.

    A layer that is itself a blend shader carries its own ``layers``, so a
    nested lookdev survives instead of collapsing to whichever leaf was
    found first.
    """
    if depth >= MAX_BLEND_DEPTH or not is_blend_shader(shader_type):
        return []
    if shader_type == MAYA_LAYERED_SHADER_TYPE:
        # Indexed compounds rather than numbered attributes, and a weight
        # that means the opposite of Arnold's, so it reads its own slots.
        return maya_layered_layers(shader, bake_context, depth)
    if shader_type == MIX_SHADER_TYPE:
        slots = [
            (MIX_SHADER_INPUTS[0], None, None),
            (MIX_SHADER_INPUTS[1], MIX_SHADER_WEIGHT, None),
        ]
    else:
        slots = [
            (
                "input{0}".format(index),
                None if index == 1 else "mix{0}".format(index),
                "enable{0}".format(index),
            )
            for index in range(1, LAYER_SHADER_SLOTS + 1)
        ]

    layers = []
    for input_attr, weight_attr, enable_attr in slots:
        if enable_attr and attr_exists(shader, enable_attr):
            try:
                if not bool(cmds.getAttr(shader + "." + enable_attr)):
                    continue
            except Exception:
                pass
        found = upstream_shader(shader, input_attr)
        if not found:
            continue
        node, kind = found
        layer = {
            "shader": node,
            "shader_type": kind,
            "channels": shader_channels(node, kind, bake_context),
            "layers": blend_layers(node, kind, bake_context, depth + 1),
        }
        if weight_attr:
            # A textured mix is common, so this goes through the same reader
            # as any other channel rather than reading a bare number.
            layer["mix"] = first_channel_record(
                shader, (weight_attr,), bake_context, "mix"
            ) or {"value": 1.0}
        layers.append(layer)
    # One layer is not a blend; the caller builds it directly and skips the
    # Mix Shader that would otherwise sit there doing nothing.
    return layers


def native_roughness(shader, shader_type, default):
    """Roughness from a native Maya shader's own gloss control.

    Maya's pre-PBR shaders each spell it differently and two of them do not
    share a single attribute, so this is a table lookup rather than an alias
    tuple. A shader with no control, or one whose control is textured, falls
    back to the approximation for its type.
    """
    attrs = NATIVE_ROUGHNESS_ATTRS.get(shader_type) or ()
    for attr in attrs:
        if not attr_exists(shader, attr):
            continue
        try:
            value = float(cmds.getAttr(shader + "." + attr))
        except Exception:
            continue
        if attr in PHONG_EXPONENT_ATTRS:
            return phong_exponent_to_roughness(value)
        return max(0.0, min(1.0, value))
    return default


def phong_exponent_to_roughness(exponent):
    """Phong exponent to microfacet roughness, r = sqrt(2 / (n + 2)).

    Analytic rather than measured: a Phong lobe and a GGX lobe are different
    shapes, so no single number makes them equal. This is the standard
    conversion and it at least tracks the artist's intent, which pinning
    every phong to one value did not.
    """
    try:
        exponent = max(0.0, float(exponent))
    except Exception:
        return FALLBACK_ROUGHNESS
    return max(0.0, min(1.0, (2.0 / (exponent + 2.0)) ** 0.5))


def maya_basic_channels(shader, roughness, bake_context=None):
    """Channels for lambert, blinn and any unrecognised surface shader."""
    result = {
        "roughness": {"value": float(roughness)},
        "metallic": {"value": 0.0},
    }
    base_color = first_channel_record(
        shader, ("color",), bake_context, "base_color"
    )
    if base_color:
        result["base_color"] = base_color

    result["opacity"] = _transparency_as_opacity(
        shader, ("transparency",), bake_context
    )

    normal = first_channel_record(
        shader, ("normalCamera",), bake_context, "normal"
    )
    if normal and normal.get("texture"):
        result["normal"] = normal
    emission = first_channel_record(
        shader, ("incandescence",), bake_context, "emission"
    )
    if emission:
        result["emission"] = emission
        result["emission_strength"] = {"value": 1.0}
    return result


def arnold_flat_channels(shader, bake_context=None):
    """Channels for aiFlat, which is unlit and therefore treated as emissive.

    Read "color", never "outColor". On a Maya surfaceShader outColor is a real
    input attribute, but on an Arnold shader it is a computed output that
    reads back as a meaningless constant outside a render.

    Verified against MtoA 5.4.8: aiFlat exposes only color and normalCamera,
    with no opacity or transparency attribute.
    """
    emission = first_channel_record(
        shader, ("color",), bake_context, "emission"
    )
    return {
        "emission": emission or {"value": [0.0, 0.0, 0.0]},
        "emission_strength": {"value": 1.0},
        "opacity": {"value": [1.0, 1.0, 1.0, 1.0]},
    }


def surface_shader_channels(shader, bake_context=None):
    """Surface shaders are emissive, so outColor drives emission not base."""
    result = {
        "emission_strength": {"value": 1.0},
    }
    emission = first_channel_record(
        shader, ("outColor", "color"), bake_context, "emission"
    )
    if emission:
        result["emission"] = emission
    else:
        result["emission"] = {"value": [0.0, 0.0, 0.0]}

    result["opacity"] = _transparency_as_opacity(
        shader,
        ("outTransparency", "transparency"),
        bake_context,
    )
    return result


def _transparency_as_opacity(shader, attrs, bake_context=None):
    """Convert a Maya transparency plug into an opacity channel record.

    A flat colour is inverted here and ``invert`` cleared, so the importer
    never inverts an already inverted value. A texture cannot be inverted
    here, so the flag travels instead and the importer builds the node.

    The texture case has to be checked first. first_channel_record fills in
    ``value`` whether or not a texture drives the plug, so testing for a value
    alone treated every textured transparency as flat: the flag was cleared,
    nothing inverted the map, and the mesh came through inside out, opaque
    where it should have been clear.
    """
    record = first_channel_record(shader, attrs, bake_context, "opacity")
    if not record:
        return {"value": [1.0, 1.0, 1.0, 1.0]}
    record["invert"] = True
    record["semantic"] = "maya_transparency_to_opacity"
    if (record.get("texture") or {}).get("path"):
        return record
    if "value" in record:
        record["value"] = invert_color(record["value"])
        record["invert"] = False
    return record


def first_channel_record(shader, attrs, bake_context=None, channel=None):
    """Build a channel record from the first attribute that exists."""
    for attr in attrs:
        if not attr_exists(shader, attr):
            continue
        return channel_record_for_plug(
            shader, shader + "." + attr, bake_context, channel, attr
        )


def channel_record_for_plug(shader, plug, bake_context=None, channel=None,
                            attr=None):
    """The same record from a plug that no attribute table can name.

    An indexed compound -- ``layeredShader.inputs[2].transparency`` -- is a
    real channel and a perfectly ordinary one, but ``attributeQuery`` cannot
    be asked about it, so the attribute driven path above cannot reach it.
    """
    if not plug:
        return None
    record = {"maya_plug": plug}
    if attr:
        record["maya_attr"] = attr
    texture = texture_from_plug(plug)
    if texture and not texture.get("path"):
        # A connection with no file behind it: a checker, a ramp,
        # layered noise. There is nothing to reference, so bake the
        # network down to the mesh's UVs instead.
        #
        # A plain U or V ramp could be rebuilt natively, but Bake
        # Procedurals is the user's choice and baking it does something
        # the native path cannot: it applies the place2dTexture. So the
        # option wins here, and the gradient only travels as stops when
        # the user left baking off.
        baked = bake_channel(
            bake_context,
            shader,
            channel or attr,
            texture.get("source_plug") or "",
        )
        if baked:
            texture = baked
    if texture:
        record["texture"] = texture
    value = plug_value(plug)
    if value is not None:
        record["value"] = value
    return record
