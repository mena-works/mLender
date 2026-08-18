# -*- coding: utf-8 -*-
"""NURBS surfaces and Maya subdivision surfaces, as temporary polygon meshes.

Discovery starts at ``ls(type="mesh")``, so neither of these was ever exported.
``coverage.py`` reports them, which stopped the loss being silent, but reporting
is not carrying: product and industrial modelling scenes are largely NURBS, and
old assets are full of them.

Three routes were measured before this one was written:

* **Let the FBX carry it.** It does -- and it comes back a ``nurbsSurface``,
  not a mesh, so no receiver sees geometry. A Maya subdivision surface does not
  survive the round trip at all.
* **Rebuild natively in the receiver.** Blender has NURBS surfaces, but they
  cannot represent a trimmed one, and trims are most of why anybody models in
  NURBS. Half an answer.
* **Tessellate to polygons during the export**, which is what this does.

The scene is modified and put back. That is not the thing the forbidden list
means: the rule is against leaving a change behind, and the bake path already
creates and removes nodes the same way. Everything here happens inside a
context whose cleanup runs in a ``finally``, so a failed export leaves the
scene as it found it -- including the original names, which are borrowed so the
tessellated stand-in can carry them into the package.
"""
from __future__ import absolute_import

import maya.cmds as cmds

from .constants import TESSELLATION_SUFFIX
from .mayautils import node_label


NURBS_SHAPE_TYPE = "nurbsSurface"
SUBDIV_SHAPE_TYPE = "subdiv"


def _parent_of(node):
    parents = cmds.listRelatives(node, parent=True, fullPath=True) or []
    return parents[0] if parents else ""


def _shapes(shape_type):
    """Renderable shapes of a type, skipping the intermediate ones."""
    found = []
    for shape in cmds.ls(type=shape_type, long=True) or []:
        try:
            if cmds.getAttr(shape + ".intermediateObject"):
                continue
        except Exception:
            pass
        if _parent_of(shape):
            found.append(shape)
    return found


def _convert(shape, shape_type):
    """One shape to a polygon transform, or "" if Maya refuses.

    nurbsToPoly's quad format honours trims, which is the whole reason this is
    not a native rebuild in the receiver.
    """
    try:
        if shape_type == NURBS_SHAPE_TYPE:
            created = cmds.nurbsToPoly(
                shape,
                constructionHistory=False,
                format=2,
                polygonType=1,
                useChordHeightRatio=False,
                uType=3, uNumber=8,
                vType=3, vNumber=8,
            ) or []
        else:
            created = cmds.subdToPoly(
                shape, constructionHistory=False, applyMatrixToResult=True
            ) or []
    except Exception:
        return ""
    for node in created:
        if cmds.objExists(node):
            return cmds.ls(node, long=True)[0]
    return ""


def tessellate_scene(warnings=None):
    """Stand-in polygon meshes for every NURBS and subdivision surface.

    Returns a context to hand to :func:`restore`. The stand-in takes the
    original's parent and its name, so it lands in the right group with the
    right identity and every later pass -- materials, sets, coverage -- treats
    it as the mesh it is standing in for.
    """
    if warnings is None:
        warnings = []
    context = {"entries": []}
    # nurbsToPoly and subdToPoly leave their output selected, which silently
    # replaced the user's selection: measured, a selected-only export then
    # carried a tessellated surface nobody had picked. The selection is put
    # back at the end, with one substitution -- a surface that *was* selected
    # is represented by its stand-in, or selecting a NURBS surface and asking
    # for the selection would export nothing.
    try:
        selection = cmds.ls(selection=True, long=True) or []
    except Exception:
        selection = []

    for shape_type in (NURBS_SHAPE_TYPE, SUBDIV_SHAPE_TYPE):
        for shape in _shapes(shape_type):
            transform = _parent_of(shape)
            if not transform:
                continue
            original_label = node_label(transform).split("|")[-1]
            stand_in = _convert(shape, shape_type)
            if not stand_in:
                warnings.append(
                    '{0} "{1}" could not be converted to polygons, so it did '
                    "not travel.".format(shape_type, original_label)
                )
                continue

            parent = _parent_of(transform)
            if parent:
                try:
                    stand_in = cmds.ls(
                        cmds.parent(stand_in, parent)[0], long=True
                    )[0]
                except Exception:
                    pass

            # The original steps aside so the stand-in can take its name. The
            # name is what the receivers match and rename on, so borrowing it
            # is what makes a tessellated surface arrive as itself rather than
            # as something called nurbsBall_mlTess.
            renamed = ""
            try:
                renamed = cmds.rename(
                    transform, original_label + TESSELLATION_SUFFIX
                )
                stand_in = cmds.ls(
                    cmds.rename(stand_in, original_label), long=True
                )[0]
            except Exception as exc:
                warnings.append(
                    '{0} "{1}" was converted but could not take its name: '
                    "{2}".format(shape_type, original_label, exc)
                )

            context["entries"].append({
                "original": renamed,
                "original_label": original_label,
                "stand_in": stand_in,
                "shape_type": shape_type,
            })

    if selection:
        restored_selection = []
        for node in selection:
            # The original has been renamed by now, so the selection's old
            # long name no longer resolves; match on the label instead.
            swapped = None
            for entry in context["entries"]:
                if node.split("|")[-1] == entry["original_label"]:
                    swapped = entry["stand_in"]
                    break
            restored_selection.append(swapped or node)
        try:
            cmds.select(
                [node for node in restored_selection if cmds.objExists(node)],
                replace=True,
            )
        except Exception:
            pass
    else:
        try:
            cmds.select(clear=True)
        except Exception:
            pass

    if context["entries"]:
        warnings.append(
            "{0} NURBS or subdivision surface(s) were tessellated to polygons "
            "for the export: {1}. They arrive as meshes, which is what every "
            "receiver can read; the originals are untouched in Maya.".format(
                len(context["entries"]),
                ", ".join(
                    entry["original_label"] for entry in context["entries"][:6]
                ),
            )
        )
    return context


def restore(context):
    """Delete the stand-ins and give the originals their names back.

    Runs from a finally, so it has to survive anything: a node already gone, a
    rename that cannot happen, a scene somebody closed. Each step is guarded on
    its own rather than the whole loop, or one bad entry would leave the rest
    of the scene renamed.
    """
    if not context:
        return 0
    restored = 0
    for entry in context.get("entries") or []:
        stand_in = entry.get("stand_in")
        try:
            if stand_in and cmds.objExists(stand_in):
                cmds.delete(stand_in)
        except Exception:
            pass
        original = entry.get("original")
        try:
            if original and cmds.objExists(original):
                cmds.rename(original, entry.get("original_label"))
                restored += 1
        except Exception:
            pass
    return restored
