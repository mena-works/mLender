# -*- coding: utf-8 -*-
"""Host-free checks: import graph, cross-package contracts, pure math.

Runs under a plain Python 3 interpreter by stubbing bpy, mathutils and
maya.cmds, so it catches what py_compile cannot: missing names in relative
imports, circular imports, protocol drift between the two packages, and
channel keys the importer cannot map.

    python tests/check_contracts.py

It does NOT verify that the Maya or Blender APIs are used correctly. For that
see maya_export_test.py and blender_import_test.py.
"""
import math
import os
import re
import sys
import types


TOOL_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

failures = []


def check(label, condition, detail=""):
    if condition:
        print("  ok    {0}".format(label))
    else:
        failures.append("{0} {1}".format(label, detail))
        print("  FAIL  {0}  {1}".format(label, detail))


def _names_in_block(source, opener):
    """The bare names listed in one parenthesised block, by its opening line."""
    start = source.find(opener)
    if start < 0:
        return set()
    end = source.find(")", start)
    body = source[start + len(opener):end]
    return set(re.findall(r"(\w+)\s*,", body))


def package_modules(folder):
    """Every importable module in a package folder, by name."""
    return set(
        name[:-3] for name in os.listdir(folder)
        if name.endswith(".py") and name != "__init__.py"
    )


def close(label, got, want, tolerance=1e-9):
    check(
        "{0} = {1:.6g}".format(label, got),
        abs(got - want) <= tolerance,
        "wanted {0!r}".format(want),
    )


# --------------------------------------------------------------- host stubs
class _Any(object):
    """Permissive stand-in for opaque host objects."""

    def __init__(self, *args, **kwargs):
        pass

    def __getattr__(self, name):
        return _Any()

    def __call__(self, *args, **kwargs):
        return _Any()

    def __getitem__(self, key):
        return _Any()


def _module(name):
    module = types.ModuleType(name)
    sys.modules[name] = module
    return module


def install_stubs():
    maya = _module("maya")
    maya.cmds = _module("maya.cmds")
    maya.mel = _module("maya.mel")
    for name in (
        "ls", "getAttr", "attributeQuery", "listRelatives", "listConnections",
        "listHistory", "nodeType", "xform", "currentTime", "currentUnit",
        "file", "sets", "select", "pluginInfo", "loadPlugin", "window",
        "deleteUI", "columnLayout", "text", "textFieldButtonGrp",
        "textFieldGrp", "intFieldGrp", "button", "showWindow", "warning",
        "confirmDialog", "fileDialog2", "workspace",
    ):
        setattr(maya.cmds, name, _Any())
    maya.mel.eval = _Any()

    bpy = _module("bpy")
    bpy.types = _module("bpy.types")
    bpy.types.Operator = type("Operator", (object,), {})
    bpy.types.Panel = type("Panel", (object,), {})
    bpy.types.Scene = _Any()
    for name in ("props", "data", "context", "ops", "utils", "app", "path"):
        setattr(bpy, name, _Any())

    class Vector(object):
        length = 0.0

        def __init__(self, values=(0.0, 0.0, 0.0)):
            self.x, self.y, self.z = list(values)[:3]

        def normalized(self):
            return self

        def copy(self):
            return self

        def __mul__(self, other):
            return self

    class Matrix(object):
        def __init__(self, rows=None):
            self.translation = Vector()

        @staticmethod
        def Identity(size):
            return Matrix()

        def to_euler(self):
            return (0.0, 0.0, 0.0)

    mathutils = _module("mathutils")
    mathutils.Vector = Vector
    mathutils.Matrix = Matrix

    # The overlay outliner draws with the GPU modules; none of that runs
    # here, but the package must import.
    gpu = _module("gpu")
    gpu.shader = _Any()
    gpu.state = _Any()
    gpu_extras = _module("gpu_extras")
    gpu_extras.batch = _module("gpu_extras.batch")
    gpu_extras.batch.batch_for_shader = _Any()
    blf = _module("blf")
    for name in ("position", "size", "draw", "color", "dimensions"):
        setattr(blf, name, _Any())


