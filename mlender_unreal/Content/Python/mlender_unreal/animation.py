# -*- coding: utf-8 -*-
"""Light, camera and visibility animation, as a Level Sequence.

The FBX brings mesh and skeletal animation with it. Everything else the
exporter samples -- a light that brightens, a camera that racks focus, a mesh
that blinks -- rode in the package and was thrown away here, with one warning
line to say so. Blender rebuilds all of it as keyframes; this is the Unreal
half, and a Level Sequence is the only place Unreal keeps that kind of key.

Every number below was measured in this engine rather than read off a doc,
because a frame space is the sort of thing that accepts a wrong value in
silence:

* **Sequencer's Python surface is entirely in ticks.** ``add_key``,
  ``set_range``, ``set_playback_start``/``end`` and the player's playback
  position all take tick numbers; the display rate only labels the ruler.
  Measured: a sequence keyed 100 -> 900 over 24 frames reads 500 at tick 12000
  and 100.40 at "frame 12", because 12 ticks is half a thousandth of the span.
* **The playback position has to be inside the range.** Landing exactly on the
  end finishes the sequence and restores the pre-animated values, so a probe
  that scrubs to the last frame reads the actor's spawn state and concludes
  nothing was keyed.
* **A component property is keyed on the component's own binding**, not the
  actor's: intensity and colour bind ``light_component``, focal length and
  aperture bind ``camera_component``.
* **Visibility is keyed True for visible.** The engine's own flag is
  ``hidden``, which is the other way round.

Maya's frame numbers are kept. Blender keys at the same numbers, and a package
that starts at frame 1 in one receiver and frame 0 in the other is a bug report
nobody can read.
"""
import json
import os

import unreal

from .constants import (
    ADOPTED_MOTION_TOLERANCE,
    ANIMATION_SEQUENCE_NAME,
    MESH_CONTENT_PATH,
    MOTION_ASSET_NAME,
    MOTION_BINDINGS_PER_SEQUENCE,
    MOTION_CONTENT_PATH,
    MOTION_FRAME_PROPERTY,
    MOTION_KEY_TOLERANCE,
    MOTION_PLAYER_NAME,
    GENERATED_TAG,
    SEQUENCE_CONTENT_PATH,
)
from .lights import (
    light_colour,
    light_intensity_for_unreal,
    resolve_unreal_light_class,
)
from .constants import (
    MASTER_SCALAR_PARAMETERS,
    MASTER_VECTOR_PARAMETERS,
)
from .materials import channel_value
from .meshes import mesh_component
from .transforms import unreal_object_transform, unreal_transform
from .utils import safe_asset_name, scalar, sequence_label


def _linear():
    """LINEAR, or nothing if this build spells the enum differently."""
    try:
        return unreal.MovieSceneKeyInterpolation.LINEAR
    except Exception:
        return None


def _add_key(channel, tick, value):
    """One key, linear where the channel allows it."""
    interpolation = _linear()
    if interpolation is not None:
        try:
            channel.add_key(
                unreal.FrameNumber(int(tick)), value,
                interpolation=interpolation,
            )
            return True
        except Exception:
            pass
    # A bool channel takes no interpolation, and says so by raising.
    try:
        channel.add_key(unreal.FrameNumber(int(tick)), value)
        return True
    except Exception:
        return False


def create_sequence(package_data, warnings):
    """An empty Level Sequence covering the package's frame range.

    Returns ``(sequence, ticks_per_frame, first_tick, last_tick)``, or Nones
    when the package carries no animation.
    """
    animation = (package_data or {}).get("animation") or {}
    if not animation.get("enabled"):
        return None, 0.0, 0, 0

    fps = scalar(animation.get("fps"), 24.0) or 24.0
    start = scalar(animation.get("start"), 1.0)
    end = scalar(animation.get("end"), start)

    label = sequence_label(package_data)
    asset_name = "{0}_{1}".format(ANIMATION_SEQUENCE_NAME, label)
    tools = unreal.AssetToolsHelpers.get_asset_tools()
    asset_path = "{0}/{1}".format(SEQUENCE_CONTENT_PATH, asset_name)
    # The previous send's sequence has to go first. create_asset will not
    # write over an asset that is already loaded, and it does not raise when
    # it refuses -- it returns None. So the second send into an open editor
    # built no sequence at all, reported no animation, and said nothing: the
    # level had every actor and a ruler that did nothing, which is exactly
    # how it was first reported.
    try:
        if unreal.EditorAssetLibrary.does_asset_exist(asset_path):
            unreal.EditorAssetLibrary.delete_asset(asset_path)
    except Exception:
        pass
    try:
        sequence = tools.create_asset(
            asset_name, SEQUENCE_CONTENT_PATH, unreal.LevelSequence,
            unreal.LevelSequenceFactoryNew(),
        )
    except Exception as exc:
        warnings.append(
            "The package carries animation but the Level Sequence could not "
            "be created: {0}".format(exc)
        )
        return None, 0.0, 0, 0
    if sequence is None:
        # Something still holds the old one. A sequence under a different
        # name beats no sequence, so long as the user is told which one to
        # open.
        try:
            unique_path, _unique_name = tools.create_unique_asset_name(
                asset_path, ""
            )
            asset_name = unique_path.rsplit("/", 1)[-1]
            sequence = tools.create_asset(
                asset_name, SEQUENCE_CONTENT_PATH, unreal.LevelSequence,
                unreal.LevelSequenceFactoryNew(),
            )
        except Exception:
            sequence = None
        if sequence is None:
            warnings.append(
                "The package carries animation but Unreal returned no Level "
                "Sequence asset, so nothing on the timeline was rebuilt."
            )
            return None, 0.0, 0, 0
        warnings.append(
            'The previous sequence is still in use, so this one was built as '
            '"{0}". Close the old one and send again to reuse the '
            "name.".format(asset_name)
        )

    try:
        sequence.set_display_rate(unreal.FrameRate(int(round(fps)), 1))
    except Exception:
        pass
    # One tick per frame. The engine's default is 24000 ticks to a second
    # against a display rate of 24, and at that ratio its own halves disagree:
    # evaluation treats a section range as ticks, while the editor's ruler and
    # get_end_frame_seconds treat the same numbers as frames. Measured with
    # the resolutions equal: a section of 0..25 reads back as 0..25 frames and
    # 0..1.042 seconds, and keys at 0 and 24 evaluate to 0, 50 and 100 at
    # frames 0, 12 and 24. Everything agrees, and a per-frame sample has no
    # use for sub-frame ticks.
    try:
        sequence.set_tick_resolution(unreal.FrameRate(int(round(fps)), 1))
    except Exception:
        pass
    resolution = sequence.get_tick_resolution()
    ticks_per_frame = float(resolution.numerator) / (
        float(resolution.denominator or 1) * float(fps)
    )
    first = int(round(start * ticks_per_frame))
    last = int(round(end * ticks_per_frame))
    try:
        # The playback range is the one part of this API that is **not** in
        # ticks. Measured: set_playback_end(33000) reads back as 1375 seconds,
        # while set_playback_end(33) reads back as 1.375 -- which is 33 frames
        # at 24fps. Handing it ticks made the ruler a thousand times too long,
        # so a 0-33 shot opened as 0-33000 with every key inside the first
        # thirty-three frames, and scrubbing anywhere showed the last pose.
        # That reads as "nothing is animated", which is how it was reported.
        sequence.set_playback_start(int(round(start)))
        sequence.set_playback_end(int(round(end)))
    except Exception:
        pass

    # The ruler as well, in seconds, with a little air on each side. Sequencer
    # remembers a view range per asset and fits it to whatever it finds; left
    # to itself it has opened this shot on a span of tens of thousands of
    # frames, which is the first thing a user sees and reads as the range
    # having arrived wrong.
    try:
        margin = max(1.0, (end - start) * 0.05) / fps
        unreal.MovieSceneSequenceExtensions.set_work_range_start(
            sequence, start / fps)
        unreal.MovieSceneSequenceExtensions.set_work_range_end(
            sequence, end / fps)
        unreal.MovieSceneSequenceExtensions.set_view_range_start(
            sequence, start / fps - margin)
        unreal.MovieSceneSequenceExtensions.set_view_range_end(
            sequence, end / fps + margin)
    except Exception:
        pass
    return sequence, ticks_per_frame, first, last


