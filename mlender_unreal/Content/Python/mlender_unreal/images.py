# -*- coding: utf-8 -*-
"""Texture import.

One texture file becomes one Texture2D asset, reused by every channel and
every material that references it. The cache is keyed by resolved path, not by
channel, because the same file driving two channels is one asset -- the Blender
receiver learned to copy a shared texture once and the same applies here.
"""

import os
import struct
import tempfile
import zlib

import unreal

from .constants import (
    ASSET_PREFIX,
    SOURCE_STAMP_TAG,
    TEXTURE_CONTENT_PATH,
)
from .utils import resolve_recorded_path, safe_asset_name


_cache = {}


def reset_cache():
    _cache.clear()


def _source_stamp(path):
    """The file's size and modification time, as one short string.

    Enough to notice a repaint without reading the file. A hash of the bytes
    would be surer and would cost a full read of every texture on every send,
    which is not a trade worth making for a map that is usually untouched.
    """
    try:
        info = os.stat(path)
    except OSError:
        return ""
    return "{0}:{1}".format(int(info.st_size), int(info.st_mtime))


def _is_current(asset, path, stamp):
    """Whether the standing asset was built from this file, as it is now.

    Two ways it can be stale, and both were reachable before this existed:

    - the file has been repainted. The asset is reused whenever one exists at
      the destination path, so a lookdev artist's new map never arrived; the
      old Texture2D was returned for the life of the project.
    - the asset came from a *different* file that happens to share a basename.
      The asset name is the file's stem, so two "colour.png" in two folders
      resolve to one asset and the second silently wears the first.
    """
    try:
        data = asset.get_editor_property("asset_import_data")
        source = str(data.get_first_filename() or "")
    except Exception:
        source = ""
    if source and os.path.normcase(os.path.normpath(source)) !=             os.path.normcase(os.path.normpath(path)):
        return False
    try:
        recorded = unreal.EditorAssetLibrary.get_metadata_tag(
            asset, SOURCE_STAMP_TAG)
    except Exception:
        recorded = ""
    if not recorded:
        # Imported by a build that did not stamp, so nothing can be said about
        # it. Re-importing once is cheap and leaves it stamped.
        return False
    return str(recorded) == stamp


def _stamp(asset, stamp):
    try:
        unreal.EditorAssetLibrary.set_metadata_tag(
            asset, SOURCE_STAMP_TAG, stamp)
    except Exception:
        pass


def _import_texture_asset(path, warnings):
    name = safe_asset_name(os.path.splitext(os.path.basename(path))[0], "Tex")
    destination = "{0}/{1}".format(TEXTURE_CONTENT_PATH, name)
    stamp = _source_stamp(path)
    if unreal.EditorAssetLibrary.does_asset_exist(destination):
        existing = unreal.EditorAssetLibrary.load_asset(destination)
        if existing is not None and _is_current(existing, path, stamp):
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
            _stamp(asset, stamp)
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

    if "<UDIM>" in path or "<udim>" in path:
        path = _first_udim_tile(record, path, channel, warnings)
        if path is None:
            return None

    if not os.path.isfile(path):
        warnings.append(
            'Texture "{0}" was not found on disk, so the channel "{1}" kept '
            "its flat value.".format(raw_path, channel)
        )
        return None

    key = os.path.normcase(os.path.abspath(path))
    if key in _cache:
        return _cache[key]

    asset = _import_texture_asset(path, warnings)
    if asset is not None:
        _configure_texture(asset, channel, colour_data)
        if "<UDIM>" in str(raw_path) or "<udim>" in str(raw_path):
            _check_udim(asset, path, channel, warnings)
    _cache[key] = asset
    return asset


def _first_udim_tile(record, path, channel, warnings):
    """A concrete tile to hand Unreal, or None if there is not one.

    Unreal finds the rest by itself: measured, importing tile.1001.png with
    its siblings beside it produced one texture with virtual texture streaming
    switched on, which is how the engine says "this is a UDIM set". So the only
    work here is undoing the token the exporter writes, and the exporter
    already kept the concrete path it came from.
    """
    concrete = str((record or {}).get("original_path") or "").strip()
    if concrete and os.path.isfile(concrete):
        return concrete
    for tile in ("1001", "1011"):
        candidate = path.replace("<UDIM>", tile).replace("<udim>", tile)
        if os.path.isfile(candidate):
            return candidate
    warnings.append(
        'Texture "{0}" is a UDIM set but no tile of it is on disk, so the '
        'channel "{1}" kept its flat value.'.format(path, channel)
    )
    return None


