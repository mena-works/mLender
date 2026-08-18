# -*- coding: utf-8 -*-
"""Shared constants for the Unreal receiver.

The protocol block must stay identical to the Maya exporter's, byte for byte.
It is duplicated rather than imported because the three packages run in three
different Python runtimes and must not share a file; check_contracts.py is what
keeps them honest.

Everything under "measured" was read off a live Unreal 5.8.1 session or solved
from a probe, never guessed. tests/docs/unreal_calibration.md records how.
"""

BUILD_VERSION = "2.56.0"

TOOL_NAME = "mLender"

LIVELINK_HOST = "127.0.0.1"
LIVELINK_PORT = 50505
LIVELINK_PROTOCOL = "mlender_livelink"
LIVELINK_VERSION = 3
LIVELINK_PACKAGE_EVENT = "scene_package_ready"
LIVELINK_POSE_EVENT = "pose_update"

# The receiver reads the same packages the Blender add-on does, so the list is
# the same one. A package this build cannot read is refused before the level is
# touched, which is why validation runs first in importer.py.
SUPPORTED_SCHEMA_VERSIONS = (
    1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19,
    20, 21, 22, 23, 24, 25, 26, 27, 28, 29, 30, 31, 32, 33, 34, 35, 36,
    37, 38, 39, 40, 41, 42, 43, 44,
)

MAX_MESSAGE_BYTES = 32 * 1024 * 1024
SOCKET_POLL_SECONDS = 0.25

# --------------------------------------------------------------- namespacing
# Generated assets are prefixed so a rebuild can tell its own output from
# whatever the FBX importer left behind, the same job ml_generated does on the
# Blender side. Unreal has no custom properties on an actor, so the marker is
# an actor tag instead.
ASSET_PREFIX = "ML_"
GENERATED_TAG = "mLender"
CONTENT_ROOT = "/Game/mLender"
MESH_CONTENT_PATH = CONTENT_ROOT + "/Meshes"
MATERIAL_CONTENT_PATH = CONTENT_ROOT + "/Materials"
TEXTURE_CONTENT_PATH = CONTENT_ROOT + "/Textures"
SEQUENCE_CONTENT_PATH = CONTENT_ROOT + "/Sequences"
AOV_CONTENT_PATH = CONTENT_ROOT + "/Render"
IES_CONTENT_PATH = CONTENT_ROOT + "/IES"
MASTER_MATERIAL_NAME = ASSET_PREFIX + "Master"
MASTER_MATERIAL_PATH = MATERIAL_CONTENT_PATH + "/" + MASTER_MATERIAL_NAME
# Actor folder paths, Unreal's equivalent of the Blender collections the
# importer builds. Maya group nesting becomes a slash separated folder path.
ACTOR_FOLDER_ROOT = "mLender Import"
LIGHT_FOLDER = ACTOR_FOLDER_ROOT + "/mLender Lights"
CAMERA_FOLDER = ACTOR_FOLDER_ROOT + "/mLender Cameras"

# The Level Sequence that carries light, camera and visibility keys.
ANIMATION_SEQUENCE_NAME = "ML_Sequence"

# The Movie Render Queue config that carries the scene AOVs.
RENDER_CONFIG_NAME = "ML_RenderConfig"

# --------------------------------------------------------------- measured
# Maya Y-up right-handed to Unreal Z-up left-handed is a plain Y/Z swap with no
# sign flip: measured by exporting cubes at (30,0,0), (0,40,0) and (0,0,50) and
# reading the actors Interchange produced, which landed at (30,0,0), (0,0,40)
# and (0,50,0). The handedness flip is absorbed by the swap, which is why this
# is NOT the Blender rule (x, -z, y).
#
# Do not "simplify" this to the Blender conversion. They are different because
# the two hosts are different, and both were measured.
MAYA_TO_UNREAL_AXES = (0, 2, 1)

# 1 Maya centimetre = 1 Unreal unit, measured on the same probe: a cube at
# Maya 30 cm arrived at Unreal 30. Unreal's world unit is a centimetre and
# Interchange applies no scaling of its own, so the FBX needs none either.
#
# The JSON borne records (lights, cameras) are in Maya linear units, so they
# are multiplied by maya_linear_unit -> centimetres to meet the FBX. That is
# meters_per_maya_unit * 100, not meters_per_maya_unit: Unreal is in
# centimetres where Blender is in metres.
UNREAL_UNITS_PER_METRE = 100.0

# Maya lights and cameras look down local -Z with +Y up. Unreal's look down
# local +X with +Z up. The offset is applied in transforms.py.
MAYA_FORWARD_AXIS = "-Z"
UNREAL_FORWARD_AXIS = "+X"

