# -*- coding: utf-8 -*-
"""Shared constants and Maya/Redshift attribute alias tables.

Attribute names differ between Maya and Redshift versions. Every semantic
channel therefore keeps a tuple of candidate attribute names, ordered by
preference; the first one that exists on the node wins. Extend the tuples to
support a new version instead of adding branching logic elsewhere.
"""
from __future__ import absolute_import


# The build number the UI shows and the package report carries. It lives
# here rather than in __init__ so package.py can reach it without
# importing the package root, which would be circular. The importer keeps
# its own in constants.py for the same reason.
BUILD_VERSION = "2.52.0"

TOOL_NAME = "mLender"
WINDOW_NAME = "mLenderWindow"
PACKAGE_PREFIX = "mLender_"

LIVELINK_HOST = "127.0.0.1"
LIVELINK_PORT = 50505
LIVELINK_PROTOCOL = "mlender_livelink"
LIVELINK_VERSION = 3
# 44: colour sets. A mesh records the sets it carries, and a channel driven
# by an aiUserDataColor records the set it reads instead of being marked an
# unsupported network and collapsing to black.
# 43: as_rig became as_rigs, a list with one namespace-qualified record per
# Advanced Skeleton rig in the scene (referenced rigs live in namespaces).
EXPORT_SCHEMA_VERSION = 44
# LiveLink events. Adding an event is backwards compatible: the importer's
# validator rejects an unknown one with an explicit error rather than acting
# on it, so an old add-on meeting a pose message says so instead of guessing.
LIVELINK_PACKAGE_EVENT = "scene_package_ready"
LIVELINK_POSE_EVENT = "pose_update"

# Advanced Skeleton's own manifest, measured identical across five production
# rigs. The sets are AS's declaration of what is skeleton and what is control;
# the FKIK switchers declare each limb's IK chain as base-name strings, with
# the side coming from the switcher's own suffix.
AS_DEFORM_SET = "DeformSet"
AS_CONTROL_SET = "ControlSet"
AS_FK_PREFIX = "FK"
AS_FKIK_PREFIX = "FKIK"
AS_IK_PREFIX = "IK"
AS_POLE_PREFIX = "Pole"
AS_FKIK_BLEND_ATTR = "FKIKBlend"
AS_FKIK_CHAIN_ATTRS = ("startJoint", "middleJoint", "endJoint")

LIGHT_NODE_TYPES = (
    "RedshiftPhysicalLight",
    "RedshiftDomeLight",
    "RedshiftIESLight",
    "RedshiftPortalLight",
    "RedshiftPhysicalSun",
    "aiAreaLight",
    "aiSkyDomeLight",
    "aiPhotometricLight",
    "aiMeshLight",
    "ambientLight",
    "areaLight",
    "directionalLight",
    "pointLight",
    "spotLight",
    "volumeLight",
)

# Node types whose name contains "light" but which emit nothing, so the
# heuristic shape scan must not turn them into black default area lights.
# Verified against MtoA 5.4.8: aiLightPortal exposes neither color nor
# intensity. Redshift portal lights are deliberately not listed here; they
# carry usable values and have always been exported as area lights.
EXCLUDED_LIGHT_NODE_TYPES = (
    "aiLightPortal",
)

# Arnold spellings below were read from a live MtoA 5.4.8 session, not guessed.
# Note the asymmetry: aiAreaLight and aiPhotometricLight expose "exposure",
# while aiSkyDomeLight, aiMeshLight and Arnold-enhanced native Maya lights only
# expose "aiExposure". Order matters, most specific first.
LIGHT_ATTR_ALIASES = {
    "on": ("on", "lightOn", "enabled"),
    "light_type": ("lightType", "type"),
    "area_shape": ("areaShape", "shape", "aiTranslator"),
    "color": ("color", "lightColor"),
    "color_mode": ("colorMode", "temperatureMode"),
    "temperature": ("temperature", "colorTemperature", "aiColorTemperature"),
    "use_temperature": (
        "useColorTemperature",
        "useTemperature",
        "aiUseColorTemperature",
    ),
    "intensity": ("intensity",),
    "exposure": ("exposure", "exposure0", "aiExposure"),
    "units": ("unitsType", "intensityMode", "units", "intensityUnits"),
    "decay": ("decayType", "decayRate"),
    "normalize": (
        "normalize",
        "normalizeIntensity",
        "areaNormalize",
        "aiNormalize",
    ),
    "spread": ("spread", "areaSpread", "aiSpread"),
    "bidirectional": ("bidirectional", "areaBidirectional"),
    "cone_angle": ("coneAngle", "spotConeAngle"),
    "falloff_angle": (
        "falloffAngle",
        "spotConeFalloffAngle",
        "spotFalloffAngle",
        "penumbraAngle",
    ),
    "falloff_curve": ("falloffCurve", "dropoff"),
    "cast_shadows": (
        "castsShadows",
        "castShadows",
        "useRayTraceShadows",
        "shadow",
    ),
    "shadow_softness": ("shadowSoftness", "lightRadius", "aiRadius"),
    "diffuse": ("diffuse", "diffuseScale"),
    "specular": ("specular", "reflectionScale", "specularScale", "aiSpecular"),
    "volume": ("volumeScale", "volume"),
    "samples": ("samples", "lightSamples", "aiSamples"),
    "ies_profile": (
        "profile",
        "iesProfile",
        "profilePath",
        "iesFile",
        "aiFilename",
    ),
    # aiSkyDomeLight: mirrored_ball : angular : latlong
    "dome_format": ("format",),
}

