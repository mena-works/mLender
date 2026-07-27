# -*- coding: utf-8 -*-
"""Rebuild Maya materials as Blender node trees.

Channel keys arriving in the package JSON are the contract with the Maya
exporter::

    base_color  roughness  metallic  opacity  normal  emission
    emission_strength  transmission  transmission_color
    transmission_roughness  ior  thin_walled  transmission_affects_alpha

There are three build paths: unlit shaders become Emission mixed against a
Transparent BSDF, refractive ones become a Glass BSDF, and everything else
becomes a Principled BSDF.

Every material produced here carries the ``za_generated`` custom property so
the import can tell its own datablocks apart from the placeholder materials
the FBX importer creates.
"""

import bpy

from .constants import (
    DEFAULT_EMISSION_STRENGTH,
    OPENPBR_EMISSION_LUMINANCE_SCALE,
    OPENPBR_EMISSION_SEMANTIC,
    GLASS_INPUTS,
    PRINCIPLED_INPUTS,
    TRANSMISSION_THRESHOLD,
    UNLIT_SHADER_TYPES,
)
from .images import load_image
from .utils import (
    color4,
    namespace_free_name,
    safe_name,
    scalar,
    unique_material_name,
)


def build_material(material_record, warnings):
    """Create a Blender material from one Maya material record."""
    maya_name = (
        material_record.get("material_full_name")
        or material_record.get("material")
        or "Material"
    )
    display_name = (
        material_record.get("material")
        or namespace_free_name(maya_name)
        or "Material"
    )
    material = bpy.data.materials.new(
        unique_material_name("ZA_" + safe_name(display_name))
    )
    material["za_generated"] = True
    material["za_maya_material"] = maya_name
    material["za_shader_type"] = material_record.get("shader_type") or ""
    material.use_nodes = True
    material.node_tree.nodes.clear()

    channels = material_record.get("channels") or {}
    if material_record.get("shader_type") in UNLIT_SHADER_TYPES:
        _build_unlit(material, channels, warnings)
        return material

    if channel_is_active(channels.get("transmission")):
        _build_glass(material, channels, warnings)
        return material

    _build_principled(material, channels, warnings)
    if not material_record.get("supported", True):
        warnings.append(
            'Unsupported Maya shader "{0}" on "{1}"; available channels were '
            "approximated.".format(
                material_record.get("shader_type") or "",
                maya_name,
            )
        )
    return material


def _build_principled(material, channels, warnings):
    nodes = material.node_tree.nodes
    links = material.node_tree.links

    output = nodes.new("ShaderNodeOutputMaterial")
    output.location = (520, 0)
    bsdf = nodes.new("ShaderNodeBsdfPrincipled")
    bsdf.location = (220, 0)
    links.new(bsdf.outputs.get("BSDF"), output.inputs.get("Surface"))

    for channel in (
        "base_color",
        "roughness",
        "metallic",
        "opacity",
        "normal",
        "emission",
        "emission_strength",
    ):
        apply_channel(material, bsdf, channel, channels.get(channel), warnings)

    _default_emission_strength(bsdf, channels)


def _default_emission_strength(bsdf, channels):
    """Make an emission colour visible when the shader sent no strength.

    Blender 3.x defaulted Emission Strength to 1.0, 4.x defaults it to 0.0.
    Without this the same package renders emissive on 3.6 and black on 4.x.
    """
    if not channels.get("emission") or channels.get("emission_strength"):
        return
    socket = principled_input(bsdf, "emission_strength")
    if socket is not None:
        socket.default_value = DEFAULT_EMISSION_STRENGTH


def channel_is_active(record):
    """Whether a weight channel is switched on in the source material.

    A textured weight counts as on regardless of its flat value, because the
    texture is what actually drives it.
    """
    if not record:
        return False
    if (record.get("texture") or {}).get("path"):
        return True
    return scalar(record.get("value"), 0.0) > TRANSMISSION_THRESHOLD


