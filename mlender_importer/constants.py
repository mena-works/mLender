# -*- coding: utf-8 -*-
"""Shared constants for the Blender importer.

The LIVELINK_* values are a contract with the Maya exporter and must stay
identical on both sides. Bump LIVELINK_VERSION in both files together when the
message shape changes.
"""

import math

BUILD_VERSION = "2.33.0"

LIVELINK_HOST = "127.0.0.1"
LIVELINK_PORT = 50505
LIVELINK_PROTOCOL = "mlender_livelink"
LIVELINK_VERSION = 3
LIVELINK_EVENT = "scene_package_ready"
# The pose bridge's event. Kept beside LIVELINK_EVENT rather than replacing
# it: the name LIVELINK_EVENT is part of the module's surface and the package
# flow still validates against it.
LIVELINK_POSE_EVENT = "pose_update"

# Package JSON schema versions this build knows how to read. The import wipes
# the scene, so an unreadable package must be rejected before anything is lost.
# 3 added glass channels and 4 added UDIM on the main branch; 5 is this
# branch with both, plus the Arnold channels.
SUPPORTED_SCHEMA_VERSIONS = (
    1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19,
    20, 21, 22, 23, 24, 25, 26, 27, 28, 29, 30, 31, 32, 33, 34, 35, 36,
    37, 38, 39, 40, 41, 42,
)

# rampShader. The mode name the exporter writes when Maya's single colorInput
# enum is set to the one a Blender shader graph can actually reproduce.
RAMP_FACING_MODE = "Facing Angle"

# Maya keeps an interpolation per ramp stop; Blender keeps one per ramp, so
# the first stop's decides. "None" is a hard step, which is CONSTANT here.
RAMP_INTERPOLATION = {
    "None": "CONSTANT",
    "Linear": "LINEAR",
    "Smooth": "EASE",
    "Spline": "B_SPLINE",
}

# Maya projection types this build can rebuild, and what they become. Only
# Planar is here: it is the one that was measured, and each of the others
# needs its own measurement before it can be claimed. Anything absent falls
# back to Bake Procedurals, which evaluates the projection correctly.
# Both are read through a FLAT image: Planar feeds it the placement's local
# X and Y directly, Spherical feeds it a longitude and latitude built from
# Math nodes. Blender's own SPHERE projection is a different mapping and was
# measured and rejected -- see tests/docs/projection_calibration.md.
PROJECTION_MODES = {
    "Planar": "FLAT",
    "Spherical": "FLAT",
    "Cylindrical": "FLAT",
    "TriPlanar": "FLAT",
    "Perspective": "FLAT",
}

# How the image behaves outside the projection, which is not the same for
# every type and was measured for each. A planar projection clamps at its
# extent: REPEAT scored 0.50 against Maya's bake, CLIP 0.36, EXTEND 0.03. A
# cylindrical one wraps, because its half turn goes round the object twice:
# EXTEND scored 0.22 and REPEAT 0.02.
PROJECTION_EXTENSIONS = {
    "Planar": "EXTEND",
    "Spherical": "EXTEND",
    "Cylindrical": "REPEAT",
    "TriPlanar": "EXTEND",
    # A perspective divide sends most of the surface outside the image, and
    # Maya tiles there: measured, REPEAT 0.08 against EXTEND 0.19.
    "Perspective": "REPEAT",
}

# How hard the triplanar blend picks its face. Measured against Maya's bake:
# 1 gives 0.13, 4 gives 0.07, 16 gives 0.036, 64 gives 0.024 and 128 gives
# 0.022 -- and 256 jumps back to 0.042 because the weights underflow. 64 is
# taken rather than the best number, to sit away from that cliff.
TRIPLANAR_SHARPNESS = 64.0

# Maya's triplanar reads a different pair of axes per face. Read off its own
# bake: the dominant axis names the face, and the pairs are these.
TRIPLANAR_FACES = (
    ("Z", "X", "Y"),
    ("X", "Z", "Y"),
    ("Y", "X", "Z"),
)
PROJECTION_DEFAULT_EXTENSION = "EXTEND"

