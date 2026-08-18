# -*- coding: utf-8 -*-
"""Read the aiColorCorrect renders and print the table.

The Maya half of this rig writes linear EXRs and a manifest; this reads the
middle pixel of each and prints what the node did, next to what the candidate
formulas predict. Blender is the reader because it opens EXR without a third
party library, which mayapy does not.

    "C:\\Program Files\\Blender Foundation\\Blender 5.2\\blender.exe" \\
        --background --factory-startup --python \\
        tests/calibration/color_correct_read.py
"""
import json
import os
import tempfile

import bpy


OUT = os.path.join(tempfile.gettempdir(), "ml_colorcorrect")


def middle_pixel(path):
    """The centre pixel, linear, as it came off the renderer."""
    image = bpy.data.images.load(path, check_existing=False)
    width, height = image.size
    if not width or not height:
        return None
    pixels = list(image.pixels)
    index = ((height // 2) * width + (width // 2)) * 4
    value = tuple(round(v, 5) for v in pixels[index:index + 3])
    bpy.data.images.remove(image)
    return value


def main():
    manifest_path = os.path.join(OUT, "manifest.json")
    if not os.path.isfile(manifest_path):
        print("MLCC no manifest at {0}".format(manifest_path))
        return
    with open(manifest_path) as handle:
        manifest = json.load(handle)

    source = tuple(manifest["input"])
    print("MLCC input = {0}".format(source))
    measured = {}
    for entry in manifest["renders"]:
        path = entry.get("path")
        if not path or not os.path.isfile(path):
            print("MLCC {0:<18} missing".format(entry["label"]))
            continue
        value = middle_pixel(path)
        measured[entry["label"]] = value
        print("MLCC {0:<18} {1:<34} {2}".format(
            entry["label"], json.dumps(entry["settings"]), value))

    identity = measured.get("identity")
    if identity is None:
        return
    # The control first: if identity is not the input, nothing below means
    # anything, and the rig is what is wrong.
    print("MLCC control: identity == input = {0}".format(
        all(abs(a - b) < 0.002 for a, b in zip(identity, source))))

    def predict(label, values):
        got = measured.get(label)
        if got is None:
            return
        print("MLCC   {0:<16} measured {1} predicted {2} match={3}".format(
            label, got, tuple(round(v, 5) for v in values),
            all(abs(a - b) < 0.003 for a, b in zip(got, values))))

    print("MLCC --- candidate formulas")
    predict("gamma2", [v ** (1.0 / 2.0) for v in source])
    predict("exposure1", [v * 2.0 for v in source])
    predict("multiply", [source[0] * 2.0, source[1] * 1.0, source[2] * 0.5])
    predict("add", [source[0] + 0.1, source[1], source[2] - 0.1])
    # Order: which one wins when both are set?
    predict("multiply2_gamma2", [(v * 2.0) ** 0.5 for v in source])
    print("MLCC   multiply2_gamma2 the other way (gamma first, then multiply):")
    print("MLCC     predicted {0}".format(
        tuple(round((v ** 0.5) * 2.0, 5) for v in source)))
    predict("multiply2_add1", [v * 2.0 + 0.1 for v in source])
    print("MLCC   multiply2_add1 the other way (add first, then multiply):")
    print("MLCC     predicted {0}".format(
        tuple(round((v + 0.1) * 2.0, 5) for v in source)))
    predict("add1_gamma2", [(v + 0.1) ** 0.5 for v in source])

    print("MLCC --- where the rest sit relative to gamma")
    def pair(label, first, second, first_name, second_name):
        got = measured.get(label)
        if got is None:
            return
        print("MLCC   {0}".format(label))
        print("MLCC     measured           {0}".format(got))
        print("MLCC     {0:<18} {1}".format(
            first_name, tuple(round(v, 5) for v in first)))
        print("MLCC     {0:<18} {1}".format(
            second_name, tuple(round(v, 5) for v in second)))

    pivot = 0.18
    pair("contrast2_gamma2",
         [((v - pivot) * 2.0 + pivot) ** 0.5 for v in source],
         [(v ** 0.5 - pivot) * 2.0 + pivot for v in source],
         "contrast then gamma", "gamma then contrast")
    pair("exposure1_gamma2",
         [(v * 2.0) ** 0.5 for v in source],
         [(v ** 0.5) * 2.0 for v in source],
         "exposure then gamma", "gamma then exposure")
    pair("invert_gamma2",
         [(1.0 - v) ** 0.5 for v in source],
         [1.0 - v ** 0.5 for v in source],
         "invert then gamma", "gamma then invert")
    pair("invert_multiply2",
         [(1.0 - v) * 2.0 for v in source],
         [1.0 - v * 2.0 for v in source],
         "invert then multiply", "multiply then invert")
    top = max(source)
    pair("contrast2_multiply2",
         [((v - pivot) * 2.0 + pivot) * 2.0 for v in source],
         [(v * 2.0 - pivot) * 2.0 + pivot for v in source],
         "contrast then mult", "mult then contrast")
    pair("contrast2_add1",
         [((v - pivot) * 2.0 + pivot) + 0.1 for v in source],
         [((v + 0.1) - pivot) * 2.0 + pivot for v in source],
         "contrast then add", "add then contrast")
    pair("saturation0_gamma2",
         [top ** 0.5] * 3,
         [max(v ** 0.5 for v in source)] * 3,
         "desat then gamma", "gamma then desat")

    print("MLCC   add1_gamma2 the other way (gamma first, then add):")
    print("MLCC     predicted {0}".format(
        tuple(round((v ** 0.5) + 0.1, 5) for v in source)))


if __name__ == "__main__":
    main()
