# -*- coding: utf-8 -*-
"""Maya cameras rebuilt as Unreal cine cameras.

Maya and Unreal cameras do not face the same way -- Maya looks down local -Z
and Unreal down local +X -- so the conversion goes through transforms.py, whose
forward mapping was verified against the engine to 1e-8.

The lens mapping is otherwise close to exact: both state focal length in
millimetres and both state a sensor size, so the numbers travel rather than
being approximated.
"""

import unreal

from .constants import CAMERA_FOLDER, GENERATED_TAG
from .transforms import unreal_transform
from .utils import safe_asset_name, scalar


def _set_if_present(target, name, value):
    """Set a property by its setter where one exists, else directly.

    The same trap as the light components: a Blueprint-read-only property with
    a setter beside it refuses a plain attribute write, and a swallowed failure
    leaves the default in place looking like a working import.
    """
    setter = getattr(target, "set_" + name, None)
    if callable(setter):
        try:
            setter(value)
            return True
        except Exception:
            pass
    if not hasattr(target, name):
        return False
    try:
        setattr(target, name, value)
        return True
    except Exception:
        return False


def apply_filmback(component, record, warnings):
    """Sensor size in millimetres, which both applications state directly.

    The struct is read, modified and written back: Unreal exposes filmback as a
    value type, so mutating what the getter returned changes nothing. That is
    the same class of trap as an operator argument that is accepted and
    ignored, and it fails just as quietly.
    """
    width = scalar(record.get("sensor_width_mm"), 0.0)
    height = scalar(record.get("sensor_height_mm"), 0.0)
    if width <= 0.0 or height <= 0.0:
        return False
    filmback = component.filmback
    _set_if_present(filmback, "sensor_width", width)
    _set_if_present(filmback, "sensor_height", height)
    # Maya's film offset is a distance in inches, already converted to a ratio
    # of the aperture by the exporter. Unreal wants a distance in millimetres,
    # so the ratio is spent back against the sensor it belongs to.
    shift_x = scalar(record.get("shift_x"), 0.0)
    shift_y = scalar(record.get("shift_y"), 0.0)
    if shift_x:
        _set_if_present(filmback, "sensor_horizontal_offset", shift_x * width)
    if shift_y:
        _set_if_present(filmback, "sensor_vertical_offset", shift_y * height)
    component.filmback = filmback
    return True


def apply_focus(component, record, unreal_scale, warnings):
    """Depth of field, or manual focus switched off when Maya had none."""
    focus = component.focus_settings
    if not record.get("depth_of_field"):
        _set_if_present(
            focus, "focus_method", unreal.CameraFocusMethod.DISABLE
        )
        component.focus_settings = focus
        return False
    distance = scalar(record.get("focus_distance"), 0.0) * unreal_scale
    _set_if_present(focus, "focus_method", unreal.CameraFocusMethod.MANUAL)
    if distance > 0.0:
        _set_if_present(focus, "manual_focus_distance", distance)
    component.focus_settings = focus
    f_stop = scalar(record.get("f_stop"), 0.0)
    if f_stop > 0.0:
        _set_if_present(component, "current_aperture", f_stop)
    return True


def create_camera_actor(record, unreal_scale, warnings):
    location, rotation = unreal_transform(
        record.get("transform") or {}, unreal_scale
    )
    actor = unreal.EditorLevelLibrary.spawn_actor_from_class(
        unreal.CineCameraActor, location, rotation
    )
    if actor is None:
        raise RuntimeError("Unreal refused to spawn the camera actor.")

    label = safe_asset_name(record.get("name") or "Camera", "Camera")
    actor.set_actor_label(label)
    actor.set_folder_path(CAMERA_FOLDER)
    actor.tags = [GENERATED_TAG]

    component = actor.camera_component
    focal = scalar(record.get("focal_length_mm"), 0.0)
    if focal > 0.0:
        # A cine camera clamps focal length to its lens settings, so the lens
        # is widened first or a 12 mm Maya camera arrives at whatever the
        # default minimum happens to be.
        lens = component.lens_settings
        if hasattr(lens, "min_focal_length"):
            lens.min_focal_length = min(
                focal, scalar(getattr(lens, "min_focal_length", focal), focal)
            )
        if hasattr(lens, "max_focal_length"):
            lens.max_focal_length = max(
                focal, scalar(getattr(lens, "max_focal_length", focal), focal)
            )
        component.lens_settings = lens
        _set_if_present(component, "current_focal_length", focal)

    apply_filmback(component, record, warnings)
    apply_focus(component, record, unreal_scale, warnings)

    if record.get("orthographic"):
        warnings.append(
            'Camera "{0}" is orthographic in Maya; a cine camera is always '
            "perspective, so it arrived as one.".format(label)
        )
    if record.get("image_planes"):
        warnings.append(
            'Camera "{0}" carries an image plane, which this build does not '
            "rebuild in Unreal.".format(label)
        )
    return actor


def import_cameras(package_data, unreal_scale, warnings):
    records = list((package_data or {}).get("cameras") or [])
    created = 0
    active = ""
    renderable = []
    for record in records:
        try:
            actor = create_camera_actor(record, unreal_scale, warnings)
            created += 1
            if record.get("renderable"):
                renderable.append(actor.get_actor_label())
        except Exception as exc:
            warnings.append(
                'Camera "{0}" could not be created: {1}'.format(
                    record.get("full_name") or record.get("name") or "Camera",
                    exc,
                )
            )
    if renderable:
        active = renderable[0]
        if len(renderable) > 1:
            warnings.append(
                "Several cameras are marked renderable in Maya; "
                '"{0}" was taken as the main one.'.format(active)
            )
    return {"camera_count": created, "active": active}
