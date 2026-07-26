# -*- coding: utf-8 -*-
from __future__ import print_function

import datetime
import io
import json
import os
import re
import socket

import maya.cmds as cmds
import maya.mel as mel


TOOL_NAME = "Z-A Exporter - Lookdev"
WINDOW_NAME = "zaLookdevExporterWindow"
PACKAGE_PREFIX = "MTB_Z_A_"
LIVELINK_HOST = "127.0.0.1"
LIVELINK_PORT = 50505
LIVELINK_PROTOCOL = "za_lookdev_livelink"
LIVELINK_VERSION = 1

SUPPORTED_SHADER_TYPES = (
    "RedshiftStandardMaterial",
    "RedshiftMaterial",
    "lambert",
    "blinn",
)

# Reflection roughness is the PBR surface roughness. Redshift's diffuse
# roughness is deliberately not used for Principled BSDF Roughness.
REDSHIFT_STANDARD_CHANNELS = {
    "base_color": ("base_color", "baseColor", "diffuse_color", "color"),
    "roughness": ("refl_roughness", "reflection_roughness", "specular_roughness"),
    "metallic": ("metalness", "refl_metalness"),
    "opacity": ("opacity_color", "opacity"),
    "normal": ("bump_input", "normalCamera"),
    "emission": ("emission_color", "emission"),
    "emission_strength": ("emission_weight", "emissionWeight"),
}

REDSHIFT_LEGACY_CHANNELS = {
    "base_color": ("diffuse_color", "base_color", "color"),
    "roughness": ("refl_roughness", "reflection_roughness"),
    "metallic": ("refl_metalness", "metalness"),
    "opacity": ("opacity_color", "opacity"),
    "normal": ("bump_input", "normalCamera"),
    "emission": ("emission_color", "emission"),
    "emission_strength": ("emission_weight", "emissionWeight"),
}


def show_ui():
    if cmds.window(WINDOW_NAME, exists=True):
        cmds.deleteUI(WINDOW_NAME)

    window = cmds.window(
        WINDOW_NAME,
        title=TOOL_NAME,
        sizeable=False,
        widthHeight=(620, 330),
    )
    cmds.columnLayout(
        adjustableColumn=True,
        rowSpacing=10,
        columnAttach=("both", 12),
    )
    cmds.text(label=TOOL_NAME, align="left", font="boldLabelFont")
    cmds.text(
        label=(
            "All renderable scene meshes are exported as FBX. Material assignments, "
            "Redshift/Lambert/Blinn values and original texture paths are sent to Blender."
        ),
        align="left",
        wordWrap=True,
        height=45,
    )

    export_folder = cmds.textFieldButtonGrp(
        label="Export Location",
        text=_default_export_folder(),
        buttonLabel="Browse",
        adjustableColumn=2,
        columnWidth3=(120, 390, 75),
    )
    cmds.textFieldButtonGrp(
        export_folder,
        edit=True,
        buttonCommand=lambda *_: _browse_folder(export_folder),
    )
    host_field = cmds.textFieldGrp(
        label="Blender Host",
        text=LIVELINK_HOST,
        adjustableColumn=2,
        columnWidth2=(120, 400),
    )
    port_field = cmds.intFieldGrp(
        label="Blender Port",
        value1=LIVELINK_PORT,
        adjustableColumn=2,
        columnWidth2=(120, 120),
    )
    cmds.text(
        label="Packages: MTB_Z_A_01, MTB_Z_A_02, MTB_Z_A_03...",
        align="left",
    )
    cmds.button(
        label="Send To Blender",
        height=42,
        command=lambda *_: _export_from_ui(export_folder, host_field, port_field),
    )
    cmds.showWindow(window)
    return window


def show():
    """Public entry point used by Maya shelf and Script Editor launchers."""
    return show_ui()


def export_lookdev(output_folder):
    output_folder = _normalize_folder(output_folder)
    if not os.path.isdir(output_folder):
        os.makedirs(output_folder)

    package_name = _next_package_name(output_folder)
    package_folder = os.path.join(output_folder, package_name)
    os.makedirs(package_folder)
    fbx_path = os.path.join(package_folder, package_name + ".fbx")
    json_path = os.path.join(package_folder, package_name + "_lookdev.json")

    try:
        mesh_shapes = _scene_mesh_shapes()
        if not mesh_shapes:
            raise RuntimeError("The Maya scene contains no exportable mesh.")
        mesh_records = [_mesh_record(shape) for shape in mesh_shapes]
        mesh_transforms = _unique(
            [
                (cmds.listRelatives(shape, parent=True, fullPath=True) or [""])[0]
                for shape in mesh_shapes
            ]
        )
        mesh_transforms = [item for item in mesh_transforms if item]
        _export_fbx(mesh_transforms, fbx_path)

        payload = {
            "schema_version": 1,
            "tool_name": TOOL_NAME,
            "profile": "lookdev",
            "exported_at_utc": datetime.datetime.utcnow().isoformat() + "Z",
            "maya_scene": cmds.file(query=True, sceneName=True) or "",
            "package_name": package_name,
            "package_folder": _maya_path(package_folder),
            "fbx_file": _maya_path(fbx_path),
            "mesh_count": len(mesh_records),
            "meshes": mesh_records,
        }
        _write_json(json_path, payload)
    except Exception:
        _remove_file(fbx_path)
        _remove_file(json_path)
        try:
            os.rmdir(package_folder)
        except Exception:
            pass
        raise

    return {
        "package_name": package_name,
        "package_folder": package_folder,
        "fbx_path": fbx_path,
        "json_path": json_path,
        "package_json": payload,
        "mesh_count": len(mesh_records),
    }


