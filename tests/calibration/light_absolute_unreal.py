# -*- coding: utf-8 -*-
"""Verify Unreal's absolute brightness against closed-form physics.

**Copy this file to <project>/Content/Python/init_unreal.py** and open the
editor on any level. It imports, measures, prints a verdict and quits. Remove it
afterwards. Run light_absolute_maya.py first.

Why analytic rather than against Arnold: Arnold's pixel values are in its own
arbitrary scale, so a ratio against them can never be absolute -- that is what
left render_match_unreal_* unable to settle absolute brightness. A Lambertian
plane under a small light at a known height has a luminance that can be
computed:

    candelas   = lumens / (4*pi)            Unreal's own conversion, measured
    lux        = candelas * cos(theta) / d^2
    luminance  = lux * albedo / pi          nits, for a Lambertian surface

and the receiver's own light_intensity_for_unreal() supplies the lumens, so what
is under test is the production conversion.

Each variant moves exactly one term. A constant ratio across all of them means
every term is right; a ratio that moves names the term that is wrong. That is
the same method that established the pi anchor on the Blender side, and it is
the only kind of evidence that can call absolute brightness verified.

The prediction is averaged over the same pixels that are sampled rather than
taken at the centre, because the patch spans a few percent of distance and
cosine falloff and pretending otherwise would build that error into the answer.
"""
import json
import math
import os
import sys
import tempfile
import traceback

import unreal

TAG = "MLABS"


def repo_root():
    """Where the repository is, for a file that gets copied out of it.

    __file__ answers this while the file is still in the repository. Installing
    it as a project's Content/Python/init_unreal.py moves it, so MLENDER_ROOT
    is the override.

    Asked for rather than hardcoded: a path with somebody's user name in it does
    not belong in a public repository, and would be wrong on every machine but
    one anyway.
    """
    here = os.path.dirname(os.path.abspath(__file__))
    for candidate in (
        os.path.dirname(os.path.dirname(here)),   # tests/<group>/<file>.py
        os.environ.get("MLENDER_ROOT", ""),
    ):
        if candidate and os.path.isdir(
            os.path.join(candidate, "mlender_unreal")
        ):
            return candidate
    return ""


REPO = repo_root()
if REPO:
    PKG_PY = os.path.join(REPO, "mlender_unreal", "Content", "Python")
    if PKG_PY not in sys.path:
        sys.path.insert(0, PKG_PY)
else:
    unreal.log_error(
        "MLABS could not find the mLender checkout. Set MLENDER_ROOT to it."
    )

OUT = os.path.join(tempfile.gettempdir(), "ml_light_absolute")
RESULT = os.path.join(OUT, "unreal_absolute.json")

RESOLUTION = 400
# The emitting quad's width in Maya centimetres: light_absolute_maya.py uses
# scale 10 and an Arnold quad spans -1..1, so 20 cm. Only used to report how
# far the prediction's point-source assumption is being stretched.
LIGHT_SIZE_CM = 20.0
# Half-width of the sampled patch, in pixels. Large on purpose: the scene
# capture's indirect light is blotchy, and a 10 pixel patch on a blotchy field
# was what made a symmetric scene read 13% asymmetric in the earlier rig.
PATCH = 20
WARMUP_TICKS = 45
SETTLE_TICKS = 10

# A constant ratio is the real result; this is how far from constant it may be.
RATIO_SPREAD_TOLERANCE_PERCENT = 5.0
# And how far the constant itself may sit from 1.0 before Unreal's scene colour
# is something other than luminance in nits.
ABSOLUTE_TOLERANCE_PERCENT = 10.0
# Rotational symmetry is free with a nadir camera, so it is checked.
SYMMETRY_TOLERANCE_PERCENT = 5.0

_state = {"ticks": 0, "handle": None, "stage": "warmup", "mark": 0,
          "index": 0, "results": [], "info": {}, "target": None, "cc": None,
          "expected": None, "record": None, "ground": None,
          "busy": False, "pending": False}


def say(key, value):
    unreal.log("{0} {1} = {2}".format(TAG, key, value))


