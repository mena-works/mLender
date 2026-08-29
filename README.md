# mLender

**Live scene transfer from Maya to Blender and Unreal.**

mLender packages a Maya scene as FBX plus a JSON sidecar, streams it to Blender
over a local socket, and rebuilds it there natively: meshes with their group
hierarchy and per-face material assignments, materials as Principled BSDF node
trees, lights as Blender lights, cameras as Blender cameras.

The same package also goes to **Unreal**, where a plugin rebuilds it as static
mesh actors, Material Instances, Unreal light actors and cine cameras. The
exporter does not know or care which receiver is listening: one sender, one
package format, two destinations. See [Unreal](#unreal).

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
- [Unreal](#unreal)
- [Scope](#scope)
- [Import modes](#import-modes)
- [How it works](#how-it-works)
- [Materials](#materials)
- [Lights](#lights)
- [Cameras](#cameras)
- [Animation](#animation)
- [Scene structure](#scene-structure)
- [Batch export](#batch-export)
- [Vertex colours](#vertex-colours)
- [Render passes](#render-passes)
- [Reports](#reports)
- [Colour management](#colour-management)
- [Development](#development)

---

## Requirements

| | |
|---|---|
| Maya | 2022 or newer |
| Renderers | Arnold (MtoA), Redshift, or native Maya shaders |
| Blender | 4.1 or newer — verified on 4.1, 4.3, 4.5 and 5.2 |
| Unreal | 5.8 — verified on 5.8.1. Optional; install it only if you send there |
| Dependencies | None. Standard library only, in all three. |

The three parts never import each other and have no shared module: they run in
three different Python runtimes. Their only contract is the LiveLink protocol
and the package JSON schema, and `tests/check_contracts.py` compares the
protocol constants of each receiver against the exporter's rather than checking
one pair — a constant that drifts in only the newest package is exactly what a
single comparison misses.

---

## Installation

### From a release

`packaging/build_release.py` writes the two artefacts each host already knows
how to install, and refuses to build if the Maya and Blender version numbers
have drifted apart:

```bash
python packaging/build_release.py     # writes dist/
python packaging/verify_release.py    # installs all three into the real hosts
```

```text
dist/mLender-<version>-blender-addon.zip   Preferences > Add-ons > Install
dist/mLender-<version>-maya-module.zip     unzip into a Maya modules folder
dist/INSTALL.md                            the steps, for whoever downloads it
```

`INSTALL.md` is generated rather than kept as a file, and a copy goes inside
the Maya archive next to the `.mod`. A version number in a document nobody
regenerates is a number that will be wrong, and an instruction naming last
release's zip sends people to a 404.

The Maya artefact is a **module**: a `.mod` file naming a folder beside it,
dropped anywhere on `MAYA_MODULE_PATH` — for example
`Documents/maya/modules/`. Maya then puts the exporter on its Python path
itself, so nothing shared has to be edited and removing the tool is deleting
two things.

`verify_release.py` is not a formality. It installs all three artefacts into
their real hosts: the module into a mayapy with a working directory the
repository cannot be reached from, the add-on into a throwaway Blender home,
and the plugin into the `Plugins/` folder of an Unreal project made there and
deleted afterwards. Each time it checks the import came from the artefact
rather than from somewhere else. All three were wrong once while this was being
written and only installing them showed it.

Two things about the Unreal leg are worth knowing. The plugin ships
`EnabledByDefault: false`, so dropping it into `Plugins/` is not enough — it
has to be enabled, which is what the install notes say and what the check now
does. And `Tools > mLender` cannot be verified headlessly: a commandlet has no
editor UI to hang a menu on, which the plugin says out loud rather than
failing. The check asks for what is checkable — that `register()` answered, and
that the startup line reached the log.

> The zip keeps `mlender_importer` as its top folder because that folder name
> **is** the add-on's module name. Rename it and Blender treats the result as
> a different add-on and installs it alongside the old one instead of updating.

The manual routes below still work and remain right for development.

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
| Collect Files | off | Copy referenced textures, volumes and standins into the package |
| Archive Package | off | Also write a single `.zip` beside the package |
| Export Scope | off | Send only the selected objects |
| Export Animation | off | Send a frame range instead of a single frame |
| Alembic Cache | off | Cache deforming meshes and emitting particles |
| Carry everything that moves | off | Carry every object whose transform moves, simulations included: deforming ones as a cache, the rest as sampled transforms |
| Bake Procedurals | off | Bake fileless shading networks to UVs |
| Bake Resolution | 1024 | Resolution of those bakes |
| Light Power Scale | 1.0 | Artistic multiplier over the measured conversion |

---

## Unreal

The Unreal receiver reads the **same package** the Blender add-on does. The
exporter is unchanged and does not know which receiver is listening, so there is
one sender, one package format and one schema for both destinations.

### Installing

The release archive holds a normal Unreal plugin folder, and it installs into
either a project or the engine:

```text
<YourProject>/Plugins/mLender/          per project — preferred
<Engine>/Engine/Plugins/mLender/        every project
```

A project install travels with the project and needs no administrator rights.
The engine folder lives under `Program Files` on Windows, so it needs elevation
and an engine update removes it.

For development, link the repository folder instead so `git pull` needs no
copying. The link's name must be `mLender`, matching the `.uplugin`:

```bat
mklink /J "<YourProject>\Plugins\mLender" "C:\path\to\mLender\mlender_unreal"
```

Restart the editor, enable **mLender** in `Edit > Plugins` if it is not already
on, and restart once more. The plugin needs Unreal's **Python Editor Script
Plugin** and **Interchange Editor**; the `.uplugin` asks for both, so enabling
mLender enables them.

#### The compiled module

The plugin is Python with one small C++ module, `Source/mLender`, holding the
actor that plays a simulation's movers (see [Carry everything that
moves](#carry-everything-that-moves)). The release archive ships it compiled
for Unreal 5.8.1 on Windows in `Binaries/Win64`, so a user needs no compiler.

A development link to the repository has no `Binaries` folder until you build
one. Build it against any project that has the plugin enabled — a throwaway
Blueprint project is enough — with the engine's own tool:

```bat
"<Engine>\Engine\Build\BatchFiles\Build.bat" UnrealEditor Win64 Development ^
    -Project="<YourProject>\<YourProject>.uproject" -WaitMutex
```

That needs Visual Studio 2022 17.14+ or 2026 with the **Desktop development
with C++** workload; the output lands in the plugin's `Binaries/` and
`Intermediate/`, both ignored by git. Opening the editor on a plugin with
`Source` and no `Binaries` gets the same offer to rebuild from Unreal itself.

Without the module the plugin still loads and everything else works; the
movers fall back to one Sequencer row each, which is the layout the module
exists to replace.

> The plugin folder in this repository is `mlender_unreal/` and the built one is
> `mLender/`, because Unreal names a plugin after its `.uplugin` file. The
> Python package inside is at `Content/Python/`, which is the only place Unreal
> puts a plugin's Python on `sys.path`.

### Using it

**In Unreal** — `Tools > mLender`:

1. Check the build number in the section header.
2. Press **Start LiveLink**.

**In Maya** — send exactly as you would to Blender. Nothing changes on the Maya
side, including the port.

Then read the Output Log: the import prints one summary line and one
`mLender warning:` line per thing that did not travel.

From Python, without the menu:

```python
import mlender_unreal
mlender_unreal.start_listener()
mlender_unreal.import_scene_package(r"C:\path\to\mLender_01")   # or directly
```

> **Unreal import replaces the level's actors, and this build does not save
> first.** The Blender receiver saves the .blend when it has a path; there is no
> equally safe unattended equivalent here, so saving is yours to do. The
> destructiveness is the same design decision described under
> [Import modes](#import-modes) — the Maya scene is the source of truth.

Only one receiver can hold the port at a time. Running Blender and Unreal
listeners together means the second one to start fails to bind; stop one first.

### What arrives

```text
Maya mesh + group hierarchy  -> StaticMeshActor, in folders mirroring the groups
Maya shader                  -> Material Instance of a generated master
Maya area / point / spot     -> Rect / Point / Spot light actor
Maya directional             -> Directional light actor
Maya dome                    -> Sky Light (intensity and colour)
Maya camera                  -> CineCameraActor, renderable one first
Maya locator / empty null    -> Actor, parented as Maya had it
NURBS and bezier curve       -> SplineComponent on a generated Blueprint
aiVolume (.vdb)              -> Sparse Volume Texture on a Heterogeneous Volume
aiStandIn / gpuCache (.abc)  -> Geometry Cache on a GeometryCacheActor
particle instancer           -> one StaticMeshActor per point, sharing the mesh
particle system              -> anchor, and the points its instancers scatter on
selection set, display layer -> Unreal Layer
package Alembic cache        -> Geometry Cache on a GeometryCacheActor
sampled motion (rigid sim)   -> one ML_MotionPlayer actor, keyed by a single float on the sequence
copies of one shape          -> one StaticMesh asset, shared by every actor that is that shape
```

**One asset per shape.** The FBX brings a mesh asset per object, and a layout
is mostly copies of a few blocks: measured on a shot, 12028 meshes over 4068
distinct shapes, and every one of the 7960 copies was an asset for Unreal to
build, save and load — the save alone took twenty minutes. So the exporter
writes each mesh a `geometry_key`, a digest of what it looks like (points in
object space, topology, normals, every UV set, the material slot structure and
the subdivision settings — not its transform, its name or which shader a slot
wears), and the receiver hands every actor with the same key the first asset
that arrived and drops the rest before anything saves them. A red block and a
blue block share the mesh and keep their colours, because materials go on the
component. A frozen duplicate, whose points sit at world positions under an
identity transform, is a different shape by this rule and keeps its own asset;
sharing it would need a pivot the receiver does not have.

The **Alembic cache is not an optional extra**. When the export caches, the
deforming meshes and emitting particles are written into the `.abc` *instead of*
the FBX, so without importing it those objects are not in the level at all. Its
axis and scale come from Unreal's own `AbcConversionPreset.MAYA`, asked for by
name rather than by writing the numbers again, and set explicitly rather than
left to a default that moves between versions.

Meshes, their hierarchy, their transforms and the unit conversion are brought by
Unreal's **Interchange** FBX import, which was measured correct and is therefore
left alone — this package contains no transform code for meshes at all. Doing a
correct conversion twice is the mistake that once made every light 318× too
bright here.

Assets land under `/Game/mLender/`, and a re-send deletes that folder before
rebuilding.

> **Known issue: re-sending into a saved level.** If a level that was saved
> after a previous send is open, deleting `/Game/mLender` leaves that level's
> actors pointing at assets that no longer exist, and the meshes the new import
> creates do not get hooked up — the import then reports meshes but no
> materials. It is reported per mesh rather than silent, and it names the fix:
> delete `/Game/mLender/Meshes` and send again, or send into an unsaved level.
> Measured: a fresh content root gives 2 materials on the same package where a
> re-import gives 0.

### Coordinates, units and energy

Maya Y-up right-handed becomes Unreal Z-up left-handed as a **plain Y/Z swap
with no sign flip**, `(x, y, z)` → `(x, z, y)`. This is *not* the Blender rule
`(x, -z, y)`: the handedness flip is absorbed by the swap. Both were measured
and they differ because the hosts differ.

Measured by exporting cubes on each axis and reading the actors Interchange
produced:

| Maya (cm) | Unreal |
|---|---|
| `(30, 0, 0)` | `(30, 0, 0)` |
| `(0, 40, 0)` | `(0, 0, 40)` |
| `(0, 0, 50)` | `(0, 50, 0)` |

One Maya centimetre is one Unreal unit.

**Import Scale** multiplies that. It reaches both halves of a send, which is
the only way it can be right: everything placed from the JSON — object motion,
cameras, locators, curves, sets — is multiplied by it directly, while the
meshes come through Interchange and are scaled by handing the same number to
that importer as its global offset. A scale that reached only one half would
tear a scene in two, geometry at its file size and everything else moved.

Measured on a shot of 11,008 meshes at `Import Scale = 10`: a ground plane of
2000 × 2000 × 4 units at `(0, 0, -2)` arrived as 20000 × 20000 × 40 at
`(0, 0, -20)` — a ratio of exactly 10 on all three axes, so the offset is
applied once rather than to the geometry and the actor both. All 7,467 moving
objects started the shot on the spot the FBX placed them, which is what says
the two halves agree.

Scaling a shot **in the level** is not an alternative for anything that moves:
the motion player writes the world transform of every mover on every frame, so
an actor scaled by hand is put back on the next one. The scale has to come from
the import.

Lights and cameras ride the JSON rather
than the FBX, so their conversion is this tool's own; a Maya light aims down
local −Z and an Unreal light down local +X, and the resulting basis was checked
against the engine to **1e-8** on all three axes.

**Light energy reuses the measured chain rather than a new constant.** Maya
intensity becomes flux in watts through the same π anchor the Blender receiver
uses — that number came from rendering Arnold against Cycles and solving for the
ratio — and watts become lumens by the photopic efficacy:

```text
Unreal lumens = 683 * pi * meters_per_maya_unit^2 * intensity * 2^exposure
```

Unreal is then left to convert from lumens itself, so the engine stays the one
authority for its own units rather than a constant here having to track it.

Measured end to end: a Maya light at intensity 80 and exposure 1 in a centimetre
scene reaches the Unreal component as **34.331326 lm** against a predicted
34.331325 — 0.000003%.

Setting that value needs the component's **setter**, not the property. Both
`intensity` and `intensity_units` are read-only to Python and raise
`Property 'Intensity' ... is read-only and cannot be set`. An early version of
this receiver assigned them inside a bare `try/except`: the write raised, the
exception was swallowed, and every light silently kept a spawned component's
default of 8 candelas — while a test that only asked whether the intensity was
positive passed. Both halves of that lesson are now in the test.

A directional light has no unit property at all and states lux, which is what
the sun branch already produces.

### What does not travel, and says so

Four things are left, each because Unreal has no equivalent this build can
honestly fill rather than because nobody got to them. Light, camera and
visibility animation used to be a fifth; it is carried now, as a Level
Sequence (below). Every one is **reported
with its count and the reason**, which is the `coverage.py` idea applied to the
receiving end:

| not carried | why |
|---|---|
| Advanced Skeleton **control layer** | Unreal's equivalent is a Control Rig asset, and authoring one from Python means building a rig graph. The skeletal meshes themselves do arrive — see below |
| coat tint and coat IOR | the coat weight and its roughness travel (below); Unreal's clear coat has no tint or IOR input at all |
| sheen, subsurface radius and scale | no Unreal input |
| skeleton root motion | the take plays; re-keying the sampled world truth on top of it would double the motion |
| Maya constraints | Unreal has no equivalent, and the FBX bake already carries the motion they produced |

### Blend shaders, as a graph of their own

A Material Instance shares one master and can only change its numbers. That is
right for nearly every material and it cannot express a stack of **shaders** —
two surfaces with different colours, roughnesses and maps, mixed by a weight.
So a blend shader gets a Material instead of an instance. This is the other
half of the hybrid the receiver was designed around.

Unreal has no shader-level mix — a material is a set of surface properties, not
a closure — but it has the node that mixes exactly those. Each layer becomes a
`MakeMaterialAttributes` fed from its own channels, and the layers are combined
with `BlendMaterialAttributes`. Every layer value lands as a named parameter
(`Layer0_BaseColor`, `Layer1`, …) so the graph stays adjustable in Unreal.

Two Maya sources arrive here and they spend their weight differently:

| source | weight | built |
|---|---|---|
| `aiMixShader`, `aiLayerShader` | `mix`, the weight of the upper layer | yes |
| `layeredShader`, `layer_texture` mode | transparency: what shows through from below | yes |
| `layeredShader`, `layer_shaders` mode | adds the upper layer to a scaled copy of what is under it | reported |

The last row is not a blend of surface properties at all, so it is named rather
than turned into a fade that would look plausible and be wrong.

One detail worth knowing if a send ever seems to ignore this: a material that
travelled as an *instance* in an earlier send leaves an asset under the same
name, and `create_asset` will not take a name that is in use. The stale one is
replaced. Measured — leaving it made the graph path return nothing and the
material silently fell back to the instance it was meant to replace.

### Layered textures

A `layeredTexture` stack takes the same route, for the same reason: a stack of
images with per-layer blend modes is structure, not numbers. Each layer becomes
a texture sample or a colour parameter, and the layers are combined bottom-up as
`lerp(lower, f(lower, upper), alpha)` — the shape every supported mode was
measured to have. Maya hands the layers top first, which is how the Attribute
Editor reads them, so the walk runs in reverse.

Seven modes are built (`over`, `multiply`, `add`, `subtract`, `difference`,
`lighten`, `darken`) and `none` replaces what is under it, ignoring its own
alpha — measured. The HSV and alpha-compositing modes (`saturate`,
`desaturate`, `illuminate`, `in`, `out`, `cpv_modulate`) are not per-channel
blends; each is named in a warning and left out rather than folded in as a fade
that would look close.

**Baking usually gets there first.** With Bake Procedurals on — the default —
the stack is resolved into one texture before any receiver sees it, so this
path only runs for packages sent with baking off. That is also why the host
test imports a second, unbaked package at the end: the stack does not exist in
the first one.

### Framing: film fit against the render aspect

Maya does not frame with the film back alone. It frames with the back, its
**film fit**, and the render resolution. Blender models that directly —
`sensor_fit` is the same idea — so its camera takes Maya's back untouched.

Unreal's cine camera has no fit. It frames on the filmback aspect, so handing
it Maya's raw back reproduces Maya's framing only when the render happens to
share that aspect. On this repo's own fixture it does not: a 36 x 24 back is
1.5 against a 1920 x 804 image. So the fit is **resolved into the filmback**
before it is written.

Which extent each fit keeps was measured by rendering, because Maya's own FOV
query ignores both the fit and the resolution and answered identically for all
four:

| fit | render wider than the back | render narrower |
|---|---|---|
| Horizontal | width | width |
| Vertical | height | height |
| Fill | width | height |
| Overscan | height | width |

The aspect comes from `width / height × pixel_aspect`, which is what the image
actually is. Maya's `deviceAspectRatio` is only a fallback: the UI maintains
it, and setting width and height directly leaves it stale — this repo's fixture
renders 1920 x 804 while still reporting 1.7778.

The resolution itself rides on the Movie Render Queue config, since that is
where a render resolution lives in Unreal.

### AOVs, as a render config

Render passes are not level contents in Unreal — they are Movie Render Queue
configuration. So the AOVs become a `MoviePipelinePrimaryConfig` asset in
`/Game/mLender/Render`: a deferred pass, an EXR output so the passes are layers
of one file, and one generated post-process material per AOV.

The mapping is by **quantity**, not by name, and that is the whole discipline.
Six of them name something Unreal writes into its GBuffer and carry exactly:

| Arnold | Unreal |
|---|---|
| `Z` | SceneDepth |
| `N` | WorldNormal |
| `albedo` | BaseColor |
| `motionvector` | Velocity |
| `opacity` | Opacity |
| `crypto_object` | the ObjectId render pass |

The rest name a **light transport** result. Arnold's `diffuse` is the diffuse
lighting response, not the diffuse colour, and Unreal's GBuffer holds the
surface property instead — `PPI_DIFFUSE_COLOR` next to a request for `diffuse`
looks like a match and is a different image. Those are reported by name with
what they are, rather than filled with something plausible.

The post-process materials are generated rather than pulled from
`/Engine/BufferVisualization`: measured, that path lists zero assets in this
build, and a generated material is reviewable the way the masters are.

### Correction nodes

Every texture slot in the master carries a small correction stack — a `Power`
and a switched `Clamp` — that is identity until a material sets it. Three Maya
nodes are rebuilt into it and the rest are still reported. `gammaCorrect` is `in^(1/gamma)`, which is why the
exponent Unreal gets is the **reciprocal** of the number Maya holds, and a clamp
is a clamp. `aiColorCorrect` was measured rather than guessed at, because it
carries exposure, gain, offset, contrast, saturation and hue at once and the
order they compose in decides the picture. Rendered one parameter at a time
with Arnold, the chain is:

```text
invert -> gamma -> contrast(pivot) -> exposure -> multiply -> add
```

Everything after the gamma is affine, so the whole tail folds into one multiply
and one add — which is why the stack needs two more nodes rather than six. The
full table is in `tests/docs/color_correct.md`.

`saturation` and `hueShift` work in HSV, not on channels, and a gain that
differs per channel cannot ride a one-scalar stack; both are named in a warning
rather than truncated to the red channel. 

`remapValue` is the one correction whose curve cannot fold into a number, so it
arrives as an asset: its stops are evaluated into a one-row 16-bit lookup
texture that the material samples with the channel's own value. Its input range
and output range fold into the row as well, so the material needs the sample
and no arithmetic around it. The curve maths lives in `utils.py`, which imports
no engine, so the contract test checks the knee without opening Unreal — a
receiver that ignored the stops and drew a straight line would read 0.4 where
this reads 0.9.

The clamp is switched rather than always on: clamping to 0..1 is not identity
for a channel that legitimately goes past one, and emission does.

What cannot be rebuilt is reported whether or not the texture loaded. A first
version only reported alongside a working texture, which meant the scene's one
colour correct node — sitting on a stub texture — produced no warning at all.

### Skeletal animation

The FBX brings an `AnimSequence` and used to leave it in the content browser.
Measured: four skeletal actors sat in `ANIMATION_BLUEPRINT` mode with no asset
while `Take_001` existed beside them, so a skinned character arrived in its bind
pose and never moved. Each skeletal actor is now handed the take that belongs to
its **skeleton** — matched that way rather than by name, since the FBX names the
take after the take.

It is stored twice, and the two are not the same thing: `set_animation` drives
the live instance and `animation_data` is what the level keeps. Setting only the
first left the assignment to vanish on the next map load.

Root motion is still reported rather than applied. The exporter samples each
root joint's evaluated world per frame because the FBX bake cannot be trusted
for motion driven by a connection; re-keying that on top of a take that already
plays would double the motion rather than correct it.

### Clear coat

A coated Arnold or Redshift surface arrives coated. Unreal keeps clear coat in
`CustomData0`/`CustomData1`, and the Python `MaterialProperty` enum does not
expose those — `MP_CUSTOMDATA0` is simply not in it. The way in is
`MakeMaterialAttributes`, whose `ClearCoat` and `ClearCoatRoughness` pins do
accept a connection; a nonsense pin name is refused, so the `True` those two
return means something. A coat master therefore routes **every** channel
through that node, which is why it is wired differently from the other masters.

Coat is a modifier on a surface class rather than a class of its own, because
Unreal keeps blend mode and shading model apart: a masked cutout can wear a
clear coat as happily as an opaque surface. The first version coated only
opaque materials and silently dropped the coat off a half-opacity one — the
test caught it.

Translucent and unlit surfaces do not take a coat: translucent clear coat is a
different lighting argument in Unreal, and an unlit surface answers no light at
all. Both are reported rather than approximated.

### UDIM sets

The exporter writes a `<UDIM>` token in the path and keeps the concrete tile it
came from. Unreal wants the concrete one — and then finds the rest itself:
measured, importing `tile.1001.png` with its siblings beside it produced a
single texture with **virtual texture streaming** switched on, which is how the
engine says it recognised a set. That flag is checked afterwards, so a set
whose other tiles are missing is reported rather than arriving silently as one
tile.

### The dome HDR

An Arnold sky dome drives Unreal's sky light, and its HDR now comes with it.
Measured: Unreal reads a Radiance `.hdr` straight into a **TextureCube**, so a
lat-long environment needs no conversion step — the sky light takes it with
`source_type` set to the specified cubemap. The result is checked rather than
assumed, because it is the import that decides: a format that lands as a plain
`Texture2D` cannot drive a sky light, and that is reported rather than left as
a black environment nobody can explain.

### IES profiles

A Maya photometric light brings its `.ies` file, which Unreal reads natively as
a `TextureLightProfile`. The profile shapes the light and deliberately does not
set its brightness: `use_ies_brightness` is left off so the measured intensity
conversion stays in charge, and two lights calibrated the same way do not end
up disagreeing.

### Reporting a channel that is switched off

A channel whose weight is zero changes nothing, so reporting it as lost is
noise. Measured on the test scene: coat was on in 3 materials of 31 and sheen
in 2, but `coat_ior` and `sheen_roughness` carry their defaults in all 31 — so
28 of the 31 warnings were about parameters of an effect nobody had switched
on, and the three real ones were buried in them. Dependent channels are now
gated on the weight that drives them.

### Object motion, and why the frame numbers look high

Meshes carry their animation **inside the FBX**, not in the package — the
package samples lights, cameras and visibility, and leaves geometry to the
format that already does it well. Unreal's Interchange does import that motion,
into a Level Sequence of its own, and writes every key at its frame number **as
a tick**. Measured on a 520-frame move: the keys land at ticks 1 and 519, so the
whole animation happens inside the first fiftieth of a frame and the object has
finished moving before frame one. On screen that is indistinguishable from
nothing having moved at all.

Those keys are read back and rewritten onto the mLender sequence at the right
time base, so one timeline carries the lights, the cameras, the visibility, the
material parameters and the object motion together. The compression is
**detected**, not assumed: keys that already span more than a frame are taken as
they are, so an engine build that fixes this will not have its animation
stretched by a thousand.

And the frame numbers: **Maya's own are kept**. A scene that plays 1001–1520
produces a sequence that reads 1001–1520, because a package that starts on
frame 1 in one application and frame 1001 in another is a conversation nobody
can have. If the sequence starts at 1001, that is the scene's start frame, not
an offset.

### The installer and a development checkout

A project whose `Plugins/mLender` is a **junction to a checkout** is left alone.
That link is the development setup — the editor loads whatever the repository
currently holds — and extracting over it would delete the link and leave a copy
that silently stops tracking. The installer says which projects it skipped and
why. `os.path.islink` does not answer this for junctions on Windows, so the
reparse attribute is read directly.

### Keeping the lighting a level already has

The import replaces the level, which is the tool's design and is documented
above. Two receiving-side options soften that for the case where somebody has
lit the level in Unreal and does not want it wiped on every send. They live in
`Tools > mLender`, because what a level already holds is not something Maya can
know about:

| toggle | what it does |
|---|---|
| **Keep Existing Lighting** | leaves the lights, sky, fog, post process volume and reflection captures the level already had |
| **Build The Package's Lights** | off means the package's lights are not rebuilt at all |

Keeping is not the same as keeping *everything*: lighting a previous send made
carries this tool's tag and is still replaced. Keeping that too would stack a
new copy of the package's lighting on top of the old one every time, which
looks like it worked until the exposure is wrong.

Sky, fog and post process count as lighting here. An artist who lit a level
placed those as well, and keeping the lights while deleting the fog leaves
something that looks nothing like what they set up.

`LiveLink Status` prints both settings, since a menu entry shows no tick.

### Simulation

A rigid body simulation carries. Measured with a Bullet sim: the solver drives
the transform with **no animation curve and no incoming connection**, so
nothing that looks for keys can see it — but the FBX export bakes the frame
range by stepping the scene, which evaluates the solver, and the motion is in
the file. From there it takes the same route as any other object motion.

Two things follow from that. The simulation has to have been **played through
in Maya** before exporting, the way it would be before rendering; and Export
Animation has to be on, since a single frame export bakes nothing. The solver
node itself is reported as not carried, which is correct — it is the motion
that travels, not the simulation.

### If nothing animated arrives

**Export Animation is off by default.** With it off the package carries a
single frame, so there is no Level Sequence to build, no visibility keys and no
camera timeline — in either receiver. That is a legitimate way to send a
lookdev still, and it used to be a silent one: the scene's animation was
dropped in Maya without a word, and the receiver had nothing to report because
nothing had arrived.

Both halves of that are closed. The exporter now names what a single frame is
leaving behind — the cameras that move, the lights, the objects whose
visibility is keyed, the ones that travel — and says which box to tick. And the
receivers repeat **everything Maya said**: until a real scene turned up, the
exporter wrote its warnings into the package and nothing on the other side ever
read them, so coverage, tessellation and frozen-channel warnings were all
written for somebody who never saw them. They appear now prefixed with
`Maya said:`.

### Animation, as a Level Sequence

The FBX brings mesh and skeletal animation with it. Everything else the
exporter samples — a light that brightens, a camera that racks focus, a mesh
that blinks — is rebuilt as a **Level Sequence** in `/Game/mLender/Sequences`,
with an actor in the level that plays it. Maya frame numbers are kept, so the
same package starts on the same frame in Blender and in Unreal.

| keyed | where it lands |
|---|---|
| light transform | transform track on the light actor |
| light intensity | `Intensity` on the light **component** binding, through the same measured conversion the static value uses |
| light colour | `LightColor` on the component binding |
| camera transform | transform track on the camera actor |
| camera focal length, aperture | `CurrentFocalLength`, `CurrentAperture` on the cine camera component |
| mesh visibility | visibility track, keyed `True` for visible |
| keyed material parameters | a component material track on the mesh slot, scalar and colour |

The sequence is built on the engine's own tick base — **24000 ticks to a
second**, against a display rate of 24 — rather than one tick per frame. That
matters for rendering: the Movie Render Queue splits an open shutter into
`TemporalSampleCount` steps, so with one tick to a frame eight samples over a
180° shutter are 0.0625 of a tick apart and land on the same instant —
accumulated motion blur accumulating eight copies of one pose. At 24000 the
same eight sit 62.5 ticks apart.

The base is the engine's business, not the script's. **Every call in
Sequencer's Python surface takes display frames**, and the tool hands it Maya
frame numbers unchanged. Measured in this build on a sequence at 24000/24:

| call | given 24 | given 24000 |
|---|---|---|
| `section.set_range(0, n)` | end **1.0000 s** | end 1000.0000 s |
| `channel.add_key(FrameNumber(n), …)` | tick **24000** | tick 24,000,000 |
| `key.get_time()` with no unit | reads display frames | — |

`AddKey` and `GetTime` take an `EMovieSceneTimeUnit` that defaults to
`DisplayRate`; `SetRange` has no tick form at all. The tool names the unit at
every call rather than leaning on that default. Read the times back in the
default unit and divide by ticks-per-frame and a sequence whose keys sit at
frame 600000 reads back as "frames 1–600" — which is how a broken one passed
a check once.

Raising an **existing** sequence's tick base does not move its keys.
`set_tick_resolution` calls the engine's own `MigrateFrameTimes`, but measured
here it moved the playback range and left the channel keys on their raw tick
numbers — base 24 → 24000 with keys still at `[1, 2, 3]`. Send again instead;
the sequence is rebuilt.

Four things about Sequencer were measured rather than assumed, and each of them
accepts a wrong value without complaining:

- **The Python surface takes display frames**, per the table above, and the
  underlying tick resolution only decides how much room there is between two
  frames. `set_playback_end(33)` reads back as 1.375 s at 24 fps;
  `set_playback_end(33000)` as 1375 s. Nothing here may multiply a frame by
  the tick base — no read-back catches it, because every call accepts the
  wrong number in silence.
- **A component property is keyed on the component's own binding**, not the
  actor's.
- **Visibility is keyed `True` for visible**; the engine's own flag is `hidden`,
  which is the other way round.
- **Scrubbing to the last frame finishes the sequence** and restores the
  pre-animated values, so a check that reads there sees the actor's spawn state
  and concludes nothing was keyed.

**Save the level before you send.** A Sequencer binding is stored as a path
inside the world it was made in, so a send into an unsaved level that is given
a name afterwards leaves the tracks intact and every one of their objects
missing — Sequencer draws each row red, "the object bound to this track is
missing", and the timeline plays nothing. Measured on a headless send that
imported into `/Temp/Untitled_0` and saved the level afterwards: 73 of 73
bindings resolved to nothing while all of their actors were still in the level
under the right labels, and a binding made in the saved world resolved on the
same asset in the same session. The import now says so in its warnings rather
than leaving it to be found in the Sequencer; the meshes, materials and lights
are unaffected, so the fix is to save the level and send again. A script that
drives the import headlessly has to `load_map` the destination **first** and
save in place, never `save_map` to a new path afterwards.

A fifth thing was measured after the first four, while adding keyed material
parameters: **the material parameter API does not use the same time unit**. On
one sequence, a transform channel handed 1000 stores 1000 and
`add_scalar_parameter_key` handed 1000 stores 1 — it divides by ticks per
frame. The first version passed plain ticks and put twenty-five keys inside the
first twenty-five ticks, which reads as "nothing is animated" because every
scrub lands past the last key.

### Skinned meshes and Advanced Skeleton

**Skinned meshes arrive as skeletal meshes**, with a Skeleton and a
PhysicsAsset, matched to their Maya record and carrying the rebuilt materials.
Interchange does this on its own — measured on the test package: four skeletal
meshes beside forty-seven static ones, with no pipeline configuration of any
kind.

That was found by measuring rather than by reasoning, and it corrected an
earlier diagnosis in this file. The receiver had been filtering its own results
on `StaticMeshActor`, so those four skeletal actors landed in the level and were
then ignored: unmatched, unnamed, still holding the FBX's placeholder materials.
The fix was to stop ignoring them, not to reconfigure the import.

**A slot name says which material, not which object.** Interchange collapses a
skinned character into **one** skeletal mesh carrying a slot per shading group,
while the package still describes the many meshes Maya had. Matching each slot
only against the record whose name the actor took then leaves the rest holding
placeholders — measured on a character: the actor arrived with 33 slots, the
record it matched held 1, and 3 materials were built for a scene that has 29.

So a slot that its own record cannot explain is looked up across the **whole
package**, and Interchange's uniquifying `_ncl_N` tail is stripped first. Same
character, same package: 29 materials, and the unmatched slots fell from 33 to
5. That lookup is tried **last**, after the positional cases — a shared mesh
asset carries the slot names of whichever mesh brought it, so there the index
is the evidence and the name is not.

The five that remain are not a failure to match; they are a scene the name
cannot resolve. A referenced rig brings its own copy of a shader under a
namespace, so the package really does hold two different materials called
`lambert20` — `lambert20` and `Character_Pars_Rigging:Model:lambert20`, on
`scalp2` and its namespaced twin. Interchange hit the same collision and spelled
the second slot `lambert20_ncl_1`. Nothing in the slot says which is wanted, so
**both candidates are named in a warning and neither is assigned**:

```text
slot 0 ("lambert20") names 2 different Maya materials
(Character_Pars_Rigging:Model:lambert20, lambert20); nothing was assigned
because the slot does not say which. Renaming one of them in Maya resolves it.
```

Picking one would be a guess, and this project has already shipped one name
collision that drew the wrong shape.

**Subdivision travels but only one receiver can act on it.** A mesh record
carries the scheme and the iteration count, and the Blender add-on turns that
into a modifier. Unreal has no equivalent for a skeletal mesh, so a character
Maya and Arnold render as Catmull-Clark arrives there as its base cage.
Measured on one: 55 of 134 exported meshes ask to be subdivided, the body
among them, and the result is visibly faceted.

The only place the decision can still be made is where the geometry is, so the
export can bake it in:

```bash
mayapy -m mlender_exporter.batch --scene shot.ma --out packages --smooth
```

`apply_subdivision` defaults to **False**. When it is on, each **unskinned**
mesh that asks for subdivision is smoothed at its own scheme and iteration
count -- never blanket, for the same reason `subdivision_info` is picky:
rounding off hard surface geometry that was never modelled smooth is worse
than leaving it. The scene is not changed; the `polySmooth` nodes go away
again in a `finally`, beside the NURBS stand-ins.

**A skinned mesh cannot be helped this way, and the first version of this
claimed otherwise.** FBX carries a skinned mesh as its base geometry plus
weights, so a `polySmooth` downstream of the `skinCluster` never reaches the
file. Measured on a character: the scene did go from 140 726 faces to
592 955 -- a ratio of 4.21 -- and the FBX grew by **3.8%**, because 61 of the
64 meshes asking for subdivision are skinned and only the three unskinned ones
travelled. The scene measurement was real and proved nothing about the export;
the number that mattered was the two FBXs side by side, 340 310 vertices
against 353 096.

Skinned meshes are now left alone and counted in a warning. Getting them
subdivided means subdividing the bind mesh and transferring weights, which is
a rigging change rather than an export one.

Records for smoothed meshes then say `subdivision.enabled = false` with
`source = "applied_at_export"`. Without that the Blender receiver would build
a modifier on top of geometry that had already been subdivided and smooth it
twice.

**A hidden mesh cannot be hidden once it has been welded into another.** The
tool carries hidden meshes and hides them on the receiver, which is deliberate
and stays the default: a shot measured 4843 of its 7106 meshes hidden, and
dropping them would have lost colliders a later pass wanted. That only works
while each mesh is its own actor. Interchange merges a skinned character's
meshes into one skeletal mesh, and then there is no actor left to hide.

Measured on a character: fifteen hidden meshes arrived welded into the same
asset, among them a `Body_geoBase` — no skin cluster, so it does not deform,
and the *same* material as the visible body — which drew a second, T-posed
body through the posed one. Hiding the section cannot help, because that
section is shared with the real body.

So the choice is made at export instead, and only when asked:

```bash
mayapy -m mlender_exporter.batch --scene shot.ma --out packages --no-hidden
```

`export_hidden_meshes` defaults to **True**, so nothing changes for anyone who
does not ask. What is left out is counted and named in the export warnings.

Two routes that look right and are not, both tried:

- `FbxImportUI.import_as_skeletal` turns *every* static cube into its own
  one-bone skeletal mesh — 50 Skeletons from this fixture.
- An `override_pipelines` entry is **accepted without complaint and imports
  nothing** (`import_scene` returns true, zero assets). The property also wants
  a soft path rather than a pipeline instance, and `auto_detect_mesh_type` is
  deprecated in 5.8.

What is still missing is the **control layer**. Unreal's equivalent of AS's FK
controls and IK chains is a Control Rig asset, and authoring one from Python
means building a rig graph. The manifest is attached to each skeletal actor as
`ml_as_*` tags, and every chain is named in the warnings with everything a
rebuild would need:

```text
mLender warning: Arm L: Shoulder_L -> Elbow_L -> Wrist_L, IK "IKArm_L",
pole "PoleArm_L", switch "FKIKArm_L" (blend 10.0) -- not rebuilt.
```

Within the kinds that do travel, five limits are reported per item rather than
hidden:

- A **particle system** arrives as an anchor. Unreal has no point-cloud
  primitive an add-on can fill — Niagara is the answer and authoring a Niagara
  graph from Python is a project, while `PointCloud` and `LidarPointCloud` are
  both absent from this build. Its points are still used by any instancer that
  scatters onto them, which is where they become visible.
- An **instancer** makes one StaticMeshActor per point rather than an
  InstancedStaticMeshComponent, because a component cannot be added to a level
  actor from Python here. The geometry still exists once; the cost is actors in
  the outliner, and a scatter above 2000 points says so.
- A **volume** attaches its VDB but gets no volume material, so check its
  shading. A per-frame VDB sequence arrives as the single recorded frame.
- A **standin** in `.usd` or `.ass` anchors rather than loading: there is no USD
  stage actor in this build and nothing outside Arnold reads `.ass`.
- Materials still lack coat and sheen, correction chains and layered stacks, as
  above.

Anything referencing a file that is not on disk **anchors at its transform with
the path on it as a tag** rather than vanishing — the same decision the Blender
receiver makes, because a package opened on another machine legitimately lands
there and empty space explains nothing.

Unreal actors have no custom properties, so the Maya originals ride along as
`ml_*` tags on the actor. That is the job `ml_source_*` does on the Blender
side: when a number is disputed, this is the reference.

Within materials, three limits are reported per material:

- **Unreal has no coat or sheen input.** `unreal.MaterialProperty` was probed on
  5.8.1 and exposes base colour, roughness, metallic, specular, normal,
  emissive, opacity, opacity mask, subsurface colour, anisotropy and refraction
  — and nothing for coat or sheen. Those channels are kept as metadata and
  named in a warning rather than folded into an input they are not.
- **Correction node chains are not rebuilt.** The texture is wired directly and
  the correction is reported. **Bake Procedurals** carries it.
- **Layered texture stacks are not rebuilt**, and are reported the same way.

Also not carried yet: UDIM tile sets, IES profiles, and the dome's HDR cubemap
(the sky light gets its intensity and colour only).

### Materials, and why there are four masters

Unreal keeps blend mode and shading model on the **Material**, not on the
instance. A Material Instance can override a parameter but not whether a surface
is opaque, masked, translucent or unlit, so one master material cannot serve a
scene holding glass, a cutout and an unlit shader.

The receiver therefore generates one master per surface class — Opaque, Masked,
Translucent, Unlit — and makes each Maya shader an instance of the right one.
The masters are built from Python rather than shipped as `.uasset` files: a
binary asset in the repository is one nobody can review, and it would need
rebuilding for every engine version.

Optional textures use a lerp against the flat value driven by a scalar
parameter, rather than a static switch. It costs a texture sample that is then
discarded and buys instances that need no shader permutation, which is the whole
reason to use instances.

### The render comparison, and what it did and did not settle

The Arnold-versus-Unreal render comparison has been run, against the same
`arnold.exr` reference the Blender half uses. It settled some things and
explicitly failed to settle the main one.

**Settled.** The energy formula is exact (0.000003%, above). Geometry, camera
and light direction all transfer correctly — read off the rendered level, the
ground sits at the origin spanning ±200, the light points straight down
`(0, 0, -1)`, and the camera's forward vector gives back Maya's −14° pitch. The
horizon lands where the geometry says it should, to within one grid cell.

**Not settled by this comparison: absolute brightness.** The ratio came out at
a mean of 260× Arnold with a 45% spread, and the rig failed its own symmetry
control — Arnold renders the symmetric scene symmetric to five digits while this
capture's two sides differed by 13.4%. The comparison step asserts that and
refuses to print a verdict, because a symmetric scene that does not render
symmetrically is measuring the rig. Worse, the capture would not respond to any
control: global illumination off via the console variable, via the capture's own
`show_flag_settings`, and via the project's `DefaultEngine.ini` all left the
result bit-identical, so no hypothesis could be eliminated.

The underlying problem is that **Arnold's pixel values are in its own arbitrary
scale**, so a ratio against them can never be absolute in the first place. That
is what the next rig fixes.

### Absolute brightness — verified against physics

`light_absolute_maya.py` and `light_absolute_unreal.py` settle it by comparing
Unreal against a **closed-form answer** instead of against Arnold. A Lambertian
plane under a small light at a known height has a luminance that can be
computed:

```text
candelas  = lumens / (4pi)          Unreal's own conversion, measured
lux       = candelas * cos(theta) / d^2
luminance = lux * albedo / pi       nits, for a Lambertian surface
```

The lumens come from the receiver's own `light_intensity_for_unreal()`, so the
production conversion is what is under test, and the prediction is averaged over
the same pixels that are sampled rather than taken at the centre.

The camera looks straight down from directly above, which makes the image
rotationally symmetric and turns left/right *and* top/bottom into symmetry
controls. That alone took the rig's asymmetry from 13.4% to **0.29%**, which
identifies the earlier failure as the tilted composition sampling a blotchy
field — a rig fault, not a transfer fault.

Each variant moves exactly one term:

| variant | lumens | measured | predicted | ratio | size/distance |
|---|---|---|---|---|---|
| base, 150 cm | 34.331 | 0.278716 | 0.292513 | **0.9528** | 0.133 |
| twice the distance, 300 cm | 34.331 | 0.072636 | 0.076206 | **0.9532** | 0.067 |
| twice the intensity | 68.663 | 0.557432 | 0.585027 | **0.9528** | 0.133 |
| one more stop | 68.663 | 0.557432 | 0.585027 | **0.9528** | 0.133 |
| half the distance, 75 cm | 17.166 | 0.458615 | 0.505630 | 0.9070 | 0.267 |

**Over the variants where a point source is a fair approximation the ratio is
0.9529 with a 0.034% spread.** That is the verification:

- **Inverse square is right** — doubling the distance leaves the ratio put, so
  the squared scene-unit term and the `1/d²` falloff are both correct.
- **Linearity is right** — doubling intensity leaves the ratio put.
- **Exposure is right** — one more stop and twice the intensity produce
  *bit-identical* measurements, so `2^exposure` is exact.

The residual 4.7% belongs to the prediction rather than the transfer, and the
variants say so: the ratio tracks how far the point-source assumption is being
stretched (0.067 → 0.9532, 0.133 → 0.9528, 0.267 → 0.9070). A 20 cm rectangle
is not an isotropic point, and the approximation degrades as the light
approaches — which is the direction observed.

So **Unreal's `SCS_SCENE_COLOR_HDR` is luminance in nits** (1.0 ≈ 1 cd/m²), and
the light energy chain is absolutely correct. Leaving **Light Power Scale** at
its default of 1.0 is the physically correct choice.

Getting a real headless render at all took three attempts, and the two that
failed are worth knowing: a commandlet never executes render commands (a target
cleared to `(0.25, 0.5, 0.75)` reads back `(1, 0, 0)`), and Movie Render Queue
is not installed in this engine build. The working route is a project startup
script that captures from a tick callback in the real editor.

Two traps in that route are recorded because they cost a run each. Importing a
package **pumps Slate ticks**, so a tick callback re-enters itself — the first
version recursed twenty-one imports deep and took the editor down with
`RecursionError`; both rigs now hold a re-entrancy guard. And setting a Material
Instance parameter from Python stores the value (the read-back confirms it) but
**does not reach the render**, while light changes in the same rig do; the
albedo variant was dropped for that reason and says so in the file.

The `Tools > mLender` menu is the other thing still unverified: a commandlet has
no Slate UI, so `find_menu` finds nothing there. The plugin detects that, logs
it and still works from Python. Confirming the menu needs the GUI editor.

Measurements, the traps behind them, and one claim this file previously got
wrong are recorded in
[`tests/docs/unreal_calibration.md`](tests/docs/unreal_calibration.md).

---

## Scope

### What did not travel

Discovery is type by type, so anything the exporter does not look for used to
leave the scene without a word. Measured, six kinds were doing exactly that:
NURBS surfaces, Maya subdivision surfaces, `gpuCache`, `aiStandIn`, fluids and
hair systems.

Adding a discovery module per kind would have fixed those six and left the
seventh silent. Instead every renderable shape is compared against what the
package carries, and whatever is left over is reported, grouped by type with a
count and an example:

```text
mLender warning: 1 "aiLightPortal" object(s) were not exported; this build
does not carry that type. First: |aiPortal
```

A kind nobody has thought of yet is now a line the user can read rather than
geometry that quietly is not there.

### Surfaces that are not meshes

NURBS surfaces and Maya subdivision surfaces are geometry a lookdev pass cares
about, and reporting them is not the same as carrying them: product and
industrial scenes are largely NURBS. Three routes were measured.

| Route | Result |
|-------|--------|
| Let the FBX carry it | It does — and it arrives a `nurbsSurface`, so no receiver sees geometry. A Maya subdivision surface does not survive the trip at all. |
| Rebuild natively in the receiver | Blender has NURBS surfaces but cannot represent a **trimmed** one, and trims are most of why anybody models in NURBS. |
| Tessellate during the export | What this does. |

Each surface gets a temporary polygon stand-in that takes the original's parent
and its name, so it lands in the right group, keeps its material and its sets,
and every receiver treats it as the mesh it is standing in for. The scene is put
back in a `finally`: the originals get their names back and the stand-ins are
deleted, whether the export succeeded or threw.

The trim comes with it, and all three hosts agree on the number. Measured on
the test panel: 1024 faces untrimmed, 448 trimmed; the FBX carries 448 polygons
and 896 triangles; Blender reports 448 polygons and Unreal 896 triangles.

Reading that number back in Unreal has a trap worth knowing. Nanite is on for
imported meshes by default, and `get_num_triangles()` then reports the
**fallback** mesh, which is built to a budget: the 896-triangle panel and a
3968-triangle sphere both read back 256. `get_num_nanite_triangles()` is the
source geometry.

Two smaller things fall out of the same measurement. `nurbsToPoly` and
`subdToPoly` leave their output selected, which silently replaced the user's
selection — a scoped export then carried a surface nobody had picked, so the
selection is saved and restored, with a surface that *was* selected represented
by its stand-in. And a trim leaves one curve-on-surface per region behind;
those are construction data, not scene curves, so they are neither exported nor
counted as lost.

```text
mLender warning: 3 NURBS or subdivision surface(s) were tessellated to polygons
for the export: nurbsBall, trimmedPanel, subdivBall. They arrive as meshes,
which is what every receiver can read; the originals are untouched in Maya.
```

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

Ticking **Collect Files** copies everything the package references into it and
rewrites the JSON paths, making the package portable:

```text
mLender_01/
  mLender_01.fbx
  mLender_01_scene.json
  textures_collected/
    wood_basecolor.tx
    tile.1001.tx
    tile.1002.tx
  files_collected/
    smoke.vdb
    hero_prop.abc
```

The option used to collect textures only, which made it a half promise:
measured, a package built with collecting on carried its texture and left the
VDB and the Alembic standin sitting outside it. Volumes and standins are
collected too now, into their own folder because they are not textures.

**Archive Package** writes `mLender_01.zip` beside the folder, with the folder
as the archive's only top level so unzipping produces what the importer wants.
It is written beside the package rather than instead of it: LiveLink and the
importer both read the folder. Pair it with collecting — an archive of a
package that still points at the exporting machine's texture library is a zip
of some paths.

### A package that has moved

A package records absolute paths, written by whichever machine exported it, and
collecting copies files inside the package but still writes the absolute path
to the copy. So a collected package opened anywhere else — another machine,
another drive letter, a folder somebody renamed — used to resolve none of them
and report every texture as not found.

On import, any recorded file that is missing is now looked for inside the
package before it is given up on: the package root first, then
`textures_collected/` and `files_collected/`. The FBX and the Alembic already
did this for themselves; it now covers textures, UDIM tile sets, the images
behind projections, the layers of a layered texture, volumes and standins.

A path that still resolves is left exactly as written — the common case is both
applications on one machine, and rewriting there would change something for
nothing. The import result reports `repointed_paths` so the difference is
visible.

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

The order below is the one the two packages reload in — `SUBMODULES` on the
Maya side and the reload block on the Blender side — so it is the dependency
order rather than a description of it.

```text
mlender_exporter/        # Maya side
  constants.py              # protocol constants, attribute alias tables
  mayautils.py              # maya.cmds wrappers and value helpers
  collect.py                # optional file collection
  animation.py              # frame range and timeline sampling
  textures.py               # upstream texture search
  bake.py                   # baking procedural networks to UVs
  tessellate.py             # NURBS and subdiv surfaces as temporary polygons
  shaders.py                # shader to channel extraction
  meshes.py                 # mesh discovery, material and face assignment
  transforms.py             # locators and empty nulls
  curves.py                 # NURBS and bezier curves
  volumes.py                # aiVolume (VDB path)
  standins.py               # aiStandIn and gpuCache (file references)
  particles.py              # particle points, per frame bake
  instancers.py             # particle instancer
  coverage.py               # what the export did not account for
  render.py                 # resolution, aspect, motion blur
  sets.py                   # selection sets and display layers
  lights.py                 # light discovery and records
  cameras.py                # camera discovery and lens records
  fbx.py                    # MEL FBXExport wrapper
  alembic.py                # AbcExport for deformed meshes and emitters
  livelink.py               # TCP client
  package.py                # package folder, JSON, archive, atomic cleanup
  ui.py                     # Maya window

mlender_importer/        # Blender side (multi-file add-on)
  constants.py              # protocol constants, socket names, calibration
  utils.py                  # value and name normalisation, path resolution
  attributes.py             # custom properties
  transforms.py             # Maya to Blender matrix conversion
  colormanagement.py        # Maya OCIO settings to Blender view transform
  animation.py              # sampled animation as keyframes
  images.py                 # texture loading, UDIM
  corrections.py            # rebuilding Maya correction nodes
  materials.py              # node trees
  lights.py                 # Blender lights, dome world
  cameras.py                # Blender cameras
  scene.py                  # scene clearing, mesh matching, subdivision
  empties.py                # locators as empties
  curves.py                 # Blender curves
  volumes.py                # Blender volume objects
  standins.py               # standin anchors and their contents
  particles.py              # vertex-only meshes and position keys
  instancers.py             # vertex instancing
  render.py                 # scene render settings
  sets.py                   # sets and layers as collections
  merge.py                  # Replace / Merge / Add
  fbx.py                    # FBX import, package file resolution
  alembic.py                # reading the package cache
  importer.py               # orchestration and schema validation
  livelink.py               # socket listener and main-thread pump
  ui.py                     # operators, properties, panel

packaging/
  build_release.py          # the two installable artefacts
  verify_release.py         # installs all three into the real hosts

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
`aiOpenPBRSurface`, `aiLambert`, `aiFlat`, `aiMixShader`, `aiLayerShader`

**Native Maya** — `lambert`, `blinn`, `phong`, `phongE`, `rampShader`,
`surfaceShader`, `layeredShader`

### Blend shaders

`aiMixShader` and `aiLayerShader` do not describe a surface, they blend other
shaders. They arrive as a **Mix Shader** chain: the bottom layer first, each
layer above it mixed over the accumulated result by its own weight. Every
sub-shader is built by the same code as a standalone material, so a glass or
an unlit shader inside a mix behaves the way it would outside one, and a blend
shader nested inside another one keeps its structure.

The direction was measured rather than assumed. Rendering an unlit red under
an unlit green at `mix 0.25` gives `(0.75, 0.25, 0)`, so Arnold's `mix` is the
weight of the **upper** shader. Blender's Mix Shader factor runs the same way,
so the number travels unchanged.

`aiLayerShader` slots that are switched off do not travel. Three connected
inputs with `enable3` unticked produce two layers, not three, because a layer
Maya was not rendering has no business appearing on top in Blender.

Maya's own **`layeredShader`** joins them, and it is the odd one of the three:
its index 0 is the *top* layer, and its weight is a **transparency** — how
much of what is below shows through — rather than a mix. It also has two
compositing modes that spend that number differently. Both were measured by
baking an unlit green over an unlit red at five transparencies:

```text
compositingFlag   T=0     T=0.5           T=1        meaning
Layer Shaders     green   (0.5, 1.0, 0)   (1,1,0)    upper + T x below
Layer Texture     green   (0.5, 0.5, 0)   red        lerp(upper, below, T)
```

The green holding at 1.0 in the first row is the whole difference: **Layer
Shaders adds**, it does not fade the upper layer out. It is also Maya's
default, so it is not the rare branch. It becomes an **Add Shader** with the
lower layers scaled against a Transparent BSDF; Layer Texture becomes a plain
**Mix Shader**. Neither inverts the number — the wiring is what differs, with
the upper shader on the Mix Shader's first input so a transparency of 0 reads
straight through as "the upper layer wins".

Maya's transparency is a colour and a mix factor is one number. A tinted
transparency is averaged and reported in the import warnings rather than
quietly picking a channel.

> Before this, a `layeredShader` anywhere in the scene **failed the entire
> export**. Every unknown shader fell through to the native reader, which
> reads `.color`; a `layeredShader` answers to that name only through an
> index, so Maya raised and the package was rolled back. Blend shaders now
> report no channels of their own, and a plug that cannot be addressed costs
> one channel instead of the export.

Transferred channels: base colour, reflection roughness, metalness,
normal/bump, opacity, emission colour and strength, specular weight,
transmission (weight, colour, roughness), IOR, thin-walled, and the coat, sheen
and subsurface lobes.

### Layered textures

Maya's `layeredTexture` stacks textures inside a single channel, which is a
different thing from the blend shaders above: those blend whole surfaces, this
blends the colour going into one socket. It used to be walked straight past —
measured, a two layer stack arrived as its bottom texture alone, with the
layering reported as an unsupported correction but not carried.

It now arrives as a chain of **Mix Color** nodes, one per layer, built from
the bottom up. Each layer's own colour goes through the ordinary channel
wiring, so a layer holding a file with its placement, a UV set, a projection
or a gradient needs none of that repeated.

Everything below was measured by baking each mode in Maya 2023 and reading the
pixels back, because the node does not evaluate through `getAttr` in batch:

```text
Maya blendMode          Blender Mix blend type
None                    the layer replaces what is under it, alpha ignored
Over                    MIX
Add                     ADD
Subtract                SUBTRACT
Multiply                MULTIPLY
Difference              DIFFERENCE
Lighten                 LIGHTEN
Darken                  DARKEN
```

Each of those computes `lerp(lower, f(lower, upper), alpha)`, which is exactly
what Blender's Mix node does with the layer's alpha on the factor, so the alpha
travels unchanged. The bottom layer composites against black, so its alpha
multiplies its own colour: measured, a 0.8 layer at alpha 0.5 bakes to 0.4 and
at alpha 0 to black. That is why it gets a Mix node too, mixing up from black.

**Index 0 is the top layer.** This was measured, and it is the reverse of the
obvious guess: a first sweep varied index 1 and produced the same colour
thirty-four times running, which is what an opaque `Over` sitting on top looks
like when you are reading the table upside down.

A layer Maya is not drawing does not travel. `isVisible` off means the layer
is dropped, on the same reasoning as a switched-off `aiLayerShader` slot.

Six of Maya's fourteen modes are refused rather than approximated, each with a
warning naming the mode and the material: `In` and `Out` are alpha compositing
against the backdrop rather than colour blends, `Saturate`, `Desaturate` and
`Illuminate` are HSV-space operations with no Mix equivalent, and
`CPV Modulate` needs colour per vertex, which the package does not carry. A
refused layer is left out of the stack; the layers around it still build.

With **Bake Procedurals** on the stack is baked instead, like any other
network, and the bake is the more faithful answer — it is Maya evaluating its
own node. The rebuild is what happens when baking is off.

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

Lambert, Blinn, Phong, PhongE and Ramp Shader transfer base colour (texture if
connected, value otherwise) and convert `transparency` to opacity, with
Metallic `0.0`.

Roughness comes from each shader's own gloss control, read off a live Maya
2023 session rather than guessed, because the four spell it differently and
two of them share no attribute at all:

| Shader | Attribute | Becomes |
|---|---|---|
| `blinn`, `rampShader` | `eccentricity` | roughness directly |
| `phong` | `cosinePower` | `sqrt(2 / (n + 2))` |
| `phongE` | `roughness` | roughness directly |
| `lambert` | none | **0.7**, a constant |

Only lambert keeps a constant, because it has no gloss control to read. Blinn
used to get one too — every blinn arrived at `0.1` whatever its eccentricity
said, which meant the artist's setting was discarded.

The Phong conversion is **analytic, not measured**: a Phong lobe and a GGX
lobe are different shapes, so no single number makes them equal. It tracks the
artist's intent, which a pinned value did not.

### Texture projection

A `projection` node maps an image through a **place3dTexture** instead of
through UVs. Before this the upstream walk stepped straight through it, found
the file behind it and shipped that path — so a projected texture arrived
wrapped on the mesh's UVs, which looks nothing like the projection and which
nothing warned about. That was a wrong result presented as a right one, not a
missing one.

**Bake Procedurals decides**, as it does for ramps. With it on the projection
is evaluated onto the mesh's UVs, which is correct for all nine of Maya's
types.

With it off, a **Planar** projection is rebuilt natively: the place3dTexture
arrives as an Empty, and the image is read through a Texture Coordinate
**Object** output so it follows that Empty. Move the Empty in Blender and the
projection moves, as it does in Maya. The placement's scale is kept, because
that is what sets how large the projection is.

The construction was measured, with the tool's own bake as the ground truth.
Maya's planar projection covers the placement's local `-0.5 .. 0.5` on both
axes, u along `+X` and v along `+Y`, with no flip. In Blender the same picture
comes back through a Mapping node rotated **−90° about X** and moved by
**+0.5**: the rotation undoes the Y-up to Z-up conversion that the Object
output has already applied, putting the texture back in Maya's space. `+90°`
renders vertically flipped and `0°` has no vertical variation at all.

The image is **clamped** at the projection's edge, not tiled. That was
measured too: against Maya's own bake on a sphere wider than the projection,
Blender's default `REPEAT` scored 0.50, `CLIP` 0.36 and `EXTEND` 0.03.

**Only Planar is rebuilt, and the other eight were measured rather than
assumed.** Every one of Maya's nine types was baked onto one sphere and
compared against a candidate Blender node tree baked into the same UV space
([`tests/docs/projection_calibration.md`](tests/docs/projection_calibration.md)):

| Maya type | best Blender candidate | difference | |
|---|---|---|---|
| Planar | `FLAT` | **0.028** | matches |
| Spherical | Math nodes | **0.019** | matches |
| Cylindrical | Math nodes | **0.020** | matches |
| TriPlanar | three lookups | **0.024** | matches |
| Perspective | Math nodes | **0.008** | matches |
| Ball | `SPHERE` | 0.107 | no |
| Cubic | `BOX` | 0.412 | no |
| Concentric | — | — | no equivalent |

**Spherical** is rebuilt from Math nodes rather than Blender's `SPHERE`
mode, which was measured and rejected — it plateaus at 0.106 however it is
turned or flipped, because the two are parameterised differently. Maya's
mapping is `u = 0.5 + atan2(x, z) / 2π` and `v = 0.5 + asin(y / |p|) / π`,
which reproduces its bake at 0.019.

Establishing that needed the reference image to be changed. Against four
coloured quadrants the winner and its mirror scored 0.0216 and 0.0217, which
is a coin toss, and the coin came down on the wrong side; against a sixteen
cell grid it is 0.019 against 0.123.

**Cylindrical** is `u = 0.5 + atan2(x, z) / π` and `v = 0.5 + y / 2`: its
image sweeps a **half** turn, not a whole one, which is the piece guessing
kept missing. It also wraps where a planar projection clamps — measured,
`REPEAT` 0.02 against `EXTEND` 0.22 — so the extension is per type.

Both formulas were read off Maya rather than guessed at, by projecting an
image that encodes u in red and v in green and baking it: every surface
point then reports the pair Maya computed for it.

**TriPlanar** reads the image three times — the dominant axis names the
face and each face reads the other two, halved and centred — and blends them
by the normal. Blender's `BOX` is not this mapping: it stops at 0.27 however
it is offset, scaled or blended, because it pairs its axes differently.

**Perspective** is `u = 0.5 - x / 2z` and `v = 0.5 - y / 2z`, with the image
centre behind the projector, which is worth 0.14 on its own. Its 0.008 is
measured away from the silhouette; across the whole sphere it reads 0.082,
because a perspective divide explodes as the depth approaches zero and half
a texel there lands anywhere in the image. That band is the test geometry,
not the mapping.

Cubic and Ball still need the bake, and say so:

```text
mLender warning: Maya projection "ballProjection" is Ball, which this build
cannot rebuild; it needs Bake Procedurals to travel.
```

3D textures such as `solidFractal` or `cloud` have always needed the bake, and
still do — the bake evaluates their place3dTexture correctly.

### Ramp textures

A `ramp` texture node is a different thing from a `rampShader`: a gradient
wired into any channel of any shader.

**Bake Procedurals decides.** With it on, a ramp is baked like any other
fileless network — that is what the option is for, and baking is the only path
that applies the ramp's `place2dTexture`.

With it off, a **U Ramp** or **V Ramp** is rebuilt natively as a Color Ramp
driven by that UV component: no extra file, no resolution loss, and the
gradient stays editable in Blender. Before this it simply collapsed to the
ramp's first colour with nothing said.

The direction was measured by baking a red-to-blue ramp through the tool's own
bake path and reading the image: position 0 sits at `v = 0` for a V Ramp and
`u = 0` for a U Ramp, so neither is inverted.

Maya keeps one interpolation on the node here, unlike a rampShader's per-stop
one. `None`, `Linear` and `Smooth` have Color Ramp equivalents; `Exponential
Up`, `Exponential Down`, `Bump` and `Spike` do not and fall back to linear.

The other seven types — Diagonal, Radial, Circular, Box, UV, Four Corner and
Tartan — are shapes one Color Ramp cannot make, so **Bake Procedurals** is the
only way they travel. With baking off they arrive as a flat colour and now say
so:

```text
mLender warning: Maya ramp texture "radialRampTex" is a Circular Ramp, which
one Color Ramp cannot reproduce; it needs Bake Procedurals to travel.
```

### Ramp shader

`rampShader` builds its look from gradients, and those now travel. The colour,
incandescence and transparency ramps arrive as **Color Ramp** nodes on Base
Color, Emission and Alpha; the transparency one is inverted into opacity on the
way out, the same as a flat `transparency`.

Maya returns a ramp's stops in creation order, so they are sorted by position
before they travel — a ramp an artist edited comes back shuffled, and an
unsorted gradient is not the one they drew. A ramp with a single stop is a
constant, not a gradient, and arrives as a flat value rather than a node tree.

The direction was **measured**, and measuring it needed Maya's own software
renderer: **Arnold does not evaluate a rampShader at all**, it substitutes a
default grey. An unlit red-to-blue facing ramp renders blue in the centre and
red at the rim, so position 1 faces the camera and position 0 grazes.

What drives it in Blender is `dot(Normal, Incoming)` — the cosine itself,
measured at 0.988 facing and falling toward the rim, which is the same
quantity and the same direction as Maya's. Layer Weight's `Facing` was measured
too and rejected: it runs the opposite way and is not linear (0.011 facing,
0.221 at the rim).

Maya has one `colorInput` enum for the whole shader, not one per ramp, and its
default is **Light Angle** rather than Facing Angle. Light Angle, Brightness
and Normalized Brightness depend on the lighting at shading time, which a
Blender shader graph cannot see; those still arrive as a gradient driven by the
facing angle, and the import says so:

```text
mLender warning: Maya drove a ramp by "Light Angle", which a Blender shader
graph cannot see; the gradient arrived driven by the facing angle instead.
```

The `specularColor`, `specularRollOff`, `reflectivity` and `environment` ramps
have no ramp-shaped Principled input and are left out rather than approximated
into the wrong one. `eccentricity` still drives roughness.

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

### UV sets

A mesh can carry several UV sets, and Maya binds each texture to one of them
through `uvLink`. All the sets ride the FBX — measured on Blender 4.1 and 5.2,
they arrive under their Maya names and in Maya's order — but only the first one
is active, so every texture used to read that one whatever Maya said. A texture
laid out on a second set arrived mapped with the wrong coordinates, which looks
like a texture that is merely misplaced rather than one reading the wrong data.

A **UV Map** node is now built for a texture bound to a non-default set:

```text
uvLink texture -> uvSet[n]   ->  UV Map node -> Mapping (if any) -> Image
uvLink texture -> uvSet[0]   ->  nothing; the active layer is already right
```

Only a difference is recorded. `uvLink` answers `uvSet[0]` even for a texture
nobody ever linked, so recording every answer would put a redundant node in
front of every texture in the scene; the comparison is against the shape's
first set, by index rather than by the name `map1`, so a renamed first set is
still recognised as the default.

Two limits, both reported rather than silent:

- One material carries one UV source. A texture bound to different sets on
  different meshes cannot be honoured on both, so the first non-default set is
  used and the disagreement is listed in the import warnings.
- Blender's UV Map node accepts a name no mesh carries without complaint and
  quietly renders the active layer instead. After import, every requested set
  is checked against the meshes that use the material, and a name that
  resolves to nothing becomes a warning naming the material, the set and the
  mesh.

Baked procedural networks carry no UV set record, and do not need one.
Measured on Maya 2023 with an object-space gradient, which is the only source
that can tell the two halves apart:

- `convertSolidTx` **evaluates the network through its own `uvLink`**. A ramp
  moved to a flipped second set baked flipped, so a procedural laid out on a
  second set bakes with the appearance Maya shows.
- It **writes into the default set, ignoring the mesh's current one**. Setting
  the current set to the flipped one changed nothing; only passing
  `uvSetName` explicitly did. The default set is index 0, which is the layer
  Blender activates, so the two agree without being told to.

Together those mean a baked procedural arrives correct whichever set it was
authored on: the set is resolved during the bake and flattened into the layout
Blender reads. A first probe using a ramp could not have shown this — the ramp
reads UVs, so the read and the write cancelled and all four bakes looked
identical whatever the answer was.

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

Three traps, any of which would ruin a turntable:

- **Euler flips.** Solving each frame's matrix independently lets angles jump a
  full turn between frames, so a camera orbiting 360° appears to snap back.
  Each frame is made compatible with the previous one.
- **Interpolation.** Baked samples are linear. Blender's default Bezier eases
  in and out of every key and makes a constant rotation stutter, so keys are
  set to `LINEAR`.
- **The FBX importer's frame offset.** Its `anim_offset` defaults to `1.0` —
  FBX time zero lands on frame 1 — but Maya writes frame N at time N/fps, so
  every baked key arrived on frame N+1. Measured on a production rig: a spine
  joint keyed 1..10 arrived keyed 2..11, one frame behind the lights, cameras
  and visibility this tool keys from the JSON at Maya's own frame numbers, and
  the final frame of the range showed the second-to-last pose. The import now
  passes `anim_offset=0.0`; the same joint matches Maya's world position at
  both ends of the range to six decimals.

The frame count is capped at **2000**. Exceeding it clips the range and records
that it was clipped, rather than sending short silently.

---

## Rigs and the live pose bridge

A skinned character travels through the FBX as a real armature: the exporter
adds the influence joints (and their joint ancestors) to the FBX selection, so
the mesh arrives with vertex groups and an Armature modifier and can be posed
in Blender. Only the influences travel — measured on a production rig, sending
every scene joint turned 1,014 joints into **132 armatures**, one of which was
the skeleton. A mesh whose deformers are all rig deformers (skinCluster,
blendShape) rides the FBX even when an Alembic cache is on; the cache would
freeze the result and throw the rig away.

What does **not** travel is the control rig. Measured on the same character:
the chain between a control and a bind joint runs through 3,010 constraints,
motion paths, skinned ribbon surfaces, 69 IK handles and pose interpolators.
No format carries that graph, and the one tool that translates it — Rumba's
`mtorba` — reimplements eighty-plus Maya node types and still calls itself a
subset. This tool does not pretend to.

Instead there is the **pose bridge**, the same pattern as Unreal's Live Link
for Maya: pose the rig *in Maya*, with its own controls, and Maya's DG does
the evaluating; only the resulting bind-joint world matrices stream over the
existing LiveLink socket, and the Blender armature mirrors them.

- **Send Pose** samples the bound skeleton at the current frame and sends it.
- **Sync Timeline Pose** streams a pose on every `timeChanged`, so scrubbing
  the Maya timeline drives the Blender character. Measured on the production
  rig: 62 Hz driven by a scrub, 8 Hz for interactive control drags, ~292 KB
  per message.

Accuracy was measured, not assumed, on a 1,014-joint production character:
applying Maya's **bind pose** moves the Blender mesh by exactly 0.000000 —
the independent judge, since the skin has no idea what the bridge intended —
and a control-driven pose lands each bind joint within a few 10⁻⁷ m of where
Maya evaluated it, with a 25 cm control move arriving as +0.249999 m of mesh.

Two honest limits:

- The bridge mirrors poses; it does not create keyframes. For final animation,
  key the rig in Maya and use **Export Animation** — baked keys land on
  Maya's own frame numbers and match world positions to six decimals.
- A pose message meeting an add-on older than 2.31 is refused with an explicit
  "Unsupported LiveLink event", never misread: adding an event does not touch
  the protocol version.

### Maya-style groups

A Maya group is a transform that owns its contents, so moving it moves
everything under it. A Blender collection is only a container — measured,
it has no transform at all, so no add-on can make a collection itself
movable. What this adds is the transform a collection lacks:

- **Group Selected** (`Object > Group Selected`, or the panel button) is
  Maya's Ctrl+G: the selection goes under a new group that is both an
  empty (the thing you grab) and a collection of the same name (the folder
  Blender's outliner shows), marked as a pair. The new group's transform
  sits at the origin, as Maya's does; tick *Pivot at Centre* for the other
  habit. **Ungroup** dissolves it and leaves the contents where they are.
- **Make Group (Movable)** appears in Blender's own outliner when you
  right-click a collection — any collection, imported or hand-made. It
  gives that collection a transform and parents its top-level objects to
  it, so from then on it behaves like a Maya group. Asking twice reuses
  the transform rather than stacking a second one. **Select Group
  Transform** is beside it, for grabbing the group from the collection
  row.

Collections mLender keeps for itself — light linking, Maya sets and
display layers — are refused, because their membership is what makes those
features work.

Imported groups are finished the same way: the FBX already parents a
group's meshes to the empty it made for it, and the import now attaches
what it rebuilt from the JSON beside them (curves, locators, volumes,
standins) to the same empty. Measured before the fix: moving `curveGroup`
moved the meshes and left the curve behind. An **animated** group is left
alone and reported instead — lights and cameras are sampled in world
space, so their keys already carry the group's motion and parenting them
to it would apply that motion twice.

### Maya-style outliner

The N-panel carries an **Outliner (Maya)** section: the scene's transform
hierarchy as a single tree, the way Maya shows it, independent of Blender's
collection-based outliner.

- **Manual order.** Blender sorts siblings alphabetically; here the ▲/▼
  buttons move the active object among its siblings and the order is saved
  with the file. Untouched objects stay alphabetical after the ordered ones,
  and **Reset Order** puts everything back to alphabetical.
- **Click to select, Ctrl-click to toggle, Shift-click for the range** —
  Maya's rules. Rows highlight the selection; each row also carries the
  viewport and render visibility toggles.
- **Reveal, rename and delete** as buttons: reveal unfolds the branches
  above the active object, delete takes the selection and everything under
  it.
- **One-click parenting.** With something selected, every other row shows a
  parent-here button — Maya's middle-drag as a click. World positions are
  kept both ways, and unparenting (the ✕ button) keeps them too. A cycle is
  refused rather than allowed to knot the hierarchy.
- **Search.** The filter shows every match flat, wherever it hides in a
  collapsed branch, like Maya's outliner filter.

A Python add-on cannot add a real editor type, and panel widgets get no
drag-and-drop or double-click — so the panel's moves are buttons, and long
scenes are capped at 400 drawn rows for the UI's sake (the search reaches
everything regardless).

**The overlay carries the gestures the panel cannot.** The window button in
the panel header opens a GPU-drawn outliner over the viewport — its own
tree, drawn and hit-tested by the add-on, so raw mouse events are on the
table:

- **drag a row onto another row to parent it there** (world position kept;
  dragging a selected row moves the whole selection, Maya's rule), and drop
  it on the header bar to unparent;
- **drag between two rows to reorder** — the row's middle parents, its top
  and bottom edges insert at that place in the order, with a line showing
  where the drop lands. Dropping between rows at another level takes that
  level's parent, so one drag both re-nests and places;
- **double-click renames in the row**, with a caret, Enter to commit and
  Esc to cancel;
- click selects, **Ctrl-click toggles, Shift-click takes the range**;
- each row's two squares hide it in the **viewport** and in **renders**;
- **right-click opens the menu** (rename, reveal, unparent, reset order,
  delete), `F` reveals the active object and scrolls to it, `X` deletes
  the selection, the wheel and the scrollbar scroll;
- **drag the header to move the window, the corner to resize it** — both
  are remembered in the .blend, and an offset that would push the card
  off-screen is clamped rather than losing it.

**Every change is undoable.** Parenting, reordering, renaming and the
visibility toggles each push an undo step, so Ctrl+Z steps back through a
drag the way it does through anything else — measured, not assumed. The
card and its rows also follow Blender's interface scale, so it is the same
physical size as the rest of the UI on a scaled display.

It shares its tree, order and fold state with the panel, lives in the one
viewport it was opened over, and closes with Esc or the same button. The
tree and the mouse agree by construction — the drawing and the hit-testing
use the same geometry, and that geometry is what the test suite checks.

### Advanced Skeleton characters

An Advanced Skeleton scene is recognised from AS's own manifest — measured
identical across five production rigs: `DeformSet` names the bind skeleton,
`ControlSet` the controls, FK controls map to joints **by name**
(`FKElbow_L` → `Elbow_L`), and each `FKIK<Limb>_<Side>` switcher declares its
IK chain in `startJoint`/`middleJoint`/`endJoint` string attributes. Nothing
is guessed; a rig that breaks the convention simply gets no entry.

**Referenced rigs and multiple rigs are recognised too.** A referenced
character keeps its manifest inside its namespace (`Chubs:DeformSet`), so
detection scans every namespace and writes one record per rig. Names travel
fully qualified on both sides — measured, the FBX importer keeps the
namespace in Blender bone and object names verbatim, colon included — so a
referenced rig's bones, control curves and pose-bridge joints all match
without any translation. Each rig's FK/IK property carries its namespace
(`FKIK_Chubs_Arm_L`), which keeps two characters sharing one armature from
fighting over the same slider. Two rigs imported **without** namespaces is
the one unsupported layout: Maya itself renames their clashing sets and
joints, and there is nothing left to tell the rigs apart.

On import, a native Blender control layer is built from that manifest:

- Every FK bone wears its imported AS control curve as a **custom shape**, so
  the animator sees the silhouette they know; the stray curve objects hide.
- Each declared limb gets a **real Blender IK constraint**. The imported
  `IK<Limb>` and `Pole<Limb>` curves are promoted into the live target and
  pole objects — the same controls AS gave the animator, now functional.
- A `FKIK_<Limb>_<Side>` property on the armature stands in for AS's
  `FKIKBlend`, driving the constraint influences. (Set it from a script and
  call `armature.update_tag()`; a property assigned from Python does not tag
  the depsgraph by itself.)

The N-panel grows an **AS Rig** section when such a rig is in the scene — the
functional stand-in for AS's picker. Per limb it shows an FK/IK slider
(0 = FK, 1 = IK; the same property as above, and edits from the UI tag the
depsgraph on their own) with a select button that grabs the limb's three
bones plus its IK and pole controls in one click, and a **Select FK
Controls** button for the dressed FK bones. It reads the `ml_as_rig`
manifest the import writes onto the armature, so it works on a reopened
.blend too — nothing is re-derived from names. With several rigs in the
scene each slider is labelled by its rig ("Chubs Arm L"), and every
manifested armature gets its own block.

Two measured facts shape the build. The FBX importer creates bones as
disconnected sticks whose tails do not sit on the next joint — no IK effector
on such a chain can coincide with the end joint, the best any arrangement
managed was a full bone length of rest error — so the declared chains are
**re-tailed** first, which costs the skin nothing because the pose is the rest
pose while it happens. And Blender's `pole_angle` is **calibrated, not
assumed**: the angle that keeps the end joint at rest is found by scanning,
so IK at rest is a no-op by construction. Verified on a production character:
rest deviation 0.000000 m, an 8 mm IK-control drag moves the wrist exactly
8 mm with the skin following, and the FK switch returns it to 0.000000.

**An animated package arrives with its limbs parked in FK.** The baked action
is the evaluated truth and the IK targets sit still at bind, so a live
constraint corrupts the animation — measured, 1.3 cm of error on the first
frame of a 3 cm character before anything even moved. Raise the FKIK
properties to puppet on top; scrub back to see the animation again.

**Motion above the skeleton travels too.** The FBX bake alone cannot carry
it — measured twice: a group with its own keys arrives with the key shape
flattened to linear, and motion driven into the group or the root by a
connection, which is how AS's `Main` works, arrives frozen entirely. So for
every skeleton that sits under a group, the exporter samples the root
joint's evaluated world per frame — the complete truth, whatever drove it —
and the importer re-keys the root bone against it, calibrating the constant
bone-axes difference at the export frame first (a production root bone sits
a measured 90° of roll from its Maya joint while both are correct). Where
the bake was already right this is exactly a no-op. Verified on a
production character with `Main` keyed on two axes: root and wrist land on
Maya's world positions to six decimals on every probed frame, including
mid-curve frames where the old linearized fold was measurably wrong.

The bridge and the IK layer drive the same bones, so they take turns rather
than fight: a streamed Maya pose is an FK dictation, and applying one parks
the limbs' FKIK properties at FK — with a warning saying so — because a live
IK constraint would re-orient the parents and dangle the baked pose a bone
length off the joint. Raise the properties to hand the limbs back to the
Blender IK controls.

Out of scope, deliberately: the face (its ~144 joints pose as plain FK), the
spine's hybrid IK, and round-tripping a Blender pose back onto the Maya
controls.

### Animated material parameters

A keyed roughness, base colour or emission travels. The exporter samples the
channel over the frame range the same way it samples lights and cameras, and
Blender keys the socket directly, LINEAR — the samples are already the
evaluated curve, so easing between them would ease twice.

Only channels that are **actually keyed** are sampled, on the same reasoning as
visibility: reading every channel of every material at every frame is a getAttr
storm for something almost nothing in a scene does.

**A colour is a compound and Maya keys its children.** The curves hang off
`baseColorR` and `baseColorB` while the compound itself reports no connection,
so asking only the compound found a keyed roughness and missed a keyed base
colour entirely. Both are in the fixture for that reason.

With **Export Animation off** a keyed channel still freezes at the export frame
— that is a legitimate choice — but it is no longer a silent one:

```text
mLender warning: 2 material channel(s) are keyed in Maya and this export is a
single frame, so they arrive frozen at frame 4: animShader.roughness,
animShader.base_color. Tick Export Animation to carry them.
```

> Fixed on the way: **an animation curve was being walked into as a shading
> network.** With nothing but a curve upstream and no file behind it, the bake
> path treated a keyed scalar as a procedural and wrote one frame of it into a
> texture map — a wrong answer that looked deliberate. The upstream walk now
> stops at an animation curve, so the channel keeps its plain value and its
> samples.

Unreal receives the samples and reports them per channel; animating them there
needs a Level Sequence, which this build does not write.

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

**nParticle counts as a particle**, which is worth saying because it is the one
an artist actually makes — the shelf and the nParticles menu both produce it,
and the classic `particle` is what a script produces. Discovery lists the base
type on the grounds that `nParticle` derives from `particle`, and that is
measured: `nodeType` answers `nParticle`, its inheritance chain runs
`... particle, nBase, nParticle`, and `ls(type="particle")` returns it anyway.
An nParticle also carries per-particle colour and opacity that a bare classic
one does not, and those travel with it.

Two readings were measured rather than assumed. `particle -q -position`
returns **None**; the query that works is `getParticleAttr` with `array`,
which hands back three numbers per particle in one flat list. And those
numbers are **local**, so they pair with the world matrix rather than
replacing it — applying the transform twice is exactly what the test guards
against.

### Animated visibility

A mesh whose `visibility` is keyed in Maya arrives keyed in Blender, on both
`hide_viewport` and `hide_render` — hiding only the viewport would still put
it in the render. The keys are **stepped**, not eased: these are booleans held
in float curves, and easing would leave an object half hidden for several
frames.

Visibility does not survive the FBX at all, so before this a mesh that blinked
in Maya arrived visible for the whole range, with no warning.

Only meshes whose visibility is actually driven by a curve are sampled. Reading
it for every mesh on every frame costs real time on a large scene over a long
range, and almost nothing in a scene blinks.

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

#### Carry everything that moves

The second box carries **every object whose world transform moves over the
exported range** — which is how a simulation travels — and it splits them into
two, because a simulation is two different problems wearing one name.

A rigid body sim is not lost by the FBX so much as by being a sim: Bullet
solves the transform each frame and writes the answer, with no animation curve
behind it. So whether the motion survives depends on whether somebody
remembered to bake the sim to keys first, and when they did not, the objects
arrive at their first-frame pose and hold still. Nothing reports it, because
from the exporter's side there was never any animation to carry.

So this option does not ask what is keyed. It **steps the timeline and reads
the world matrix**, at twelve frames spread across the range, and anything
whose matrix changed is carried. That catches Bullet, expressions,
constraints, IK, and a prop parented under something that moves — all of which
report "not animated" to any test that walks connections.

The same pass asks a second question of each mesh: **do its own points move**,
in its own frame. That is what decides which of two channels carries it:

- a mesh whose points move is **cached**, because only a stream of vertices
  can carry a deformation;
- a mesh whose points hold still is **sampled** — one world matrix per frame,
  written beside the scene file, keyed onto the mesh the FBX already carried.

The difference is not academic. On the shot this was written for, **0 of 3384
moving objects deformed**: every one of them was a rigid body, and all of them
were paying for a container that cannot be instanced, cannot be ray traced,
and has to stream 452 MB off disk to play back. As sampled transforms the same
motion is a few megabytes of matrices on ordinary static meshes.

**In Unreal the sampled movers do not become Sequencer rows.** A binding is a
row in the Sequencer outliner, and measured on the same shot grown to 7562
movers, one row each made a 349 MB Level Sequence the editor would not open
at all; cutting it into 400-row sub-sequences let the master open, but every
part was still a sequence a person could open by mistake and hang on. So the
receiver takes the movers out of the sequence entirely:

- their transforms go into one **`ML_Motion` data asset** under
  `Content/mLender/Motion`, thinned to the samples that are not already on
  the line between their neighbours;
- one **`ML_MotionPlayer` actor** holds a binding per mover and writes every
  world transform itself, interpolating between samples so a sub-frame render
  gets motion blur;
- the Level Sequence keys **one float**, `Frame`, on that actor. Opening the
  shot costs one row, and scrubbing the ruler moves everything.

**A simulation that stopped converging is reported at export.** A rigid body
cannot turn round twice in two frames without being struck twice, so a run of
hard reversals is a solver blowing up rather than debris — and it arrives as
an object that vibrates across the shot, faithfully transferred and wrong.
Measured on a real shot: 178 of 7468 movers reversed direction every frame at
about 1.1 m of amplitude, and every piece under one tower carried the *same*
per-frame delta to 0.0000, so the instability was in a group transform rather
than in the pieces. The export warning therefore names the ancestor, with the
frame it starts on, because that is the node somebody has to look at:

```text
178 moving object(s) reverse direction on consecutive frames ...
Worst: KO_tower_13 (64 object(s), from frame 407), tower3 (50 object(s), from
frame 92), KO_tower_11 (25 object(s), from frame 405) ...
```

The function that applies a frame is called `JumpToFrame`, and it is
deliberately **not** called `SetFrame`. Sequencer chooses how to write a
property by looking for a function named `Set` plus the property's name: when
one exists it refuses the fast path and writes through a slower one that the
editor does not run while a sequence is *playing*. Measured on a real shot —
with `SetFrame` present, dragging the playhead applied every frame while
pressing Play applied exactly one, the first, as the ruler ran to 519; with
the name gone, `Frame` follows the ruler through both. It played in PIE either
way, which is what made it look like a Sequencer problem rather than a naming
one. If you add a property for Sequencer to key, do not give its class a
`Set<Property>` function.

The player is a C++ actor because that is what makes it update while you
scrub in the editor, where a Blueprint does not tick; see
[The compiled module](#the-compiled-module). Its visibility keys ride the
same asset, so a piece that appears when it breaks still does. The old
per-row layout remains as the fallback for a plugin loaded without its
module, and the import says so in its warnings when that happens.

There is a measurement behind "cannot be ray traced". A geometry cache's ray
tracing geometry is sized from the frame it first saw, and a track whose
vertex buffer grows mid shot trips an assertion that takes the editor with
it:

```text
Assertion failed: P.Segments[i].MaxVertices <=
Geometry->Initializer.Segments[i].MaxVertices
Maximum number of vertices in a segment (125) must not be larger than what
was declared during FRHIRayTracingGeometry creation (123)
```

Blinking objects — a fractured piece that appears when it breaks — are exactly
what makes a buffer grow. The cache the tool imports is now optimised once
rather than per frame, which removes that growth, and the cache actor is kept
out of the ray tracing scene as well; what is lost there is the cache's
contribution to hardware ray traced reflections and shadows, not the cache.
With the split above, most shots have nothing in the cache to lose it for.

Sampled motion carries **visibility** too, keyed per frame, because a piece
that is on screen before it breaks reads as a piece that never moved.

**A live simulation is sampled as a replay, and a replay is not
reproducible.** Measured on a Bullet shot of 12 028 meshes: the first walk
through the timeline after opening the scene differed from the second on
2044 objects, by up to 108 units, and the second and third walks agreed
exactly. Maya itself behaves this way — the artist who has scrubbed the shot
sees one result and a fresh batch session sees another — so the exporter
cannot promise the same package twice from a live solver. It says so in the
report when it finds one. Bake the simulation to keys, or cache it, for an
export that comes out the same every time.

The sampling reads each mover through the OpenMaya API rather than a `cmds`
call per object per frame — a shot of 7468 movers over 520 frames is 3.9
million reads, and a command round trip for each was a third of the export.
Measured on that shot: 32 minutes through `cmds`, 24 through the API, with
the motion file byte for byte identical. The rest of the time is Maya
evaluating the scene at every frame — a Bullet solver has to be stepped
from the first frame, and there is no shortcut through a simulation — so
an export of a long simulation is still a coffee, not a click. Visibility
plugs are read every frame only where something drives them; a static plug
is read once.

It is applied **on top of where the receiver put the object**, not instead of
it. Measured: Unreal's FBX import places every actor with a 90 degree roll —
that is where the format's up-axis conversion ends up, with the mesh left in
the converted frame — so a world transform written over it turned every
moving object by exactly that much. Each mover therefore carries the pose it
was in at a reference frame, and the receiver composes each sample onto its
own placement with that pose divided out. At the reference frame the object
does not move at all, which is what both receivers' tests check.

The reference is the **first frame of the exported range**, and the FBX is
written from there, because that is the frame both receivers show. The
package records it as `motion.reference_frame`, and the export puts the
artist's frame back afterwards.

Materials come with them. A cached object is still described in the JSON, so
the receiver still builds its Maya materials and assigns them; the geometry is
what moved into the cache, not the look. Two measurements make that work in
Unreal:

- the cache is written with **face sets**, so each material slot is named
  after the shading group it came from. Without them every slot on the
  imported cache is called `NoFaceSetName` and nothing can tell which slot
  belongs to which shader — a cache of ten objects arrived as ten slots of
  grey checker.
- the cache is imported with **one track per object** rather than Unreal's
  default, which flattens the whole file into a single track with a single
  material slot. Measured: six objects, one slot.

Two things happen to the geometry on the way, both measured on a real shot:

- **n-gons are triangulated for the cache.** Unreal's Alembic reader refuses
  a face with more than four sides — *"expecting triangles (3) or quads
  (4)"* — and fails the **entire file** over one of them, so a single n-gon
  took all 574 cached objects of a shot down with it. Only the shapes that
  actually have one are touched, so a quad model keeps its quads; and it is
  done as construction history that is removed again, so the Maya scene is
  unchanged.
- **the FBX is written without a bake** when both channels took every mover
  and nothing left behind is skinned or deformed. Baking evaluates the scene once
  per frame per node, and on that same shot — 7106 meshes over a Bullet sim —
  it was over an hour of baking objects that do not move. The cache itself
  took 63 seconds.

What it costs is worth knowing before turning it on:

- a **cached** object arrives as geometry per frame. In Unreal that is a
  Geometry Cache, not a static mesh, so it is not instanced and cannot be
  re-timed; in Blender it is a Mesh Sequence Cache modifier reading the `.abc`
  from disk. Only deforming objects pay this now.
- a **sampled** object costs a key per frame per channel instead. That is
  small next to a cache, but a scene where thousands of objects move is still
  thousands of tracks in the Sequencer.
- sampling is done in **world space**, so a prop inside a moving group carries
  its journey itself; the receiver takes it off its parent before keying it,
  or the group's motion would be applied twice.

The export says which objects took which route:

```text
mLender warning: 12 moving object(s) deform, so they travel as an Alembic
cache rather than as keyed geometry. They arrive as cached geometry, so they
are not instanced and cannot be re-animated.
mLender warning: 3384 moving object(s) do not deform, so they travel as their
own transform per frame on the mesh the FBX carries: instanced, ray traced,
and nothing to stream. Only what deforms is worth a cache.
```

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

### Particle instancers

Maya's `instancer` places geometry on particle points. Nothing looked for the
node, so it and everything it placed left the scene without a word.

It arrives as Blender **vertex instancing**: the points object is switched to
`VERTS` and a copy of the source geometry is parented to it, giving one
instance per point. Measured on 4.1, 4.5 and 5.2, all three evaluate the same
number of instances, which is why this route was chosen over geometry nodes.

The source object is never re-parented. It came through the FBX with its own
place in the scene, and moving it would edit the user's geometry to make the
instancer work; a linked copy sharing the same mesh data is created instead.

Two limits, both stated rather than approximated. Maya cycles several sources
with a per-particle index and vertex instancing has no room for one, so only
the first source travels and the export says so when there is more than one.
Per-particle rotation and scale are not carried either.

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

### Standins

An `aiStandIn` and a `gpuCache` hold no geometry at all. Each is a pointer to
a file the renderer opens later, and Maya draws a proxy in its place. Both used
to be reported by the coverage scan and left behind; they are now carried.

The file is **referenced, never copied**. A standin is routinely gigabytes,
and the package already references textures for the same reason.

```text
aiStandIn.dso            -> the file
gpuCache.cacheFileName   -> the same idea under a different name
objectPath / cacheGeomPath, frameNumber, frameOffset,
useFrameExtension        -> kept as ml_source_*
Min/MaxBoundingBox       -> the size of the box drawn in place of the file
```

Every standin gets an **anchor** empty carrying the Maya transform, and
whatever the file yields is parented under it. That is the arrangement Maya
describes: the contents live in the file's own space and the standin's
transform sits on top.

Three formats, three different answers about units, each measured on 4.1 and
5.2 rather than assumed:

- **Alembic** carries no unit metadata, so the scale is supplied — the same
  call the package's own cache goes through.
- **OBJ** carries none either, and `global_scale` does what it says: a four
  unit cube at 0.01 arrives 0.04 across.
- **USD** describes its own units, and the importer's `scale` argument is
  accepted and then **ignored** — measured in world space, the cube arrived
  four units across whatever was passed. So nothing is passed and the file's
  own `metersPerUnit` decides.

**A referenced asset does not get to redecorate the scene.** A USD carries its
own start and end time codes, and can carry lights and cameras of its own; the
importer's defaults let all three in. Measured on 4.1 and 5.2 through this
tool's own standin import: a scene set to 1..24 became **40..90**, and the
asset's `SphereLight` lit it at **9869 on 4.1 and 3141 on 5.2** — the same
file, 3.14× apart, never through `light_energy()`. A camera arrived too, and
nothing was reported.

The frame range, the lights and the cameras all come from the Maya scene
through the JSON, so the USD import now refuses all three. The prims still
arrive, **as empties**, so the shape of the asset survives and what was left
out is visible in the outliner — and the refusal is named in the import
warnings, because trading one silence for another is not a fix.

Arnold's own `.ass` is not on that list and cannot be: Blender has no reader
for it. **A file that cannot be read, or is not there, leaves the anchor
standing as a box the size of Maya's proxy**, with the path on it and a
warning naming both. A placeholder in the right place beats a hole in the
scene with nothing to explain it — and since paths are referenced, a package
opened on another machine lands here by design.

> The bounding box is what Maya draws, not a claim about the file. Measured:
> Arnold fills `Min/MaxBoundingBox` in from the viewport, so a headless export
> reads its ±1 default and `exactWorldBoundingBox` answers zero. A unit box in
> Blender is then exactly what Maya was showing too.

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

## Batch export

The exporter runs without the UI, for a farm job, an overnight publish or a
shot list:

```bash
mayapy path/to/mlender_exporter/batch.py --scene shot.ma --out D:/packages
mayapy -m mlender_exporter.batch --scene shot.ma --out D:/packages --send
```

Both forms work and neither needs `PYTHONPATH` set: run as a plain script the
module puts its own package back on the path, because a farm job types the file
path far more often than it types `-m`.

```text
--scene            the file to open; omit to export whatever is already open
--out              where the package goes
--preset           which saved preset to start from (default: "default")
--send             also notify a listening Blender or Unreal
--selected         export the selection only
--no-bake          turn Bake Procedurals off
--collect          copy referenced files into the package
--archive          also write the .zip
--animation        export a frame range
--alembic          cache deforming meshes
--cache-animation  also cache everything whose transform moves
--start --end --step --bake-resolution --host --port
```

Warnings go to stdout as well as into the report, because a farm log is often
the only thing anybody reads afterwards.

### Presets

**Save Preset** in the Maya window keeps the current options under the user's
Maya preferences, and **Load Preset** puts them back. A preset holds exactly the
arguments `export_scene` takes plus the output folder and the LiveLink address,
so what an artist clicks and what a farm job runs cannot drift into meaning
different things.

Settings resolve in three layers, later winning: the built-in defaults, then the
preset, then the command line. **A flag that is not named does not reset
anything** — `--out` alone keeps every other setting the preset holds, which is
what makes a preset worth having.

Two rules the tests pin down: a key the running build does not know is
**dropped** rather than passed on, so a preset written by a newer build cannot
turn into a failed export by handing `export_scene` an argument it has never
heard of; and a preset somebody hand-edited into invalid JSON falls back to the
defaults rather than raising, because a broken settings file must not stop
anybody exporting.

## Vertex colours

A Maya colour set travels twice over: the **paint** rides the FBX, and the
**shader link** rides the JSON.

The paint was already arriving — measured, a painted set lands in Blender as a
corner colour attribute under its Maya name, and every set on the mesh comes,
not just the current one. What was missing was anything reading it. An
`aiUserDataColor` was an unsupported network, so with **Bake Procedurals off**
the channel fell back to its flat value, which for a colour is black. The
material went black and nothing said why.

Now the exporter records the set the shader names, and Blender builds a
**Color Attribute** node reading exactly that set:

```text
aiUserDataColor.attribute = "paintCol"  ->  Color Attribute node, layer paintCol
```

The name matters and the fixture makes sure of it: the test cube carries two
sets, the shader reads the first, and Maya is deliberately left with the
*second* one current. A receiver that took "the current set" would read the
wrong colours and look entirely plausible doing it.

The mesh also records every set it carries, so a set nothing reads is still
visible in the package rather than only in the geometry.

With **Bake Procedurals on** the network is baked to a texture instead, which
is Maya evaluating its own node and remains the more faithful answer. The
Color Attribute path is what happens when baking is off.

Unreal receives the same record but does not wire vertex colour into its master
materials yet, and says so per channel.

> While fixing this, the flag `unsupported_network` turned out to have been
> written by the exporter since the beginning and **read by nobody**. Any
> network the exporter could not express left the channel on its flat value in
> silence. Both receivers now report it by name.

## Render passes

Enabled Arnold `aiAOV` and Redshift `RedshiftAOV` nodes travel as name, engine
and Arnold's raw type integer. Blender turns each name into the view layer pass
that means the same thing:

```text
Z, depth, zdepth        -> Z
N, normal               -> Normal
motionvector, mv        -> Vector
uv                      -> UV
crypto*                 -> Cryptomatte object, material and asset
emission, emit          -> Emission
albedo                  -> Diffuse Colour
diffuse*                -> Diffuse colour, direct and indirect
specular*, reflection*  -> Glossy colour, direct and indirect
```

Everything else becomes a **named custom AOV slot and is reported**, because a
Blender custom AOV renders black unless a shader writes into it — a pass that
arrived and is empty hides better than one that never arrived. On the test
fixture that is `sss` and `opacity`.

Two of the old matches were wrong and the fixture now proves it:

- **`"z" in name` caught every name containing a z.** OpenPBR calls its sheen
  lobe **fuzz**, so a `fuzz` AOV quietly switched on the depth pass instead of
  landing in a slot of its own. Depth is now an exact match on Arnold's `Z`.
- **A bare `albedo` switched on diffuse direct and indirect** as well as colour.
  Albedo is the colour pass; the other two are light transport nobody asked for.

Arnold's type integer was a guess in a comment (`5=RGBA usually`) until it was
read off a live session. Measured: **4 float** (`Z`), **5 RGB** (most),
**6 RGBA** (what an unrecognised name defaults to), **7 vector** (`N`).

The Unreal receiver carries none of this: render passes there are Movie Render
Queue configuration, and this engine build does not ship MRQ. The count is
reported.

> Until this release the AOV path had never run with real data on either side —
> nothing in the fixture created an AOV, so both halves were untested code. It
> now creates eleven, chosen so that each one lands somewhere different.

## Reports

Every send and every import writes a plain text report **into the package
folder**, so the package carries the whole story and there is one file to hand
over instead of console lines copied by hand:

```text
mLender_01/
  mLender_01_report.txt            what Maya exported, and its warnings
  mLender_01_import_blender.txt    what Blender made of it
  mLender_01_import_unreal.txt     what Unreal made of it
```

Each report opens with the build number, the host version and the scene, then
counts what travelled, then lists **every** warning. The test fixture produces
sixty-seven of them in Unreal, which is exactly why a scrolling console was not
good enough.

The Maya report also says **where the time went**, phase by phase — scene
discovery, the motion probes, the sampling, the FBX, the JSON — because a
half-hour export names nothing on its own. On the shot this was added for,
the guess was the per-object reads and the truth was Maya evaluating a Bullet
solver at every frame; only the phases could tell the two apart. The batch
exporter prints the same lines to its log.

In Blender the same warnings are also in the sidebar, under
**mLender Import > Last Import Warnings**, with a button that opens the report.
The panel shows the first twenty-five — a panel with hundreds of rows stops the
UI — and the report always has all of them.

A report is never allowed to fail the thing it describes. A package folder can
legitimately be read only, and losing a good export or a good import over a log
file would be absurd, so a report that cannot be written is simply not written.

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
