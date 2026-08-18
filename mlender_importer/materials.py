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

Every material produced here carries the ``ml_generated`` custom property so
the import can tell its own datablocks apart from the placeholder materials
the FBX importer creates.
"""

import math

import bpy

from .animation import animate_socket
from mathutils import Matrix, Vector

from .constants import (
    COLOUR_VALUED_CHANNELS,
    UNCLAMPED_COLOUR_CHANNELS,
    DISPLACEMENT_SPACES,
    DEFAULT_COAT_IOR,
    DEFAULT_EMISSION_STRENGTH,
    OPENPBR_EMISSION_LUMINANCE_SCALE,
    ARNOLD_SHEEN_ROUGHNESS_SEMANTIC,
    OPENPBR_EMISSION_SEMANTIC,
    OPENPBR_SPECULAR_SEMANTIC,
    SHEEN_ROUGHNESS_REMAP,
    GLASS_INPUTS,
    LAYERED_ALPHA_CHANNEL,
    LAYERED_BLEND_TYPES,
    LAYERED_BOTTOM_COLOUR,
    LAYERED_NODE_NAME,
    LAYERED_REPLACE_MODE,
    MAYA_LAYER_TEXTURE_MODE,
    PRINCIPLED_INPUTS,
    PROJECTION_DEFAULT_EXTENSION,
    PROJECTION_EXTENSIONS,
    PROJECTION_MAPPING_OFFSET,
    PROJECTION_MAPPING_ROTATION,
    PROJECTION_MODES,
    TRIPLANAR_FACES,
    TRIPLANAR_SHARPNESS,
    RAMP_FACING_MODE,
    RAMP_TEXTURE_COMPONENTS,
    RAMP_TEXTURE_INTERPOLATION,
    RAMP_INTERPOLATION,
    SPECULAR_WEIGHT_TO_LEVEL,
    TEXTURE_EXTENSION_CLAMP,
    TEXTURE_EXTENSION_MIRROR,
    TEXTURE_EXTENSION_REPEAT,
    TRANSMISSION_THRESHOLD,
    UNLIT_SHADER_TYPES,
    UV_MAP_NODE_NAME,
)
from .corrections import apply_corrections
from .transforms import maya_matrix_to_blender
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
        unique_material_name("ML_" + safe_name(display_name))
    )
    material["ml_generated"] = True
    material["ml_maya_material"] = maya_name
    material["ml_shader_type"] = material_record.get("shader_type") or ""
    material.use_nodes = True
    material.node_tree.nodes.clear()

    channels = material_record.get("channels") or {}
    # A mix or layer shader blends other shaders rather than describing a
    # surface, so its own channels are empty and the layers are the material.
    layers = material_record.get("layers") or []
    if layers:
        _build_layered(material, layers, warnings)
        apply_displacement(material, material_record, warnings)
        return material

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


def _build_layered(material, layers, warnings):
    """Build a blended material: the layer chain, then one output for it."""
    nodes = material.node_tree.nodes
    links = material.node_tree.links

    top = build_layer_chain(material, layers, warnings)
    output = nodes.new("ShaderNodeOutputMaterial")
    output.location = (300 + len(layers) * 200, 0)
    if top is not None:
        links.new(top.outputs[0], output.inputs.get("Surface"))
    return output


def build_layer_chain(material, layers, warnings):
    """Stack blended shaders into a Mix Shader chain, bottom layer first.

    Arnold's mix is the weight of the upper shader -- rendered, an unlit red
    under an unlit green at 0.25 gives (0.75, 0.25, 0) -- and Blender's Mix
    Shader factor runs the same way, so the number is used unchanged.

    Returns the node the material output should read from.
    """
    nodes = material.node_tree.nodes
    links = material.node_tree.links

    top = _layer_shader_node(material, layers[0], warnings)
    for index, layer in enumerate(layers[1:], start=1):
        upper = _layer_shader_node(material, layer, warnings)
        if upper is None:
            continue
        if top is None:
            top = upper
            continue
        if layer.get("compositing"):
            # Maya's own layeredShader, which composites its own way.
            top = _maya_layer_composite(
                material, top, upper, layer, index, warnings
            )
            continue
        mix = nodes.new("ShaderNodeMixShader")
        mix.name = "ML_Layer_Mix_{0}".format(index)
        mix.label = "Maya Layer {0}".format(index)
        mix.location = (300 + index * 200, 0)
        links.new(top.outputs[0], mix.inputs[1])
        links.new(upper.outputs[0], mix.inputs[2])
        # Index, not name: the factor socket is "Fac" on every build measured,
        # but the project has been bitten by socket names moving before.
        apply_record_to_socket(
            material, mix, mix.inputs[0], "mix",
            layer.get("mix") or {"value": 1.0}, warnings,
        )
        top = mix
    return top


def _maya_layer_composite(material, below, upper, layer, index, warnings):
    """One step of a Maya layeredShader stack, in whichever mode it is set to.

    Both modes were measured by baking an unlit green over an unlit red:
    layer_texture fades between them, layer_shaders adds the upper layer to a
    scaled copy of what is under it and leaves the upper one at full
    strength. Neither number is inverted on the way; the wiring is what
    differs.
    """
    nodes = material.node_tree.nodes
    links = material.node_tree.links
    record = _maya_layer_transparency(material, layer, warnings)

    if layer.get("compositing") == MAYA_LAYER_TEXTURE_MODE:
        mix = nodes.new("ShaderNodeMixShader")
        mix.name = "ML_MayaLayer_Mix_{0}".format(index)
        mix.label = "Maya layer texture"
        mix.location = (300 + index * 200, 0)
        # Upper first: transparency 0 means the upper layer wins, which is a
        # factor of 0, so the number reads straight off Maya.
        links.new(upper.outputs[0], mix.inputs[1])
        links.new(below.outputs[0], mix.inputs[2])
        apply_record_to_socket(
            material, mix, mix.inputs[0], "mix", record, warnings
        )
        return mix

    scale = nodes.new("ShaderNodeMixShader")
    scale.name = "ML_MayaLayer_Below_{0}".format(index)
    scale.label = "Maya layer transparency"
    scale.location = (300 + index * 200, -160)
    transparent = nodes.new("ShaderNodeBsdfTransparent")
    transparent.location = (120 + index * 200, -240)
    links.new(transparent.outputs[0], scale.inputs[1])
    links.new(below.outputs[0], scale.inputs[2])
    apply_record_to_socket(
        material, scale, scale.inputs[0], "mix", record, warnings
    )

    add = nodes.new("ShaderNodeAddShader")
    add.name = "ML_MayaLayer_Add_{0}".format(index)
    add.label = "Maya layer shaders"
    add.location = (460 + index * 200, 0)
    links.new(upper.outputs[0], add.inputs[0])
    links.new(scale.outputs[0], add.inputs[1])
    return add


def _maya_layer_transparency(material, layer, warnings):
    """A layeredShader layer's transparency as something a factor can take.

    Maya's is a colour and a Mix factor is one number. A tinted transparency
    is a real thing there and cannot be one factor here, so the components
    are averaged and the approximation is reported rather than hidden.
    """
    record = dict(layer.get("transparency") or {"value": 0.0})
    value = record.get("value")
    if isinstance(value, (list, tuple)) and value:
        components = [float(item) for item in value]
        if max(components) - min(components) > 1e-4:
            warnings.append(
                'Maya layer "{0}" has a tinted transparency {1}, which one '
                "mix factor cannot carry; its average was used in material "
                '"{2}".'.format(
                    layer.get("shader") or "?",
                    [round(item, 4) for item in components],
                    material.name,
                )
            )
        record["value"] = sum(components) / float(len(components))
    return record


def _layer_shader_node(material, layer_record, warnings):
    """Build one layer inside this material's tree, return its top node.

    The three surface builders each create their own material output, which
    is right when they are the whole material and wrong when they are one
    layer of it. Rather than split all three, the layer is built as usual and
    its output node is then removed, which keeps every per-type behaviour --
    glass, unlit, coat darkening -- reachable from here for free.
    """
    nodes = material.node_tree.nodes
    before = set(nodes)

    sub_layers = layer_record.get("layers") or []
    if sub_layers:
        return build_layer_chain(material, sub_layers, warnings)

    channels = layer_record.get("channels") or {}
    if layer_record.get("shader_type") in UNLIT_SHADER_TYPES:
        _build_unlit(material, channels, warnings)
    elif channel_is_active(channels.get("transmission")):
        _build_glass(material, channels, warnings)
    else:
        _build_principled(material, channels, warnings)
    return _detach_output(material, before)


def _detach_output(material, before):
    """Remove the output a layer builder made and return what fed it."""
    nodes = material.node_tree.nodes
    output = next(
        (
            node for node in nodes
            if node not in before
            and node.bl_idname == "ShaderNodeOutputMaterial"
        ),
        None,
    )
    if output is None:
        return None
    surface = output.inputs.get("Surface")
    source = None
    if surface is not None and surface.is_linked:
        source = surface.links[0].from_node
    nodes.remove(output)
    return source


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
    node.name = "ML_Displacement"
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

    material["ml_displacement"] = method
    material["ml_source_displacement_height"] = scalar(
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
        "ior",
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
    apply_sheen_roughness_remap(material, bsdf, channels, warnings)
    # Before the coat darkening, so the darkening curve sees the base colour
    # the metal lobe actually starts from.
    apply_openpbr_metal_specular(material, bsdf, channels, warnings)
    apply_coat_darkening(material, bsdf, channels, warnings)


def remapped_sheen_roughness(value):
    """Arnold standard surface sheen roughness onto Blender's scale."""
    value = max(0.0, float(value))
    points = SHEEN_ROUGHNESS_REMAP
    if value >= points[-1][0]:
        return points[-1][1]
    for index in range(len(points) - 1):
        low, low_out = points[index]
        high, high_out = points[index + 1]
        if low <= value <= high and high > low:
            span = (value - low) / (high - low)
            return low_out + (high_out - low_out) * span
    return points[0][1]