def _build_glass(material, channels, warnings):
    """Rebuild a refractive material as a Glass BSDF.

    Principled can do transmission, but a dedicated Glass BSDF matches what
    Redshift and Arnold refraction actually look like far more closely, and
    keeps the roughness and IOR meaning the same thing on both sides.
    """
    nodes = material.node_tree.nodes
    links = material.node_tree.links

    output = nodes.new("ShaderNodeOutputMaterial")
    output.location = (560, 0)
    glass = nodes.new("ShaderNodeBsdfGlass")
    glass.name = "ZA_Glass"
    glass.label = "Glass"
    glass.location = (80, 40)

    # OpenPBR has no transmission roughness of its own, and neither do some
    # Redshift versions, so the surface roughness stands in.
    colour_record = channels.get("transmission_color") or channels.get("base_color")
    roughness_record = (
        channels.get("transmission_roughness") or channels.get("roughness")
    )
    for channel, record in (
        ("transmission_color", colour_record),
        ("transmission_roughness", roughness_record),
        ("ior", channels.get("ior")),
        ("normal", channels.get("normal")),
    ):
        apply_record_to_socket(
            material,
            glass,
            _socket_for(glass, GLASS_INPUTS, channel),
            channel,
            record,
            warnings,
        )

    opacity_record = channels.get("opacity") or {}
    if _opacity_requires_mix(opacity_record):
        # Cutout opacity is a different thing from refraction, so it stays a
        # mix against a Transparent BSDF rather than tinting the glass.
        transparent = nodes.new("ShaderNodeBsdfTransparent")
        transparent.location = (80, -170)
        mix = nodes.new("ShaderNodeMixShader")
        mix.name = "ZA_Glass_Opacity"
        mix.label = "Glass Cutout Opacity"
        mix.location = (330, 0)
        links.new(transparent.outputs.get("BSDF"), mix.inputs[1])
        links.new(glass.outputs.get("BSDF"), mix.inputs[2])
        links.new(mix.outputs.get("Shader"), output.inputs.get("Surface"))
        apply_record_to_socket(
            material,
            mix,
            mix.inputs[0],
            "opacity",
            opacity_record,
            warnings,
        )
    else:
        links.new(glass.outputs.get("BSDF"), output.inputs.get("Surface"))

    material["za_material_mode"] = "GLASS_BSDF"
    material["za_transmission_weight"] = scalar(
        (channels.get("transmission") or {}).get("value"),
        1.0,
    )
    material["za_thin_walled"] = bool(
        scalar((channels.get("thin_walled") or {}).get("value"), 0.0)
    )
    material["za_transmission_affects_alpha"] = bool(
        scalar(
            (channels.get("transmission_affects_alpha") or {}).get("value"),
            1.0,
        )
    )
    _enable_transmission(material)


def _opacity_requires_mix(record):
    if not record:
        return False
    if (record.get("texture") or {}).get("path"):
        return True
    return scalar(record.get("value"), 1.0) < 1.0 - TRANSMISSION_THRESHOLD


def _enable_transmission(material):
    """Turn on whatever refraction support the running Blender offers."""
    for attr, value in (
        ("use_screen_refraction", True),
        ("use_raytrace_refraction", True),
        ("use_backface_culling", False),
        ("use_transparent_shadow", True),
    ):
        if hasattr(material, attr):
            try:
                setattr(material, attr, value)
            except Exception:
                pass


def _build_unlit(material, channels, warnings):
    """Unlit shaders (Maya surfaceShader, Arnold aiFlat) are emissive.

    Emission mixed against a Transparent BSDF reproduces their behaviour far
    more closely than pushing the colour into a Principled base colour would.
    """
    nodes = material.node_tree.nodes
    links = material.node_tree.links

    output = nodes.new("ShaderNodeOutputMaterial")
    output.location = (520, 0)
    emission = nodes.new("ShaderNodeEmission")
    emission.location = (20, 80)
    transparent = nodes.new("ShaderNodeBsdfTransparent")
    transparent.location = (20, -130)
    mix = nodes.new("ShaderNodeMixShader")
    mix.location = (280, 0)
    links.new(transparent.outputs["BSDF"], mix.inputs[1])
    links.new(emission.outputs["Emission"], mix.inputs[2])
    links.new(mix.outputs["Shader"], output.inputs["Surface"])

    emission_record = channels.get("emission") or {}
    emission_texture = emission_record.get("texture") or {}
    if emission_texture.get("path"):
        image = load_image(emission_texture, "emission", warnings)
        if image:
            image_node = nodes.new("ShaderNodeTexImage")
            image_node.name = "ZA_Unlit_Color"
            image_node.image = image
            links.new(image_node.outputs["Color"], emission.inputs["Color"])
    elif "value" in emission_record:
        emission.inputs["Color"].default_value = color4(
            emission_record.get("value")
        )

    strength_record = channels.get("emission_strength") or {}
    emission.inputs["Strength"].default_value = max(
        0.0,
        scalar(strength_record.get("value"), 1.0),
    )

    opacity_record = channels.get("opacity") or {}
    opacity_texture = opacity_record.get("texture") or {}
    if opacity_texture.get("path"):
        image = load_image(opacity_texture, "opacity", warnings)
        if image:
            image_node = nodes.new("ShaderNodeTexImage")
            image_node.name = "ZA_Unlit_Opacity"
            image_node.image = image
            rgb_to_bw = nodes.new("ShaderNodeRGBToBW")
            links.new(image_node.outputs["Color"], rgb_to_bw.inputs["Color"])
            opacity_output = rgb_to_bw.outputs["Val"]
            if opacity_record.get("invert"):
                opacity_output = _insert_value_invert(nodes, links, opacity_output)
            links.new(opacity_output, mix.inputs[0])
    else:
        mix.inputs[0].default_value = max(
            0.0,
            min(1.0, scalar(opacity_record.get("value"), 1.0)),
        )
    enable_alpha(material)


def apply_channel(material, bsdf, channel, record, warnings):
    """Wire one channel into the Principled BSDF, texture first then value."""
    apply_record_to_socket(
        material,
        bsdf,
        principled_input(bsdf, channel),
        channel,
        record,
        warnings,
    )