# Measured with the tool's own bake as ground truth. Maya's planar projection
# covers the placement's local -0.5..0.5 with u along +X and v along +Y, so
# the Mapping node moves the origin by half. The -90 degrees about X undoes
# the Y-up to Z-up conversion that Texture Coordinate's Object output has
# already applied, putting the texture back in Maya's space; +90 renders
# vertically flipped and 0 has no vertical variation at all.
PROJECTION_MAPPING_ROTATION = (-math.pi / 2.0, 0.0, 0.0)
PROJECTION_MAPPING_OFFSET = (0.5, 0.5, 0.0)

# Which UV component drives a Maya ramp texture. Measured by baking a
# red-to-blue ramp and reading the image: a V Ramp puts position 0 at v=0 and
# a U Ramp puts it at u=0, so neither is inverted. The other seven types are
# shapes one Color Ramp cannot make and are deliberately absent, which is what
# sends them back to the bake instead of arriving wrong.
RAMP_TEXTURE_COMPONENTS = {
    "U Ramp": "X",
    "V Ramp": "Y",
}

# A ramp texture keeps one interpolation on the node. Only three of Maya's
# seven have a Color Ramp equivalent; the rest fall back to linear.
RAMP_TEXTURE_INTERPOLATION = {
    "None": "CONSTANT",
    "Linear": "LINEAR",
    "Smooth": "EASE",
}

# The key the exporter writes the cache filename under.
ALEMBIC_FILE_KEY = "file"

MAX_MESSAGE_BYTES = 32 * 1024 * 1024
SOCKET_POLL_SECONDS = 0.5
TIMER_INTERVAL_SECONDS = 0.1

ROOT_COLLECTION_NAME = "mLender Import"
LIGHT_COLLECTION_NAME = "mLender Lights"
CAMERA_COLLECTION_NAME = "mLender Cameras"
# Import modes. Replace is the original behaviour and stays the default:
# it is what makes the Maya scene the single source of truth.
# Everything the tool writes onto a datablock starts with this. A Maya
# user attribute of the same shape is refused rather than allowed to
# overwrite a marker the import depends on.
# Maya offers five image plane fit modes against Blender's three. Fill
# crops the overflow and To Size stretches; the rest are closest to fit.
# The Maya value is kept on the camera so the approximation is visible.
IMAGE_PLANE_FIT = {
    "Fill": "CROP",
    "Best": "FIT",
    "Horizontal": "FIT",
    "Vertical": "FIT",
    "To Size": "STRETCH",
}
# Maya's None display mode means the plane is there but not drawn.
IMAGE_PLANE_HIDDEN_MODE = "None"

PROPERTY_PREFIX = "ml_"

IMPORT_MODE_REPLACE = "REPLACE"
IMPORT_MODE_MERGE = "MERGE"
IMPORT_MODE_ADD = "ADD"

# Marks an object a previous import made that the current package no
# longer has. Marked and counted, never deleted without being asked.
STALE_PROPERTY = "ml_stale"

SET_COLLECTION_NAME = "mLender Sets"
LAYER_COLLECTION_NAME = "mLender Layers"

# Maya display type: 0 normal, 1 template, 2 reference. In both of the
# latter Maya means the objects are not to be grabbed, which is
# hide_select in Blender.
MAYA_DISPLAY_TYPE_NORMAL = 0

# Maya filmFit onto Blender sensor_fit. Overscan has no Blender equivalent and
# frames like Fill, so both fall back to AUTO.
CAMERA_SENSOR_FIT = {
    "fill": "AUTO",
    "horizontal": "HORIZONTAL",
    "vertical": "VERTICAL",
    "overscan": "AUTO",
}
# Maya locators read as axes; a null used purely as a folder or control
# reads better as plain axes too, but at a smaller size so a scene full of
# controls does not drown the geometry.
# Maya curve form: 0 open, 1 closed, 2 periodic. Both of the latter close
# the loop, so only the open case gets endpoint knots.
CURVE_FORM_OPEN = 0

EMPTY_DISPLAY_TYPES = {
    "locator": "PLAIN_AXES",
    "group": "PLAIN_AXES",
}
EMPTY_DISPLAY_SIZE = 0.25

SUBDIVISION_MODIFIER_NAME = "mLender Subdivision"

