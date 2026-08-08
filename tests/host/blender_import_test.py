# -*- coding: utf-8 -*-
"""End-to-end import test against a real headless Blender.

Imports the package written by maya_export_test.py and asserts on the actual
node trees and light data Blender ends up with.

    "C:\\Program Files\\Blender Foundation\\Blender 5.2\\blender.exe" ^
        --background --factory-startup --python tests/host/blender_import_test.py

Run maya_export_test.py first; this reads its output from
<temp>/mlender_test/mLender_01.
"""
import glob
import math
import os
import sys
import tempfile

import bpy

# Three levels up: tests/<group>/<file>.py
TOOL_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)
TEST_ROOT = os.path.join(tempfile.gettempdir(), "mlender_test")

if TOOL_ROOT not in sys.path:
    sys.path.insert(0, TOOL_ROOT)

failures = []


def check(label, condition, detail=""):
    if condition:
        print("  ok    {0}".format(label))
    else:
        failures.append("{0} {1}".format(label, detail))
        print("  FAIL  {0}  {1}".format(label, detail))


def find_package():
    packages = sorted(glob.glob(os.path.join(TEST_ROOT, "mLender_*")))
    if not packages:
        raise SystemExit(
            "No package in {0}. Run maya_export_test.py first.".format(TEST_ROOT)
        )
    return packages[-1]


def fcurves_of(action):
    """Actions became slotted in 4.4 and Action.fcurves went away in 5.0."""
    from mlender_importer.animation import action_fcurves

    return action_fcurves(action)


def object_named(fragment):
    for obj in bpy.data.objects:
        if fragment.lower() in obj.name.lower():
            return obj
    return None


def material_for(fragment):
    """Find a material by its Maya name, exact stem first.

    Substring alone is ambiguous: "lambertCube" is inside "aiLambertCube_shd",
    so the native shader's assertions silently ran against the Arnold one.
    """
    wanted = fragment.lower()
    fallback = None
    for material in bpy.data.materials:
        name = str(material.get("ml_maya_material", "")).lower()
        if name == wanted or name == wanted + "_shd":
            return material
        if fallback is None and wanted in name:
            fallback = material
    return fallback


def bsdf_of(material):
    return next(
        (n for n in material.node_tree.nodes
         if n.bl_idname == "ShaderNodeBsdfPrincipled"),
        None,
    )


def socket(material, name):
    bsdf = bsdf_of(material)
    if bsdf is None:
        return None
    return bsdf.inputs.get(name)


def value(material, name):
    found = socket(material, name)
    return None if found is None else found.default_value


