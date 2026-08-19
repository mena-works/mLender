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
import unreal

from .constants import (
    ANIMATION_SEQUENCE_NAME,
    MESH_CONTENT_PATH,
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
from .transforms import unreal_transform
from .utils import safe_asset_name, scalar


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

    label = safe_asset_name(
        (package_data or {}).get("package_name") or "Scene", "Scene"
    )
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
    return sequence, ticks_per_frame, first, last


def _section(binding, track_class, first, last):
    """A track's single section, spanning the whole range."""
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


def adopt_object_animation(sequence, ticks_per_frame, first, last, warnings):
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
    for source in _interchange_sequences():
        for binding in source.get_bindings() or []:
            label = str(binding.get_display_name() or "")
            actor = actors.get(label)
            if actor is None:
                continue
            for track in binding.get_tracks() or []:
                if not isinstance(track, unreal.MovieScene3DTransformTrack):
                    continue
                for section in track.get_sections() or []:
                    channels = _channel_keys(section)
                    if not channels:
                        continue
                    span = max(
                        (pairs[-1][0] - pairs[0][0]) for _n, pairs in channels
                    )
                    scale = ticks_per_frame if span < ticks_per_frame else 1.0
                    target = sequence.add_possessable(actor)
                    _track, destination = _section(
                        target, unreal.MovieScene3DTransformTrack, first, last
                    )
                    written = _copy_channels(destination, channels, scale)
                    if written:
                        adopted += 1
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
    return adopted, keys_written


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

    The track goes on the component rather than the actor. Both are accepted,
    but the component is what owns the cache, and every other component
    property in this file is keyed the same way.
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
            binding = sequence.add_possessable(component)
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


def import_animation(package_data, unreal_scale, metre_scale, power_scale,
                     warnings):
    """Build the Level Sequence and place an actor that plays it."""
    sequence, ticks_per_frame, first, last = create_sequence(
        package_data, warnings
    )
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
            sequence, ticks_per_frame, first, last, warnings
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
        player_actor.set_actor_label(
            safe_asset_name(ANIMATION_SEQUENCE_NAME, "Sequence")
        )
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
    }