def _section(binding, track_class, first, last):
    """A track's single section, spanning the whole range.

    The numbers are ticks, which are frames here: create_sequence sets the
    sequence's tick resolution equal to its display rate. Measured at the
    engine's default resolution of 24000 against a display rate of 24, the two
    disagreed -- evaluation read a section range as ticks while the editor and
    get_end_frame_seconds read the same numbers as frames, so a section
    covering the shot drew a ruler a thousand times too long. Making one tick
    one frame leaves nothing to disagree about; sub-frame precision is not
    something a per-frame sample has to offer anyway.
    """
    track = binding.add_track(track_class)
    section = track.add_section()
    section.set_range(first, last)
    return track, section


def _tick_of(sample, ticks_per_frame):
    return int(round(scalar(sample.get("frame"), 0.0) * ticks_per_frame))


def _key_transform(section, samples, unreal_scale, ticks_per_frame):
    """Nine channels from a run of sampled Maya world matrices.

    The channel order was read back rather than assumed: Location X/Y/Z,
    Rotation X/Y/Z, Scale X/Y/Z.
    """
    channels = section.get_all_channels()
    if len(channels) < 6:
        return 0
    keys = 0
    for sample in samples:
        matrix = sample.get("matrix")
        if not matrix:
            continue
        tick = _tick_of(sample, ticks_per_frame)
        location, rotation = unreal_transform(
            {"world_matrix": matrix}, unreal_scale
        )
        values = (
            location.x, location.y, location.z,
            rotation.roll, rotation.pitch, rotation.yaw,
        )
        for index, value in enumerate(values):
            if _add_key(channels[index], tick, float(value)):
                keys += 1
    return keys


def _key_float(binding, property_name, samples, ticks_per_frame, value_of,
               first, last):
    """One float property track, keyed from a sample run."""
    pairs = []
    for sample in samples:
        try:
            value = value_of(sample)
        except Exception:
            value = None
        if value is None:
            continue
        pairs.append((_tick_of(sample, ticks_per_frame), float(value)))
    if not pairs:
        return 0
    track, section = _section(
        binding, unreal.MovieSceneFloatTrack, first, last
    )
    track.set_property_name_and_path(property_name, property_name)
    channels = section.get_all_channels()
    if not channels:
        return 0
    keys = 0
    for tick, value in pairs:
        if _add_key(channels[0], tick, value):
            keys += 1
    return keys


def _key_colour(binding, property_name, samples, ticks_per_frame, colour_of,
                first, last):
    """A colour property track: four channels, R G B A, in that order."""
    pairs = []
    for sample in samples:
        try:
            rgb = colour_of(sample)
        except Exception:
            rgb = None
        if rgb is None:
            continue
        pairs.append((_tick_of(sample, ticks_per_frame), rgb))
    if not pairs:
        return 0
    track, section = _section(
        binding, unreal.MovieSceneColorTrack, first, last
    )
    track.set_property_name_and_path(property_name, property_name)
    channels = section.get_all_channels()
    if len(channels) < 3:
        return 0
    keys = 0
    for tick, rgb in pairs:
        values = list(rgb) + [1.0, 1.0, 1.0, 1.0]
        for index in range(min(4, len(channels))):
            if _add_key(channels[index], tick, float(values[index])):
                keys += 1
    return keys


def actors_by_label():
    """Every level actor, keyed by label, for matching Maya names."""
    found = {}
    try:
        actors = unreal.get_editor_subsystem(
            unreal.EditorActorSubsystem
        ).get_all_level_actors() or []
    except Exception:
        return found
    for actor in actors:
        try:
            found.setdefault(actor.get_actor_label(), actor)
        except Exception:
            continue
    return found


def _component(actor, name):
    try:
        return getattr(actor, name)
    except Exception:
        return None


def animate_lights(sequence, package_data, actors, unreal_scale, metre_scale,
                   power_scale, ticks_per_frame, first, last, warnings):
    """Transform, intensity and colour for every light that was sampled."""
    tracks = 0
    keys = 0
    for record in (package_data or {}).get("lights") or []:
        samples = record.get("samples") or []
        if len(samples) < 2:
            continue
        label = safe_asset_name(record.get("name") or "Light", "Light")
        actor = actors.get(label)
        if actor is None:
            warnings.append(
                'Light "{0}" is animated but no actor of that name is in the '
                "level, so its animation was not keyed.".format(label)
            )
            continue

        binding = sequence.add_possessable(actor)
        _track, section = _section(
            binding, unreal.MovieScene3DTransformTrack, first, last
        )
        moved = _key_transform(
            section, samples, unreal_scale, ticks_per_frame
        )
        if moved:
            tracks += 1
            keys += moved

        component = _component(actor, "light_component")
        if component is None:
            continue
        component_binding = sequence.add_possessable(component)

        light_class = resolve_unreal_light_class(
            str(record.get("light_kind") or "AREA").upper(),
            str(record.get("area_shape") or "RECTANGLE").upper(),
        )

        def intensity_of(sample, record=record, light_class=light_class):
            # Run through the same measured conversion the static value uses.
            # Keying raw Maya intensity would animate a different quantity
            # than the one frame one is holding.
            #
            # The stale key has to go, not just be written over: the record
            # carries the *static* effective_intensity and the conversion
            # prefers it, so a first version keyed the frame-one value
            # twenty-five times. It agreed with its own expected value and
            # still animated nothing -- what gave it away was the number
            # sitting still while the Maya samples ran 1 to 9.
            merged = dict(record)
            merged.pop("effective_intensity", None)
            merged["intensity"] = sample.get("intensity", record.get(
                "intensity"))
            merged["exposure"] = sample.get("exposure", record.get("exposure"))
            if sample.get("effective_intensity") is not None:
                merged["effective_intensity"] = sample["effective_intensity"]
            parameters = dict(record.get("parameters") or {})
            parameters.pop("intensity", None)
            parameters.pop("exposure", None)
            merged["parameters"] = parameters
            value, _units = light_intensity_for_unreal(
                merged, light_class, metre_scale, power_scale
            )
            return value

        keyed = _key_float(
            component_binding, "Intensity", samples, ticks_per_frame,
            intensity_of, first, last,
        )
        if keyed:
            tracks += 1
            keys += keyed

        def colour_of(sample, record=record):
            rgb = sample.get("color")
            if not rgb:
                return None
            merged = dict(record)
            merged["color"] = rgb
            # parameters wins over the top level record in light_colour, so
            # writing only record["color"] leaves the static colour in place.
            parameters = dict(record.get("parameters") or {})
            parameters["color"] = rgb
            merged["parameters"] = parameters
            # light_colour hands back a LinearColor, which is not iterable;
            # measured the hard way, as a caught "object is not iterable" that
            # dropped every colour track while the rest of the keys landed.
            value = light_colour(merged)
            return (value.r, value.g, value.b, value.a)

        keyed = _key_colour(
            component_binding, "LightColor", samples, ticks_per_frame,
            colour_of, first, last,
        )
        if keyed:
            tracks += 1
            keys += keyed
    return tracks, keys


