# -*- coding: utf-8 -*-
"""Rebuild Maya colour correction nodes as Blender shader nodes.

The exporter walks upstream from a shader input to find the texture behind it
and records the correction nodes it stepped over on the way. This module puts
them back, so a texture that was gamma corrected and tinted in Maya arrives
that way in Blender instead of raw.

Every conversion here was measured rather than reasoned about, because the
conventions disagree in ways that are easy to get backwards:

    Maya and Arnold   out = pow(in, 1 / gamma)
    Blender Gamma     out = pow(in, gamma)

    Arnold hueShift   turns, 0 is no change
    Blender Hue       offset, 0.5 is no change

    Arnold contrast   out = c * (in - pivot) + pivot
    Blender B/C       out = max((1 + C) * in + (B - C / 2), 0)

The Arnold values were read out of renders through an unlit shader and the
Blender ones out of renders of a node chain driving the world background; both
sets are in tests/docs/correction_nodes.md. The contrast mapping below reproduces
Arnold's measured pixel exactly.

Sockets are addressed by index, not by name: "Fac" became "Factor" and "Bright"
became "Brightness" between 4.1 and 5.2, while the positions stayed put.
"""

import math

from .constants import (
    ARNOLD_CONTRAST_PIVOT,
    CORRECTION_EPSILON,
    CORRECTION_NODE_SPACING,
    RAMP_INTERPOLATIONS,
)
from .utils import scalar


def apply_corrections(material, output, texture_record, warnings):
    """Rebuild a texture's correction chain, returning the corrected socket.

    Returns the socket handed in when there is nothing to rebuild, so callers
    can use the result unconditionally.
    """
    record = texture_record or {}
    for entry in record.get("corrections") or []:
        kind = entry.get("type")
        builder = CORRECTION_BUILDERS.get(kind)
        if builder is None:
            continue
        try:
            output = builder(material, output, entry.get("parameters") or {},
                             warnings)
        except Exception as error:
            # One unbuildable correction must not cost the whole material.
            warnings.append(
                'Could not rebuild the "{0}" correction node "{1}": {2}'.format(
                    kind, entry.get("node") or "", error
                )
            )

    for entry in record.get("unsupported_corrections") or []:
        warnings.append(
            'Correction node "{0}" ({1}) has no Blender equivalent, so the '
            "texture is used without it.".format(
                entry.get("node") or "", entry.get("node_type") or ""
            )
        )
    return output


def _chain_node(material, output, bl_idname, name):
    """Add a node to the right of whatever currently feeds the chain."""
    node = material.node_tree.nodes.new(bl_idname)
    node.name = name
    node.label = name.replace("ZA_", "").replace("_", " ")
    source = output.node
    node.location = (
        source.location.x + CORRECTION_NODE_SPACING,
        source.location.y,
    )
    return node


def _rgb(value, default):
    """Three components, unclamped: a multiply of 2 is a legitimate value."""
    if isinstance(value, (list, tuple)):
        components = [float(item) for item in value[:3]]
    else:
        try:
            components = [float(value)] * 3
        except (TypeError, ValueError):
            components = [float(default)] * 3
    while len(components) < 3:
        components.append(components[-1] if components else float(default))
    return components


def _mix_rgb(material, output, blend_type, color, name):
    node = _chain_node(material, output, "ShaderNodeMixRGB", name)
    node.blend_type = blend_type
    node.inputs[0].default_value = 1.0
    node.inputs[2].default_value = (color[0], color[1], color[2], 1.0)
    material.node_tree.links.new(output, node.inputs[1])
    return node.outputs[0]


def _apply_gamma(material, output, gamma):
    if gamma <= 0.0 or abs(gamma - 1.0) <= CORRECTION_EPSILON:
        return output
    node = _chain_node(material, output, "ShaderNodeGamma", "ZA_CC_Gamma")
    # Maya raises to 1/gamma, Blender's node raises to gamma.
    node.inputs[1].default_value = 1.0 / gamma
    material.node_tree.links.new(output, node.inputs[0])
    return node.outputs[0]