# Attributes searched for a light color texture and for file-backed light
# resources such as Dome HDRs and IES profiles.
LIGHT_COLOR_TEXTURE_ATTRS = ("color", "lightColor", "tex0", "texture")
LIGHT_DOME_TEXTURE_ATTRS = (
    "tex0",
    "texture",
    "domeTexture",
    "map",
    "mapTexture",
    "color",
)

# Arnold motion blur, read off a live MtoA 5.4.8 session. motion_frames is
# a shutter length in frames, which is what Blender's motion_blur_shutter
# means too, so the two need no conversion.
#
# Redshift is deliberately absent. Its attribute names cannot be probed on
# this machine and this project does not write names it has not read off a
# live session; the same footing as the Redshift light anchor.
# Sets and layers Maya makes for itself. The first two are genuine object
# sets rather than shading engines, so a node type filter does not catch
# them and they have to go by name.
EXCLUDED_SET_NAMES = (
    "defaultObjectSet",
    "defaultLightSet",
    "initialShadingGroup",
    "initialParticleSE",
    "defaultLayer",
)

ARNOLD_MOTION_BLUR_NODE = "defaultArnoldRenderOptions"
ARNOLD_MOTION_BLUR_ENABLED_ATTRS = ("motion_blur_enable",)
ARNOLD_MOTION_BLUR_LENGTH_ATTRS = ("motion_frames",)

# rampShader. Read from a live Maya 2023 node: every ramp is a multi compound
# whose children are <name>_Position, <name>_Color or <name>_FloatValue, and
# <name>_Interp. Entries come back in arbitrary index order and have to be
# sorted by position.
#
# One enum drives them all. There is no transparencyInput or
# incandescenceInput; the single colorInput chooses what every ramp on the
# shader is a function of, and its default is Light Angle, not Facing Angle.
RAMP_SHADER_TYPE = "rampShader"
RAMP_INPUT_ATTR = "colorInput"
RAMP_INPUT_MODES = (
    "Light Angle",
    "Facing Angle",
    "Brightness",
    "Normalized Brightness",
)
RAMP_FACING_MODE = "Facing Angle"
RAMP_INTERP_MODES = ("None", "Linear", "Smooth", "Spline")

# Which ramp feeds which channel. Only the three that land on a real
# Principled socket travel; specularColor, specularRollOff, reflectivity and
# environment have no ramp-shaped equivalent and are left out rather than
# approximated into the wrong input.
RAMP_CHANNEL_ATTRS = (
    ("base_color", "color", False),
    ("emission", "incandescence", False),
    # Maya transparency, so the exporter inverts it into opacity the same way
    # it does for a flat value, and clears the flag so nobody inverts twice.
    ("opacity", "transparency", True),
)

# Measured rather than assumed, with Maya's software renderer because Arnold
# does not evaluate a rampShader at all -- it substitutes a default grey.
# An unlit red-to-blue facing ramp renders blue in the centre and red at the
# rim, so position 1 is facing the camera and position 0 is grazing.
#
# Blender's Layer Weight "Facing" runs the other way and is not linear
# (0.011 facing, 0.221 at the rim on a Blend of 0.5). dot(Normal, Incoming)
# is the cosine itself -- 0.988 facing, 0.771 toward the rim -- so that is
# what the importer builds.
RAMP_FACING_SEMANTIC = "maya_ramp_facing_angle"

# Shape types the coverage scan must not report. Lights and cameras travel
# through the JSON rather than as geometry, so they are accounted for
# elsewhere; an image plane belongs to its camera; a particle instancer's
# output is not a shape the package carries on its own.
COVERAGE_IGNORED_SHAPE_TYPES = (
    "imagePlane",
    "instancer",
    "locator",
)

# Texture projection. A projection node maps an image through a
# place3dTexture rather than through UVs, and the enum below was read from a
# live Maya 2023 node.
#
# Measured, planar, with the tool's own bake as ground truth: the image
# covers the placement's local -0.5..0.5 on both axes, u along +X and v along
# +Y, with no flip. On the Blender side the same picture comes back from a
# Texture Coordinate Object output through a Mapping node rotated -90 degrees
# about X and translated by +0.5; the rotation undoes the Y-up to Z-up
# conversion so the texture space is Maya's again, and +90 degrees is
# vertically flipped.
PROJECTION_NODE_TYPE = "projection"
PROJECTION_TYPE_ATTR = "projType"
PROJECTION_IMAGE_ATTR = "image"
PROJECTION_PLACEMENT_ATTR = "placementMatrix"
PLACEMENT_3D_NODE_TYPE = "place3dTexture"
PROJECTION_TYPES = (
    "Off",
    "Planar",
    "Spherical",
    "Cylindrical",
    "Ball",
    "Cubic",
    "TriPlanar",
    "Concentric",
    "Perspective",
)

# The ramp *texture* node, which is a different thing from a rampShader: a
# gradient wired into any channel. Enum labels and the entry children were
# read from a live Maya 2023 node. Note two differences from rampShader:
# interpolation belongs to the node rather than to each stop, and a freshly
# created node has no entries at all.
RAMP_TEXTURE_TYPE = "ramp"
RAMP_TEXTURE_ENTRIES = "colorEntryList"
RAMP_TEXTURE_TYPES = (
    "V Ramp",
    "U Ramp",
    "Diagonal Ramp",
    "Radial Ramp",
    "Circular Ramp",
    "Box Ramp",
    "UV Ramp",
    "Four Corner Ramp",
    "Tartan Ramp",
)
RAMP_TEXTURE_INTERPOLATIONS = (
    "None",
    "Linear",
    "Exponential Up",
    "Exponential Down",
    "Smooth",
    "Bump",
    "Spike",
)