def animate_cameras(sequence, package_data, actors, unreal_scale,
                    ticks_per_frame, first, last, warnings):
    """Transform, focal length and aperture for every camera that moved."""
    tracks = 0
    keys = 0
    for record in (package_data or {}).get("cameras") or []:
        samples = record.get("samples") or []
        if len(samples) < 2:
            continue
        label = safe_asset_name(record.get("name") or "Camera", "Camera")
        actor = actors.get(label)
        if actor is None:
            warnings.append(
                'Camera "{0}" is animated but no actor of that name is in the '
                "level, so its animation was not keyed.".format(label)
            )
            continue

        binding = sequence.add_possessable(actor)
        _track, section = _section(
            binding, unreal.MovieScene3DTransformTrack, first, last
        )
        moved = _key_transform(
            section, samples, unreal_scale, ticks_per_frame
        )
        if moved:
            tracks += 1
            keys += moved

        component = _component(actor, "camera_component")
        if component is None:
            continue
        component_binding = sequence.add_possessable(component)
        for property_name, key in (("CurrentFocalLength", "focal_length_mm"),
                                   ("CurrentAperture", "f_stop")):
            keyed = _key_float(
                component_binding, property_name, samples, ticks_per_frame,
                lambda sample, key=key: sample.get(key),
                first, last,
            )
            if keyed:
                tracks += 1
                keys += keyed
    return tracks, keys


def animate_visibility(sequence, package_data, actors, ticks_per_frame,
                       first, last, warnings):
    """A visibility track per mesh whose Maya visibility was keyed."""
    tracks = 0
    keys = 0
    for record in (package_data or {}).get("meshes") or []:
        samples = record.get("visibility_samples") or []
        if len(samples) < 2:
            continue
        # A run that never changes is not animation; a track per mesh in a
        # scene where nothing blinks is noise in the Sequencer outliner.
        states = set(bool(sample.get("visible")) for sample in samples)
        if len(states) < 2:
            continue
        # A mesh record is keyed on "mesh", not "name" -- a first version
        # asked for "name", got nothing from every record, and labelled the
        # lot "Mesh", so no actor ever matched and no blink was keyed.
        label = safe_asset_name(
            record.get("mesh") or record.get("mesh_full_name") or "Mesh",
            "Mesh",
        )
        actor = actors.get(label)
        if actor is None:
            continue
        binding = sequence.add_possessable(actor)
        _track, section = _section(
            binding, unreal.MovieSceneVisibilityTrack, first, last
        )
        channels = section.get_all_channels()
        if not channels:
            continue
        counted = 0
        for sample in samples:
            # True is visible here; the engine's own flag is hidden, and
            # passing that value straight through inverts every blink.
            if _add_key(channels[0], _tick_of(sample, ticks_per_frame),
                        bool(sample.get("visible"))):
                counted += 1
        if counted:
            tracks += 1
            keys += counted
    return tracks, keys


def _material_slot(component, material_name):
    """The slot index holding a rebuilt material, or None.

    Slots are matched by name rather than by the record order, for the same
    reason the material assignment does it: the FBX decides the order and an
    index is only right until something reorders.
    """
    if component is None or not material_name:
        return None
    wanted = str(material_name)
    try:
        count = component.get_num_materials()
    except Exception:
        return None
    for index in range(count):
        try:
            material = component.get_material(index)
        except Exception:
            continue
        if material is None:
            continue
        name = material.get_name()
        if name == wanted or name.endswith(wanted) or wanted in name:
            return index
    return None


def animate_materials(sequence, package_data, actors, ticks_per_frame, first,
                      last, warnings):
    """Keyed material parameters, as component material tracks.

    The time argument here is not the one every other channel takes. Measured
    on the same sequence: a transform channel handed 1000 stores 1000, but
    add_scalar_parameter_key handed 1000 stores 1 -- it divides by
    ticks-per-frame. Keys therefore go in multiplied back up, and the first
    version, which passed plain ticks, put twenty five keys inside the first
    twenty five ticks of the sequence. It looked like nothing was animated at
    all, because every scrub landed past the last key and read its value.
    """
    tracks = 0
    keys = 0
    for mesh_record in (package_data or {}).get("meshes") or []:
        label = safe_asset_name(
            mesh_record.get("mesh") or mesh_record.get("mesh_full_name")
            or "Mesh", "Mesh",
        )
        actor = actors.get(label)
        if actor is None:
            continue
        component = mesh_component(actor)
        if component is None:
            continue
        binding = None
        for material_record in mesh_record.get("materials") or []:
            channels = material_record.get("channels") or {}
            keyed = [
                (channel, record) for channel, record in sorted(channels.items())
                if (record or {}).get("samples")
                and (channel in MASTER_SCALAR_PARAMETERS
                     or channel in MASTER_VECTOR_PARAMETERS)
            ]
            if not keyed:
                continue
            slot = _material_slot(
                component,
                "{0}{1}".format("ML_", material_record.get("material") or ""),
            )
            if slot is None:
                warnings.append(
                    'Material "{0}" is keyed in Maya but no slot on "{1}" '
                    "holds it, so it was not animated.".format(
                        material_record.get("material"), label
                    )
                )
                continue
            if binding is None:
                binding = sequence.add_possessable(component)
            track = binding.add_track(unreal.MovieSceneComponentMaterialTrack)
            track.set_material_index(slot)
            section = track.add_section()
            section.set_range(first, last)
            interpolation = _linear()
            built = 0
            for channel, record in keyed:
                info = unreal.MaterialParameterInfo()
                colour = channel in MASTER_VECTOR_PARAMETERS
                info.set_editor_property(
                    "name",
                    MASTER_VECTOR_PARAMETERS[channel] if colour
                    else MASTER_SCALAR_PARAMETERS[channel],
                )
                for sample in record["samples"]:
                    tick = _tick_of(sample, ticks_per_frame)
                    stamp = unreal.FrameNumber(
                        int(round(tick * ticks_per_frame))
                    )
                    value = channel_value(channel, sample)
                    try:
                        if colour:
                            section.add_color_parameter_key(
                                info, stamp,
                                unreal.LinearColor(
                                    value[0], value[1], value[2], 1.0
                                ),
                                "", "", [], interpolation,
                            )
                        else:
                            section.add_scalar_parameter_key(
                                info, stamp, float(value), "", "",
                                interpolation,
                            )
                        built += 1
                    except Exception as exc:
                        warnings.append(
                            'Material "{0}" channel "{1}" could not be keyed: '
                            "{2}".format(
                                material_record.get("material"), channel, exc
                            )
                        )
                        break
            if built:
                tracks += 1
                keys += built
    return tracks, keys