# Principled BSDF socket names per channel. Later Blender versions renamed
# some sockets, so each channel lists the names to try in order.
PRINCIPLED_INPUTS = {
    "base_color": ("Base Color",),
    "roughness": ("Roughness",),
    "specular": ("Specular IOR Level", "Specular"),
    "metallic": ("Metallic",),
    # Arnold's specularIOR drives the specular Fresnel, and so does
    # Principled's IOR. It used to be listed only under GLASS_INPUTS,
    # so every non refractive material silently kept Blender's 1.45
    # default however the Maya shader was set.
    "ior": ("IOR",),
    "opacity": ("Alpha",),
    "normal": ("Normal",),
    "emission": ("Emission Color", "Emission"),
    "emission_strength": ("Emission Strength",),
    "anisotropic": ("Anisotropic",),
    "coat": ("Coat Weight", "Clearcoat"),
    "coat_roughness": ("Coat Roughness", "Clearcoat Roughness"),
    "coat_tint": ("Coat Tint",),
    "coat_ior": ("Coat IOR",),
    "sheen": ("Sheen Weight", "Sheen"),
    "sheen_roughness": ("Sheen Roughness",),
    "sheen_tint": ("Sheen Tint",),
    "subsurface": ("Subsurface Weight", "Subsurface"),
    "subsurface_radius": ("Subsurface Radius",),
    "subsurface_scale": ("Subsurface Scale",),
}

# Channels whose value is a colour rather than a scalar, wherever they
# land. Kept separate from COLOR_CHANNELS, which is about colour space.
COLOUR_VALUED_CHANNELS = (
    "base_color",
    "emission",
    "transmission_color",
    "coat_tint",
    "sheen_tint",
    "subsurface_radius",
)

# Of those, the ones that are not reflectances and so must not be clamped to
# one. Measured: an emission colour of 50 in Maya arrived in Blender as 1, so
# every bright emissive material was silently flattened.
#
# Base colour and the tints stay clamped on purpose. An albedo above one is
# unphysical and Principled misbehaves when given it.
UNCLAMPED_COLOUR_CHANNELS = (
    "emission",
    # A distance in scene units, not a colour at all.
    "subsurface_radius",
)

# Maya wrap and mirror flags onto the image node's extension mode.
TEXTURE_EXTENSION_MIRROR = "MIRROR"
TEXTURE_EXTENSION_REPEAT = "REPEAT"
TEXTURE_EXTENSION_CLAMP = "EXTEND"

# UV sets. Measured on 4.1 and 5.2: the FBX importer keeps Maya's UV set names
# exactly and in order, so the name the exporter read in Maya goes straight
# into the node. Index 0 arrives active and active_render, which is why only a
# non-default set gets a node at all.
#
# The node accepts a name no mesh carries without complaint -- measured, it
# stores the string and renders the default set -- so a name that resolves to
# nothing has to be reported here rather than seen.
UV_MAP_NODE_NAME = "ML_UVMap"

# layeredTexture. Measured by baking every mode in Maya 2023 -- 0.2 over 0.6,
# because the first sweep used 0.8 over 0.4 where |a-b|, min(a,b) and the
# backdrop are all 0.4 and Difference, Darken and "did nothing" were the same
# number. A colour pair was baked too, which ruled out a luminance-only
# operation: all of these work per channel.
#
# Every mode below computes lerp(lower, f(lower, upper), alpha), which is
# exactly Blender's Mix node with the layer's alpha on Fac. Six of Maya's
# fourteen are missing on purpose:
#
#   in, out       alpha compositing against the backdrop, not a colour blend
#   saturate, desaturate, illuminate   HSV-space operations with no Mix
#                                      equivalent; measured and left out
#                                      rather than approximated
#   cpv_modulate  needs colour per vertex, which is not in the package
LAYERED_BLEND_TYPES = {
    "over": "MIX",
    "add": "ADD",
    "subtract": "SUBTRACT",
    "multiply": "MULTIPLY",
    "difference": "DIFFERENCE",
    "lighten": "LIGHTEN",
    "darken": "DARKEN",
}
# Measured: "None" ignores its alpha and replaces everything under it.
LAYERED_REPLACE_MODE = "none"
# Spelled out rather than left as "whatever is not in the table", so the
# contract check can prove every mode Maya has is accounted for one way or
# the other. A mode added to the exporter and forgotten here fails the check
# instead of silently becoming a dropped layer.
LAYERED_UNSUPPORTED_MODES = (
    "in",
    "out",
    "saturate",
    "desaturate",
    "illuminate",
    "cpv_modulate",
)
LAYERED_NODE_NAME = "ML_Layer"
# The bottom layer composites against black, so its alpha multiplies its own
# colour: measured 0.8 at alpha 0.5 arriving as 0.4, and at alpha 0 as black.
LAYERED_BOTTOM_COLOUR = (0.0, 0.0, 0.0, 1.0)
# A neutral name for the per-layer wiring, so the channel-specific behaviour
# in apply_record_to_socket keys off the outer channel and not off a layer.
LAYERED_ALPHA_CHANNEL = "layer_alpha"

