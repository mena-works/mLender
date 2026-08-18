# -*- coding: utf-8 -*-
"""Blend shaders, as a material graph of their own.

This is the other half of the hybrid this receiver was designed around. A
Material Instance shares one master and can only change parameters, which is
right for the overwhelming majority of materials and cannot express a stack of
*shaders*: two surfaces with different colours, roughnesses and maps, mixed by
a weight. So a blend shader gets a Material rather than an instance.

Unreal has no shader-level mix -- a material is a set of surface properties,
not a closure -- but it does have the node that mixes exactly those:
``BlendMaterialAttributes``. Each layer becomes a ``MakeMaterialAttributes``
fed from its own channels, and the layers are blended in order. That is the
same intent Maya's mix has, expressed in the terms Unreal actually shades in.

Two Maya sources land here and they are not the same:

* ``aiMixShader`` / ``aiLayerShader`` carry a **mix** weight, which is the
  weight of the upper layer. Measured for the Blender receiver: an unlit red
  under an unlit green at 0.25 renders (0.75, 0.25, 0), so the number is used
  unchanged.
* Maya's own ``layeredShader`` spends **transparency** instead, and its two
  compositing modes spend it differently. ``layer_texture`` fades between the
  layers, which is a blend and is built; ``layer_shaders`` adds the upper
  layer to a scaled copy of what is under it, which is not a blend of surface
  properties at all, and is reported rather than approximated.

The pin names are connected by name and the return value is checked, because a
nonsense pin comes back False here -- so a True means the connection landed.
"""
import unreal

from .constants import (
    ASSET_PREFIX,
    BLEND_MODE_MASKED,
    BLEND_MODE_OPAQUE,
    BLEND_MODE_TRANSLUCENT,
    MATERIAL_CONTENT_PATH,
)
from .images import load_texture
from .utils import channel_texture_path, colour, safe_asset_name, scalar


# Channel -> the pin of MakeMaterialAttributes that holds it. Deliberately
# separate from the master's tables: this graph writes attributes, and the
# names differ from the material property enum.
LAYER_CHANNEL_PINS = {
    "base_color": "BaseColor",
    "roughness": "Roughness",
    "metallic": "Metallic",
    "specular": "Specular",
    "normal": "Normal",
    "emission": "EmissiveColor",
    "opacity": "Opacity",
    "anisotropic": "Anisotropy",
    "subsurface_color": "SubsurfaceColor",
}

COLOUR_PINS = ("BaseColor", "EmissiveColor", "SubsurfaceColor", "Normal")

# Maya layeredShader compositing modes.
MAYA_LAYER_TEXTURE_MODE = "layer_texture"


def _expression(material, class_name, x, y):
    cls = getattr(unreal, class_name, None)
    if cls is None:
        return None
    try:
        return unreal.MaterialEditingLibrary.create_material_expression(
            material, cls, x, y
        )
    except Exception:
        return None


def _connect(source, target, pin):
    """Connect and say whether it landed; a wrong pin name returns False."""
    if source is None or target is None:
        return False
    try:
        return bool(
            unreal.MaterialEditingLibrary.connect_material_expressions(
                source, "", target, pin
            )
        )
    except Exception:
        return False


def _constant_node(material, pin, value, x, y, name):
    """A layer's flat value, as a named parameter rather than a constant.

    A parameter costs nothing extra and leaves the graph adjustable in Unreal,
    which is the point of a lookdev bridge -- and it gives the test something
    to read back by name, which a Constant3Vector does not.
    """
    if pin in COLOUR_PINS:
        node = _expression(material, "MaterialExpressionVectorParameter", x, y)
        if node is None:
            return None
        rgb = colour(value, (0.5, 0.5, 0.5))
        try:
            node.set_editor_property("parameter_name", name)
            node.set_editor_property(
                "default_value", unreal.LinearColor(rgb[0], rgb[1], rgb[2], 1.0)
            )
        except Exception:
            pass
        return node
    node = _expression(material, "MaterialExpressionScalarParameter", x, y)
    if node is None:
        return None
    try:
        node.set_editor_property("parameter_name", name)
        node.set_editor_property("default_value", float(scalar(value, 0.5)))
    except Exception:
        pass
    return node


def _channel_node(material, channel, record, package_folder, x, y, warnings,
                  name):
    """One channel of one layer: its texture if it has one, else its value."""
    pin = LAYER_CHANNEL_PINS.get(channel)
    if pin is None:
        return None, None
    if channel_texture_path(record):
        texture = load_texture(
            record, package_folder, channel,
            channel in ("base_color", "emission", "subsurface_color"),
            warnings,
        )
        if texture is not None:
            sample = _expression(
                material, "MaterialExpressionTextureSample", x, y
            )
            if sample is not None:
                try:
                    sample.set_editor_property("texture", texture)
                except Exception:
                    pass
                return sample, pin
    return (_constant_node(material, pin, (record or {}).get("value"),
                           x, y, name), pin)


def _layer_attributes(material, layer, package_folder, x, y, warnings,
                      index):
    """A MakeMaterialAttributes carrying one layer's surface."""
    attributes = _expression(
        material, "MaterialExpressionMakeMaterialAttributes", x, y
    )
    if attributes is None:
        return None
    row = 0
    for channel, record in sorted((layer.get("channels") or {}).items()):
        if channel not in LAYER_CHANNEL_PINS:
            continue
        node, pin = _channel_node(
            material, channel, record, package_folder,
            x - 350, y - 300 + row * 90, warnings,
            "Layer{0}_{1}".format(index, LAYER_CHANNEL_PINS[channel]),
        )
        if node is None or pin is None:
            continue
        _connect(node, attributes, pin)
        row += 1
    return attributes