def assign_skeletal_animation(warnings):
    """Hand each skeletal actor the sequence the FBX brought for its skeleton.

    The FBX import creates an AnimSequence and then leaves it in the content
    browser: measured, four skeletal actors sat in ANIMATION_BLUEPRINT mode
    with no asset while Take_001 existed beside them, so a skinned character
    arrived in the pose it was bound in and never moved. Matching is by
    skeleton rather than by name, because the FBX names the take after the
    take, not after the mesh.
    """
    sequences = []
    try:
        paths = unreal.EditorAssetLibrary.list_assets(
            MESH_CONTENT_PATH, recursive=True
        ) or []
    except Exception:
        paths = []
    for path in paths:
        try:
            asset = unreal.EditorAssetLibrary.load_asset(path)
        except Exception:
            continue
        if isinstance(asset, unreal.AnimSequence):
            sequences.append(asset)
    if not sequences:
        return 0

    by_skeleton = {}
    for sequence in sequences:
        try:
            skeleton = sequence.get_editor_property("skeleton")
        except Exception:
            skeleton = None
        if skeleton is not None:
            by_skeleton.setdefault(skeleton.get_path_name(), sequence)

    assigned = 0
    for actor in (unreal.get_editor_subsystem(
            unreal.EditorActorSubsystem).get_all_level_actors() or []):
        if not isinstance(actor, unreal.SkeletalMeshActor):
            continue
        component = actor.skeletal_mesh_component
        mesh = None
        for name in ("skeletal_mesh_asset", "skeletal_mesh"):
            try:
                mesh = component.get_editor_property(name)
            except Exception:
                mesh = None
            if mesh is not None:
                break
        if mesh is None:
            continue
        try:
            skeleton = mesh.get_editor_property("skeleton")
        except Exception:
            continue
        if skeleton is None:
            continue
        sequence = by_skeleton.get(skeleton.get_path_name())
        if sequence is None:
            continue
        try:
            component.set_editor_property(
                "animation_mode", unreal.AnimationMode.ANIMATION_SINGLE_NODE
            )
            # Both, and they are not the same thing: set_animation drives the
            # live instance and animation_data is what the level stores.
            # Measured, setting only the first left animation_data empty, so
            # the assignment vanished the moment anybody reloaded the map.
            play_data = unreal.SingleAnimationPlayData()
            play_data.set_editor_property("anim_to_play", sequence)
            # The fields are saved_* here, not looping/playing -- the plain
            # names are refused outright, which is the good kind of failure.
            play_data.set_editor_property("saved_looping", True)
            play_data.set_editor_property("saved_playing", True)
            component.set_editor_property("animation_data", play_data)
            component.set_animation(sequence)
            component.play(True)
            assigned += 1
        except Exception as exc:
            warnings.append(
                'Skeletal actor "{0}" could not be given its animation: '
                "{1}".format(actor.get_actor_label(), exc)
            )
    return assigned


def _interchange_sequences():
    """Level Sequences the FBX import made, as opposed to the one we build."""
    found = []
    try:
        paths = unreal.EditorAssetLibrary.list_assets(
            MESH_CONTENT_PATH, recursive=True) or []
    except Exception:
        return found
    for path in paths:
        try:
            asset = unreal.EditorAssetLibrary.load_asset(path)
        except Exception:
            continue
        if isinstance(asset, unreal.LevelSequence):
            found.append(asset)
    return found


def _channel_keys(section):
    """Every channel of a section as (name, [(tick, value)]), keys only."""
    read = []
    for channel in section.get_all_channels() or []:
        try:
            keys = channel.get_keys() or []
        except Exception:
            continue
        pairs = []
        for key in keys:
            try:
                pairs.append((key.get_time().frame_number.value,
                              key.get_value()))
            except Exception:
                continue
        if pairs:
            read.append((channel.get_name(), pairs))
    return read


def make_movable(actor):
    """Let the actor be moved at runtime, which Interchange does not.

    Every mesh the FBX brings arrives Static, and the editor moves a Static
    component without complaint -- which is why scrubbing a sequence shows the
    whole shot playing. Press Play and the engine refuses: "Mobility of
    ... StaticMeshComponent0 has to be 'Movable' if you'd like to move", once
    per object per attempt, and the level stands still while the camera flies.
    That difference between the editor and PIE is the whole bug, and it is
    invisible to anything that measures in the editor world.

    Only what is keyed or driven gets this: Static is worth keeping for the
    thousands of objects that never move, since it is what lets them take
    baked lighting.
    """
    try:
        component = actor.root_component
    except Exception:
        return False
    if component is None:
        return False
    try:
        if component.mobility == unreal.ComponentMobility.MOVABLE:
            return False
        component.set_editor_property(
            "mobility", unreal.ComponentMobility.MOVABLE)
        return True
    except Exception:
        return False


def _varies(channels, tolerance=ADOPTED_MOTION_TOLERANCE):
    """Whether any channel actually changes across its keys.

    Interchange keys every object it imported, moving or not. Measured on a
    real shot: 65 of the adopted sections were two keys reading 0.0 to three
    places on all six channels. They cost nothing to evaluate -- a transform
    track is relative, so they write the identity an unparented actor already
    has -- but they are *rows*, and they were the only object rows in the
    outliner, the movers having been taken off the sequence on purpose.
    Somebody opening that sequence scrolls a list of mesh names whose
    transform tracks do nothing and reads it as a shot that did not arrive.
    That is how it was reported.

    "Reading 0.0" is not zero, and the first guard here was 1e-6 and caught
    none of them: the bake leaves noise at 4.554e-05. The tolerance is where
    it is because the two populations were measured, not rounded -- see
    ADOPTED_MOTION_TOLERANCE.
    """
    for _name, pairs in channels:
        values = [value for _tick, value in pairs]
        if values and (max(values) - min(values)) > tolerance:
            return True
    return False


def adopt_object_animation(sequence, ticks_per_frame, first, last, warnings,
                           skip_labels=None):
    """Object motion from the FBX, retimed into the sequence we built.

    Meshes carry their animation inside the FBX rather than in the package,
    and Interchange does import it -- into a Level Sequence of its own, with
    every key written at its **frame number as a tick**. Measured on a 520
    frame move: the keys land at ticks 1 and 519, so the whole animation
    happens inside the first fiftieth of a frame and the object is already at
    its end position before frame one. That reads exactly like nothing moved.

    So the keys are read out and written back on our sequence at the right
    time base, where the lights and cameras already are. The compression is
    detected rather than assumed: if the keys already span more than a frame,
    they are taken as they are, so an engine build that fixes this does not
    get its animation stretched by a thousand.
    """
    if ticks_per_frame <= 0:
        return 0, 0

    actors = actors_by_label()
    adopted = 0
    keys_written = 0
    still = 0
    emptied = []
    for source in _interchange_sequences():
        # Sections read, whether or not they were worth a track. A source
        # whose every object is static gives up nothing, and counting only
        # what was written would leave it behind for the user to open by
        # mistake -- which is the failure it was measured causing before.
        taken = 0
        for binding in source.get_bindings() or []:
            label = str(binding.get_display_name() or "")
            actor = actors.get(label)
            if actor is None:
                continue
            # Whatever the FBX happened to bake for an object the package
            # measured is not a second opinion worth having: two transform
            # tracks on one binding fight, and the sampled one is the one
            # that caught the solver.
            if label in (skip_labels or set()):
                continue
            for track in binding.get_tracks() or []:
                if not isinstance(track, unreal.MovieScene3DTransformTrack):
                    continue
                for section in track.get_sections() or []:
                    channels = _channel_keys(section)
                    if not channels:
                        continue
                    if not _varies(channels):
                        still += 1
                        taken += 1
                        continue
                    span = max(
                        (pairs[-1][0] - pairs[0][0]) for _n, pairs in channels
                    )
                    scale = ticks_per_frame if span < ticks_per_frame else 1.0
                    make_movable(actor)
                    target = sequence.add_possessable(actor)
                    _track, destination = _section(
                        target, unreal.MovieScene3DTransformTrack, first, last
                    )
                    written = _copy_channels(destination, channels, scale)
                    if written:
                        adopted += 1
                        taken += 1
                        keys_written += written
                        if scale != 1.0:
                            warnings.append(
                                'Object "{0}" was animated in the FBX at one '
                                "tick per frame, which plays entirely inside "
                                "the first frame. Its {1} key(s) were retimed "
                                "onto the mLender sequence.".format(
                                    label, written
                                )
                            )
        if taken:
            emptied.append(source)
    _discard(emptied, warnings)
    if still:
        # Said rather than left to be noticed: an outliner with fewer rows
        # than the level has objects is the sort of thing a person reads as
        # loss, and this is the opposite of loss.
        warnings.append(
            "{0} object(s) the FBX keyed do not move -- every key is the same "
            "value -- so no track was built for them. What does move is on "
            "the sequence.".format(still)
        )
    return adopted, keys_written


