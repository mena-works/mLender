# -*- coding: utf-8 -*-
"""Render match, step 3 of 4: capture the level and sample the patches.

**Copy this file to <project>/Content/Python/init_unreal.py** and open the
editor on /Game/RenderMatch/MatchLevel. It captures and quits by itself.
Remove it afterwards, or every later editor launch tries to capture again.

Run render_match_unreal_import.py first; render_match_unreal_compare.py after.

Runs as a project startup script rather than through -ExecutePythonScript,
which quits the editor before any frame is drawn. A commandlet is no good
either: measured, its render commands never execute and a target cleared to
(0.25, 0.5, 0.75) reads back (1, 0, 0). So the capture happens here, from a
Slate post-tick callback, after real frames.

Three things this rig does that a naive capture does not, each because the naive
version produced a confident wrong answer first:

* **A clear-colour control**, checked before anything is measured. See above.
* **One capture per tick, repeated, and the spread reported.** A single
  capture_scene() returns one temporally jittered frame. Averaging over
  separate frames converges it, and the spread across those frames is the
  evidence for whether temporal noise was the problem at all.
* **Show flags per capture, not console variables.** r.DynamicGlobal-
  IlluminationMethod does not reach a scene capture -- measured, the GI-off and
  GI-on passes came back bit-identical -- so global illumination is switched
  through the capture component's own show flags, and the two passes are
  compared to prove the switch did something.

**Vertical orientation matters and cost a run.** Blender's image.pixels is
ordered bottom-up, so the Blender rig's `(1 - v) * height` lands v as a
fraction from the top. An Unreal render target reads top-down, so copying that
expression mirrors the frame: the ground patches landed in empty sky and read
exactly 0.0. Here v is a fraction from the top.
"""
import json
import math
import os
import tempfile
import traceback

import unreal

TAG = "MLCAP"
OUT = os.path.join(tempfile.gettempdir(), "ml_render_match")
RESULT = os.path.join(OUT, "unreal_samples.json")
RESOLUTION = 160
PATCH = 5
GRID = 12
WARMUP_TICKS = 45
# Captures per pass, each on its own tick, then averaged.
CAPTURES_PER_PASS = 8
# Ticks to let pass after changing show flags before the first capture counts.
SETTLE_TICKS = 10

SAMPLES = {
    "cube front face": (0.50, 0.46),
    "ground left of cube": (0.25, 0.60),
    "ground right of cube": (0.75, 0.60),
    "ground far behind": (0.50, 0.78),
}

# The rig's own control: these two must agree, because the scene is symmetric.
SYMMETRY_PAIR = ("ground left of cube", "ground right of cube")

# Everything that would put screen-space or temporal history into an absolute
# measurement. Names are Unreal's show flag names.
NEUTRAL_FLAGS = (
    ("AntiAliasing", False),
    ("TemporalAA", False),
    ("MotionBlur", False),
    ("Bloom", False),
    ("EyeAdaptation", False),
    ("ToneCurve", False),
    ("Tonemapper", False),
    ("AmbientOcclusion", False),
    ("ScreenSpaceAO", False),
    ("ScreenSpaceReflections", False),
    ("Fog", False),
    ("AtmosphericFog", False),
    ("VolumetricFog", False),
    ("DepthOfField", False),
    ("Vignette", False),
    ("Grain", False),
)

# The two passes. Direct only is what the Arnold reference computes; the Lumen
# pass exists so the switch can be shown to work.
PASSES = (
    ("direct_only", (("GlobalIllumination", False),
                     ("ReflectionEnvironment", False),
                     ("DynamicShadows", True))),
    ("global_illumination", (("GlobalIllumination", True),
                             ("ReflectionEnvironment", True),
                             ("DynamicShadows", True))),
)

_state = {
    "ticks": 0, "handle": None, "stage": "warmup", "mark": 0,
    "pass_index": 0, "runs": [], "results": {}, "info": {},
    "target": None, "cc": None,
}


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


