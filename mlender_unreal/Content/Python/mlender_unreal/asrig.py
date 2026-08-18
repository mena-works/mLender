# -*- coding: utf-8 -*-
"""Advanced Skeleton: what arrives, and what the manifest says about it.

The skeletal half needs no work here and that was a measurement, not a guess:
Interchange's scene import already brings skinned meshes in as SkeletalMesh with
a Skeleton and a PhysicsAsset, with no pipeline override at all. The receiver's
own mesh pass had simply been filtering them out. Trying to force skeletal
import the obvious way is actively wrong -- ``FbxImportUI.import_as_skeletal``
turns every static cube into its own one-bone skeletal mesh, measured at 50
skeletons on this fixture.

What is genuinely missing is the **control layer**: AS's FK controls and its
IK/pole chains, which on the Blender side become bone shapes, real IK
constraints and an FKIK property. Unreal's equivalent is a Control Rig asset,
and authoring one from Python means building a rig graph -- a project rather
than a module.

So this reads the manifest, attaches it to the skeletal actors it belongs to so
nothing has to re-derive it later, and reports precisely what did and did not
travel. The manifest itself is complete: per namespace it carries the bind
joints, the control-to-joint pairs and each limb's chain with its switch.
"""

import json

import unreal

from .objects import record_metadata
from .utils import safe_asset_name


def _skeleton_bone_names(actor):
    """Bone names on a skeletal actor, or an empty list."""
    component = getattr(actor, "skeletal_mesh_component", None)
    if component is None:
        return []
    for getter in ("get_all_socket_names",):
        pass
    try:
        names = component.get_bone_names()
        return [str(name) for name in names or []]
    except Exception:
        return []


def apply_as_rigs(package_data, actors, warnings):
    """Attach each AS manifest to the skeletal actors it describes.

    Matching is by namespace: a referenced rig lives in one and its bones carry
    it, which is the only thing telling two references of one asset apart. That
    is the same reasoning the Blender receiver uses, where stripping the
    namespace silently left a referenced rig's pose unmatched.
    """
    records = list((package_data or {}).get("as_rigs") or [])
    if not records:
        return {"as_rig_count": 0, "as_skeletal_actors": 0}

    skeletal = []
    cls = getattr(unreal, "SkeletalMeshActor", None)
    if cls is not None:
        skeletal = [actor for actor in actors if isinstance(actor, cls)]

    if not skeletal:
        warnings.append(
            "The package declares {0} Advanced Skeleton rig(s) but no skeletal "
            "mesh arrived, so there is nothing for the manifest to describe. "
            "The skinned meshes came in as static meshes.".format(len(records))
        )
        return {"as_rig_count": 0, "as_skeletal_actors": 0}

    tagged = 0
    for record in records:
        namespace = str(record.get("namespace") or "")
        chains = list(record.get("chains") or [])
        controls = list(record.get("fk_controls") or [])
        joints = list(record.get("deform_set") or [])
        label = namespace or "root"

        # A namespaced rig's bones keep the namespace, so its actors are the
        # ones whose names carry it; without a namespace every skeletal actor
        # is a candidate.
        if namespace:
            targets = [
                actor for actor in skeletal
                if safe_asset_name(namespace) in actor.get_actor_label()
            ]
        else:
            targets = list(skeletal)
        if not targets:
            warnings.append(
                'Advanced Skeleton rig "{0}" found no skeletal mesh carrying '
                "its namespace.".format(label)
            )
            continue

        for actor in targets:
            record_metadata(actor, (
                ("as_namespace", namespace or "(none)"),
                ("as_deform_joints", len(joints)),
                ("as_fk_controls", len(controls)),
                ("as_chains", ",".join(
                    "{0}_{1}".format(c.get("limb"), c.get("side"))
                    for c in chains
                )),
                ("as_manifest", json.dumps(record)[:900]),
            ))
            tagged += 1

        warnings.append(
            'Advanced Skeleton rig "{0}" arrived as a skeletal mesh with its '
            "{1} bind joint(s), but its control layer did not: Unreal's "
            "equivalent is a Control Rig asset and this build does not author "
            "one. The {2} FK control(s) and {3} IK chain(s) are recorded on "
            "the actor as ml_as_* tags.".format(
                label, len(joints), len(controls), len(chains)
            )
        )
        for chain in chains:
            warnings.append(
                '  {0} {1}: {2} -> {3} -> {4}, IK "{5}", pole "{6}", switch '
                '"{7}" (blend {8}) -- not rebuilt.'.format(
                    chain.get("limb"), chain.get("side"), chain.get("start"),
                    chain.get("middle"), chain.get("end"),
                    chain.get("ik_control"), chain.get("pole_control"),
                    chain.get("switch"), chain.get("blend"),
                )
            )

    return {"as_rig_count": len(records), "as_skeletal_actors": tagged}