def apply_sheen_roughness_remap(material, bsdf, channels, warnings):
    """Put an aiStandardSurface sheen roughness onto Blender's scale.

    The two sheen lobes are different models and their roughness inputs do not
    mean the same thing: at 0.3 Arnold shows a sheen that Blender barely
    registers, and at 1.0 Blender shows more than twice as much as Arnold.
    Measured at three viewing angles and two base albedos, one remap of the
    roughness reconciles them, and it came out the same at both albedos.

    OpenPBR's fuzz already matches Blender and is left alone; the exporter
    tags only the record this applies to.
    """
    record = channels.get("sheen_roughness") or {}
    if record.get("source_semantic") != ARNOLD_SHEEN_ROUGHNESS_SEMANTIC:
        return
    socket = principled_input(bsdf, "sheen_roughness")
    if socket is None:
        # Blender 3.x has a sheen with no roughness at all.
        return
    if (record.get("texture") or {}).get("path"):
        warnings.append(
            "sheen roughness is textured on {0}; it was left on the Arnold "
            "scale, which reads differently in Blender".format(material.name)
        )
        return
    source = scalar(record.get("value"), None)
    if source is None:
        return
    socket.default_value = remapped_sheen_roughness(source)
    material["ml_source_sheen_roughness"] = float(source)


def apply_openpbr_metal_specular(material, bsdf, channels, warnings):
    """Scale the base colour where OpenPBR's specular weight scales the metal.

    OpenPBR multiplies its metal lobe by the specular weight, so a metal with
    the weight at zero renders black; aiStandardSurface keeps its metal and
    Principled has no input that does this at all. Untouched, such a material
    arrived as a bright metal where Maya showed nothing.

    Measured against Arnold at five weights and five metalness values: the
    result is exactly ``base * (1 - metalness * (1 - weight))``. At the
    default weight of one the factor is one and nothing is touched.
    """
    specular = channels.get("specular") or {}
    if specular.get("source_semantic") != OPENPBR_SPECULAR_SEMANTIC:
        return
    if (specular.get("texture") or {}).get("path"):
        # A mapped weight would need the whole curve as nodes, and a metal
        # with a textured specular weight has not been seen in practice.
        warnings.append(
            "OpenPBR specular weight is textured on {0}; its effect on the "
            "metal lobe was not applied".format(material.name)
        )
        return
    weight = max(0.0, min(1.0, scalar(specular.get("value"), 1.0)))
    metallic = channels.get("metallic") or {}
    if (metallic.get("texture") or {}).get("path"):
        warnings.append(
            "OpenPBR metalness is textured on {0}; the specular weight was "
            "applied at full metalness".format(material.name)
        )
        metal = 1.0
    else:
        metal = max(0.0, min(1.0, scalar(metallic.get("value"), 0.0)))

    factor = 1.0 - metal * (1.0 - weight)
    if factor >= 1.0 - 1e-6:
        return
    socket = principled_input(bsdf, "base_color")
    if socket is None:
        return
    if socket.is_linked:
        _insert_colour_scale(material, socket, factor)
    else:
        colour = list(socket.default_value)
        for index in range(3):
            colour[index] = max(0.0, colour[index]) * factor
        socket.default_value = colour
    material["ml_openpbr_specular_scale"] = factor


def _insert_colour_scale(material, socket, factor):
    """Put a flat multiply between whatever feeds a colour socket and it."""
    nodes = material.node_tree.nodes
    links = material.node_tree.links
    source = socket.links[0].from_socket
    node = nodes.new("ShaderNodeVectorMath")
    node.operation = "MULTIPLY"
    node.name = "ML_SpecularMetalScale"
    node.label = "OpenPBR Specular Weight"
    node.location = (socket.node.location[0] - 780,
                     socket.node.location[1] - 120)
    node.inputs[1].default_value = (factor, factor, factor)
    links.new(source, node.inputs[0])
    links.new(node.outputs[0], socket)