def _discard(sequences, warnings):
    """Get the FBX importer's sequences out of the way once their keys are ours.

    Leaving one costs more than the disk it takes. Interchange puts its
    sequence beside the meshes, where it is the easier of the two to open by
    mistake, and it plays nothing: every key sits at its frame number as a
    tick, so the whole shot happens inside the first fiftieth of a frame.
    Somebody opening that one drags the playhead and sees a level that does
    not move.

    Deleting is refused while anything still references it, and the refusal
    is a False return rather than an exception -- so the answer is read, and
    when it is no, the user is told which sequence to open instead. Only
    sequences whose keys were taken are touched; one that gave up nothing may
    still hold something.
    """
    # Through the compiled module when it is there: the sequence was made
    # this session and never saved, and the editor's force delete of it
    # trips an ensure -- "failed to unload all packages, likely corrupt" --
    # measured on every import of a shot, and it is what sent the commandlet
    # home with a non-zero exit while everything had in fact worked.
    utility = getattr(unreal, "MLAssetUtility", None)
    for sequence in sequences:
        path = ""
        gone = False
        try:
            path = sequence.get_path_name().split(".")[0]
            if utility is not None:
                gone = utility.discard_unsaved_assets([sequence]) == 1
            if not gone:
                gone = bool(
                    unreal.EditorAssetLibrary.delete_loaded_asset(sequence))
            if not gone:
                gone = bool(unreal.EditorAssetLibrary.delete_asset(path))
        except Exception:
            gone = False
        if not gone:
            warnings.append(
                "The FBX importer left a Level Sequence of its own at "
                "\"{0}\", which could not be removed. Its keys are already "
                "on the mLender sequence; opening that one instead is the "
                "difference between a shot that plays and one that looks "
                "still.".format(path)
            )


def _channel_role(name):
    """"Location.Z_2" -> "location.z". The suffix differs between assets."""
    label = str(name or "")
    if "_" in label:
        head, _sep, tail = label.rpartition("_")
        if tail.isdigit() and head:
            label = head
    return label.strip().lower()


def _copy_channels(section, channels, scale):
    """Write read-back channels onto a section, scaling their times.

    Matched by role, not by position. Only channels that carry keys come back
    from a read, so a fall keyed on Z alone arrives as a single channel -- and
    writing it into the destination's first slot puts a vertical drop on the X
    axis. Measured on a rigid body sim: the object was keyed, the track was
    there, and it did not move, because it was moving sideways out of view.
    """
    destination = section.get_all_channels() or []
    if not destination:
        return 0
    by_role = {}
    for channel in destination:
        by_role.setdefault(_channel_role(channel.get_name()), channel)

    written = 0
    for name, pairs in channels:
        target = by_role.get(_channel_role(name))
        if target is None:
            continue
        for tick, value in pairs:
            if _add_key(target, int(round(tick * scale)), float(value)):
                written += 1
    return written


def animate_geometry_caches(sequence, ticks_per_frame, first, last,
                            warnings):
    """Put every geometry cache on the sequence, so scrubbing plays it.

    A cache is not keyed by anything this tool writes: it plays on its own
    clock, driven by a component. Without a track it holds its first frame
    for the whole shot, which is exactly what a simulation that did not
    travel looks like -- and this option exists to carry simulations.

    The track goes on the **actor**. The engine accepts either -- its
    execution token calls GeometryMeshComponentFromObject, which takes an
    actor and finds the component, or takes the component itself -- but the
    actor is the binding Epic's own documentation describes adding the track
    to, and it is one fewer thing to resolve: a component possessable only
    resolves through its parent actor's binding anyway.
    """
    caches = []
    try:
        actors = unreal.get_editor_subsystem(
            unreal.EditorActorSubsystem).get_all_level_actors() or []
    except Exception:
        return 0, 0
    for actor in actors:
        if actor.get_class().get_name() != "GeometryCacheActor":
            continue
        component = _component(actor, "geometry_cache_component")
        if component is None:
            continue
        try:
            asset = component.get_editor_property("geometry_cache")
        except Exception:
            asset = None
        if asset is None:
            continue
        caches.append((actor, component, asset))

    tracks = 0
    for actor, component, asset in caches:
        try:
            binding = sequence.add_possessable(actor)
            _track, section = _section(
                binding, unreal.MovieSceneGeometryCacheTrack, first, last
            )
            params = section.get_editor_property("params")
            params.set_editor_property("geometry_cache_asset", asset)
            section.set_editor_property("params", params)
            tracks += 1
        except Exception as exc:
            warnings.append(
                'The cache on "{0}" could not be put on the sequence, so it '
                "holds its first frame: {1}".format(
                    actor.get_actor_label(), exc
                )
            )
    # No keys of ours: the cache carries its own frames, and counting them
    # here would report geometry the sequence does not hold.
    return tracks, 0


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
        handle = open(path, "r")
        try:
            return json.load(handle)
        finally:
            handle.close()
    except Exception as exc:
        warnings.append(
            "The sampled motion could not be read ({0}), so the objects it "
            "carries arrive still.".format(exc)
        )
        return {}


def _unwound(previous, angles):
    """The same rotation, told so it does not jump between frames.

    Every sample is an independent world matrix, and resolving each to Euler
    on its own turns a full revolution into a jump from 179 to -179. A
    tumbling piece of debris does that several times a shot, and the keys
    either side of such a sample spin it backwards through the whole turn.
    """
    if previous is None:
        return list(angles)
    result = []
    for before, angle in zip(previous, angles):
        while angle - before > 180.0:
            angle -= 360.0
        while before - angle > 180.0:
            angle += 360.0
        result.append(angle)
    return result


def _parent_inverse(actor):
    """The inverse of whatever the actor hangs from, or nothing.

    A Sequencer transform track keys an actor's *relative* transform, so an
    actor the FBX left attached to a group would be keyed inside that group
    and arrive somewhere else entirely. The parent does not move -- nothing
    in this package keys a group -- so one inverse, taken once, is the whole
    correction. Once per object rather than once per frame: a shot of 3384
    movers over 520 frames would otherwise ask the same actor who its parent
    is 1.7 million times.
    """
    try:
        parent = actor.get_attach_parent_actor()
    except Exception:
        return None
    if parent is None:
        return None
    try:
        return unreal.MathLibrary.invert_transform(
            parent.get_actor_transform())
    except Exception:
        return None


def _relative_to_parent(inverse, location, rotation, scale):
    """A world transform expressed in the frame the keys are read in."""
    if inverse is None:
        return location, rotation, scale
    try:
        relative = unreal.MathLibrary.compose_transforms(
            unreal.Transform(location, rotation, scale), inverse)
        return (relative.translation, relative.rotation.rotator(),
                relative.scale3d)
    except Exception:
        return location, rotation, scale


def _keyable(values, tolerance=1.0e-4):
    """The indices worth a key, given that the keys interpolate linearly.

    A sample sitting between two identical neighbours is already on the line
    those two draw, so keying it changes nothing and costs a call. The ends of
    a run are kept, so an object that settles and later moves again still
    starts moving on the right frame.

    It is not a micro-optimisation at this scale: a shot of 3384 movers over
    520 frames is 15.8 million channel keys written one call at a time, and
    debris that comes to rest halfway through is most of them.
    """
    keep = []
    count = len(values)
    for index in range(count):
        if index == 0 or index == count - 1:
            keep.append(index)
            continue
        before = values[index - 1]
        after = values[index + 1]
        value = values[index]
        if (abs(value - before) <= tolerance
                and abs(after - value) <= tolerance):
            continue
        keep.append(index)
    return keep


def _expanded(reference):
    """A twelve float reference back into a full Maya world matrix."""
    if not reference or len(reference) < 12:
        return None
    row = list(reference[:12])
    return [
        row[0], row[1], row[2], 0.0,
        row[3], row[4], row[5], 0.0,
        row[6], row[7], row[8], 0.0,
        row[9], row[10], row[11], 1.0,
    ]