# Luminous efficacy of the ideal photopic radiator, the same constant the
# Blender side divides by to turn lumens into watts. Unreal states light
# intensity in lumens directly, so this multiplies rather than divides.
#
# The chain is therefore: Maya intensity -> flux in watts (the measured pi
# anchor shared with the Blender receiver) -> lumens (x683) -> Unreal.
LUMENS_PER_WATT = 683.0

# Unreal's own conversions, read from
# PointLightComponent.get_units_conversion_factor on 5.8.1 and recorded here
# only as documentation. The receiver does NOT apply them: it sets
# intensity_units to LUMENS and lets the engine convert, so there is one
# authority for the number rather than two.
#
#   CANDELAS -> LUMENS  12.566372  (= 4*pi, the isotropic sphere)
#   LUMENS   -> CANDELAS 0.0795775 (= 1/(4*pi))
#   UNITLESS -> CANDELAS 0.0016    (= 1/625, Unreal's legacy scaling)
#   CANDELAS -> NITS     10000     (cm^2 to m^2)
#
# EV came back with the same factor as CANDELAS, which cannot be right for a
# logarithmic unit; the receiver never asks for EV.
UNREAL_CANDELAS_TO_LUMENS = 12.566371

# A *spawned* point, rect or spot light's component starts at 8.0 CANDELAS.
# Measured, and worth writing down because the class default object reports
# 5000 UNITLESS instead -- so the number a probe reads off the CDO is not the
# number a new actor in a level actually has. That 8.0 is what a light keeps
# when a write silently fails, which is how it was found.
SPAWNED_LIGHT_DEFAULT_CANDELAS = 8.0

# A directional light has no intensity_units property at all: measured, the
# reflection exposes it on point, rect and spot only. Unreal states
# directional intensity in lux, which is what the Sun branch already produces.
DIRECTIONAL_LIGHT_UNIT_IS_LUX = True

# The two calibration tables below are the Blender receiver's, unchanged and
# deliberately so. They convert a renderer's dimensionless intensity into flux
# and its transform scale into an emitting size, and both were measured by
# rendering -- not against Unreal, but against physical units, which is what
# makes them portable to a third host at all.
#
# Do not "recalibrate" these for Unreal. If a light looks wrong in Unreal the
# suspect is this package's use of them, not the numbers: the numbers have a
# rendered measurement behind them and tests/docs/light_calibration.md records
# how to repeat it. Redshift's entry is still an inherited guess because the
# plugin is not installed on this machine.
WATTS_PER_INTENSITY = {
    "arnold": 3.141592653589793,
    "maya": 3.141592653589793,
    "redshift": 10.0,
}

AREA_SIZE_PER_SCALE = {
    "arnold": 2.0,
    "maya": 2.0,
    "redshift": 1.0,
}

# User multiplier over the measured conversion. It scales every light equally,
# so light-to-light ratios are untouched.
DEFAULT_LIGHT_POWER_SCALE = 1.0

# --------------------------------------------------------------- materials
# The channel contract, straight from the exporter. Every key here must exist
# in the exporter's channel tables and every channel the exporter can emit
# must appear in one of the three groups below, or check_contracts.py fails.
#
# Unreal's Material has no clear coat or sheen input reachable from Python:
# MaterialProperty exposes MP_BASE_COLOR, MP_ROUGHNESS, MP_METALLIC,
# MP_SPECULAR, MP_NORMAL, MP_EMISSIVE_COLOR, MP_OPACITY, MP_OPACITY_MASK,
# MP_SUBSURFACE_COLOR, MP_ANISOTROPY, MP_REFRACTION and nothing for coat or
# sheen. Measured twice on 5.8.1. Those channels are therefore metadata, and
# the import says so rather than pretending.
MASTER_SCALAR_PARAMETERS = {
    "coat": "Coat",
    "coat_roughness": "CoatRoughness",
    "roughness": "Roughness",
    "metallic": "Metallic",
    "specular": "Specular",
    "opacity": "Opacity",
    "emission_strength": "EmissiveStrength",
    "ior": "IOR",
    "anisotropic": "Anisotropy",
    "subsurface": "SubsurfaceWeight",
}

MASTER_VECTOR_PARAMETERS = {
    "base_color": "BaseColor",
    "emission": "EmissiveColor",
    "transmission_color": "TransmissionColor",
    "subsurface_color": "SubsurfaceColor",
}

MASTER_TEXTURE_PARAMETERS = {
    "base_color": "BaseColorMap",
    "roughness": "RoughnessMap",
    "metallic": "MetallicMap",
    "specular": "SpecularMap",
    "opacity": "OpacityMap",
    "normal": "NormalMap",
    "emission": "EmissiveMap",
}