# ------------------------------------------------------------------- checks
def main():
    install_stubs()
    if TOOL_ROOT not in sys.path:
        sys.path.insert(0, TOOL_ROOT)

    print("import graph")
    import mlender_exporter as exporter
    import mlender_importer as importer
    check("exporter package imports", True)
    check("importer package imports", True)

    for attr in ("show_ui", "show", "export_scene", "reload_package"):
        check("exporter exposes {0}".format(attr), hasattr(exporter, attr))
    for attr in ("register", "unregister", "import_scene_package", "bl_info"):
        check("importer exposes {0}".format(attr), hasattr(importer, attr))

    print("\nevery module is in its reload list")
    # A module left out of a reload list keeps running its old code through a
    # reload, which at development time looks like the edit not having worked.
    # It is on the project's own forbidden list and nothing enforced it.
    exporter_modules = package_modules(
        os.path.join(TOOL_ROOT, "mlender_exporter")
    )
    listed = set(exporter.SUBMODULES)
    check("exporter SUBMODULES covers every module",
          exporter_modules <= listed,
          "missing {0}".format(sorted(exporter_modules - listed)))
    check("and names nothing that is not there",
          listed <= exporter_modules,
          "stale {0}".format(sorted(listed - exporter_modules)))

    importer_modules = package_modules(
        os.path.join(TOOL_ROOT, "mlender_importer")
    )
    with open(os.path.join(TOOL_ROOT, "mlender_importer", "__init__.py"),
              encoding="utf-8") as handle:
        importer_source = handle.read()
    # Two lists, because the project's own rule says two: the import block and
    # the tuple that is reloaded. They look identical, so they are read one at
    # a time -- a single pattern over the whole file matches their union and
    # a module missing from one of them passes.
    for label, opener in (("import block", "from . import ("),
                          ("reload list", "for _module in (")):
        names = _names_in_block(importer_source, opener)
        check("importer {0} covers every module".format(label),
              importer_modules <= names,
              "missing {0}".format(sorted(importer_modules - names)))

    print("\ncross-package contracts")
    for field in (
        "LIVELINK_HOST",
        "LIVELINK_PORT",
        "LIVELINK_PROTOCOL",
        "LIVELINK_VERSION",
    ):
        check(
            "{0} matches on both sides".format(field),
            getattr(exporter, field) == getattr(importer, field),
            "{0!r} vs {1!r}".format(
                getattr(exporter, field), getattr(importer, field)
            ),
        )

    check(
        "importer accepts the exporter's schema version",
        exporter.EXPORT_SCHEMA_VERSION
        in importer.constants.SUPPORTED_SCHEMA_VERSIONS,
        "{0} not in {1}".format(
            exporter.EXPORT_SCHEMA_VERSION,
            importer.constants.SUPPORTED_SCHEMA_VERSIONS,
        ),
    )
    check(
        "build versions in step",
        exporter.BUILD_VERSION == importer.BUILD_VERSION,
        "{0} vs {1}".format(exporter.BUILD_VERSION, importer.BUILD_VERSION),
    )
    check(
        "bl_info version matches BUILD_VERSION",
        ".".join(str(n) for n in importer.bl_info["version"])
        == importer.BUILD_VERSION,
    )

    print("\nchannel contract")
    exporter_constants = exporter.constants
    exported = set()
    for table in (
        exporter_constants.REDSHIFT_STANDARD_CHANNELS,
        exporter_constants.REDSHIFT_LEGACY_CHANNELS,
        exporter_constants.ARNOLD_STANDARD_CHANNELS,
        exporter_constants.ARNOLD_OPENPBR_CHANNELS,
        exporter_constants.ARNOLD_LAMBERT_CHANNELS,
    ):
        exported.update(table.keys())
    # A channel is honoured if it drives a Principled socket, a Glass socket,
    # or is deliberately metadata only.
    known = (
        set(importer.constants.PRINCIPLED_INPUTS)
        | set(importer.constants.GLASS_INPUTS)
        | set(importer.constants.METADATA_CHANNELS)
    )
    check(
        "every exported channel is honoured by the importer",
        exported <= known,
        "unmapped: {0}".format(sorted(exported - known)),
    )
    # A channel honoured only by the glass path is not honoured: the common
    # build is Principled, and ior used to be missing from it entirely.
    principled_reachable = (
        set(importer.constants.PRINCIPLED_INPUTS)
        | set(importer.constants.METADATA_CHANNELS)
        | set(importer.constants.GLASS_ONLY_CHANNELS)
    )
    check(
        "every channel reaches the Principled build or is declared glass only",
        exported <= principled_reachable,
        "only reachable through glass: {0}".format(
            sorted(exported - principled_reachable)
        ),
    )
    check(
        "the glass only list really is only about refraction",
        all(
            "transmission" in name
            for name in importer.constants.GLASS_ONLY_CHANNELS
        ),
        sorted(importer.constants.GLASS_ONLY_CHANNELS),
    )
    check(
        "the glass path covers the refraction channels",
        {"transmission_color", "transmission_roughness", "ior"}
        <= set(importer.constants.GLASS_INPUTS),
    )
    print("       channels: {0}".format(", ".join(sorted(exported))))

    check(
        "OpenPBR emission semantic agrees on both sides",
        exporter_constants.OPENPBR_EMISSION_SEMANTIC
        == importer.constants.OPENPBR_EMISSION_SEMANTIC,
    )

    print("\ncolour clamping")
    color4 = importer.utils.color4
    check("an albedo above one is clamped",
          color4((2.0, 2.0, 2.0))[:3] == (1.0, 1.0, 1.0),
          color4((2.0, 2.0, 2.0)))
    check("an emission colour above one is not",
          color4((50.0, 2.0, 0.5), clamp=False)[:3] == (50.0, 2.0, 0.5),
          color4((50.0, 2.0, 0.5), clamp=False))
    check("negatives are still floored either way",
          color4((-1.0, 0.5, 0.5), clamp=False)[0] == 0.0
          and color4((-1.0, 0.5, 0.5))[0] == 0.0)
    # Which channels skip the clamp is the part worth pinning down: an albedo
    # above one is unphysical, an emission colour above one is ordinary.
    unclamped = set(importer.constants.UNCLAMPED_COLOUR_CHANNELS)
    check("emission skips the clamp", "emission" in unclamped)
    check("a distance skips it too", "subsurface_radius" in unclamped)
    check("base colour and the tints do not",
          not unclamped.intersection(
              {"base_color", "transmission_color", "coat_tint", "sheen_tint"}
          ),
          sorted(unclamped))
    check("every unclamped channel is a colour valued one",
          unclamped <= set(importer.constants.COLOUR_VALUED_CHANNELS),
          sorted(unclamped - set(importer.constants.COLOUR_VALUED_CHANNELS)))

    print("\nlivelink message")
    validate = importer.livelink.validate_message
    base = {
        "protocol": importer.constants.LIVELINK_PROTOCOL,
        "protocol_version": importer.constants.LIVELINK_VERSION,
        "event": importer.constants.LIVELINK_EVENT,
        "package_folder": "C:/packages/mLender_01",
    }

    def rejects(label, message):
        try:
            validate(message)
        except ValueError:
            check(label, True)
            return
        check(label, False, "accepted {0!r}".format(message))

    try:
        validate(dict(base))
        check("a protocol 2 message needs no embedded JSON", True)
    except ValueError as error:
        check("a protocol 2 message needs no embedded JSON", False, error)
    try:
        validate(dict(base, package_json={"schema_version": 1}))
        check("an embedded JSON is still accepted", True)
    except ValueError as error:
        check("an embedded JSON is still accepted", False, error)

    rejects("a message with no package folder is rejected",
            {k: v for k, v in base.items() if k != "package_folder"})
    rejects("an empty package folder is rejected",
            dict(base, package_folder="   "))
    rejects("a non-object package_json is rejected",
            dict(base, package_json="not an object"))
    rejects("the old protocol version is rejected",
            dict(base, protocol_version=1))

    # The whole point of protocol 2: the message no longer grows with the
    # animation, so the importer's size ceiling stops being reachable.
    import json as _json

    wire = _json.dumps(base)
    check(
        "the message stays tiny regardless of scene size",
        len(wire) < 1024,
        "{0} bytes".format(len(wire)),
    )

    print("\nanimation range")
    parse = exporter.ui.parse_frame_range
    check("plain range", parse("1-120") == (1.0, 120.0, None), parse("1-120"))
    check("range with a step", parse("1-120x2") == (1.0, 120.0, 2.0),
          parse("1-120x2"))
    check("spaces tolerated", parse(" 10 - 20 ") == (10.0, 20.0, None),
          parse(" 10 - 20 "))
    check("blank means the playback range", parse("") == (None, None, None))
    # A half typed range must not silently export the wrong frames.
    for text in ("120", "1-", "abc", "1-2-3"):
        check("{0!r} rejected".format(text), parse(text) == (None, None, None),
              parse(text))

    info = exporter.animation.animation_info
    single = info(False)
    check("animation off reports a single frame",
          single["enabled"] is False and single["frame_count"] == 1, single)
    ranged = info(True, 1, 10)
    check("inclusive frame count, 1 to 10 is 10 frames",
          ranged["frame_count"] == 10, ranged["frame_count"])
    stepped = info(True, 1, 11, 2)
    check("a step of 2 over 1 to 11 is 6 frames",
          stepped["frame_count"] == 6, stepped["frame_count"])
    check("frame list matches the count",
          exporter.animation.frame_list(stepped) == [1, 3, 5, 7, 9, 11],
          exporter.animation.frame_list(stepped))
    reversed_range = info(True, 20, 5)
    check("a backwards range is put the right way round",
          (reversed_range["start"], reversed_range["end"]) == (5.0, 20.0),
          (reversed_range["start"], reversed_range["end"]))
    huge = info(True, 1, 100000)
    check("a runaway range is clamped and says so",
          huge["truncated"] is True
          and huge["frame_count"] == exporter.constants.MAX_ANIMATION_FRAMES,
          (huge["truncated"], huge["frame_count"]))

    print("\ncorrection node contract")
    recorded = set(exporter_constants.CORRECTION_NODE_ATTRS)
    rebuilt = set(importer.corrections.CORRECTION_BUILDERS)
    check(
        "every correction node the exporter records can be rebuilt",
        recorded <= rebuilt,
        "no builder for: {0}".format(sorted(recorded - rebuilt)),
    )
    check(
        "no builder waits for a node the exporter never records",
        rebuilt <= recorded,
        "never recorded: {0}".format(sorted(rebuilt - recorded)),
    )
    check(
        "every two input node names an operand the builders read",
        all(
            operand in ("multiply", "add", "operand", "other_color")
            for operand, _attrs
            in exporter_constants.CORRECTION_OPERAND_INPUTS.values()
        ),
        sorted(
            operand for operand, _attrs
            in exporter_constants.CORRECTION_OPERAND_INPUTS.values()
        ),
    )
    check(
        "every node with an operand has a builder",
        set(exporter_constants.CORRECTION_OPERAND_INPUTS)
        <= set(importer.corrections.CORRECTION_BUILDERS),
    )
    check(
        "the file node is never mistaken for a correction",
        "file" in exporter_constants.CORRECTION_IGNORED_NODE_TYPES,
    )
    print("       correction nodes: {0}".format(", ".join(sorted(recorded))))

    print("\narea shape resolution")
    resolve = exporter.lights.resolve_area_shape
    # Redshift sends an enum label, Arnold sends a bare aiTranslator string.
    check("redshift enum label disk", resolve(1, "Disk") == "DISK")
    check("arnold string 'disk'", resolve("disk", "") == "DISK")
    check("arnold string 'quad' is a rectangle", resolve("quad", "") == "RECTANGLE")
    check("arnold string 'cylinder'", resolve("cylinder", "") == "CYLINDER")
    check("empty aiTranslator defaults to rectangle", resolve("", "") == "RECTANGLE")
    check("numeric index still works", resolve(2, "") == "SPHERE")
    check("unknown string falls back", resolve("banana", "") == "RECTANGLE")

    print("\nlight energy and area")
    lights = importer.lights

    def record(shape="RECTANGLE", scale=(1.0, 1.0, 1.0), **extra):
        data = {"area_shape": shape, "transform": {"scale": list(scale)}}
        data.update(extra)
        return data

    # Measured: an Arnold or native Maya quad spans -1..1, so its emitting
    # size is twice the transform scale. Redshift is unmeasured and stays 1:1.
    check(
        "arnold and maya area lights are twice their transform scale",
        (lights.area_size_factor(record(node_type="aiAreaLight")),
         lights.area_size_factor(record(node_type="areaLight"))) == (2.0, 2.0),
    )
    check(
        "redshift keeps the unmeasured one to one reading",
        lights.area_size_factor(record(node_type="RedshiftPhysicalLight")) == 1.0,
    )
    close(
        "redshift rectangle 2x3 area",
        lights.emitting_surface_area(
            record("RECTANGLE", (2.0, 3.0, 1.0),
                   node_type="RedshiftPhysicalLight"), 1.0),
        6.0,
    )
    close(
        "arnold rectangle 2x3 area doubles on each edge",
        lights.emitting_surface_area(
            record("RECTANGLE", (2.0, 3.0, 1.0), node_type="aiAreaLight"), 1.0),
        24.0,
    )
    close(
        "redshift disk diameter 4 area",
        lights.emitting_surface_area(
            record("DISK", (4.0, 2.0, 1.0),
                   node_type="RedshiftPhysicalLight"), 1.0),
        math.pi * 4.0,
    )
    close(
        "redshift sphere diameter 4 area",
        lights.emitting_surface_area(
            record("SPHERE", (4.0, 2.0, 1.0),
                   node_type="RedshiftPhysicalLight"), 1.0),
        16.0 * math.pi,
    )
    close(
        "sun passes intensity through",
        lights.light_energy(record(effective_intensity=3.0), "SUN", 1.0),
        3.0,
    )
    close(
        "lumens over luminous efficacy",
        lights.light_energy(
            record(effective_intensity=683.0, enum_labels={"units": "Lumens"}),
            "AREA",
            1.0,
        ),
        1.0,
    )
    close(
        "exposure folds into effective intensity",
        lights.light_energy(record(intensity=2.0, exposure=3.0), "SUN", 1.0),
        16.0,
    )
    # Measured, not chosen. Arnold's normalized intensity is the radiant
    # intensity along the light's normal, and a Lambertian emitter's total flux
    # is pi times that, which is what Blender Power means. Confirmed by
    # rendering matched scenes in both; see tests/docs/light_calibration.md.
    watts = importer.constants.WATTS_PER_INTENSITY
    close("arnold converts through pi", watts["arnold"], math.pi)
    close("native maya converts through pi", watts["maya"], math.pi)
    close(
        "a centimetre scene folds the unit scale in as its square",
        lights.light_energy(
            record(effective_intensity=1.0, node_type="aiAreaLight"),
            "AREA",
            0.01,
        ),
        math.pi * 0.0001,
    )
    close(
        "arnold intensity 1 becomes pi watts",
        lights.light_energy(
            record(effective_intensity=1.0, node_type="aiAreaLight"),
            "AREA",
            1.0,
        ),
        math.pi,
    )
    close(
        "native maya intensity 1 becomes pi watts",
        lights.light_energy(
            record(effective_intensity=1.0, node_type="areaLight"),
            "AREA",
            1.0,
        ),
        math.pi,
    )
    close(
        "the user scale multiplies the conversion",
        lights.light_energy(
            record(effective_intensity=1.0, node_type="aiAreaLight"),
            "AREA",
            1.0,
            power_scale=2.5,
        ),
        2.5 * math.pi,
    )

    print("\nnormalize is folded into flux exactly once")
    normalized = record(
        "RECTANGLE",
        (2.0, 3.0, 1.0),
        effective_intensity=1.0,
        node_type="aiAreaLight",
        parameters={"normalize": True},
    )
    unnormalized = record(
        "RECTANGLE",
        (2.0, 3.0, 1.0),
        effective_intensity=1.0,
        node_type="aiAreaLight",
        parameters={"normalize": False},
    )
    check(
        "a missing normalize flag is treated as normalized",
        lights.source_is_normalized(record(effective_intensity=1.0)),
    )
    close(
        "normalized light ignores its area",
        lights.light_energy(normalized, "AREA", 1.0),
        math.pi,
    )
    close(
        "non-normalized light folds in its area once",
        lights.light_energy(unnormalized, "AREA", 1.0),
        math.pi * 24.0,
    )
    close(
        "non-normalized spot has no area to fold in",
        lights.light_energy(unnormalized, "SPOT", 1.0),
        math.pi,
    )
    check(
        "renderer detected from node type",
        (
            lights.renderer_key(record(node_type="RedshiftPhysicalLight")),
            lights.renderer_key(record(node_type="aiSkyDomeLight")),
            lights.renderer_key(record(node_type="areaLight")),
        )
        == ("redshift", "arnold", "maya"),
    )

    print("\nthe pose bridge speaks the same protocol on both sides")
    check("package event name matches",
          exporter.constants.LIVELINK_PACKAGE_EVENT
          == importer.constants.LIVELINK_EVENT,
          (exporter.constants.LIVELINK_PACKAGE_EVENT,
           importer.constants.LIVELINK_EVENT))
    check("pose event name matches",
          exporter.constants.LIVELINK_POSE_EVENT
          == importer.constants.LIVELINK_POSE_EVENT,
          (exporter.constants.LIVELINK_POSE_EVENT,
           importer.constants.LIVELINK_POSE_EVENT))

    validate = importer.livelink.validate_message
    pose_wire = {
        "protocol": importer.constants.LIVELINK_PROTOCOL,
        "protocol_version": importer.constants.LIVELINK_VERSION,
        "event": importer.constants.LIVELINK_POSE_EVENT,
        "pose": {"joints": []},
    }
    validate(pose_wire)
    check("a pose message passes the validator", True)
    for broken, label in (
        (dict(pose_wire, event="no_such_event"), "an unknown event"),
        (dict(pose_wire, pose=None), "a pose message without its pose"),
        (dict(pose_wire, pose="not a dict"), "a pose that is not an object"),
    ):
        try:
            validate(broken)
            check("{0} is refused".format(label), False, "no error raised")
        except ValueError:
            check("{0} is refused".format(label), True)

    print("\nuv sets travel only when they differ from the default")
    textures = exporter.textures

    class _UvCmds(object):
        """Just enough of maya.cmds for the uvLink walk."""

        def __init__(self, links, names):
            self._links = links
            self._names = names

        def uvLink(self, **kwargs):
            return self._links

        def getAttr(self, plug):
            return self._names.get(plug)

    saved_cmds = textures.cmds
    try:
        # Measured: uvLink names index 0 even for a texture nobody linked, so
        # the default answer must record nothing at all.
        textures.cmds = _UvCmds(
            ["shapeA.uvSet[0].uvSetName"],
            {"shapeA.uvSet[0].uvSetName": "map1"},
        )
        check(
            "default uv set records nothing",
            textures.uv_set_info("someFile") is None,
        )

        both = {
            "shapeA.uvSet[0].uvSetName": "map1",
            "shapeA.uvSet[1].uvSetName": "secondUV",
            "shapeB.uvSet[0].uvSetName": "map1",
        }
        textures.cmds = _UvCmds(["shapeA.uvSet[1].uvSetName"], both)
        check(
            "non-default uv set is recorded by name",
            textures.uv_set_info("someFile") == {"name": "secondUV"},
            repr(textures.uv_set_info("someFile")),
        )

        # A first set that is not called map1 is still the default one; the
        # rule is the index, not the name.
        textures.cmds = _UvCmds(
            ["shapeC.uvSet[0].uvSetName"],
            {"shapeC.uvSet[0].uvSetName": "renamedSet"},
        )
        check(
            "a renamed first set still counts as default",
            textures.uv_set_info("someFile") is None,
        )

        textures.cmds = _UvCmds(
            ["shapeA.uvSet[1].uvSetName", "shapeB.uvSet[0].uvSetName"], both
        )
        conflicted = textures.uv_set_info("someFile")
        check(
            "disagreeing meshes are reported, not resolved silently",
            conflicted == {
                "name": "secondUV",
                "conflict": ["secondUV", "map1"],
            },
            repr(conflicted),
        )
    finally:
        textures.cmds = saved_cmds

    class _UvNode(object):
        def __init__(self, name, uv_map):
            self.name = name
            self.uv_map = uv_map

    class _UvMaterial(dict):
        def __init__(self, name, nodes):
            dict.__init__(self)
            self["ml_generated"] = True
            self.name = name
            self.node_tree = type("_Tree", (object,), {"nodes": nodes})()

    def _uv_object(name, layers, materials):
        return type("_Obj", (object,), {
            "name": name,
            "data": type("_Mesh", (object,), {
                "uv_layers": [
                    type("_Layer", (object,), {"name": layer})()
                    for layer in layers
                ],
            })(),
            "material_slots": [
                type("_Slot", (object,), {"material": material})()
                for material in materials
            ],
        })()

    materials_module = importer.materials
    asking = _UvMaterial("ML_mat", [_UvNode("ML_UVMap", "secondUV")])
    found = materials_module.verify_uv_sets(
        [_uv_object("cube", ["map1", "secondUV"], [asking])], []
    )
    check("a uv set the mesh carries is silent", found == [], repr(found))

    missing = materials_module.verify_uv_sets(
        [
            _uv_object("cubeA", ["map1"], [asking]),
            _uv_object("cubeB", ["map1"], [asking]),
        ],
        [],
    )
    check(
        "a uv set no mesh carries is reported once, not per mesh",
        len(missing) == 1 and "secondUV" in missing[0],
        repr(missing),
    )

    print("\nevery layered blend mode is accounted for")
    exporter_modes = set(exporter.constants.LAYERED_BLEND_MODES)
    handled = set(importer.constants.LAYERED_BLEND_TYPES)
    replaced = {importer.constants.LAYERED_REPLACE_MODE}
    refused = set(importer.constants.LAYERED_UNSUPPORTED_MODES)
    check(
        "the three sets cover Maya's fourteen modes exactly",
        handled | replaced | refused == exporter_modes,
        "unaccounted {0}, unknown {1}".format(
            sorted(exporter_modes - handled - replaced - refused),
            sorted(handled | replaced | refused - exporter_modes),
        ),
    )
    check(
        "and no mode is in two of them",
        not (handled & refused) and not (handled & replaced)
        and not (refused & replaced),
        sorted((handled & refused) | (handled & replaced)
               | (refused & replaced)),
    )
    check(
        "the default mode is one the importer can build",
        exporter.constants.LAYERED_DEFAULT_BLEND_MODE in handled,
        exporter.constants.LAYERED_DEFAULT_BLEND_MODE,
    )

    print("\nplacement identity survived the uv rewrite")
    identity = materials_module._placement_is_identity
    check("an untouched placement is identity", identity({}))
    check(
        "repeat 1 and no offset is identity",
        identity({"repeat_u": 1.0, "repeat_v": 1.0, "offset": [0.0, 0.0]}),
    )
    for changed in (
        {"repeat_u": 4.0},
        {"repeat_v": 4.0},
        {"offset": [0.5, 0.0]},
        {"offset": [0.0, 0.5]},
        {"rotate_uv_degrees": 90.0},
        # Past the usual range on purpose: a rule that only looks at sensible
        # numbers hides the bug that narrows the range.
        {"repeat_u": -3.0},
    ):
        check(
            "{0!r} is not identity".format(changed),
            not identity(changed),
        )

    print("\na collected package survives being moved")
    check(
        "both sides name the same collected folders",
        set(importer.constants.COLLECTED_FOLDERS) == {
            exporter.constants.COLLECT_FOLDER_NAME,
            exporter.constants.FILE_COLLECT_FOLDER_NAME,
        },
        (importer.constants.COLLECTED_FOLDERS,
         exporter.constants.COLLECT_FOLDER_NAME,
         exporter.constants.FILE_COLLECT_FOLDER_NAME),
    )

    import shutil
    import tempfile

    resolve = importer.utils.resolve_package_paths
    package = tempfile.mkdtemp(prefix="mlender_contract_")
    try:
        textures = os.path.join(
            package, exporter.constants.COLLECT_FOLDER_NAME
        )
        files = os.path.join(
            package, exporter.constants.FILE_COLLECT_FOLDER_NAME
        )
        os.makedirs(textures)
        os.makedirs(files)
        for name, folder in (("wood.png", textures), ("wood.1001.png", textures),
                             ("smoke.vdb", files), ("proxy.abc", files)):
            with open(os.path.join(folder, name), "w") as handle:
                handle.write("x")
        present = os.path.join(package, "already_here.png")
        with open(present, "w") as handle:
            handle.write("x")

        payload = {
            "meshes": [{"materials": [{"channels": {
                "base_color": {"texture": {"path": "D:/gone/wood.png"}},
                "roughness": {"texture": {"path": present}},
                "opacity": {"texture": {
                    "path": "D:/gone/wood.<UDIM>.png",
                    "udim_pattern": "D:/gone/wood.<UDIM>.png",
                }},
                "emission": {"texture": {"layered": {"layers": [
                    {"color": {"texture": {"path": "D:/gone/wood.png"}}},
                ]}}},
            }}]}],
            "volumes": [{"file_path": "D:/gone/smoke.vdb"}],
            "standins": [{"file_path": "D:/gone/proxy.abc"}],
        }
        moved = resolve(payload, package)
        channels = payload["meshes"][0]["materials"][0]["channels"]
        check("a missing texture is found inside the package",
              channels["base_color"]["texture"]["path"].endswith(
                  "textures_collected/wood.png"),
              channels["base_color"]["texture"]["path"])
        check("a texture that still exists is left alone",
              channels["roughness"]["texture"]["path"] == present,
              channels["roughness"]["texture"]["path"])
        # A pattern is not a file, so isfile can never find it; the tiles are
        # what has to be looked for.
        check("a UDIM pattern is repointed by its tiles",
              channels["opacity"]["texture"]["path"].endswith(
                  "textures_collected/wood.<UDIM>.png"),
              channels["opacity"]["texture"]["path"])
        check("a texture inside a layered stack is reached too",
              (channels["emission"]["texture"]["layered"]["layers"][0]
               ["color"]["texture"]["path"]).endswith("wood.png"),
              channels["emission"]["texture"]["layered"]["layers"][0])
        check("volumes and standins are repointed as well",
              payload["volumes"][0]["file_path"].endswith("smoke.vdb")
              and payload["standins"][0]["file_path"].endswith("proxy.abc")
              and "files_collected" in payload["standins"][0]["file_path"],
              (payload["volumes"][0], payload["standins"][0]))
        check("and the Maya original is kept",
              channels["base_color"]["texture"]["original_package_path"]
              == "D:/gone/wood.png",
              channels["base_color"]["texture"].get("original_package_path"))
        check("the count is what was moved, not what was looked at",
              moved == 6, moved)

        untouched = {"volumes": [{"file_path": "D:/gone/smoke.vdb"}]}
        check("a package folder that is not there changes nothing",
              resolve(untouched, os.path.join(package, "no_such")) == 0
              and untouched["volumes"][0]["file_path"] == "D:/gone/smoke.vdb",
              untouched)
    finally:
        shutil.rmtree(package, ignore_errors=True)

    print("\nschema validation guards the scene")
    validate = importer.importer.validate_schema_version
    check("current schema accepted", validate({"schema_version": 2}) == 2)
    check("legacy package assumed to be schema 1", validate({}) == 1)
    for bad in ({"schema_version": 99}, {"schema_version": "abc"}):
        try:
            validate(bad)
            check("rejects {0!r}".format(bad), False, "no error raised")
        except ValueError:
            check("rejects {0!r}".format(bad), True)

    print()
    if failures:
        print("FAILURES ({0}):".format(len(failures)))
        for item in failures:
            print("  - {0}".format(item))
        return 1
    print("all contract checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
