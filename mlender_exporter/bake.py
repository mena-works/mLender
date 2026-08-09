# -*- coding: utf-8 -*-
"""Bake procedural shading networks to image files.

The tool normally ships the original texture path and rebuilds the material
around it, which cannot work when a channel is driven by a network with no
file behind it at all: a checker, a ramp, layered noise. Those are baked to
the mesh's UVs so Blender has something to load.

Measured facts shape this module, all from a live Maya 2023 session:

* convertSolidTx writes **linear** values into the image regardless of colour
  management, so a baked map must be read as Non-Color in Blender even when it
  drives a colour channel. Loading it as sRGB would darken every bake.
* It cannot write EXR. The file node is created pointing at the path but
  nothing lands on disk, so the format list here is deliberately short.
* UV sets need no handling here, which was measured rather than hoped: the
  bake evaluates the network through its own ``uvLink``, and writes into the
  mesh's **default** set whatever the current one is. Blender activates that
  same first layer, so a procedural authored on a second UV set is resolved
  during the bake and lands right. Passing ``uvSetName`` would change where it
  writes -- and a name the mesh does not carry raises -- so it stays unset.
"""
from __future__ import absolute_import

import os

import maya.cmds as cmds

from .constants import (
    BAKE_BACKGROUND_MODE,
    BAKE_FILE_FORMAT,
    BAKE_SEMANTIC,
    DEFAULT_BAKE_RESOLUTION,
    MAX_BAKE_RESOLUTION,
    SCALAR_BAKE_CHANNELS,
)
from .mayautils import maya_path, node_label, without_namespace


class BakeContext(object):
    """Everything a bake needs that a shader on its own cannot know.

    The mesh supplies the UVs, the folder is inside the package being written,
    and the cache stops a material shared across ten meshes being baked ten
    times.
    """

    def __init__(self, folder, resolution=None, enabled=True, warnings=None):
        self.folder = folder
        self.resolution = _clamp_resolution(resolution)
        self.enabled = bool(enabled)
        self.warnings = warnings if warnings is not None else []
        self.mesh = ""
        self.cache = {}
        self.baked_files = []

    def for_mesh(self, mesh_transform):
        self.mesh = mesh_transform or ""
        return self


def _clamp_resolution(value):
    try:
        resolution = int(value)
    except (TypeError, ValueError):
        resolution = DEFAULT_BAKE_RESOLUTION
    return max(16, min(MAX_BAKE_RESOLUTION, resolution))


def bake_channel(context, shader, channel, source_plug):
    """Bake one channel's network and return a texture record, or None.

    Returns None whenever baking is impossible rather than raising, because a
    material that cannot be baked should still export with its flat values.
    """
    if context is None or not context.enabled or not source_plug:
        return None
    if not context.mesh:
        return None

    key = (shader, channel)
    if key in context.cache:
        return context.cache[key]

    path = _bake_plug(context, shader, channel, source_plug)
    record = None
    if path:
        record = {
            "path": maya_path(path),
            "baked": True,
            "baked_from": source_plug,
            "baked_resolution": context.resolution,
            # Measured: the written values are linear, so the importer must
            # not apply an sRGB decode on the way in.
            "linear": True,
            "color_space": "Raw",
            "semantic": BAKE_SEMANTIC,
        }
        context.baked_files.append(path)
    context.cache[key] = record
    return record


def _bake_plug(context, shader, channel, source_plug):
    if not os.path.isdir(context.folder):
        try:
            os.makedirs(context.folder)
        except Exception as exc:
            context.warnings.append(
                "Bake folder could not be created: {0}".format(exc)
            )
            return ""

    filename = "{0}_{1}.{2}".format(
        _safe_name(without_namespace(node_label(shader))),
        _safe_name(channel),
        BAKE_FILE_FORMAT,
    )
    target = os.path.join(context.folder, filename).replace("\\", "/")

    before = set(cmds.ls(type="file") or [])
    created = []
    try:
        cmds.convertSolidTx(
            source_plug,
            context.mesh,
            fileImageName=target,
            fileFormat=BAKE_FILE_FORMAT,
            resolutionX=context.resolution,
            resolutionY=context.resolution,
            samplePlane=False,
            antiAlias=True,
            backgroundMode=BAKE_BACKGROUND_MODE,
            fillTextureSeams=True,
            alpha=channel in SCALAR_BAKE_CHANNELS,
            force=True,
        )
        created = [
            node for node in (cmds.ls(type="file") or []) if node not in before
        ]
    except Exception as exc:
        context.warnings.append(
            'Could not bake "{0}" on {1}: {2}'.format(channel, shader, exc)
        )
        target = ""
    finally:
        # convertSolidTx leaves a file node wired into the scene. The export
        # must not change the user's scene, so it goes away again.
        for node in created:
            try:
                cmds.delete(node)
            except Exception:
                pass

    if target and not os.path.isfile(target):
        context.warnings.append(
            'Bake of "{0}" on {1} produced no file.'.format(channel, shader)
        )
        return ""
    return target


def _safe_name(value):
    text = "".join(
        character if character.isalnum() or character in "-_" else "_"
        for character in str(value or "")
    )
    return text.strip("_") or "channel"