def _anchor_transform(placed, reference, unreal_scale):
    """Where the FBX put the object, with the reference pose divided out.

    A sample says where the object was in Maya; the anchor turns that into
    where the actor should be, by asking what has changed since the pose the
    FBX carries. Composing a sample onto this leaves the reference frame
    exactly where Interchange put it -- roll and all.
    """
    matrix = _expanded(reference)
    if matrix is None:
        return None
    try:
        location, rotation, scale = unreal_object_transform(
            {"world_matrix": matrix}, unreal_scale)
        return unreal.MathLibrary.compose_transforms(
            placed,
            unreal.MathLibrary.invert_transform(
                unreal.Transform(location, rotation, scale)),
        )
    except Exception:
        return None


def _motion_parts(master, label, count, first, last, warnings):
    """Sub-sequences for the movers, hung off the master, or nothing.

    Nothing when the shot is small enough to hold in one sequence, which
    keeps the common case exactly as it was. Above that the objects are cut
    into parts and the master carries a section per part, so opening it costs
    one row per few hundred objects rather than one per object.
    """
    if count <= MOTION_BINDINGS_PER_SEQUENCE:
        return []
    wanted = (count + MOTION_BINDINGS_PER_SEQUENCE - 1)         // MOTION_BINDINGS_PER_SEQUENCE
    tools = unreal.AssetToolsHelpers.get_asset_tools()
    try:
        track = master.add_track(unreal.MovieSceneSubTrack)
    except Exception as exc:
        warnings.append(
            "The shot is {0} objects but could not be split into "
            "sub-sequences ({1}), so it is one sequence and may be slow to "
            "open.".format(count, exc)
        )
        return []
    parts = []
    for index in range(wanted):
        name = "{0}_{1}_Part{2:02d}".format(
            ANIMATION_SEQUENCE_NAME, label, index + 1)
        path = "{0}/{1}".format(SEQUENCE_CONTENT_PATH, name)
        try:
            if unreal.EditorAssetLibrary.does_asset_exist(path):
                unreal.EditorAssetLibrary.delete_asset(path)
            part = tools.create_asset(
                name, SEQUENCE_CONTENT_PATH, unreal.LevelSequence,
                unreal.LevelSequenceFactoryNew(),
            )
        except Exception:
            part = None
        if part is None:
            warnings.append(
                'Sub-sequence "{0}" could not be built, so the objects it '
                "would have carried stay on the main sequence.".format(name)
            )
            break
        # The parts share the master's time base, or a section that spans the
        # shot on one reads as a fraction of it on the other.
        try:
            part.set_display_rate(master.get_display_rate())
            part.set_tick_resolution(master.get_tick_resolution())
            part.set_playback_start(master.get_playback_start())
            part.set_playback_end(master.get_playback_end())
        except Exception:
            pass
        section = track.add_section()
        section.set_sequence(part)
        section.set_range(first, last)
        parts.append(part)
    return parts


def motion_player_available():
    """Whether the plugin's compiled module is loaded.

    The player and its asset are C++ classes. A plugin installed without its
    Binaries folder, or on an engine it was not built for, has the Python and
    not the module -- and then the movers fall back to one row each on the
    sequence, which plays but is what the editor could not open above a few
    hundred objects.
    """
    return (getattr(unreal, "MLMotionPlayer", None) is not None
            and getattr(unreal, "MLMotionData", None) is not None)


def _sparse(samples, tolerance=MOTION_KEY_TOLERANCE):
    """The indices worth keeping, given that the player interpolates.

    The rule of _keyable applied to a whole sample rather than one lane: a
    sample within tolerance of both neighbours on every component already
    lies on the line between them. Run ends are kept, so a piece that settles
    and later moves again starts moving on the right frame.
    """
    keep = []
    count = len(samples)
    for index in range(count):
        if index == 0 or index == count - 1:
            keep.append(index)
            continue
        before = samples[index - 1]
        after = samples[index + 1]
        value = samples[index]
        if all(abs(v - b) <= tolerance and abs(a - v) <= tolerance
               for v, b, a in zip(value, before, after)):
            continue
        keep.append(index)
    return keep


def _visibility_switches(frame_numbers, visible):
    """The frames at which visibility changes, with the value from then on."""
    switch_frames = []
    switch_values = []
    previous = None
    for frame, state in zip(frame_numbers, visible):
        state = bool(state)
        if previous is None or state != previous:
            switch_frames.append(int(frame))
            switch_values.append(state)
            previous = state
    return switch_frames, switch_values


def _world_samples(track, frames, anchor, unreal_scale):
    """Ten floats per frame: the world transform the player should write.

    The same composition the sequence keys used -- each sample onto the
    anchor that divides out the reference pose -- without the parent inverse,
    because the player sets world transforms and Sequencer keys relative ones.
    """
    values = track.get("matrix") or []
    samples = []
    for index in range(len(frames)):
        row = values[index * 12:(index + 1) * 12]
        matrix = [
            row[0], row[1], row[2], 0.0,
            row[3], row[4], row[5], 0.0,
            row[6], row[7], row[8], 0.0,
            row[9], row[10], row[11], 1.0,
        ]
        location, rotation, scale = unreal_object_transform(
            {"world_matrix": matrix}, unreal_scale
        )
        world = unreal.MathLibrary.compose_transforms(
            anchor, unreal.Transform(location, rotation, scale)
        )
        translation = world.translation
        quaternion = world.rotation
        scale3d = world.scale3d
        samples.append((
            float(translation.x), float(translation.y), float(translation.z),
            float(quaternion.x), float(quaternion.y), float(quaternion.z),
            float(quaternion.w),
            float(scale3d.x), float(scale3d.y), float(scale3d.z),
        ))
    return samples


def _motion_asset(label, warnings):
    """A fresh motion asset for this shot, or None with the reason said."""
    name = safe_asset_name(
        "{0}_{1}".format(MOTION_ASSET_NAME, label), "Motion")
    path = "{0}/{1}".format(MOTION_CONTENT_PATH, name)
    try:
        if unreal.EditorAssetLibrary.does_asset_exist(path):
            unreal.EditorAssetLibrary.delete_asset(path)
    except Exception:
        pass
    try:
        asset = unreal.MLMotionData.create_motion_asset(
            MOTION_CONTENT_PATH, name)
    except Exception as exc:
        warnings.append(
            "The motion asset could not be created ({0}), so the movers "
            "arrive still.".format(exc)
        )
        return None
    if asset is None:
        warnings.append(
            'Unreal returned no motion asset for "{0}", so the movers arrive '
            "still.".format(path)
        )
    return asset


