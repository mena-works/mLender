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


# ------------------------------------------------------------------- checks
def main():
    install_stubs()
    if TOOL_ROOT not in sys.path:
        sys.path.insert(0, TOOL_ROOT)

    print("import graph")
    import za_lookdev_exporter as exporter
    import za_lookdev_importer as importer
    check("exporter package imports", True)
    check("importer package imports", True)

    for attr in ("show_ui", "show", "export_lookdev", "reload_package"):
        check("exporter exposes {0}".format(attr), hasattr(exporter, attr))
    for attr in ("register", "unregister", "import_lookdev_package", "bl_info"):
        check("importer exposes {0}".format(attr), hasattr(importer, attr))

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
    # rendering matched scenes in both; see tests/light_calibration.md.
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
