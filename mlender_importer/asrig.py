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
    """Dress and wire the AS control layer. Returns counts for the report.

    One package can carry several rigs -- referenced characters each live in
    their own namespace, and FBX brings the namespace into the bone names
    verbatim, so the records' qualified names match the armatures directly.
    A package older than schema 43 carries a single record under "as_rig".
    """
    records = package_data.get("as_rigs")
    if records is None:
        legacy = package_data.get("as_rig") or {}
        records = [legacy] if legacy else []
    records = [r for r in records if r.get("detected")]

    totals = {"as_fk_shapes": 0, "as_ik_chains": 0}
    # Two rigs can land in one armature (FBX groups skeletons as it likes),
    # so manifests merge per armature rather than overwrite.
    manifests = {}
    for record in records:
        counts = _build_one_rig(record, warnings, manifests)
        totals["as_fk_shapes"] += counts[0]
        totals["as_ik_chains"] += counts[1]
    for armature, manifest in manifests.values():
        armature["ml_as_rig"] = manifest
    if manifests:
        _refresh()
    return totals


def _build_one_rig(record, warnings, manifests):
    """Build one rig's layer; accumulate its manifest. Returns counts."""
    namespace = record.get("namespace") or ""
    armature = _armature_for(record)
    if armature is None:
        warnings.append(
            'The package declares an Advanced Skeleton rig ("{0}") but no '
            "imported armature carries its joints; that control layer was "
            "not built.".format(namespace.rstrip(":") or "scene")
        )
        return (0, 0)

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
    built = []
    for chain, walk in walks.values():
        if _build_chain(armature, chain, walk, warnings, namespace):
            chains += 1
            built.append(chain)
    # The manifest goes onto the armature itself, so the panel and the
    # selection helpers read what was actually built rather than re-deriving
    # it from names -- and so it survives a .blend save.
    _, manifest = manifests.setdefault(
        armature.name, (armature, {"chains": [], "fk_bones": []})
    )
    label_prefix = namespace.rstrip(":")
    for chain in built:
        limb = chain.get("limb") or ""
        side = chain.get("side") or ""
        manifest["chains"].append({
            "limb": limb,
            "side": side,
            "label": " ".join(p for p in (label_prefix, limb, side) if p),
            "start": chain.get("start") or "",
            "middle": chain.get("middle") or "",
            "end": chain.get("end") or "",
            "ik": chain.get("ik_control") or "",
            "pole": chain.get("pole_control") or "",
            "prop": fkik_property(namespace, limb, side),
        })
    manifest["fk_bones"].extend(
        pair.get("joint") or ""
        for pair in record.get("fk_controls") or []
        if armature.pose.bones.get(pair.get("joint") or "")
    )
    return (shapes, chains)


def fkik_property(namespace, limb, side):
    """Per-limb property name; the namespace keeps two rigs sharing one
    armature from fighting over FKIK_Arm_L."""
    return FKIK_PROPERTY.format(
        (namespace or "").replace(":", "_") + (limb or "Limb"),
        side or "X",
    )


def as_armatures():
    """Every armature carrying a built AS control layer."""
    return [obj for obj in bpy.data.objects
            if obj.type == "ARMATURE" and obj.get("ml_as_rig")]


def set_bone_selected(pose_bone, state):
    """Selection lives on Bone through 4.x and moved to PoseBone in 5.x.

    Measured: 4.1 has Bone.select and no PoseBone.select, 5.2 the reverse.
    """
    if hasattr(pose_bone, "select"):
        pose_bone.select = state
    else:
        pose_bone.bone.select = state


def bone_selected(pose_bone):
    if hasattr(pose_bone, "select"):
        return pose_bone.select
    return pose_bone.bone.select


def select_chain(armature, chain, extend=False):
    """Select one limb: its bones in pose data, its controls as objects.

    Kept free of operator context so it can be tested headless; the panel's
    operator is a thin wrapper. Accepts a plain dict or the IDPropertyGroup
    stored on the armature -- both answer .get(). Returns how many things
    were selected.
    """
    manifest_chain = chain
    count = 0
    if not extend:
        for bone in armature.pose.bones:
            set_bone_selected(bone, False)
    for key in ("start", "middle", "end"):
        bone = armature.pose.bones.get(manifest_chain.get(key) or "")
        if bone is not None:
            set_bone_selected(bone, True)
            count += 1
    for key in ("ik", "pole"):
        obj = bpy.data.objects.get(manifest_chain.get(key) or "")
        if obj is not None:
            try:
                obj.select_set(True)
                count += 1
            except Exception:
                pass
    try:
        bpy.context.view_layer.objects.active = armature
    except Exception:
        pass
    return count


def select_fk_bones(armature, extend=False):
    """Select every FK-dressed bone. Returns how many."""
    manifest = armature.get("ml_as_rig") or {}
    names = list(manifest.get("fk_bones") or [])
    if not extend:
        for bone in armature.pose.bones:
            set_bone_selected(bone, False)
    count = 0
    for name in names:
        bone = armature.pose.bones.get(str(name))
        if bone is not None:
            set_bone_selected(bone, True)
            count += 1
    try:
        bpy.context.view_layer.objects.active = armature
    except Exception:
        pass
    return count


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


def _build_chain(armature, chain, walk, warnings, namespace=""):
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

    prop = fkik_property(namespace, chain.get("limb"), chain.get("side"))
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
    try:
        armature.id_properties_ui(prop).update(
            min=0.0, max=1.0, soft_min=0.0, soft_max=1.0,
            description="0 = FK, 1 = IK (Advanced Skeleton FKIKBlend / 10)",
        )
    except Exception:
        pass
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