# layeredTexture. Attribute names and the blendMode enum read off a live Maya
# 2023 node; the enum order below is Maya's own spelling, lowercased.
#
# Index 0 is the **top** layer, which was measured rather than assumed and is
# the reverse of the first guess: a sweep that varied index 1 produced the
# same colour thirty-four times running, because an opaque Over sitting on top
# hides everything below it including the blend mode of what is below.
# Nodes that read a per-vertex colour set into a shading network. Arnold's
# user data nodes name the set in a plain string attribute; the attribute is
# called "attribute" on all of them, read off a live MtoA 5.4.8 session.
#
# Without this a colour-set network is unrepresentable and the channel
# collapses to black: measured, an aiUserDataColor on baseColor exported as
# value [0, 0, 0] with unsupported_network set and no warning anywhere.
# An animation curve is not a shading network. Walking upstream from a keyed
# attribute finds one, and without this it looked like a procedural with no
# file behind it -- so the bake path turned a keyframed roughness into a flat
# texture map, which is a wrong answer that looks deliberate. Measured:
# baked_from named the animCurve node itself.
# What a NURBS or subdivision surface's transform is renamed to while its
# tessellated stand-in borrows its name. Only ever present during an
# export, and put back in a finally.
TESSELLATION_SUFFIX = "_mlOriginal"

# Maya spells a curve-on-surface with an arrow in its DAG path.
CURVE_ON_SURFACE_MARK = "->"

ANIMATION_CURVE_PREFIX = "animCurve"

COLOR_SET_READER_TYPES = (
    "aiUserDataColor",
    "aiUserDataRgb",
)
COLOR_SET_ATTRIBUTE_NAMES = ("attribute", "colorAttrName")

LAYERED_TEXTURE_TYPE = "layeredTexture"
LAYERED_TEXTURE_ENTRIES = "inputs"
LAYERED_BLEND_MODES = (
    "none",
    "over",
    "in",
    "out",
    "add",
    "subtract",
    "multiply",
    "difference",
    "lighten",
    "darken",
    "saturate",
    "desaturate",
    "illuminate",
    "cpv_modulate",
)
LAYERED_DEFAULT_BLEND_MODE = "over"
# A layered texture may hold another one. The limit is a loop guard, not a
# judgement about how deep a lookdev artist should stack.
MAX_LAYERED_DEPTH = 8

# Shaders that blend other shaders rather than describing a surface. Names
# read from a live MtoA 5.4.8 session: aiMixShader has shader1/shader2/mix,
# aiLayerShader has input1..8 with mix1..8, enable1..8 and name1..8.
#
# Measured, not assumed: rendering an unlit red under an unlit green at
# mix 0.25 gives (0.75, 0.25, 0), so mix is the weight of the *upper* shader.
# Blender's Mix Shader Fac runs the same direction, so the number travels
# unchanged rather than being flipped.
MIX_SHADER_TYPE = "aiMixShader"
MIX_SHADER_INPUTS = ("shader1", "shader2")
MIX_SHADER_WEIGHT = "mix"
MIX_SHADER_MODE = "mode"

LAYER_SHADER_TYPE = "aiLayerShader"
LAYER_SHADER_SLOTS = 8

# Maya's own layeredShader. Children read off a live 2023 node: inputs is a
# multi compound of color, transparency and glowColor, and index 0 is the top
# layer as it is on layeredTexture.
#
# Its weight is a transparency -- how much of what is *below* shows through --
# and its two compositing modes use it differently. Both were measured by
# baking an unlit green over an unlit red:
#
#   Layer Shaders   T=0.5 -> (0.5, 1.0, 0)    upper + T * below
#   Layer Texture   T=0.5 -> (0.5, 0.5, 0)    lerp(upper, below, T)
#
# The green staying at 1.0 in the first is the whole difference: that mode
# adds, it does not fade the upper layer out. Layer Shaders is the default.
MAYA_LAYERED_SHADER_TYPE = "layeredShader"
MAYA_LAYERED_SHADER_ENTRIES = "inputs"
MAYA_LAYERED_COMPOSITING_ATTR = "compositingFlag"
MAYA_LAYERED_COMPOSITING_MODES = ("layer_shaders", "layer_texture")

# A blend shader may hold another blend shader. The limit is a loop guard,
# not a judgement about how deep a lookdev artist should go.
MAX_BLEND_DEPTH = 8

SUPPORTED_SHADER_TYPES = (
    MIX_SHADER_TYPE,
    LAYER_SHADER_TYPE,
    MAYA_LAYERED_SHADER_TYPE,
    "RedshiftStandardMaterial",
    "RedshiftMaterial",
    "aiStandardSurface",
    "aiOpenPBRSurface",
    "aiLambert",
    "aiFlat",
    "lambert",
    "blinn",
    "phong",
    "phongE",
    "rampShader",
    "surfaceShader",
)