def _apply_hue_saturation(material, output, hue, saturation):
    if (abs(hue) <= CORRECTION_EPSILON
            and abs(saturation - 1.0) <= CORRECTION_EPSILON):
        return output
    node = _chain_node(
        material, output, "ShaderNodeHueSaturation", "ZA_CC_Hue_Saturation"
    )
    # Arnold shifts by a number of turns; Blender offsets from a neutral 0.5.
    # Both wrap, and both multiply saturation and clamp it at one, which was
    # confirmed by rendering the same colour through each.
    node.inputs[0].default_value = (0.5 + hue) % 1.0
    node.inputs[1].default_value = max(0.0, saturation)
    node.inputs[2].default_value = 1.0
    node.inputs[3].default_value = 1.0
    material.node_tree.links.new(output, node.inputs[4])
    return node.outputs[0]


def _apply_contrast(material, output, contrast, pivot):
    if abs(contrast - 1.0) <= CORRECTION_EPSILON:
        return output
    node = _chain_node(
        material, output, "ShaderNodeBrightContrast", "ZA_CC_Contrast"
    )
    # Solving Arnold's c*(in - pivot) + pivot against Blender's
    # (1 + C)*in + (B - C/2) gives these two. Blender additionally clamps the
    # result at zero, which Arnold does not.
    node.inputs[1].default_value = (1.0 - contrast) * (pivot - 0.5)
    node.inputs[2].default_value = contrast - 1.0
    material.node_tree.links.new(output, node.inputs[0])
    return node.outputs[0]


def _apply_scale_and_offset(material, output, exposure, multiply, add):
    # Exposure and multiply are both pure scales and adjacent in the order, so
    # they fold into one node rather than two.
    scale = math.pow(2.0, exposure)
    multiply = [component * scale for component in multiply]
    if any(abs(c - 1.0) > CORRECTION_EPSILON for c in multiply):
        output = _mix_rgb(
            material, output, "MULTIPLY", multiply, "ZA_CC_Multiply"
        )
    if any(abs(c) > CORRECTION_EPSILON for c in add):
        output = _mix_rgb(material, output, "ADD", add, "ZA_CC_Add")
    return output


def _apply_invert(material, output, name):
    node = _chain_node(material, output, "ShaderNodeInvert", name)
    node.inputs[0].default_value = 1.0
    material.node_tree.links.new(output, node.inputs[1])
    return node.outputs[0]


def _build_color_correct(material, output, params, warnings):
    """aiColorCorrect, in the measured order of operations."""
    source = output
    output = _apply_gamma(material, output, scalar(params.get("gamma"), 1.0))
    output = _apply_hue_saturation(
        material,
        output,
        scalar(params.get("hue_shift"), 0.0),
        scalar(params.get("saturation"), 1.0),
    )
    output = _apply_contrast(
        material,
        output,
        scalar(params.get("contrast"), 1.0),
        scalar(params.get("contrast_pivot"), ARNOLD_CONTRAST_PIVOT),
    )
    output = _apply_scale_and_offset(
        material,
        output,
        scalar(params.get("exposure"), 0.0),
        _rgb(params.get("multiply"), 1.0),
        _rgb(params.get("add"), 0.0),
    )
    if params.get("invert"):
        output = _apply_invert(material, output, "ZA_CC_Invert")

    # The mask blends the corrected result back against the untouched input,
    # so it is only meaningful once something above actually built a node.
    mask = scalar(params.get("mask"), 1.0)
    if abs(mask - 1.0) > CORRECTION_EPSILON and output is not source:
        node = _chain_node(material, output, "ShaderNodeMixRGB", "ZA_CC_Mask")
        node.blend_type = "MIX"
        node.inputs[0].default_value = max(0.0, min(1.0, mask))
        material.node_tree.links.new(source, node.inputs[1])
        material.node_tree.links.new(output, node.inputs[2])
        output = node.outputs[0]
    return output


def _build_gamma_correct(material, output, params, warnings):
    components = _rgb(params.get("gamma"), 1.0)
    if max(components) - min(components) > CORRECTION_EPSILON:
        warnings.append(
            "gammaCorrect carries a per-channel gamma, but Blender's Gamma "
            "node takes a single value, so the red channel's was used."
        )
    return _apply_gamma(material, output, components[0])


def _build_multiply(material, output, params, warnings):
    multiply = _rgb(params.get("multiply"), 1.0)
    if all(abs(c - 1.0) <= CORRECTION_EPSILON for c in multiply):
        return output
    return _mix_rgb(material, output, "MULTIPLY", multiply, "ZA_Multiply")