def _check_udim(asset, path, channel, warnings):
    """Say so if Unreal did not recognise the set it was handed."""
    if asset is None:
        return
    try:
        streaming = asset.get_editor_property("virtual_texture_streaming")
    except Exception:
        return
    if not streaming:
        warnings.append(
            'Texture "{0}" is a UDIM set, but Unreal imported it as a single '
            'tile, so the channel "{1}" is not tiled. The other tiles have to '
            "sit beside the first one.".format(os.path.basename(path), channel)
        )


def _png_bytes(values):
    """A 16 bit greyscale PNG, one row, written by hand.

    Written rather than imported because the receiver may only use the
    standard library, and 8 bits would put visible steps in a curve that a
    roughness reads straight off.
    """
    width = len(values)
    raw = bytearray()
    raw.append(0)  # filter: none, one row
    for value in values:
        clamped = 0 if value < 0.0 else (65535 if value > 1.0
                                         else int(round(value * 65535.0)))
        raw.append((clamped >> 8) & 0xFF)
        raw.append(clamped & 0xFF)

    def chunk(kind, payload):
        return (struct.pack(">I", len(payload)) + kind + payload
                + struct.pack(">I", zlib.crc32(kind + payload) & 0xFFFFFFFF))

    header = struct.pack(">IIBBBBB", width, 1, 16, 0, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", header)
            + chunk(b"IDAT", zlib.compress(bytes(raw), 9))
            + chunk(b"IEND", b""))


def ramp_lut_texture(label, values, warnings):
    """A ramp as a one row lookup texture Unreal can sample.

    The whole of remapValue folds in here: its input range, its curve and its
    output range are all evaluated into the row, so the material needs one
    sample and no arithmetic around it. A curve cannot be approximated by a
    number, and this is the one correction where the curve *is* the node.
    """
    if not values:
        return None
    name = safe_asset_name("{0}LUT_{1}".format(ASSET_PREFIX, label), "LUT")
    destination = "{0}/{1}".format(TEXTURE_CONTENT_PATH, name)
    if unreal.EditorAssetLibrary.does_asset_exist(destination):
        existing = unreal.EditorAssetLibrary.load_asset(destination)
        if existing is not None:
            return existing

    folder = os.path.join(tempfile.gettempdir(), "mlender_luts")
    try:
        if not os.path.isdir(folder):
            os.makedirs(folder)
        path = os.path.join(folder, name + ".png")
        with open(path, "wb") as handle:
            handle.write(_png_bytes(values))
    except Exception as exc:
        warnings.append(
            'A remap curve for "{0}" could not be written: {1}'.format(
                label, exc
            )
        )
        return None

    asset = _import_texture_asset(path, warnings)
    if asset is None:
        return None
    for name_, value in (
        ("srgb", False),
        ("compression_settings",
         getattr(unreal.TextureCompressionSettings, "TC_GRAYSCALE", None)),
        ("filter", getattr(unreal.TextureFilter, "TF_BILINEAR", None)),
    ):
        if value is None:
            continue
        try:
            asset.set_editor_property(name_, value)
        except Exception:
            pass
    # A curve that wraps would read its own far end at the edges.
    for axis in ("address_x", "address_y"):
        try:
            asset.set_editor_property(
                axis, unreal.TextureAddress.TA_CLAMP
            )
        except Exception:
            pass
    try:
        unreal.EditorAssetLibrary.save_loaded_asset(asset, False)
    except Exception:
        pass
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
            # Grayscale rather than masks, because the master samples these
            # through a Linear Grayscale parameter and Unreal refuses to
            # compile a sampler whose texture is of another type. TC_MASKS
            # pairs with a Masks sampler; the mismatch fails the whole
            # material, and every object wearing it falls back to the engine's
            # grey checker.
            asset.set_editor_property(
                "compression_settings",
                unreal.TextureCompressionSettings.TC_GRAYSCALE,
            )
    except Exception:
        # A texture that refuses a setting is still a usable texture; the
        # channel is worth more than the setting.
        pass
