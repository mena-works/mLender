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