# Arnold attribute names below were read from a live MtoA 5.4.8 session.
#
# Arnold opacity is real opacity (1 = opaque), unlike Maya's transparency, so
# these channels must never go through the transparency inversion path.
ARNOLD_STANDARD_CHANNELS = {
    "base_color": ("baseColor",),
    "roughness": ("specularRoughness",),
    "specular": ("specular",),
    "metallic": ("metalness",),
    "opacity": ("opacity",),
    "transmission": ("transmission",),
    "transmission_color": ("transmissionColor",),
    "transmission_roughness": ("transmissionExtraRoughness",),
    "ior": ("specularIOR",),
    "thin_walled": ("thinWalled",),
    "anisotropic": ("specularAnisotropy",),
    "coat": ("coat",),
    "coat_roughness": ("coatRoughness",),
    "coat_tint": ("coatColor",),
    "coat_ior": ("coatIOR",),
    "sheen": ("sheen",),
    "sheen_roughness": ("sheenRoughness",),
    "sheen_tint": ("sheenColor",),
    "subsurface": ("subsurface",),
    "subsurface_color": ("subsurfaceColor",),
    "subsurface_radius": ("subsurfaceRadius",),
    "subsurface_scale": ("subsurfaceScale",),
    "normal": ("normalCamera",),
    "emission": ("emissionColor",),
    "emission_strength": ("emission",),
}

# OpenPBR renames three of the seven channels relative to aiStandardSurface:
# metalness -> baseMetalness, opacity -> geometryOpacity (a float, not a
# colour), and the emission weight becomes emissionLuminance, which is a
# photometric value in nits rather than a 0..1 weight.
ARNOLD_OPENPBR_CHANNELS = {
    "base_color": ("baseColor",),
    "roughness": ("specularRoughness",),
    "specular": ("specularWeight", "specular"),
    "metallic": ("baseMetalness", "metalness"),
    "opacity": ("geometryOpacity", "opacity"),
    "transmission": ("transmissionWeight",),
    "transmission_color": ("transmissionColor",),
    "ior": ("specularIOR",),
    "thin_walled": ("geometryThinWalled",),
    "anisotropic": ("specularRoughnessAnisotropy",),
    "coat": ("coatWeight",),
    "coat_roughness": ("coatRoughness",),
    "coat_tint": ("coatColor",),
    "coat_ior": ("coatIOR",),
    # OpenPBR darkens the base under the coat and Principled has no such
    # input, so the importer folds it into the base colour instead.
    "coat_darkening": ("coatDarkening",),
    # OpenPBR calls the sheen lobe fuzz.
    "sheen": ("fuzzWeight",),
    "sheen_roughness": ("fuzzRoughness",),
    "sheen_tint": ("fuzzColor",),
    "subsurface": ("subsurfaceWeight",),
    "subsurface_color": ("subsurfaceColor",),
    "subsurface_radius": ("subsurfaceRadiusScale", "subsurfaceRadius"),
    "normal": ("normalCamera",),
    "emission": ("emissionColor",),
    "emission_strength": ("emissionLuminance",),
}

# aiLambert names its diffuse colour KdColor, and carries opacity rather than
# transparency.
ARNOLD_LAMBERT_CHANNELS = {
    "base_color": ("KdColor", "color"),
    "opacity": ("opacity",),
    "normal": ("normalCamera",),
}

# Marks an emission strength record whose value is a luminance in nits, so the
# importer can scale it instead of feeding it straight into a Blender socket.
OPENPBR_EMISSION_SEMANTIC = "openpbr_emission_luminance"

# OpenPBR scales its metal lobe by the specular weight, so a metal with a
# weight of zero renders black. Standard surface does not, and Principled
# has no equivalent, so the record is tagged and the importer folds the
# weight into the base colour. Measured: reflectance is exactly linear in
# the weight (tests/docs/material_match.md).
OPENPBR_SPECULAR_SEMANTIC = "openpbr_specular_scales_metal"

# aiStandardSurface's sheen roughness is not on the same scale as Blender's.
# OpenPBR's fuzz is: measured against Blender 4.1 and 5.2 it agrees within 2%
# at every roughness, because both follow the same microfiber model. Standard
# surface does not, so only its record is tagged and only it gets remapped.
ARNOLD_SHEEN_ROUGHNESS_SEMANTIC = "arnold_standard_sheen_roughness"

# Reflection roughness is the PBR surface roughness. Redshift's diffuse
# roughness is deliberately not used for Principled BSDF Roughness.
REDSHIFT_STANDARD_CHANNELS = {
    "base_color": ("base_color", "baseColor", "diffuse_color", "color"),
    "roughness": ("refl_roughness", "reflection_roughness", "specular_roughness"),
    "specular": ("refl_weight", "reflection_weight"),
    "metallic": ("metalness", "refl_metalness"),
    "opacity": ("opacity_color", "opacity"),
    "transmission": ("refr_weight", "transmission_weight"),
    "transmission_color": ("refr_color", "transmission_color"),
    "transmission_roughness": ("refr_roughness", "transmission_roughness"),
    "ior": ("refl_ior", "refr_ior", "ior"),
    "thin_walled": ("refr_thin_walled", "thin_walled"),
    "transmission_affects_alpha": ("affects_alpha",),
    "anisotropic": ("refl_aniso", "anisotropy"),
    "coat": ("coat_weight", "coating_weight"),
    "coat_roughness": ("coat_roughness", "coating_roughness"),
    "coat_tint": ("coat_color", "coating_transmittance"),
    "coat_ior": ("coat_ior", "coating_ior"),
    "sheen": ("sheen_weight",),
    "sheen_roughness": ("sheen_roughness",),
    "sheen_tint": ("sheen_color",),
    "subsurface": ("ms_amount", "sss_amount"),
    "subsurface_color": ("ms_color", "sss_color"),
    "subsurface_radius": ("ms_radius", "sss_radius"),
    "normal": ("bump_input", "normalCamera"),
    "emission": ("emission_color", "emission"),
    "emission_strength": ("emission_weight", "emissionWeight"),
}