# One switch per texture slot, so an instance that has no map keeps the flat
# value instead of multiplying by a black texture.
# The correction stack every texture slot carries, in the order it is applied.
# Only two Maya correction nodes are rebuilt here, and deliberately: these two
# have one meaning each. gammaCorrect is in^(1/gamma) -- measured for the
# Blender receiver, where the same node is in^gamma and the exponent has to be
# inverted -- and clamp is a clamp. A colour correct node carries exposure,
# gain, offset, contrast, saturation and hue at once, and guessing at Arnold's
# composition order would produce a plausible picture that is wrong; it stays
# reported until somebody bakes the measurement the way layeredTexture was.
CORRECTION_GAMMA_SUFFIX = "Gamma"
# Everything aiColorCorrect does after its gamma is affine, so the
# tail folds into one multiply and one add. The order that makes that
# true was measured, not assumed: tests/docs/color_correct.md.
#   A = contrast * 2^exposure * multiply
#   B = pivot * (1 - contrast) * 2^exposure * multiply + add
CORRECTION_SCALE_SUFFIX = "CorrScale"
CORRECTION_OFFSET_SUFFIX = "CorrOffset"
CORRECTION_CLAMP_MIN_SUFFIX = "ClampMin"
CORRECTION_CLAMP_MAX_SUFFIX = "ClampMax"
CORRECTION_CLAMP_SWITCH_SUFFIX = "ClampUse"

# What this build can rebuild. Anything else in a chain is reported, and so is
# a chain that puts these in an order the fixed stack cannot express.
REBUILT_CORRECTIONS = ("gammaCorrect", "clamp",
                       "aiColorCorrect")

MASTER_SWITCH_SUFFIX = "Use"

# Channels with no Unreal input, kept as metadata on the material instance and
# reported. Coat and sheen are here for the reason above, not because they were
# forgotten.
# A channel whose weight is zero changes nothing, so reporting it as lost is
# noise. Measured on the test scene: coat was on in 3 materials of 31 and
# sheen in 2, but coat_ior and sheen_roughness carry their defaults in all 31 --
# so 28 of the 31 warnings were about parameters of an effect nobody switched
# on, and the three real ones were buried in them.
CHANNEL_WEIGHT_GATES = {
    "coat_roughness": "coat",
    "coat_tint": "coat",
    "coat_ior": "coat",
    "coat_darkening": "coat",
    "sheen_roughness": "sheen",
    "sheen_tint": "sheen",
    "subsurface_color": "subsurface",
    "subsurface_radius": "subsurface",
    "subsurface_scale": "subsurface",
    "transmission_roughness": "transmission",
    "thin_walled": "transmission",
    "transmission_affects_alpha": "transmission",
}

# Channels that are wired on one master and metadata on the others. Coat only
# has an Unreal input on a clear coat master, so on any other surface it is
# still something that did not travel and still has to be reported. This set is
# the whole list of channels allowed to sit in both tables -- the contract test
# checks the overlap against it exactly, so a channel that lands in both by
# accident still fails.
CONDITIONAL_CHANNELS = frozenset(("coat", "coat_roughness"))

UNREAL_METADATA_CHANNELS = (
    "transmission",
    "transmission_roughness",
    "thin_walled",
    "transmission_affects_alpha",
    "coat",
    "coat_roughness",
    "coat_tint",
    "coat_ior",
    "coat_darkening",
    "sheen",
    "sheen_roughness",
    "sheen_tint",
    "subsurface_radius",
    "subsurface_scale",
)

# Colour data goes through sRGB, everything else must not. Same split as the
# Blender receiver's Non-Color, and the same trap: a baked map is linear even
# when it drives a colour channel, so bake_records override this.
COLOUR_CHANNELS = ("base_color", "emission", "transmission_color")

# Arnold and Redshift state specular as a 0..1 weight. Unreal's Specular input
# is also 0..1 with 0.5 the dielectric default, so the Blender side's
# SPECULAR_WEIGHT_TO_LEVEL applies here unchanged.
SPECULAR_WEIGHT_TO_LEVEL = 0.5

# Blend mode names come from unreal.BlendMode, probed: BLEND_OPAQUE,
# BLEND_MASKED, BLEND_TRANSLUCENT and friends. The enum is called BlendMode,
# not MaterialBlendMode, which is what a guess would have written.
BLEND_MODE_OPAQUE = "BLEND_OPAQUE"
BLEND_MODE_MASKED = "BLEND_MASKED"
BLEND_MODE_TRANSLUCENT = "BLEND_TRANSLUCENT"

# Below this, an opacity is a cutout rather than a tint, so the material is
# built masked instead of translucent. Translucency in Unreal is markedly more
# expensive and reads differently, so the choice matters.
OPACITY_MASKED_THRESHOLD = 0.999