def finish(payload):
    _state["stage"] = "done"
    if not os.path.isdir(OUT):
        os.makedirs(OUT)
    with open(RESULT, "w") as handle:
        json.dump(payload, handle, indent=2, default=str)
    say("wrote", RESULT)
    if _state["handle"] is not None:
        try:
            unreal.unregister_slate_post_tick_callback(_state["handle"])
        except Exception:
            pass
    say("DONE", "")
    unreal.SystemLibrary.quit_editor()


def world():
    return unreal.EditorLevelLibrary.get_editor_world()


def actors():
    return unreal.get_editor_subsystem(
        unreal.EditorActorSubsystem
    ).get_all_level_actors() or []


# ------------------------------------------------------------------ physics
def predicted_nits(lumens, light_height_m, albedo, camera_height_m, fov_degrees):
    """Mean Lambertian luminance over the sampled patch, in nits.

    Averaged over the same pixels the capture samples. The light is treated as
    a point source, which at 20 cm across and 150 cm away is worth well under a
    percent; the variant that doubles the distance makes that approximation
    better, not worse, so it cannot masquerade as a distance error.
    """
    candelas = lumens / (4.0 * math.pi)
    half = math.tan(math.radians(fov_degrees) * 0.5) * camera_height_m
    total = 0.0
    count = 0
    centre = RESOLUTION * 0.5
    for y in range(int(centre - PATCH), int(centre + PATCH)):
        for x in range(int(centre - PATCH), int(centre + PATCH)):
            # Ground offset from the axis for this pixel, in metres.
            dx = ((x + 0.5) / RESOLUTION - 0.5) * 2.0 * half
            dy = ((y + 0.5) / RESOLUTION - 0.5) * 2.0 * half
            radius = math.sqrt(dx * dx + dy * dy)
            distance = math.sqrt(light_height_m ** 2 + radius ** 2)
            cos_theta = light_height_m / distance
            lux = candelas * cos_theta / (distance * distance)
            total += lux * albedo / math.pi
            count += 1
    return total / count if count else 0.0


# ------------------------------------------------------------------ capture
def patch_mean(target, u_centre, v_centre):
    reader = unreal.RenderingLibrary.read_render_target_raw_pixel
    x0 = int(u_centre * RESOLUTION)
    y0 = int(v_centre * RESOLUTION)
    total = 0.0
    count = 0
    for y in range(max(0, y0 - PATCH), min(RESOLUTION, y0 + PATCH)):
        for x in range(max(0, x0 - PATCH), min(RESOLUTION, x0 + PATCH)):
            total += reader(world(), target, x, y).r
            count += 1
    return total / count if count else 0.0


def quadrant_means(target):
    """Four off-axis patches. With a nadir camera these must agree."""
    offset = 0.18
    return {
        "left": patch_mean(target, 0.5 - offset, 0.5),
        "right": patch_mean(target, 0.5 + offset, 0.5),
        "top": patch_mean(target, 0.5, 0.5 - offset),
        "bottom": patch_mean(target, 0.5, 0.5 + offset),
    }


def build_light(variant):
    """Spawn the variant's light through the receiver's own production code."""
    from mlender_unreal import lights as ml_lights

    # Retire the previous variant's light.
    subsystem = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
    for actor in actors():
        if isinstance(actor, unreal.Light):
            subsystem.destroy_actor(actor)

    record = json.loads(json.dumps(_state["record"]))  # deep copy
    record["intensity"] = variant["intensity"]
    record["exposure"] = variant["exposure"]
    record["effective_intensity"] = (
        variant["intensity"] * (2.0 ** variant["exposure"])
    )
    matrix = record["transform"].get("world_matrix")
    if matrix and len(matrix) == 16:
        matrix[13] = variant["height"]      # Maya Y is the height
    record["transform"]["translation"] = [0.0, variant["height"], 0.0]

    warnings = []
    metre_scale = 0.01
    unreal_scale = 1.0
    actor = ml_lights.create_light_actor(
        record, unreal_scale, metre_scale, 1.0, warnings
    )
    for warning in warnings:
        say("light warning", warning)
    lumens, units = ml_lights.light_intensity_for_unreal(
        record, unreal.RectLight, metre_scale, 1.0
    )
    component = actor.light_component
    return {
        "requested_lumens": lumens,
        "requested_units": str(units),
        "component_intensity": component.intensity,
        "component_units": str(component.intensity_units),
        "location": [actor.get_actor_location().x,
                     actor.get_actor_location().y,
                     actor.get_actor_location().z],
        "forward": [actor.get_actor_forward_vector().x,
                    actor.get_actor_forward_vector().y,
                    actor.get_actor_forward_vector().z],
    }


