# -*- coding: utf-8 -*-
"""Maya's particle instancer: geometry placed on points.

Nothing looked for this node, so an instancer and everything it placed
vanished from the package without a word -- the same silent loss that hid
instances, locators, curves, volumes and particles before it.

The wiring was read from a live Maya 2023 session rather than guessed:

    instancer1.inputPoints       <- <particleShape>.instanceData[0]...
    instancer1.inputHierarchy[n] <- <sourceTransform>.matrix

So the points come from a particle shape the exporter already carries, and
the sources are ordinary transforms connected by their matrix plug. An
instancer is itself a DAG node and sits at the top level with no parent.
"""
from __future__ import absolute_import

import maya.cmds as cmds

from .mayautils import node_label, parent_of, unique, world_matrix
from .meshes import expanded_selection, group_path

INSTANCER_NODE_TYPE = "instancer"
INSTANCER_POINTS_ATTR = "inputPoints"
INSTANCER_SOURCES_ATTR = "inputHierarchy"


def scene_instancers(selected_only=False):
    try:
        nodes = cmds.ls(type=INSTANCER_NODE_TYPE, long=True) or []
    except Exception:
        return []
    if selected_only:
        allowed = set(expanded_selection())
        nodes = [node for node in nodes if node in allowed]
    return unique(nodes)


def instancer_points(node):
    """The particle transform whose points this instancer places on.

    The connection arrives from the particle *shape*, so the transform is
    taken from it: that is the path the importer's particle records are
    keyed by, and matching shape to transform later would be guesswork.
    """
    try:
        sources = cmds.listConnections(
            node + "." + INSTANCER_POINTS_ATTR,
            source=True, destination=False, shapes=True,
        ) or []
    except Exception:
        return ""
    for source in sources:
        full = (cmds.ls(source, long=True) or [source])[0]
        return parent_of(full) or full
    return ""


def instancer_sources(node):
    """Transforms wired into inputHierarchy, in slot order."""
    try:
        found = cmds.listConnections(
            node + "." + INSTANCER_SOURCES_ATTR,
            source=True, destination=False,
        ) or []
    except Exception:
        return []
    paths = []
    for item in found:
        resolved = cmds.ls(item, long=True) or []
        if resolved:
            paths.append(resolved[0])
    return unique(paths)


def instancer_record(node):
    full_name = node_label(node)
    sources = instancer_sources(node)
    return {
        "instancer": full_name,
        "instancer_path": node,
        "points_path": instancer_points(node),
        "sources": sources,
        "source_count": len(sources),
        "groups": group_path(node),
        "world_matrix": world_matrix(node),
    }


def instancer_records(nodes):
    return [instancer_record(node) for node in nodes]
