# -*- coding: utf-8 -*-
"""Render match, step 4 of 4: compare the Arnold reference against Unreal.

    blender --background --factory-startup ^
        --python tests/calibration/render_match_unreal_compare.py

Runs under Blender only because Blender is the EXR reader this repository
already has; nothing about Blender's renderer is involved. The Arnold patches
are sampled with exactly the expression render_match_blender.py uses, so the
Arnold column here is the same Arnold column that rig reports.

**The symmetry control is an assertion, not a note.** The scene is left/right
symmetric and Arnold reproduces that to five digits, so if Unreal's two ground
samples disagree the rig is measuring itself and no ratio from it means
anything. This exits non-zero and refuses to print a verdict in that case --
it was measured at 14% apart once, and reading the mean ratio anyway would have
turned a broken rig into a calibration constant.

Exit codes: 0 match, 1 mismatch, 2 the rig is not trustworthy.
"""
import json
import math
import os
import sys
import tempfile

import bpy

OUT = os.path.join(tempfile.gettempdir(), "ml_render_match")

SAMPLES = {
    "cube front face": (0.50, 0.46),
    "ground left of cube": (0.25, 0.60),
    "ground right of cube": (0.75, 0.60),
    "ground far behind": (0.50, 0.78),
}
PATCH = 5
SYMMETRY_PAIR = ("ground left of cube", "ground right of cube")

# How far the two symmetric samples may differ before the rig is not
# trustworthy. Arnold holds them to five digits; a real renderer with noise
# will not, so this is loose enough to allow sampling noise and tight enough
# to catch the 14% failure that prompted it.
SYMMETRY_TOLERANCE_PERCENT = 2.0
# How far the mean ratio may sit from a constant before "one scale factor"
# stops being an honest description of it.
RATIO_SPREAD_TOLERANCE_PERCENT = 10.0


def patch_average(pixels, width, height, u, v):
    # Blender's pixel array is bottom-up, so this expression places v as a
    # fraction from the top. The Unreal side samples top-down with v directly,
    # which is the same point in the picture.
    x0 = int(u * width)
    y0 = int((1.0 - v) * height)
    total = 0.0
    count = 0
    for y in range(max(0, y0 - PATCH), min(height, y0 + PATCH)):
        for x in range(max(0, x0 - PATCH), min(width, x0 + PATCH)):
            total += pixels[(y * width + x) * 4]
            count += 1
    return total / count if count else 0.0


def sample(path):
    image = bpy.data.images.load(path, check_existing=False)
    width, height = image.size
    pixels = list(image.pixels)
    values = {
        label: patch_average(pixels, width, height, u, v)
        for label, (u, v) in SAMPLES.items()
    }
    bpy.data.images.remove(image)
    return values


def percent_difference(a, b):
    mean = 0.5 * (a + b)
    return (100.0 * abs(a - b) / mean) if mean else float("nan")


def check_energy(expected, light):
    """The formula this repository claims, against what reached the component."""
    wanted = (683.0 * math.pi * (0.01 ** 2)
              * expected["light_intensity"]
              * (2.0 ** expected["light_exposure"]))
    got = light.get("intensity") or 0.0
    error = 100.0 * abs(got - wanted) / wanted if wanted else float("nan")
    print("\nlight energy")
    print("  Maya: intensity {0}, exposure {1}".format(
        expected["light_intensity"], expected["light_exposure"]))
    print("  683 * pi * mpu^2 * intensity * 2^exposure = {0:.6f} lm".format(
        wanted))
    print("  reached the component                     = {0:.6f} {1}".format(
        got, light.get("units")))
    print("  difference                                = {0:.6f}%".format(error))
    return error