def set_albedo(albedo):
    """Drive the ground's Material Instance BaseColor, as the importer built it.

    The return value is checked and the instance is explicitly updated. Both
    matter: the first version ignored the setter's result and never called
    update_material_instance, so the albedo variant rendered at the previous
    albedo and read exactly 2x the prediction -- a rig bug that looked like a
    transfer bug until the measured value turned out to be bit-identical to the
    variant before it.
    """
    if _state["ground"] is None:
        return None
    component = _state["ground"].static_mesh_component
    material = component.get_material(0) if component else None
    if material is None:
        say("albedo", "the ground carries no material")
        return None
    library = unreal.MaterialEditingLibrary
    colour = unreal.LinearColor(albedo, albedo, albedo, 1.0)
    applied = None
    try:
        applied = library.set_material_instance_vector_parameter_value(
            material, "BaseColor", colour
        )
    except Exception as exc:
        say("albedo", "ERROR {0}".format(exc))
        return None
    updater = getattr(library, "update_material_instance", None)
    if callable(updater):
        try:
            updater(material)
        except Exception as exc:
            say("albedo update", "ERROR {0}".format(exc))
    # Read it back rather than trusting the write.
    readback = None
    try:
        readback = library.get_material_instance_vector_parameter_value(
            material, "BaseColor"
        )
    except Exception:
        pass
    say("albedo", "{0} on {1} applied={2} readback={3}".format(
        albedo, material.get_name(), applied,
        "({0:.4f})".format(readback.r) if readback is not None else "?"))
    if applied is False:
        say("albedo", "the setter refused; the variant would measure the "
                      "previous albedo")
    return material.get_name()