def _layer_alpha(material, layer, index, x, y, warnings, label):
    """How much of the upper layer shows, as a node.

    Returns ``None`` when the layer's own mode is not a blend, which is the
    caller's cue to stop rather than to guess.
    """
    compositing = layer.get("compositing")
    if compositing:
        if compositing != MAYA_LAYER_TEXTURE_MODE:
            warnings.append(
                'Material "{0}" is a Maya layeredShader in "{1}" mode, which '
                "adds the upper layer to a scaled copy of what is under it "
                "rather than blending the two. That is not a blend of surface "
                "properties, so the base layer was used on its own.".format(
                    label, compositing
                )
            )
            return None
        transparency = ((layer.get("transparency") or {}).get("value"))
        rgb = colour(transparency, (0.0, 0.0, 0.0))
        # Transparency is how much of the layer *below* shows through, so the
        # upper layer's weight is what is left. Colour transparency is
        # averaged, the same way the Blender receiver does it.
        average = (rgb[0] + rgb[1] + rgb[2]) / 3.0
        weight = 1.0 - average
    else:
        weight = scalar((layer.get("mix") or {}).get("value"), 1.0)

    node = _expression(material, "MaterialExpressionScalarParameter", x, y)
    if node is None:
        return None
    try:
        node.set_editor_property("parameter_name", "Layer{0}".format(index))
        node.set_editor_property("default_value", float(weight))
    except Exception:
        pass
    return node


def _surface_blend(record):
    """Opaque unless a layer says otherwise, read from the layers."""
    for layer in record.get("layers") or []:
        channels = layer.get("channels") or {}
        transmission = scalar(
            (channels.get("transmission") or {}).get("value"), 0.0
        )
        if transmission > 0.0:
            return BLEND_MODE_TRANSLUCENT
        opacity = channels.get("opacity") or {}
        if channel_texture_path(opacity):
            return BLEND_MODE_MASKED
    return BLEND_MODE_OPAQUE


def build_blend_material(record, package_folder, warnings):
    """A Maya blend shader as its own Material, or None if it is not one."""
    layers = [layer for layer in (record.get("layers") or []) if layer]
    if len(layers) < 2:
        return None

    label = safe_asset_name(
        record.get("material") or "Material", "Material"
    )
    name = "{0}{1}".format(ASSET_PREFIX, label)
    path = "{0}/{1}".format(MATERIAL_CONTENT_PATH, name)
    if unreal.EditorAssetLibrary.does_asset_exist(path):
        existing = unreal.EditorAssetLibrary.load_asset(path)
        if isinstance(existing, unreal.Material):
            return existing
        # An earlier send left a Material *Instance* under this name, because
        # the shader was not carried as a graph then. create_asset will not
        # take a name that is in use, so the stale one goes: measured, leaving
        # it made the graph path return None and the material silently fell
        # back to the instance it was meant to replace.
        try:
            unreal.EditorAssetLibrary.delete_asset(path)
        except Exception as exc:
            warnings.append(
                'Blend shader "{0}" could not replace the material already at '
                "{1}: {2}".format(label, path, exc)
            )
            return None

    try:
        material = unreal.AssetToolsHelpers.get_asset_tools().create_asset(
            name, MATERIAL_CONTENT_PATH, unreal.Material,
            unreal.MaterialFactoryNew()
        )
    except Exception as exc:
        warnings.append(
            'Blend shader "{0}" could not be created: {1}'.format(label, exc)
        )
        return None
    if material is None:
        return None

    try:
        material.set_editor_property("use_material_attributes", True)
    except Exception:
        pass
    blend = getattr(unreal.BlendMode, _surface_blend(record), None)
    if blend is not None:
        try:
            material.set_editor_property("blend_mode", blend)
        except Exception:
            pass

    head = _layer_attributes(
        material, layers[0], package_folder, -900, 0, warnings, 0
    )
    if head is None:
        warnings.append(
            'Blend shader "{0}" has no buildable base layer.'.format(label)
        )
        return None

    built = 1
    for index, layer in enumerate(layers[1:], start=1):
        upper = _layer_attributes(
            material, layer, package_folder, -900, 700 * index, warnings, index
        )
        if upper is None:
            continue
        alpha = _layer_alpha(
            material, layer, index, -900, 700 * index + 320, warnings, label
        )
        if alpha is None:
            # The mode is not a blend; stop here rather than inventing one.
            break
        mixer = _expression(
            material, "MaterialExpressionBlendMaterialAttributes",
            -400 + index * 200, 0,
        )
        if mixer is None:
            break
        if not (_connect(head, mixer, "A") and _connect(upper, mixer, "B")):
            break
        _connect(alpha, mixer, "Alpha")
        head = mixer
        built += 1

    prop = getattr(unreal.MaterialProperty, "MP_MATERIAL_ATTRIBUTES", None)
    if prop is None:
        warnings.append(
            'Blend shader "{0}" cannot be wired: this engine has no material '
            "attributes output.".format(label)
        )
        return None
    try:
        unreal.MaterialEditingLibrary.connect_material_property(
            head, "", prop
        )
    except Exception as exc:
        warnings.append(
            'Blend shader "{0}" could not be connected: {1}'.format(label, exc)
        )
        return None

    unreal.MaterialEditingLibrary.recompile_material(material)
    try:
        unreal.EditorAssetLibrary.save_loaded_asset(material, False)
    except Exception:
        pass

    if built < len(layers):
        warnings.append(
            'Blend shader "{0}" carried {1} of its {2} layer(s).'.format(
                label, built, len(layers)
            )
        )
    return material
