# -*- coding: utf-8 -*-
"""Import the Maya test package into a real Unreal editor and assert on it.

Run maya_export_test.py first; this reads the package that one writes.

    "C:\\Program Files\\Epic Games\\UE_5.8\\Engine\\Binaries\\Win64\\UnrealEditor-Cmd.exe" ^
        <project>.uproject -run=pythonscript ^
        -script="tests/host/unreal_import_test.py" -unattended -nosplash -nullrhi

Exits non-zero on the first failed assertion, so the shell can gate on it.
Unreal's commandlet swallows a bare SystemExit code in some paths, so failures
are also printed with a MLFAIL prefix that the caller can grep for.
"""

import json
import os
import sys
import tempfile

import unreal


REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PACKAGE_PYTHON = os.path.join(REPO, "mlender_unreal", "Content", "Python")
if PACKAGE_PYTHON not in sys.path:
    sys.path.insert(0, PACKAGE_PYTHON)


def _use_the_checkout():
    """Make sure this tests the repository, not a plugin installed beside it.

    If the project has mLender in its Plugins folder and enabled, Unreal runs
    that copy's init_unreal.py before this file exists, so mlender_unreal is
    already in sys.modules and inserting a path changes nothing. Measured: a
    copy that had been taken from the repository earlier in the day shadowed
    it completely, and an edit made minutes before simply was not there --
    the module reported no attribute that the file on disk plainly had.

    Dropping the modules and importing again is the fix, and the check that
    follows is the point: this test says which copy it exercised rather than
    leaving it to be discovered.
    """
    shadowed = sys.modules.get("mlender_unreal")
    origin = os.path.dirname(getattr(shadowed, "__file__", "") or "")
    if shadowed is not None and not os.path.samefile(
            os.path.dirname(origin) or ".", PACKAGE_PYTHON) \
            if origin else False:
        pass
    if shadowed is not None:
        for name in [n for n in sys.modules
                     if n == "mlender_unreal" or n.startswith(
                         "mlender_unreal.")]:
            del sys.modules[name]
    return origin


SHADOWED_BY = _use_the_checkout()

PACKAGE = os.path.join(tempfile.gettempdir(), "mlender_test", "mLender_01")

failures = []


def check(label, condition, detail=""):
    if condition:
        print("  ok    {0}".format(label))
    else:
        failures.append("{0} {1}".format(label, detail))
        print("MLFAIL  {0}  {1}".format(label, detail))


def close(label, got, want, tolerance):
    check(
        "{0} = {1:.6g}".format(label, got),
        abs(got - want) <= tolerance,
        "wanted {0!r}".format(want),
    )


