# mLender

**Live scene transfer from Maya to Blender.**

mLender packages a Maya scene as FBX plus a JSON sidecar, streams it to Blender
over a local socket, and rebuilds it there natively: meshes with their group
hierarchy and per-face material assignments, materials as Principled BSDF node
trees, lights as Blender lights, cameras as Blender cameras.

The goal is not a file format. It is that a scene built in Maya arrives in
Blender ready to render, without anybody re-authoring it. Where the two renderers
disagree, the conversion constants in this tool were **measured by rendering
both sides and solving for the ratio**, not guessed. Those measurements are
recorded under [`tests/docs/`](tests/docs/).

---

## Contents

- [Requirements](#requirements)
- [Installation](#installation)
- [Usage](#usage)
- [Scope](#scope)
- [Import modes](#import-modes)
- [How it works](#how-it-works)
- [Materials](#materials)
- [Lights](#lights)
- [Cameras](#cameras)
- [Animation](#animation)
- [Scene structure](#scene-structure)
- [Colour management](#colour-management)
- [Development](#development)

---

## Requirements

| | |
|---|---|
| Maya | 2022 or newer |
| Renderers | Arnold (MtoA), Redshift, or native Maya shaders |
| Blender | 4.1 or newer — verified on 4.1, 4.3, 4.5 and 5.2 |
| Dependencies | None. Standard library only on both sides. |

The two halves never import each other and have no shared module: they run in
different Python runtimes. Their only contract is the LiveLink protocol and the
package JSON schema.

---

## Installation

### Maya

The exporter is a plain Python package. Add the directory **containing**
`mlender_exporter` to `sys.path`:

```python
import sys

tool_path = r"C:\path\to\mLender"
if tool_path not in sys.path:
    sys.path.append(tool_path)

import mlender_exporter as ml
ml.show_ui()
```

For a permanent setup, append the following to
`Documents/maya/scripts/userSetup.py`. Do not overwrite an existing file; add to
it. `import maya.utils` must appear at the top of the file.

```python
MLENDER_ROOT = r"C:\path\to\mLender"


def _register_mlender():
    import os
    import sys
    try:
        if not os.path.isdir(os.path.join(MLENDER_ROOT,
                                          "mlender_exporter")):
            return
        if MLENDER_ROOT not in sys.path:
            sys.path.append(MLENDER_ROOT)
    except Exception as exc:
        print("mLender could not be registered: %s" % exc)


maya.utils.executeDeferred(_register_mlender)
```

The whole block is wrapped in `try`, so a moved directory cannot break Maya's
startup.

A shelf is the other option: drop a separate `shelf_mLender.mel` into
`Documents/maya/<version>/prefs/shelves/`. Because it is a new file, existing
shelves are untouched. Two buttons are useful — one calling `ml.show_ui()` and
one calling `ml.reload_package()` for development.

### Blender

`mlender_importer` is a standard multi-file add-on. Install it in any of
three ways:

**Copy the folder** into Blender's add-on directory:

```text
%APPDATA%\Blender Foundation\Blender\<version>\scripts\addons\mlender_importer\
```

**Install a zip** of the `mlender_importer` folder through
`Edit > Preferences > Add-ons > Install`.

**Link the folder** — best for development, since `git pull` then needs no
copying:

```bat
mklink /J "%APPDATA%\Blender Foundation\Blender\5.2\scripts\addons\mlender_importer" ^
          "C:\path\to\mLender\mlender_importer"
```

A directory junction needs no administrator rights on Windows. `ln -s` does the
same on Linux and macOS.

Enable **mLender** in `Edit > Preferences > Add-ons`.

> **Upgrading from 1.x.** The add-on module was called `za_lookdev_importer`
> and is now `mlender_importer`, so Blender treats it as a new add-on rather
> than an update. Remove the old one and, if you installed it as a junction or
> symlink, point the link at the new folder. Generated nodes are prefixed
> `ML_` and custom properties `ml_`, where 1.x used `ZA_` and `za_`.
>
> A 1.x package still imports: its JSON is named `*_lookdev.json` and the
> importer accepts both names. The two halves must match, though — the
> LiveLink protocol string changed, so a 2.0 exporter cannot talk to a 1.x
> importer, and it says so rather than failing quietly.

---

## Usage

**In Maya** — `ml.show_ui()`, then:

1. Choose an **Export Location**.
2. Check the Blender host and port. Default `127.0.0.1:50505`.
3. Press **Send To Blender**.

**In Blender** — `View3D > N Panel > mLender`:

1. Confirm the **Build** number is the version you expect.
2. Check **FBX Scale**.
3. Check host and port.
4. Press **Start LiveLink**.

After an import, read the panel's status line (mesh, material, subdivision and
light counts) and check the System Console for lines beginning
`mLender warning:`.

### Options

| Control | Default | Effect |
|---|---|---|
| Collect Textures | off | Copy every referenced texture into the package |
| Export Scope | off | Send only the selected objects |
| Export Animation | off | Send a frame range instead of a single frame |
| Alembic Cache | off | Cache deforming meshes and emitting particles |
| Bake Procedurals | off | Bake fileless shading networks to UVs |
| Bake Resolution | 1024 | Resolution of those bakes |
| Light Power Scale | 1.0 | Artistic multiplier over the measured conversion |

---

## Scope

Deliberately **not** included:

- No Alembic.
- No shape keys, parenting or constraint setup.
- No template `.blend` selection.
- No turntable generator — whatever is animated in the scene is what arrives.

**Replace is the default and it is destructive by design.** It wipes the
Blender scene and purges unused data-blocks before rebuilding, which is what
makes the Maya scene the single source of truth. Two other modes are available
from the N panel; see [Import modes](#import-modes).

---

## How it works

### Package layout

Each send creates a new package folder under the chosen export location:

```text
mLender_01/
  mLender_01.fbx
  mLender_01_scene.json
```

Textures are **not** copied by default. The JSON carries the original Maya
texture path and Blender's image node opens the same file. When both
applications run on one machine this is the correct behaviour and it avoids
duplicating a texture library.

Ticking **Collect Textures** copies every referenced texture into
`textures_collected/` inside the package and rewrites the JSON paths, making
the package portable:

```text
mLender_01/
  mLender_01.fbx
  mLender_01_scene.json
  textures_collected/
    wood_basecolor.tx
    tile.1001.tx
    tile.1002.tx
```

Three details matter here:

- **A UDIM path is a pattern, not a file.** Copying a path containing `<UDIM>`
  verbatim copies nothing, so the sibling tiles are found on disk and copied
  individually while the JSON keeps the token.
- A texture used by several channels is copied **once**.
- The original Maya path is preserved in `original_path`.

A missing texture does not stop the export. A warning is recorded and that path
is left unchanged.

### Import sequence

1. Validate the LiveLink protocol and the package schema version. An
   incompatible package is rejected **before the scene is touched**.
2. Locate the package's FBX.
3. Save the current .blend if it has a path.
4. Delete all objects and collections.
5. Purge unused meshes, materials, images, textures, actions and other
   data-blocks.
6. Import the FBX.
7. Remove the temporary material slots the FBX importer created.
8. Apply the mesh-to-material and per-face assignments from the JSON.
9. Rebuild materials as Principled BSDF (or Glass, or unlit) node trees.
10. Link textures from their recorded locations.
11. Rebuild lights and the Dome world.
12. Rebuild cameras and make the renderable one active.
13. Configure subdivision modifiers.
14. Purge orphans again.

Validation runs first on purpose. If the Blender add-on is older than the Maya
exporter, the package is refused and the existing scene survives. Supported
schema versions are listed in `SUPPORTED_SCHEMA_VERSIONS`.

A single failed material, texture or light does not abort the import. Failures
are collected as warnings and the rest of the scene still arrives — a partial
result beats none.

### Repository layout

Both packages are ordered by dependency: a module may only import ones listed
above it.

```text
mlender_exporter/        # Maya side
  constants.py              # protocol constants, attribute alias tables
  mayautils.py              # maya.cmds wrappers and value helpers
  collect.py                # optional texture collection
  animation.py              # frame range and timeline sampling
  textures.py               # upstream texture search
  bake.py                   # baking procedural networks to UVs
  shaders.py                # shader to channel extraction
  meshes.py                 # mesh discovery, material and face assignment
  lights.py                 # light discovery and records
  cameras.py                # camera discovery and lens records
  fbx.py                    # MEL FBXExport wrapper
  livelink.py               # TCP client
  package.py                # package folder, JSON, atomic cleanup
  ui.py                     # Maya window

mlender_importer/        # Blender side (multi-file add-on)
  constants.py              # protocol constants, socket names, calibration
  utils.py                  # value and name normalisation
  images.py                 # texture loading, UDIM
  corrections.py            # rebuilding Maya correction nodes
  materials.py              # node trees
  lights.py                 # Blender lights, dome world
  cameras.py                # Blender cameras
  transforms.py             # Maya to Blender matrix conversion
  colormanagement.py        # Maya OCIO settings to Blender view transform
  animation.py              # sampled animation as keyframes
  scene.py                  # scene clearing, mesh matching, subdivision
  fbx.py                    # FBX import, package file resolution
  importer.py               # orchestration and schema validation
  livelink.py               # socket listener and main-thread pump
  ui.py                     # operators, properties, panel

tests/
  check_contracts.py        # no host needed, runs in seconds
  host/                     # real Maya and real Blender
  calibration/              # render matching and measurement rigs
  docs/                     # measurement records
```

---

## Materials

### Supported shaders

**Redshift** — `RedshiftStandardMaterial`, `RedshiftMaterial` (legacy)

**Arnold** (verified against MtoA 5.4.8) — `aiStandardSurface`,
`aiOpenPBRSurface`, `aiLambert`, `aiFlat`

**Native Maya** — `lambert`, `blinn`, `surfaceShader`

Transferred channels: base colour, reflection roughness, metalness,
normal/bump, opacity, emission colour and strength, specular weight,
transmission (weight, colour, roughness), IOR, thin-walled, and the coat, sheen
and subsurface lobes.

### Three build paths

**Principled BSDF** is the normal case.

**Glass BSDF** is used when the transmission weight is above zero. A dedicated
Glass BSDF matches Redshift and Arnold refraction markedly better than
Principled's transmission, and roughness and IOR mean the same thing on both
sides. Cutout opacity is kept separate from refraction: an opacity below one
mixes the Glass BSDF against a Transparent BSDF rather than tinting the glass.

**Emission mixed against Transparent** is used for unlit shaders
(`surfaceShader`, `aiFlat`), which reproduces their behaviour far better than
pushing the colour into a base colour would.

Source values survive as custom properties: `ml_material_mode`,
`ml_transmission_weight`, `ml_thin_walled`, `ml_transmission_affects_alpha`.

### Specular weight

Arnold and Redshift state specular as a 0–1 weight. In Blender's
`Specular IOR Level`, 0.5 is an ordinary dielectric and 0 is no specular at all,
so a full weight maps onto Blender's **default**, not onto 1.

This matters more than it looks. Principled conserves energy, so leaving the
level at 0.5 for a shader whose Maya specular was 0 both adds a highlight that
was never there and steals that energy from the diffuse.

### Redshift roughness

Principled Roughness is driven by Redshift **Reflection Roughness**. Redshift's
Diffuse Roughness controls Oren–Nayar diffuse behaviour and is deliberately not
used.

If the material's flag says the roughness input is glossiness, the value is
inverted (`roughness = 1 - glossiness`). A flat value is inverted by the
exporter; a texture cannot be, so the flag travels with the record and the
importer inserts an invert node. The split is on whether there is a **file**
behind the texture, not on whether the record carries a value — a procedural
that could not be baked leaves a record with no path, and the flat value is
then the only place an inversion can still happen.

Attribute candidates:

```text
                        RedshiftStandardMaterial   RedshiftMaterial
Base Color              base_color                 diffuse_color
Reflection Roughness    refl_roughness             refl_roughness
Metalness               metalness                  refl_metalness
Opacity                 opacity_color              opacity_color
Normal/Bump             bump_input                 bump_input
Emission                emission_color             emission_color
Emission Strength       emission_weight            emission_weight
```

Alternative spellings are tried for each channel. The JSON records the
`maya_attr` and `maya_plug` actually found.

### Arnold

Attribute names were read from a live MtoA 5.4.8 session, not guessed.
`aiStandardSurface` and `aiOpenPBRSurface` differ in three channels:

```text
Channel            aiStandardSurface     aiOpenPBRSurface
Base Color         baseColor             baseColor
Roughness          specularRoughness     specularRoughness
Metallic           metalness             baseMetalness
Opacity            opacity (colour)      geometryOpacity (float)
Normal/Bump        normalCamera          normalCamera
Emission           emissionColor         emissionColor
Emission Strength  emission (0-1)        emissionLuminance (nits)
```

Three behavioural differences:

- **Arnold opacity is not inverted.** Maya's `transparency` is inverted on the
  way to opacity; Arnold's `opacity` already is opacity (1 = opaque).
- **OpenPBR emission is a luminance in nits, not a weight.** It is divided by
  `OPENPBR_EMISSION_LUMINANCE_SCALE` (1000, measured) to reach a Blender
  strength. The value 100 that was first assumed made every OpenPBR emissive
  surface ten times too bright.
- **`aiFlat` reads `color`, never `outColor`.** On a Maya `surfaceShader`
  `outColor` is a real input attribute; on an Arnold shader it is a computed
  output that reads back as a meaningless constant outside a render.

`aiStandardSurface.base` and OpenPBR's `baseWeight` are not applied: Principled
has no matching input and folding them into base colour would misreport the
exported value.

`aiLambert` takes its base colour from `KdColor` and is built with Roughness
`0.7` and Metallic `0.0`.

### Native Maya shaders

Lambert and Blinn transfer base colour (texture if connected, value otherwise)
and convert `transparency` to opacity. Roughness is approximated: **0.7** for
lambert, **0.1** for blinn, with Metallic `0.0` for both.

`surfaceShader.outColor` drives an Emission shader and `outTransparency`
becomes the Mix Shader factor against a Transparent BSDF, so the material
behaves emissively rather than taking light like a Principled surface.

### Texture networks

A material input need not have a file node wired straight into it. The exporter
walks the upstream history and checks `file.fileTextureName`, Redshift's
`tex0`, `filename` and `file`.

Intermediate nodes are no longer skipped: recognised ones are rebuilt as
Blender nodes (see below) and unrecognised ones are reported. When a network's
result cannot be expressed that way, baking takes over.

Base colour and emission textures load as colour data; roughness, metalness,
opacity and normal textures load as Non-Color. Normal maps route through a
Normal Map node.

### UDIM

UDIM detection is not guessed from the filename, it is **asked of Maya**:
`file.uvTilingMode` says whether the node is tiled and
`computedFileTextureNamePattern` gives Maya's own resolved pattern. Only if
both come back empty is the tile number in the filename replaced with `<UDIM>`.

- `<UDIM>`, `<udim>`, `%(UDIM)d`, `$UDIM` and `{UDIM}` normalise to one token.
- A tile number must be 1001 or above and must be the **last** four-digit group
  in the name, so version numbers are not mistaken for tiles.
- The Blender image is set to `TILED` and reloaded — Blender only scans for
  sibling tiles during a reload.
- The glob uses `[1-9][0-9][0-9][0-9]` rather than `*`, which used to catch
  unrelated files sharing a prefix.

### Texture placement

Maya keeps tiling in a separate `place2dTexture` node. Because the upstream
search walked past it on the way to the file, these values used to be dropped
silently: a texture repeating 4×3 in Maya arrived 1×1 in Blender. A **Mapping**
node is now built:

```text
repeatU / repeatV   -> Mapping Scale X / Y
offset              -> Mapping Location X / Y
rotateUV            -> Mapping Rotation Z   (degrees -> radians)
wrapU / wrapV       -> Image extension REPEAT, or EXTEND when off
mirrorU / mirrorV   -> Image extension MIRROR
```

`rotateUV` is a `doubleAngle` attribute and `getAttr` returns it in the current
angle unit, so it is written to JSON as degrees and converted on import. If the
placement is at its defaults, no Mapping node is created.

### Bump

`bump2d.bumpDepth` reaches the Normal Map node's **Strength** input. It used to
be dropped, which meant every normal map arrived at full strength.

`bumpInterp` selects the node: `Tangent Space Normals` builds a Normal Map
node, `Object Space Normals` the same with `space = OBJECT`, and plain `Bump`
builds Blender's **Bump** node, treating the map as a height field.

### Coat, sheen and subsurface

```text
coat / coatWeight        -> Coat Weight
coatRoughness            -> Coat Roughness
coatColor                -> Coat Tint
coatIOR                  -> Coat IOR
sheen / fuzzWeight       -> Sheen Weight
sheenRoughness           -> Sheen Roughness
sheenColor / fuzzColor   -> Sheen Tint
subsurface / weight      -> Subsurface Weight
subsurfaceRadius         -> Subsurface Radius
subsurfaceScale          -> Subsurface Scale
specularAnisotropy       -> Anisotropic
```

Five of these needed more than a rename. Each was measured against Arnold with
the chart rig in [`tests/calibration/`](tests/calibration/); the numbers are in
[`tests/docs/material_match.md`](tests/docs/material_match.md).

**aiStandardSurface sheen roughness is remapped.** Arnold's standard-surface
sheen and Blender's microfiber sheen are different lobes whose roughness inputs
do not mean the same thing: at 0.3 Arnold shows a sheen Blender barely
registers, and at 1.0 Blender shows a third more than Arnold. No single factor
could fix that — the sign of the error changes partway along the scale. A
measured table remaps it (0.25 becomes about 0.51); the original is kept in
`ml_source_sheen_roughness`. The table came out identical at two base albedos
and stable across Blender 4.1 to 5.2.

**aiOpenPBRSurface `fuzzRoughness` passes through untouched.** Swept the same
way it already agrees with Blender to within 2%, because both follow the same
model. Remapping it would break a match that is already correct.

**OpenPBR's `specularWeight` scales the metal lobe.** A surface with
`baseMetalness = 1` and `specularWeight = 0` renders **completely black** in
Arnold; `aiStandardSurface` does not behave this way and Principled has no
socket that does. Measured across five weights and five metalness values, the
result is exactly `base × (1 − metalness × (1 − specularWeight))`. That factor
is applied to the base colour and recorded as `ml_openpbr_specular_scale`. At
the default weight of 1.0 the factor is 1 and nothing changes.

**OpenPBR's `coatDarkening` is folded into the base colour.** OpenPBR darkens
what sits under the coat — light the underside of the coat reflects back down
is absorbed again, so a dark base loses far more than a bright one. Principled
has no such input, and without this a coated OpenPBR material arrived up to
**twice as bright** as Maya rendered it. The curve is
`(1 − rᵢ)/(1 − rᵢ · base)`, linear in the darkening attribute and quadratic in
the coat weight because the light crosses the coat going in and coming out.
`rᵢ` follows the coat IOR and was checked at three IORs. A flat base colour is
darkened directly; a textured one goes through a node chain. The package keeps
reporting the artist's base colour; the amount applied is in
`ml_coat_darkening`. `aiStandardSurface` has no such attribute and is
unaffected.

**Principled has no separate Subsurface Color socket** in 4.1 or 5.2; it tints
from the base colour. Maya's `subsurfaceColor` is therefore kept as metadata
rather than dropped silently. **`Subsurface Scale` defaults differ between
versions** (0.05 in 4.1, 0.005 in 5.2), so the value is always set explicitly.

### Colour correction nodes

Correction nodes between a texture and a shader used to be skipped silently:
the upstream search walked past them, and a texture whose gamma and saturation
had been changed arrived raw. Recognised nodes are now rebuilt as Blender
nodes, which is faster than baking and stays editable:

| Maya / Arnold | Blender |
|---|---|
| `aiColorCorrect` | Gamma + Hue/Saturation + Bright/Contrast + Mix |
| `gammaCorrect` | Gamma |
| `aiRange` | Mix (scale) + Mix (offset) + Bright/Contrast |
| `aiMultiply` | Mix (Multiply) |
| `aiAdd` | Mix (Add) |
| `reverse` | Invert |
| `clamp` | Mix (Lighten) + Mix (Darken) |
| `blendColors` | Mix, factor inverted |
| `multiplyDivide` | Mix (Multiply / Divide) |
| `remapValue` | Mix + Colour Ramp + Mix |

Nodes are prefixed `ML_CC_` / `ML_`. A setting left at its neutral value builds
no node, so an untouched correction node does not clutter the tree.

Five conversions were measured and came out against intuition — details in
[`tests/docs/correction_nodes.md`](tests/docs/correction_nodes.md):

- **Gamma is the inverse exponent.** Maya applies `in^(1/g)`, Blender's Gamma
  node applies `in^g`.
- **`hueShift` is in turns**, not degrees, while Blender's Hue is an offset
  around a neutral 0.5.
- **`contrast` is pivoted.** Arnold computes `c·(in − pivot) + pivot`, Blender
  `(1 + C)·in + (B − C/2)`.
- **`blendColors` is the reverse of Blender's Mix.** In Maya `blender = 1`
  returns colour 1; in Blender `Factor = 1` returns the **second** colour. The
  factor is inverted, and which input the texture arrived on is recorded
  because the node is not symmetric.
- **`remapValue`'s ramp is its main job.** Building only the linear part — the
  old behaviour — silently discarded the curve the artist drew. The ramp is now
  built as a Colour Ramp. Maya stores interpolation per stop and Blender per
  ramp, so the first is used and a mixed ramp is reported.

Nodes with no Blender equivalent (`aiComposite`, `remapHsv`, and `aiRange`'s
`smoothstep`, `bias` and `gain`) are reported after the import:

```text
Correction node "remapCoat" (remapValue) has no Blender equivalent,
so the texture is used without it.
```

### Procedural baking

When a channel is driven by a network with no file behind it — a checker, a
ramp, layered noise — there is nothing to reference, so the exporter **bakes**
the network to the mesh's UVs and writes it into the package.

```text
mLender_01/
  textures/
    procCube_shd_base_color.png
    procCube_shd_roughness.png
```

Baking only runs when it is genuinely needed; if the upstream search finds a
file, that file is referenced instead.

Two measured constraints shaped this:

- **Maya writes linear.** `convertSolidTx` writes linear values whether colour
  management is on or off (0.5 in stores as 0.498; sRGB would give 0.735).
  Baked maps are therefore loaded as **Non-Color even for colour channels**.
  Assuming sRGB would darken every bake.
- **It cannot write EXR.** The file node points at a path but nothing lands on
  disk, so the format is PNG.

Eight-bit linear PNG can band in the darks for colour channels. That is a
deliberate trade; the alternative is not transferring the channel at all.

A baked record carries `baked_from`, so a map can be traced back to the Maya
node it came from. A mesh with no UVs bakes empty; that is warned about and the
export continues.

### Displacement

Maya keeps displacement **on the shading engine, not the shader** —
`aiStandardSurface` has no displacement attribute. Mesh and shading engine are
therefore read together: the map comes from the engine, the height and zero
value from the mesh. Both wirings found in real scenes are recognised:

```text
file -> displacementShader -> SG.displacementShader     (the common one)
file --------------------->  SG.displacementShader      (Arnold renders this too)
```

A **Displacement** node is built and connected to the material output. The
mapping is exact because both sides compute `(map − midlevel) × scale`:

```text
aiDispHeight * displacementShader.scale  ->  Scale
aiDispZeroValue                          ->  Midlevel
map                                      ->  Height
aiDispAutobump                           ->  displacement_method = BOTH
```

**No unit scale is applied, on purpose.** Measured: FBX import puts the unit
conversion on the object's scale and leaves vertex coordinates in Maya units,
so one unit of object-space displacement already is one Maya unit. This is the
**opposite** of the light energy rule, where the squared scene scale is
mandatory; adding it here would give a hundred times too much displacement in a
centimetre scene.

Vector displacement is built as well: `displacementMode` states both whether it
is vector and which space, and Blender's Vector Displacement node offers the
same spaces.

Displacement is a **Cycles** feature; EEVEE ignores it. A mesh with no
subdivision is warned about, since displacement then has no geometry to move.
The `Scale` socket's default differs between versions (1.0 in 4.1, 0.01 in
5.2), so it is always set explicitly.

---

## Lights

Lights are not written into the FBX. They are sent through the JSON and rebuilt
under `mLender Import > mLender Lights`.

```text
Redshift Physical Area         -> Area
Redshift Physical Point        -> Point
Redshift Physical Spot         -> Spot
Redshift Physical Directional  -> Sun
Redshift Dome                  -> World environment
Redshift IES                   -> Spot + IES texture node
aiAreaLight                    -> Area (quad / disk / cylinder)
aiSkyDomeLight                 -> World environment
aiPhotometricLight             -> Spot + IES texture node
aiMeshLight                    -> Area (approximated)
Maya Area/Point/Spot/Directional -> the matching Blender light
```

`aiLightPortal` is not transferred: it has neither colour nor intensity, so it
would arrive as a black area light.

Transferred: world position and rotation, area size from the transform scale,
colour and colour temperature, intensity, exposure and physical unit, area
shape, normalize, spread and bidirectional metadata, spot cone and falloff,
shadow settings, and dome HDR and IES file paths. Exposure is evaluated as
`intensity × 2^exposure`. Originals are preserved in `ml_source_*` properties.

Arnold spells the exposure attribute inconsistently — `aiAreaLight` and
`aiPhotometricLight` carry `exposure`, while `aiSkyDomeLight`, `aiMeshLight`
and Arnold-enhanced native Maya lights carry only `aiExposure`. The alias table
tries both, in that order.

### Energy model

**Blender's light Power is total luminous flux.** This was established by
rendering, not from documentation: in Blender 4.1 and 5.2, quadrupling a
light's size with normalize on leaves its brightness unchanged (ratio 0.998),
and with normalize off multiplies it by 16 (= 4²). Older versions without the
`normalize` property behave in flux mode too.

That is the same contract Arnold documents: with normalize on the total output
is `O = C`, with it off `O = C × A`. Redshift uses the same concept.

The importer therefore **converts every light to total flux** and leaves
Blender's `normalize` on. Doing the area multiplication here *and* leaving it
to Blender would apply the area twice.

Lights that state a physical unit convert exactly:

```text
Lumens     -> flux = intensity / 683
Candela    -> flux = intensity * 4pi / 683
Watts      -> direct
Radiance   -> flux = intensity * area * pi / 683
Sun        -> irradiance; area and normalize do not apply
```

### Intensity to watts

Arnold's `intensity` and Redshift's "Image" unit are dimensionless, while
Blender's Power is total flux in watts. This conversion was **measured**, by
rendering an identical scene in Arnold and Cycles and solving for the ratio:

```text
Arnold        x pi     (measured)
Native Maya   x pi     (measured; MtoA converts to the same quad_light)
Redshift      x10      (not measurable here, inherited from the original tool)
```

π is not a coincidence: Arnold's normalized `intensity` is the luminous
intensity along the light's normal (`I₀`), the total flux of a Lambertian
emitter is `Φ = π·I₀`, and Blender's Power is total flux.

The square of the scene unit enters as well, because Arnold is unit-agnostic: a
distance of 150 units in a centimetre scene becomes 1.5 m in Blender, and
illumination goes wrong by 10⁴ through `1/d²`.

```text
Blender Power = pi * meters_per_maya_unit^2 * intensity * 2^exposure
```

Across five variants changing distance, intensity and exposure, the anchor came
out at 3.1412 every time (spread 0.00006). Method and raw numbers are in
[`tests/docs/light_calibration.md`](tests/docs/light_calibration.md).

> Before 1.7.0 this meant Arnold and Maya lights arrived **318× too bright**.
> Re-sending an old package will change its lighting noticeably. The new
> result is the correct one.

**Light Power Scale** in the N panel is an artistic multiplier over this,
default `1.0`. It scales all lights equally and does not disturb their
relative ratios.

Redshift users can skip the inherited estimate entirely by setting the light's
`unitsType` to a physical unit — those branches convert exactly.

Cylinder and mesh area shapes, which Blender has no exact equivalent for, are
approximated as rectangular area lights. With several domes present, the first
active one drives Blender's single world and the rest are kept as metadata
empties.

### Light linking

Maya's light linking is transferred. Blender's equivalent is a **receiver
collection**:

```text
Maya      lightA -> cubeA (link to cubeB broken)
Blender   lightA.light_linking.receiver_collection = ML_Link_lightA
          containing: cubeA
```

That collection is **not** linked into the scene tree; it is a linking
mechanism, not an organisational folder, so a mesh legitimately appears both in
its group collection and in a receiver collection.

Three decisions:

- **No queries at all if nothing is unlinked.** Maya keeps broken links in
  `lightLinker.ignore`; an empty array means every light lights everything, and
  the per-light query — expensive in large scenes — is skipped.
- **Nothing is written for a light that lights everything.** Absence means no
  restriction.
- **An empty answer is not read as "lights nothing".** Maya returns an empty
  result for any light outside `defaultLightSet`, and treating that as a
  restriction would black the light out entirely in Blender. The two errors are
  not equal: restricting wrongly destroys the light, while failing to restrict
  merely misses a restriction that probably was not there.

**Shadow linking is transferred separately**, since Maya keeps it in its own
arrays and a light can restrict shadows without restricting illumination.
Blender's equivalent is the `blocker_collection`.

---

## Cameras

Maya's startup cameras (`persp`, `top`, `front`, `side`) are viewport
furniture and are not transferred. User cameras are rebuilt under
`mLender Import > mLender Cameras`.

Maya and Blender cameras face the same way (local −Z forward, +Y up), so the
same matrix conversion as lights applies. The differences are lens and units:

```text
focalLength              -> lens (mm, direct)
horizontalFilmAperture   -> sensor_width   (inches x 25.4)
verticalFilmAperture     -> sensor_height  (inches x 25.4)
filmFit                  -> sensor_fit     (Fill/Overscan -> AUTO)
horizontalFilmOffset     -> shift_x        (divided by aperture, a ratio)
nearClipPlane/farClip    -> clip_start/end (scene units -> metres)
orthographicWidth        -> ortho_scale    (scene units -> metres)
depthOfField/fStop       -> dof.use_dof / dof.aperture_fstop
focusDistance            -> dof.focus_distance (scene units -> metres)
```

### Image planes

A Maya image plane becomes a Blender camera background image. Both are
viewport reference rather than something that renders, so the mapping is about
the right image being on the right camera:

```text
imageName    -> the loaded image        alphaGain -> alpha
fit          -> frame_method            (always behind the geometry)
displayMode  -> None hides the plane without removing it
offsetX / Y  -> offset, as a fraction of the plane's own size
```

Two approximations, both recorded rather than hidden. Maya has five fit modes
(Fill, Best, Horizontal, Vertical, To Size) against Blender's three, so Fill
becomes crop, To Size becomes stretch and the rest become fit. And Maya's
plane depth is a distance while Blender only offers front or back. The Maya
values survive on the camera data as `ml_source_image_plane_fit` and
`ml_source_image_plane_depth`.

A plane driven by a texture or a movie has no file to point Blender at, and a
path that is not on disk is refused rather than attached as a broken
background; both are reported.

The camera marked `renderable` in Maya becomes Blender's active scene camera.
With several renderable cameras the first is chosen and a warning is issued.
Originals are stored in `ml_source_*` on the camera data.

---

## Animation

Off by default — the tool sends a single frame. Ticking **Export Animation**
transfers a frame range.

```text
Frame Range   empty   -> Maya's playback range (minTime - maxTime)
              1-120   -> explicit range
              1-120x2 -> sample every second frame
```

Two different routes are used, deliberately:

- **Meshes travel inside the FBX.** FBX already carries animation and is the
  only route that transfers deformers correctly;
  `FBXExportBakeComplexAnimation` is enabled along with the range.
- **Cameras and lights are sampled into the JSON**, because they are rebuilt
  from scratch in Blender. World matrix, camera lens, light intensity and
  colour are written per frame.

Light energy is **recomputed per frame** rather than interpolated, so every
frame goes through the measured conversion.

FPS is read from Maya (`currentTimeUnitToFPS`) and NTSC fractions are
reconstructed exactly with Blender's `fps` / `fps_base` pair (23.976 → 24 /
1.001).

Two traps, either of which would ruin a turntable:

- **Euler flips.** Solving each frame's matrix independently lets angles jump a
  full turn between frames, so a camera orbiting 360° appears to snap back.
  Each frame is made compatible with the previous one.
- **Interpolation.** Baked samples are linear. Blender's default Bezier eases
  in and out of every key and makes a constant rotation stutter, so keys are
  set to `LINEAR`.

The frame count is capped at **2000**. Exceeding it clips the range and records
that it was clipped, rather than sending short silently.

---

## Scene structure

### Groups become collections

Maya's group hierarchy is rebuilt as nested collections. Everything used to
land flat in one root collection, which made the outliner unusable in a busy
scene.

```text
Maya                              Blender
|setDressing|props|chair    ->    mLender Import
                                    setDressing
                                      props
                                        chair
```

- **Only real groups become folders.** A transform with its own shape is an
  object, not a folder; otherwise a transform carrying geometry would invent a
  nesting level that does not exist.
- A mesh with no group stays in the root collection.
- Two meshes from the same Maya group share **one** collection.
- Generated collections carry `ml_generated` and `ml_maya_group`.

Lights and cameras stay together under `mLender Lights` and `mLender Cameras` rather
than joining this hierarchy, so they stay reachable as a set.

### User attributes

Attributes a pipeline hangs off a Maya node — an asset id, a variant name, a
LOD level — arrive as Blender custom properties under **their own names**, so a
script written against the Maya scene keeps working: `obj["assetId"]` on both
sides. Meshes, locators, empties and curves all carry them, and a mesh's shape
attributes are merged in alongside its transform's.

```text
long / double  -> number        string  -> string
bool           -> bool          double3 -> three numbers
enum           -> its label, not its index
```

Three details, each measured rather than assumed:

- **An enum reads back as an integer.** The label is stored instead, for the
  reason this codebase already matches enums on labels elsewhere: the indices
  are not stable across versions.
- **A compound is listed together with its children**, so a `double3` appears
  four times over. Only the parent is kept, recognised by the children having
  one.
- **A name starting with `ml_` is refused and reported.** Everything the tool
  writes onto an object uses that prefix, and Merge decides what it may adopt
  by reading `ml_generated` — letting a Maya attribute overwrite it would make
  the importer lose track of its own objects.

An object with no user attributes costs nothing: Maya returns nothing for it.

### Hard and soft edges

Also already carried by the FBX, and also asserted rather than assumed. A cube
with every edge hard arrives faceted, with twelve sharp edges and face
normals; one with every edge soft arrives with none and vertex-averaged
normals. Both carry custom normals, and the corner normal API is spelled the
same on 4.1 and 5.2.

The pair is what makes the check worth having: a single cube would pass
against an export that flattened every mesh to the same shading.

### UV sets and vertex colours

Both already survive the FBX and the tool builds neither. Measured on a cube
with two named UV sets and a colour set: the sets arrive under their Maya
names, Maya's current set is the one Blender makes active, the two sets hold
genuinely different coordinates, and the colour set arrives as a corner-domain
colour attribute with the painted values intact.

They are asserted in the host tests anyway, because nothing else pins them and
a change to the FBX export options could drop a UV set without a word.

### Particles

Blender has nothing to receive a Maya particle object. Its own particle
systems are driven by emitters and physics rather than explicit positions, and
a point cloud — the truer analogue — **cannot be built from Python at all**:
measured on 4.1, 4.5 and 5.2, the datablock exists but its points collection
has no `add`.

So what travels is the thing that survives the difference intact, where the
particles are, and they arrive as a mesh of loose vertices. That works on
every version, shows the particles where Maya had them, and is what geometry
nodes instance onto — which is how a Blender artist would put geometry back on
them. Per-particle radius, colour and opacity arrive as point-domain
attributes under their own names when Maya had them.

Two readings were measured rather than assumed. `particle -q -position`
returns **None**; the query that works is `getParticleAttr` with `array`,
which hands back three numbers per particle in one flat list. And those
numbers are **local**, so they pair with the world matrix rather than
replacing it — applying the transform twice is exactly what the test guards
against.

#### Baking a simulation

With **Export Animation** on, the positions are sampled across the frame range
and arrive as keyframes on the mesh vertices, linear rather than eased, so the
simulation plays back in Blender.

That bake is only possible when the particle count never changes. A Blender
mesh has a fixed vertex count, and measured on 4.1 and 5.2 an object's mesh
datablock cannot be keyframed either, so there is no representation on the
other side for a set of points that grows. An emitter-driven system does grow —
measured 0, 3, 7 and 15 particles at frames 1, 5, 10 and 20 — and rather than
shipping a bake that drops the particles born later, such an object travels as
a snapshot of the exported frame and says so:

```text
mLender warning: Particle object "sparkParticle" changes count over the
frame range, so only the exported frame travels.
```

A very dense simulation is refused the same way, with its own message, because
three numbers per point per frame would otherwise exceed the live link's 32 MB
message limit and fail as a transfer instead of as a bake.

To bring an emitting simulation across in full, turn on **Alembic Cache**
below.

The panel's status line reports how many particle objects arrived and how many
of them were baked.

### Alembic cache

**Alembic Cache** in the Maya window writes a second file next to the FBX and
the JSON, holding the two kinds of object neither of those can carry. It is off
by default and needs **Export Animation**.

Both cases were measured, not assumed.

**A mesh whose points are moved by a deformer arrives frozen through FBX.** A
cluster that moves vertices six units in Maya moved them zero in Blender, with
no warning. FBX carries a transform's animation and a skin's, but not the
result of an arbitrary deformer. Through the cache the same mesh reproduces the
motion exactly.

**An emitting particle system cannot travel at all otherwise**, for the reason
given above: its count changes. Alembic reproduces the varying counts exactly —
0, 3, 7 and 15 points at frames 1, 5, 10 and 20, the numbers Maya reported.

What is cached is decided per object, not per scene: a mesh with no deformer
stays in the FBX, and a particle object with a constant count still travels as
a vertex bake. Only the objects that need a cache get one, so turning the
option on does not turn every package into a cache.

Blender receives these objects with a **Mesh Sequence Cache** modifier pointing
at the `.abc`, which means:

- the file must travel with the package; move the folder, not the file
- an emitting system arrives as a **point cloud** on Blender 4.5 and later, and
  as a mesh on 4.1, which is the only datablock those builds can hold it in
- the geometry is read from disk each frame rather than stored in the `.blend`

A cache carries the deformed *result* and nothing that drives it. Caching a
skinned character therefore gives you geometry in Blender that plays back but
cannot be posed, and the export says so:

```text
mLender warning: 1 cached mesh(es) are rig driven; the cache carries the
deformed result, not the rig.
```

If Maya's `AbcExport` plugin cannot be loaded, the export still succeeds and
warns; the affected objects travel as a single frame.

### Volumes

An Arnold `aiVolume` points at a VDB and Blender's volume object reads the
same format, so nothing is converted: the path travels and Blender opens the
file itself. A volume is neither a mesh nor a locator, so none of the existing
discovery found one and it simply did not arrive.

```text
filename           -> filepath
useFrameExtension  -> is_sequence, with frame becoming frame_start
grids, stepSize, stepScale, velocityScale, motionBlur
                   -> kept as ml_source_*, being Arnold render settings with
                      no Blender datablock equivalent
```

**A missing VDB is built anyway**, unlike a missing image plane. Measured on
4.1 and 5.2: Blender takes the path, reports no grids and raises nothing, so
the volume still marks where it belongs and can be re-pointed — and a VDB path
is routinely a per-frame sequence that resolves elsewhere. The missing file is
reported.

Only Arnold is read. Redshift's volume attribute names cannot be probed here,
and this project does not write names it has not read off a live session.

### Curves

NURBS and bezier curves never rode the FBX either — the export selects mesh
transforms, so a curve was not even offered to it. They travel as their own
records, carrying their control points in local space plus the transform's
world matrix.

Blender does not accept an arbitrary knot vector; it offers uniform, endpoint
and bezier knots. What Maya reports maps onto that cleanly:

```text
degree 1          -> POLY spline
degree 2 and up   -> NURBS spline, order = degree + 1
form 0 (open)     -> use_endpoint_u, the clamped curve Maya's (0,0,0,1,1,1)
                     knots describe
form 1 or 2       -> use_cyclic_u
```

Two measured details decide whether this works at all:

- **Control points are read one at a time, not in bulk.** Asking for them in
  one go returns **zeros** for any curve with construction history, because
  the attribute is unused and the geometry arrives through the input
  connection. A circle came back as eight points at the origin, which would
  have collapsed every procedurally built curve in a scene to a dot.
- **A periodic curve reports more control points than it has.** Maya repeats
  degree many of them to close the loop: a circle reports 11 while the unique
  count is 8. Eight is what Blender wants for a cyclic spline, so the other
  reading stacks three duplicates on the seam.

Round-tripped against Maya at three curves — one open cubic moved, rotated and
scaled, one linear, one grouped periodic circle — every control point lands
within 1e-6 of where Maya had it.

### Locators and empty nulls

The FBX only carries what sits above an exported mesh. A locator used as a
placement control, and any group holding nothing but locators, therefore never
reached Blender at all — no object, no warning. They travel as their own JSON
records now, the way lights and cameras do, and arrive as Blender empties with
their Maya transform, their parent and their place in the group hierarchy.

A transform that *does* have a mesh below it is deliberately not recorded:
FBX already brings it as an empty, being an ancestor of an exported mesh, and
recording it twice would build two Blender objects for one Maya node.

A Maya group ends up represented twice on purpose. The collection is the
organisation, and the empty is what still lets the group be moved as a unit,
which a collection cannot do. Both now sit together: the group's empty is
inside the collection that mirrors it, rather than at the root while its
contents sit a level down.

Meshes parented under other meshes keep their parent — that relationship the
FBX does carry, and the test asserts it rather than assuming it.

### Instances

A Maya instance is several transforms sharing one shape. The exporter used to
read only the first of them, so **every instance but one disappeared** — no
object, no geometry, no warning. All of them are now exported, and each keeps
its own name, transform, visibility and place in the group hierarchy.

In Blender they become linked duplicates: the objects that came from one Maya
shape share a single mesh datablock, which is what Maya was expressing in the
first place and what keeps a scene of instanced set dressing from arriving as
thousands of unique meshes.

```text
Maya                                   Blender
treeSource ┐                           treeSource ┐
treeInstA  ├─ one shape       ->       treeInstA  ├─ one mesh datablock
treeInstB  ┘                           treeInstB  ┘
treeCopy    (a real duplicate)         treeCopy    (its own datablock)
```

Records that share a `shape_path` are what identifies them, so a genuine
duplicate — same geometry, separate shape — is correctly left alone. Which
object owns the shared datablock is decided by Maya's parent order rather than
by FBX import order, so the name is the same every time a package is re-sent.
The instances are counted on the panel's status line, and each linked object
records `ml_instance_of`.

### Referenced assets

Two references of one asset are the hardest naming case in Maya: both meshes
are called `body`, both sit in a group called `assetGrp`, and both use a
material called `assetShader`. The namespace is the only thing that separates
them, and stripping it left a scene of `body`, `body.001`, `body.002` with no
way to say which reference any of them came from.

The namespace is treated as part of the identity now:

- **The group trail leads with it**, so each reference becomes its own
  collection subtree. This also gives the same-name tie-break something to
  work with — without it two references share a trail as well as a name.
- **A name keeps its namespace only when it would otherwise collide.** A scene
  with one reference keeps clean short names; only the clashing ones become
  `heroA:body` and `heroB:body`.

Materials were already safe, being cached on their full name.

An FBX-brought group empty is placed in its collection when there is one
candidate and left alone when there are several: two references give two
collections whose last segment is `assetGrp`, and nothing in the empty's name
says which one it belongs to, so putting it in either would be a guess.

### Meshes with the same name

Two meshes under different groups sharing a short name (`|setA|twin` and
`|setB|twin`) is entirely normal in Maya. Matching records to objects **by
name** gave both the same score and one won at random: the meshes **swapped**,
each taking the other's materials, visibility and group.

The **parent chain** the FBX brings now breaks the tie, comparing the record's
group trail against the object's ancestor names. Its contribution is
deliberately kept below a full-path match, so a deep hierarchy can never
outscore a genuine one.

### Visibility and render flags

An object hidden from camera but casting shadows — one of the most common
setups in production — used to arrive fully visible. Ray visibility is now
transferred:

```text
primaryVisibility                 -> visible_camera
castsShadows                      -> visible_shadow
aiVisibleInDiffuseReflection      -> visible_diffuse
aiVisibleInSpecularReflection     -> visible_glossy
aiVisibleInSpecularTransmission   -> visible_transmission
aiVisibleInVolume                 -> visible_volume_scatter
aiMatte / holdOut                 -> is_holdout
visibility (transform)            -> hide_render + hide_viewport
lodVisibility                     -> hide_viewport
```

Arnold splits ray visibility more finely than Maya and reads its own `ai*`
attributes; Maya's `visibleInReflections` / `visibleInRefractions` are for
other renderers. Both are in the candidate list, Arnold's first.

**Only flags that differ from their defaults are written.** An ordinary mesh
produces no flags at all and Blender's own defaults are left alone, so the
transfer never applies something the source scene did not ask for.

A hidden Maya mesh is hidden in both the viewport and the **render**; hiding
only the viewport would let it reappear at render time.

These flags are **Cycles** features; EEVEE ignores ray visibility.

### Subdivision

Subdivision is **not** applied to every mesh, only where the Maya mesh actually
asks for it. Sources are checked in this order, because the renderer setting is
what actually renders and Maya's smooth preview is the fallback for intent:

```text
1. Arnold    aiSubdivType != none   -> aiSubdivIterations
2. Redshift  rsEnableSubdivision    -> rsMaxTessellationSubdivs
3. Maya      displaySmoothMesh != 0 -> smoothLevel / renderSmoothLevel
```

If none of them asks, no modifier is added. Arnold's `aiSubdivType` defaults to
**none**, so an unmodelled cube is left as it is rather than rounded off with
Catmull-Clark.

`catclark` maps to `CATMULL_CLARK` and `linear` to `SIMPLE`;
`aiSubdivUvSmoothing` maps `pin_corners` to `PRESERVE_CORNERS`, `pin_borders`
to `PRESERVE_BOUNDARIES` and `smooth` to `SMOOTH_ALL`. When
`useSmoothPreviewForRender` is off, viewport and render levels transfer
separately. The source is recorded in `ml_subdivision_source`.

> Packages older than schema 6 carry no subdivision record and those meshes are
> left unsubdivided. Before 1.9.0 every mesh was subdivided; re-sending the
> package is enough.

### Export scope

Ticking **Export Scope** sends only the selected objects instead of the whole
scene, which is what you want while iterating on a single asset.

- **The selection is expanded through groups.** Selecting an asset normally
  means selecting the group holding it, so reading the selection literally
  would export nothing in the most common case.
- **Lights and cameras always come in full.** A scene package without its
  lighting is not a scene, it is darkness. A light in the selection is
  mentioned in a warning rather than silently ignored.
- If the selection contains no meshes at all, the export **fails loudly**
  rather than leaving half a package behind.
- **Everything else obeys the scope too.** Locators, curves, sets and display
  layers are filtered by the same expanded selection, and a set or layer is
  trimmed to the members the package actually carries — one naming nothing in
  it is dropped rather than arriving in Blender as a warning and an empty
  collection.

---

### Selection sets and display layers

Maya sets and display layers become Blender collections, gathered under
`mLender Sets` and `mLender Layers` so they are never mistaken for the group
hierarchy. Objects are **added** to them, not moved: a set is a second way of
naming the same objects, not a different place for them, and a Blender object
can belong to several collections.

A display layer also carries state a collection cannot, so it is applied to
the members as well:

```text
visibility off      -> hide_viewport and hide_render on every member
displayType 1 or 2  -> hide_select, since Maya means "not meant to be grabbed"
```

Three exclusions, each measured rather than assumed. `shadingEngine` is its
own node type, so filtering on `objectSet` keeps material assignments out.
`defaultObjectSet` and `defaultLightSet` are *not* — they are genuine object
sets and are excluded by name. And **a set of components is reported, not
half-built**: Blender has no equivalent for "these three faces", so such a set
produces a warning rather than a collection that quietly means something else.

Set membership comes back from Maya as short names, which are ambiguous in a
scene where two meshes share one, so members are resolved to full paths before
they are written.

## Import modes

Chosen in the N panel. **Replace** is the default and unchanged.

| Mode | What a new package does |
|---|---|
| Replace | Wipes the scene and rebuilds it |
| Merge | Updates what an earlier import made, leaves your own work alone |
| Add | Brings the package in beside what is already there |

**Merge keeps the object.** A mesh that came from an earlier import of the
same Maya node has its geometry, materials, transform and visibility replaced
while the Blender object itself stays, so a modifier, a parent or a driver you
put on it survives. Only objects carrying the `ml_generated` marker are
adopted, so anything you made yourself is never touched.

Objects are matched on the Maya node they came from (`ml_maya_path`), not on
their Blender name. A name can be changed in Blender, and two Maya meshes can
share a short one — the same reason mesh matching needs a tie-break.

**Nothing is deleted for having left the package.** If a Maya node is gone,
the object it made is marked and counted, and the panel offers a button to
remove them. An import arriving over a socket is no place to destroy work
unasked, and that is exactly what Replace is for.

Merge also reuses the collections already standing rather than building
`mLender Import.001` and `props.001` beside the ones holding the same meshes.

Empties, curves and volumes are **rebuilt** rather than adopted, so the
previous ones are removed first. Without that they accumulated: a second merge
of the same package left `probeLocator.001` beside the locator already there.
Only objects the tool made are removed, so this never reaches your own work —
but it does mean a modifier put on an imported empty or curve, unlike one on a
mesh, does not survive a merge.

The three-pass scene clear, which raises if anything survives it, is not
softened by any of this. Merge and Add skip it; they do not weaken it.

## Render settings

Resolution, pixel aspect and motion blur travel with the package. It is a
small thing that decides whether a scene feels ready or merely present: a shot
framed for 1920x804 arriving into Blender's 1920x1080 is reframed, and every
judgement about the camera then looks wrong for a reason that has nothing to
do with the camera.

```text
defaultResolution.width / height   -> resolution_x / resolution_y
defaultResolution.pixelAspect      -> pixel_aspect_x, against pixel_aspect_y 1
(no Maya equivalent)               -> resolution_percentage forced to 100
motion_blur_enable                 -> use_motion_blur
motion_frames                      -> motion_blur_shutter
```

Arnold states the shutter as a length in frames and so does Blender, so that
number crosses untouched.

Two deliberate limits. **Resolution percentage is forced to 100** because Maya
has no equivalent and the scene datablock survives the import wipe, so a value
left at 50 by an earlier session would silently halve every render. And
**motion blur is read from Arnold only** — Redshift's attribute names cannot
be probed on this machine, and this project does not write names it has not
read off a live session, the same footing as the Redshift light anchor.

The frame range is not repeated here; it already travels with the animation
record.

## Colour management

This is the most common reason a transfer that is technically correct still
looks wrong: geometry, materials and lights all agree, but the two applications
tone-map differently.

Maya's colour management settings are written into the package and applied in
Blender:

```text
renderingSpaceName    ACEScg
viewTransformName     ACES 1.0 SDR-video (sRGB)
displayName           sRGB
configFilePath        ...\OCIO-configs\Maya2022-default\config.ocio
```

**A measured limitation:** Blender's own OCIO config has **no ACES view
transform in any version** (tried individually in 4.1, 4.5 and 5.2 — only
Standard, Raw, Filmic, Filmic Log, False Color, AgX, and Khronos PBR Neutral
from 4.5 onwards).

So the behaviour is:

- If Blender **has** the transform Maya asked for, it is applied. On a Blender
  pointed at an ACES config this matches exactly.
- If it does **not**, the closest defined transform is applied and a warning
  names both what was wanted and how to get it:

```text
Maya was using the "ACES 1.0 SDR-video (sRGB)" view transform, which this
Blender's colour config does not have; "Standard" was used instead. To match
exactly, point Blender at the same OCIO config through the OCIO environment
variable: C:/Program Files/Autodesk/Maya2023/resources/OCIO-configs/...
```

Leaving AgX in place and calling it a match would be the one genuinely
misleading outcome. With colour management off in Maya, the scene is treated as
raw linear and `Standard` is applied.

---

## Development

### Reloading

**Maya** — `importlib.reload(za)` is not enough; for a package it only
refreshes `__init__.py` and leaves the submodules stale.

```python
ml = ml.reload_package()
ml.show_ui()
```

`reload_package()` refreshes submodules in dependency order and returns the
refreshed package. Remember to reassign the result.

**Blender** — `F3 > Reload Scripts` is enough. `__init__.py` refreshes its own
submodules in order and `unregister()` closes the listener socket and timer. If
port 50505 stays bound, press **Stop LiveLink** first, then reload.

### Tests

```bash
# 1. Syntax
python -m py_compile mlender_exporter/*.py mlender_importer/*.py

# 2. Contract checks (no host required, seconds)
python tests/check_contracts.py

# 3. Real Maya + Arnold (~2 min)
"C:\Program Files\Autodesk\Maya2023\bin\mayapy.exe" tests/host/maya_export_test.py

# 4. Real Blender, reading the package step 3 wrote (~30 s)
"C:\Program Files\Blender Foundation\Blender 5.2\blender.exe" ^
    --background --factory-startup --python tests/host/blender_import_test.py
```

`tests/calibration/` holds the measurement rigs rather than tests: they do not
verify the calibration constants, they **produce** them. See
[`tests/README.md`](tests/README.md).

Note that the tests do not render. They verify that the calibration constants
are *applied*, not that they are *correct*. Changing a constant calls for a
visual comparison.

### Contracts

Two constants must stay in step across both packages, and a contract check
enforces it:

| | |
|---|---|
| `LIVELINK_VERSION` | bumped in both files together for a breaking protocol change |
| `EXPORT_SCHEMA_VERSION` | bumped in the exporter, added to the importer's `SUPPORTED_SCHEMA_VERSIONS` |

The channel keys the exporter produces must match the importer's socket
mapping exactly. A new channel belongs in exactly one of `PRINCIPLED_INPUTS`,
`GLASS_INPUTS` or `METADATA_CHANNELS`; the contract check catches one that is
in none of them.

Attribute names differ between Maya and renderer versions. Every semantic
channel keeps a **tuple of candidate names** and the first one that exists
wins. Support a new version by extending the tuple, never by branching the
logic. Order is priority: `aiAreaLight` carries both `exposure` and
`aiExposure` and Arnold uses `exposure`, while `aiSkyDomeLight` carries only
`aiExposure`.

### Repository

```text
origin     https://github.com/mena-works/mLender
upstream   https://github.com/hasancivili/MayaToBlender_Exporter
```

Commit messages are in English and follow `feat:` / `fix:` / `docs:`.
Behavioural changes update this README in the same commit.