def _export_from_ui(export_folder, host_field, port_field):
    output_folder = cmds.textFieldButtonGrp(
        export_folder,
        query=True,
        text=True,
    )
    host = cmds.textFieldGrp(host_field, query=True, text=True).strip()
    port = cmds.intFieldGrp(port_field, query=True, value1=True)
    try:
        result = export_lookdev(output_folder)
    except Exception as exc:
        cmds.warning("Z-A Lookdev export failed: {0}".format(exc))
        cmds.confirmDialog(
            title="Export Failed",
            message=str(exc),
            button=["OK"],
            icon="critical",
        )
        return

    try:
        _send_package(result, host, port)
    except Exception as exc:
        cmds.warning("LiveLink send failed: {0}".format(exc))
        cmds.confirmDialog(
            title="Export Complete, LiveLink Failed",
            message=(
                "FBX and JSON were exported, but Blender could not be notified.\n\n"
                "{0}\n\nPackage:\n{1}"
            ).format(exc, result["package_folder"]),
            button=["OK"],
            icon="warning",
        )
        return

    cmds.confirmDialog(
        title="Z-A Lookdev Export Complete",
        message=(
            "Meshes: {0}\n\nPackage:\n{1}\n\nFBX:\n{2}"
        ).format(
            result["mesh_count"],
            result["package_folder"],
            result["fbx_path"],
        ),
        button=["OK"],
        icon="information",
    )


def _scene_mesh_shapes():
    result = []
    for shape in cmds.ls(type="mesh", long=True) or []:
        try:
            if cmds.getAttr(shape + ".intermediateObject"):
                continue
        except Exception:
            pass
        parents = cmds.listRelatives(shape, parent=True, fullPath=True) or []
        if not parents:
            continue
        result.append(shape)
    return _unique(result)


def _mesh_record(mesh_shape):
    transform = (cmds.listRelatives(mesh_shape, parent=True, fullPath=True) or [""])[0]
    full_name = _node_label(transform or mesh_shape)
    return {
        "mesh": _without_namespace(full_name),
        "mesh_full_name": full_name,
        "mesh_path": transform,
        "shape": _node_label(mesh_shape),
        "shape_path": mesh_shape,
        "materials": _mesh_materials(mesh_shape),
    }


def _mesh_materials(mesh_shape):
    result = []
    seen = set()
    shading_engines = _unique(
        cmds.listConnections(mesh_shape, type="shadingEngine") or []
    )
    for shading_engine in shading_engines:
        shaders = cmds.listConnections(
            shading_engine + ".surfaceShader",
            source=True,
            destination=False,
        ) or []
        for shader in _unique(shaders):
            key = (shading_engine, shader)
            if key in seen:
                continue
            seen.add(key)
            shader_type = _node_type(shader)
            result.append(
                {
                    "material": _without_namespace(_node_label(shader)),
                    "material_full_name": _node_label(shader),
                    "material_path": shader,
                    "shader_type": shader_type,
                    "supported": shader_type in SUPPORTED_SHADER_TYPES,
                    "shading_engine": _node_label(shading_engine),
                    "face_assignment": _face_assignment(
                        mesh_shape,
                        shading_engine,
                    ),
                    "channels": _shader_channels(shader, shader_type),
                }
            )
    return result


def _shader_channels(shader, shader_type):
    if shader_type == "RedshiftStandardMaterial":
        return _redshift_channels(shader, REDSHIFT_STANDARD_CHANNELS)
    if shader_type == "RedshiftMaterial":
        return _redshift_channels(shader, REDSHIFT_LEGACY_CHANNELS)
    if shader_type == "blinn":
        return _maya_basic_channels(shader, roughness=0.1)
    if shader_type == "lambert":
        return _maya_basic_channels(shader, roughness=0.7)
    return _maya_basic_channels(shader, roughness=0.5)


