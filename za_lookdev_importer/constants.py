# -*- coding: utf-8 -*-
"""Shared constants for the Blender importer.

The LIVELINK_* values are a contract with the Maya exporter and must stay
identical on both sides. Bump LIVELINK_VERSION in both files together when the
message shape changes.
"""

import math

BUILD_VERSION = "1.11.0"

LIVELINK_HOST = "127.0.0.1"
LIVELINK_PORT = 50505
LIVELINK_PROTOCOL = "za_lookdev_livelink"
LIVELINK_VERSION = 1
LIVELINK_EVENT = "lookdev_package_ready"

# Package JSON schema versions this build knows how to read. The import wipes
# the scene, so an unreadable package must be rejected before anything is lost.
# 3 added glass channels and 4 added UDIM on the main branch; 5 is this
# branch with both, plus the Arnold channels.
SUPPORTED_SCHEMA_VERSIONS = (1, 2, 3, 4, 5, 6, 7, 8)

MAX_MESSAGE_BYTES = 32 * 1024 * 1024
SOCKET_POLL_SECONDS = 0.5
TIMER_INTERVAL_SECONDS = 0.1

ROOT_COLLECTION_NAME = "Z-A Lookdev Import"
LIGHT_COLLECTION_NAME = "Z-A Lights"
CAMERA_COLLECTION_NAME = "Z-A Cameras"

# Maya filmFit onto Blender sensor_fit. Overscan has no Blender equivalent and
# frames like Fill, so both fall back to AUTO.
CAMERA_SENSOR_FIT = {
    "fill": "AUTO",
    "horizontal": "HORIZONTAL",
    "vertical": "VERTICAL",
    "overscan": "AUTO",
}
SUBDIVISION_MODIFIER_NAME = "Z-A Subdivision"

# Principled BSDF socket names per channel. Later Blender versions renamed
# some sockets, so each channel lists the names to try in order.
PRINCIPLED_INPUTS = {
    "base_color": ("Base Color",),
    "roughness": ("Roughness",),
    "specular": ("Specular IOR Level", "Specular"),
    "metallic": ("Metallic",),
    "opacity": ("Alpha",),
    "normal": ("Normal",),
    "emission": ("Emission Color", "Emission"),
    "emission_strength": ("Emission Strength",),
}

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

# Channels with no socket of their own. They either select the build path or
# survive as custom properties on the material for reference.
METADATA_CHANNELS = (
    "transmission",
    "thin_walled",
    "transmission_affects_alpha",
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
# tests/light_calibration.md for the procedure to settle it.
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
# Dividing by this maps a display-white-ish 100 nits onto strength 1.0.
OPENPBR_EMISSION_LUMINANCE_SCALE = 100.0
OPENPBR_EMISSION_SEMANTIC = "openpbr_emission_luminance"

# A light's node tree is a multiplier on top of its energy. Nodes feeding
# Emission Strength must stay at unit scale, otherwise energy is applied twice.
NODE_TREE_UNIT_STRENGTH = 1.0