def _build_add(material, output, params, warnings):
    add = _rgb(params.get("add"), 0.0)
    if all(abs(c) <= CORRECTION_EPSILON for c in add):
        return output
    return _mix_rgb(material, output, "ADD", add, "ZA_Add")


def _build_reverse(material, output, params, warnings):
    return _apply_invert(material, output, "ZA_Reverse")


def _build_range(material, output, params, warnings):
    """aiRange, as a linear remap plus its contrast.

    The remap collapses into one multiply and one add, because
    (in - inMin) / span * outSpan + outMin is in * gain + offset.
    """
    input_min = scalar(params.get("input_min"), 0.0)
    input_max = scalar(params.get("input_max"), 1.0)
    output_min = scalar(params.get("output_min"), 0.0)
    output_max = scalar(params.get("output_max"), 1.0)

    span = input_max - input_min
    if abs(span) > CORRECTION_EPSILON:
        gain = (output_max - output_min) / span
        offset = output_min - input_min * gain
        if abs(gain - 1.0) > CORRECTION_EPSILON:
            output = _mix_rgb(
                material, output, "MULTIPLY", [gain] * 3, "ZA_Range_Scale"
            )
        if abs(offset) > CORRECTION_EPSILON:
            output = _mix_rgb(
                material, output, "ADD", [offset] * 3, "ZA_Range_Offset"
            )

    output = _apply_contrast(
        material,
        output,
        scalar(params.get("contrast"), 1.0),
        # aiRange pivots on 0.5, unlike aiColorCorrect's 0.18.
        scalar(params.get("contrast_pivot"), 0.5),
    )

    if params.get("smoothstep"):
        warnings.append(
            "aiRange smoothstep was not rebuilt; the remap is linear."
        )
    for key in ("bias", "gain"):
        if abs(scalar(params.get(key), 0.5) - 0.5) > CORRECTION_EPSILON:
            warnings.append(
                'aiRange "{0}" was not rebuilt.'.format(key)
            )
    return output


def _build_clamp(material, output, params, warnings):
    """Maya's clamp, as a max against the floor then a min against the ceiling.

    Mix's LIGHTEN is a per-channel max and DARKEN a per-channel min, so the
    pair is exactly a clamp and needs no Separate/Combine detour.

    A freshly made clamp node has both bounds at zero, which really does clamp
    everything to black in Maya. That is reproduced rather than second-guessed.
    """
    low = _rgb(params.get("clamp_min"), 0.0)
    high = _rgb(params.get("clamp_max"), 0.0)
    if any(abs(c) > CORRECTION_EPSILON for c in low):
        output = _mix_rgb(material, output, "LIGHTEN", low, "ZA_Clamp_Min")
    output = _mix_rgb(material, output, "DARKEN", high, "ZA_Clamp_Max")
    return output


def _build_blend_colors(material, output, params, warnings):
    """blendColors, with Maya's blend the reverse of Blender's.

    Measured on both sides: Maya's blender of 1 returns color1, while Blender's
    Factor of 1 returns the second colour. The factor is therefore inverted,
    and which side the texture arrived on decides which slot it takes.
    """
    blend = scalar(params.get("blender"), 0.5)
    other = _rgb(params.get("other_color"), 0.0)
    connected = str(params.get("connected_input") or "color1")

    node = _chain_node(material, output, "ShaderNodeMixRGB", "ZA_Blend_Colors")
    node.blend_type = "MIX"
    if connected == "color2":
        # The texture is Maya's color2, which is the side blender fades out.
        node.inputs[0].default_value = max(0.0, min(1.0, blend))
        node.inputs[1].default_value = (other[0], other[1], other[2], 1.0)
        material.node_tree.links.new(output, node.inputs[2])
    else:
        node.inputs[0].default_value = max(0.0, min(1.0, 1.0 - blend))
        material.node_tree.links.new(output, node.inputs[1])
        node.inputs[2].default_value = (other[0], other[1], other[2], 1.0)
    return node.outputs[0]


def _build_multiply_divide(material, output, params, warnings):
    """multiplyDivide, for the two operations Mix can express."""
    operation = str(params.get("operation_name") or "none")
    operand = _rgb(params.get("operand"), 1.0)
    if operation == "none":
        return output
    if operation == "multiply":
        if all(abs(c - 1.0) <= CORRECTION_EPSILON for c in operand):
            return output
        return _mix_rgb(material, output, "MULTIPLY", operand, "ZA_Multiply")
    if operation == "divide":
        return _mix_rgb(material, output, "DIVIDE", operand, "ZA_Divide")
    warnings.append(
        'multiplyDivide "{0}" was not rebuilt; Mix has no such blend '
        "type.".format(operation)
    )
    return output