def patch_average(target, u, v):
    """Mean red channel over a patch. v is a fraction from the TOP."""
    reader = unreal.RenderingLibrary.read_render_target_raw_pixel
    x0 = int(u * RESOLUTION)
    y0 = int(v * RESOLUTION)
    total = 0.0
    count = 0
    for y in range(max(0, y0 - PATCH), min(RESOLUTION, y0 + PATCH)):
        for x in range(max(0, x0 - PATCH), min(RESOLUTION, x0 + PATCH)):
            total += reader(world(), target, x, y).r
            count += 1
    return total / count if count else 0.0


def sample_all(target):
    return {
        label: patch_average(target, u, v)
        for label, (u, v) in SAMPLES.items()
    }


def grid_of(target):
    reader = unreal.RenderingLibrary.read_render_target_raw_pixel
    rows = []
    for gy in range(GRID):
        row = []
        for gx in range(GRID):
            x = int((gx + 0.5) / GRID * RESOLUTION)
            y = int((gy + 0.5) / GRID * RESOLUTION)
            row.append(round(reader(world(), target, x, y).r, 6))
        rows.append(row)
    return rows


def apply_show_flags(cc, flags):
    """Set show flags on the capture component.

    Show flags rather than console variables, because the console variables do
    not reach a scene capture. Reported rather than assumed: if this engine
    does not expose the setting type, the caller is told so the result is not
    read as "GI was off".
    """
    setting_type = getattr(unreal, "EngineShowFlagsSetting", None)
    if setting_type is None:
        say("show flags", "EngineShowFlagsSetting is missing on this engine")
        return False
    settings = []
    for name, enabled in tuple(NEUTRAL_FLAGS) + tuple(flags):
        try:
            setting = setting_type()
            setting.set_editor_property("show_flag_name", name)
            setting.set_editor_property("enabled", enabled)
            settings.append(setting)
        except Exception as exc:
            say("show flag " + name, "ERROR {0}".format(exc))
    try:
        cc.set_editor_property("show_flag_settings", settings)
        return True
    except Exception as exc:
        say("show_flag_settings", "ERROR {0}".format(exc))
        return False


def setup():
    reader = unreal.RenderingLibrary.read_render_target_raw_pixel
    control = unreal.RenderingLibrary.create_render_target2d(
        world(), 32, 32, unreal.TextureRenderTargetFormat.RTF_RGBA32F
    )
    known = (0.25, 0.5, 0.75)
    unreal.RenderingLibrary.clear_render_target2d(
        world(), control, unreal.LinearColor(known[0], known[1], known[2], 1.0)
    )
    pixel = reader(world(), control, 16, 16)
    got = (pixel.r, pixel.g, pixel.b)
    error = max(abs(k - g) for k, g in zip(known, got))
    say("control readback", "({0:.6f}, {1:.6f}, {2:.6f}) error {3:.6f}".format(
        got[0], got[1], got[2], error))
    _state["info"]["control_readback"] = list(got)
    if error > 1e-3:
        finish({"control_ok": False, "control_readback": list(got),
                "reason": "readback does not round-trip a known colour"})
        return False

    camera = None
    for actor in actors():
        if isinstance(actor, unreal.CineCameraActor):
            camera = actor
            break
    if camera is None:
        finish({"control_ok": True, "reason": "no cine camera"})
        return False

    component = camera.camera_component
    focal = component.current_focal_length
    sensor_width = component.filmback.sensor_width
    fov = 2.0 * math.degrees(math.atan(sensor_width / (2.0 * focal)))

    lights = []
    for actor in actors():
        if isinstance(actor, unreal.Light):
            lc = actor.light_component
            lights.append({
                "name": actor.get_actor_label(),
                "class": actor.get_class().get_name(),
                "intensity": lc.intensity,
                "units": str(lc.intensity_units),
                "source_width": getattr(lc, "source_width", None),
                "source_height": getattr(lc, "source_height", None),
                "cast_shadows": getattr(lc, "cast_shadows", None),
            })
    say("lights", json.dumps(lights))

    target = unreal.RenderingLibrary.create_render_target2d(
        world(), RESOLUTION, RESOLUTION,
        unreal.TextureRenderTargetFormat.RTF_RGBA32F
    )
    capture_actor = unreal.EditorLevelLibrary.spawn_actor_from_class(
        unreal.SceneCapture2D, camera.get_actor_location(),
        camera.get_actor_rotation()
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
        ("override_bloom_intensity", True),
        ("bloom_intensity", 0.0),
        ("override_ambient_occlusion_intensity", True),
        ("ambient_occlusion_intensity", 0.0),
    ):
        try:
            settings.set_editor_property(key, value)
        except Exception as exc:
            say("pp " + key, "unavailable: {0}".format(exc))
    cc.post_process_settings = settings

    # Belt and braces: the cvars as well, in case a flag name is wrong.
    for text in ("r.AntiAliasingMethod 0", "r.MotionBlurQuality 0",
                 "r.DefaultFeature.AutoExposure 0"):
        try:
            unreal.SystemLibrary.execute_console_command(world(), text)
        except Exception:
            pass

    _state["target"] = target
    _state["cc"] = cc
    _state["info"].update({
        "resolution": RESOLUTION,
        "focal_length": focal,
        "sensor_width": sensor_width,
        "fov": fov,
        "lights": lights,
        "captures_per_pass": CAPTURES_PER_PASS,
    })
    return True