def setup():
    from mlender_unreal import importer as ml_importer

    expected = json.load(open(os.path.join(OUT, "expected.json")))
    _state["expected"] = expected
    say("package", expected["package"])

    result = ml_importer.import_scene_package(expected["package"])
    say("import", "meshes {0} materials {1} lights {2} cameras {3}".format(
        result["mesh_count"], result["material_count"],
        result["light_count"], result["camera_count"]))
    for warning in result["warnings"]:
        say("import warning", warning)
    if not result["material_count"]:
        finish({"ok": False, "reason": "the import assigned no materials, so "
                                       "the ground albedo is not ours to set"})
        return False

    package_json = None
    for name in sorted(os.listdir(expected["package"])):
        if name.endswith("_scene.json"):
            package_json = os.path.join(expected["package"], name)
            break
    with open(package_json, "r") as handle:
        _state["record"] = json.load(handle)["lights"][0]

    camera = None
    for actor in actors():
        if isinstance(actor, unreal.CineCameraActor):
            camera = actor
        elif isinstance(actor, unreal.StaticMeshActor):
            _state["ground"] = actor
    if camera is None or _state["ground"] is None:
        finish({"ok": False, "reason": "the package brought no camera or no "
                                       "ground mesh"})
        return False

    component = camera.camera_component
    focal = component.current_focal_length
    sensor_width = component.filmback.sensor_width
    fov = 2.0 * math.degrees(math.atan(sensor_width / (2.0 * focal)))
    location = camera.get_actor_location()
    say("camera", "z {0:.3f} focal {1} fov {2:.4f}".format(
        location.z, focal, fov))

    target = unreal.RenderingLibrary.create_render_target2d(
        world(), RESOLUTION, RESOLUTION,
        unreal.TextureRenderTargetFormat.RTF_RGBA32F
    )
    # The control: a readback that cannot round-trip a known colour cannot
    # measure a render. Measured dead in a commandlet, alive in the editor.
    unreal.RenderingLibrary.clear_render_target2d(
        world(), target, unreal.LinearColor(0.25, 0.5, 0.75, 1.0)
    )
    pixel = unreal.RenderingLibrary.read_render_target_raw_pixel(
        world(), target, 8, 8
    )
    error = max(abs(a - b) for a, b in
                zip((0.25, 0.5, 0.75), (pixel.r, pixel.g, pixel.b)))
    say("control readback error", "{0:.8f}".format(error))
    if error > 1e-3:
        finish({"ok": False, "reason": "render target readback does not "
                                       "round-trip a known colour"})
        return False

    capture_actor = unreal.EditorLevelLibrary.spawn_actor_from_class(
        unreal.SceneCapture2D, location, camera.get_actor_rotation()
    )
    cc = capture_actor.capture_component2d
    cc.set_editor_property("texture_target", target)
    cc.set_editor_property(
        "capture_source", unreal.SceneCaptureSource.SCS_SCENE_COLOR_HDR
    )
    cc.set_editor_property("capture_every_frame", False)
    cc.set_editor_property("capture_on_movement", False)
    cc.set_editor_property("fov_angle", fov)
    settings = cc.post_process_settings
    for key, value in (
        ("override_auto_exposure_method", True),
        ("auto_exposure_method", unreal.AutoExposureMethod.AEM_MANUAL),
        ("override_auto_exposure_bias", True),
        ("auto_exposure_bias", 0.0),
        ("override_auto_exposure_apply_physical_camera_exposure", True),
        ("auto_exposure_apply_physical_camera_exposure", False),
    ):
        try:
            settings.set_editor_property(key, value)
        except Exception:
            pass
    cc.post_process_settings = settings

    _state["target"] = target
    _state["cc"] = cc
    _state["info"] = {
        "resolution": RESOLUTION, "patch": PATCH, "fov": fov,
        "camera_height_m": location.z / 100.0, "focal_length": focal,
        "exporter_build": expected.get("exporter_build"),
    }
    return True


def measure(variant):
    light = build_light(variant)
    set_albedo(variant["albedo"])
    _state["cc"].capture_scene()

    centre = patch_mean(_state["target"], 0.5, 0.5)
    quadrants = quadrant_means(_state["target"])
    values = list(quadrants.values())
    symmetry = (
        100.0 * (max(values) - min(values)) / (sum(values) / len(values))
        if sum(values) else float("nan")
    )
    wanted = predicted_nits(
        light["requested_lumens"],
        variant["height"] / 100.0,
        variant["albedo"],
        _state["info"]["camera_height_m"],
        _state["info"]["fov"],
    )
    ratio = (centre / wanted) if wanted else float("nan")
    # How badly the prediction's point-source assumption is being stretched.
    # The emitting quad is LIGHT_SIZE_CM across; the closer the light, the worse
    # a point is as a stand-in for it, and that error belongs to the prediction
    # rather than to the transfer.
    size_over_distance = LIGHT_SIZE_CM / max(variant["height"], 1e-6)
    say(variant["name"],
        "lumens {0:.4f} measured {1:.6f} predicted {2:.6f} ratio {3:.4f} "
        "symmetry {4:.2f}% size/distance {5:.3f}".format(
            light["requested_lumens"], centre, wanted, ratio, symmetry,
            size_over_distance))
    return {
        "variant": variant,
        "light": light,
        "measured_nits": centre,
        "predicted_nits": wanted,
        "ratio": ratio,
        "quadrants": quadrants,
        "symmetry_percent": symmetry,
        "size_over_distance": size_over_distance,
    }


