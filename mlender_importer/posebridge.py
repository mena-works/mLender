# -*- coding: utf-8 -*-
"""Apply a Maya pose to the imported armatures.

The other half of the exporter's pose bridge. Maya evaluated its rig and sent
the bind skeleton's world matrices; this puts each bone where Maya says it is.
Nothing here interprets the rig -- by the time a matrix arrives, every
constraint, ribbon and twist chain has already been evaluated by the one
application that knows how.

The maths runs entirely on the message plus the armatures' rest data, parents
before children, so no depsgraph update is needed mid-pose: a bone's
``matrix_basis`` is derived against its parent's *target* matrix, which was
computed a moment earlier, not against an evaluated scene state.

Whatever axis convention the FBX importer chose for bone rest matrices cancels
out of that derivation -- both the rest pose and the target come through the
same world mapping -- which is why a bind-pose message must produce identity
bases. The end-to-end test asserts exactly that before it asserts anything
else, because it is the cheapest way to catch a convention drift.
"""

import bpy
from mathutils import Matrix

from .animation import action_fcurves
from .constants import ANIMATION_INTERPOLATION
from .utils import scalar


def apply_pose(pose, scene=None, warnings=None):
    """Pose every matching bone. Returns counts the caller can report."""
    warnings = warnings if warnings is not None else []
    pose = pose or {}
    joints = pose.get("joints") or []
    if not joints:
        return {"applied": 0, "unmatched": 0, "armatures": 0}

    scene = scene or bpy.context.scene
    meters_per_unit = scalar(pose.get("meters_per_maya_unit"), 0.01)
    import_scale = scalar(getattr(scene, "ml_import_scale", 1.0), 1.0)
    position_scale = meters_per_unit * max(import_scale, 0.000001)

    bones = _bone_lookup(warnings)
    if not bones:
        warnings.append(
            "Pose received but the scene has no armature to apply it to. "
            "Import a package with a skinned mesh first."
        )
        return {"applied": 0, "unmatched": len(joints), "armatures": 0}

    # Parents before children: the basis of a child is derived against the
    # parent's target matrix, so the parent's target must be on record first.
    ordered = sorted(
        (entry for entry in joints if isinstance(entry, dict)),
        key=lambda entry: str(entry.get("path") or "").count("|"),
    )

    targets = {}
    touched = set()
    applied = 0
    unmatched = 0
    for entry in ordered:
        name = str(entry.get("name") or "")
        found = bones.get(name)
        matrix = entry.get("matrix") or []
        if found is None or len(matrix) != 16:
            unmatched += 1
            continue
        armature, pose_bone = found
        target = _pose_space_target(armature, matrix, position_scale)
        pose_bone.matrix_basis = _basis_for(pose_bone, target, targets)
        targets[(armature.name, pose_bone.name)] = target
        touched.add(armature.name)
        applied += 1

    if unmatched:
        warnings.append(
            "{0} joint(s) in the pose matched no bone; the package and the "
            "Maya scene may have drifted apart. Re-send the package.".format(
                unmatched
            )
        )
    switched = _park_ik_limbs(touched)
    if switched:
        # A streamed pose is an FK dictation: every joint's world matrix is
        # already the evaluated truth. An IK limb left live would fight it --
        # measured, the solver re-orients the parents and the child bases
        # the pose baked in then dangle a bone length off the joint.
        warnings.append(
            "{0} Advanced Skeleton limb(s) switched to FK to follow the "
            "streamed pose; raise their FKIK properties to hand them back "
            "to the Blender IK controls.".format(switched)
        )
    _refresh()
    return {
        "applied": applied,
        "unmatched": unmatched,
        "armatures": len(touched),
    }


def apply_root_motion(package_data, position_scale, warnings):
    """Key each root bone to its sampled Maya world truth, frame by frame.

    The FBX bake is only trustworthy for what was exported. Measured on the
    group above a skeleton: the exporter's own FBX turns that group into the
    armature *object* and folds the group's animCurves onto it -- with the
    key shape flattened to linear -- while motion driven into the group by a
    connection, the way Advanced Skeleton's Main works, is folded at its
    static value and never arrives. The exporter therefore samples each root
    joint's evaluated world per frame, and this re-keys the root bone so the
    truth holds *whatever* FBX put on the object: the scene is stepped to
    each frame and the basis solved against the armature's evaluated world
    at that frame, so any object-level animation cancels out of the result
    instead of doubling it.
    """
    records = [
        record for record in
        (package_data.get("skeleton_root_motion") or [])
        if len(record.get("samples") or []) >= 2
    ]
    if not records:
        return 0

    bones = _bone_lookup(warnings)
    scene = bpy.context.scene
    original_frame = scene.frame_current
    keyed_bones = 0
    try:
        for record in records:
            name = str(record.get("joint") or "")
            found = bones.get(name)
            if found is None:
                warnings.append(
                    'Root motion for "{0}" matched no bone; that skeleton '
                    "keeps only its baked FBX animation.".format(name)
                )
                continue
            armature, pose_bone = found
            if _key_root_bone(scene, armature, pose_bone, record,
                              position_scale):
                keyed_bones += 1
    finally:
        scene.frame_set(original_frame)
    _refresh()
    return keyed_bones