# Maya's layeredShader. Its weight is a transparency -- how much of what is
# below shows through -- and its two compositing modes spend it differently.
# Measured by baking an unlit green over an unlit red at five transparencies:
#
#   layer_shaders   T=0.5 -> (0.5, 1.0, 0)    upper + T * below
#   layer_texture   T=0.5 -> (0.5, 0.5, 0)    lerp(upper, below, T)
#
# The green holding at 1.0 in the first is the whole difference: that mode
# adds the layers, it does not fade the upper one out. It is also Maya's
# default, so it is not the rare branch.
#
# Neither needs the number inverted. layer_texture puts the upper shader on
# the Mix Shader's first input and the lower on its second, so a factor of T
# reads straight; layer_shaders scales the lower shader by T against a
# Transparent BSDF and adds the result.
MAYA_LAYER_SHADERS_MODE = "layer_shaders"
MAYA_LAYER_TEXTURE_MODE = "layer_texture"

# Standins. What a standin's file can be, and how each format answers the
# question of units -- measured on 4.1 and 5.2, in world space:
#
#   .abc  no unit metadata, so the scale must be supplied
#   .obj  no unit metadata either, and global_scale works: a four unit cube
#         at 0.01 arrives 0.04 across
#   .usd  describes its own units, and the importer's "scale" argument is
#         accepted and then ignored -- the cube arrived four units across
#         whatever was passed. So nothing is passed.
#
# Arnold's own .ass is not here and cannot be: Blender has no reader for it.
STANDIN_ALEMBIC_FORMATS = (".abc",)
STANDIN_OBJ_FORMATS = (".obj",)
STANDIN_USD_FORMATS = (".usd", ".usda", ".usdc", ".usdz")

# The anchor empty is drawn as the box Maya draws in place of the geometry.
# What a standin's file is not allowed to bring with it. The frame range, the
# lights and the cameras all come from the Maya scene through the JSON, and a
# referenced asset may not overrule any of them.
#
# Measured on 4.1 and 5.2 through this tool's own standin import: with the
# operator's defaults a scene set to 1..24 became 40..90, and the asset's own
# SphereLight lit the scene at 9869 on 4.1 and 3141 on 5.2 -- the same file,
# 3.14x apart, and never through light_energy(). Nothing was reported.
USD_IMPORT_REFUSALS = {
    "set_frame_range": False,
    "import_lights": False,
    "import_cameras": False,
}

# Prim types counted when saying what was left out. LightAPI covers the
# modern spelling; the list is the fallback for older stages.
USD_LIGHT_PRIM_TYPES = (
    "SphereLight",
    "RectLight",
    "DiskLight",
    "CylinderLight",
    "DistantLight",
    "DomeLight",
    "GeometryLight",
    "PortalLight",
)
USD_CAMERA_PRIM_TYPE = "Camera"

STANDIN_PLACEHOLDER_DISPLAY = "CUBE"
STANDIN_PLACEHOLDER_SIZE = 0.5

# Where the exporter puts the files it collects. Repeated here rather than
# shared, because the two packages run in different Python runtimes and must
# not import each other -- so these two strings are part of the package
# contract and change on both sides together.
#
# They are searched, along with the package root, whenever a recorded path is
# not on disk. That is what makes a collected package survive being moved: the
# paths inside it are absolute, written by whichever machine did the export.
COLLECTED_FOLDERS = ("textures_collected", "files_collected")