def coat_internal_reflectance(ior):
    """Fraction of diffuse light the coat reflects back down, from inside.

    The standard approximation, kept rather than a table because it was
    checked against Arnold at three coat IORs and reproduced every one to
    about a part in ten thousand (tests/docs/material_match.md).
    """
    ior = max(1.0, float(ior))
    return -1.440 / (ior * ior) + 0.710 / ior + 0.668 + 0.0636 * ior


def coat_darkening_amount(channels):
    """How much of the full darkening this material asks for, nought to one.

    Linear in the darkening attribute, measured; and quadratic in the coat
    weight, because the light crosses the coat on the way in and again on the
    way out. Linear in the weight is 17% wrong at half coverage, squared is
    within half a per cent.
    """
    darkening = scalar((channels.get("coat_darkening") or {}).get("value"), 0.0)
    weight = scalar((channels.get("coat") or {}).get("value"), 0.0)
    darkening = max(0.0, min(1.0, darkening))
    weight = max(0.0, min(1.0, weight))
    return darkening * weight * weight


def apply_coat_darkening(material, bsdf, channels, warnings):
    """Fold OpenPBR's coat darkening into the base colour.

    OpenPBR darkens what is under the coat, by an amount that depends on the
    base colour itself: light bounced back down by the underside of the coat
    is absorbed again, so a dark base loses far more than a bright one.
    Principled has no such input, and without this a coated OpenPBR material
    arrived up to twice as bright as Maya rendered it.

    Applied here rather than in the exporter so the package keeps reporting
    the base colour the artist actually set.
    """
    amount = coat_darkening_amount(channels)
    if amount <= 0.0:
        return
    socket = principled_input(bsdf, "base_color")
    if socket is None:
        return
    ior_socket = principled_input(bsdf, "coat_ior")
    ior = getattr(ior_socket, "default_value", DEFAULT_COAT_IOR)
    reflectance = max(0.0, min(0.99, coat_internal_reflectance(ior)))

    if socket.is_linked:
        _insert_coat_darkening(material, socket, reflectance, amount)
    else:
        colour = list(socket.default_value)
        for index in range(3):
            colour[index] = _darkened_channel(
                colour[index], reflectance, amount
            )
        socket.default_value = colour
    material["ml_coat_darkening"] = amount
    material["ml_coat_internal_reflectance"] = reflectance


def _darkened_channel(value, reflectance, amount):
    """base * (1 - amount * (1 - (1 - r) / (1 - r * base)))."""
    base = max(0.0, float(value))
    full = (1.0 - reflectance) / max(1e-6, 1.0 - reflectance * min(1.0, base))
    return base * (1.0 - amount * (1.0 - full))


