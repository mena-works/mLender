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
EXPORT_SCHEMA_VERSION = 2

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
    "metallic": ("metalness",),
    "opacity": ("opacity",),
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
    "metallic": ("baseMetalness", "metalness"),
    "opacity": ("geometryOpacity", "opacity"),
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
    "metallic": ("metalness", "refl_metalness"),
    "opacity": ("opacity_color", "opacity"),
    "normal": ("bump_input", "normalCamera"),
    "emission": ("emission_color", "emission"),
    "emission_strength": ("emission_weight", "emissionWeight"),
}

REDSHIFT_LEGACY_CHANNELS = {
    "base_color": ("diffuse_color", "base_color", "color"),
    "roughness": ("refl_roughness", "reflection_roughness"),
    "metallic": ("refl_metalness", "metalness"),
    "opacity": ("opacity_color", "opacity"),
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

# File path attributes checked while walking a texture network upstream.
TEXTURE_PATH_ATTRS = ("fileTextureName", "tex0", "filename", "file")

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