# UDIM. Tiles are numbered from 1001. The token pattern covers the spellings
# different tools write, so a package from any exporter version resolves.
UDIM_TOKEN = "<UDIM>"
UDIM_TOKEN_PATTERN = r"(?i)(<udim>|%\(udim\)d|\$udim|\{udim\})"
UDIM_TILING_MODE = 3
UDIM_FIRST_TILE = 1001

# Glass BSDF socket names per channel, used by the refractive build path.
GLASS_INPUTS = {
    "transmission_color": ("Color",),
    "transmission_roughness": ("Roughness",),
    "ior": ("IOR",),
    "normal": ("Normal",),
}

# Channels that only ever apply on the refractive path, because transmission
# is what selects that path in the first place. Everything else a shader can
# export has to reach the Principled build too.
#
# This list exists because "the importer honours this channel" used to be
# satisfied by the glass path alone: ior sat in GLASS_INPUTS and nowhere else,
# so every non refractive material silently ignored the Maya IOR.
GLASS_ONLY_CHANNELS = (
    "transmission_color",
    "transmission_roughness",
)

# Channels with no socket of their own. They either select the build path or
# survive as custom properties on the material for reference.
METADATA_CHANNELS = (
    "transmission",
    # Principled has no separate subsurface colour socket in 4.x or
    # 5.x; it tints from the base colour. Kept as metadata rather than
    # silently dropped.
    "subsurface_color",
    "thin_walled",
    "transmission_affects_alpha",
    # Has no socket; it is folded into the base colour instead.
    "coat_darkening",
)

# Arnold and Redshift state specular as a 0..1 weight; Blender states it as a
# level where 0.5 is an ordinary dielectric and 0 is no specular at all. So a
# full weight of 1 maps onto Blender's default rather than onto 1.
#
# This matters more than it looks: Principled conserves energy, so leaving the
# level at 0.5 for a shader whose Maya specular was 0 both adds a highlight
# that was never there and steals that energy from the diffuse.
SPECULAR_WEIGHT_TO_LEVEL = 0.5

# Channels that carry colour data; everything else is loaded as Non-Color.
COLOR_CHANNELS = ("base_color", "emission")

# A transmission weight above this switches a material to the Glass BSDF path
# instead of Principled. It also serves as the tolerance for deciding that an
# opacity value is meaningfully below one.
TRANSMISSION_THRESHOLD = 1e-6

# Shaders that are unlit. These are rebuilt as Emission mixed against a
# Transparent BSDF rather than as a Principled surface, which is far closer to
# how they behave in Maya.
UNLIT_SHADER_TYPES = ("surfaceShader", "aiFlat")

# Applied when a shader sent an emission colour but no strength. Blender 3.x
# defaulted this socket to 1.0 and 4.x defaults it to 0.0, which would render
# the same package emissive on one version and black on the other.
DEFAULT_EMISSION_STRENGTH = 1.0

# Only reached when the Coat IOR socket is missing entirely. OpenPBR's own
# default is 1.6, which is also what the darkening was measured against.
DEFAULT_COAT_IOR = 1.6

# Datablock collections cleared before a new package is imported.
PURGED_DATA_COLLECTIONS = (
    "meshes",
    "curves",
    "cameras",
    "lights",
    "worlds",
    "materials",
    "images",
    "textures",
    "actions",
    "armatures",
)

# Subdivision is applied only when the Maya mesh asked for it. Packages older
# than schema 6 carry no subdivision record at all, and those meshes are left
# unsubdivided rather than guessed at.
DEFAULT_SUBDIV_ITERATIONS = 2
MAX_SUBDIV_ITERATIONS = 6

# Arnold's aiSubdivUvSmoothing values mapped onto Blender's uv_smooth enum.
SUBDIV_UV_SMOOTHING = {
    "pin_corners": "PRESERVE_CORNERS",
    "pin_borders": "PRESERVE_BOUNDARIES",
    "linear": "PRESERVE_BOUNDARIES",
    "smooth": "SMOOTH_ALL",
}

# Everything except the type and the levels, which come from the mesh record.
SUBDIVISION_SETTINGS = {
    "subdivision_type": "CATMULL_CLARK",
    "levels": DEFAULT_SUBDIV_ITERATIONS,
    "render_levels": DEFAULT_SUBDIV_ITERATIONS,
    "boundary_smooth": "PRESERVE_CORNERS",
    "use_limit_surface": True,
    "quality": 3,
    "uv_smooth": "PRESERVE_BOUNDARIES",
    "use_creases": True,
    "use_custom_normals": False,
    "show_viewport": True,
    "show_render": True,
}