def _key_root_bone(scene, armature, pose_bone, record, position_scale):
    """Write one bone's corrected keys. Returns success.

    The samples are the root joint's evaluated world per frame -- the
    complete truth, whatever drove it. It cannot be keyed onto the bone
    directly: measured, a production root bone sits a constant 90 degrees
    of roll from its Maya joint while both are correct, so the bone-axes
    convention ``R`` is calibrated first and rides on every frame::

        bone world(f) = mapped joint truth(f) @ R
        R = (mapped joint truth)^-1 @ mapped group truth @ baked pose
            ... at the exporter's reference frame

    That anchor is clean against both measured fold failures: a static fold
    holds exactly the reference frame's value, and a curve fold's
    linearization error lives on the armature object, which the anchor
    formula never reads. Wherever the bake was right the result is a no-op,
    so nothing is ever applied twice.

    The armature world and the baked pose are read per frame BEFORE any key
    is inserted, because inserting one changes what the action evaluates to
    at the frames not yet re-keyed (FBX sometimes bakes sparse keys).
    """
    reference = record.get("reference") or {}
    ref_joint = reference.get("matrix") or []
    ref_group = reference.get("parent_matrix") or []
    if len(ref_joint) != 16 or len(ref_group) != 16:
        return False
    ref_frame = int(round(scalar(reference.get("frame"), 0.0)))
    scene.frame_set(ref_frame)
    _refresh()
    # The FBX made the skeleton's group the armature object, so the baked
    # pose matrix is the bone in the group's own frame; putting it under
    # the TRUE group world -- not the armature's possibly-wrong one --
    # is what keeps both fold failures out of the anchor.
    anchor = (_maya_world_matrix(ref_group, position_scale)
              @ pose_bone.matrix)
    axes = (_maya_world_matrix(ref_joint, position_scale).inverted_safe()
            @ anchor)

    frames = []
    for sample in record.get("samples") or []:
        matrix = sample.get("matrix") or []
        if len(matrix) != 16:
            continue
        frame = int(round(scalar(sample.get("frame"), 0.0)))
        scene.frame_set(frame)
        _refresh()
        frames.append((
            frame,
            _maya_world_matrix(matrix, position_scale),
            armature.matrix_world.copy(),
        ))
    if len(frames) < 2:
        return False

    euler_mode = pose_bone.rotation_mode not in ("QUATERNION", "AXIS_ANGLE")
    if pose_bone.rotation_mode == "AXIS_ANGLE":
        # Four floats with no continuity story; XYZ keys the same pose.
        pose_bone.rotation_mode = "XYZ"
        euler_mode = True
    rotation_path = ("rotation_euler" if euler_mode
                     else "rotation_quaternion")

    previous_rotation = None
    keyed = 0
    for frame, joint_world, armature_world in frames:
        world = joint_world @ axes
        target = armature_world.inverted_safe() @ world
        basis = _basis_for(pose_bone, target, {})
        location, rotation, scale = basis.decompose()
        pose_bone.location = location
        if euler_mode:
            euler = rotation.to_euler(pose_bone.rotation_mode)
            if previous_rotation is not None:
                # Keep this frame in the same turn as the last one.
                euler.make_compatible(previous_rotation)
            previous_rotation = euler.copy()
            pose_bone.rotation_euler = euler
        else:
            if (previous_rotation is not None
                    and previous_rotation.dot(rotation) < 0.0):
                # The same orientation with all four signs flipped
                # interpolates the long way round.
                rotation.negate()
            previous_rotation = rotation.copy()
            pose_bone.rotation_quaternion = rotation
        pose_bone.scale = scale
        try:
            pose_bone.keyframe_insert("location", frame=frame)
            pose_bone.keyframe_insert(rotation_path, frame=frame)
            pose_bone.keyframe_insert("scale", frame=frame)
        except Exception:
            return False
        keyed += 1
    if keyed < 2:
        return False

    # Linear, and only this bone's curves: the rest of the action belongs
    # to the FBX importer and is not this function's to restyle.
    prefix = 'pose.bones["{0}"].'.format(pose_bone.name)
    action = getattr(getattr(armature, "animation_data", None), "action",
                     None)
    for curve in action_fcurves(action):
        if not curve.data_path.startswith(prefix):
            continue
        for point in curve.keyframe_points:
            try:
                point.interpolation = ANIMATION_INTERPOLATION
            except Exception:
                break
    return True


