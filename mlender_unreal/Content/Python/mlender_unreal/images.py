# -*- coding: utf-8 -*-
"""Texture import.

One texture file becomes one Texture2D asset, reused by every channel and
every material that references it. The cache is keyed by resolved path, not by
channel, because the same file driving two channels is one asset -- the Blender
receiver learned to copy a shared texture once and the same applies here.
"""

import os

import unreal

from .constants import TEXTURE_CONTENT_PATH
from .utils import resolve_recorded_path, safe_asset_name


_cache = {}


def reset_cache():
    _cache.clear()


def _import_texture_asset(path, warnings):
    name = safe_asset_name(os.path.splitext(os.path.basename(path))[0], "Tex")
    destination = "{0}/{1}".format(TEXTURE_CONTENT_PATH, name)
    if unreal.EditorAssetLibrary.does_asset_exist(destination):
        existing = unreal.EditorAssetLibrary.load_asset(destination)
        if existing is not None:
            return existing

    task = unreal.AssetImportTask()
    task.filename = path
    task.destination_path = TEXTURE_CONTENT_PATH
    task.destination_name = name
    task.automated = True
    task.replace_existing = True
    task.save = False
    unreal.AssetToolsHelpers.get_asset_tools().import_asset_tasks([task])

    for imported in task.imported_object_paths or []:
        asset = unreal.EditorAssetLibrary.load_asset(imported)
        if isinstance(asset, unreal.Texture):
            return asset
    warnings.append('Texture "{0}" could not be imported.'.format(path))
    return None


def load_texture(record, package_folder, channel, colour_data, warnings):
    """A Texture2D for a channel record, or None.

    ``colour_data`` decides sRGB and the compression setting. A normal map is
    recognised by its channel rather than by its filename, because a name is a
    convention and the channel is what the shader asked for.
    """
    texture = (record or {}).get("texture") or {}
    raw_path = str(texture.get("path") or "").strip()
    if not raw_path:
        return None
    path, _repointed = resolve_recorded_path(raw_path, package_folder)
    if not os.path.isfile(path):
        warnings.append(
            'Texture "{0}" was not found on disk, so the channel "{1}" kept '
            "its flat value.".format(raw_path, channel)
        )
        return None

    if "<UDIM>" in path or "<udim>" in path:
        warnings.append(
            'Texture "{0}" is a UDIM set; this build imports Unreal textures '
            "one file at a time, so the channel \"{1}\" arrived without "
            "tiling.".format(raw_path, channel)
        )
        return None

    key = os.path.normcase(os.path.abspath(path))
    if key in _cache:
        return _cache[key]

    asset = _import_texture_asset(path, warnings)
    if asset is not None:
        _configure_texture(asset, channel, colour_data)
    _cache[key] = asset
    return asset


def _configure_texture(asset, channel, colour_data):
    """sRGB and compression, set explicitly rather than left to the importer.

    Unreal guesses from the filename and the bit depth, and a guess that is
    right most of the time is exactly what silently darkens the exceptions --
    a baked map is linear even when it feeds a colour channel.
    """
    try:
        if channel == "normal":
            asset.set_editor_property(
                "compression_settings",
                unreal.TextureCompressionSettings.TC_NORMALMAP,
            )
            asset.set_editor_property("srgb", False)
            return
        asset.set_editor_property("srgb", bool(colour_data))
        if not colour_data:
            asset.set_editor_property(
                "compression_settings",
                unreal.TextureCompressionSettings.TC_MASKS,
            )
    except Exception:
        # A texture that refuses a setting is still a usable texture; the
        # channel is worth more than the setting.
        pass
