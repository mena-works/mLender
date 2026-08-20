# -*- coding: utf-8 -*-
"""Rebuild sampled Maya animation as Blender keyframes.

Only lights and cameras come through here. Mesh animation rides the FBX, which
already carries it, so touching meshes would fight the importer that just read
them.

Two things here are easy to get wrong and both ruin a turntable specifically:

* Decomposing each frame's matrix into Euler angles independently lets the
  angles jump by a full turn between frames, so a camera orbiting once reads
  as a sudden flip. Every frame is therefore made compatible with the one
  before it.
* Baked samples want linear interpolation. Blender's default Bezier eases
  between keys, which turns a constant orbit into one that slows at every
  frame boundary.
"""

import json
import os

import bpy

from .constants import ANIMATION_INTERPOLATION, DEFAULT_FPS
from .transforms import maya_matrix_to_blender
from .utils import scalar


def apply_scene_range(package_data):
    """Set the scene frame range and rate from the package."""
    animation = package_data.get("animation") or {}
    if not animation.get("enabled"):
        return False
    scene = bpy.context.scene
    start = int(round(scalar(animation.get("start"), 1.0)))
    end = int(round(scalar(animation.get("end"), start)))
    scene.frame_start = start
    scene.frame_end = max(start, end)
    scene.frame_current = start
    _apply_fps(scene, scalar(animation.get("fps"), DEFAULT_FPS))
    return True


def _apply_fps(scene, fps):
    """Blender states the rate as fps over fps_base, which is how it holds
    the NTSC rates exactly rather than as 29.97."""
    if fps <= 0.0:
        return
    nearest = int(round(fps))
    if nearest <= 0:
        return
    try:
        scene.render.fps = nearest
        scene.render.fps_base = 1.0 if abs(fps - nearest) < 1e-4 else nearest / fps
    except Exception:
        pass


def read_motion(package_folder, package_data, warnings):
    """The sampled motion beside the scene file, or nothing.

    Beside rather than inside: a shot's worth of matrices indented for
    reading is larger than the matrices themselves. Resolved by name inside
    the package folder, because a package is routinely opened from somewhere
    other than the machine that wrote it.
    """
    record = (package_data or {}).get("motion") or {}
    name = os.path.basename(str(record.get("file") or "").replace("\\", "/"))
    if not name:
        return {}
    path = os.path.join(package_folder or "", name)
    if not os.path.isfile(path):
        warnings.append(
            "{0} object(s) travel as sampled motion but {1} is not in the "
            "package, so they arrive still.".format(
                record.get("object_count") or 0, name)
        )
        return {}
    try:
        with open(path, "r") as handle:
            return json.load(handle)
    except Exception as exc:
        warnings.append(
            "The sampled motion could not be read ({0}), so the objects it "
            "carries arrive still.".format(exc)
        )
        return {}


def _still_frames(values, visible, tolerance=1.0e-4):
    """Frame indices whose matrix matches both neighbours, and that blink.

    Visibility is checked alongside because it is keyed from the same run: a
    frame dropped for holding still must not be the frame the object appears
    on.
    """
    count = len(values) // 12
    still = set()
    for index in range(1, count - 1):
        here = values[index * 12:(index + 1) * 12]
        before = values[(index - 1) * 12:index * 12]
        after = values[(index + 1) * 12:(index + 2) * 12]
        if any(abs(a - b) > tolerance for a, b in zip(here, before)):
            continue
        if any(abs(a - b) > tolerance for a, b in zip(after, here)):
            continue
        if index < len(visible) and (
                visible[index] != visible[index - 1]
                or (index + 1 < len(visible)
                    and visible[index + 1] != visible[index])):
            continue
        still.add(index)
    return still


def motion_samples(track, frames):
    """A sampled track spelled back out as the samples everything else takes.

    The file holds flat arrays because a dict per frame spends more on
    repeating the word "matrix" than on the motion -- 3384 movers over 520
    frames on the shot this was written for. Spelling one object's arrays
    back out is a few hundred numbers, and it means the keying path is the
    same one lights and cameras have always used.
    """
    values = (track or {}).get("matrix") or []
    visible = (track or {}).get("visible") or []
    still = _still_frames(values, visible)
    samples = []
    for index, frame in enumerate(frames or []):
        # A frame identical to both its neighbours sits on the line the two
        # of them already draw, and these keys interpolate linearly -- so
        # keying it changes nothing and costs three keyframe inserts. Debris
        # that comes to rest halfway through a shot is most of them.
        if index in still:
            continue
        row = values[index * 12:(index + 1) * 12]
        if len(row) < 12:
            break
        sample = {
            "frame": frame,
            # The fourth column the exporter dropped, put back: Maya never
            # varies it, so it was not worth a quarter of the file.
            "matrix": [
                row[0], row[1], row[2], 0.0,
                row[3], row[4], row[5], 0.0,
                row[6], row[7], row[8], 0.0,
                row[9], row[10], row[11], 1.0,
            ],
        }
        if index < len(visible):
            sample["visible"] = bool(visible[index])
        samples.append(sample)
    return samples