def _park_ik_limbs(armature_names):
    """Set every AS FKIK property on the touched armatures to FK.

    Returns how many limbs were switched, so the caller can say so.
    """
    switched = 0
    for name in armature_names:
        armature = bpy.data.objects.get(name)
        if armature is None:
            continue
        for key in list(armature.keys()):
            if not str(key).startswith("FKIK_"):
                continue
            if scalar(armature.get(key), 0.0) > 0.0:
                switched += 1
            armature[key] = 0.0
        try:
            armature.update_tag()
        except Exception:
            pass
    return switched


def _bone_lookup(warnings):
    """Bone name to (armature, pose bone), across every scene armature.

    Names collide only across armatures -- Blender keeps them unique inside
    one -- and a collision is reported rather than silently resolved, because
    first-match is an arbitrary winner.
    """
    lookup = {}
    collisions = set()
    for obj in bpy.data.objects:
        if obj.type != "ARMATURE":
            continue
        for pose_bone in obj.pose.bones:
            if pose_bone.name in lookup:
                collisions.add(pose_bone.name)
                continue
            lookup[pose_bone.name] = (obj, pose_bone)
    if collisions:
        warnings.append(
            "{0} bone name(s) exist on more than one armature; the first "
            "match was posed. First: {1}".format(
                len(collisions), sorted(collisions)[0]
            )
        )
    return lookup


def _pose_space_target(armature, values, position_scale):
    """A Maya world matrix as a Blender pose-space (armature-local) matrix.

    The same world mapping the rest of the tool uses -- (x, y, z) to
    (x, -z, y) -- applied to the full basis with the joint's own scale kept:
    stripping it would freeze squash-and-stretch.

    The unit scale multiplies the **whole matrix**, not the translation
    alone. Measured on a production rig: the FBX importer expresses its
    centimetre conversion in the bone frames -- every rest-chain world matrix
    carries a uniform 0.01 -- so a target whose basis stayed at scale one
    disagreed with the rest pose by a factor of a hundred, and the bind pose
    came back with a basis of scale 100 on the root instead of identity.

    Going back through ``matrix_world.inverted()`` then unwinds both the
    armature object's transform and that unit scale, which is what makes the
    result comparable with the rest matrices.
    """
    world = _maya_world_matrix(values, position_scale)
    return armature.matrix_world.inverted_safe() @ world


def _maya_world_matrix(values, position_scale):
    """A Maya xform world matrix as a Blender-space world matrix."""
    rows = [values[0:4], values[4:8], values[8:12], values[12:16]]
    # Maya's xform matrix is row-major with basis vectors in rows;
    # mathutils wants rows of the mathematical matrix, so transpose.
    maya = Matrix((
        (rows[0][0], rows[1][0], rows[2][0], rows[3][0]),
        (rows[0][1], rows[1][1], rows[2][1], rows[3][1]),
        (rows[0][2], rows[1][2], rows[2][2], rows[3][2]),
        (0.0, 0.0, 0.0, 1.0),
    ))
    axes = Matrix((
        (1.0, 0.0, 0.0, 0.0),
        (0.0, 0.0, -1.0, 0.0),
        (0.0, 1.0, 0.0, 0.0),
        (0.0, 0.0, 0.0, 1.0),
    ))
    return Matrix.Scale(position_scale, 4) @ axes @ maya


def _basis_for(pose_bone, target, targets):
    """The matrix_basis that puts a constraint-free bone at ``target``.

    Blender evaluates a plain bone as::

        pose = parent_pose @ (parent_rest.inverted() @ rest) @ basis

    Solved for basis against the parent's *target* pose rather than its
    current evaluated one, so a whole skeleton poses in one pass. A parent
    the message did not carry falls back to its current pose matrix.
    """
    rest = pose_bone.bone.matrix_local
    parent = pose_bone.parent
    if parent is None:
        return rest.inverted_safe() @ target
    parent_key = (pose_bone.id_data.name, parent.name)
    parent_pose = targets.get(parent_key, parent.matrix)
    chain = parent_pose @ (parent.bone.matrix_local.inverted_safe() @ rest)
    return chain.inverted_safe() @ target


def _refresh():
    """One depsgraph pass so the pose is visible without a user nudge."""
    try:
        bpy.context.view_layer.update()
    except Exception:
        pass