def _redshift_channels(shader, channel_map):
    result = {}
    for channel, attrs in channel_map.items():
        record = _first_channel_record(shader, attrs)
        if record:
            result[channel] = record
    _apply_redshift_glossiness_conversion(shader, result.get("roughness"))
    result.setdefault("roughness", {"value": 0.5})
    result.setdefault("metallic", {"value": 0.0})
    result.setdefault("opacity", {"value": [1.0, 1.0, 1.0, 1.0]})
    return result


def _apply_redshift_glossiness_conversion(shader, roughness_record):
    if not roughness_record:
        return
    convert_gloss = False
    for attr in (
        "refl_isGlossiness",
        "refl_is_glossiness",
        "refl_roughness_isGlossiness",
        "refl_convertFromGlossiness",
        "refl_convert_from_glossiness",
    ):
        if not _attr_exists(shader, attr):
            continue
        try:
            convert_gloss = bool(cmds.getAttr(shader + "." + attr))
        except Exception:
            convert_gloss = False
        roughness_record["glossiness_flag_attr"] = attr
        break
    if not convert_gloss:
        return
    roughness_record["source_semantic"] = "glossiness"
    if roughness_record.get("texture"):
        roughness_record["invert"] = True
    elif "value" in roughness_record:
        roughness_record["value"] = 1.0 - float(roughness_record["value"])


def _maya_basic_channels(shader, roughness):
    result = {
        "roughness": {"value": float(roughness)},
        "metallic": {"value": 0.0},
    }
    base_color = _first_channel_record(shader, ("color",))
    if base_color:
        result["base_color"] = base_color

    transparency = _first_channel_record(shader, ("transparency",))
    if transparency:
        transparency["invert"] = True
        transparency["semantic"] = "maya_transparency_to_opacity"
        if "value" in transparency:
            transparency["value"] = _invert_color(transparency["value"])
            transparency["invert"] = False
        result["opacity"] = transparency
    else:
        result["opacity"] = {"value": [1.0, 1.0, 1.0, 1.0]}

    normal = _first_channel_record(shader, ("normalCamera",))
    if normal and normal.get("texture"):
        result["normal"] = normal
    emission = _first_channel_record(shader, ("incandescence",))
    if emission:
        result["emission"] = emission
        result["emission_strength"] = {"value": 1.0}
    return result


def _first_channel_record(shader, attrs):
    for attr in attrs:
        if not _attr_exists(shader, attr):
            continue
        plug = shader + "." + attr
        texture = _texture_upstream_from_plug(plug)
        record = {
            "maya_attr": attr,
            "maya_plug": plug,
        }
        if texture:
            record["texture"] = texture
        value = _plug_value(plug)
        if value is not None:
            record["value"] = value
        return record
    return None


def _texture_upstream_from_plug(plug):
    source_plugs = cmds.listConnections(
        plug,
        source=True,
        destination=False,
        plugs=True,
    ) or []
    if not source_plugs:
        return None

    source_plug = source_plugs[0]
    source_node = source_plug.split(".", 1)[0]
    candidates = [source_node]
    candidates.extend(cmds.listHistory(source_node, pruneDagObjects=True) or [])
    for node in _unique(candidates):
        path = _texture_path_from_node(node)
        if path:
            return {
                "path": _maya_path(path),
                "node": _node_label(node),
                "node_type": _node_type(node),
                "source_plug": source_plug,
                "color_space": _texture_color_space(node),
            }
    return {
        "path": "",
        "node": _node_label(source_node),
        "node_type": _node_type(source_node),
        "source_plug": source_plug,
        "unsupported_network": True,
    }


def _texture_path_from_node(node):
    for attr in ("fileTextureName", "tex0", "filename", "file"):
        if not _attr_exists(node, attr):
            continue
        try:
            value = cmds.getAttr(node + "." + attr)
        except Exception:
            continue
        if isinstance(value, (str, bytes)) and value:
            return os.path.abspath(os.path.expandvars(os.path.expanduser(value)))
    return ""


def _texture_color_space(node):
    if not _attr_exists(node, "colorSpace"):
        return ""
    try:
        return str(cmds.getAttr(node + ".colorSpace") or "")
    except Exception:
        return ""


def _plug_value(plug):
    try:
        value = cmds.getAttr(plug)
    except Exception:
        return None
    while isinstance(value, (list, tuple)) and len(value) == 1:
        value = value[0]
    if isinstance(value, (list, tuple)):
        return [float(item) for item in value]
    if isinstance(value, bool):
        return bool(value)
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _face_assignment(mesh_shape, shading_engine):
    transform = (cmds.listRelatives(mesh_shape, parent=True, fullPath=True) or [""])[0]
    targets = set([mesh_shape, transform])
    components = []
    all_faces = False
    for member in cmds.sets(shading_engine, query=True) or []:
        text = str(member)
        node_name = text.split(".f[", 1)[0]
        resolved = cmds.ls(node_name, long=True) or []
        if not any(item in targets for item in resolved):
            continue
        if ".f[" not in text:
            all_faces = True
            continue
        component = text.split(".f[", 1)[1].rstrip("]")
        if component and component not in components:
            components.append(component)
    return {
        "all_faces": all_faces,
        "face_components": components,
    }


