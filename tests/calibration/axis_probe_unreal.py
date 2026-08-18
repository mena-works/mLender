# -*- coding: utf-8 -*-
"""Read back where the axis probe's scene landed in Unreal, and check rotation.

Run tests/calibration/axis_probe_maya.py first; this reads the package it
writes.

    "C:\\Program Files\\Epic Games\\UE_5.8\\Engine\\Binaries\\Win64\\UnrealEditor-Cmd.exe" ^
        <project>.uproject -run=pythonscript ^
        -script="tests/calibration/axis_probe_unreal.py" ^
        -unattended -nosplash -nullrhi

Output goes to <project>/Saved/Logs/<project>.log, not to stdout. Grep MLAXIS.

This is a measurement rig, not a test: it produces the numbers recorded in
tests/docs/unreal_calibration.md rather than asserting known ones. The two
halves it measures are deliberately different:

* **Mesh transforms** come from Interchange. Nothing in this tool converts
  them, so what is measured here is the engine's own behaviour -- which is
  where the axis mapping and the unit scale were established.
* **Light and camera transforms** come from the JSON, so the conversion is
  ours. That half is checked non-circularly: the expected direction is
  computed from Maya's own world matrix in plain Python, and the actual one is
  read back off the spawned actor. Nothing compares the receiver to itself.
"""

import glob
import json
import math
import os
import sys
import tempfile

import unreal


TAG = "MLAXIS"
PROBE = os.path.join(tempfile.gettempdir(), "ml_axis_probe")
REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PACKAGE_PYTHON = os.path.join(REPO, "mlender_unreal", "Content", "Python")
if PACKAGE_PYTHON not in sys.path:
    sys.path.insert(0, PACKAGE_PYTHON)

CONTENT = "/Game/mLenderAxisProbe"


def say(key, value):
    print("{0} {1} = {2}".format(TAG, key, value))


def normalise(vector):
    length = math.sqrt(sum(component * component for component in vector))
    if length <= 1e-9:
        return tuple(vector)
    return tuple(component / length for component in vector)


def swap(vector):
    """The mapping under test, written out rather than imported.

    Deliberately not calling the receiver's own function: this rig is where the
    mapping is established, so it must not depend on the thing it measures.
    """
    return (vector[0], vector[2], vector[1])


def main():
    expected_file = os.path.join(PROBE, "expected.json")
    if not os.path.isfile(expected_file):
        say("FATAL", "run axis_probe_maya.py first; no {0}".format(
            expected_file
        ))
        return 1
    expected = json.load(open(expected_file))
    say("exporter build", expected.get("exporter_build"))
    say("maya linear unit", expected.get("linear_unit"))
    say("meters per maya unit", expected.get("meters_per_maya_unit"))

    # ------------------------------------------------ the FBX borne half
    manager = unreal.InterchangeManager.get_interchange_manager_scripted()
    source = manager.create_source_data(expected["fbx"])
    parameters = unreal.ImportAssetParameters()
    parameters.is_automated = True
    # import_level is a Level object, not a flag: the engine refuses a bool.
    if not manager.import_scene(CONTENT, source, parameters):
        say("FATAL", "Interchange refused the FBX")
        return 1

    subsystem = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
    by_label = {}
    for actor in subsystem.get_all_level_actors() or []:
        by_label[actor.get_actor_label()] = actor

    say("actors", ", ".join(sorted(by_label)))

    print("")
    say("--- mesh path, Interchange's own conversion ---", "")
    for name, maya_position in sorted(
        (expected.get("axis_positions_maya") or {}).items()
    ):
        actor = by_label.get(name)
        if actor is None:
            say("MISSING " + name, "no actor")
            continue
        location = actor.get_actor_location()
        want = swap(tuple(maya_position))
        say(
            name,
            "maya {0} -> unreal ({1:.4f}, {2:.4f}, {3:.4f}), "
            "y/z swap predicts ({4:.4f}, {5:.4f}, {6:.4f}) {7}".format(
                tuple(maya_position), location.x, location.y, location.z,
                want[0], want[1], want[2],
                "OK" if max(
                    abs(w - g) for w, g in zip(
                        want, (location.x, location.y, location.z)
                    )
                ) < 1e-3 else "MISMATCH",
            ),
        )

    rotated = by_label.get("probeRotated")
    if rotated is not None:
        location = rotated.get_actor_location()
        rotation = rotated.get_actor_rotation()
        scale = rotated.get_actor_scale3d()
        say(
            "probeRotated",
            "loc=({0:.4f}, {1:.4f}, {2:.4f}) "
            "rot=(roll {3:.4f}, pitch {4:.4f}, yaw {5:.4f}) "
            "scale=({6:.4f}, {7:.4f}, {8:.4f})".format(
                location.x, location.y, location.z,
                rotation.roll, rotation.pitch, rotation.yaw,
                scale.x, scale.y, scale.z,
            ),
        )
        say("probeRotated maya euler", expected.get("rotated_euler_maya"))
        say("probeRotated maya scale", expected.get("rotated_scale_maya"))

    # ------------------------------------------------ the JSON borne half
    print("")
    say("--- light path, this tool's conversion ---", "")
    from mlender_unreal import transforms

    json_path = glob.glob(os.path.join(expected["package"], "*_scene.json"))[0]
    data = json.load(open(json_path))
    record = data["lights"][0]
    transform = record["transform"]
    matrix = transform.get("world_matrix") or []
    if len(matrix) != 16:
        say("FATAL", "the light record carries no world matrix")
        return 1

    maya_x = normalise(matrix[0:3])
    maya_y = normalise(matrix[4:7])
    maya_z = normalise(matrix[8:11])
    # A Maya light aims down local -Z, an Unreal light down local +X.
    want = {
        "forward": swap(tuple(-c for c in maya_z)),
        "up": swap(maya_y),
        "right": swap(maya_x),
    }

    scale = transforms.position_scale(data, 1.0)
    say("position scale", scale)
    location = transforms.unreal_location(transform, scale)
    rotation = transforms.unreal_rotation(transform)
    actor = unreal.EditorLevelLibrary.spawn_actor_from_class(
        unreal.SpotLight, location, rotation
    )
    got = {
        "forward": actor.get_actor_forward_vector(),
        "up": actor.get_actor_up_vector(),
        "right": actor.get_actor_right_vector(),
    }
    for axis in ("forward", "up", "right"):
        vector = got[axis]
        error = max(
            abs(w - g) for w, g in zip(
                want[axis], (vector.x, vector.y, vector.z)
            )
        )
        say(
            axis,
            "want ({0:.6f}, {1:.6f}, {2:.6f}) got ({3:.6f}, {4:.6f}, {5:.6f}) "
            "error {6:.9f} {7}".format(
                want[axis][0], want[axis][1], want[axis][2],
                vector.x, vector.y, vector.z, error,
                "OK" if error < 1e-4 else "MISMATCH",
            ),
        )

    # Both halves in one number: the light sits at the same Maya point as
    # probeRotated, so the FBX path and the JSON path must agree. This is the
    # check that catches the two halves of one package landing in different
    # worlds.
    say(
        "light location",
        "({0:.4f}, {1:.4f}, {2:.4f}) from maya {3}".format(
            location.x, location.y, location.z, matrix[12:15]
        ),
    )
    say("DONE", "")
    return 0


if __name__ == "__main__":
    main()
