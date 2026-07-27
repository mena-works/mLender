# -*- coding: utf-8 -*-
"""Shared constants and Maya/Redshift attribute alias tables.

Attribute names differ between Maya and Redshift versions. Every semantic
channel therefore keeps a tuple of candidate attribute names, ordered by
preference; the first one that exists on the node wins. Extend the tuples to
support a new version instead of adding branching logic elsewhere.
"""
from __future__ import absolute_import


TOOL_NAME = "Z-A Exporter - Lookdev"
WINDOW_NAME = "zaLookdevExporterWindow"
PACKAGE_PREFIX = "MTB_Z_A_"

LIVELINK_HOST = "127.0.0.1"
LIVELINK_PORT = 50505
LIVELINK_PROTOCOL = "za_lookdev_livelink"
LIVELINK_VERSION = 1
EXPORT_SCHEMA_VERSION = 14

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

SUPPORTED_SHADER_TYPES = (
    "RedshiftStandardMaterial",
    "RedshiftMaterial",
    "aiStandardSurface",
    "aiOpenPBRSurface",
    "aiLambert",
    "aiFlat",
    "lambert",
    "blinn",
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
}

# aiMultiply and aiAdd take two interchangeable inputs, so which one holds the
# constant depends on how the network was wired. The free input is the operand.
CORRECTION_OPERAND_INPUTS = {
    "aiMultiply": ("multiply", ("input1", "input2")),
    "aiAdd": ("add", ("input1", "input2")),
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
BAKE_BACKGROUND_MODE = "black"
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

# Principled roughness approximations for Maya's non-PBR shaders.
LAMBERT_ROUGHNESS = 0.7
BLINN_ROUGHNESS = 0.1
FALLBACK_ROUGHNESS = 0.5

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
