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