REDSHIFT_LEGACY_CHANNELS = {
    "base_color": ("diffuse_color", "base_color", "color"),
    "roughness": ("refl_roughness", "reflection_roughness"),
    "specular": ("refl_weight", "reflection_weight"),
    "metallic": ("refl_metalness", "metalness"),
    "opacity": ("opacity_color", "opacity"),
    "transmission": ("refr_weight", "transmission_weight"),
    "transmission_color": ("refr_color", "transmission_color"),
    "transmission_roughness": ("refr_roughness", "transmission_roughness"),
    "ior": ("refr_ior", "refl_ior", "ior"),
    "thin_walled": ("refr_thin_walled", "thin_walled"),
    "transmission_affects_alpha": ("affects_alpha",),
    "normal": ("bump_input", "normalCamera"),
    "emission": ("emission_color", "emission"),
    "emission_strength": ("emission_weight", "emissionWeight"),
}

# Redshift flags that mark the roughness input as glossiness.
REDSHIFT_GLOSSINESS_FLAGS = (
    "refl_isGlossiness",
    "refl_is_glossiness",
    "refl_roughness_isGlossiness",
    "refl_convertFromGlossiness",
    "refl_convert_from_glossiness",
)

# UDIM. Maya's uvTilingMode 3 is the UDIM mode and tiles are numbered from
# 1001, which is what separates a tile number from a version number in a file
# name. The token pattern covers the spellings different tools write.
UDIM_TOKEN = "<UDIM>"
UDIM_TOKEN_PATTERN = r"(?i)(<udim>|%\(udim\)d|\$udim|\{udim\})"
UDIM_TILING_MODE = 3
UDIM_FIRST_TILE = 1001

# File path attributes checked while walking a texture network upstream.
TEXTURE_PATH_ATTRS = ("fileTextureName", "tex0", "filename", "file")

# place2dTexture, read from a live Maya 2023 node. rotateUV and rotateFrame
# are doubleAngle attributes, so getAttr hands them back in the current angular
# unit, which is degrees by default. They are exported as degrees and named so.
PLACEMENT_NODE_TYPE = "place2dTexture"
PLACEMENT_NUMERIC_ATTRS = {
    "repeat_u": "repeatU",
    "repeat_v": "repeatV",
    "offset": "offset",
    "rotate_uv_degrees": "rotateUV",
    "rotate_frame_degrees": "rotateFrame",
    "translate_frame": "translateFrame",
    "coverage": "coverage",
    "wrap_u": "wrapU",
    "wrap_v": "wrapV",
    "mirror_u": "mirrorU",
    "mirror_v": "mirrorV",
    "stagger": "stagger",
    "noise_u": "noiseU",
    "noise_v": "noiseV",
}

# UV sets. Maya keeps the names on an indexed attribute of the mesh shape, and
# ``uvLink`` answers in exactly this form -- measured, not guessed:
# "probeCubeShape.uvSet[1].uvSetName". It answers for an unlinked texture too,
# naming index 0, so a plug on its own does not mean a non-default set.
UV_SET_NAME_PLUG = "{0}.uvSet[{1}].uvSetName"
DEFAULT_UV_SET_INDEX = 0

# Shapes that stand in for a file rather than carrying geometry. Names read
# off live Maya 2023 nodes: the path is "dso" on a standin and
# "cacheFileName" on a gpuCache, which is one idea under two names and so a
# table rather than a branch.
#
# Measured: Min/MaxBoundingBox is filled in by the viewport, not the DG, so a
# headless export reads its plus-minus-one default and exactWorldBoundingBox
# answers zero. The bounds travel as what Maya draws, not as a claim about
# what is in the file.
STANDIN_NODE_TYPES = {
    "aiStandIn": {
        "path": ("dso",),
        "object_path": ("objectPath",),
        "bounds_min": ("MinBoundingBox",),
        "bounds_max": ("MaxBoundingBox",),
        "frame": ("frameNumber",),
        "frame_offset": ("frameOffset",),
        "use_frame_extension": ("useFrameExtension",),
    },
    "gpuCache": {
        "path": ("cacheFileName",),
        "object_path": ("cacheGeomPath",),
        "bounds_min": ("boundingBoxMin",),
        "bounds_max": ("boundingBoxMax",),
        "frame": (),
        "frame_offset": (),
        "use_frame_extension": (),
    },
}

# Texture collection. Off by default: pointing at the Maya paths is right when
# both applications run on the same machine and avoids duplicating a texture
# library, but it breaks the moment the package moves.
COLLECT_FOLDER_NAME = "textures_collected"
# Volumes and standins are referenced files too, and collecting used to walk
# straight past them: measured, a package built with collecting on carried its
# texture and left the VDB and the Alembic proxy outside. They go in their own
# folder rather than among the textures, because they are not textures and a
# user looking for one should not have to know that.
FILE_COLLECT_FOLDER_NAME = "files_collected"

