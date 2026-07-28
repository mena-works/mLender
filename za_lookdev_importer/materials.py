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

import math

import bpy

from .constants import (
    COLOUR_VALUED_CHANNELS,
    UNCLAMPED_COLOUR_CHANNELS,
    DISPLACEMENT_SPACES,
    DEFAULT_EMISSION_STRENGTH,
    OPENPBR_EMISSION_LUMINANCE_SCALE,
    OPENPBR_EMISSION_SEMANTIC,
    GLASS_INPUTS,
    PRINCIPLED_INPUTS,
    SPECULAR_WEIGHT_TO_LEVEL,
    TEXTURE_EXTENSION_CLAMP,
    TEXTURE_EXTENSION_MIRROR,
    TEXTURE_EXTENSION_REPEAT,
    TRANSMISSION_THRESHOLD,
    UNLIT_SHADER_TYPES,
)
from .corrections import apply_corrections
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
        apply_displacement(material, material_record, warnings)
        return material

    if channel_is_active(channels.get("transmission")):
        _build_glass(material, channels, warnings)
        apply_displacement(material, material_record, warnings)
        return material

    _build_principled(material, channels, warnings)
    apply_displacement(material, material_record, warnings)
    if not material_record.get("supported", True):
        warnings.append(
            'Unsupported Maya shader "{0}" on "{1}"; available channels were '
            "approximated.".format(
                material_record.get("shader_type") or "",
                maya_name,
            )
        )
    return material


def apply_displacement(material, material_record, warnings):
    """Rebuild Maya displacement as a Displacement node on the material output.

    Maya's height and zero value map straight onto Blender's Scale and
    Midlevel, because both compute (map - midlevel) * scale.

    The node is left in OBJECT space deliberately, and the scene unit scale is
    deliberately *not* folded in. Measured on the imported FBX: the unit
    conversion lands on the object's scale while the vertex coordinates stay in
    Maya units, so an object space displacement of one is already one Maya
    unit. This is the opposite of the light energy rule, where the unit scale
    must be applied; adding it here would displace by a factor of a hundred.
    """
    displacement = material_record.get("displacement") or {}
    if not displacement.get("enabled"):
        return False

    nodes = material.node_tree.nodes
    links = material.node_tree.links
    output = next(
        (n for n in nodes if n.bl_idname == "ShaderNodeOutputMaterial"), None
    )
    if output is None:
        return False
    target = output.inputs.get("Displacement")
    if target is None:
        return False

    is_vector = bool(displacement.get("vector"))
    node = nodes.new(
        "ShaderNodeVectorDisplacement" if is_vector else "ShaderNodeDisplacement"
    )
    node.name = "ZA_Displacement"
    node.label = "Maya Displacement"
    # Object space unless Maya said otherwise. Measured on the imported FBX:
    # the unit conversion lands on the object's scale while vertex coordinates
    # stay in Maya units, so object space needs no unit term.
    space = DISPLACEMENT_SPACES.get(
        str(displacement.get("vector_space") or "").lower(), "OBJECT"
    )
    if hasattr(node, "space"):
        try:
            node.space = space
        except Exception:
            pass

    # Sockets by index on both nodes: the map, Midlevel, Scale. The scalar
    # node adds a Normal input the vector one does not have.
    apply_record_to_socket(
        material, node, node.inputs[0], "displacement", displacement, warnings
    )
    node.inputs[1].default_value = scalar(displacement.get("zero_value"), 0.0)
    # Set explicitly: the Scale default is 1.0 on 4.1 and 0.01 on 5.2, so
    # leaving it alone would displace the same package differently per version.
    node.inputs[2].default_value = (
        scalar(displacement.get("height"), 1.0)
        * scalar(displacement.get("scale"), 1.0)
    )
    links.new(node.outputs[0], target)

    # Autobump is Arnold shading the fine detail as bump rather than geometry,
    # which is what Blender's BOTH does.
    method = "BOTH" if displacement.get("autobump") else "DISPLACEMENT"
    if hasattr(material, "displacement_method"):
        try:
            material.displacement_method = method
        except Exception:
            pass

    material["za_displacement"] = method
    material["za_source_displacement_height"] = scalar(
        displacement.get("height"), 1.0
    )
    if not displacement.get("subdivision_enabled"):
        warnings.append(
            'Material "{0}" is displaced but its Maya mesh asks for no '
            "subdivision, so the displacement has no geometry to move.".format(
                material_record.get("material") or ""
            )
        )
    return True


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
        "specular",
        "anisotropic",
        "metallic",
        "opacity",
        "normal",
        "emission",
        "emission_strength",
        "coat",
        "coat_roughness",
        "coat_tint",
        "coat_ior",
        "sheen",
        "sheen_roughness",
        "sheen_tint",
        "subsurface",
        "subsurface_radius",
        "subsurface_scale",
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
            _apply_placement(material, image_node, emission_texture)
            links.new(
                apply_corrections(
                    material,
                    image_node.outputs["Color"],
                    emission_texture,
                    warnings,
                ),
                emission.inputs["Color"],
            )
    elif "value" in emission_record:
        # An unlit shader's colour is emission, so it is not clamped
        # either; a surfaceShader above one is ordinary.
        emission.inputs["Color"].default_value = color4(
            emission_record.get("value"), clamp=False
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
            _apply_placement(material, image_node, opacity_texture)
            rgb_to_bw = nodes.new("ShaderNodeRGBToBW")
            links.new(
                apply_corrections(
                    material,
                    image_node.outputs["Color"],
                    opacity_texture,
                    warnings,
                ),
                rgb_to_bw.inputs["Color"],
            )
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
                texture,
                warnings,
            )
            return

    if "value" not in record:
        return
    value = record.get("value")
    if channel in COLOUR_VALUED_CHANNELS:
        target.default_value = _fit_socket(
            target,
            color4(value, clamp=channel not in UNCLAMPED_COLOUR_CHANNELS),
        )
    elif channel == "opacity":
        target.default_value = scalar(value, 1.0)
        enable_alpha(material)
    elif channel == "normal":
        # A normal socket has no meaningful flat value.
        return
    elif channel == "specular":
        target.default_value = max(
            0.0, min(1.0, scalar(value, 1.0) * SPECULAR_WEIGHT_TO_LEVEL)
        )
    elif record.get("source_semantic") == OPENPBR_EMISSION_SEMANTIC:
        # A luminance in nits, not a socket-ready weight.
        target.default_value = max(
            0.0,
            scalar(value, 0.0) / OPENPBR_EMISSION_LUMINANCE_SCALE,
        )
    else:
        target.default_value = scalar(value, target.default_value)


