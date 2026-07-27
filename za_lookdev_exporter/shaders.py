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
    ARNOLD_OPENPBR_CHANNELS,
    ARNOLD_STANDARD_CHANNELS,
    BLINN_ROUGHNESS,
    DEFAULT_IOR,
    FALLBACK_ROUGHNESS,
    LAMBERT_ROUGHNESS,
    OPENPBR_EMISSION_SEMANTIC,
    REDSHIFT_GLOSSINESS_FLAGS,
    REDSHIFT_LEGACY_CHANNELS,
    REDSHIFT_STANDARD_CHANNELS,
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
    if shader_type == "blinn":
        return maya_basic_channels(shader, BLINN_ROUGHNESS, bake_context)
    if shader_type == "lambert":
        return maya_basic_channels(shader, LAMBERT_ROUGHNESS, bake_context)
    if shader_type == "surfaceShader":
        return surface_shader_channels(shader, bake_context)
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
    if roughness_record.get("texture"):
        roughness_record["invert"] = True
    elif "value" in roughness_record:
        roughness_record["value"] = 1.0 - float(roughness_record["value"])


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

    A flat colour is inverted immediately and ``invert`` cleared, so the
    importer never inverts an already inverted value.
    """
    record = first_channel_record(shader, attrs, bake_context, "opacity")
    if not record:
        return {"value": [1.0, 1.0, 1.0, 1.0]}
    record["invert"] = True
    record["semantic"] = "maya_transparency_to_opacity"
    if "value" in record:
        record["value"] = invert_color(record["value"])
        record["invert"] = False
    return record


def first_channel_record(shader, attrs, bake_context=None, channel=None):
    """Build a channel record from the first attribute that exists."""
    for attr in attrs:
        if not attr_exists(shader, attr):
            continue
        plug = shader + "." + attr
        record = {
            "maya_attr": attr,
            "maya_plug": plug,
        }
        texture = texture_from_plug(plug)
        if texture and not texture.get("path"):
            # A connection with no file behind it: a checker, a ramp,
            # layered noise. There is nothing to reference, so bake the
            # network down to the mesh's UVs instead.
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
    return None