# Colour management. Flag names read from a live Maya 2023 session, where the
# defaults are the ACES config: renderingSpaceName "ACEScg" and
# viewTransformName "ACES 1.0 SDR-video (sRGB)".
#
# The config path comes back with a <MAYA_RESOURCES> token rather than expanded,
# so it is resolved before it goes in the package; the importer only has the
# string to work with.
COLOR_MANAGEMENT_FLAGS = {
    "enabled": "cmEnabled",
    "config_enabled": "cmConfigFileEnabled",
    "config_path": "configFilePath",
    "rendering_space": "renderingSpaceName",
    "view_transform": "viewTransformName",
    "view_name": "viewName",
    "display": "displayName",
    "output_transform": "outputTransformName",
    "output_transform_enabled": "outputTransformEnabled",
}
MAYA_RESOURCES_TOKEN = "<MAYA_RESOURCES>"

# Visibility and render flags, read from a live Maya 2023 / MtoA 5.4.8 mesh.
#
# Arnold splits ray visibility more finely than Maya does and reads its own
# ai* attributes; the plain Maya ones are what the other renderers read. Both
# are listed so a scene authored for either resolves, Arnold's first.
#
# Every one of these defaults to on, so a mesh that says nothing is fully
# visible and no flag is written for it.
MESH_VISIBILITY_ATTRS = {
    "camera": ("primaryVisibility",),
    "shadow": ("castsShadows",),
    "diffuse": ("aiVisibleInDiffuseReflection", "visibleInReflections"),
    "glossy": ("aiVisibleInSpecularReflection", "visibleInReflections"),
    "transmission": (
        "aiVisibleInSpecularTransmission",
        "visibleInRefractions",
    ),
    "volume_scatter": ("aiVisibleInVolume",),
    "receive_shadows": ("receiveShadows",),
    "self_shadows": ("aiSelfShadows",),
    "opaque": ("aiOpaque",),
    # aiMatte is Arnold's holdout; Maya's own holdOut means the same thing.
    "matte": ("aiMatte", "holdOut"),
}

# Read from the transform rather than the shape.
TRANSFORM_VISIBILITY_ATTRS = {
    "visible": ("visibility",),
    "lod_visible": ("lodVisibility",),
}

# Animation.
#
# Meshes travel as animation baked into the FBX, which is what the FBX exchange
# is for and what carries deformers correctly. Lights and cameras are rebuilt
# from JSON instead, so their animation has to be sampled here.
#
# currentTimeUnitToFPS was probed on Maya 2023 and returns exact rates,
# including the NTSC fractions, so it is preferred. The table is the fallback
# for builds where the MEL global is missing.
TIME_UNIT_FPS = {
    "game": 15.0,
    "film": 24.0,
    "pal": 25.0,
    "ntsc": 30.0,
    "show": 48.0,
    "palf": 50.0,
    "ntscf": 60.0,
    "23.976fps": 24000.0 / 1001.0,
    "29.97fps": 30000.0 / 1001.0,
    "59.94fps": 60000.0 / 1001.0,
}
DEFAULT_FPS = 24.0

# A guard, not a preference. Sampling every light and camera over a very long
# range writes a large JSON and takes real time, so the range is clamped and
# the package says it was clamped rather than quietly shipping less.
MAX_ANIMATION_FRAMES = 2000

# Alembic. The base type catches every deformer -- cluster, lattice, wrap,
# skinCluster, blendShape -- which is the point: what matters is that the
# points move, not what moves them.
ALEMBIC_EXPORT_PLUGIN = "AbcExport"
DEFORMER_NODE_TYPE = "geometryFilter"
ALEMBIC_FILE_SUFFIX = "_cache.abc"

# uvWrite and writeUVSets so a cached mesh keeps the UVs the FBX would have
# carried; worldSpace is deliberately absent, so the transform stays on the
# object rather than being folded into the points.
ALEMBIC_EXPORT_FLAGS = (
    "-uvWrite",
    "-writeUVSets",
    "-writeVisibility",
    "-dataFormat ogawa",
)

# A particle bake writes three numbers per point per frame, and the live link
# refuses a message over 32 MB, so a dense simulation would fail as a transfer
# rather than as a bake. Past this many point frames the snapshot travels
# alone and the package says so.
MAX_PARTICLE_BAKE_POINTS = 500000

# Scalars worth sampling per frame. Anything else on a light or camera is
# lookdev state that does not animate in practice.
ANIMATED_CAMERA_ATTRS = {
    "focal_length_mm": "focalLength",
    "focus_distance": "focusDistance",
    "f_stop": "fStop",
    "orthographic_width": "orthographicWidth",
}

# Displacement, read from a live Maya 2023 / MtoA 5.4.8 session.
#
# It hangs off the shadingEngine, not the surface shader: aiStandardSurface has
# no displacement attribute at all. Two wirings are both valid and both turn up
# in real scenes, so both are handled: a displacementShader node in between, or
# a texture wired straight into the engine plug.
DISPLACEMENT_ENGINE_PLUG = "displacementShader"
DISPLACEMENT_NODE_TYPES = ("displacementShader",)
DISPLACEMENT_NODE_INPUT = "displacement"
DISPLACEMENT_NODE_SCALE = "scale"
DISPLACEMENT_NODE_VECTOR = "vectorDisplacement"
DISPLACEMENT_MODE_ATTR = "displacementMode"
DISPLACEMENT_SPACE_ATTR = "vectorSpace"

# Measured enums. displacementMode is the authoritative flag for vector
# displacement, and it carries the space, so the separate vectorSpace is
# only the fallback for a network that set it the older way.
DISPLACEMENT_MODES = {
    0: "scalar",
    1: "vector_tangent",
    2: "vector_object",
    3: "vector_world",
}
DISPLACEMENT_SPACES = {
    0: "world",
    1: "object",
    2: "tangent",
}