# Photometric conversions used when a light reports its intensity unit.
LUMENS_PER_WATT = 683.0

# Blender's light Power is total radiant flux. Measured by rendering on 4.1
# and 5.2: with normalize on, a light's brightness does not change when its
# size changes, and builds that predate the normalize property behave the same
# way. With normalize off, brightness scales with area, which is exactly the
# convention Arnold documents (normalized output = C, otherwise C * area).
#
# The importer therefore converts every source light into total flux and lets
# Blender's Power mean flux. Doing the area maths here *and* handing Blender a
# non-normalized light would apply the area twice.
#
# Watts of total radiant flux per unit of a renderer's dimensionless intensity.
#
# Arnold was measured, not guessed. Matched scenes (white Lambertian plane,
# small quad light, orthographic camera) were rendered in Arnold via kick and
# in Cycles, and the ratio solved for. Across five variants spanning distance,
# intensity and exposure the factor came out 3.1412 every time, a spread of
# 6e-5 per cent, which is pi to within render noise.
#
# It is pi for a reason: Arnold's normalized intensity is the radiant intensity
# along the light's normal, and a Lambertian emitter's total flux is pi times
# that. Blender's Power is total flux. So the conversion is exact, not a look
# calibration. Native Maya lights go through MtoA as the same quad_light and
# measured identically, pixel for pixel.
#
# Redshift is the one entry that is still a carried-over guess: the plugin is
# not installed on this machine, so the same measurement could not be run. See
# tests/docs/light_calibration.md for the procedure to settle it.
WATTS_PER_INTENSITY = {
    "arnold": math.pi,
    "maya": math.pi,
    "redshift": 10.0,
}

# How a light's transform scale relates to its emitting size. Measured by
# rendering a camera-visible quad light face on through an orthographic camera
# of known width: a transform scale of 1 produced a 2 unit wide light, because
# Arnold's quad spans -1..1. Native Maya area lights export to the same
# quad_light and measured identically. Redshift is unmeasured, the plugin is
# not installed here, so it keeps the previous one-to-one reading.
AREA_SIZE_PER_SCALE = {
    "arnold": 2.0,
    "maya": 2.0,
    "redshift": 1.0,
}

# User multiplier on top of the conversion above, exposed in the sidebar. It
# scales every light in the package uniformly, so light-to-light ratios are
# unaffected and only overall brightness moves.
DEFAULT_LIGHT_POWER_SCALE = 1.0

# OpenPBR's emissionLuminance is a photometric value in nits, not a 0..1
# weight, so it cannot go straight into a Blender Emission Strength socket.
#
# Measured, having previously been a guess of 100. The material chart rendered
# an OpenPBR surface with emissionLuminance 100 and emissionColor 0.4: Arnold
# produced 0.0404, so the multiplier Arnold applies to the colour is about a
# tenth, not one. Confirmed linear at a second luminance. Blender was ten times
# too bright on every OpenPBR emissive surface until this changed.
OPENPBR_EMISSION_LUMINANCE_SCALE = 1000.0
OPENPBR_EMISSION_SEMANTIC = "openpbr_emission_luminance"

# OpenPBR scales its metal lobe by the specular weight, so a metal with a
# weight of zero renders black. Standard surface does not, and Principled
# has no equivalent, so the record is tagged and the importer folds the
# weight into the base colour. Measured: reflectance is exactly linear in
# the weight (tests/docs/material_match.md).
OPENPBR_SPECULAR_SEMANTIC = "openpbr_specular_scales_metal"

# See the exporter's note: only aiStandardSurface's sheen roughness needs this.
ARNOLD_SHEEN_ROUGHNESS_SEMANTIC = "arnold_standard_sheen_roughness"

