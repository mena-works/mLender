# -*- coding: utf-8 -*-
"""A native Blender control layer for Advanced Skeleton characters.

Built from the manifest the exporter read out of AS's own declarations, so
nothing here guesses at the rig's structure:

* FK posing already exists -- the deform bones *are* the FK controls, mapped
  by name -- so the FK work is dressing: each imported FK control curve
  becomes its bone's custom shape and the stray curve object is hidden.
* The declared limb chains get a real Blender IK constraint. The imported
  ``IK<Limb>_<Side>`` and ``Pole<Limb>_<Side>`` curves are promoted into the
  live target and pole objects, so the animator grabs the same controls AS
  gave them.
* A per-limb ``FKIK_<Limb>_<Side>`` property on the armature stands in for
  AS's ``FKIKBlend``, driving the constraint influences.

Two things were measured before this was written, and both shape the code:

* An AS limb chain is **not** a direct parent chain -- twist ``Part`` joints
  sit between (``Wrist_L``'s parent is ``ElbowPart1_L``). The constraint
  therefore walks the real parent chain and locks IK on every in-between
  bone, so the solve bends only at the declared start and middle, the same
  two joints Maya's solver bends.
* Blender's ``pole_angle`` is calibrated, not assumed: with the constraint
  live and the controls at rest, the angle that keeps the middle bone at its
  rest position is found by scanning. IK at rest must be a no-op, and the
  scan makes that property hold by construction instead of by luck.
"""

import math

import bpy

from .utils import scalar


FKIK_PROPERTY = "FKIK_{0}_{1}"
LOCKED_AXES = ("lock_ik_x", "lock_ik_y", "lock_ik_z")


def build_as_rig(package_data, warnings):
    """Dress and wire the AS control layer. Returns counts for the report."""
    record = package_data.get("as_rig") or {}
    if not record.get("detected"):
        return {"as_fk_shapes": 0, "as_ik_chains": 0}

    armature = _armature_for(record)
    if armature is None:
        warnings.append(
            "The package declares an Advanced Skeleton rig but no imported "
            "armature carries its joints; the control layer was not built."
        )
        return {"as_fk_shapes": 0, "as_ik_chains": 0}

    shapes = _dress_fk_bones(armature, record.get("fk_controls") or [],
                             warnings)
    walks = {}
    for chain in record.get("chains") or []:
        walk = _chain_walk(armature, chain, warnings)
        if walk:
            walks[chain.get("switch") or str(len(walks))] = (chain, walk)
    # One edit-mode pass for every chain at once: the FBX importer builds
    # bones as disconnected sticks whose tails do not sit on the next joint,
    # and no IK effector on such a chain can coincide with the end joint --
    # measured, the best any constraint arrangement reached was one full
    # bone length of rest error. Pointing each chain bone's tail at the next
    # bone's head makes the classic solve geometrically true, and costs the
    # skin nothing because the pose is the rest pose while it happens.
    _retail_chains(armature, [walk for _c, walk in walks.values()])
    chains = 0
    for chain, walk in walks.values():
        if _build_chain(armature, chain, walk, warnings):
            chains += 1
    _refresh()
    return {"as_fk_shapes": shapes, "as_ik_chains": chains}


def _chain_walk(armature, chain, warnings):
    """Bone names from the end joint up to the start, or None to skip."""
    bones = armature.pose.bones
    if not all(bones.get(chain.get(key) or "")
               for key in ("start", "middle", "end")):
        warnings.append(
            'Advanced Skeleton chain "{0}" names joints the armature does '
            "not carry; skipped.".format(chain.get("switch") or "?")
        )
        return None
    walk = []
    node = bones[chain["end"]]
    while node is not None:
        walk.append(node.name)
        if node.name == chain["start"]:
            break
        node = node.parent
    if not walk or walk[-1] != chain["start"]:
        warnings.append(
            'Advanced Skeleton chain "{0}" is not a connected bone chain in '
            "the armature; skipped.".format(chain.get("switch") or "?")
        )
        return None
    return walk


def _retail_chains(armature, walks):
    """Point every chain bone's tail at the next bone's head, in one pass.

    Pose bone references die when edit mode is toggled, which is why this
    takes names and why the callers re-fetch their bones afterwards.
    """
    if not walks:
        return
    previous_active = bpy.context.view_layer.objects.active
    try:
        bpy.context.view_layer.objects.active = armature
        bpy.ops.object.mode_set(mode="EDIT")
        edit_bones = armature.data.edit_bones
        for walk in walks:
            # walk runs end-first; the parent's tail goes to the child's head.
            for child_name, parent_name in zip(walk[:-1], walk[1:]):
                child = edit_bones.get(child_name)
                parent = edit_bones.get(parent_name)
                if child is None or parent is None:
                    continue
                parent.tail = child.head
        bpy.ops.object.mode_set(mode="OBJECT")
    except Exception:
        try:
            bpy.ops.object.mode_set(mode="OBJECT")
        except Exception:
            pass
    finally:
        try:
            bpy.context.view_layer.objects.active = previous_active
        except Exception:
            pass


def _armature_for(record):
    wanted = set(record.get("deform_set") or [])
    if not wanted:
        return None
    best = None
    best_hits = 0
    for obj in bpy.data.objects:
        if obj.type != "ARMATURE":
            continue
        hits = len(wanted.intersection(set(obj.pose.bones.keys())))
        if hits > best_hits:
            best, best_hits = obj, hits
    # Half the declared skeleton is the floor: below that the armature is
    # something else that happens to share a few names.
    if best_hits * 2 < len(wanted):
        return None
    return best