# Mesh level Arnold settings. The height is the multiplier and the zero value
# is the map level that means "no displacement", which is exactly what
# Blender's Displacement node calls Midlevel.
DISPLACEMENT_MESH_ATTRS = {
    "height": ("aiDispHeight",),
    "zero_value": ("aiDispZeroValue",),
    "padding": ("aiDispPadding",),
    "autobump": ("aiDispAutobump",),
}

# Redshift is not installed on the development machine, so these names come
# from its documentation rather than from a probe. They are read defensively
# and simply miss if a build spells them differently.
DISPLACEMENT_REDSHIFT_ENABLE = ("rsEnableDisplacement", "rsEnableDisp")
DISPLACEMENT_REDSHIFT_SCALE = ("rsDisplacementScale", "rsDispScale")

# Correction nodes sitting between a texture and a shader input. Both the
# attribute names and the maths behind them were measured on Maya 2023 with
# MtoA 5.4.8, by driving an unlit aiFlat and rendering it; see
# tests/docs/correction_nodes.md for the numbers.
#
# Two of the measurements contradict the obvious reading, so they are stated
# here rather than left to the importer to rediscover:
#   gamma      is applied as pow(input, 1/gamma), not pow(input, gamma)
#   hueShift   is in turns (0..1), not degrees
#
# The order the values are applied in is part of the contract and is not the
# order they appear in the attribute editor:
#   gamma, hue, saturation, contrast, exposure, multiply, add, invert, mask
CORRECTION_NODE_ATTRS = {
    "aiColorCorrect": {
        "gamma": "gamma",
        "hue_shift": "hueShift",
        "saturation": "saturation",
        "contrast": "contrast",
        "contrast_pivot": "contrastPivot",
        "exposure": "exposure",
        "multiply": "multiply",
        "add": "add",
        "invert": "invert",
        "mask": "mask",
    },
    "gammaCorrect": {
        "gamma": "gamma",
    },
    "aiRange": {
        "input_min": "inputMin",
        "input_max": "inputMax",
        "output_min": "outputMin",
        "output_max": "outputMax",
        "smoothstep": "smoothstep",
        "contrast": "contrast",
        "contrast_pivot": "contrastPivot",
        "bias": "bias",
        "gain": "gain",
    },
    # Unconditional 1 - input, so it carries no parameters of its own.
    "reverse": {},
    "aiMultiply": {},
    "aiAdd": {},
    "clamp": {
        "clamp_min": "min",
        "clamp_max": "max",
    },
    "blendColors": {
        "blender": "blender",
    },
    "multiplyDivide": {
        "operation": "operation",
    },
    "remapValue": {
        "input_min": "inputMin",
        "input_max": "inputMax",
        "output_min": "outputMin",
        "output_max": "outputMax",
    },
}

# multiplyDivide's operation enum, measured: No operation:Multiply:Divide:Power.
# Power has no Mix blend type, so it is reported rather than approximated.
MULTIPLY_DIVIDE_OPERATIONS = {
    0: "none",
    1: "multiply",
    2: "divide",
    3: "power",
}

# remapValue keeps its curve in a ramp array. Measured on Maya 2023: each entry
# carries a position, a float value and its own interpolation, and a fresh node
# already holds two entries, (0, 0) and (1, 1).
REMAP_RAMP_ATTR = "value"
REMAP_RAMP_CHILDREN = {
    "position": "value_Position",
    "value": "value_FloatValue",
    "interpolation": "value_Interp",
}
# value_Interp enum, measured: None:Linear:Smooth:Spline.
REMAP_INTERPOLATIONS = {
    0: "none",
    1: "linear",
    2: "smooth",
    3: "spline",
}

# Nodes taking two interchangeable inputs, where which one holds the constant
# depends on how the network was wired. The free input is the operand.
#
# blendColors is here too, and its blend is the reverse of Blender's: measured,
# Maya's blender of 1 returns color1 while Blender's Factor of 1 returns the
# second colour.
CORRECTION_OPERAND_INPUTS = {
    "aiMultiply": ("multiply", ("input1", "input2")),
    "aiAdd": ("add", ("input1", "input2")),
    "multiplyDivide": ("operand", ("input1", "input2")),
    "blendColors": ("other_color", ("color1", "color2")),
}

# Which of the two inputs the upstream texture actually arrived on. blendColors
# is not symmetric, so rebuilding it needs to know which side is which.
CORRECTION_CONNECTED_INPUTS = {
    "blendColors": ("connected_input", ("color1", "color2")),
}

# Nodes that legitimately appear in a texture chain and carry no correction of
# their own. Anything else found there is reported to the importer so a value
# that silently fails to survive the transfer is at least visible.
CORRECTION_IGNORED_NODE_TYPES = (
    "file",
    "place2dTexture",
    "place3dTexture",
    "uvChooser",
    "bump2d",
    "shadingEngine",
    "displacementShader",
    "defaultColorMgtGlobals",
)

# bump2d sits between a texture and normalCamera and carries the strength that
# would otherwise be lost when the walk steps past it to reach the file.
BUMP_NODE_TYPES = ("bump2d",)
BUMP_DEPTH_ATTR = "bumpDepth"
BUMP_INTERP_ATTR = "bumpInterp"  # Bump : Tangent Space Normals : Object Space