def animate_object(obj, record, position_scale, apply_sample=None):
    """Key an object's transform, and optionally its data, from the samples.

    ``apply_sample(sample)`` is called with the object already moved to that
    frame and should set and key whatever data values change; returning the
    transform work to one place keeps the light and camera paths identical.
    """
    samples = record.get("samples") or []
    if len(samples) < 2:
        return 0

    if obj.rotation_mode not in ("XYZ", "QUATERNION"):
        obj.rotation_mode = "XYZ"

    previous_euler = None
    keyed = 0
    for sample in samples:
        matrix = maya_matrix_to_blender(
            {"world_matrix": sample.get("matrix")}, position_scale
        )
        if matrix is None:
            continue
        frame = int(round(scalar(sample.get("frame"), 0.0)))

        translation, rotation, scale = matrix.decompose()
        euler = rotation.to_euler("XYZ")
        if previous_euler is not None:
            # Keep this frame in the same turn as the last one.
            euler.make_compatible(previous_euler)
        previous_euler = euler.copy()

        obj.location = translation
        obj.rotation_euler = euler
        obj.scale = scale
        obj.keyframe_insert("location", frame=frame)
        obj.keyframe_insert("rotation_euler", frame=frame)
        obj.keyframe_insert("scale", frame=frame)
        if apply_sample is not None:
            apply_sample(sample, frame)
        keyed += 1

    set_linear_interpolation(obj)
    set_linear_interpolation(getattr(obj, "data", None))
    return keyed


def animate_visibility(obj, record):
    """Key an object's visibility from the exported per frame samples.

    Both hide flags, because Maya's visibility means gone from the render as
    well as from the viewport; hiding only the viewport would still render it.

    The keys are CONSTANT, not linear. These are booleans stored as float
    curves, so easing between them would make an object half hidden for
    several frames and pop at whatever value rounds first.
    """
    samples = record.get("visibility_samples") or []
    if len(samples) < 2 or obj is None:
        return False

    keyed = 0
    for sample in samples:
        frame = sample.get("frame")
        if frame is None:
            continue
        hidden = sample.get("visible") is False
        for path in ("hide_viewport", "hide_render"):
            try:
                setattr(obj, path, hidden)
                obj.keyframe_insert(path, frame=frame)
            except Exception:
                continue
        keyed += 1

    if keyed < 2:
        return False
    set_constant_interpolation(obj, ("hide_viewport", "hide_render"))
    return True


def set_constant_interpolation(holder, paths):
    """Step, not ease, for the curves driving the given properties."""
    action = getattr(getattr(holder, "animation_data", None), "action", None)
    wanted = set(paths)
    for curve in action_fcurves(action):
        if curve.data_path not in wanted:
            continue
        for point in curve.keyframe_points:
            try:
                point.interpolation = "CONSTANT"
            except Exception:
                return


def key_data_value(data, path, value, frame):
    """Set one data property and key it, ignoring properties this build lacks."""
    if data is None or not hasattr(data, path):
        return False
    try:
        setattr(data, path, value)
        data.keyframe_insert(path, frame=frame)
        return True
    except Exception:
        return False


def action_fcurves(action):
    """Every F-Curve in an action, whichever API this Blender exposes.

    Slotted actions arrived in 4.4 and the flat ``Action.fcurves`` went away
    with 5.0. Measured: 4.1 has only the legacy list, 4.5 has both, and 5.2 has
    only layers. The new path is tried first so the legacy one stays a
    fallback rather than the thing that silently wins on 4.5.
    """
    if action is None:
        return []
    curves = []
    for layer in getattr(action, "layers", None) or []:
        for strip in getattr(layer, "strips", None) or []:
            for bag in getattr(strip, "channelbags", None) or []:
                curves.extend(bag.fcurves)
    if curves:
        return curves
    return list(getattr(action, "fcurves", None) or [])


def set_linear_interpolation(holder):
    """Baked samples are linear; Bezier would ease between every frame."""
    action = getattr(getattr(holder, "animation_data", None), "action", None)
    for curve in action_fcurves(action):
        for point in curve.keyframe_points:
            try:
                point.interpolation = ANIMATION_INTERPOLATION
            except Exception:
                return


def _socket_data_path(node, socket):
    """The RNA path a socket's value is keyed through.

    By index, not by name: Blender renamed several Principled sockets between
    4.1 and 5.2 while their indices stayed put, which is the same reason the
    correction nodes are addressed by index.
    """
    for index, candidate in enumerate(node.inputs):
        if candidate == socket:
            return 'nodes["{0}"].inputs[{1}].default_value'.format(
                node.name.replace('"', '\\"'), index
            )
    return ""


def animate_socket(material, node, socket, samples, warnings=None):
    """Key a node socket from a channel's per frame samples.

    Returns the number of keys set. Fewer than two samples is not animation
    and is left as a plain value, so a channel that happens to carry one
    sample does not end up with a pointless curve on it.

    The keys are LINEAR. Maya's own curve shape does not travel -- only the
    sampled values do -- so easing between samples that are already the
    evaluated result would ease twice.
    """
    if material is None or node is None or socket is None:
        return 0
    if len(samples or []) < 2:
        return 0
    path = _socket_data_path(node, socket)
    if not path:
        return 0

    tree = material.node_tree
    keyed = 0
    for sample in samples:
        frame = sample.get("frame")
        if frame is None:
            continue
        value = sample.get("value")
        try:
            if isinstance(value, (list, tuple)):
                current = socket.default_value
                if hasattr(current, "__len__"):
                    # A colour socket is four components and the sample is
                    # three; assuming the count is how a Subsurface Radius
                    # ends up half written.
                    width = len(current)
                    filled = list(value[:width])
                    while len(filled) < width:
                        filled.append(1.0)
                    socket.default_value = filled
                else:
                    socket.default_value = float(value[0])
            else:
                socket.default_value = float(value)
            tree.keyframe_insert(data_path=path, frame=frame)
            keyed += 1
        except Exception:
            continue

    _make_linear(tree, path)
    if keyed and warnings is not None:
        pass
    return keyed


def _make_linear(tree, path):
    """Baked samples are already the evaluated curve; Bezier would ease twice."""
    action = getattr(getattr(tree, "animation_data", None), "action", None)
    if action is None:
        return
    for curve in action_fcurves(action):
        if curve.data_path != path:
            continue
        for point in curve.keyframe_points:
            point.interpolation = "LINEAR"