def apply_record_to_socket(material, shader, target, channel, record, warnings):
    """Wire a channel record into any socket, texture first then flat value.

    Kept separate from the Principled mapping so the glass path can drive a
    Glass BSDF's sockets through exactly the same texture and invert handling.
    """
    if not record or target is None:
        return

    texture = record.get("texture") or {}
    if texture.get("path"):
        image = load_image(texture, channel, warnings)
        if image:
            connect_image_channel(
                material,
                shader,
                target,
                channel,
                image,
                bool(record.get("invert")),
            )
            return

    if "value" not in record:
        return
    value = record.get("value")
    if channel in ("base_color", "emission", "transmission_color"):
        target.default_value = color4(value)
    elif channel == "opacity":
        target.default_value = scalar(value, 1.0)
        enable_alpha(material)
    elif channel == "normal":
        # A normal socket has no meaningful flat value.
        return
    elif record.get("source_semantic") == OPENPBR_EMISSION_SEMANTIC:
        # A luminance in nits, not a socket-ready weight.
        target.default_value = max(
            0.0,
            scalar(value, 0.0) / OPENPBR_EMISSION_LUMINANCE_SCALE,
        )
    else:
        target.default_value = scalar(value, target.default_value)


def connect_image_channel(material, bsdf, target, channel, image, invert):
    nodes = material.node_tree.nodes
    links = material.node_tree.links
    image_node = nodes.new("ShaderNodeTexImage")
    image_node.name = "ZA_{0}_Texture".format(channel)
    image_node.label = channel.replace("_", " ").title()
    image_node.image = image

    if channel == "normal":
        normal_map = nodes.new("ShaderNodeNormalMap")
        links.new(image_node.outputs.get("Color"), normal_map.inputs.get("Color"))
        links.new(normal_map.outputs.get("Normal"), target)
        return

    if channel == "opacity":
        rgb_to_bw = nodes.new("ShaderNodeRGBToBW")
        links.new(image_node.outputs.get("Color"), rgb_to_bw.inputs.get("Color"))
        output = rgb_to_bw.outputs.get("Val")
        if invert:
            output = _insert_value_invert(nodes, links, output)
        links.new(output, target)
        enable_alpha(material)
        return

    output = image_node.outputs.get("Color")
    if invert:
        invert_node = nodes.new("ShaderNodeInvert")
        links.new(output, invert_node.inputs.get("Color"))
        output = invert_node.outputs.get("Color")
    links.new(output, target)


def _insert_value_invert(nodes, links, output):
    """1 - value, for scalar sockets where a colour Invert node won't do."""
    invert_node = nodes.new("ShaderNodeMath")
    invert_node.operation = "SUBTRACT"
    invert_node.inputs[0].default_value = 1.0
    links.new(output, invert_node.inputs[1])
    return invert_node.outputs[0]


def principled_input(bsdf, channel):
    """Resolve a channel to a Principled socket across Blender versions."""
    return _socket_for(bsdf, PRINCIPLED_INPUTS, channel)


def _socket_for(shader, mapping, channel):
    """First socket on a shader that a channel's candidate names resolve to."""
    for name in mapping.get(channel, ()):
        socket = shader.inputs.get(name)
        if socket is not None:
            return socket
    return None


def enable_alpha(material):
    """Switch a material to alpha blending across Blender/EEVEE versions."""
    for attr, value in (
        ("blend_method", "BLEND"),
        ("surface_render_method", "DITHERED"),
        ("shadow_method", "HASHED"),
    ):
        if hasattr(material, attr):
            try:
                setattr(material, attr, value)
            except Exception:
                pass


def apply_face_assignments(obj, material_records):
    """Rebuild per-face material indices from Maya shadingEngine membership."""
    if not material_records:
        return
    if not any(record.get("face_assignment") for record in material_records):
        return
    polygon_count = len(obj.data.polygons)
    for slot_index, record in enumerate(material_records):
        assignment = record.get("face_assignment") or {}
        if assignment.get("all_faces"):
            for polygon in obj.data.polygons:
                polygon.material_index = slot_index
        for index in face_indices(assignment.get("face_components") or []):
            if 0 <= index < polygon_count:
                obj.data.polygons[index].material_index = slot_index


def face_indices(components):
    """Expand Maya component expressions ("0:35", "7") into face indices."""
    result = []
    seen = set()
    for component in components:
        for part in str(component).split(","):
            part = part.strip()
            if not part:
                continue
            if ":" in part:
                values = part.split(":")
                try:
                    start = int(values[0])
                    stop = int(values[1])
                    step = int(values[2]) if len(values) > 2 else 1
                except Exception:
                    continue
                indices = range(start, stop + 1, max(1, step))
            else:
                try:
                    indices = (int(part),)
                except Exception:
                    continue
            for index in indices:
                if index not in seen:
                    seen.add(index)
                    result.append(index)
    return result