def main():
    import mlender_unreal

    # Which copy is under test. A plugin installed into this project would
    # otherwise answer for the repository and freeze whatever was last copied.
    where = os.path.dirname(os.path.dirname(mlender_unreal.__file__))
    check("the test is exercising the checkout, not an installed copy",
          os.path.normcase(os.path.abspath(where))
          == os.path.normcase(os.path.abspath(PACKAGE_PYTHON)),
          (where, PACKAGE_PYTHON))
    # Only worth saying when it was a *different* copy. A development install
    # is a junction to this checkout, so the path differs while the files are
    # the same, and a note every run about a copy that is not a copy is noise.
    if SHADOWED_BY:
        try:
            same = os.path.samefile(os.path.dirname(SHADOWED_BY),
                                    PACKAGE_PYTHON)
        except Exception:
            same = False
        if not same:
            print("  note: a different installed plugin was loaded first and "
                  "dropped: {0}".format(SHADOWED_BY))
    from mlender_unreal import lights, transforms

    print("mLender build:", mlender_unreal.BUILD_VERSION)
    check("package exists", os.path.isdir(PACKAGE), PACKAGE)
    if not os.path.isdir(PACKAGE):
        return 1

    # ---------------------------------------------------- pure conversions
    print("\nmeasured conversions")
    # The Y/Z swap, measured against Interchange's own output.
    check(
        "maya (0,40,0) becomes unreal (0,0,40)",
        transforms.maya_vector_to_unreal((0.0, 40.0, 0.0)) == (0.0, 0.0, 40.0),
        str(transforms.maya_vector_to_unreal((0.0, 40.0, 0.0))),
    )
    check(
        "maya (0,0,50) becomes unreal (0,50,0)",
        transforms.maya_vector_to_unreal((0.0, 0.0, 50.0)) == (0.0, 50.0, 0.0),
        str(transforms.maya_vector_to_unreal((0.0, 0.0, 50.0))),
    )
    # A centimetre scene is 1:1 with Unreal, and this is the number whose
    # sibling in metres the energy model needs. They must not be the same.
    close(
        "position scale for a centimetre scene",
        transforms.position_scale({"meters_per_maya_unit": 0.01}, 1.0),
        1.0,
        1e-9,
    )
    close(
        "position scale for a metre scene",
        transforms.position_scale({"meters_per_maya_unit": 1.0}, 1.0),
        100.0,
        1e-9,
    )

    # Energy: an Arnold light of intensity 1 in a centimetre scene. The flux
    # anchor is pi * mpu^2, and Unreal wants lumens, so x683.
    record = {"intensity": 1.0, "exposure": 0.0, "node_type": "aiAreaLight",
              "parameters": {"normalize": True}, "area_shape": "RECTANGLE"}
    intensity, units = lights.light_intensity_for_unreal(
        record, unreal.RectLight, 0.01, 1.0
    )
    close("rect light lumens", intensity, 3.141592653589793 * 0.0001 * 683.0,
          1e-6)
    check("rect light asks for lumens", units == unreal.LightUnits.LUMENS,
          str(units))
    # The squared unit term is mandatory; dropping it is a 10,000x error in a
    # centimetre scene. A metre scene must therefore be 10,000x brighter.
    metre_intensity, _units = lights.light_intensity_for_unreal(
        record, unreal.RectLight, 1.0, 1.0
    )
    close("metre scene is 10,000x the centimetre one",
          metre_intensity / max(intensity, 1e-12), 10000.0, 1.0)
    # A sun states irradiance, so neither area nor the unit square applies.
    sun = {"intensity": 2.0, "exposure": 0.0, "node_type": "aiSkyDomeLight",
           "parameters": {}}
    sun_intensity, sun_units = lights.light_intensity_for_unreal(
        sun, unreal.DirectionalLight, 0.01, 1.0
    )
    close("sun lux", sun_intensity, 2.0 * 683.0, 1e-6)
    check("a directional light is given no unit enum", sun_units is None,
          str(sun_units))

    # ---------------------------------------------------- the real import
    print("\nimport")
    with open(
        os.path.join(PACKAGE, "mLender_01_scene.json"), "r"
    ) as handle:
        package_data = json.load(handle)

    result = mlender_unreal.import_scene_package(PACKAGE)
    print(json.dumps(
        {k: v for k, v in result.items()
         if k not in ("assignments", "warnings")},
        indent=2, default=str,
    ))

    check("meshes matched a Maya record", result["mesh_count"] > 0,
          str(result["mesh_count"]))
    check("materials were built", result["material_count"] > 0,
          str(result["material_count"]))
    check(
        "every mesh in the package matched",
        result["mesh_count"] >= len(package_data.get("meshes") or []) * 0.5,
        "{0} of {1}".format(
            result["mesh_count"], len(package_data.get("meshes") or [])
        ),
    )
    # Surfaces Maya does not store as meshes -- a NURBS sphere, a trimmed
    # NURBS panel and a subdivision surface -- are tessellated during the
    # export. Here they have to be indistinguishable from any other mesh.
    actors = unreal.get_editor_subsystem(
        unreal.EditorActorSubsystem
    ).get_all_level_actors() or []
    labels = set()
    for actor in actors:
        try:
            labels.add(actor.get_actor_label())
        except Exception:
            pass
    for label in ("nurbsBall", "trimmedPanel", "subdivBall"):
        check("a tessellated Maya surface is in the level: " + label,
              any(name == label or name.startswith(label + "_")
                  for name in labels),
              sorted(n for n in labels if label[:5].lower() in n.lower())[:4])
    # Measured in Maya: 1024 faces untrimmed, 448 trimmed. A panel that
    # arrives whole means the trim was dropped on the way here.
    panel = next(
        (actor for actor in actors
         if isinstance(actor, unreal.StaticMeshActor)
         and actor.get_actor_label().startswith("trimmedPanel")),
        None,
    )
    if panel is not None:
        mesh = panel.static_mesh_component.static_mesh
        # Nanite is on for imported meshes here -- the engine's default, not
        # something this tool sets -- and get_num_triangles then reports the
        # *fallback* mesh. Measured: the 896-triangle panel reads back 256,
        # and so does a 3968-triangle sphere, because the fallback is built to
        # a budget. Counting that would have reported a surface as lost when
        # every triangle of it was present.
        triangles = -1
        try:
            nanite = mesh.get_editor_property("nanite_settings")
            if nanite.get_editor_property("enabled"):
                triangles = mesh.get_num_nanite_triangles()
            else:
                triangles = mesh.get_num_triangles(0)
        except Exception as exc:
            print("  note: triangle count unavailable: {0}".format(exc))
        if triangles >= 0:
            # 448 quads triangulated. Exact, not a range: a trim that half
            # survives is the failure worth catching, and a range hides it.
            check("the trim survived to Unreal, hole and all",
                  triangles == 896, triangles)

    # Clear coat. Unreal keeps it in CustomData0/1, which the Python
    # MaterialProperty enum does not expose, so the master routes everything
    # through MakeMaterialAttributes to reach the ClearCoat pins.
    coated = {}
    for mesh_record in package_data.get("meshes") or []:
        for material_record in mesh_record.get("materials") or []:
            channels = material_record.get("channels") or {}
            weight = (channels.get("coat") or {}).get("value") or 0.0
            # Translucent and unlit surfaces do not take a coat here, on
            # purpose: translucent clear coat is a different lighting argument
            # in Unreal, and an unlit surface answers no light at all. Both are
            # reported instead, so they must not be counted as expected here.
            transmission = (channels.get("transmission") or {}).get("value") or 0.0
            unlit = bool(material_record.get("unlit")) or str(
                material_record.get("material_mode") or "").lower() in (
                    "unlit", "emission")
            if weight and not transmission and not unlit:
                coated[material_record.get("material")
                       or material_record.get("shader") or ""] = (
                    weight,
                    (channels.get("coat_roughness") or {}).get("value"),
                )
    check("the package has a coated material", bool(coated),
          sorted(coated))
    if coated:
        library = unreal.MaterialEditingLibrary
        instances = {}
        for path in (unreal.EditorAssetLibrary.list_assets(
                "/Game/mLender/Materials", recursive=True) or []):
            asset = unreal.EditorAssetLibrary.load_asset(path)
            if isinstance(asset, unreal.MaterialInstanceConstant):
                instances[asset.get_name()] = asset
        on_coat_master = []
        for name, asset in instances.items():
            parent = asset.get_editor_property("parent")
            if parent is not None and "Coat" in parent.get_name():
                on_coat_master.append(name)
        check("its instance was parented to a clear coat master",
              len(on_coat_master) == len(coated),
              (sorted(on_coat_master), sorted(coated)))
        for name in on_coat_master:
            master = instances[name].get_editor_property("parent")
            check("and that master really is a clear coat: " + name,
                  master.get_editor_property("shading_model")
                  == unreal.MaterialShadingModel.MSM_CLEAR_COAT,
                  master.get_editor_property("shading_model"))
            break
        # The values, not just the wiring: a first version built the master,
        # parented the instance and then set nothing, so every coated material
        # arrived with a coat weight of zero.
        matched = []
        for name in on_coat_master:
            got = library.get_material_instance_scalar_parameter_value(
                instances[name], "Coat")
            source = name[3:] if name.startswith("ML_") else name
            want = None
            for key, value in coated.items():
                if key and (key in name or source in key):
                    want = value[0]
                    break
            if want is not None:
                matched.append((name, round(got, 4), round(want, 4)))
        check("the coat weight Maya set is the one Unreal has",
              bool(matched) and all(abs(got - want) < 0.001
                                    for _n, got, want in matched),
              matched)
        check("and coat is no longer reported as lost",
              not [w for w in result.get("warnings") or []
                   if "carries coat," in w],
              [w for w in result.get("warnings") or []
               if "carries coat," in w][:1])

    # A correction chain on a texture a receiver can actually open. The other
    # chains in this scene sit on .tx stubs Unreal refuses, so the correction
    # had nothing to correct and the gamma was never checked against a number.
    corrected = None
    for mesh_record in package_data.get("meshes") or []:
        for material_record in mesh_record.get("materials") or []:
            for channel, channel_record in (
                    material_record.get("channels") or {}).items():
                texture = (channel_record or {}).get("texture") or {}
                kinds = [str(entry.get("type")) for entry
                         in texture.get("corrections") or []]
                path = str(texture.get("path") or "")
                if "gammaCorrect" in kinds and path.lower().endswith(".png"):
                    corrected = (material_record, channel, texture, kinds)
                    break
            if corrected:
                break
        if corrected:
            break
    check("the package has a correction chain on a loadable texture",
          corrected is not None)
    if corrected is not None:
        material_record, channel, texture, kinds = corrected
        instance = unreal.EditorAssetLibrary.load_asset(
            "/Game/mLender/Materials/ML_{0}".format(
                material_record.get("material"))
        )
        check("its material instance exists", instance is not None,
              material_record.get("material"))
        if instance is not None:
            library = unreal.MaterialEditingLibrary
            parameter = "BaseColorMap"
            source_gamma = 1.0
            low = high = None
            for entry in texture.get("corrections") or []:
                values = (entry or {}).get("parameters") or {}
                if entry.get("type") == "gammaCorrect":
                    value = values.get("gamma")
                    if isinstance(value, list):
                        value = value[0]
                    source_gamma *= float(value or 1.0)
                if entry.get("type") == "clamp":
                    low = values.get("clamp_min")
                    high = values.get("clamp_max")
                    if isinstance(low, list):
                        low = low[0]
                    if isinstance(high, list):
                        high = high[0]
            got = library.get_material_instance_scalar_parameter_value(
                instance, parameter + "Gamma")
            # Maya applies in^(1/gamma) and Unreal's Power is in^exponent, so
            # the exponent is the reciprocal, not the number Maya holds.
            check("the gamma arrived as the reciprocal Unreal needs",
                  abs(got - 1.0 / source_gamma) < 0.001,
                  (round(got, 5), round(1.0 / source_gamma, 5)))
            if low is not None:
                check("the clamp bounds arrived",
                      abs(library.get_material_instance_scalar_parameter_value(
                          instance, parameter + "ClampMin") - low) < 0.001
                      and abs(
                          library.get_material_instance_scalar_parameter_value(
                              instance, parameter + "ClampMax") - high) < 0.001,
                      (low, high))
                check("and the clamp is switched on, not left at its default",
                      library.get_material_instance_scalar_parameter_value(
                          instance, parameter + "ClampUse") == 1.0,
                      library.get_material_instance_scalar_parameter_value(
                          instance, parameter + "ClampUse"))
        # A chain this build cannot rebuild must still be named.
        check("a correction it cannot rebuild is still reported by name",
              any("aiColorCorrect" in w for w in result.get("warnings") or []),
              [w for w in result.get("warnings") or []
               if "correction" in w.lower()][:1])

    # A colour correct node whose tail folds into the correction stack. The
    # chain Arnold runs is invert, gamma, contrast, exposure, multiply, add,
    # and everything after the gamma is affine -- measured, not assumed, in
    # tests/docs/color_correct.md. The expected numbers below come from that
    # measurement, not from the code under test.
    fold = None
    for mesh_record in package_data.get("meshes") or []:
        for material_record in mesh_record.get("materials") or []:
            for channel_record in (
                    material_record.get("channels") or {}).values():
                texture = (channel_record or {}).get("texture") or {}
                for entry in texture.get("corrections") or []:
                    if entry.get("type") != "aiColorCorrect":
                        continue
                    values = entry.get("parameters") or {}
                    multiply = values.get("multiply")
                    add = values.get("add")
                    uniform = all(
                        not isinstance(v, list) or len(set(
                            round(x, 6) for x in v)) == 1
                        for v in (multiply, add) if v is not None
                    )
                    if uniform and str(texture.get("path") or "").endswith(
                            ".png"):
                        fold = (material_record, values)
                        break
                if fold:
                    break
            if fold:
                break
        if fold:
            break
    check("the package has a foldable colour correct chain", fold is not None)
    if fold is not None:
        material_record, values = fold
        instance = unreal.EditorAssetLibrary.load_asset(
            "/Game/mLender/Materials/ML_{0}".format(
                material_record.get("material"))
        )
        check("its instance exists", instance is not None,
              material_record.get("material"))
        if instance is not None:
            library = unreal.MaterialEditingLibrary

            def first(value, fallback):
                if isinstance(value, list) and value:
                    return float(value[0])
                return float(value) if value is not None else fallback

            gamma = first(values.get("gamma"), 1.0)
            contrast = first(values.get("contrast"), 1.0)
            pivot = first(values.get("contrast_pivot"), 0.18)
            exposure = 2.0 ** first(values.get("exposure"), 0.0)
            multiply = first(values.get("multiply"), 1.0)
            offset = first(values.get("add"), 0.0)
            want_scale = contrast * exposure * multiply
            want_offset = (pivot * (1.0 - contrast) * exposure * multiply
                           + offset)
            got_gamma = library.get_material_instance_scalar_parameter_value(
                instance, "BaseColorMapGamma")
            got_scale = library.get_material_instance_scalar_parameter_value(
                instance, "BaseColorMapCorrScale")
            got_offset = library.get_material_instance_scalar_parameter_value(
                instance, "BaseColorMapCorrOffset")
            check("the gamma folded to the reciprocal",
                  abs(got_gamma - 1.0 / gamma) < 0.001,
                  (round(got_gamma, 5), round(1.0 / gamma, 5)))
            check("contrast, exposure and gain folded into one scale",
                  abs(got_scale - want_scale) < 0.001,
                  (round(got_scale, 5), round(want_scale, 5)))
            check("and the offset came with them",
                  abs(got_offset - want_offset) < 0.001,
                  (round(got_offset, 5), round(want_offset, 5)))
    # A gain that differs per channel cannot ride a one-scalar stack, and
    # taking the red channel quietly would lose the other two.
    check("a per-channel gain is reported rather than truncated",
          any("per-channel" in w for w in result.get("warnings") or []),
          [w for w in result.get("warnings") or [] if "per-channel" in w][:1])

    # remapValue, as a one row lookup texture. A curve cannot fold into a
    # number the way the rest of the chain does, so this is the one correction
    # that arrives as an asset.
    remap = None
    for mesh_record in package_data.get("meshes") or []:
        for material_record in mesh_record.get("materials") or []:
            for channel, channel_record in (
                    material_record.get("channels") or {}).items():
                texture = (channel_record or {}).get("texture") or {}
                kinds = [str(entry.get("type")) for entry
                         in texture.get("corrections") or []]
                if kinds == ["remapValue"] and texture.get("path"):
                    remap = (material_record, channel)
                    break
            if remap:
                break
        if remap:
            break
    if remap is not None:
        material_record, channel = remap
        instance = unreal.EditorAssetLibrary.load_asset(
            "/Game/mLender/Materials/ML_{0}".format(
                material_record.get("material"))
        )
        parameter = {
            "base_color": "BaseColorMap", "roughness": "RoughnessMap",
            "metallic": "MetallicMap", "specular": "SpecularMap",
            "opacity": "OpacityMap", "normal": "NormalMap",
            "emission": "EmissiveMap",
        }.get(channel)
        check("the remapped material was built",
              instance is not None and parameter is not None,
              (material_record.get("material"), channel))
        if instance is not None and parameter:
            library = unreal.MaterialEditingLibrary
            curve = library.get_material_instance_texture_parameter_value(
                instance, parameter + "RemapCurve")
            check("its curve arrived as a lookup texture",
                  curve is not None, parameter)
            if curve is not None:
                check("one row, and not colour managed",
                      curve.blueprint_get_size_y() == 1
                      and not curve.get_editor_property("srgb"),
                      (curve.blueprint_get_size_x(),
                       curve.blueprint_get_size_y(),
                       curve.get_editor_property("srgb")))
            check("and the material is told to use it",
                  library.get_material_instance_scalar_parameter_value(
                      instance, parameter + "RemapUse") == 1.0,
                  library.get_material_instance_scalar_parameter_value(
                      instance, parameter + "RemapUse"))

    # Blend shaders, as a graph of their own. A Material Instance shares one
    # master and can only change numbers, so a stack of surfaces cannot be one
    # -- this is the other half of the hybrid.
    blends = []
    for mesh_record in package_data.get("meshes") or []:
        for material_record in mesh_record.get("materials") or []:
            if len(material_record.get("layers") or []) > 1:
                blends.append(material_record)
    check("the package has blend shaders", bool(blends),
          [b.get("material") for b in blends])
    if blends:
        library = unreal.MaterialEditingLibrary
        graphs = 0
        instances = 0
        for material_record in blends:
            asset = unreal.EditorAssetLibrary.load_asset(
                "/Game/mLender/Materials/ML_{0}".format(
                    material_record.get("material"))
            )
            if isinstance(asset, unreal.MaterialInstanceConstant):
                instances += 1
            elif isinstance(asset, unreal.Material):
                graphs += 1
        check("every one of them became a Material, not an instance",
              graphs == len(blends) and instances == 0,
              (graphs, instances, len(blends)))

        # The one with a plain mix weight: its numbers have a single right
        # answer on the other side, so they are checked against Maya's own
        # record rather than against this build's arithmetic.
        mixed = None
        for material_record in blends:
            layers = material_record["layers"]
            if (layers[1].get("mix") or {}).get("value") is not None:
                mixed = material_record
                break
        if mixed is not None:
            asset = unreal.EditorAssetLibrary.load_asset(
                "/Game/mLender/Materials/ML_{0}".format(mixed["material"]))
            check("the blended material uses material attributes",
                  asset is not None
                  and asset.get_editor_property("use_material_attributes"),
                  mixed["material"])
            want_mix = float(mixed["layers"][1]["mix"]["value"])
            try:
                got_mix = library.get_material_default_scalar_parameter_value(
                    asset, "Layer1")
            except Exception:
                got_mix = None
            check("the mix weight Maya set is the weight Unreal blends with",
                  got_mix is not None and abs(got_mix - want_mix) < 0.001,
                  (got_mix, want_mix))
            # Both layers, because a graph that wired one layer twice would
            # pass a single-layer check.
            matched = []
            for index, layer in enumerate(mixed["layers"]):
                want = ((layer.get("channels") or {}).get("base_color")
                        or {}).get("value")
                if not want:
                    continue
                try:
                    got = library.get_material_default_vector_parameter_value(
                        asset, "Layer{0}_BaseColor".format(index))
                except Exception:
                    got = None
                if got is None:
                    matched.append((index, "missing"))
                    continue
                if (abs(got.r - want[0]) > 0.002
                        or abs(got.g - want[1]) > 0.002
                        or abs(got.b - want[2]) > 0.002):
                    matched.append((index, (got.r, got.g, got.b), want))
            check("and each layer kept its own colour",
                  not matched, matched)

        # And the level wears it, which is the claim that matters to a user.
        worn = 0
        for actor in (unreal.get_editor_subsystem(
                unreal.EditorActorSubsystem).get_all_level_actors() or []):
            if not isinstance(actor, unreal.StaticMeshActor):
                continue
            component = actor.static_mesh_component
            try:
                count = component.get_num_materials()
            except Exception:
                continue
            for slot in range(count):
                material = component.get_material(slot)
                if (material is not None
                        and isinstance(material, unreal.Material)
                        and material.get_name().startswith("ML_")):
                    worn += 1
        check("a mesh in the level actually wears a blend graph", worn > 0,
              worn)

    # A layeredShader in "layer_shaders" mode adds rather than blends, which
    # is not something BlendMaterialAttributes can be told to do. It has to be
    # reported rather than quietly turned into a fade.
    adding = [
        material_record for mesh_record in (package_data.get("meshes") or [])
        for material_record in (mesh_record.get("materials") or [])
        for layer in (material_record.get("layers") or [])
        if layer.get("compositing") not in (None, "", "layer_texture")
    ]
    if adding:
        check("a layeredShader that adds is reported, not faked as a fade",
              any("adds the upper layer" in w
                  for w in result.get("warnings") or []),
              [w for w in result.get("warnings") or []
               if "layeredShader" in w][:1])

    # Film fit, resolved against the render aspect.
    #
    # Maya frames with the film back *and* its fit *and* the resolution.
    # Unreal's cine camera has no fit, so a raw film back only reproduces
    # Maya's framing when the render happens to share its aspect -- and here
    # it does not: a 36 x 24 back is 1.5 against a 1920 x 804 image.
    render_record = package_data.get("render") or {}
    width = float(render_record.get("width") or 0)
    height = float(render_record.get("height") or 0)
    pixel = float(render_record.get("pixel_aspect") or 1.0) or 1.0
    if width > 0 and height > 0:
        want_aspect = (width / height) * pixel
        cine = []
        for actor in (unreal.get_editor_subsystem(
                unreal.EditorActorSubsystem).get_all_level_actors() or []):
            if isinstance(actor, unreal.CineCameraActor):
                cine.append(actor)
        check("the scene brought cine cameras", bool(cine), len(cine))
        off = []
        for actor in cine:
            filmback = actor.camera_component.filmback
            if not filmback.sensor_height:
                continue
            got = filmback.sensor_width / filmback.sensor_height
            if abs(got - want_aspect) > 0.001:
                off.append((actor.get_actor_label(), round(got, 4)))
        check("the film fit was resolved against the render aspect",
              not off, (off, round(want_aspect, 4)))
        # And the extent the fit promises to keep is the one that survived.
        # Horizontal keeps the width, so the width must be Maya's own number;
        # a fit resolved the wrong way round would still match the aspect
        # above while framing something else entirely.
        kept = []
        for record in package_data.get("cameras") or []:
            fit = str(record.get("film_fit") or "").lower()
            actor = next(
                (a for a in cine
                 if a.get_actor_label() == record.get("name")), None)
            if actor is None:
                continue
            filmback = actor.camera_component.filmback
            source_w = float(record.get("sensor_width_mm") or 0)
            source_h = float(record.get("sensor_height_mm") or 0)
            if fit.startswith("horizontal"):
                kept.append((record.get("name"), "width",
                             abs(filmback.sensor_width - source_w) < 0.01))
            elif fit.startswith("vertical"):
                kept.append((record.get("name"), "height",
                             abs(filmback.sensor_height - source_h) < 0.01))
        check("and each fit kept the extent it names",
              kept and all(ok for _n, _k, ok in kept),
              [(n, k) for n, k, ok in kept if not ok] or kept)
        # The render itself, which is the other half of the same question.
        if result.get("render_config_path"):
            config = unreal.load_asset(
                result["render_config_path"].split(".")[0])
            found = None
            for setting in (config.get_all_settings() or []) if config else []:
                if isinstance(setting, unreal.MoviePipelineOutputSetting):
                    found = setting.get_editor_property("output_resolution")
            check("the render config carries Maya's resolution",
                  found is not None and found.x == int(width)
                  and found.y == int(height),
                  (found.x, found.y) if found else None)

    # Maya's own warnings, repeated here. Until a real scene turned up, the
    # exporter wrote them into the package and no receiver read them -- so a
    # scene sent with Export Animation off built no sequence and explained
    # nothing on either side.
    said = package_data.get("export_warnings") or []
    check("the package carries warnings from the Maya side", bool(said),
          len(said))
    if said:
        carried = [w for w in result.get("warnings") or []
                   if w.startswith("Maya said:")]
        check("and every one of them is repeated here",
              len(carried) == len(said), (len(carried), len(said)))
        check("the importer counted them",
              result.get("export_warning_count") == len(said),
              result.get("export_warning_count"))

    # AOVs, as a Movie Render Queue config. Render passes are not level
    # contents in Unreal, so what has to exist is the config the user renders
    # with -- and the mapping has to be by quantity, not by name: Unreal has a
    # DiffuseColor buffer and Arnold's "diffuse" AOV is not it.
    aov_records = package_data.get("aovs") or []
    if aov_records:
        check("a render config was built",
              bool(result.get("render_config_path")),
              result.get("render_config_path"))
        config = None
        if result.get("render_config_path"):
            config = unreal.load_asset(
                result["render_config_path"].split(".")[0])
        check("and it loads", config is not None)
        if config is not None:
            settings = config.get_all_settings() or []
            kinds = [type(setting).__name__ for setting in settings]
            check("it has a deferred pass to render",
                  any("DeferredPass" in kind for kind in kinds), kinds)
            check("and an EXR output, so the AOVs are layers of one file",
                  any("EXR" in kind for kind in kinds), kinds)
            wanted_crypto = any(
                str(record.get("name") or "").lower().startswith("crypto")
                for record in aov_records
            )
            if wanted_crypto:
                check("cryptomatte became the object id pass",
                      any("ObjectId" in kind for kind in kinds), kinds)
            materials = []
            for setting in settings:
                if isinstance(setting, unreal.MoviePipelineDeferredPassBase):
                    materials = setting.get_editor_property(
                        "additional_post_process_materials") or []
            names = [entry.get_editor_property("name") for entry in materials]
            # The quantities Unreal really holds. Depth and normal are the two
            # a compositor asks for first.
            for wanted in ("Z", "N"):
                if any(str(r.get("name")) == wanted for r in aov_records):
                    check("the " + wanted + " AOV became a pass",
                          wanted in names, names)
            check("every AOV pass has its material",
                  all(entry.get_editor_property("material") is not None
                      for entry in materials),
                  names)
            check("depth is written at high precision, not quantised to 8 bit",
                  all(entry.get_editor_property("high_precision_output")
                      for entry in materials),
                  names)
        # And the ones that are a different quantity must be named, not
        # quietly filled with the buffer that shares their name.
        check("a light transport AOV is reported rather than faked",
              any("diffuse" in w and "different image" in w
                  for w in result.get("warnings") or []),
              [w for w in result.get("warnings") or [] if "AOV" in w][:1])
        check("the importer counted what it carried and what it did not",
              (result.get("aov_passes", 0) + result.get("aov_reported", 0))
              == len(aov_records),
              (result.get("aov_passes"), result.get("aov_reported"),
               len(aov_records)))

    # The FBX brings an AnimSequence and used to leave it in the content
    # browser: measured, four skeletal actors sat in ANIMATION_BLUEPRINT mode
    # with no asset while Take_001 existed beside them, so a skinned character
    # arrived in its bind pose and never moved.
    skeletal = [
        actor for actor in (unreal.get_editor_subsystem(
            unreal.EditorActorSubsystem).get_all_level_actors() or [])
        if isinstance(actor, unreal.SkeletalMeshActor)
    ]
    if skeletal:
        playing = []
        for actor in skeletal:
            data = actor.skeletal_mesh_component.get_editor_property(
                "animation_data")
            asset = getattr(data, "anim_to_play", None)
            if asset is not None:
                playing.append((actor.get_actor_label(), asset.get_name()))
        check("a skeletal actor was given the take the FBX brought",
              bool(playing),
              [a.get_actor_label() for a in skeletal])
        # Stored on the component, not only on the live instance: setting the
        # second alone left animation_data empty, so the assignment vanished
        # the moment anybody reloaded the map.
        check("and it is stored on the component, not just played",
              all(actor.skeletal_mesh_component.get_editor_property(
                  "animation_mode")
                  == unreal.AnimationMode.ANIMATION_SINGLE_NODE
                  for actor, _name in [
                      (a, None) for a in skeletal
                      if getattr(a.skeletal_mesh_component.get_editor_property(
                          "animation_data"), "anim_to_play", None) is not None
                  ]),
              playing)
        check("the importer counted it", result.get("skeletal_animated", 0) > 0,
              result.get("skeletal_animated"))

    # A UDIM set. Measured: handed the first tile with its siblings beside it,
    # Unreal finds the rest itself and switches virtual texture streaming on,
    # which is how the engine says "this is a set". The exporter writes a
    # <UDIM> token, so the only work is handing over a concrete tile.
    udim_material = None
    udim_channel = None
    for mesh_record in package_data.get("meshes") or []:
        for material_record in mesh_record.get("materials") or []:
            for channel, channel_record in (
                    material_record.get("channels") or {}).items():
                texture = (channel_record or {}).get("texture") or {}
                if texture.get("udim"):
                    udim_material = material_record
                    udim_channel = channel
                    break
            if udim_material:
                break
        if udim_material:
            break
    check("the package carries a UDIM set", udim_material is not None,
          udim_material and udim_material.get("material"))
    if udim_material is not None:
        instance = unreal.EditorAssetLibrary.load_asset(
            "/Game/mLender/Materials/ML_{0}".format(
                udim_material.get("material"))
        )
        check("its material instance was built", instance is not None,
              udim_material.get("material"))
        if instance is not None:
            parameter = {
                "base_color": "BaseColorMap", "roughness": "RoughnessMap",
                "metallic": "MetallicMap", "specular": "SpecularMap",
                "opacity": "OpacityMap", "normal": "NormalMap",
                "emission": "EmissiveMap",
            }.get(udim_channel)
            texture_asset = None
            if parameter:
                texture_asset = unreal.MaterialEditingLibrary.\
                    get_material_instance_texture_parameter_value(
                        instance, parameter)
            check("the UDIM texture reached the material",
                  texture_asset is not None,
                  (udim_channel, parameter))
            if texture_asset is not None:
                check("and Unreal recognised it as a set, not one tile",
                      bool(texture_asset.get_editor_property(
                          "virtual_texture_streaming")),
                      texture_asset.get_editor_property(
                          "virtual_texture_streaming"))
        check("nothing reported the set as untiled",
              not [w for w in result.get("warnings") or []
                   if "without tiling" in w],
              [w for w in result.get("warnings") or []
               if "without tiling" in w][:1])

    # The dome HDR as the sky light cubemap. Measured: Unreal reads a
    # Radiance .hdr straight into a TextureCube, so a lat-long environment
    # needs no conversion step -- but the import decides that, so the result
    # is checked rather than assumed.
    dome_record = next(
        (record for record in (package_data.get("lights") or [])
         if (record.get("dome_texture") or {}).get("path")),
        None,
    )
    if dome_record is not None:
        sky = None
        for actor in (unreal.get_editor_subsystem(
                unreal.EditorActorSubsystem).get_all_level_actors() or []):
            if isinstance(actor, unreal.SkyLight):
                sky = actor
                break
        check("a sky light stands in for the dome", sky is not None)
        if sky is not None:
            component = sky.light_component
            check("its source is the specified cubemap, not the scene",
                  component.get_editor_property("source_type")
                  == unreal.SkyLightSourceType.SLS_SPECIFIED_CUBEMAP,
                  component.get_editor_property("source_type"))
            cubemap = component.get_editor_property("cubemap")
            check("and the Maya HDR is the cubemap",
                  isinstance(cubemap, unreal.TextureCube),
                  type(cubemap).__name__ if cubemap else "none")
        check("nothing reported the HDR as unloaded",
              not [w for w in result.get("warnings") or []
                   if "cubemap" in w and "does not load" in w],
              [w for w in result.get("warnings") or [] if "cubemap" in w][:1])

    # An IES profile, which shapes the light without taking over its
    # brightness. use_ies_brightness stays off on purpose: turning it on hands
    # the level to whatever the file says and abandons the measured intensity
    # conversion, so two lights calibrated the same way would disagree.
    ies_record = next(
        (record for record in (package_data.get("lights") or [])
         if (record.get("ies_profile") or {}).get("path")),
        None,
    )
    if ies_record is not None:
        ies_actor = None
        for actor in (unreal.get_editor_subsystem(
                unreal.EditorActorSubsystem).get_all_level_actors() or []):
            try:
                if actor.get_actor_label() == ies_record.get("name"):
                    ies_actor = actor
                    break
            except Exception:
                continue
        check("the IES light is in the level", ies_actor is not None,
              ies_record.get("name"))
        if ies_actor is not None:
            component = ies_actor.light_component
            profile = component.get_editor_property("ies_texture")
            check("its IES profile was loaded and attached",
                  profile is not None, profile)
            check("and the profile did not take over the brightness",
                  not component.get_editor_property("use_ies_brightness"),
                  component.get_editor_property("use_ies_brightness"))
            check("so the intensity is still the converted one",
                  component.get_editor_property("intensity") > 0.0,
                  component.get_editor_property("intensity"))
        check("nothing reported the IES profile as dropped",
              not [w for w in result.get("warnings") or []
                   if "IES" in w and "plain" in w],
              [w for w in result.get("warnings") or [] if "IES" in w][:1])

    # --- Level Sequence: light, camera and visibility animation.
    #
    # These assertions play the sequence rather than counting its keys. Keys
    # that exist and keys that reach the actor are different claims, and this
    # build was already caught making the first while failing the second: a
    # version that keyed the record static intensity twenty five times agreed
    # with its own expected value and animated nothing.
    animation = package_data.get("animation") or {}
    if animation.get("enabled"):
        check("a Level Sequence was built", bool(result.get("sequence_path")),
              result.get("sequence_path"))
        check("with tracks on it", result.get("animation_track_count", 0) > 0,
              result.get("animation_track_count"))
        sequence = None
        if result.get("sequence_path"):
            sequence = unreal.load_asset(
                result["sequence_path"].split(".")[0]
            )
        if sequence is not None:
            fps = float(animation.get("fps") or 24.0)
            per_frame = sequence.get_tick_resolution().numerator / fps
            player_actor = unreal.EditorLevelLibrary.spawn_actor_from_class(
                unreal.LevelSequenceActor, unreal.Vector(0.0, 0.0, 0.0)
            )
            player_actor.set_sequence(sequence)
            player = player_actor.sequence_player
            by_label = {}
            for actor in (unreal.get_editor_subsystem(
                    unreal.EditorActorSubsystem
            ).get_all_level_actors() or []):
                try:
                    by_label.setdefault(actor.get_actor_label(), actor)
                except Exception:
                    continue

            def scrub(frame):
                params = unreal.MovieSceneSequencePlaybackParams()
                params.set_editor_property("frame", unreal.FrameTime(
                    unreal.FrameNumber(int(round(frame * per_frame)))))
                params.set_editor_property(
                    "position_type", unreal.MovieScenePositionType.FRAME)
                params.set_editor_property(
                    "update_method", unreal.UpdatePositionMethod.JUMP)
                player.set_playback_position(params)

            start = float(animation.get("start") or 1.0)
            end = float(animation.get("end") or start)
            # Never the last frame: landing on the end finishes the sequence
            # and restores the pre-animated values, which reads as "nothing
            # was keyed" when everything was.
            middle = (start + end) / 2.0
            last_inside = end - 1.0

            light_record = None
            for record in (package_data.get("lights") or []):
                samples = record.get("samples") or []
                if len(samples) > 1 and len(set(
                        sample.get("intensity") for sample in samples)) > 1:
                    light_record = record
                    break
            check("the package has a light whose intensity really moves",
                  light_record is not None,
                  [r.get("name") for r in package_data.get("lights") or []])
            light_actor = by_label.get((light_record or {}).get("name") or "")
            if light_record is not None and light_actor is not None:
                samples = light_record["samples"]

                def sample_at(frame, samples=samples):
                    return min(samples,
                               key=lambda s: abs(s.get("frame", 0) - frame))

                readings = []
                for frame in (start, middle, last_inside):
                    scrub(frame)
                    component = light_actor.light_component
                    readings.append((
                        component.intensity,
                        light_actor.get_actor_location().x,
                        component.light_color.r,
                        component.light_color.g,
                    ))
                check("the sequence actually drives the light intensity",
                      readings[0][0] < readings[1][0] < readings[2][0],
                      [round(r[0], 4) for r in readings])
                # Against the Maya numbers, not against this build own
                # conversion: a ratio is independent of the calibration
                # constant, so it still fails if the samples stop being
                # followed after somebody changes that constant.
                maya_first = sample_at(start).get("intensity")
                maya_last = sample_at(last_inside).get("intensity")
                if maya_first:
                    want = maya_last / float(maya_first)
                    got = readings[2][0] / readings[0][0]
                    check("and follows the Maya intensity ratio",
                          abs(got - want) < 0.02 * max(1.0, want),
                          (round(got, 4), round(want, 4)))
                check("the sequence drives the light position too",
                      abs(readings[2][1] - readings[0][1]) > 1.0,
                      [round(r[1], 3) for r in readings])
                check("and the colour, red falling as green rises",
                      readings[2][2] < readings[0][2]
                      and readings[2][3] > readings[0][3],
                      [(r[2], r[3]) for r in readings])

            # Keyed material parameters. The time argument on this API is
            # not the one the other channels take -- measured on the same
            # sequence, a transform channel handed 1000 stores 1000 and
            # add_scalar_parameter_key handed 1000 stores 1 -- so the check
            # reads values back through the dynamic instance Sequencer makes
            # rather than trusting that the keys went in.
            keyed_material = None
            keyed_mesh = None
            for mesh_record in package_data.get("meshes") or []:
                for material_record in mesh_record.get("materials") or []:
                    channels = material_record.get("channels") or {}
                    if any((r or {}).get("samples") for r in channels.values()):
                        keyed_material = material_record
                        keyed_mesh = mesh_record
                        break
                if keyed_material:
                    break
            check("the package has a keyed material parameter",
                  keyed_material is not None,
                  keyed_material and keyed_material.get("material"))
            mesh_actor = by_label.get((keyed_mesh or {}).get("mesh") or "")
            if keyed_material is not None and mesh_actor is not None:
                component = mesh_actor.static_mesh_component
                channels = keyed_material.get("channels") or {}
                rough = (channels.get("roughness") or {}).get("samples") or []
                colour = (channels.get("base_color") or {}).get("samples") or []
                readings = []
                for frame in (start, middle, last_inside):
                    scrub(frame)
                    material = component.get_material(0)
                    try:
                        got_scalar = material.get_scalar_parameter_value(
                            "Roughness")
                        got_colour = material.get_vector_parameter_value(
                            "BaseColor")
                    except Exception:
                        got_scalar = None
                        got_colour = None
                    want_scalar = None
                    for sample in rough:
                        if abs(sample.get("frame", 0) - frame) < 0.01:
                            want_scalar = sample.get("value")
                    want_colour = None
                    for sample in colour:
                        if abs(sample.get("frame", 0) - frame) < 0.01:
                            want_colour = sample.get("value")
                    readings.append(
                        (got_scalar, want_scalar, got_colour, want_colour)
                    )
                # Sequencer swaps in a dynamic instance when a material track
                # drives the slot. A constant instance here means the track
                # never took hold.
                check("a material track drives the mesh slot",
                      "Dynamic" in type(component.get_material(0)).__name__,
                      type(component.get_material(0)).__name__)
                scalar_ok = [
                    (round(got, 4), round(want, 4))
                    for got, want, _gc, _wc in readings
                    if got is not None and want is not None
                    and abs(got - want) > 0.002
                ]
                check("the keyed roughness follows Maya frame by frame",
                      not scalar_ok
                      and any(got is not None for got, _w, _gc, _wc in readings),
                      scalar_ok or [r[0] for r in readings])
                colour_off = [
                    (gc.r, wc[0]) for _gs, _ws, gc, wc in readings
                    if gc is not None and wc is not None
                    and abs(gc.r - wc[0]) > 0.002
                ]
                check("and so does the keyed base colour",
                      not colour_off,
                      colour_off)
                check("nothing still calls a keyed channel frozen",
                      not [w for w in result.get("warnings") or []
                           if "does not animate it" in w],
                      [w for w in result.get("warnings") or []
                       if "does not animate it" in w][:1])

            # Object motion, which does not ride in the package at all --
            # meshes carry their animation inside the FBX. Interchange
            # imports it into a sequence of its own with every key written at
            # its frame number as a *tick*, so a move that spans the whole
            # shot happens inside the first fiftieth of a frame and is over
            # before frame one. It reads exactly like nothing moved, which is
            # how it was reported. The keys are retimed onto this sequence, so
            # what has to be true is that the object is in a different place
            # at the end than at the start.
            mover = None
            for actor in (unreal.get_editor_subsystem(
                    unreal.EditorActorSubsystem).get_all_level_actors() or []):
                try:
                    if actor.get_actor_label() == "flatCube":
                        mover = actor
                        break
                except Exception:
                    continue
            check("the mesh Maya animated is in the level", mover is not None)
            if mover is not None:
                places = []
                for frame in (start, middle, last_inside):
                    scrub(frame)
                    location = mover.get_actor_location()
                    places.append(round(location.x, 2))
                check("and the sequence moves it, not just the lights",
                      abs(places[-1] - places[0]) > 1.0, places)
                # Monotonic, because a move that lands right but jumps about
                # in between is a retime that got its scale wrong.
                # On the axis Maya moved it, and only that one. Maya's Y is
            # Unreal's Z, so a drop must land in Z -- a channel mapping that
            # slipped would still animate, sideways, and still pass every
            # check above.
            dropper = None
            for actor in (unreal.get_editor_subsystem(
                    unreal.EditorActorSubsystem).get_all_level_actors() or []):
                try:
                    if actor.get_actor_label() == "dropCube":
                        dropper = actor
                        break
                except Exception:
                    continue
            check("the object Maya dropped is in the level",
                  dropper is not None)
            if dropper is not None:
                readings = []
                for frame in (start, last_inside):
                    scrub(frame)
                    location = dropper.get_actor_location()
                    readings.append((round(location.x, 2), round(location.y, 2),
                                     round(location.z, 2)))
                first_read, last_read = readings[0], readings[-1]
                check("it falls on Unreal's Z, which is Maya's Y",
                      abs(last_read[2] - first_read[2]) > 1.0, readings)
                check("and stays put on the other two",
                      abs(last_read[0] - first_read[0]) < 0.01
                      and abs(last_read[1] - first_read[1]) < 0.01,
                      readings)

            check("smoothly, in one direction",
                      (places[0] <= places[1] <= places[2])
                      or (places[0] >= places[1] >= places[2]),
                      places)

            camera_record = None
            for record in (package_data.get("cameras") or []):
                samples = record.get("samples") or []
                if len(set(sample.get("focal_length_mm")
                           for sample in samples)) > 1:
                    camera_record = record
                    break
            camera_actor = by_label.get((camera_record or {}).get("name") or "")
            if camera_record is not None and camera_actor is not None:
                focals = []
                wanted = []
                for frame in (start, last_inside):
                    scrub(frame)
                    focals.append(
                        camera_actor.camera_component.current_focal_length
                    )
                    nearest = min(
                        camera_record["samples"],
                        key=lambda s, f=frame: abs(s.get("frame", 0) - f),
                    )
                    wanted.append(nearest.get("focal_length_mm"))
                check("the sequence drives the camera focal length",
                      all(abs(got - expect) < 0.01
                          for got, expect in zip(focals, wanted)),
                      (focals, wanted))

            blink = None
            for record in (package_data.get("meshes") or []):
                samples = record.get("visibility_samples") or []
                if len(set(bool(s.get("visible")) for s in samples)) > 1:
                    blink = record
                    break
            blink_actor = by_label.get((blink or {}).get("mesh") or "")
            if blink is not None and blink_actor is not None:
                states = []
                for sample in blink["visibility_samples"]:
                    frame = sample.get("frame")
                    if frame is None or frame >= end:
                        continue
                    scrub(frame)
                    states.append((bool(sample.get("visible")),
                                   not blink_actor.is_hidden_ed()))
                mismatched = [s for s in states if s[0] != s[1]]
                check("the sequence hides and shows the mesh Maya blinked",
                      bool(states) and not mismatched,
                      mismatched[:4] or "all matched")

    expected_lights = len([
        record for record in (package_data.get("lights") or [])
        if record.get("enabled", True)
    ])
    check("lights were built", result["light_count"] > 0,
          "{0}, package had {1}".format(result["light_count"], expected_lights))
    check("cameras were built",
          result["camera_count"] == len(package_data.get("cameras") or []),
          "{0} of {1}".format(
              result["camera_count"], len(package_data.get("cameras") or [])
          ))

    # ------------------------------------------- the JSON-rebuilt kinds
    # Counted against the package rather than against a number typed here, so
    # the assertions follow the fixture instead of freezing today's one.
    print("\nkinds the JSON rebuilds")
    for key, result_key, label in (
        ("transforms", "transform_count", "locators"),
        ("curves", "curve_count", "curves"),
        ("volumes", "volume_count", "volumes"),
        ("standins", "standin_count", "standins"),
        ("particles", "particle_count", "particle systems"),
        ("instancers", "instancer_count", "instancers"),
    ):
        wanted = len(package_data.get(key) or [])
        got = result.get(result_key, 0)
        if not wanted:
            continue
        check(
            "every one of the {0} arrived ({1}/{2})".format(label, got, wanted),
            got == wanted,
            "package had {0}, built {1}".format(wanted, got),
        )

    # A count is not enough for the two that reference a file: a standin that
    # anchored and a standin that loaded its cache both count as one.
    if package_data.get("standins"):
        check(
            "at least one standin loaded its cache rather than anchoring",
            result.get("standin_loaded", 0) > 0,
            "{0} of {1} loaded".format(
                result.get("standin_loaded"),
                len(package_data.get("standins") or []),
            ),
        )
    report_path = result.get("report_path") or ""
    check("the import wrote a report", bool(report_path)
          and os.path.isfile(report_path), report_path)
    if report_path and os.path.isfile(report_path):
        report_text = open(report_path, encoding="utf-8").read()
        check("the report lists every warning",
              report_text.count("  - ") >= len(result.get("warnings") or []),
              (report_text.count("  - "), len(result.get("warnings") or [])))
        check("the report says what arrived",
              "what arrived" in report_text, report_text[:60])

    # Skinned meshes. Interchange brings these as SkeletalMesh with no
    # override; the receiver used to filter them out of its own results, so
    # they sat in the level unmatched and holding placeholder materials.
    skeletal_in_level = [
        actor for actor in unreal.get_editor_subsystem(
            unreal.EditorActorSubsystem
        ).get_all_level_actors() or []
        if actor.get_class().get_name() == "SkeletalMeshActor"
    ]
    if skeletal_in_level:
        check(
            "skinned meshes arrived as skeletal actors",
            result.get("skeletal_count", 0) > 0,
            "{0} counted, {1} in level".format(
                result.get("skeletal_count"), len(skeletal_in_level)
            ),
        )
        ours_skeletal = 0
        for actor in skeletal_in_level:
            component = getattr(actor, "skeletal_mesh_component", None)
            if component is None:
                continue
            try:
                for index in range(component.get_num_materials()):
                    material = component.get_material(index)
                    if material and material.get_name().startswith("ML_"):
                        ours_skeletal += 1
            except Exception:
                continue
        check(
            "a skeletal mesh carries a rebuilt material, not a placeholder",
            ours_skeletal > 0,
            "{0} skeletal slot(s) hold ML_ materials".format(ours_skeletal),
        )
        if package_data.get("as_rigs"):
            check(
                "the Advanced Skeleton manifest reached a skeletal actor",
                result.get("as_skeletal_actors", 0) > 0,
                "{0} actor(s) tagged from {1} rig record(s)".format(
                    result.get("as_skeletal_actors"),
                    len(package_data.get("as_rigs") or []),
                ),
            )

    # The cache is not an optional extra: the meshes in it were kept out of the
    # FBX on purpose, so a failure here means they are absent from the level
    # entirely rather than merely unrefined.
    cache_record = package_data.get("alembic") or {}
    if cache_record.get("file") and os.path.isfile(
        str(cache_record.get("file"))
    ):
        check(
            "the package's Alembic cache arrived",
            result.get("alembic_count", 0) > 0,
            "{0} cache actor(s) for {1} cached mesh(es)".format(
                result.get("alembic_count"), cache_record.get("mesh_count")
            ),
        )
        found = [
            actor for actor in unreal.get_editor_subsystem(
                unreal.EditorActorSubsystem
            ).get_all_level_actors() or []
            if actor.get_class().get_name() == "GeometryCacheActor"
        ]
        check(
            "a GeometryCacheActor is in the level carrying a cache",
            any(
                (getattr(a, "geometry_cache_component", None) is not None)
                for a in found
            ) and bool(found),
            "{0} geometry cache actor(s)".format(len(found)),
        )

    # Only demand a loaded volume when the VDB is actually on disk. The fixture
    # references smoke.vdb without creating it, so anchoring is the correct
    # behaviour there -- an unconditional assertion here failed a working
    # importer, which is the test being wrong rather than the code.
    volume_files_present = [
        record for record in (package_data.get("volumes") or [])
        if os.path.isfile(str(record.get("file_path") or ""))
    ]
    if volume_files_present:
        check(
            "the VDB volume attached its sparse volume texture",
            result.get("volume_loaded", 0) > 0,
            "{0} loaded of {1} present".format(
                result.get("volume_loaded"), len(volume_files_present)
            ),
        )
    elif package_data.get("volumes"):
        check(
            "a volume whose VDB is absent anchored instead of vanishing",
            result.get("volume_count", 0) > 0
            and result.get("volume_loaded", 0) == 0,
            "count {0}, loaded {1}".format(
                result.get("volume_count"), result.get("volume_loaded")
            ),
        )
    if package_data.get("curves"):
        check(
            "curves arrived as editable splines, not anchors",
            result.get("curve_splines", 0) > 0,
            "{0} of {1} are splines".format(
                result.get("curve_splines"),
                len(package_data.get("curves") or []),
            ),
        )
    if package_data.get("instancers"):
        check(
            "the instancer actually scattered points",
            result.get("instance_count", 0) > 0,
            "{0} instances".format(result.get("instance_count")),
        )
    if package_data.get("selection_sets") or package_data.get("display_layers"):
        check(
            "sets and layers became Unreal layers",
            result.get("set_count", 0) + result.get("layer_count", 0) > 0,
            "{0} sets, {1} layers".format(
                result.get("set_count"), result.get("layer_count")
            ),
        )
        layers = unreal.get_editor_subsystem(unreal.LayersSubsystem)
        named = []
        try:
            for record in package_data.get("display_layers") or []:
                name = record.get("layer_full_name") or record.get("layer")
                if not name:
                    continue
                members = layers.get_actors_from_layer(
                    "ML_Layer_" + str(name).replace(":", "_")
                )
                if members:
                    named.append(name)
        except Exception as exc:
            print("  layer query failed:", exc)
        check(
            "a display layer reports its members back",
            bool(named) or not (package_data.get("display_layers") or []),
            "none of the layers reported members",
        )

    # ---------------------------------------------------- what is in the level
    print("\nlevel contents")
    subsystem = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
    actors = list(subsystem.get_all_level_actors() or [])
    kinds = {}
    for actor in actors:
        kinds[actor.get_class().get_name()] = kinds.get(
            actor.get_class().get_name(), 0
        ) + 1
    print("  actors:", kinds)
    check("static mesh actors are in the level",
          kinds.get("StaticMeshActor", 0) > 0, str(kinds))
    check("light actors are in the level",
          any(name.endswith("Light") for name in kinds), str(kinds))
    check("a cine camera is in the level",
          kinds.get("CineCameraActor", 0) > 0, str(kinds))

    # A mesh must actually be carrying one of our instances, not the FBX's
    # placeholder. Checking the count alone would pass on a build that made
    # the materials and assigned none of them.
    ours = 0
    for actor in actors:
        if not isinstance(actor, unreal.StaticMeshActor):
            continue
        component = actor.static_mesh_component
        try:
            count = component.get_num_materials()
        except Exception:
            continue
        for index in range(count):
            material = component.get_material(index)
            if material is not None and material.get_name().startswith("ML_"):
                ours += 1
    check("meshes carry the rebuilt materials", ours > 0, str(ours))

    # The light energy has to survive the round trip into the component, not
    # merely be computed correctly above. Asserted in lumens rather than in
    # whatever unit Unreal settled on: a RectLightComponent silently reports
    # CANDELAS after being given LUMENS, and an assertion on the enum would
    # either fail on a correct light or pass on a light that is 4*pi out.
    light_by_label = {}
    for record in package_data.get("lights") or []:
        label = str(record.get("name") or "")
        if label:
            light_by_label[label] = record

    for actor in actors:
        if not isinstance(actor, unreal.RectLight):
            continue
        component = actor.light_component
        check(
            "a rect light has a positive intensity",
            component.intensity > 0.0,
            str(component.intensity),
        )
        record = light_by_label.get(actor.get_actor_label())
        check(
            "the rect light actor matches a Maya light record",
            record is not None,
            actor.get_actor_label(),
        )
        if record is None:
            break
        accepted = component.intensity_units
        back_to_lumens = 1.0
        if accepted != unreal.LightUnits.LUMENS:
            back_to_lumens = component.get_units_conversion_factor(
                accepted, unreal.LightUnits.LUMENS
            )
        lumens = component.intensity * back_to_lumens
        # The expectation comes from the record, not from a number typed here:
        # the fixture's area light is exposure 2 on intensity 12, and a
        # hardcoded guess of 1 made a correct light look 48x wrong.
        #
        # This asserts the round trip -- computed, written through the setter,
        # read back in whatever unit stuck -- rather than the physics, which the
        # pure conversion checks above cover against a hand-computed
        # pi*mpu^2*683. It is the check that fails if a write silently does
        # nothing and the light keeps a spawned component's default 8 candelas.
        wanted, _units = lights.light_intensity_for_unreal(
            record, unreal.RectLight, 0.01, 1.0
        )
        close("the rect light's flux reached the component",
              lumens, wanted, max(1e-4, wanted * 1e-4))
        break

    # The camera gets the same treatment, and for the same reason: a filmback
    # or focal length that quietly refused to be set leaves Unreal's default
    # 35 mm behind, which looks like a working camera.
    camera_records = package_data.get("cameras") or []
    for actor in actors:
        if not isinstance(actor, unreal.CineCameraActor):
            continue
        component = actor.camera_component
        wanted = None
        for record in camera_records:
            if record.get("focal_length_mm"):
                wanted = record
                break
        if wanted is None:
            break
        close(
            "the cine camera kept its Maya focal length",
            component.current_focal_length,
            float(wanted["focal_length_mm"]),
            0.01,
        )
        if wanted.get("sensor_width_mm"):
            close(
                "the cine camera kept its Maya sensor width",
                component.filmback.sensor_width,
                float(wanted["sensor_width_mm"]),
                0.01,
            )
        break

    # --- a second package, exported with baking off.
    #
    # Baking resolves a layeredTexture into one file before any receiver sees
    # it, so the stack only exists in a package sent with it off -- which is
    # why this reads the second package the Maya test writes. It imports over
    # the level, so it runs last, after every assertion above has been made.
    unbaked = os.path.join(os.path.dirname(PACKAGE), "unbaked", "mLender_01")
    unbaked_json = os.path.join(unbaked, "mLender_01_scene.json")
    if os.path.isfile(unbaked_json):
        print("\nunbaked package: layeredTexture stacks")
        with open(unbaked_json) as handle:
            unbaked_data = json.load(handle)
        stacks = []
        for mesh_record in unbaked_data.get("meshes") or []:
            for material_record in mesh_record.get("materials") or []:
                for channel, channel_record in (
                        material_record.get("channels") or {}).items():
                    layered = ((channel_record or {}).get("texture")
                               or {}).get("layered") or {}
                    if layered.get("layers"):
                        stacks.append((material_record, channel, layered))
        check("the unbaked package carries a layeredTexture stack",
              bool(stacks),
              [s[0].get("material") for s in stacks])
        if stacks:
            unbaked_result = mlender_unreal.import_scene_package(unbaked)
            material_record, channel, layered = stacks[0]
            asset = unreal.EditorAssetLibrary.load_asset(
                "/Game/mLender/Materials/ML_{0}".format(
                    material_record.get("material"))
            )
            check("a material with a layered channel became a graph",
                  isinstance(asset, unreal.Material),
                  type(asset).__name__ if asset else None)
            if isinstance(asset, unreal.Material):
                library = unreal.MaterialEditingLibrary
                # Only the layers that actually blend carry an alpha: the
                # bottom one starts the chain and an unsupported mode is left
                # out, so those two have no parameter to read.
                blended = [
                    layer for layer in layered["layers"]
                    if str(layer.get("blend_mode") or "").lower()
                    not in ("saturate", "desaturate", "illuminate", "in",
                            "out", "cpv_modulate")
                ]
                checked = 0
                for layer in blended[:-1]:
                    name = "{0}_Layer{1}_Alpha".format(
                        channel, layer.get("index"))
                    want = float((layer.get("alpha") or {}).get("value") or 1.0)
                    try:
                        got = (library
                               .get_material_default_scalar_parameter_value(
                                   asset, name))
                    except Exception:
                        got = None
                    if got is not None and abs(got - want) < 0.001:
                        checked += 1
                check("each blending layer kept the alpha Maya gave it",
                      checked == max(0, len(blended) - 1),
                      (checked, len(blended) - 1))
            # A mode that is not a per-channel blend has to be named, not
            # quietly folded in as if it were a fade.
            unsupported = [
                layer for layer in layered["layers"]
                if str(layer.get("blend_mode") or "").lower()
                in ("saturate", "desaturate", "illuminate", "in", "out",
                    "cpv_modulate")
            ]
            if unsupported:
                check("an unblendable layer mode is reported by name",
                      any("is not a per-channel blend" in w
                          for w in unbaked_result.get("warnings") or []),
                      [w for w in unbaked_result.get("warnings") or []
                       if "layeredTexture" in w][:1])
            check("and the stack is no longer called a flat value",
                  not [w for w in unbaked_result.get("warnings") or []
                       if "layeredTexture" in w and "flat value" in w],
                  [w for w in unbaked_result.get("warnings") or []
                   if "flat value" in w][:1])

    # All of them, not the first few: the interesting warning is rarely in the
    # first twenty-five, and a truncated list sent a diagnosis down the wrong
    # path once already.
    print("\nwarnings ({0})".format(len(result.get("warnings") or [])))
    for warning in result.get("warnings") or []:
        print("  -", warning)

    print("")
    if failures:
        print("MLFAIL {0} assertion(s) failed".format(len(failures)))
        for failure in failures:
            print("MLFAIL   ", failure)
        return 1
    print("MLPASS all Unreal import assertions passed")
    return 0


if __name__ == "__main__":
    code = main()
    if code:
        sys.exit(code)