def main():
    expected = json.load(open(os.path.join(OUT, "expected.json")))
    arnold_exr = expected["arnold_exr"]
    if not os.path.isfile(arnold_exr):
        raise SystemExit("No Arnold render; run render_match_maya.py first.")

    unreal_file = os.path.join(OUT, "unreal_samples.json")
    if not os.path.isfile(unreal_file):
        raise SystemExit("No Unreal capture; run the capture step first.")
    captured = json.load(open(unreal_file))
    if not captured.get("control_ok"):
        raise SystemExit(
            "The Unreal capture's control check failed, so its numbers mean "
            "nothing: {0}".format(captured.get("reason"))
        )

    arnold = sample(arnold_exr)
    lights = captured.get("lights") or [{}]
    energy_error = check_energy(expected, lights[0])

    passes = captured["passes"]
    applied = captured.get("show_flags_applied") or {}
    print("\nshow flags applied per pass: {0}".format(
        json.dumps(applied) if applied else "unknown"))

    # Did switching global illumination actually change the render? If the two
    # passes are identical the switch did nothing, and "direct only" is a claim
    # rather than a fact.
    names = sorted(passes)
    if len(names) >= 2:
        a = passes[names[0]]["summary"]
        b = passes[names[1]]["summary"]
        changed = max(
            percent_difference(a[label]["mean"], b[label]["mean"])
            for label in SAMPLES
        )
        print("largest difference between the two passes: {0:.4f}%".format(
            changed))
        if changed < 0.001:
            print(
                "  the global illumination switch did nothing, so neither pass\n"
                "  can be called direct-only"
            )

    verdict = 0
    for name in names:
        entry = passes[name]
        summary = entry["summary"]
        print("\n=== {0} ===".format(name))
        print("{0:24s} {1:>12s} {2:>12s} {3:>10s} {4:>10s}".format(
            "sample", "arnold", "unreal", "ratio", "frame +-"))
        print("-" * 74)
        ratios = []
        for label in SAMPLES:
            a = arnold[label]
            u = summary[label]["mean"]
            ratio = (u / a) if a > 1e-9 else float("nan")
            if a > 1e-6 and u > 1e-6:
                ratios.append(ratio)
            print("{0:24s} {1:12.6g} {2:12.6g} {3:10.4f} {4:9.3f}%".format(
                label, a, u, ratio, summary[label]["spread_percent"]))

        # The rig's own control, before any conclusion is drawn from the table.
        symmetry = entry.get("symmetry_error_percent")
        if symmetry is None:
            symmetry = percent_difference(
                summary[SYMMETRY_PAIR[0]]["mean"],
                summary[SYMMETRY_PAIR[1]]["mean"],
            )
        arnold_symmetry = percent_difference(
            arnold[SYMMETRY_PAIR[0]], arnold[SYMMETRY_PAIR[1]]
        )
        worst_frame_spread = max(
            summary[label]["spread_percent"] for label in SAMPLES
        )
        print("\n  symmetry control: arnold {0:.4f}%, unreal {1:.4f}% "
              "(tolerance {2:.1f}%)".format(
                  arnold_symmetry, symmetry, SYMMETRY_TOLERANCE_PERCENT))
        print("  worst frame-to-frame spread: {0:.3f}%".format(
            worst_frame_spread))

        if symmetry > SYMMETRY_TOLERANCE_PERCENT:
            print(
                "\n  RIG NOT TRUSTWORTHY: a symmetric scene did not render\n"
                "  symmetrically, so this ratio measures the rig, not the\n"
                "  transfer. No verdict from this pass."
            )
            verdict = max(verdict, 2)
            continue

        if not ratios:
            print("  nothing comparable")
            verdict = max(verdict, 2)
            continue

        low, high = min(ratios), max(ratios)
        mean = sum(ratios) / len(ratios)
        spread = 100.0 * (high - low) / mean
        print("  unreal / arnold: min {0:.4f}  max {1:.4f}  mean {2:.4f}".format(
            low, high, mean))
        print("  spread across samples: {0:.2f}%".format(spread))
        if spread <= RATIO_SPREAD_TOLERANCE_PERCENT:
            print(
                "\n  CONSISTENT: the lighting distribution transferred. The\n"
                "  remaining {0:.4g}x is one scale factor, which is Unreal's\n"
                "  scene-colour convention rather than a transfer error."
                .format(mean)
            )
        else:
            print(
                "\n  INCONSISTENT: the ratio varies by {0:.1f}% across the\n"
                "  frame, which points at geometry, falloff or the camera\n"
                "  rather than at one conversion constant.".format(spread)
            )
            verdict = max(verdict, 1)

    print("\nlight energy error: {0:.6f}%".format(energy_error))
    if energy_error > 0.01:
        print("  the lumen formula did not survive the trip to the component")
        verdict = max(verdict, 1)
    return verdict


if __name__ == "__main__":
    sys.exit(main())