def connect_image_channel(material, bsdf, target, channel, image, invert,
                         texture_record=None, warnings=None):
    nodes = material.node_tree.nodes
    links = material.node_tree.links
    image_node = nodes.new("ShaderNodeTexImage")
    image_node.name = "ZA_{0}_Texture".format(channel)
    image_node.label = channel.replace("_", " ").title()
    image_node.image = image
    _apply_placement(material, image_node, texture_record)

    # The Maya correction nodes the exporter walked past go back in here, so
    # every channel sees the corrected colour rather than the raw file.
    source = apply_corrections(
        material,
        image_node.outputs.get("Color"),
        texture_record,
        warnings if warnings is not None else [],
    )

    if channel == "normal":
        _connect_normal(material, source, target, texture_record)
        return

    if channel == "opacity":
        rgb_to_bw = nodes.new("ShaderNodeRGBToBW")
        links.new(source, rgb_to_bw.inputs.get("Color"))
        output = rgb_to_bw.outputs.get("Val")
        if invert:
            output = _insert_value_invert(nodes, links, output)
        links.new(output, target)
        enable_alpha(material)
        return

    output = source
    if invert:
        invert_node = nodes.new("ShaderNodeInvert")
        links.new(output, invert_node.inputs.get("Color"))
        output = invert_node.outputs.get("Color")
    links.new(output, target)