def summarise(runs):
    """Mean and spread per patch across the repeated captures."""
    summary = {}
    for label in SAMPLES:
        values = [run[label] for run in runs]
        mean = sum(values) / len(values)
        low, high = min(values), max(values)
        summary[label] = {
            "mean": mean,
            "min": low,
            "max": high,
            "spread_percent": (100.0 * (high - low) / mean) if mean else 0.0,
        }
    return summary


def symmetry_error(summary):
    left = summary[SYMMETRY_PAIR[0]]["mean"]
    right = summary[SYMMETRY_PAIR[1]]["mean"]
    mean = 0.5 * (left + right)
    return (100.0 * abs(left - right) / mean) if mean else float("nan")


def on_tick(_delta):
    if _state["stage"] == "done":
        return
    _state["ticks"] += 1
    ticks = _state["ticks"]
    try:
        if _state["stage"] == "warmup":
            if ticks < WARMUP_TICKS:
                return
            if not setup():
                return
            _state["stage"] = "flags"
            return

        if _state["stage"] == "flags":
            name, flags = PASSES[_state["pass_index"]]
            _state["info"].setdefault("show_flags_applied", {})[name] = (
                apply_show_flags(_state["cc"], flags)
            )
            say("pass", name)
            _state["runs"] = []
            _state["mark"] = ticks
            _state["stage"] = "settle"
            return

        if _state["stage"] == "settle":
            if ticks - _state["mark"] < SETTLE_TICKS:
                return
            _state["stage"] = "capture"
            return

        if _state["stage"] == "capture":
            # One capture per tick: repeated captures inside a single tick
            # share the same frame and would not converge anything.
            _state["cc"].capture_scene()
            _state["runs"].append(sample_all(_state["target"]))
            if len(_state["runs"]) < CAPTURES_PER_PASS:
                return
            name, _flags = PASSES[_state["pass_index"]]
            summary = summarise(_state["runs"])
            error = symmetry_error(summary)
            _state["results"][name] = {
                "summary": summary,
                "symmetry_error_percent": error,
                "grid": grid_of(_state["target"]),
                "runs": _state["runs"],
            }
            for label in sorted(summary):
                entry = summary[label]
                say("{0} {1}".format(name, label),
                    "mean {0:.8f} spread {1:.3f}%".format(
                        entry["mean"], entry["spread_percent"]))
            say("{0} symmetry error".format(name), "{0:.3f}%".format(error))

            _state["pass_index"] += 1
            if _state["pass_index"] < len(PASSES):
                _state["stage"] = "flags"
                return
            payload = {"control_ok": True, "passes": _state["results"]}
            payload.update(_state["info"])
            finish(payload)
    except Exception as exc:
        unreal.log_error(traceback.format_exc())
        finish({"control_ok": None, "reason": str(exc),
                "passes": _state["results"]})


_state["handle"] = unreal.register_slate_post_tick_callback(on_tick)
say("registered", "waiting for {0} ticks".format(WARMUP_TICKS))
