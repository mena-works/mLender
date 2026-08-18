# -*- coding: utf-8 -*-
"""Arnold AOVs as a Movie Render Queue configuration.

Render passes in Unreal are not part of a level, they are Movie Render Queue
configuration -- so an AOV cannot be "placed" the way a light can. What this
builds is the config asset the user renders with: a deferred pass, an EXR
output, and one post-process material per AOV that Unreal can actually produce.

The mapping is by **quantity**, not by name, and that is the whole discipline
here. Six of the scene's AOVs name something Unreal writes into its GBuffer and
they carry exactly:

    Z            -> SceneDepth
    N            -> WorldNormal
    albedo       -> BaseColor
    motionvector -> Velocity
    opacity      -> Opacity
    crypto_object-> the ObjectId render pass

The rest name a *light transport* result -- Arnold's ``diffuse`` is the diffuse
lighting response, not the diffuse colour -- and Unreal's GBuffer holds the
surface property instead. ``PPI_DIFFUSE_COLOR`` next to a request for
``diffuse`` looks like a match and is a different image. Those are reported by
name, with what they are, rather than filled with something plausible.

The post-process materials are generated here rather than pulled from
``/Engine/BufferVisualization``: measured, that path lists zero assets in this
build, and a generated material is reviewable in the same way the master
materials are.
"""
import os

import unreal

from .constants import (
    AOV_CONTENT_PATH,
    ASSET_PREFIX,
    GENERATED_TAG,
    RENDER_CONFIG_NAME,
)
from .utils import safe_asset_name


# Arnold AOV name -> the scene texture that holds the same quantity.
AOV_SCENE_TEXTURES = {
    "z": "PPI_SCENE_DEPTH",
    "depth": "PPI_SCENE_DEPTH",
    "zdepth": "PPI_SCENE_DEPTH",
    "n": "PPI_WORLD_NORMAL",
    "normal": "PPI_WORLD_NORMAL",
    "albedo": "PPI_BASE_COLOR",
    "motionvector": "PPI_VELOCITY",
    "motion_vector": "PPI_VELOCITY",
    "opacity": "PPI_OPACITY",
    "roughness": "PPI_ROUGHNESS",
    "metallic": "PPI_METALLIC",
    "ao": "PPI_AMBIENT_OCCLUSION",
    "occlusion": "PPI_AMBIENT_OCCLUSION",
}

# Names that mean a light transport pass rather than a surface property. Unreal
# has a buffer with a similar name for several of these and it is not the same
# image, so each says what it would have been mistaken for.
AOV_TRANSPORT_REASONS = {
    "diffuse": "Arnold's diffuse AOV is the diffuse lighting response; "
               "Unreal's DiffuseColor buffer is the surface colour, which is "
               "a different image",
    "specular": "Arnold's specular AOV is the specular lighting response; "
                "Unreal's SpecularColor buffer is the surface property",
    "sss": "Arnold's sss AOV is the subsurface response; Unreal's "
           "SubsurfaceColor buffer is the surface property",
    "emission": "Unreal's deferred renderer keeps no emissive buffer to read",
    "fuzz": "Unreal has no sheen buffer, and no sheen material input either",
    "coat": "Unreal has no clear coat buffer to read",
}

CRYPTOMATTE_NAMES = ("crypto_object", "crypto_material", "crypto_asset",
                     "cryptomatte")


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


def scene_texture_material(label, texture_id, warnings):
    """A post-process material that writes one GBuffer channel out.

    Post process is a material *domain*, not a setting on an ordinary material,
    and the scene texture goes to Emissive Color because that is the only
    output a post-process material has.
    """
    name = "{0}AOV_{1}".format(ASSET_PREFIX, safe_asset_name(label, "AOV"))
    path = "{0}/{1}".format(AOV_CONTENT_PATH, name)
    if unreal.EditorAssetLibrary.does_asset_exist(path):
        existing = unreal.EditorAssetLibrary.load_asset(path)
        if existing is not None:
            return existing

    try:
        material = unreal.AssetToolsHelpers.get_asset_tools().create_asset(
            name, AOV_CONTENT_PATH, unreal.Material,
            unreal.MaterialFactoryNew()
        )
    except Exception as exc:
        warnings.append(
            'AOV "{0}" needed a post process material and Unreal refused to '
            "create one: {1}".format(label, exc)
        )
        return None
    if material is None:
        return None

    try:
        material.set_editor_property(
            "material_domain", unreal.MaterialDomain.MD_POST_PROCESS
        )
    except Exception:
        pass

    node = _expression(material, "MaterialExpressionSceneTexture", -400, 0)
    if node is None:
        warnings.append(
            'AOV "{0}" could not be built: this engine has no SceneTexture '
            "expression.".format(label)
        )
        return None
    identifier = getattr(unreal.SceneTextureId, texture_id, None)
    if identifier is None:
        warnings.append(
            'AOV "{0}" asked for {1}, which this engine does not have.'.format(
                label, texture_id
            )
        )
        return None
    try:
        node.set_editor_property("scene_texture_id", identifier)
    except Exception as exc:
        warnings.append(
            'AOV "{0}" could not select {1}: {2}'.format(
                label, texture_id, exc
            )
        )
        return None

    library = unreal.MaterialEditingLibrary
    connected = False
    try:
        connected = bool(library.connect_material_property(
            node, "Color", unreal.MaterialProperty.MP_EMISSIVE_COLOR
        ))
    except Exception:
        connected = False
    if not connected:
        warnings.append(
            'AOV "{0}" material was created but its scene texture could not '
            "be connected.".format(label)
        )
    library.recompile_material(material)
    unreal.EditorAssetLibrary.save_loaded_asset(material, False)
    return material