def main():
    import mlender_importer as zi

    print("Blender {0}, importer build {1}".format(
        bpy.app.version_string, zi.BUILD_VERSION))

    result = zi.import_scene_package(find_package(), import_scale=1.0)
    print("meshes={0} materials={1} subdiv={2} lights={3} domes={4}".format(
        result["mesh_count"], result["material_count"],
        result["subdivision_count"], result["light_count"],
        result["dome_count"]))
    for warning in result["warnings"]:
        print("  warn: {0}".format(warning))

    print("\nscene")
    check("22 meshes imported", result["mesh_count"] == 22,
          result["mesh_count"])
    check("17 materials built", result["material_count"] == 17,
          result["material_count"])
    # Four of the eight cubes asked for subdivision in Maya, the displaced one
    # among them; the rest must arrive unmodified.
    check("only the meshes that asked are subdivided",
          result["subdivision_count"] == 4, result["subdivision_count"])

    print("\naiStandardSurface")
    std = material_for("stdSurfCube")
    check("material exists", std is not None)
    if std:
        check("metallic 0.75", abs(value(std, "Metallic") - 0.75) < 1e-5)
        check("roughness 0.33", abs(value(std, "Roughness") - 0.33) < 1e-5)
        check("alpha 0.5, not inverted", abs(value(std, "Alpha") - 0.5) < 1e-5,
              value(std, "Alpha"))
        check("emission strength 0.4",
              abs(value(std, "Emission Strength") - 0.4) < 1e-5)
        check("base colour driven by a texture",
              socket(std, "Base Color").is_linked)

    print("\ngroup collections")
    root = bpy.data.collections.get(result["root_collection"])
    check("root collection exists", root is not None)
    set_dressing = bpy.data.collections.get("setDressing")
    props = bpy.data.collections.get("props")
    check("outer group became a collection under the root",
          set_dressing is not None
          and set_dressing.name in {c.name for c in root.children})
    check("inner group nests inside the outer one",
          props is not None and set_dressing is not None
          and props.name in {c.name for c in set_dressing.children})
    grouped = object_named("stdSurfCube")
    ungrouped = object_named("flatCube")
    # Light linking collections are a mechanism, not scene organisation, so a
    # mesh can legitimately be in a receiver or a blocker collection too.
    def scene_collections(obj):
        return [
            c.name for c in obj.users_collection
            if not c.name.startswith(("ML_Link_", "ML_Shadow_"))
        ]

    check("the mesh sits in the innermost collection only",
          grouped is not None and scene_collections(grouped) == ["props"],
          [c.name for c in grouped.users_collection] if grouped else None)
    check("collections are marked as ours",
          props is not None and props.get("ml_generated") is True)
    check("an ungrouped mesh stays at the root",
          ungrouped is not None
          and scene_collections(ungrouped) == [result["root_collection"]],
          [c.name for c in ungrouped.users_collection] if ungrouped else None)
    check("six collections were reported",
          result["group_collection_count"] == 6,
          result["group_collection_count"])

    print("\ninstances")
    # Maya instances share a shape. Before this they were dropped on the way
    # out entirely; now they arrive and must share one mesh datablock, while a
    # real duplicate of the same cube must keep its own.
    source = bpy.data.objects.get("instSource")
    inst_a = bpy.data.objects.get("instA")
    inst_b = bpy.data.objects.get("instB")
    copy = bpy.data.objects.get("instCopy")
    for name, obj in (("instSource", source), ("instA", inst_a),
                      ("instB", inst_b), ("instCopy", copy)):
        check("{0} arrived".format(name), obj is not None)
    if source and inst_a and inst_b and copy:
        check("both instances share the source's mesh data",
              inst_a.data is source.data and inst_b.data is source.data,
              [inst_a.data.name, inst_b.data.name, source.data.name])
        check("a real duplicate keeps its own",
              copy.data is not source.data, copy.data.name)
        check("the shared datablock is named after Maya's first parent",
              source.data.name == "instSource", source.data.name)
        check("three users on the shared mesh", source.data.users == 3,
              source.data.users)
        # Sharing geometry must not have merged the objects themselves.
        xs = sorted(round(o.location.x, 4)
                    for o in (source, inst_a, inst_b, copy))
        check("each instance kept its own transform", len(set(xs)) == 4, xs)
        check("the import reported the instances",
              result["instanced_count"] == 2, result["instanced_count"])

    print("\ntransforms with no geometry")
    # None of these ride the FBX, so before they were exported they simply
    # were not here. The mesh under a mesh is the control: that one the FBX
    # does carry, and its parent must survive.
    locator = bpy.data.objects.get("probeLocator")
    control_group = bpy.data.objects.get("controlGroup")
    nested = bpy.data.objects.get("nestedLocator")
    child_mesh = bpy.data.objects.get("childMesh")
    parent_mesh = bpy.data.objects.get("parentMesh")
    for name, obj in (("probeLocator", locator), ("controlGroup", control_group),
                      ("nestedLocator", nested)):
        check("{0} arrived".format(name), obj is not None)
        if obj is not None:
            check("{0} is an empty".format(name), obj.type == "EMPTY", obj.type)
    check("the import reported them", result["transform_count"] == 4,
          result["transform_count"])
    if locator:
        # Maya Y becomes Blender Z, and the scene is in centimetres, so 7
        # units up is 0.07 m. Passing the raw import scale instead of the unit
        # conversion put it a hundred times too far out.
        z = locator.matrix_world.translation.z
        check("a locator lands where Maya had it", abs(z - 0.07) < 1e-4, z)
    if nested and control_group:
        check("a nested locator keeps its parent",
              nested.parent is control_group,
              nested.parent.name if nested.parent else None)
        # The group's own empty belongs with its contents, not beside them.
        names = {c.name for c in nested.users_collection}
        check("and shares its group's collection",
              names == {c.name for c in control_group.users_collection}
              and "controlGroup" in names, sorted(names))
    if child_mesh and parent_mesh:
        check("a mesh parented under a mesh keeps its parent",
              child_mesh.parent is parent_mesh,
              child_mesh.parent.name if child_mesh.parent else None)
    # An FBX-brought group empty must land in its collection too, or the
    # outliner shows the control at the root and its contents a level down.
    set_dressing_empty = bpy.data.objects.get("setDressing")
    if set_dressing_empty:
        check("an FBX group empty sits in its own collection",
              "setDressing" in {c.name
                                for c in set_dressing_empty.users_collection},
              [c.name for c in set_dressing_empty.users_collection])

    print("\ncurves")
    # Curves never rode the FBX, so before this they were simply absent.
    probe_curve = bpy.data.objects.get("probeCurve")
    probe_line = bpy.data.objects.get("probeLine")
    probe_circle = bpy.data.objects.get("probeCircle")
    check("the import reported 3 curves", result["curve_count"] == 3,
          result["curve_count"])
    for name, obj in (("probeCurve", probe_curve), ("probeLine", probe_line),
                      ("probeCircle", probe_circle)):
        check("{0} arrived as a curve".format(name),
              obj is not None and obj.type == "CURVE",
              obj.type if obj else None)
    if probe_line:
        spline = probe_line.data.splines[0]
        check("a degree 1 curve becomes a poly spline",
              spline.type == "POLY", spline.type)
        check("with its three points", len(spline.points) == 3,
              len(spline.points))
    if probe_curve:
        spline = probe_curve.data.splines[0]
        check("a cubic becomes a NURBS spline of order 4",
              spline.type == "NURBS" and spline.order_u == 4,
              (spline.type, spline.order_u))
        check("open, so endpoint knots and no cycle",
              spline.use_endpoint_u and not spline.use_cyclic_u,
              (spline.use_endpoint_u, spline.use_cyclic_u))
        # Maya had this ten units up on a transform scaled by two. Setting
        # matrix_world and then obj.scale looks equivalent and is not; it came
        # through at half size.
        world = probe_curve.matrix_world @ spline.points[1].co.to_3d()
        check("a scaled transform reaches the control points",
              abs(world.x - 0.0346) < 1e-3 and abs(world.z - 0.14) < 1e-3,
              [round(v, 4) for v in world])
    if probe_circle:
        spline = probe_circle.data.splines[0]
        check("a periodic circle is cyclic", spline.use_cyclic_u)
        check("and endpoint knots are off, which would kink the seam",
              not spline.use_endpoint_u)
        check("with 8 points, not the 11 Maya reports",
              len(spline.points) == 8, len(spline.points))
        # Reading control points the obvious way returns zeros for a curve
        # built by construction history, which a circle is.
        moved = any(abs(p.co[i]) > 1e-6 for p in spline.points
                    for i in range(3))
        check("its points are not all at the origin", moved)
        check("a grouped curve lands in its collection",
              "curveGroup" in {c.name for c in probe_circle.users_collection},
              [c.name for c in probe_circle.users_collection])

    print("\nvalues outside the usual range")
    # The emission clamp survived every test because nothing ever asked for a
    # value past a limit. These assertions exist to keep that from recurring.
    extreme = material_for("extremeCube")
    check("the extreme material exists", extreme is not None)
    if extreme:
        emission = value(extreme, "Emission Color")
        check("an emission colour of 8 is not clamped to 1",
              emission is not None and abs(emission[0] - 8.0) < 1e-4,
              list(emission) if emission is not None else None)
        radius = value(extreme, "Subsurface Radius")
        check("a subsurface radius of 5 is not clamped to 1",
              radius is not None and abs(radius[0] - 5.0) < 1e-4,
              list(radius) if radius is not None else None)
        check("an IOR of 2.4 survives", abs(value(extreme, "IOR") - 2.4) < 1e-4,
              value(extreme, "IOR"))
        coat_ior = socket(extreme, "Coat IOR")
        check("a coat IOR of 2.0 survives",
              coat_ior is None or abs(coat_ior.default_value - 2.0) < 1e-4,
              coat_ior.default_value if coat_ior else None)
        check("roughness of exactly zero stays zero",
              abs(value(extreme, "Roughness")) < 1e-6,
              value(extreme, "Roughness"))
        check("metallic of exactly one stays one",
              abs(value(extreme, "Metallic") - 1.0) < 1e-6,
              value(extreme, "Metallic"))

    boost = object_named("boostLight")
    check("the boosted light exists", boost is not None)
    if boost:
        colour = list(boost.data.color)
        check("a light colour of 3,2,1 is not clamped to white",
              abs(colour[0] - 3.0) < 1e-4 and abs(colour[1] - 2.0) < 1e-4,
              colour)

    print("\nedge cases")
    # Two Maya meshes share the short name "twin" under different groups. The
    # importer pairs records to objects by name, so this is exactly where a
    # silent swap would happen. They sit at opposite x, so a swap is visible.
    set_a = bpy.data.collections.get("setA")
    set_b = bpy.data.collections.get("setB")
    # Meshes only: a group's collection also holds the group's own empty, so
    # indexing objects[0] would silently test whichever came first.
    def meshes_in(collection):
        if collection is None:
            return []
        return [obj for obj in collection.objects if obj.type == "MESH"]

    a_meshes = meshes_in(set_a)
    b_meshes = meshes_in(set_b)
    check("both same-named meshes got their own collection",
          len(a_meshes) == 1 and len(b_meshes) == 1,
          (len(a_meshes), len(b_meshes)))
    if a_meshes and b_meshes:
        a_x = a_meshes[0].matrix_world.translation.x
        b_x = b_meshes[0].matrix_world.translation.x
        check("the mesh in setA is the one Maya had in setA",
              a_x > 0.0 and b_x < 0.0, (round(a_x, 4), round(b_x, 4)))
        check("they are two distinct objects", a_meshes[0] is not b_meshes[0])

    accented = next(
        (obj for obj in bpy.data.objects
         if obj.type == "MESH" and not obj.name.isascii()),
        None,
    )
    check("a non-ASCII mesh name survived the round trip",
          accented is not None,
          [o.name for o in bpy.data.objects if o.type == "MESH"][:12])

    missing_material = material_for("accentedShaded")
    check("a material whose texture is missing is still built",
          missing_material is not None)
    check("the missing texture was reported, not swallowed",
          any("definitely_not_here" in warning
              for warning in result["warnings"]))
    if missing_material:
        check("its base colour socket still has a usable value",
              socket(missing_material, "Base Color") is not None)

    print("\nrebuilt colour correction")
    if std:
        by_name = {node.name: node for node in std.node_tree.nodes}
        gamma_nodes = [
            node for node in std.node_tree.nodes
            if node.bl_idname == "ShaderNodeGamma"
        ]
        # gammaCorrect 2.2 and aiColorCorrect 2.0, both reciprocated because
        # Maya raises to 1/gamma while Blender's node raises to gamma.
        exponents = sorted(
            round(node.inputs[1].default_value, 5) for node in gamma_nodes
        )
        check("both gammas rebuilt as their reciprocal",
              exponents == [round(1.0 / 2.2, 5), 0.5], exponents)

        hue_sat = by_name.get("ML_CC_Hue_Saturation")
        check("saturation 0.5 rebuilt", hue_sat is not None
              and abs(hue_sat.inputs[1].default_value - 0.5) < 1e-5)
        check("hue left neutral at 0.5", hue_sat is not None
              and abs(hue_sat.inputs[0].default_value - 0.5) < 1e-5)

        # exposure 1 folds into multiply, so the red channel is 2 * 2 = 4.
        multiply = by_name.get("ML_CC_Multiply")
        check("exposure folded into the multiply", multiply is not None
              and abs(multiply.inputs[2].default_value[0] - 4.0) < 1e-5,
              multiply.inputs[2].default_value[:] if multiply else None)
        check("green channel carries exposure alone", multiply is not None
              and abs(multiply.inputs[2].default_value[1] - 2.0) < 1e-5)

        check("the corrected colour, not the raw image, reaches the socket",
              socket(std, "Base Color").links[0].from_node.name.startswith("ML_CC"),
              socket(std, "Base Color").links[0].from_node.name)

        check("a node with no builder is still reported",
              any("aiComposite" in warning for warning in result["warnings"]),
              result["warnings"])

        ramp_node = by_name.get("ML_Remap_Ramp")
        check("the remapValue curve became a Colour Ramp",
              ramp_node is not None, sorted(by_name))
        if ramp_node:
            stops = [
                (round(e.position, 3), round(e.color[0], 3))
                for e in ramp_node.color_ramp.elements
            ]
            check("all three stops rebuilt with their values",
                  stops == [(0.0, 0.0), (0.4, 0.9), (1.0, 1.0)], stops)
            check("Maya's Linear interpolation became Blender's LINEAR",
                  ramp_node.color_ramp.interpolation == "LINEAR",
                  ramp_node.color_ramp.interpolation)

        check("clamp rebuilt as a max then a min",
              by_name.get("ML_Clamp_Min") is not None
              and by_name.get("ML_Clamp_Max") is not None,
              sorted(n for n in by_name if "Clamp" in n))
        clamp_max = by_name.get("ML_Clamp_Max")
        if clamp_max:
            check("the ceiling is a per-channel minimum",
                  clamp_max.blend_type == "DARKEN"
                  and abs(clamp_max.inputs[2].default_value[0] - 0.75) < 1e-5,
                  (clamp_max.blend_type,
                   clamp_max.inputs[2].default_value[0]))

        blend_node = by_name.get("ML_Blend_Colors")
        check("blendColors rebuilt", blend_node is not None)
        if blend_node:
            # Maya blender 0.25 keeps a quarter of color1, and Blender's
            # Factor runs the other way, so it must be 0.75.
            check("the blend factor was inverted for Blender",
                  abs(blend_node.inputs[0].default_value - 0.75) < 1e-5,
                  blend_node.inputs[0].default_value)
            check("the texture stayed on the side Maya had it",
                  blend_node.inputs[1].is_linked,
                  (blend_node.inputs[1].is_linked,
                   blend_node.inputs[2].is_linked))

    print("\nlight linking")
    area_light = object_named("aiArea")
    check("the restricted light imported", area_light is not None)
    if area_light is not None:
        linking = getattr(area_light, "light_linking", None)
        check("this Blender has light linking", linking is not None)
        if linking is not None:
            receivers = linking.receiver_collection
            check("a receiver collection was built", receivers is not None,
                  receivers)
            if receivers:
                names = {obj.name for obj in receivers.objects}
                check("the unlinked meshes are not receivers",
                      not any(n.startswith(("flatCube", "glassCube"))
                              for n in names),
                      sorted(names))
                check("the linked meshes are receivers",
                      any(n.startswith("stdSurfCube") for n in names),
                      sorted(names))
                check("the receiver collection stays out of the scene tree",
                      receivers.name not in
                      {c.name for c in bpy.context.scene.collection.children},
                      receivers.name)

    if area_light is not None:
        linking = getattr(area_light, "light_linking", None)
        blockers = getattr(linking, "blocker_collection", None) if linking else None
        check("shadow linking became a blocker collection", blockers is not None,
              blockers)
        if blockers:
            blocked = {obj.name for obj in blockers.objects}
            check("the shadow-unlinked mesh is not a blocker",
                  not any(n.startswith("openPbrCube") for n in blocked),
                  sorted(blocked))
            receivers = linking.receiver_collection
            receiver_names = (
                {o.name for o in receivers.objects} if receivers else set()
            )
            check("blockers and receivers are genuinely different sets",
                  blocked != receiver_names,
                  (sorted(blocked), sorted(receiver_names)))

    ies_light = object_named("aiIes")
    if ies_light is not None:
        linking = getattr(ies_light, "light_linking", None)
        check("an unrestricted light gets no receiver collection",
              linking is None or linking.receiver_collection is None,
              linking.receiver_collection if linking else None)

    print("\ncolour management")
    # Blender's stock config has no ACES view transform on any installed
    # version, so on this machine the honest outcome is a fallback plus a
    # warning naming the config. A build with an ACES OCIO config would match
    # exactly instead, and both are correct behaviour.
    view_settings = bpy.context.scene.view_settings
    applied = result["view_transform"]
    check("some view transform was applied", bool(applied), applied)
    check("the applied transform is one Blender actually has",
          view_settings.view_transform == applied,
          (view_settings.view_transform, applied))
    matched = applied.startswith("ACES")
    if matched:
        check("this Blender has an ACES config, so it matched exactly", True)
    else:
        check("a mismatch is reported rather than left silent",
              any("view transform" in warning for warning in result["warnings"]),
              result["warnings"])
        check("the warning names the OCIO config to point Blender at",
              any(".ocio" in warning for warning in result["warnings"]),
              [w for w in result["warnings"] if "view transform" in w])
        check("AgX was not left in place pretending to match",
              view_settings.view_transform != "AgX",
              view_settings.view_transform)

    print("\nvisibility flags")
    shadow_only = object_named("glassCube")
    check("shadow-only object is hidden from the camera",
          shadow_only is not None and shadow_only.visible_camera is False,
          shadow_only.visible_camera if shadow_only else None)
    check("but still casts a shadow",
          shadow_only is not None and shadow_only.visible_shadow is True,
          shadow_only.visible_shadow if shadow_only else None)
    check("glossy visibility off",
          shadow_only is not None and shadow_only.visible_glossy is False)
    check("untouched ray visibility left alone",
          shadow_only is not None and shadow_only.visible_diffuse is True)

    matte = object_named("aiLambertCube")
    check("aiMatte became a holdout",
          matte is not None and matte.is_holdout is True,
          matte.is_holdout if matte else None)

    hidden = object_named("openPbrCube")
    check("a hidden Maya mesh is hidden in the render too",
          hidden is not None and hidden.hide_render and hidden.hide_viewport,
          (hidden.hide_render, hidden.hide_viewport) if hidden else None)

    ordinary = object_named("stdSurfCube")
    check("an ordinary mesh keeps every default",
          ordinary is not None
          and ordinary.visible_camera and ordinary.visible_shadow
          and not ordinary.is_holdout and not ordinary.hide_render)
    check("three meshes reported as having flags",
          result["visibility_count"] == 3, result["visibility_count"])

    print("\nanimation")
    scene = bpy.context.scene
    check("import reports it animated", result["animated"] is True)
    check("scene range set to 1-25",
          (scene.frame_start, scene.frame_end) == (1, 25),
          (scene.frame_start, scene.frame_end))
    check("fps 24 with a base of 1",
          scene.render.fps == 24 and abs(scene.render.fps_base - 1.0) < 1e-6,
          (scene.render.fps, scene.render.fps_base))

    # Mesh animation rides the FBX rather than the JSON, so it is worth
    # asserting separately: the camera passing proves only the JSON path.
    animated_mesh = object_named("flatCube")
    mesh_action = getattr(
        getattr(animated_mesh, "animation_data", None), "action", None
    )
    check("the animated mesh arrived with animation", mesh_action is not None,
          animated_mesh.name if animated_mesh else None)
    if mesh_action:
        loc_x = next(
            (c for c in fcurves_of(mesh_action)
             if c.data_path == "location" and c.array_index == 0),
            None,
        )
        check("mesh translation is keyed", loc_x is not None
              and len(loc_x.keyframe_points) >= 2,
              len(loc_x.keyframe_points) if loc_x else None)
        if loc_x:
            span = abs(loc_x.keyframe_points[-1].co[1]
                       - loc_x.keyframe_points[0].co[1])
            # 8 Maya centimetres is 0.08 Blender metres.
            check("mesh moved 8 Maya units, so 0.08 in Blender",
                  abs(span - 0.08) < 1e-3, span)

    turntable = object_named("turntableCam")
    check("turntable camera imported", turntable is not None)
    if turntable:
        action = getattr(
            getattr(turntable, "animation_data", None), "action", None
        )
        check("the camera object is keyed", action is not None)
        if action:
            rot_z = next(
                (c for c in fcurves_of(action)
                 if c.data_path == "rotation_euler" and c.array_index == 2),
                None,
            )
            check("rotation is keyed on every frame",
                  rot_z is not None and len(rot_z.keyframe_points) == 25,
                  len(rot_z.keyframe_points) if rot_z else None)
            if rot_z:
                values = [p.co[1] for p in rot_z.keyframe_points]
                # A full turn decomposed per frame would wrap at pi and read
                # as a sudden jump back; compatible Eulers keep it monotonic.
                steps = [abs(b - a) for a, b in zip(values, values[1:])]
                check("no Euler flip across the full turn",
                      max(steps) < math.pi / 2.0,
                      "largest step {0:.4f} rad".format(max(steps)))
                check("the turn actually spans a full circle",
                      abs(abs(values[-1] - values[0]) - 2.0 * math.pi) < 1e-3,
                      abs(values[-1] - values[0]))
                check("baked samples use linear interpolation",
                      all(p.interpolation == "LINEAR"
                          for p in rot_z.keyframe_points),
                      {p.interpolation for p in rot_z.keyframe_points})

        lens_action = getattr(
            getattr(turntable.data, "animation_data", None), "action", None
        )
        lens_curve = None
        if lens_action:
            lens_curve = next(
                (c for c in fcurves_of(lens_action) if c.data_path == "lens"),
                None,
            )
        check("focal length is keyed on the camera data",
              lens_curve is not None and len(lens_curve.keyframe_points) == 25,
              len(lens_curve.keyframe_points) if lens_curve else None)
        if lens_curve:
            first = lens_curve.keyframe_points[0].co[1]
            last = lens_curve.keyframe_points[-1].co[1]
            check("focal length runs 35 to 85",
                  abs(first - 35.0) < 1e-3 and abs(last - 85.0) < 1e-3,
                  (first, last))

    print("\ndisplacement")
    displaced = material_for("dispCube")
    check("displaced material exists", displaced is not None)
    if displaced:
        node = next(
            (n for n in displaced.node_tree.nodes
             if n.bl_idname == "ShaderNodeDisplacement"),
            None,
        )
        check("Displacement node built", node is not None)
        if node:
            check("height map drives the Height socket", node.inputs[0].is_linked)
            check("Maya zero value became Midlevel 0.5",
                  abs(node.inputs[1].default_value - 0.5) < 1e-5,
                  node.inputs[1].default_value)
            # aiDispHeight 0.25 times displacementShader scale 2.0. Set
            # explicitly because the socket default is 1.0 on 4.1 and 0.01
            # on 5.2.
            check("scale is height times node scale = 0.5",
                  abs(node.inputs[2].default_value - 0.5) < 1e-5,
                  node.inputs[2].default_value)
            check("object space, so no unit scale is folded in",
                  getattr(node, "space", "OBJECT") == "OBJECT",
                  getattr(node, "space", None))
            check("wired into the material output",
                  node.outputs[0].is_linked
                  and node.outputs[0].links[0].to_socket.name == "Displacement")
        check("autobump became the BOTH method",
              getattr(displaced, "displacement_method", None) == "BOTH",
              getattr(displaced, "displacement_method", None))

    undisplaced = material_for("flatCube")
    check("an undisplaced material builds no Displacement node",
          undisplaced is not None
          and not any(n.bl_idname == "ShaderNodeDisplacement"
                      for n in undisplaced.node_tree.nodes))

    print("\naiOpenPBRSurface")
    pbr = material_for("openPbrCube")
    check("material exists", pbr is not None)
    if pbr:
        check("metallic 1.0", abs(value(pbr, "Metallic") - 1.0) < 1e-5)
        check("alpha 0.25", abs(value(pbr, "Alpha") - 0.25) < 1e-5)
        # 250 nits over the measured 1000, not the 100 that was guessed at
        # first: rendering both sides put Blender ten times too bright.
        check("250 nits scaled to emission strength 0.25",
              abs(value(pbr, "Emission Strength") - 0.25) < 1e-5,
              value(pbr, "Emission Strength"))
        # The same 0.25 the standard surface cube carries. OpenPBR's fuzz is
        # the lobe Blender already implements, so this one passes straight
        # through; remapping it would break a match that is already right.
        fuzz = value(pbr, "Sheen Roughness")
        check("fuzz roughness 0.25 passed through unremapped",
              fuzz is not None and abs(fuzz - 0.25) < 1e-5, fuzz)
        check("and no source value recorded, nothing having been changed",
              "ml_source_sheen_roughness" not in pbr.keys())

    print("\naiFlat")
    flat = material_for("flatCube")
    check("material exists", flat is not None)
    if flat:
        ids = {n.bl_idname for n in flat.node_tree.nodes}
        check("built unlit: Emission + Transparent + Mix",
              {"ShaderNodeEmission", "ShaderNodeBsdfTransparent",
               "ShaderNodeMixShader"} <= ids, sorted(ids))
        check("no Principled node", "ShaderNodeBsdfPrincipled" not in ids)
        emission = next((n for n in flat.node_tree.nodes
                         if n.bl_idname == "ShaderNodeEmission"), None)
        if emission:
            colour = [round(c, 3)
                      for c in emission.inputs["Color"].default_value[:3]]
            check("emission colour survived the round trip",
                  colour == [0.1, 0.9, 0.4], colour)

    print("\naiLambert")
    lam = material_for("aiLambertCube")
    check("material exists", lam is not None)
    if lam:
        check("roughness pinned to the lambert approximation 0.7",
              abs(value(lam, "Roughness") - 0.7) < 1e-5)
        check("alpha 0.8, not inverted to 0.2",
              abs(value(lam, "Alpha") - 0.8) < 1e-5, value(lam, "Alpha"))

    print("\nnative Maya shaders")
    # Maya states transparency, Blender wants opacity. Arnold's opacity is
    # already opacity, so only this family is inverted and only here.
    native_lam = material_for("lambertCube")
    check("lambert material exists", native_lam is not None)
    if native_lam:
        check("transparency 0.25 arrived as alpha 0.75",
              abs(value(native_lam, "Alpha") - 0.75) < 1e-5,
              value(native_lam, "Alpha"))
        base = value(native_lam, "Base Color")
        check("base colour survived",
              base is not None and abs(base[0] - 0.4) < 1e-4
              and abs(base[1] - 0.6) < 1e-4,
              list(base) if base is not None else None)
        check("roughness pinned to the lambert approximation",
              abs(value(native_lam, "Roughness") - 0.7) < 1e-5,
              value(native_lam, "Roughness"))

    native_blinn = material_for("blinnCube")
    check("blinn material exists", native_blinn is not None)
    if native_blinn:
        alpha = socket(native_blinn, "Alpha")
        check("a textured transparency reaches alpha at all",
              alpha is not None and alpha.is_linked)
        # The exporter cannot invert a map, so it sends the flag and the
        # importer owes us a 1-x node. Without it the mesh renders inside out.
        def upstream_ids(sock, depth=6):
            found = set()
            if depth <= 0 or sock is None or not sock.is_linked:
                return found
            node = sock.links[0].from_node
            found.add((node.bl_idname, getattr(node, "operation", "")))
            for downstream in node.inputs:
                found |= upstream_ids(downstream, depth - 1)
            return found

        chain = upstream_ids(alpha) if alpha else set()
        check("and an invert sits between the map and the socket",
              ("ShaderNodeMath", "SUBTRACT") in chain, sorted(chain))
        check("the map itself is in the chain",
              any(i[0] == "ShaderNodeTexImage" for i in chain), sorted(chain))
        check("roughness pinned to the blinn approximation",
              abs(value(native_blinn, "Roughness") - 0.1) < 1e-5,
              value(native_blinn, "Roughness"))

    native_surface = material_for("surfaceCube")
    check("surfaceShader material exists", native_surface is not None)
    if native_surface:
        ids = {n.bl_idname for n in native_surface.node_tree.nodes}
        check("built unlit, like aiFlat",
              {"ShaderNodeEmission", "ShaderNodeBsdfTransparent",
               "ShaderNodeMixShader"} <= ids, sorted(ids))
        emission = next((n for n in native_surface.node_tree.nodes
                         if n.bl_idname == "ShaderNodeEmission"), None)
        if emission:
            colour = [round(c, 3)
                      for c in emission.inputs["Color"].default_value[:3]]
            check("outColor drives emission", colour == [0.9, 0.3, 0.1], colour)
        mix = next((n for n in native_surface.node_tree.nodes
                    if n.bl_idname == "ShaderNodeMixShader"), None)
        check("outTransparency 0.2 became a mix factor of 0.8",
              mix is not None and abs(mix.inputs[0].default_value - 0.8) < 1e-5,
              mix.inputs[0].default_value if mix else None)

    print("\nglass")
    glass = material_for("glassCube")
    check("material exists", glass is not None)
    if glass:
        ids = {n.bl_idname for n in glass.node_tree.nodes}
        check("built as a Glass BSDF, not Principled",
              "ShaderNodeBsdfGlass" in ids
              and "ShaderNodeBsdfPrincipled" not in ids,
              sorted(ids))
        node = next((n for n in glass.node_tree.nodes
                     if n.bl_idname == "ShaderNodeBsdfGlass"), None)
        if node:
            colour = [round(c, 3) for c in node.inputs["Color"].default_value[:3]]
            check("transmission colour carried", colour == [0.2, 0.9, 0.8], colour)
            check("transmission roughness 0.05",
                  abs(node.inputs["Roughness"].default_value - 0.05) < 1e-5,
                  node.inputs["Roughness"].default_value)
            check("ior 1.52", abs(node.inputs["IOR"].default_value - 1.52) < 1e-5,
                  node.inputs["IOR"].default_value)
        check("thin walled recorded", glass.get("ml_thin_walled") is True,
              glass.get("ml_thin_walled"))
        check("material mode recorded",
              glass.get("ml_material_mode") == "GLASS_BSDF",
              glass.get("ml_material_mode"))
    check("a non refractive material stays Principled",
          bsdf_of(material_for("stdSurfCube")) is not None)

    print("\nUDIM")
    image = None
    if lam:
        node = next((n for n in lam.node_tree.nodes
                     if n.bl_idname == "ShaderNodeTexImage"), None)
        image = node.image if node else None
    check("aiLambert base colour loaded an image", image is not None)
    if image:
        check("image is tiled", image.source == "TILED", image.source)
        check("udim marked on the image", image.get("ml_udim") is True)
        check("all three tiles registered", len(image.tiles) == 3,
              [tile.number for tile in image.tiles])

    print("\nsubdivision")

    def modifier_of(fragment):
        obj = None
        for candidate in bpy.data.objects:
            if (candidate.type == "MESH"
                    and fragment.lower() in candidate.name.lower()):
                obj = candidate
        return obj, (obj.modifiers.get("mLender Subdivision") if obj else None)

    plain_obj, plain_mod = modifier_of("stdSurfCube")
    check("the plain cube has no subdivision modifier",
          plain_obj is not None and plain_mod is None,
          [m.name for m in plain_obj.modifiers] if plain_obj else None)

    _pbr_obj, pbr_mod = modifier_of("openPbrCube")
    check("the catclark cube has one", pbr_mod is not None)
    if pbr_mod:
        check("type is Catmull-Clark",
              pbr_mod.subdivision_type == "CATMULL_CLARK",
              pbr_mod.subdivision_type)
        check("render levels follow Maya's 3",
              pbr_mod.render_levels == 3, pbr_mod.render_levels)
        check("uv smoothing mapped from pin_borders",
              pbr_mod.uv_smooth == "PRESERVE_BOUNDARIES", pbr_mod.uv_smooth)

    _flat_obj, flat_mod = modifier_of("flatCube")
    check("the linear cube uses Simple",
          flat_mod is not None and flat_mod.subdivision_type == "SIMPLE",
          flat_mod.subdivision_type if flat_mod else None)

    _lam_obj, lam_mod = modifier_of("aiLambertCube")
    check("the smooth preview cube has one at level 1",
          lam_mod is not None and lam_mod.levels == 1,
          lam_mod.levels if lam_mod else None)

    print("\nplacement, bump and the extra lobes")
    tiled = material_for("tiledCube")
    check("tiled material exists", tiled is not None)
    if tiled:
        mapping = next((n for n in tiled.node_tree.nodes
                        if n.bl_idname == "ShaderNodeMapping"), None)
        check("a Mapping node was built", mapping is not None)
        if mapping:
            scale = [round(v, 4) for v in mapping.inputs["Scale"].default_value]
            check("scale follows repeatU and repeatV",
                  scale[:2] == [4.0, 3.0], scale)
            location = [
                round(v, 4) for v in mapping.inputs["Location"].default_value
            ]
            check("location follows the offset",
                  location[:2] == [0.25, 0.5], location)
            rotation = mapping.inputs["Rotation"].default_value[2]
            check("45 degrees became radians",
                  abs(rotation - math.radians(45.0)) < 1e-5, rotation)
        base_image = next(
            (n for n in tiled.node_tree.nodes
             if n.bl_idname == "ShaderNodeTexImage"
             and "base_color" in n.name), None)
        if base_image:
            check("mirrorU became a mirrored extension",
                  base_image.extension == "MIRROR", base_image.extension)

        normal_map = next((n for n in tiled.node_tree.nodes
                           if n.bl_idname == "ShaderNodeNormalMap"), None)
        check("a Normal Map node was built", normal_map is not None)
        if normal_map:
            check("bump depth became normal map strength",
                  abs(normal_map.inputs["Strength"].default_value - 0.35) < 1e-5,
                  normal_map.inputs["Strength"].default_value)

        check("coat weight 0.6", abs(value(tiled, "Coat Weight") - 0.6) < 1e-5)
        check("coat roughness 0.08",
              abs(value(tiled, "Coat Roughness") - 0.08) < 1e-5)
        check("sheen weight 0.4", abs(value(tiled, "Sheen Weight") - 0.4) < 1e-5)
        # Arnold's standard surface sheen and Blender's are different lobes
        # read off different scales, so 0.25 there is about 0.51 here.
        remapped = value(tiled, "Sheen Roughness")
        check("standard surface sheen roughness remapped off 0.25",
              remapped is not None and abs(remapped - 0.5065) < 0.01, remapped)
        check("and the Maya value kept for reference",
              abs(tiled.get("ml_source_sheen_roughness", -1) - 0.25) < 1e-5,
              tiled.get("ml_source_sheen_roughness"))
        check("subsurface weight 0.3",
              abs(value(tiled, "Subsurface Weight") - 0.3) < 1e-5)
        check("subsurface scale 2.5 set explicitly, not left at the version default",
              abs(value(tiled, "Subsurface Scale") - 2.5) < 1e-5,
              value(tiled, "Subsurface Scale"))
        check("anisotropy 0.35", abs(value(tiled, "Anisotropic") - 0.35) < 1e-5)

    print("\nbaked procedurals")
    proc = material_for("procCube")
    check("procedural material exists", proc is not None)
    if proc:
        images = [
            node.image for node in proc.node_tree.nodes
            if node.bl_idname == "ShaderNodeTexImage" and node.image
        ]
        check("the bake produced image nodes", len(images) >= 2, len(images))
        check("base colour is driven by a texture, not a flat value",
              socket(proc, "Base Color").is_linked)
        check("roughness is driven by a texture too",
              socket(proc, "Roughness").is_linked)
        for image in images:
            # Maya bakes linear values, so an sRGB decode would darken them.
            check("baked map {0} loaded as Non-Color".format(image.name),
                  image.colorspace_settings.name == "Non-Color",
                  image.colorspace_settings.name)
            check("baked map {0} has real pixels".format(image.name),
                  image.size[0] > 0 and image.size[1] > 0, image.size)

    print("\ncameras")
    cams = {o.name: o for o in bpy.data.objects if o.type == "CAMERA"}
    check("all three cameras imported", len(cams) == 3, sorted(cams))
    shot = next((o for n, o in cams.items() if "shotCam" in n), None)
    ortho = next((o for n, o in cams.items() if "orthoCam" in n), None)
    check("shot camera exists", shot is not None)
    if shot:
        check("perspective", shot.data.type == "PERSP", shot.data.type)
        check("lens 50 mm", abs(shot.data.lens - 50.0) < 1e-4, shot.data.lens)
        check("sensor width 24 mm",
              abs(shot.data.sensor_width - 24.0) < 0.01, shot.data.sensor_width)
        check("sensor fit vertical from filmFit",
              shot.data.sensor_fit == "VERTICAL", shot.data.sensor_fit)
        check("shift_x 0.1", abs(shot.data.shift_x - 0.1) < 1e-3,
              shot.data.shift_x)
        # Maya states clip planes in scene units, Blender in metres: x0.01.
        check("near clip scaled to 0.01",
              abs(shot.data.clip_start - 0.01) < 1e-6, shot.data.clip_start)
        check("far clip scaled to 50",
              abs(shot.data.clip_end - 50.0) < 1e-4, shot.data.clip_end)
        check("depth of field on", shot.data.dof.use_dof)
        check("f-stop 2.8", abs(shot.data.dof.aperture_fstop - 2.8) < 1e-5)
        check("focus distance scaled to 2.5",
              abs(shot.data.dof.focus_distance - 2.5) < 1e-4,
              shot.data.dof.focus_distance)
        # Maya (0, 30, 120) becomes Blender (0, -1.2, 0.3) after the Y-up to
        # Z-up swap and the centimetre to metre scale.
        check("position converted and scaled",
              abs(shot.matrix_world.translation.z - 0.3) < 1e-4
              and abs(shot.matrix_world.translation.y + 1.2) < 1e-4,
              tuple(round(v, 4) for v in shot.matrix_world.translation))
        check("the renderable camera became the scene camera",
              bpy.context.scene.camera is shot,
              bpy.context.scene.camera.name if bpy.context.scene.camera else None)
    if ortho:
        check("orthographic type", ortho.data.type == "ORTHO", ortho.data.type)
        check("ortho width 40 units becomes 0.4",
              abs(ortho.data.ortho_scale - 0.4) < 1e-5, ortho.data.ortho_scale)
    check("camera count reported", result["camera_count"] == 3,
          result["camera_count"])

    print("\nlights")
    lights = {obj.data.get("ml_source_node_type"): obj
              for obj in bpy.data.objects if obj.type == "LIGHT"}

    area = lights.get("aiAreaLight")
    check("aiAreaLight became an AREA light",
          area is not None and area.data.type == "AREA")
    if area:
        check("disk shape", area.data.shape == "DISK", area.data.shape)
        # 12 intensity x 2^2 exposure = 48 effective, through the measured
        # factor of pi, and then the square of the scene unit: Arnold is unit
        # agnostic, so a centimetre scene is a hundredth the size in Blender
        # and its lights fall off over a hundredth the distance.
        expected = 48.0 * math.pi * (0.01 ** 2)
        check("energy is 48 x pi x the unit scale squared",
              abs(area.data.energy - expected) < 1e-9,
              "{0} vs {1}".format(area.data.energy, expected))
        if hasattr(area.data, "normalize"):
            check("Blender Power left meaning total flux",
                  area.data.normalize is True)
        check("source normalize recorded in metadata",
              area.data.get("ml_source_normalized") is True,
              area.data.get("ml_source_normalized"))
        check("source renderer recorded in metadata",
              area.data.get("ml_source_renderer") == "arnold",
              area.data.get("ml_source_renderer"))
        if hasattr(area.data, "temperature"):
            check("temperature 4500",
                  abs(area.data.temperature - 4500.0) < 1e-3)
            check("temperature enabled", area.data.use_temperature)
        else:
            print("       (this Blender has no light temperature input)")

    ies = lights.get("aiPhotometricLight")
    check("aiPhotometricLight became a SPOT",
          ies is not None and ies.data.type == "SPOT")
    if ies:
        ids = set()
        if ies.data.use_nodes:
            ids = {n.bl_idname for n in ies.data.node_tree.nodes}
        check("IES texture node built", "ShaderNodeTexIES" in ids, sorted(ids))
        check("cone angle 75 degrees",
              abs(ies.data.spot_size - 1.30899694) < 1e-3, ies.data.spot_size)
        falloff = next((n for n in ies.data.node_tree.nodes
                        if n.bl_idname == "ShaderNodeLightFalloff"), None)
        if falloff:
            check("falloff strength stays at unit scale",
                  abs(falloff.inputs["Strength"].default_value - 1.0) < 1e-6,
                  falloff.inputs["Strength"].default_value)

    check("dome became the World environment",
          bpy.context.scene.world is not None)
    check("one dome counted", result["dome_count"] == 1, result["dome_count"])

    print()
    if failures:
        print("FAILURES ({0}):".format(len(failures)))
        for item in failures:
            print("  - {0}".format(item))
        return 1
    print("all import assertions passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