def _dress_fk_bones(armature, pairs, warnings):
    """The FK curves become custom shapes; the stray curve objects hide."""
    dressed = 0
    missing = 0
    for pair in pairs:
        bone = armature.pose.bones.get(pair.get("joint") or "")
        curve = bpy.data.objects.get(pair.get("control") or "")
        if bone is None or curve is None or curve.type != "CURVE":
            missing += 1
            continue
        bone.custom_shape = curve
        # The bone sits where the joint is and the curve was modelled around
        # that same spot in world space, so the shape must not inherit the
        # bone's length as a scale.
        try:
            bone.use_custom_shape_bone_size = False
        except AttributeError:
            pass
        curve.hide_viewport = True
        curve.hide_render = True
        dressed += 1
    if missing:
        warnings.append(
            "{0} Advanced Skeleton FK control(s) had no matching bone or "
            "curve after import; those bones pose without their "
            "silhouette.".format(missing)
        )
    return dressed


def _build_chain(armature, chain, walk, warnings):
    """One declared limb: IK constraint, live targets, FK/IK property.

    ``walk`` is the end-first list of bone names the chains were re-tailed
    along; the pose bones are fetched fresh here because the edit-mode pass
    invalidated every earlier reference.
    """
    bones = armature.pose.bones
    start = bones.get(chain.get("start") or "")
    middle = bones.get(chain.get("middle") or "")
    end = bones.get(chain.get("end") or "")
    if start is None or middle is None or end is None or len(walk) < 2:
        return False

    target = _promote_control(chain.get("ik_control"))
    pole = _promote_control(chain.get("pole_control"))
    if target is None:
        warnings.append(
            'Advanced Skeleton chain "{0}" has no imported IK control curve '
            "to use as a target; skipped.".format(chain.get("switch") or "?")
        )
        return False

    # After re-tailing, the classic arrangement is geometrically true: the
    # bone above the end joint has its tail exactly on that joint, so it
    # carries the constraint and its tail is the effector. Only the declared
    # start and middle may bend -- the two joints Maya's solver bends --
    # and every in-between twist bone goes rigid.
    holder = bones[walk[1]]
    for name in walk[1:]:
        node = bones[name]
        if node not in (start, middle):
            for axis in LOCKED_AXES:
                try:
                    setattr(node, axis, True)
                except AttributeError:
                    pass

    constraint = holder.constraints.new(type="IK")
    constraint.name = "ML_AS_IK"
    constraint.target = target
    constraint.chain_count = len(walk) - 1
    if pole is not None:
        constraint.pole_target = pole
        constraint.pole_angle = _calibrated_pole_angle(
            armature, constraint, end
        )

    # The wrist follows the IK control's orientation the way AS's does.
    follow = end.constraints.new(type="COPY_ROTATION")
    follow.name = "ML_AS_IK_Rotation"
    follow.target = target

    prop = FKIK_PROPERTY.format(chain.get("limb") or "Limb",
                                chain.get("side") or "X")
    # AS's blend runs 0..10 with 10 as IK; the property is 0..1 of IK.
    # An animated package parks the limb in FK regardless: the baked action
    # is the evaluated truth and the IK targets sit still at bind, so a live
    # constraint corrupts the animation -- measured, 1.3 cm of error on the
    # first frame of a 3 cm character before anything even moved.
    if armature.animation_data and armature.animation_data.action:
        armature[prop] = 0.0
    else:
        armature[prop] = min(max(scalar(chain.get("blend"), 10.0) / 10.0,
                                 0.0), 1.0)
    for driven in (constraint, follow):
        _drive_influence(armature, driven, prop)
    return True


def _promote_control(name):
    """The imported control curve, made a live, grabbable target."""
    if not name:
        return None
    obj = bpy.data.objects.get(name)
    if obj is None:
        return None
    obj.hide_viewport = False
    obj.hide_render = True
    return obj


def _calibrated_pole_angle(armature, constraint, probe_bone):
    """The pole angle that keeps the chain at rest, found by measuring.

    With target and pole sitting at their bind positions, the correct angle
    reproduces the rest pose exactly. Rather than deriving it from bone roll
    conventions -- which shift between importers -- every candidate is tried
    and the one that moves the probe bone (the end joint) the least wins: a
    coarse sweep, then a fine one around the best coarse answer.
    """
    rest = (armature.matrix_world @ probe_bone.bone.matrix_local).translation
    view = bpy.context.view_layer

    def deviation(angle):
        constraint.pole_angle = angle
        view.update()
        head = (armature.matrix_world @ probe_bone.matrix).translation
        return (head - rest).length

    best = min((deviation(math.radians(a)), math.radians(a))
               for a in range(-180, 180, 15))
    fine = min((deviation(best[1] + math.radians(step)),
                best[1] + math.radians(step))
               for step in range(-14, 15, 2))
    constraint.pole_angle = fine[1]
    view.update()
    return fine[1]


def _drive_influence(armature, constraint, prop):
    """Constraint influence follows the armature's FK/IK property."""
    try:
        curve = constraint.driver_add("influence")
    except Exception:
        return
    driver = curve.driver
    driver.type = "AVERAGE"
    variable = driver.variables.new()
    variable.name = "fkik"
    variable.type = "SINGLE_PROP"
    target = variable.targets[0]
    target.id = armature
    target.data_path = '["{0}"]'.format(prop)


def _refresh():
    try:
        bpy.context.view_layer.update()
    except Exception:
        pass
