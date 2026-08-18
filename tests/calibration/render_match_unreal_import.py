# -*- coding: utf-8 -*-
"""Render match, step 2 of 4: import the package and save the level.

The full sequence:

    1. mayapy tests/calibration/render_match_maya.py
       builds the scene, exports the package, renders arnold.exr

    2. UnrealEditor-Cmd <project> -run=pythonscript \\
           -script="tests/calibration/render_match_unreal_import.py" \\
           -unattended -nosplash -nullrhi
       imports the package and saves /Game/RenderMatch/MatchLevel

    3. copy render_match_unreal_capture.py to
       <project>/Content/Python/init_unreal.py, then open the editor on that
       level. It captures and quits by itself.

    4. blender --background --factory-startup \\
           --python tests/calibration/render_match_unreal_compare.py

Why the capture is a separate step in the real editor rather than part of this
one: a commandlet never executes render commands -- measured, a render target
cleared to (0.25, 0.5, 0.75) reads back (1, 0, 0) -- and -ExecutePythonScript
quits the editor before a frame is drawn. Details in
tests/docs/unreal_calibration.md.
"""
import glob
import json
import os
import sys
import tempfile

import unreal

TAG = "MLPHASEA"
# Three levels up: tests/<group>/<file>.py
REPO = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)
PKG_PY = os.path.join(REPO, "mlender_unreal", "Content", "Python")
if PKG_PY not in sys.path:
    sys.path.insert(0, PKG_PY)

OUT = os.path.join(tempfile.gettempdir(), "ml_render_match")
LEVEL = "/Game/RenderMatch/MatchLevel"


def say(key, value):
    print("{0} {1} = {2}".format(TAG, key, value))


expected = json.load(open(os.path.join(OUT, "expected.json")))
package = expected["package"]
say("package", package)

subsystem = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
subsystem.new_level(LEVEL)
say("new level", LEVEL)

import mlender_unreal  # noqa: E402

result = mlender_unreal.import_scene_package(package)
say("meshes", result["mesh_count"])
say("materials", result["material_count"])
say("lights", result["light_count"])
say("cameras", result["camera_count"])
say("active camera", result["active_camera"])
for warning in result["warnings"]:
    say("warn", warning)

# The camera transform is written out so phase B can place its capture without
# having to find the actor by name in a freshly loaded world.
camera_info = None
for actor in unreal.get_editor_subsystem(
    unreal.EditorActorSubsystem
).get_all_level_actors() or []:
    if isinstance(actor, unreal.CineCameraActor):
        location = actor.get_actor_location()
        rotation = actor.get_actor_rotation()
        component = actor.camera_component
        camera_info = {
            "label": actor.get_actor_label(),
            "location": [location.x, location.y, location.z],
            "rotation": [rotation.roll, rotation.pitch, rotation.yaw],
            "focal_length": component.current_focal_length,
            "sensor_width": component.filmback.sensor_width,
            "sensor_height": component.filmback.sensor_height,
        }
        break
say("camera info", json.dumps(camera_info))

with open(os.path.join(OUT, "unreal_camera.json"), "w") as handle:
    json.dump(camera_info, handle, indent=2)

subsystem.save_current_level()
unreal.EditorAssetLibrary.save_directory("/Game/mLender", False, True)
say("saved level", unreal.EditorAssetLibrary.does_asset_exist(LEVEL))
say("DONE", "")