# Arnold sheen roughness -> the Blender sheen roughness that renders the same.
# Measured at three viewing angles and two base albedos (0.05 and 0.3); the
# curve came out identical at both albedos, so it is a property of the two
# parameterisations rather than a fit to one material. Blender 4.1 and 5.2
# produce the same curve.
#
# The remap takes the worst disagreement from 91% down to 25%, and that 25%
# is one corner: a very dark base at a grazing angle with almost no sheen
# roughness, where Arnold has a rim Blender cannot produce at any setting.
# Everything else lands within a few per cent. Below 0.05 is extrapolation.
SHEEN_ROUGHNESS_REMAP = (
    (0.00, 0.000),
    (0.05, 0.282),
    (0.20, 0.474),
    (0.40, 0.604),
    (0.60, 0.676),
    (0.80, 0.726),
    (1.00, 0.750),
)

# A light's node tree is a multiplier on top of its energy. Nodes feeding
# Emission Strength must stay at unit scale, otherwise energy is applied twice.
NODE_TREE_UNIT_STRENGTH = 1.0

# Colour management.
#
# Measured on 4.1, 4.5 and 5.2 by trying to set each name: Blender's stock OCIO
# config offers Standard, Raw, Filmic, Filmic Log, False Color and AgX, plus
# Khronos PBR Neutral from 4.5. It has *no* ACES view transform. So a Maya
# scene on the ACES config can only be matched if the user has pointed Blender
# at an ACES config through the OCIO environment variable.
#
# The importer therefore tries the Maya names first, falls back to a rough
# equivalent, and warns plainly when it cannot do what Maya was doing rather
# than leaving AgX in place and pretending.
VIEW_TRANSFORM_FALLBACKS = {
    # Maya's untone-mapped view is Blender's Standard.
    "un-tone-mapped": ("Standard",),
    "raw": ("Raw", "Standard"),
    "log": ("Filmic Log", "AgX Log"),
    "unity neutral tone-map": ("Khronos PBR Neutral", "Standard"),
}

# Tried in order when nothing else matched, so the scene at least gets a
# defined transform rather than whatever the file happened to carry.
DEFAULT_VIEW_TRANSFORM = "Standard"

# Maya display names that mean the same thing as Blender's.
DISPLAY_DEVICE_FALLBACKS = {
    "srgb": ("sRGB",),
    "gamma 2.2 / rec.709": ("sRGB",),
    "rec.1886 / rec.709 video": ("Rec.1886", "sRGB"),
    "dci-p3 d65": ("Display P3", "sRGB"),
    "adobergb": ("sRGB",),
}

# Maya/Arnold ray visibility onto Blender's per-ray object visibility.
# Measured: all of these exist directly on the object in 4.1 and 5.2, not
# under object.cycles. They are Cycles features; EEVEE ignores them.
OBJECT_VISIBILITY_ATTRS = {
    "camera": "visible_camera",
    "diffuse": "visible_diffuse",
    "glossy": "visible_glossy",
    "transmission": "visible_transmission",
    "volume_scatter": "visible_volume_scatter",
    "shadow": "visible_shadow",
}

# Arnold's matte and Maya's holdOut both mean "punch a hole in the render".
HOLDOUT_ATTR = "is_holdout"

# Animation. Samples arrive one per frame already baked, so linear is the
# faithful reading; Blender's default Bezier would ease between every pair and
# turn a constant orbit into a stuttering one.
ANIMATION_INTERPOLATION = "LINEAR"
DEFAULT_FPS = 24.0

# Maya's vector displacement space onto Blender's. Both applications offer the
# same three, so this is a straight rename rather than an approximation.
DISPLACEMENT_SPACES = {
    "": "OBJECT",
    "object": "OBJECT",
    "world": "WORLD",
    "tangent": "TANGENT",
}

# Maya states ramp interpolation per stop, Blender once for the whole ramp.
# Maya's enum was measured as None:Linear:Smooth:Spline.
RAMP_INTERPOLATIONS = {
    "none": "CONSTANT",
    "linear": "LINEAR",
    "smooth": "EASE",
    "spline": "B_SPLINE",
}

# Rebuilt colour correction. A setting within this of its neutral value builds
# no node at all, which keeps an untouched correction node out of the tree.
CORRECTION_EPSILON = 1e-6

# Arnold's contrast pivots on 0.18 and aiRange's on 0.5, so the pivot is always
# passed explicitly rather than defaulted.
ARNOLD_CONTRAST_PIVOT = 0.18

# Horizontal gap between rebuilt correction nodes, so a chain stays readable
# rather than stacking every node on the same spot.
CORRECTION_NODE_SPACING = 200.0