def animate_motion_player(sequence, motion, actors_by_path, unreal_scale,
                          ticks_per_frame, first, last, warnings,
                          keyed_labels=None, package_label="Scene",
                          result=None):
    """Every rigid mover on one actor, and one float track on the sequence.

    A binding is a row in the Sequencer outliner, and a shot of 7562 movers
    as rows made a 349 MB asset the editor would not open. Cutting it into
    parts kept the rows, in sub-sequences a person could still open by
    mistake. So the movers leave the sequence: their transforms go into one
    data asset, one player actor applies them, and the sequence keys a single
    float -- the frame -- on that actor. Opening the shot costs one row.

    The samples are the same world transforms the rows carried, anchored to
    where Interchange placed each actor for the same measured reason (see
    animate_sampled_motion), thinned to the samples that are not already on
    the line between their neighbours. The player interpolates between them,
    which is also what a sub-frame render needs for motion blur.
    """
    frames = list((motion or {}).get("frames") or [])
    objects = (motion or {}).get("objects") or {}
    if keyed_labels is None:
        keyed_labels = set()
    if result is None:
        result = {}
    if not frames or not objects:
        return 0, 0

    asset = _motion_asset(package_label, warnings)
    if asset is None:
        return 0, 0

    frame_numbers = [int(round(float(frame))) for frame in frames]
    ids = []
    actors = []
    missing = 0
    keys = 0
    for path, track in objects.items():
        actor = actors_by_path.get(path)
        if actor is None:
            missing += 1
            continue
        values = track.get("matrix") or []
        if len(values) < len(frames) * 12:
            missing += 1
            continue
        # Where Interchange put it, read before anything of ours touches the
        # actor, with the reference pose divided out so a sample composes
        # straight onto it.
        anchor = _anchor_transform(
            actor.get_actor_transform(), track.get("reference"), unreal_scale)
        if anchor is None:
            missing += 1
            continue
        samples = _world_samples(track, frames, anchor, unreal_scale)
        kept = _sparse(samples)
        flat = []
        for index in kept:
            flat.extend(samples[index])
        visible = track.get("visible") or []
        if len(visible) >= len(frames):
            switch_frames, switch_values = _visibility_switches(
                frame_numbers, visible)
        else:
            switch_frames, switch_values = [], []
        added = asset.add_track(
            path, [frame_numbers[index] for index in kept], flat,
            switch_frames, switch_values)
        if added < 0:
            missing += 1
            continue
        make_movable(actor)
        ids.append(path)
        actors.append(actor)
        keys += len(kept)

    if missing:
        warnings.append(
            "{0} object(s) carry sampled motion but no actor in the level "
            "matched them, so they arrive still.".format(missing)
        )
    if not ids:
        return 0, 0

    # The FBX pose is the reference frame's, so that is where the player
    # rests: closing the sequence restores the property, and the actors
    # return to exactly where Interchange put them.
    reference = (motion or {}).get("reference_frame")
    try:
        reference = float(reference)
    except (TypeError, ValueError):
        reference = float(frames[0])

    try:
        player = unreal.EditorLevelLibrary.spawn_actor_from_class(
            unreal.MLMotionPlayer, unreal.Vector(0.0, 0.0, 0.0))
        player.set_actor_label(safe_asset_name(
            "{0}_{1}".format(MOTION_PLAYER_NAME, package_label),
            "MotionPlayer"))
        player.tags = [GENERATED_TAG]
        player.set_editor_property("motion", asset)
        bound = player.bind_actors(ids, actors)
        player.set_frame(reference)
    except Exception as exc:
        warnings.append(
            "The motion player could not be placed ({0}), so the {1} "
            "mover(s) arrive still.".format(exc, len(ids))
        )
        return 0, 0
    try:
        unreal.EditorAssetLibrary.save_loaded_asset(asset)
    except Exception:
        pass

    # One binding, one track, two keys: the frame number itself, linear
    # from the first tick to the last, so scrubbing the ruler reads the
    # frame straight off it.
    counted = 0
    try:
        binding = sequence.add_possessable(player)
        track = binding.add_track(unreal.MovieSceneFloatTrack)
        track.set_property_name_and_path(
            MOTION_FRAME_PROPERTY, MOTION_FRAME_PROPERTY)
        section = track.add_section()
        section.set_range(first, last)
        channels = section.get_all_channels()
        if channels:
            per_frame = float(ticks_per_frame) or 1.0
            if _add_key(channels[0], first, float(first) / per_frame):
                counted += 1
            if _add_key(channels[0], last, float(last) / per_frame):
                counted += 1
    except Exception as exc:
        warnings.append(
            "The motion player is placed but the sequence could not key it "
            "({0}); scrub it from the actor's Frame instead.".format(exc)
        )

    for actor in actors:
        try:
            keyed_labels.add(str(actor.get_actor_label()))
        except Exception:
            pass
    result["motion_objects"] = bound
    result["motion_keys"] = keys
    try:
        result["motion_player"] = str(player.get_actor_label())
        result["motion_asset"] = str(asset.get_path_name())
    except Exception:
        pass
    return (1 if counted else 0), counted + keys


def animate_motion(sequence, motion, actors_by_path, unreal_scale,
                   ticks_per_frame, first, last, warnings,
                   keyed_labels=None, package_label="Scene", result=None):
    """The movers, on the player when the module is there and as rows if not."""
    if motion_player_available():
        return animate_motion_player(
            sequence, motion, actors_by_path, unreal_scale, ticks_per_frame,
            first, last, warnings, keyed_labels, package_label, result)
    count = len((motion or {}).get("objects") or {})
    if count:
        warnings.append(
            "The plugin's compiled module is not loaded, so its {0} mover(s) "
            "were keyed one row each on the sequence{1}. Install a build "
            "with its Binaries folder, or build Source/mLender, to play them "
            "from one actor instead.".format(
                count,
                ", split into parts" if count > MOTION_BINDINGS_PER_SEQUENCE
                else "")
        )
    return animate_sampled_motion(
        sequence, motion, actors_by_path, unreal_scale, ticks_per_frame,
        first, last, warnings, keyed_labels, package_label)