def verdict():
    results = _state["results"]
    ratios = [r["ratio"] for r in results
              if r["ratio"] == r["ratio"] and r["ratio"] > 0]
    payload = {"ok": True, "results": results}
    payload.update(_state["info"])
    if not ratios:
        payload["ok"] = False
        payload["reason"] = "no usable ratios"
        finish(payload)
        return

    low, high = min(ratios), max(ratios)
    mean = sum(ratios) / len(ratios)
    spread = 100.0 * (high - low) / mean
    worst_symmetry = max(r["symmetry_percent"] for r in results)
    payload.update({
        "ratio_mean": mean, "ratio_min": low, "ratio_max": high,
        "ratio_spread_percent": spread,
        "worst_symmetry_percent": worst_symmetry,
    })

    say("ratio mean", "{0:.4f}".format(mean))
    say("ratio spread", "{0:.2f}%".format(spread))
    say("worst symmetry", "{0:.2f}%".format(worst_symmetry))

    trustworthy = worst_symmetry <= SYMMETRY_TOLERANCE_PERCENT
    consistent = spread <= RATIO_SPREAD_TOLERANCE_PERCENT
    absolute = abs(mean - 1.0) * 100.0 <= ABSOLUTE_TOLERANCE_PERCENT
    payload.update({"trustworthy": trustworthy, "consistent": consistent,
                    "absolute": absolute})

    # Where the point-source assumption holds, which is where the ratio is a
    # statement about the transfer rather than about the prediction.
    clean = [r for r in results if r["size_over_distance"] <= 0.15]
    if clean:
        clean_ratios = [r["ratio"] for r in clean]
        clean_mean = sum(clean_ratios) / len(clean_ratios)
        clean_spread = (
            100.0 * (max(clean_ratios) - min(clean_ratios)) / clean_mean
        )
        payload.update({"clean_ratio_mean": clean_mean,
                        "clean_ratio_spread_percent": clean_spread,
                        "clean_variants": [r["variant"]["name"] for r in clean]})
        say("ratio over the variants where a point source is a fair "
            "approximation", "{0:.4f}, spread {1:.3f}%".format(
                clean_mean, clean_spread))

    if not trustworthy:
        say("VERDICT", "RIG NOT TRUSTWORTHY: a rotationally symmetric scene "
                       "rendered {0:.2f}% asymmetric".format(worst_symmetry))
    elif consistent and absolute:
        say("VERDICT", "ABSOLUTE BRIGHTNESS VERIFIED: ratio {0:.4f} across "
                       "distance, intensity and exposure, spread "
                       "{1:.2f}%".format(mean, spread))
    elif consistent:
        say("VERDICT", "CONSISTENT BUT OFFSET: every term tracks, but Unreal "
                       "reads {0:.4f}x the physical luminance".format(mean))
    else:
        say("VERDICT", "INCONSISTENT: the ratio moves by {0:.2f}% across the "
                       "variants, so a term is wrong".format(spread))
    finish(payload)


def on_tick(_delta):
    if _state["stage"] == "done":
        return
    # Re-entrancy guard, and not a defensive flourish: importing a package pumps
    # Slate ticks, so this callback is called again from inside itself. Without
    # the guard the first run recursed twenty-one imports deep and died with
    # RecursionError, taking the editor with it.
    if _state["busy"]:
        return
    _state["busy"] = True
    try:
        _on_tick_body()
    finally:
        _state["busy"] = False


def _on_tick_body():
    _state["ticks"] += 1
    ticks = _state["ticks"]
    try:
        if _state["stage"] == "warmup":
            if ticks < WARMUP_TICKS:
                return
            if not setup():
                return
            _state["stage"] = "variant"
            _state["mark"] = ticks
            return
        if _state["stage"] == "variant":
            variants = _state["expected"]["variants"]
            if _state["index"] >= len(variants):
                verdict()
                return
            # A fresh light and material need a frame before they are in the
            # picture; measuring in the same tick reads the previous variant.
            if ticks - _state["mark"] < SETTLE_TICKS:
                return
            variant = variants[_state["index"]]
            if not _state.get("pending"):
                build_light(variant)
                set_albedo(variant["albedo"])
                _state["pending"] = True
                _state["mark"] = ticks
                return
            _state["results"].append(measure(variant))
            _state["pending"] = False
            _state["index"] += 1
            _state["mark"] = ticks
    except Exception as exc:
        unreal.log_error(traceback.format_exc())
        finish({"ok": False, "reason": str(exc), "results": _state["results"]})


_state["handle"] = unreal.register_slate_post_tick_callback(on_tick)
say("registered", "absolute brightness rig")