# Procedural baking. Measured on Maya 2023: convertSolidTx writes linear
# values whatever the colour management setting, and it cannot write EXR (the
# file node appears but nothing lands on disk), so the format list is short.
BAKE_FILE_FORMAT = "png"
# Measured: -backgroundMode takes "shader" or "color" and nothing else. This
# used to read "black", which Maya answered with "Wrong argument to
# -backgroundMode, using 'shader' mode" and then ignored -- so the constant
# named one behaviour and the bakes had always used the other. Spelling the
# real one keeps the bakes identical and stops the constant lying.
BAKE_BACKGROUND_MODE = "shader"
BAKE_SEMANTIC = "baked_procedural"
DEFAULT_BAKE_RESOLUTION = 1024
MAX_BAKE_RESOLUTION = 8192
BAKE_FOLDER_NAME = "textures"

# Channels whose network drives a single value rather than a colour, so the
# bake is taken from the alpha output rather than the colour output.
SCALAR_BAKE_CHANNELS = (
    "roughness",
    "metallic",
    "specular",
    "opacity",
    "transmission",
    "transmission_roughness",
    "emission_strength",
)

# Cameras. Names and units measured on a live Maya 2023 camera: the film back
# is stated in inches (1.41732 in is the 36 mm full frame width) and the clip
# planes, focus distance and orthographic width are in scene linear units.
CAMERA_INCHES_TO_MM = 25.4
CAMERA_FILM_FIT_ATTR = "filmFit"  # Fill : Horizontal : Vertical : Overscan
CAMERA_NUMERIC_ATTRS = {
    "focal_length": "focalLength",
    "film_aperture_horizontal": "horizontalFilmAperture",
    "film_aperture_vertical": "verticalFilmAperture",
    "film_offset_horizontal": "horizontalFilmOffset",
    "film_offset_vertical": "verticalFilmOffset",
    "near_clip": "nearClipPlane",
    "far_clip": "farClipPlane",
    "orthographic": "orthographic",
    "orthographic_width": "orthographicWidth",
    "depth_of_field": "depthOfField",
    "f_stop": "fStop",
    "focus_distance": "focusDistance",
    "lens_squeeze": "lensSqueezeRatio",
}

# Subdivision. Attribute names read from a live Maya 2023 / MtoA 5.4.8 mesh.
#
# Nothing is subdivided unless the Maya mesh actually asks for it. Arnold
# defaults aiSubdivType to "none", so blanket subdivision would turn a cube
# into a ball that was never modelled that way.
#
# Sources are checked in this order, because a renderer setting is what
# actually renders and Maya's smooth preview is the fallback intent.
SUBDIV_ARNOLD_TYPE = "aiSubdivType"
SUBDIV_ARNOLD_ITERATIONS = "aiSubdivIterations"
SUBDIV_ARNOLD_UV_SMOOTHING = "aiSubdivUvSmoothing"

# Redshift is not installed on the development machine, so these names come
# from its documentation rather than from a probe. They are read defensively
# and simply miss if a build spells them differently.
SUBDIV_REDSHIFT_ENABLE = ("rsEnableSubdivision", "rsEnableSubdiv")
SUBDIV_REDSHIFT_ITERATIONS = ("rsMaxTessellationSubdivs", "rsScreenSpaceAdaptive")

# Maya's own smooth mesh preview, which is always Catmull-Clark.
SUBDIV_MAYA_DISPLAY = "displaySmoothMesh"
SUBDIV_MAYA_VIEWPORT_LEVEL = "smoothLevel"
SUBDIV_MAYA_RENDER_LEVEL = "renderSmoothLevel"
SUBDIV_MAYA_USE_PREVIEW_FOR_RENDER = "useSmoothPreviewForRender"

# Blender only has Catmull-Clark and Simple, so Arnold's linear maps to Simple.
SUBDIV_SCHEME_CATMULL_CLARK = "CATMULL_CLARK"
SUBDIV_SCHEME_LINEAR = "LINEAR"

MAX_SUBDIV_ITERATIONS = 6

# Dielectric default, used when a shader exposes no IOR attribute.
DEFAULT_IOR = 1.5

# Principled roughness approximations for Maya's non-PBR shaders. Lambert has
# no gloss control at all, so it keeps a constant; the others expose one and it
# is now read instead of guessed. A fixed value ignored what the artist set:
# every blinn arrived at 0.1 whatever its eccentricity said.
LAMBERT_ROUGHNESS = 0.7
BLINN_ROUGHNESS = 0.1
FALLBACK_ROUGHNESS = 0.5

# Attribute names read from a live Maya 2023 session, with their defaults:
# blinn eccentricity 0.3, phong cosinePower 20.0, phongE roughness 0.5.
# phong has no eccentricity and phongE has no cosinePower, so this is a table
# rather than one alias tuple.
NATIVE_ROUGHNESS_ATTRS = {
    "blinn": ("eccentricity",),
    "phong": ("cosinePower",),
    "phongE": ("roughness",),
    "rampShader": ("eccentricity",),
}

# Attributes whose value is a Phong exponent rather than a 0..1 roughness.
# The conversion is the standard one between a Phong lobe and a microfacet
# roughness, r = sqrt(2 / (n + 2)); it is analytic, not a render measurement,
# and cosinePower 20 lands at 0.30.
PHONG_EXPONENT_ATTRS = ("cosinePower",)

METERS_PER_LINEAR_UNIT = {
    "mm": 0.001,
    "cm": 0.01,
    "m": 1.0,
    "km": 1000.0,
    "in": 0.0254,
    "ft": 0.3048,
    "yd": 0.9144,
    "mi": 1609.344,
}