def _export_fbx(mesh_transforms, fbx_path):
    _load_fbx()
    previous_selection = cmds.ls(selection=True, long=True) or []
    try:
        cmds.select(mesh_transforms, replace=True)
        _mel("FBXResetExport;")
        _mel("FBXExportCameras -v false;")
        _mel("FBXExportLights -v false;")
        _mel("FBXExportEmbeddedTextures -v false;")
        _mel("FBXExportInputConnections -v false;")
        _mel("FBXExportBakeComplexAnimation -v false;")
        _mel("FBXExportSkins -v true;")
        _mel("FBXExportShapes -v true;")
        _mel("FBXExportSmoothingGroups -v true;")
        mel.eval('FBXExport -f "{0}" -s;'.format(_mel_path(fbx_path)))
    finally:
        if previous_selection:
            cmds.select(previous_selection, replace=True)
        else:
            cmds.select(clear=True)


def _load_fbx():
    try:
        if cmds.pluginInfo("fbxmaya", query=True, loaded=True):
            return
    except Exception:
        pass
    try:
        cmds.loadPlugin("fbxmaya")
    except Exception:
        cmds.loadPlugin("fbxmaya.mll")


def _send_package(result, host, port):
    host = host or LIVELINK_HOST
    try:
        port = int(port)
    except Exception:
        raise ValueError("Blender port must be a number.")
    message = {
        "protocol": LIVELINK_PROTOCOL,
        "protocol_version": LIVELINK_VERSION,
        "event": "lookdev_package_ready",
        "package_folder": _maya_path(result["package_folder"]),
        "package_json": result["package_json"],
    }
    payload = (json.dumps(message, ensure_ascii=False) + "\n").encode("utf-8")
    try:
        connection = socket.create_connection((host, port), timeout=5.0)
        try:
            connection.sendall(payload)
        finally:
            connection.close()
    except socket.error as exc:
        raise RuntimeError(
            "Could not connect to Blender at {0}:{1}. ({2})".format(
                host,
                port,
                exc,
            )
        )


def _next_package_name(folder):
    highest = 0
    if os.path.isdir(folder):
        pattern = re.compile(r"^MTB_Z_A_(\d+)$", re.IGNORECASE)
        for name in os.listdir(folder):
            if not os.path.isdir(os.path.join(folder, name)):
                continue
            match = pattern.match(name)
            if match:
                highest = max(highest, int(match.group(1)))
    return "{0}{1:02d}".format(PACKAGE_PREFIX, highest + 1)


def _default_export_folder():
    scene = cmds.file(query=True, sceneName=True) or ""
    if scene:
        return os.path.dirname(scene)
    try:
        return cmds.workspace(query=True, rootDirectory=True) or os.path.expanduser("~")
    except Exception:
        return os.path.expanduser("~")


def _browse_folder(field):
    result = cmds.fileDialog2(
        dialogStyle=2,
        fileMode=3,
        caption="Choose Z-A Lookdev Export Location",
    )
    if result:
        cmds.textFieldButtonGrp(field, edit=True, text=result[0])


def _normalize_folder(path):
    if not path:
        raise ValueError("Choose an export location.")
    return os.path.abspath(os.path.expanduser(path))


def _write_json(path, data):
    with io.open(path, "w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2, sort_keys=True)


def _attr_exists(node, attr):
    try:
        return cmds.attributeQuery(attr, node=node, exists=True)
    except Exception:
        return False


def _node_type(node):
    try:
        return cmds.nodeType(node)
    except Exception:
        return ""


def _node_label(node):
    return str(node or "").split("|")[-1]


def _without_namespace(value):
    return str(value or "").rsplit(":", 1)[-1]


def _invert_color(value):
    if isinstance(value, (list, tuple)):
        inverted = [1.0 - float(item) for item in value[:3]]
        return inverted + [1.0]
    return 1.0 - float(value)


def _unique(items):
    result = []
    seen = set()
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result


def _mel(command):
    try:
        mel.eval(command)
    except Exception:
        pass


def _mel_path(path):
    return os.path.abspath(path).replace("\\", "/").replace('"', '\\"')


def _maya_path(path):
    return os.path.abspath(path).replace("\\", "/")


def _remove_file(path):
    try:
        if os.path.isfile(path):
            os.remove(path)
    except Exception:
        pass


if __name__ == "__main__":
    show_ui()