def _output_resolution(package_data):
    render = (package_data or {}).get("render") or {}
    width = render.get("width") or render.get("resolution_width")
    height = render.get("height") or render.get("resolution_height")
    try:
        width = int(width)
        height = int(height)
    except Exception:
        return None
    if width > 0 and height > 0:
        return width, height
    return None


def build_render_config(package_data, sequence_path, warnings):
    """One Movie Render Queue config carrying the scene's AOVs.

    Returns a summary dict. Nothing here renders anything: the config is the
    deliverable, and rendering is the user pressing the button with a sequence
    selected.
    """
    records = list((package_data or {}).get("aovs") or [])
    result = {
        "render_config_path": "",
        "aov_passes": 0,
        "aov_reported": 0,
    }
    if not records:
        return result

    try:
        config = unreal.AssetToolsHelpers.get_asset_tools().create_asset(
            RENDER_CONFIG_NAME, AOV_CONTENT_PATH,
            unreal.MoviePipelinePrimaryConfig,
            unreal.MoviePipelinePrimaryConfigFactory(),
        )
    except Exception as exc:
        warnings.append(
            "The scene carries {0} AOV(s) but the render config could not be "
            "created: {1}".format(len(records), exc)
        )
        return result
    if config is None:
        warnings.append(
            "The scene carries {0} AOV(s) but Unreal returned no render "
            "config asset.".format(len(records))
        )
        return result

    try:
        deferred = config.find_or_add_setting_by_class(
            unreal.MoviePipelineDeferredPassBase
        )
    except Exception as exc:
        warnings.append(
            "The render config has no deferred pass: {0}".format(exc)
        )
        deferred = None

    passes = []
    unmapped = []
    wants_cryptomatte = False
    for record in records:
        label = str((record or {}).get("name") or "").strip()
        key = label.lower()
        if key in CRYPTOMATTE_NAMES or key.startswith("crypto"):
            wants_cryptomatte = True
            continue
        texture_id = AOV_SCENE_TEXTURES.get(key)
        if texture_id is None:
            reason = AOV_TRANSPORT_REASONS.get(key)
            unmapped.append((label, reason))
            continue
        material = scene_texture_material(label, texture_id, warnings)
        if material is None:
            unmapped.append((label, "its post process material failed"))
            continue
        entry = unreal.MoviePipelinePostProcessPass()
        entry.set_editor_property("enabled", True)
        entry.set_editor_property("material", material)
        try:
            entry.set_editor_property("name", label)
        except Exception:
            pass
        try:
            # Depth and velocity are not colours; 8 bits would quantise them
            # into something nobody can composite with.
            entry.set_editor_property("high_precision_output", True)
        except Exception:
            pass
        passes.append(entry)

    if deferred is not None and passes:
        try:
            deferred.set_editor_property(
                "additional_post_process_materials", passes
            )
        except Exception as exc:
            warnings.append(
                "The AOV materials could not be attached to the deferred "
                "pass: {0}".format(exc)
            )
            passes = []

    if wants_cryptomatte:
        try:
            config.find_or_add_setting_by_class(
                unreal.MoviePipelineObjectIdRenderPass
            )
        except Exception as exc:
            unmapped.append(("crypto_object", "the object id pass "
                             "refused to load: {0}".format(exc)))
            wants_cryptomatte = False

    # EXR, because the AOVs arrive as layers of one file rather than a folder
    # of images nobody can keep in step.
    try:
        config.find_or_add_setting_by_class(
            unreal.MoviePipelineImageSequenceOutput_EXR
        )
    except Exception as exc:
        warnings.append("The render config has no EXR output: {0}".format(exc))

    try:
        output = config.find_or_add_setting_by_class(
            unreal.MoviePipelineOutputSetting
        )
    except Exception:
        output = None
    resolution = _output_resolution(package_data)
    if output is not None and resolution:
        try:
            output.set_editor_property(
                "output_resolution",
                unreal.IntPoint(resolution[0], resolution[1]),
            )
        except Exception:
            pass

    try:
        unreal.EditorAssetLibrary.save_loaded_asset(config, False)
    except Exception:
        pass

    if unmapped:
        for label, reason in unmapped:
            warnings.append(
                'AOV "{0}" has no Unreal equivalent this build will fake: '
                "{1}.".format(label, reason or "Unreal writes no such buffer")
            )

    result["render_config_path"] = config.get_path_name()
    result["aov_passes"] = len(passes) + (1 if wants_cryptomatte else 0)
    result["aov_reported"] = len(unmapped)
    if sequence_path:
        result["render_sequence"] = sequence_path
    return result