def animate_sampled_motion(sequence, motion, actors_by_path, unreal_scale,
                           ticks_per_frame, first, last, warnings,
                           keyed_labels=None, package_label="Scene"):
    """Transform and visibility keys for the movers that only move.

    The fallback for a plugin whose compiled module is not loaded; see
    animate_motion_player for the path a full install takes.

    This is the half of a simulation that does not belong in a geometry
    cache. It arrives as one transform per frame per object, which is what a
    rigid body is, and it lands on the static mesh the FBX already brought --
    ray traced, instanced, and with nothing to stream.

    What arrives is a *delta* from the frame the FBX holds, not a world
    transform, and it is applied on top of where Interchange put the actor.
    Measured, and the reason: Interchange places every FBX actor with a 90
    degree roll -- that is where the format's up-axis conversion lands, with
    the mesh left in the converted frame. Writing our own world transform
    over that discarded it and turned every moving object by exactly that
    much. A delta keeps whatever the format did and adds only the movement,
    so at the reference frame the object does not move at all.
    """
    frames = list((motion or {}).get("frames") or [])
    objects = (motion or {}).get("objects") or {}
    if keyed_labels is None:
        keyed_labels = set()
    if not frames or not objects:
        return 0, 0

    # One sequence per few hundred objects rather than one for the shot. A
    # binding is a row, and a shot of 7562 of them made an asset the editor
    # would not open: measured, 349 MB and 14383 tracks hung on opening,
    # while the same data at 400 bindings and 21 MB opened at once. The
    # master keeps one row per part, so the outliner stays a page long.
    parts = _motion_parts(sequence, package_label, len(objects), first, last,
                          warnings)
    tracks = 0
    keys = 0
    missing = 0
    for index, (path, track) in enumerate(objects.items()):
        target = (parts[index // MOTION_BINDINGS_PER_SEQUENCE]
                  if parts else sequence)
        actor = actors_by_path.get(path)
        if actor is None:
            missing += 1
            continue
        values = track.get("matrix") or []
        if len(values) < len(frames) * 12:
            missing += 1
            continue
        make_movable(actor)
        binding = target.add_possessable(actor)
        _track, section = _section(
            binding, unreal.MovieScene3DTransformTrack, first, last
        )
        channels = section.get_all_channels()
        if len(channels) < 9:
            continue
        previous = None
        counted = 0
        inverse = _parent_inverse(actor)
        # Where Interchange put it, read before anything of ours touches
        # the actor -- and with the sampled pose of the same frame divided
        # out, so a sample composes straight onto it.
        placed = actor.get_actor_transform()
        anchor = _anchor_transform(placed, track.get("reference"),
                                   unreal_scale)
        if anchor is None:
            missing += 1
            continue
        lanes = [[] for _index in range(9)]
        for index, frame in enumerate(frames):
            row = values[index * 12:(index + 1) * 12]
            # The fourth column the exporter dropped, put back: Maya never
            # varies it, so it was not worth a quarter of the file.
            matrix = [
                row[0], row[1], row[2], 0.0,
                row[3], row[4], row[5], 0.0,
                row[6], row[7], row[8], 0.0,
                row[9], row[10], row[11], 1.0,
            ]
            location, rotation, scale = unreal_object_transform(
                {"world_matrix": matrix}, unreal_scale
            )
            # The sample, composed onto the anchor: A then B, which is
            # what compose_transforms means by its order.
            world = unreal.MathLibrary.compose_transforms(
                anchor, unreal.Transform(location, rotation, scale)
            )
            location, rotation, scale = _relative_to_parent(
                inverse, world.translation, world.rotation.rotator(),
                world.scale3d,
            )
            angles = _unwound(
                previous, (rotation.roll, rotation.pitch, rotation.yaw)
            )
            previous = angles
            for lane, value in zip(lanes, (
                location.x, location.y, location.z,
                angles[0], angles[1], angles[2],
                scale.x, scale.y, scale.z,
            )):
                lane.append(float(value))
        ticks = [int(round(float(frame) * ticks_per_frame))
                 for frame in frames]
        for channel, lane in zip(channels, lanes):
            for index in _keyable(lane):
                if _add_key(channel, ticks[index], lane[index]):
                    counted += 1
        visible = track.get("visible") or []
        if len(visible) >= len(frames):
            _vis_track, vis_section = _section(
                binding, unreal.MovieSceneVisibilityTrack, first, last
            )
            vis_channels = vis_section.get_all_channels()
            if vis_channels:
                for index, frame in enumerate(frames):
                    # True is visible here; the engine's own flag is hidden,
                    # and passing that value through inverts every blink.
                    if _add_key(vis_channels[0],
                                int(round(float(frame) * ticks_per_frame)),
                                bool(visible[index])):
                        counted += 1
        if counted:
            tracks += 1
            keys += counted
            try:
                keyed_labels.add(str(actor.get_actor_label()))
            except Exception:
                pass
    if missing:
        warnings.append(
            "{0} object(s) carry sampled motion but no actor in the level "
            "matched them, so they arrive still.".format(missing)
        )
    return tracks, keys


def _editor_world():
    """The world being edited, through whichever accessor this build has."""
    try:
        return unreal.get_editor_subsystem(
            unreal.UnrealEditorSubsystem).get_editor_world()
    except Exception:
        pass
    try:
        return unreal.EditorLevelLibrary.get_editor_world()
    except Exception:
        return None


def warn_unsaved_world(warnings):
    """Say so when the level has no name yet, because every binding will stale.

    A possessable is stored as a path inside the world it was bound in, so
    saving that world under a new name leaves every binding pointing at a
    world that no longer exists. Measured on a headless send: the import ran
    in ``/Temp/Untitled_0`` and the driver saved the level afterwards as
    ``/Game/Shot_v108_player``. All 73 bindings then resolved to nothing while
    all of their actors were still in the level under the right labels, and
    Sequencer drew every row red -- "the object bound to this track is
    missing". A binding made in the saved world resolved on the same asset in
    the same session, which is what ruled the API out and the rename in.

    A warning rather than a refusal: the meshes, materials and lights are all
    still worth having, and it is only the timeline that is lost.
    """
    world = _editor_world()
    path = ""
    try:
        path = str(world.get_path_name()) if world is not None else ""
    except Exception:
        path = ""
    if not path.startswith("/Temp/") and not path.startswith("/Engine/"):
        return False
    warnings.append(
        'The level has not been saved yet ("{0}"), so every Sequencer '
        "binding this import writes is stored against a world that stops "
        "existing the moment the level is saved under a name: the tracks "
        "survive, their objects read as missing, and the timeline plays "
        "nothing. Save the level first, then send again.".format(path)
    )
    return True


def import_animation(package_data, unreal_scale, metre_scale, power_scale,
                     warnings, package_folder="", actors_by_path=None,
                     motion=None):
    """Build the Level Sequence and place an actor that plays it."""
    sequence, ticks_per_frame, first, last = create_sequence(
        package_data, warnings
    )
    # Before a single binding is written, and whether or not there is a
    # sequence: an unnamed world costs the FBX's own object animation too.
    warn_unsaved_world(warnings)
    if sequence is None:
        # No package animation still leaves the FBX's own take to hand out.
        skeletal = 0
        try:
            skeletal = assign_skeletal_animation(warnings)
        except Exception:
            pass
        return {"sequence_path": "", "track_count": 0, "key_count": 0,
                "skeletal_animated": skeletal}

    actors = actors_by_label()
    tracks = 0
    keys = 0
    # Filled by the sampled motion pass and read by the adopt pass below.
    sampled_labels = set()
    # What the motion pass built, for the report: the player and its asset.
    motion_result = {}
    try:
        skeletal = assign_skeletal_animation(warnings)
    except Exception as exc:
        skeletal = 0
        warnings.append(
            "Skeletal animation could not be assigned: {0}".format(exc)
        )
    builders = (
        lambda: animate_lights(
            sequence, package_data, actors, unreal_scale, metre_scale,
            power_scale, ticks_per_frame, first, last, warnings),
        lambda: animate_cameras(
            sequence, package_data, actors, unreal_scale, ticks_per_frame,
            first, last, warnings),
        lambda: animate_visibility(
            sequence, package_data, actors, ticks_per_frame, first, last,
            warnings),
        lambda: animate_materials(
            sequence, package_data, actors, ticks_per_frame, first, last,
            warnings),
        lambda: animate_geometry_caches(
            sequence, ticks_per_frame, first, last, warnings),
        lambda: animate_motion(
            sequence,
            motion if motion is not None
            else read_motion(package_folder, package_data, warnings),
            actors_by_path or {}, unreal_scale, ticks_per_frame, first, last,
            warnings, sampled_labels, sequence_label(package_data),
            motion_result),
    )
    for builder in builders:
        try:
            built_tracks, built_keys = builder()
        except Exception as exc:
            warnings.append(
                "Part of the animation could not be keyed: {0}".format(exc)
            )
            continue
        tracks += built_tracks
        keys += built_keys

    # Object motion rides the FBX, and Interchange puts it in a sequence of
    # its own at the wrong time base. Adopted last, so it joins everything
    # else on one timeline.
    try:
        adopted, adopted_keys = adopt_object_animation(
            sequence, ticks_per_frame, first, last, warnings, sampled_labels
        )
        tracks += adopted
        keys += adopted_keys
    except Exception as exc:
        warnings.append(
            "Object animation from the FBX could not be adopted: {0}".format(
                exc
            )
        )

    path = ""
    try:
        path = sequence.get_path_name()
        unreal.EditorAssetLibrary.save_loaded_asset(sequence)
    except Exception:
        pass

    # An actor that holds the sequence, so the level plays it rather than the
    # level holding an asset nobody opens.
    try:
        player_actor = unreal.EditorLevelLibrary.spawn_actor_from_class(
            unreal.LevelSequenceActor, unreal.Vector(0.0, 0.0, 0.0)
        )
        player_actor.set_sequence(sequence)
        # Named after the shot as well, for the same reason the asset is: two
        # shots in one project otherwise produce two actors called ML_Sequence
        # and neither says which timeline it plays.
        player_actor.set_actor_label("{0}_{1}".format(
            safe_asset_name(ANIMATION_SEQUENCE_NAME, "Sequence"),
            sequence_label(package_data),
        ))
        player_actor.tags = [GENERATED_TAG]
    except Exception as exc:
        warnings.append(
            "The Level Sequence was built but no actor plays it: {0}".format(
                exc
            )
        )

    return {
        "sequence_path": path,
        "track_count": tracks,
        "key_count": keys,
        "skeletal_animated": skeletal,
        "motion_objects": motion_result.get("motion_objects", 0),
        "motion_keys": motion_result.get("motion_keys", 0),
        "motion_player": motion_result.get("motion_player", ""),
        "motion_asset": motion_result.get("motion_asset", ""),
    }