def _build_remap_value(material, output, params, warnings):
    """remapValue, curve included, as a Map Range into a Colour Ramp.

    The ramp is the point of the node. Rebuilding only the linear part, which
    is all the previous version could do, silently dropped whatever curve the
    artist actually drew.

    Maya states interpolation per stop and Blender states it once for the whole
    ramp, so the first stop's setting is used and a mixed ramp is reported.
    """
    input_min = scalar(params.get("input_min"), 0.0)
    input_max = scalar(params.get("input_max"), 1.0)
    output_min = scalar(params.get("output_min"), 0.0)
    output_max = scalar(params.get("output_max"), 1.0)
    stops = params.get("ramp") or []

    # Normalise into the ramp's 0..1 domain first.
    span = input_max - input_min
    if abs(span) > CORRECTION_EPSILON and (
        abs(input_min) > CORRECTION_EPSILON
        or abs(input_max - 1.0) > CORRECTION_EPSILON
    ):
        gain = 1.0 / span
        output = _mix_rgb(
            material, output, "MULTIPLY", [gain] * 3, "ZA_Remap_Normalise"
        )
        offset = -input_min * gain
        if abs(offset) > CORRECTION_EPSILON:
            output = _mix_rgb(
                material, output, "ADD", [offset] * 3, "ZA_Remap_Offset"
            )

    if _ramp_is_meaningful(stops):
        output = _build_ramp(material, output, stops, warnings)

    out_span = output_max - output_min
    if abs(out_span - 1.0) > CORRECTION_EPSILON:
        output = _mix_rgb(
            material, output, "MULTIPLY", [out_span] * 3, "ZA_Remap_Scale"
        )
    if abs(output_min) > CORRECTION_EPSILON:
        output = _mix_rgb(
            material, output, "ADD", [output_min] * 3, "ZA_Remap_Output"
        )
    return output


def _ramp_is_meaningful(stops):
    """Whether a ramp does anything a straight line would not.

    A fresh remapValue holds (0, 0) and (1, 1), which is the identity; building
    a Colour Ramp for it would only clutter the tree.
    """
    if len(stops) < 2:
        return False
    for stop in stops:
        position = scalar(stop.get("position"), 0.0)
        value = scalar(stop.get("value"), 0.0)
        if abs(position - value) > 1e-4:
            return True
    return len(stops) > 2


def _build_ramp(material, output, stops, warnings):
    node = _chain_node(material, output, "ShaderNodeValToRGB", "ZA_Remap_Ramp")
    ramp = node.color_ramp

    modes = set(str(stop.get("interpolation") or "linear") for stop in stops)
    if len(modes) > 1:
        warnings.append(
            "remapValue stops use more than one interpolation ({0}); Blender "
            "sets it once for the whole ramp, so the first was used.".format(
                ", ".join(sorted(modes))
            )
        )
    interpolation = RAMP_INTERPOLATIONS.get(
        str(stops[0].get("interpolation") or "linear"), "LINEAR"
    )
    try:
        ramp.interpolation = interpolation
    except Exception:
        pass

    # A new ramp already holds two elements and the first cannot be removed,
    # so they are reused and the rest appended.
    while len(ramp.elements) > len(stops):
        ramp.elements.remove(ramp.elements[-1])
    while len(ramp.elements) < len(stops):
        ramp.elements.new(1.0)

    for element, stop in zip(ramp.elements, stops):
        value = scalar(stop.get("value"), 0.0)
        element.position = max(0.0, min(1.0, scalar(stop.get("position"), 0.0)))
        element.color = (value, value, value, 1.0)

    material.node_tree.links.new(output, node.inputs[0])
    return node.outputs[0]


CORRECTION_BUILDERS = {
    "aiColorCorrect": _build_color_correct,
    "gammaCorrect": _build_gamma_correct,
    "aiMultiply": _build_multiply,
    "aiAdd": _build_add,
    "reverse": _build_reverse,
    "aiRange": _build_range,
    "clamp": _build_clamp,
    "blendColors": _build_blend_colors,
    "multiplyDivide": _build_multiply_divide,
    "remapValue": _build_remap_value,
}