def _insert_coat_darkening(material, socket, reflectance, amount):
    """Build the same curve as nodes, for a textured base colour.

    Sockets are addressed by index throughout: Vector Math input names have
    moved between 4.1 and 5.2 while the indices have not.

    Written out, with b the incoming colour, r the coat's internal
    reflectance and f the amount:

        b * (1 - r * (b * (1 - f) + f)) / (1 - r * b)
    """
    nodes = material.node_tree.nodes
    links = material.node_tree.links
    source = socket.links[0].from_socket
    origin = socket.node.location

    def vector(operation, index, first, second):
        node = nodes.new("ShaderNodeVectorMath")
        node.operation = operation
        node.name = "ML_CoatDarkening_{0}".format(index)
        node.label = "Coat Darkening"
        node.location = (origin[0] - 720 + index * 80, origin[1] - 320)
        for slot, value in ((0, first), (1, second)):
            if hasattr(value, "is_output"):
                links.new(value, node.inputs[slot])
            else:
                node.inputs[slot].default_value = (value, value, value)
        return node.outputs[0]

    scaled = vector("MULTIPLY", 0, source, 1.0 - amount)
    shifted = vector("ADD", 1, scaled, amount)
    inner = vector("MULTIPLY", 2, shifted, reflectance)
    numerator_term = vector("SUBTRACT", 3, 1.0, inner)
    numerator = vector("MULTIPLY", 4, source, numerator_term)
    denominator_term = vector("MULTIPLY", 5, source, reflectance)
    denominator = vector("SUBTRACT", 6, 1.0, denominator_term)
    result = vector("DIVIDE", 7, numerator, denominator)
    links.new(result, socket)


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
    glass.name = "ML_Glass"
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
        mix.name = "ML_Glass_Opacity"
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

    material["ml_material_mode"] = "GLASS_BSDF"
    material["ml_transmission_weight"] = scalar(
        (channels.get("transmission") or {}).get("value"),
        1.0,
    )
    material["ml_thin_walled"] = bool(
        scalar((channels.get("thin_walled") or {}).get("value"), 0.0)
    )
    material["ml_transmission_affects_alpha"] = bool(
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
            image_node.name = "ML_Unlit_Color"
            image_node.image = image
            _apply_placement(material, image_node, emission_texture, warnings)
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
            image_node.name = "ML_Unlit_Opacity"
            image_node.image = image
            _apply_placement(material, image_node, opacity_texture, warnings)
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


def build_projection(material, texture, warnings):
    """A Maya projection as an Image Texture read through a place3dTexture.

    Measured, planar, with the tool's own bake as the ground truth: Maya's
    image covers the placement's local -0.5..0.5 on both axes, u along +X and
    v along +Y, with no flip. The same picture comes back in Blender from a
    Texture Coordinate Object output through a Mapping node rotated -90
    degrees about X and moved by +0.5; the rotation undoes the Y-up to Z-up
    conversion so the texture space is Maya's again, and +90 is vertically
    flipped.

    Only Planar is reproduced. The other types each need their own
    measurement, and a projection in the wrong shape is worse than one that
    says it needs the bake.

    Returns the socket carrying the projected colour, or None. A socket
    rather than a node: a triplanar result is three lookups blended together
    and has no single image node to hand back.
    """
    projection = texture.get("projection") or {}
    kind = str(projection.get("type") or "")
    image_record = projection.get("image") or {}
    if kind not in PROJECTION_MODES or not image_record.get("path"):
        warnings.append(
            'Maya projection "{0}" is {1}, which this build cannot rebuild; '
            "it needs Bake Procedurals to travel.".format(
                projection.get("node") or "?", kind or "an unknown type"
            )
        )
        return None

    image = load_image(image_record, "projection", warnings)
    if image is None:
        return None

    nodes = material.node_tree.nodes
    links = material.node_tree.links

    node = nodes.new("ShaderNodeTexImage")
    node.name = "ML_Projection"
    node.label = "Maya {0} Projection".format(kind)
    node.image = image
    node.projection = PROJECTION_MODES[kind]
    # Per type, and measured for each: a planar projection clamps at its
    # extent while a cylindrical one wraps, because its half turn goes round
    # the object twice. Using one rule for both costs 0.2 either way.
    node.extension = PROJECTION_EXTENSIONS.get(
        kind, PROJECTION_DEFAULT_EXTENSION
    )
    node.location = (-500, 0)

    empty = _placement_empty(projection)
    coords = nodes.new("ShaderNodeTexCoord")
    coords.name = "ML_Projection_Coord"
    coords.location = (-1100, 0)
    if empty is not None:
        coords.object = empty

    mapping = nodes.new("ShaderNodeMapping")
    mapping.name = "ML_Projection_Mapping"
    mapping.label = "Maya texture space"
    mapping.location = (-900, 0)
    mapping.inputs["Rotation"].default_value = PROJECTION_MAPPING_ROTATION
    if kind == "Planar":
        # Planar reads the placement's local X and Y straight, over its
        # -0.5..0.5, so the half offset is all it needs.
        mapping.inputs["Location"].default_value = PROJECTION_MAPPING_OFFSET
    links.new(coords.outputs["Object"], mapping.inputs["Vector"])

    if kind == "TriPlanar":
        # Three lookups rather than one, so the node made above is the first
        # of them and the others are built alongside it.
        return _triplanar_colour(material, node, mapping.outputs["Vector"])

    if kind == "Spherical":
        vector = _spherical_vector(material, mapping.outputs["Vector"])
    elif kind == "Cylindrical":
        vector = _cylindrical_vector(material, mapping.outputs["Vector"])
    elif kind == "Perspective":
        vector = _perspective_vector(material, mapping.outputs["Vector"])
    else:
        vector = mapping.outputs["Vector"]
    links.new(vector, node.inputs["Vector"])
    return node.outputs["Color"]


def _spherical_vector(material, vector_socket):
    """Longitude and latitude, the way Maya's spherical projection reads them.

    Measured against Maya's own bake: u is ``atan2(x, z)`` over a full turn
    and v is ``asin(y / length)`` over a half turn, both centred on 0.5. The
    fixture had to be a sixteen cell grid to establish it -- four quadrants
    scored the winner and its mirror 0.0216 against 0.0217, which is not an
    answer -- and with the grid it is 0.019 against 0.123 for the runner up.

    Blender's own SPHERE projection is not this mapping: it plateaus at 0.106
    however it is turned or flipped.
    """
    nodes = material.node_tree.nodes
    links = material.node_tree.links

    separate = nodes.new("ShaderNodeSeparateXYZ")
    separate.name = "ML_Projection_Axes"
    separate.location = (-700, 0)
    links.new(vector_socket, separate.inputs[0])

    length = nodes.new("ShaderNodeVectorMath")
    length.name = "ML_Projection_Radius"
    length.operation = "LENGTH"
    length.location = (-700, -260)
    links.new(vector_socket, length.inputs[0])

    longitude = _math(material, "ARCTAN2", (-520, 80),
                      separate.outputs["X"], separate.outputs["Z"])
    unit = _math(material, "DIVIDE", (-360, 80), longitude, None,
                 2.0 * math.pi)
    u = _math(material, "ADD", (-200, 80), unit, None, 0.5)

    sine = _math(material, "DIVIDE", (-520, -160),
                 separate.outputs["Y"], length.outputs["Value"])
    latitude = _math(material, "ARCSINE", (-360, -160), sine)
    half = _math(material, "DIVIDE", (-260, -160), latitude, None, math.pi)
    v = _math(material, "ADD", (-160, -160), half, None, 0.5)

    combine = nodes.new("ShaderNodeCombineXYZ")
    combine.name = "ML_Projection_UV"
    combine.location = (-60, 0)
    links.new(u, combine.inputs["X"])
    links.new(v, combine.inputs["Y"])
    return combine.outputs[0]


def _cylindrical_vector(material, vector_socket):
    """An angle around the placement's Y, and the height straight up it.

    Read off Maya rather than guessed at: an image encoding u in red and v in
    green was projected and baked, so every surface point reported the pair
    Maya had computed for it. Against the placement-local coordinates of the
    same points, v is ``y / 2 + 0.5`` exactly, and u is twice the spherical
    longitude less a half -- that is, the image wraps over a **half** turn
    rather than a whole one, which is why the sweep divides by pi.

    Guessing a full turn scored 0.30 against Maya's bake and the half turn
    scores 0.02.
    """
    nodes = material.node_tree.nodes
    links = material.node_tree.links

    separate = nodes.new("ShaderNodeSeparateXYZ")
    separate.name = "ML_Projection_Axes"
    separate.location = (-700, 0)
    links.new(vector_socket, separate.inputs[0])

    longitude = _math(material, "ARCTAN2", (-520, 80),
                      separate.outputs["X"], separate.outputs["Z"])
    swept = _math(material, "DIVIDE", (-360, 80), longitude, None, math.pi)
    u = _math(material, "ADD", (-200, 80), swept, None, 0.5)

    half = _math(material, "MULTIPLY", (-360, -160),
                 separate.outputs["Y"], None, 0.5)
    v = _math(material, "ADD", (-200, -160), half, None, 0.5)

    combine = nodes.new("ShaderNodeCombineXYZ")
    combine.name = "ML_Projection_UV"
    combine.location = (-60, 0)
    links.new(u, combine.inputs["X"])
    links.new(v, combine.inputs["Y"])
    return combine.outputs[0]


def _perspective_vector(material, vector_socket):
    """A perspective divide from the placement, the way Maya projects it.

    Read off Maya's own bake: ``u = 0.5 - x / 2z`` and ``v = 0.5 - y / 2z``.
    Behind the projector, where z is positive, Maya returns the centre of the
    image, and reproducing that is worth 0.14 on its own.

    The residual on a sphere is 0.08 whole but 0.008 away from the silhouette:
    a perspective divide explodes as z approaches zero, so a sub-texel
    difference there lands in a different part of the image. That band is the
    test geometry, not the mapping.
    """
    nodes = material.node_tree.nodes
    links = material.node_tree.links

    separate = nodes.new("ShaderNodeSeparateXYZ")
    separate.name = "ML_Projection_Axes"
    separate.location = (-700, 0)
    links.new(vector_socket, separate.inputs[0])
    depth = separate.outputs["Z"]

    u = _math(material, "ADD", (-300, 80), _math(
        material, "MULTIPLY", (-450, 80),
        _math(material, "DIVIDE", (-580, 80), separate.outputs["X"], depth),
        None, -0.5), None, 0.5)
    v = _math(material, "ADD", (-300, -160), _math(
        material, "MULTIPLY", (-450, -160),
        _math(material, "DIVIDE", (-580, -160), separate.outputs["Y"], depth),
        None, -0.5), None, 0.5)

    combine = nodes.new("ShaderNodeCombineXYZ")
    combine.name = "ML_Projection_UV"
    combine.location = (-160, 0)
    links.new(u, combine.inputs["X"])
    links.new(v, combine.inputs["Y"])

    behind = nodes.new("ShaderNodeMix")
    behind.name = "ML_Projection_Behind"
    behind.label = "Behind the projector"
    behind.data_type = "VECTOR"
    behind.location = (-40, 0)
    links.new(_math(material, "GREATER_THAN", (-160, -300), depth, None, 0.0),
              behind.inputs["Factor"])
    links.new(combine.outputs[0], behind.inputs[4])
    behind.inputs[5].default_value = (0.5, 0.5, 0.0)
    return behind.outputs[1]


def _triplanar_colour(material, first_image, vector_socket):
    """Three planar lookups blended by the normal, as Maya's TriPlanar is.

    The pairing was read off Maya's bake rather than guessed: the dominant
    axis names the face, and each face reads the other two, halved and
    centred -- twice the extent of a plain planar projection.

    Blender's own BOX projection is not this. It stops at 0.27 however it is
    offset, scaled or blended, because it pairs its axes differently.

    The blend is by the normal. On the measuring sphere the normal and the
    position point the same way, so the fixture cannot tell them apart; the
    normal is used because that is what a triplanar projection means.
    """
    nodes = material.node_tree.nodes
    links = material.node_tree.links

    separate = nodes.new("ShaderNodeSeparateXYZ")
    separate.name = "ML_Projection_Axes"
    separate.location = (-820, 200)
    links.new(vector_socket, separate.inputs[0])

    centred = {}
    for index, axis in enumerate("XYZ"):
        centred[axis] = _math(
            material, "ADD", (-620, 300 - index * 120),
            _math(material, "MULTIPLY", (-720, 300 - index * 120),
                  separate.outputs[axis], None, 0.5),
            None, 0.5,
        )

    # The normal, turned into the placement's space the same way the
    # coordinates were.
    geometry = nodes.new("ShaderNodeNewGeometry")
    geometry.location = (-820, -300)
    normal_map = nodes.new("ShaderNodeMapping")
    normal_map.name = "ML_Projection_Normal"
    normal_map.location = (-660, -300)
    normal_map.inputs["Rotation"].default_value = PROJECTION_MAPPING_ROTATION
    links.new(geometry.outputs["Normal"], normal_map.inputs["Vector"])
    normal_axes = nodes.new("ShaderNodeSeparateXYZ")
    normal_axes.location = (-500, -300)
    links.new(normal_map.outputs["Vector"], normal_axes.inputs[0])

    weights = {}
    for index, axis in enumerate("XYZ"):
        weights[axis] = _math(
            material, "POWER", (-340, -220 - index * 120),
            _math(material, "ABSOLUTE", (-420, -220 - index * 120),
                  normal_axes.outputs[axis]),
            None, TRIPLANAR_SHARPNESS,
        )
    total = _math(material, "ADD", (-180, -320),
                  _math(material, "ADD", (-260, -320),
                        weights["X"], weights["Y"]),
                  weights["Z"])

    result = None
    for index, (face, first, second) in enumerate(TRIPLANAR_FACES):
        image = first_image if index == 0 else nodes.new("ShaderNodeTexImage")
        if index:
            image.image = first_image.image
            image.projection = first_image.projection
            image.extension = first_image.extension
        image.name = "ML_Projection_{0}".format(face)
        image.location = (-260, 300 - index * 260)
        pair = nodes.new("ShaderNodeCombineXYZ")
        pair.location = (-400, 300 - index * 260)
        links.new(centred[first], pair.inputs["X"])
        links.new(centred[second], pair.inputs["Y"])
        links.new(pair.outputs[0], image.inputs["Vector"])

        share = nodes.new("ShaderNodeMix")
        share.data_type = "RGBA"
        share.location = (-60, 300 - index * 260)
        links.new(_math(material, "DIVIDE", (-160, 220 - index * 260),
                        weights[face], total), share.inputs["Factor"])
        share.inputs[6].default_value = (0.0, 0.0, 0.0, 1.0)
        links.new(image.outputs["Color"], share.inputs[7])

        if result is None:
            result = share.outputs[2]
            continue
        total_mix = nodes.new("ShaderNodeMix")
        total_mix.data_type = "RGBA"
        total_mix.blend_type = "ADD"
        total_mix.inputs["Factor"].default_value = 1.0
        total_mix.location = (100, 200 - index * 160)
        links.new(result, total_mix.inputs[6])
        links.new(share.outputs[2], total_mix.inputs[7])
        result = total_mix.outputs[2]
    return result


def _math(material, operation, location, first, second=None, value=None):
    """One Math node, wired or filled, returning its output socket."""
    node = material.node_tree.nodes.new("ShaderNodeMath")
    node.operation = operation
    node.location = location
    if first is not None:
        material.node_tree.links.new(first, node.inputs[0])
    if second is not None:
        material.node_tree.links.new(second, node.inputs[1])
    elif value is not None:
        node.inputs[1].default_value = value
    return node.outputs[0]


def import_projection_placements(package_data, collection, import_scale,
                                 warnings):
    """Build one Empty per place3dTexture, before any material needs it.

    A separate pass for the same reason the locators and curves have one: the
    materials are built deep inside the mesh loop, and threading the scene
    scale down to every socket writer to make an object there would be worse
    than looking one up by name.

    Scale is kept, unlike the light and camera conversion that strips it. A
    placement's scale is what sets how large the projection is, so dropping it
    would project the image at the wrong size.

    The scene unit belongs in that scale too, and this is the one thing the
    first measurement could not see because it was made at a scale of one.
    Maya's projection covers half a *Maya unit* either side of the placement,
    while Blender's object coordinates come out in metres; without the unit
    in the Empty's scale a centimetre scene projects the image a hundred
    times too small, which on a sphere reads as one flat colour.
    """
    meters_per_unit = scalar(package_data.get("meters_per_maya_unit"), 0.01)
    position_scale = meters_per_unit * max(scalar(import_scale, 1.0), 1e-6)

    built = 0
    for projection in _scene_projections(package_data):
        name = _placement_name(projection)
        if not name or bpy.data.objects.get(name):
            continue
        try:
            empty = bpy.data.objects.new(name, None)
            empty["ml_generated"] = True
            empty["ml_maya_placement"] = projection.get("placement") or name
            empty.empty_display_type = "CUBE"
            if collection is not None:
                collection.objects.link(empty)
            basis = maya_matrix_to_blender(projection, position_scale)
            axes = Vector(_matrix_scale(projection)) * position_scale
            empty.matrix_world = basis @ Matrix.Diagonal(axes).to_4x4()
        except Exception as exc:
            warnings.append(
                'Texture placement "{0}" could not be built: {1}'.format(
                    projection.get("placement") or "?", exc
                )
            )
            continue
        built += 1
    return built


def _scene_projections(package_data):
    """Every projection record in the package, materials and layers alike."""
    found = []

    def walk(material):
        for record in (material.get("channels") or {}).values():
            projection = (record.get("texture") or {}).get("projection")
            if projection:
                found.append(projection)
        for layer in material.get("layers") or []:
            walk(layer)

    for mesh in package_data.get("meshes") or []:
        for material in mesh.get("materials") or []:
            walk(material)
    return found


def _placement_name(projection):
    name = projection.get("placement")
    return "ML_" + safe_name(name) if name else ""


def _placement_empty(projection):
    """The Empty built for this placement, or None if there was none."""
    name = _placement_name(projection)
    return bpy.data.objects.get(name) if name else None


def _matrix_scale(record):
    values = record.get("world_matrix") or []
    if len(values) != 16:
        return (1.0, 1.0, 1.0)
    lengths = []
    for start in (0, 4, 8):
        axis = values[start:start + 3]
        length = sum(float(item) * float(item) for item in axis) ** 0.5
        lengths.append(length if length > 1e-9 else 1.0)
    return tuple(lengths)


def build_layered_texture(material, shader, texture, channel, warnings):
    """A Maya layeredTexture as a stack of Mix nodes, and its output socket.

    Maya lists the top layer first and composites downwards, so the stack is
    built from the other end: each layer mixes over everything already under
    it, with its own alpha on the factor.

    One Mix node per layer including the bottom one, which is not waste. The
    bottom layer composites against black in Maya -- measured, a 0.8 layer at
    alpha 0.5 bakes to 0.4 -- so its alpha has to multiply it, and a node that
    mixes it up from black is exactly that.
    """
    layers = ((texture.get("layered") or {}).get("layers")) or []
    if not layers:
        return None

    nodes = material.node_tree.nodes
    links = material.node_tree.links
    output = None
    for position, layer in enumerate(reversed(layers)):
        mode = str(layer.get("blend_mode") or "over").lower()
        blend = LAYERED_BLEND_TYPES.get(mode)
        if output is not None and blend is None and mode != LAYERED_REPLACE_MODE:
            warnings.append(
                'Maya layer blend mode "{0}" on "{1}" has no Blender '
                "equivalent; that layer was left out of material "
                '"{2}".'.format(
                    mode, (texture.get("layered") or {}).get("node") or "?",
                    material.name,
                )
            )
            continue

        mix = nodes.new("ShaderNodeMixRGB")
        mix.name = "{0}_{1}".format(LAYERED_NODE_NAME, position)
        mix.label = "Maya layer: {0}".format(mode)
        mix.location = (-1000 + position * 220, 320)

        if output is None:
            # Nothing under it: the layer comes up from black, so its alpha
            # multiplies it rather than mixing it with anything.
            mix.blend_type = "MIX"
            mix.inputs[1].default_value = LAYERED_BOTTOM_COLOUR
            _layer_alpha(material, shader, layer, mix.inputs[0], warnings)
        elif mode == LAYERED_REPLACE_MODE:
            mix.blend_type = "MIX"
            mix.inputs[0].default_value = 1.0
            links.new(output, mix.inputs[1])
        else:
            mix.blend_type = blend
            links.new(output, mix.inputs[1])
            _layer_alpha(material, shader, layer, mix.inputs[0], warnings)

        # The layer's own colour goes through the ordinary channel wiring, so
        # a layer holding a file with its placement, a projection or a
        # gradient needs nothing repeated here.
        apply_record_to_socket(
            material, shader, mix.inputs[2], channel,
            layer.get("color") or {}, warnings,
        )
        output = mix.outputs[0]
    return output


def _layer_alpha(material, shader, layer, target, warnings):
    """Drive a Mix factor from a layer's alpha, texture or flat value."""
    record = layer.get("alpha")
    if not record:
        target.default_value = 1.0
        return
    apply_record_to_socket(
        material, shader, target, LAYERED_ALPHA_CHANNEL, record, warnings
    )


def build_texture_ramp(material, texture, warnings):
    """A Maya ramp *texture* as a Color Ramp driven by a UV coordinate.

    Different node from a rampShader and a different driver: this one is a
    function of the surface's UVs rather than of the viewing angle.

    Measured by baking a red-to-blue ramp through the tool's own bake path
    and reading the image: a V Ramp puts position 0 at v=0 and a U Ramp puts
    it at u=0, so neither is inverted. Only those two are reproduced; the
    radial, box and tartan types are shapes a single Color Ramp cannot make,
    and they keep falling back to the bake rather than arriving wrong.

    Returns the Color Ramp node, or None.
    """
    ramp_record = texture.get("ramp") or {}
    entries = ramp_record.get("entries") or []
    kind = str(ramp_record.get("type") or "")
    if len(entries) < 2:
        return None
    component = RAMP_TEXTURE_COMPONENTS.get(kind)
    if component is None:
        warnings.append(
            'Maya ramp texture "{0}" is a {1}, which one Color Ramp cannot '
            "reproduce; it needs Bake Procedurals to travel.".format(
                texture.get("node") or "?", kind or "ramp"
            )
        )
        return None

    nodes = material.node_tree.nodes
    links = material.node_tree.links

    coords = nodes.new("ShaderNodeTexCoord")
    coords.name = "ML_RampTex_Coord"
    coords.location = (-1100, 0)
    split = nodes.new("ShaderNodeSeparateXYZ")
    split.name = "ML_RampTex_Split"
    split.location = (-900, 0)
    links.new(coords.outputs["UV"], split.inputs[0])

    ramp = nodes.new("ShaderNodeValToRGB")
    ramp.name = "ML_RampTex"
    ramp.label = "Maya {0}".format(kind)
    ramp.location = (-700, 0)
    links.new(split.outputs[component], ramp.inputs[0])
    _fill_ramp(
        ramp,
        entries,
        RAMP_TEXTURE_INTERPOLATION.get(
            str(ramp_record.get("interpolation") or "Linear"), "LINEAR"
        ),
    )
    return ramp


def build_ramp(material, record, warnings):
    """A rampShader gradient as a Color Ramp driven by the facing angle.

    Measured, because Arnold does not evaluate a rampShader at all and the
    direction had to come from Maya's own software renderer: an unlit
    red-to-blue facing ramp renders blue in the centre and red at the rim, so
    position 1 faces the camera and position 0 grazes.

    Blender's Layer Weight "Facing" runs the other way and is not linear
    (0.011 facing, 0.221 toward the rim). dot(Normal, Incoming) is the cosine
    itself, 0.988 facing and falling toward the rim, so it is what drives the
    ramp; nothing is inverted on the way.

    Returns the Color Ramp node, or None.
    """
    ramp_record = record.get("ramp") or {}
    entries = ramp_record.get("entries") or []
    # One stop is a constant, not a gradient, and every rampShader has a
    # default single entry on every ramp it owns. Building a Color Ramp for
    # those puts a node tree on channels the artist never touched; the flat
    # value the record also carries says the same thing.
    if len(entries) < 2:
        return None

    nodes = material.node_tree.nodes
    links = material.node_tree.links

    geometry = nodes.new("ShaderNodeNewGeometry")
    geometry.name = "ML_Ramp_Geometry"
    geometry.location = (-900, 0)
    facing = nodes.new("ShaderNodeVectorMath")
    facing.name = "ML_Ramp_Facing"
    facing.label = "Facing Angle"
    facing.operation = "DOT_PRODUCT"
    facing.location = (-700, 0)
    links.new(geometry.outputs["Normal"], facing.inputs[0])
    links.new(geometry.outputs["Incoming"], facing.inputs[1])

    ramp = nodes.new("ShaderNodeValToRGB")
    ramp.name = "ML_Ramp"
    ramp.label = "Maya Ramp"
    ramp.location = (-500, 0)
    # Index, not name: the factor socket is "Fac" on every build measured,
    # but socket names have moved between versions in this project before.
    links.new(facing.outputs["Value"], ramp.inputs[0])
    _fill_ramp(ramp, entries)

    mode = ramp_record.get("input") or ""
    if mode and mode != RAMP_FACING_MODE:
        warnings.append(
            'Maya drove a ramp by "{0}", which a Blender shader graph cannot '
            "see; the gradient arrived driven by the facing angle "
            "instead.".format(mode)
        )
    return ramp


def _fill_ramp(ramp, entries, interpolation=None):
    """Write the stops, keeping the ones Blender cannot hold out of the way.

    A new Color Ramp starts with two stops and its first cannot be removed,
    so the existing ones are reused before any are added.
    """
    elements = ramp.color_ramp.elements
    while len(elements) > 1:
        elements.remove(elements[-1])

    for index, entry in enumerate(entries):
        colour = list(entry.get("color") or [0.0, 0.0, 0.0])[:3]
        while len(colour) < 3:
            colour.append(0.0)
        position = max(0.0, min(1.0, float(entry.get("position", 0.0))))
        element = elements[0] if index == 0 else elements.new(position)
        element.position = position
        element.color = (colour[0], colour[1], colour[2], 1.0)

    # A rampShader keeps an interpolation per stop and Blender keeps one per
    # ramp, so the first stop's decides; a ramp texture keeps one on the node
    # and the caller passes it in.
    if interpolation is None:
        interpolation = RAMP_INTERPOLATION.get(
            str(entries[0].get("interp") or "Linear"), "LINEAR"
        )
    try:
        ramp.color_ramp.interpolation = interpolation
    except Exception:
        pass


def build_color_attribute(material, texture, channel, warnings):
    """A Color Attribute node reading the colour set the Maya shader named.

    The set itself already arrived: the FBX carries a painted colour set and
    Blender lands it as a corner colour attribute under its Maya name. What was
    missing was anything reading it -- an aiUserDataColor used to be an
    unsupported network, so the channel collapsed to black with no warning.

    The node is looked up by class name rather than assumed: Blender renamed
    this node once already, so both spellings are tried before giving up.
    """
    name = str(texture.get("color_set") or "").strip()
    if not name:
        return None
    nodes = material.node_tree.nodes
    node = None
    for identifier in ("ShaderNodeVertexColor", "ShaderNodeAttribute"):
        try:
            node = nodes.new(identifier)
            break
        except Exception:
            node = None
    if node is None:
        warnings.append(
            'Channel "{0}" reads the colour set "{1}", which this Blender has '
            "no node for.".format(channel, name)
        )
        return None
    node.name = "ML_ColorSet_{0}".format(name)
    node.label = name
    if hasattr(node, "layer_name"):
        node.layer_name = name
    elif hasattr(node, "attribute_name"):
        node.attribute_name = name
        if hasattr(node, "attribute_type"):
            node.attribute_type = "GEOMETRY"
    output = node.outputs.get("Color")
    if output is None and node.outputs:
        output = node.outputs[0]
    return output


def apply_record_to_socket(material, shader, target, channel, record, warnings):
    """Wire a channel record into any socket, texture first then flat value.

    Kept separate from the Principled mapping so the glass path can drive a
    Glass BSDF's sockets through exactly the same texture and invert handling.
    """
    if not record or target is None:
        return

    # Keyed in Maya: the samples are the evaluated values, so they go straight
    # onto the socket as keys. Before the texture branches because a channel
    # that is keyed has no texture -- the upstream walk stops at an animation
    # curve rather than treating it as a network.
    samples = record.get("samples") or []
    if len(samples) >= 2:
        node = getattr(target, "node", None)
        keyed = animate_socket(material, node, target, samples, warnings)
        if keyed:
            return

    # Before the texture: a rampShader carries a gradient and a fallback
    # value in the same record, and taking the value would flatten it.
    if record.get("ramp"):
        ramp = build_ramp(material, record, warnings)
        if ramp is not None:
            material.node_tree.links.new(ramp.outputs["Color"], target)
            return

    texture = record.get("texture") or {}
    # The flag the exporter has always written and nothing ever read. A
    # network it cannot express leaves the channel on its flat value, which
    # for a colour is usually black -- so the user got a black material and
    # not one word about why.
    if texture.get("unsupported_network") and not texture.get("path"):
        warnings.append(
            'Channel "{0}" is driven by a "{1}" network Maya could not hand '
            "over; the channel fell back to its flat value. Use Bake "
            "Procedurals to carry it.".format(
                channel, texture.get("node_type") or "procedural"
            )
        )

    # A colour set has no path and no image; it reads geometry the mesh
    # already carries, so it comes before anything that looks for a file.
    if texture.get("color_set"):
        attribute = build_color_attribute(material, texture, channel, warnings)
        if attribute is not None:
            material.node_tree.links.new(attribute, target)
            return

    # A projected texture has no path either, and it has to come first: the
    # image behind the projection is a perfectly ordinary file, and treating
    # it as one is exactly the wrong result this exists to prevent.
    if texture.get("projection"):
        projected = build_projection(material, texture, warnings)
        if projected is not None:
            material.node_tree.links.new(projected, target)
            return

    # A layered texture has no path of its own, and the layers under it do:
    # measured, the upstream walk used to hand over the bottom layer's file
    # as if it were the whole channel. This has to come before the path check
    # for the same reason the projection does.
    if texture.get("layered"):
        stack = build_layered_texture(
            material, shader, texture, channel, warnings
        )
        if stack is not None:
            if record.get("invert"):
                # Maya transparency reaches opacity through here as well, and
                # the stack has to be inverted whole rather than layer by
                # layer: inverting each one is a different picture.
                invert_node = material.node_tree.nodes.new("ShaderNodeInvert")
                material.node_tree.links.new(
                    stack, invert_node.inputs.get("Color")
                )
                stack = invert_node.outputs.get("Color")
            material.node_tree.links.new(stack, target)
            return

    # A ramp texture has no file to load, so this has to come before the path
    # check or the gradient is skipped and the flat value wins.
    if texture.get("ramp") and not texture.get("path"):
        ramp = build_texture_ramp(material, texture, warnings)
        if ramp is not None:
            material.node_tree.links.new(ramp.outputs["Color"], target)
            return

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
    image_node.name = "ML_{0}_Texture".format(channel)
    image_node.label = channel.replace("_", " ").title()
    image_node.image = image
    _apply_placement(material, image_node, texture_record, warnings)

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
        node.name = "ML_Bump"
        links.new(source, node.inputs.get("Height"))
        if node.inputs.get("Strength") is not None:
            node.inputs["Strength"].default_value = max(0.0, depth)
        links.new(node.outputs.get("Normal"), target)
        return

    normal_map = nodes.new("ShaderNodeNormalMap")
    normal_map.name = "ML_Normal_Map"
    if "object" in interpretation and hasattr(normal_map, "space"):
        try:
            normal_map.space = "OBJECT"
        except Exception:
            pass
    if normal_map.inputs.get("Strength") is not None:
        normal_map.inputs["Strength"].default_value = max(0.0, depth)
    links.new(source, normal_map.inputs.get("Color"))
    links.new(normal_map.outputs.get("Normal"), target)


def _apply_placement(material, image_node, texture_record, warnings=None):
    """Rebuild a place2dTexture as a Mapping node in front of the image.

    Without this a texture tiled four times in Maya arrives tiled once, which
    is a silent and very visible difference.

    The UV source goes in here too, because the two share one Vector input:
    whatever reads the coordinates has to sit behind the placement, not
    replace it.
    """
    placement = (texture_record or {}).get("placement") or {}
    _apply_extension(image_node, placement)
    uv_source = _uv_set_source(material, texture_record, warnings)

    if not placement or _placement_is_identity(placement):
        # Nothing to express; leave the tree uncluttered.
        if uv_source is not None:
            material.node_tree.links.new(
                uv_source, image_node.inputs.get("Vector")
            )
        return

    repeat_u = scalar(placement.get("repeat_u"), 1.0)
    repeat_v = scalar(placement.get("repeat_v"), 1.0)
    offset = placement.get("offset") or [0.0, 0.0]
    rotation = scalar(placement.get("rotate_uv_degrees"), 0.0)

    nodes = material.node_tree.nodes
    links = material.node_tree.links
    mapping = nodes.new("ShaderNodeMapping")
    mapping.name = "ML_Placement"
    mapping.label = "Maya Placement"
    mapping.vector_type = "POINT"
    if uv_source is None:
        coord = nodes.new("ShaderNodeTexCoord")
        coord.name = "ML_Placement_Coord"
        uv_source = coord.outputs.get("UV")

    mapping.inputs["Scale"].default_value = (repeat_u, repeat_v, 1.0)
    mapping.inputs["Location"].default_value = (
        scalar(offset[0] if offset else 0.0, 0.0),
        scalar(offset[1] if len(offset) > 1 else 0.0, 0.0),
        0.0,
    )
    # rotateUV is exported in degrees, which is the unit getAttr reports.
    mapping.inputs["Rotation"].default_value = (0.0, 0.0, math.radians(rotation))

    links.new(uv_source, mapping.inputs.get("Vector"))
    links.new(mapping.outputs.get("Vector"), image_node.inputs.get("Vector"))


def verify_uv_sets(objects, warnings):
    """Report a UV set a material asks for that its mesh does not carry.

    The UV Map node stores a name resolving to nothing without complaint --
    measured on 4.1 and 5.2 -- and renders the default set instead. A set lost
    on the way through the FBX would otherwise look exactly like a texture
    that is merely mapped wrong, which is the hardest kind of wrong to trace.

    Grouped per material and set rather than per object: a scene where four
    hundred meshes share the fault should say so once.
    """
    requested = {}
    reported = set()
    for obj in objects:
        layers = getattr(getattr(obj, "data", None), "uv_layers", None)
        if layers is None:
            continue
        names = set(layer.name for layer in layers)
        for slot in getattr(obj, "material_slots", []):
            material = slot.material
            if material is None or not material.get("ml_generated"):
                continue
            if material.name not in requested:
                requested[material.name] = _requested_uv_sets(material)
            for wanted in requested[material.name]:
                key = (material.name, wanted)
                if wanted in names or key in reported:
                    continue
                reported.add(key)
                warnings.append(
                    'Material "{0}" reads UV set "{1}", which mesh "{2}" does '
                    "not carry; Blender renders its active UV layer "
                    "instead.".format(material.name, wanted, obj.name)
                )
    return warnings


def _requested_uv_sets(material):
    """UV set names the ML_ UV Map nodes of a material ask for."""
    tree = getattr(material, "node_tree", None)
    if tree is None:
        return ()
    found = []
    for node in tree.nodes:
        # A second node in the same tree is suffixed by Blender, so the
        # prefix is what identifies it rather than the whole name.
        if not node.name.startswith(UV_MAP_NODE_NAME):
            continue
        name = getattr(node, "uv_map", "")
        if name and name not in found:
            found.append(name)
    return tuple(found)


def _placement_is_identity(placement):
    """True when a placement asks for nothing the default UVs do not do."""
    offset = placement.get("offset") or [0.0, 0.0]
    return (
        abs(scalar(placement.get("repeat_u"), 1.0) - 1.0) < 1e-6
        and abs(scalar(placement.get("repeat_v"), 1.0) - 1.0) < 1e-6
        and abs(scalar(offset[0] if offset else 0.0, 0.0)) < 1e-6
        and abs(scalar(offset[1] if len(offset) > 1 else 0.0, 0.0)) < 1e-6
        and abs(scalar(placement.get("rotate_uv_degrees"), 0.0)) < 1e-6
    )


def _uv_set_source(material, texture_record, warnings=None):
    """A UV Map node for a texture bound to a non-default UV set, or None.

    The exporter only records a set that differs from the mesh's first one,
    so a record here always means a node is wanted: without it the image
    reads the active layer, which is a different set with the same geometry
    and therefore wrong in a way that looks plausible.
    """
    uv_set = (texture_record or {}).get("uv_set") or {}
    name = uv_set.get("name")
    if not name or not isinstance(name, str):
        return None

    conflict = uv_set.get("conflict") or []
    if conflict and warnings is not None:
        # One material carries one UV source, so this cannot be honoured on
        # both meshes; saying which set was picked beats a silent choice.
        warnings.append(
            'Texture "{0}" reads different UV sets on different meshes '
            "({1}); "
            'used "{2}" for material "{3}".'.format(
                texture_record.get("node") or "?",
                ", ".join(str(entry) for entry in conflict),
                name,
                material.name,
            )
        )

    node = material.node_tree.nodes.new("ShaderNodeUVMap")
    node.name = UV_MAP_NODE_NAME
    node.label = "Maya UV set"
    node.uv_map = name
    node.location = (-1100, -300)
    return node.outputs.get("UV")


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