def _connect_normal(material, source, target, texture_record):
    """Wire a normal or bump map, honouring the bump2d strength from Maya.

    Maya's bump2d can be interpreted as a height field or as tangent space
    normals, and its bumpDepth is the strength. Both were dropped before, which
    left every normal map at Blender's default strength of one.
    """
    nodes = material.node_tree.nodes
    links = material.node_tree.links
    bump = (texture_record or {}).get("bump") or {}
    interpretation = str(bump.get("interpretation") or "").lower()
    depth = scalar(bump.get("depth"), 1.0)

    if interpretation.startswith("bump"):
        # A height field rather than a normal map.
        node = nodes.new("ShaderNodeBump")
        node.name = "ZA_Bump"
        links.new(source, node.inputs.get("Height"))
        if node.inputs.get("Strength") is not None:
            node.inputs["Strength"].default_value = max(0.0, depth)
        links.new(node.outputs.get("Normal"), target)
        return

    normal_map = nodes.new("ShaderNodeNormalMap")
    normal_map.name = "ZA_Normal_Map"
    if "object" in interpretation and hasattr(normal_map, "space"):
        try:
            normal_map.space = "OBJECT"
        except Exception:
            pass
    if normal_map.inputs.get("Strength") is not None:
        normal_map.inputs["Strength"].default_value = max(0.0, depth)
    links.new(source, normal_map.inputs.get("Color"))
    links.new(normal_map.outputs.get("Normal"), target)


def _apply_placement(material, image_node, texture_record):
    """Rebuild a place2dTexture as a Mapping node in front of the image.

    Without this a texture tiled four times in Maya arrives tiled once, which
    is a silent and very visible difference.
    """
    placement = (texture_record or {}).get("placement") or {}
    _apply_extension(image_node, placement)
    if not placement:
        return

    repeat_u = scalar(placement.get("repeat_u"), 1.0)
    repeat_v = scalar(placement.get("repeat_v"), 1.0)
    offset = placement.get("offset") or [0.0, 0.0]
    rotation = scalar(placement.get("rotate_uv_degrees"), 0.0)
    if (
        abs(repeat_u - 1.0) < 1e-6
        and abs(repeat_v - 1.0) < 1e-6
        and abs(scalar(offset[0] if offset else 0.0, 0.0)) < 1e-6
        and abs(scalar(offset[1] if len(offset) > 1 else 0.0, 0.0)) < 1e-6
        and abs(rotation) < 1e-6
    ):
        # Nothing to express; leave the tree uncluttered.
        return

    nodes = material.node_tree.nodes
    links = material.node_tree.links
    mapping = nodes.new("ShaderNodeMapping")
    mapping.name = "ZA_Placement"
    mapping.label = "Maya Placement"
    mapping.vector_type = "POINT"
    coord = nodes.new("ShaderNodeTexCoord")
    coord.name = "ZA_Placement_Coord"

    mapping.inputs["Scale"].default_value = (repeat_u, repeat_v, 1.0)
    mapping.inputs["Location"].default_value = (
        scalar(offset[0] if offset else 0.0, 0.0),
        scalar(offset[1] if len(offset) > 1 else 0.0, 0.0),
        0.0,
    )
    # rotateUV is exported in degrees, which is the unit getAttr reports.
    mapping.inputs["Rotation"].default_value = (0.0, 0.0, math.radians(rotation))

    links.new(coord.outputs.get("UV"), mapping.inputs.get("Vector"))
    links.new(mapping.outputs.get("Vector"), image_node.inputs.get("Vector"))


def _apply_extension(image_node, placement):
    """Maya wrap and mirror flags onto the image node's extension mode."""
    if not hasattr(image_node, "extension"):
        return
    mirror = bool(placement.get("mirror_u")) or bool(placement.get("mirror_v"))
    # wrapU and wrapV default to on in Maya, so an absent flag means wrap.
    wrap = bool(placement.get("wrap_u", True)) or bool(
        placement.get("wrap_v", True)
    )
    if mirror:
        mode = TEXTURE_EXTENSION_MIRROR
    elif wrap:
        mode = TEXTURE_EXTENSION_REPEAT
    else:
        mode = TEXTURE_EXTENSION_CLAMP
    try:
        image_node.extension = mode
    except Exception:
        pass


def _fit_socket(target, rgba):
    """Trim a colour to the component count the socket actually accepts.

    Most colour sockets take RGBA, but some vector ones do not: Subsurface
    Radius is three components and rejects a fourth outright.
    """
    try:
        wanted = len(target.default_value)
    except TypeError:
        return rgba[0]
    return tuple(rgba[:wanted])


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
