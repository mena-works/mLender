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
    check("38 meshes imported", result["mesh_count"] == 38,
          result["mesh_count"])
    check("30 materials built", result["material_count"] == 30,
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
    # Light linking collections, selection sets and display layers all name
    # objects rather than placing them, so a mesh can legitimately be in one
    # of those as well as in its group collection. Sets and layers are
    # recognised by their marker rather than their name, which the user chose.
    def scene_collections(obj):
        return [
            c.name for c in obj.users_collection
            if not c.name.startswith(("ML_Link_", "ML_Shadow_"))
            and "ml_maya_set" not in c.keys()
            and "ml_maya_layer" not in c.keys()
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

    print("\nselection sets and display layers")
    hero = bpy.data.collections.get("heroSet")
    check("the set became a collection", hero is not None)
    check("the import reported it", result["set_count"] == 1,
          result["set_count"])
    if hero:
        names = {obj.name for obj in hero.objects}
        check("holding the objects Maya had in it",
              names == {"stdSurfCube", "flatCube"}, sorted(names))
        # A set names objects that live elsewhere; it must not move them.
        std_obj = bpy.data.objects.get("stdSurfCube")
        check("without taking them out of their group collection",
              std_obj is not None
              and "props" in {c.name for c in std_obj.users_collection},
              [c.name for c in std_obj.users_collection] if std_obj else None)
        check("gathered under their own parent, not the group tree",
              hero.name in {c.name for c in
                            bpy.data.collections["mLender Sets"].children},
              [c.name for c in
               bpy.data.collections["mLender Sets"].children]
              if bpy.data.collections.get("mLender Sets") else None)

    hidden_layer = bpy.data.collections.get("hiddenLayer")
    reference_layer = bpy.data.collections.get("referenceLayer")
    check("display layers became collections",
          hidden_layer is not None and reference_layer is not None)
    check("the import reported them", result["layer_count"] == 2,
          result["layer_count"])
    lambert_obj = bpy.data.objects.get("aiLambertCube")
    if hidden_layer and lambert_obj:
        # Set on the object as well as the collection: it is in its group
        # collection too, and Maya hides it however it is reached.
        check("an invisible layer hides its members",
              lambert_obj.hide_viewport and lambert_obj.hide_render,
              (lambert_obj.hide_viewport, lambert_obj.hide_render))
    disp_obj = bpy.data.objects.get("dispCube")
    if reference_layer and disp_obj:
        # Maya's reference display type means "not meant to be grabbed".
        check("a reference layer makes its members unselectable",
              disp_obj.hide_select is True, disp_obj.hide_select)
        check("and the Maya display type is kept for reference",
              reference_layer.get("ml_source_display_type") == 2,
              reference_layer.get("ml_source_display_type"))

    print("\nrender settings")
    # 1920x804, not 1920x1080: Blender's own default would pass against an
    # importer that ignored the record entirely.
    render = bpy.context.scene.render
    check("resolution came from Maya",
          render.resolution_x == 1920 and render.resolution_y == 804,
          (render.resolution_x, render.resolution_y))
    # Maya has no equivalent, and a leftover value silently scales the render.
    check("resolution percentage set to 100",
          render.resolution_percentage == 100, render.resolution_percentage)
    check("pixel aspect is square",
          abs(render.pixel_aspect_x - 1.0) < 1e-6
          and abs(render.pixel_aspect_y - 1.0) < 1e-6,
          (render.pixel_aspect_x, render.pixel_aspect_y))
    check("motion blur switched on", render.use_motion_blur is True,
          render.use_motion_blur)
    check("with Maya's shutter length, in frames",
          abs(render.motion_blur_shutter - 0.75) < 1e-5,
          render.motion_blur_shutter)

    print("\nparticles")
    # Blender has no particle object to receive these, and a point cloud
    # cannot be built from Python at all, so they arrive as loose vertices.
    dust = bpy.data.objects.get("dustParticle")
    check("the particle object arrived", dust is not None)
    # One, not two: the emitting system travels in the Alembic cache and
    # must not also be rebuilt here as a frozen snapshot.
    check("the import reported the uncached ones",
          result["particle_count"] == 2, result["particle_count"])
    if dust:
        check("as a mesh of loose vertices",
              dust.type == "MESH" and len(dust.data.vertices) == 4
              and len(dust.data.polygons) == 0,
              (dust.type, len(dust.data.vertices), len(dust.data.polygons)))
        # Maya had this ten units up, and the positions were local, so the
        # particle at the local origin must land at 0.1 m and not at 0.
        world = [dust.matrix_world @ v.co for v in dust.data.vertices]
        check("the transform is applied once, not twice",
              abs(world[0].z - 0.1) < 1e-4, round(world[0].z, 4))
        # Maya (1, 2, 0) is 1 cm across and 2 cm up, plus the 10 cm offset.
        check("and the points keep their shape",
              abs(world[1].x - 0.01) < 1e-4
              and abs(world[1].z - 0.12) < 1e-4,
              (round(world[1].x, 4), round(world[1].z, 4)))
        check("the Maya count is recorded",
              dust.get("ml_source_count") == 4, dust.get("ml_source_count"))

    print("\nparticle bake")
    check("the import reported both bakes",
          result["particle_baked_count"] == 2,
          result["particle_baked_count"])
    if dust:
        action = getattr(
            getattr(dust.data, "animation_data", None), "action", None
        )
        curves = zi.animation.action_fcurves(action)
        # Three curves per vertex, one per component, or the bake reached
        # only some of the points.
        check("every vertex component is keyed",
              len(curves) == 12, len(curves))
        check("and the keys are linear, not eased",
              all(point.interpolation == "LINEAR"
                  for curve in curves for point in curve.keyframe_points),
              sorted(set(point.interpolation
                         for curve in curves
                         for point in curve.keyframe_points)))
        # The rest state must be the snapshot, not wherever the loop
        # happened to stop keying.
        check("the rest position is the first frame",
              abs((dust.matrix_world @ dust.data.vertices[0].co).z - 0.1)
              < 1e-4,
              round((dust.matrix_world @ dust.data.vertices[0].co).z, 4))
        # Gravity was connected in Maya, so the points must fall between the
        # two ends of the range rather than sit still. The fall is in the
        # object's local Y, since the positions carry no axis swap of their
        # own; it is the matrix that turns them, so this reads world space.
        scene = bpy.context.scene
        original_frame = scene.frame_current
        scene.frame_set(scene.frame_start)
        start_z = (dust.matrix_world @ dust.data.vertices[0].co).z
        scene.frame_set(scene.frame_end)
        end_z = (dust.matrix_world @ dust.data.vertices[0].co).z
        scene.frame_set(original_frame)
        # Maya fell 5.1 units, a centimetre scene, so about five centimetres
        # down. Asserting the direction and size catches a swapped axis, not
        # merely a bake that moved something.
        check("and the simulation plays back downward",
              abs(start_z - 0.1) < 1e-4 and abs(end_z - 0.049) < 5e-3,
              (round(start_z, 5), round(end_z, 5)))

    # The emitter driven object changes count, so it must arrive as a
    # snapshot with no animation rather than a bake missing its later births.
    spark = bpy.data.objects.get("sparkParticle")
    check("the varying count object still arrived", spark is not None)
    if spark:
        check("but carries no vertex animation",
              getattr(spark.data, "animation_data", None) is None
              or spark.data.animation_data.action is None)

    print("\nalembic cache")
    check("the import reported the cached objects",
          result["alembic_count"] >= 2, result["alembic_count"])
    wobble = bpy.data.objects.get("wobblePlane")
    check("the deformed mesh arrived", wobble is not None)
    if wobble:
        check("carrying a cache reader",
              any(m.type == "MESH_SEQUENCE_CACHE" for m in wobble.modifiers),
              [m.type for m in wobble.modifiers])
        check("marked as ours", wobble.get("ml_generated") is True)
        # The whole reason the cache exists: through FBX this mesh arrived
        # frozen. Maya moved it six units up, a centimetre scene, so the
        # spread must open by about six centimetres across the range.
        scene = bpy.context.scene
        original_frame = scene.frame_current

        def spread(frame):
            scene.frame_set(frame)
            evaluated = wobble.evaluated_get(
                bpy.context.evaluated_depsgraph_get()
            )
            heights = [
                (wobble.matrix_world @ v.co).z
                for v in evaluated.data.vertices
            ]
            return max(heights) - min(heights)

        flat = spread(scene.frame_start)
        bent = spread(scene.frame_end)
        scene.frame_set(original_frame)
        check("and it actually deforms over the range",
              flat < 1e-4 and abs(bent - 0.06) < 5e-3,
              (round(flat, 5), round(bent, 5)))

    spark = bpy.data.objects.get("sparkParticle")
    check("the emitting particle system arrived", spark is not None)
    if spark:
        # 4.1 has no point cloud Blender can build, so the cache lands as a
        # mesh there and as a POINTCLOUD from 4.5 on. Both are acceptable;
        # arriving with a reader attached is what matters.
        check("as a cache reader, whatever datablock this build uses",
              any(m.type == "MESH_SEQUENCE_CACHE" for m in spark.modifiers),
              (spark.type, [m.type for m in spark.modifiers]))

    print("\nvolumes")
    volume_obj = bpy.data.objects.get("smokeVolume")
    check("the volume arrived", volume_obj is not None)
    check("the import reported it", result["volume_count"] == 1,
          result["volume_count"])
    if volume_obj:
        check("as a Blender volume object", volume_obj.type == "VOLUME",
              volume_obj.type)
        data = volume_obj.data
        check("pointing at the VDB",
              str(data.filepath).endswith("smoke.vdb"), data.filepath)
        # The file is deliberately absent. Measured: Blender takes the path,
        # reports no grids and raises nothing, so the volume still marks where
        # it belongs and the missing file is reported instead.
        check("a missing VDB still builds the object", len(data.grids) == 0,
              len(data.grids))
        check("and is reported",
              any("smoke.vdb" in str(w) for w in result["warnings"]),
              [w for w in result["warnings"] if "vdb" in str(w).lower()])
        check("frame extension became a sequence",
              data.is_sequence is True and data.frame_start == 12,
              (data.is_sequence, data.frame_start))
        # Arnold render settings Blender has no place for.
        check("the grid names survive as reference",
              data.get("ml_source_grids") == "density temperature",
              data.get("ml_source_grids"))
        check("and the step size",
              abs(data.get("ml_source_step_size", 0) - 0.25) < 1e-6,
              data.get("ml_source_step_size"))
        # Maya had this 40 units up and scaled 3x in X; centimetres, so 0.4 m.
        check("it lands where Maya had it",
              abs(volume_obj.matrix_world.translation.z - 0.4) < 1e-4,
              round(volume_obj.matrix_world.translation.z, 4))
        check("with its scale, which a second assignment would have halved",
              abs(volume_obj.scale.x - 3.0) < 1e-4, volume_obj.scale.x)

    print("\nimage planes")
    shot_cam = bpy.data.objects.get("shotCam")
    check("shotCam arrived", shot_cam is not None)
    if shot_cam:
        cam_data = shot_cam.data
        check("its image plane became a background image",
              len(cam_data.background_images) == 1,
              len(cam_data.background_images))
        check("and backgrounds are switched on",
              cam_data.show_background_images is True)
        if len(cam_data.background_images):
            bg = cam_data.background_images[0]
            check("the image was loaded",
                  bg.image is not None
                  and bg.image.name.startswith("ref_plate"),
                  bg.image.name if bg.image else None)
            check("alpha came from alphaGain",
                  abs(bg.alpha - 0.6) < 1e-5, bg.alpha)
            # Maya Fill crops the overflow, which is Blender's CROP.
            check("Maya's Fill became CROP",
                  bg.frame_method == "CROP", bg.frame_method)
            check("it sits behind the geometry",
                  bg.display_depth == "BACK", bg.display_depth)
        # Maya has five fit modes against Blender's three, so the original is
        # kept rather than lost in the approximation.
        check("the Maya fit mode is recorded",
              cam_data.get("ml_source_image_plane_fit") == "Fill",
              cam_data.get("ml_source_image_plane_fit"))
        check("and so is the plane depth Blender cannot express",
              abs(cam_data.get("ml_source_image_plane_depth", 0) - 120.0) < 1e-4,
              cam_data.get("ml_source_image_plane_depth"))
    ortho_cam = bpy.data.objects.get("orthoCam")
    if ortho_cam:
        check("a camera with no plane gets no background",
              len(ortho_cam.data.background_images) == 0,
              len(ortho_cam.data.background_images))

    print("\nuser attributes")
    # Under their own names, so a script written against the Maya scene keeps
    # working: obj["assetId"] on both sides.
    attr_obj = bpy.data.objects.get("attrCube")
    check("attrCube arrived", attr_obj is not None)
    if attr_obj:
        check("an integer arrived", attr_obj.get("assetId") == 4271,
              attr_obj.get("assetId"))
        check("a bool arrived", bool(attr_obj.get("isHero")) is True,
              attr_obj.get("isHero"))
        check("a string arrived", attr_obj.get("variantName") == "rusty",
              attr_obj.get("variantName"))
        check("an enum arrived as its label",
              attr_obj.get("lodLevel") == "high", attr_obj.get("lodLevel"))
        check("a compound arrived as three numbers",
              [round(v, 3) for v in attr_obj.get("offsetVec")] == [1.0, 2.0, 3.0],
              list(attr_obj.get("offsetVec") or []))
        check("a shape attribute arrived too",
              attr_obj.get("shapeTag") == "onShape", attr_obj.get("shapeTag"))
        # The one that matters. Merge decides what it may adopt by reading
        # ml_generated, so letting a Maya attribute overwrite it would make
        # the importer lose track of its own objects.
        check("a Maya attribute cannot overwrite the importer's marker",
              attr_obj.get("ml_generated") is True,
              attr_obj.get("ml_generated"))
        check("and the refusal is reported",
              any("ml_generated" in str(w) for w in result["warnings"]),
              [w for w in result["warnings"] if "ml_" in str(w)])
        check("the import counted the ones it applied",
              result["custom_attribute_count"] >= 6,
              result["custom_attribute_count"])

    print("\nhard and soft edges")
    # Nothing in the tool builds these; they ride the FBX. The pair is what
    # makes the check mean something, because one cube alone would pass
    # against an export that flattened every mesh to the same shading.
    hard = bpy.data.objects.get("hardEdgeCube")
    soft = bpy.data.objects.get("softEdgeCube")
    check("both edge cubes arrived", hard is not None and soft is not None)
    if hard and soft:
        hard_sharp = sum(1 for e in hard.data.edges if e.use_edge_sharp)
        soft_sharp = sum(1 for e in soft.data.edges if e.use_edge_sharp)
        check("a hard edged cube arrives faceted",
              hard_sharp == 12, hard_sharp)
        check("and a soft edged one does not", soft_sharp == 0, soft_sharp)
        check("custom normals came across",
              getattr(hard.data, "has_custom_normals", False) is True)
        # The distinction is in the corner normals, not only the sharp flags:
        # a face normal against a vertex-averaged one.
        if hasattr(hard.data, "corner_normals"):
            hard_n = tuple(round(v, 2)
                           for v in hard.data.corner_normals[0].vector)
            soft_n = tuple(round(v, 2)
                           for v in soft.data.corner_normals[0].vector)
            check("the hard cube's corner normal is a face normal",
                  max(abs(c) for c in hard_n) > 0.99, hard_n)
            check("the soft cube's is averaged between faces",
                  max(abs(c) for c in soft_n) < 0.99, soft_n)

    print("\nUV sets and vertex colours")
    # These already survive the FBX; nothing in the tool builds them. The
    # assertions exist because nothing else pins them either, and a change to
    # FBX_EXPORT_OPTIONS could drop a UV set without a word.
    uv_cube = bpy.data.objects.get("uvSetCube")
    check("uvSetCube arrived", uv_cube is not None)
    if uv_cube:
        mesh = uv_cube.data
        names = [layer.name for layer in mesh.uv_layers]
        check("both UV sets arrived under their Maya names",
              names == ["map1", "lightmap"], names)
        check("the Maya current set is the active one",
              mesh.uv_layers.active is not None
              and mesh.uv_layers.active.name == "map1",
              mesh.uv_layers.active.name if mesh.uv_layers.active else None)
        if len(mesh.uv_layers) >= 2:
            # Two sets that arrived as the same data twice would still pass a
            # count check, so the second one is offset in Maya.
            first = [tuple(round(v, 4) for v in d.uv)
                     for d in mesh.uv_layers[0].data[:4]]
            second = [tuple(round(v, 4) for v in d.uv)
                      for d in mesh.uv_layers[1].data[:4]]
            check("and they hold different coordinates", first != second,
                  (first[:1], second[:1]))
        # vertex_colors was replaced by color_attributes in 4.0 and is still
        # present as an alias, so the newer name is what gets asserted.
        colours = getattr(mesh, "color_attributes", None)
        check("the colour set arrived",
              colours is not None and "paint" in [a.name for a in colours],
              [a.name for a in colours] if colours is not None else None)
        if colours and len(colours):
            sample = tuple(round(v, 3) for v in colours[0].data[0].color)
            check("with the colour Maya painted",
                  abs(sample[0] - 1.0) < 0.02 and sample[1] < 0.02, sample)

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
        # Maya's eccentricity, not a pinned constant: the fixture sets 0.45,
        # away from both the 0.3 default and the 0.1 this used to be.
        check("roughness came from the blinn's eccentricity",
              abs(value(native_blinn, "Roughness") - 0.45) < 1e-5,
              value(native_blinn, "Roughness"))

    print("\nramp shader")
    ramp_material = material_for("rampCube")
    check("the ramp material exists", ramp_material is not None)
    if ramp_material:
        nodes = ramp_material.node_tree.nodes
        ramps = [n for n in nodes if n.bl_idname == "ShaderNodeValToRGB"]
        # Two: one for the colour ramp and one for the transparency ramp.
        check("both ramps became Color Ramp nodes", len(ramps) == 2,
              len(ramps))
        colour_ramp = next(
            (n for n in ramps
             if n.outputs["Color"].links
             and n.outputs["Color"].links[0].to_socket.name == "Base Color"),
            None,
        )
        check("one drives Base Color", colour_ramp is not None)
        if colour_ramp:
            stops = colour_ramp.color_ramp.elements
            check("with all three stops in order",
                  [round(e.position, 3) for e in stops] == [0.0, 0.5, 1.0],
                  [e.position for e in stops])
            # Measured with Maya's software renderer: position 1 faces the
            # camera. A ramp built backwards would put red here.
            check("position 1 is the colour Maya had facing the camera",
                  [round(v, 3) for v in stops[2].color[:3]] == [0.0, 0.0, 1.0],
                  list(stops[2].color)[:3])
            check("and position 0 the one at the rim",
                  [round(v, 3) for v in stops[0].color[:3]] == [1.0, 0.0, 0.0],
                  list(stops[0].color)[:3])
            check("the first stop's interpolation decided the ramp's",
                  colour_ramp.color_ramp.interpolation == "LINEAR",
                  colour_ramp.color_ramp.interpolation)
            # Driven by the cosine itself, not Layer Weight: measured, Layer
            # Weight runs the other way and is not linear.
            source = colour_ramp.inputs[0].links[0].from_node
            check("driven by dot(Normal, Incoming)",
                  source.bl_idname == "ShaderNodeVectorMath"
                  and source.operation == "DOT_PRODUCT",
                  (source.bl_idname, getattr(source, "operation", None)))
            feeds = sorted(
                link.from_socket.name for link in ramp_material.node_tree.links
                if link.to_node.name == source.name
            )
            check("fed by the geometry normal and incoming vector",
                  feeds == ["Incoming", "Normal"], feeds)

    print("\nramp texture")
    # Bake Procedurals is on for this package, and it is the user's choice,
    # so both ramps arrive as their baked images. The native rebuild is
    # asserted at the end of this file, against the unbaked package.
    for ramp_name in ("rampTexCube", "radialRampCube"):
        ramp_material = material_for(ramp_name)
        check("{0} material exists".format(ramp_name),
              ramp_material is not None)
        if ramp_material:
            kinds = [n.bl_idname for n in ramp_material.node_tree.nodes]
            check("{0} arrived as its baked image".format(ramp_name),
                  "ShaderNodeTexImage" in kinds
                  and "ShaderNodeValToRGB" not in kinds,
                  kinds)

    print("\ninstancers")
    check("the import reported one instancer",
          result["instancer_count"] == 1, result["instancer_count"])
    holder = bpy.data.objects.get("scatterParticle")
    check("the points object arrived", holder is not None)
    if holder:
        check("switched to vertex instancing",
              holder.instance_type == "VERTS", holder.instance_type)
        children = list(holder.children)
        check("with one template parented to it", len(children) == 1,
              [c.name for c in children])
        if children:
            template = children[0]
            # A linked copy, not the original: re-parenting the source would
            # move geometry the user placed to make the instancer work.
            source = bpy.data.objects.get("instancedGeo")
            check("the template shares the source's mesh data",
                  source is not None and template.data is source.data,
                  template.data.name)
            check("and the source itself was left alone",
                  source is not None and source.parent is None,
                  getattr(getattr(source, "parent", None), "name", None))
        # Three points in Maya, so three instances after evaluation.
        depsgraph = bpy.context.evaluated_depsgraph_get()
        # Read inside the loop: a DepsgraphObjectInstance is only valid while
        # it is being iterated, and keeping the list raises ReferenceError on
        # the first attribute touched afterwards.
        places = []
        for item in depsgraph.object_instances:
            if not item.is_instance or not item.parent:
                continue
            if item.parent.original != holder:
                continue
            places.append(round(item.matrix_world.translation.x, 4))
        check("three instances are actually evaluated",
              len(places) == 3, len(places))
        # Maya spaced the points 2 units apart in a centimetre scene, so the
        # copies must land 2 cm apart, on the points rather than offset from
        # them. This is what a stale parent inverse or a doubled transform
        # would move, and a count alone would not notice.
        places = sorted(places)
        check("and they land on the points Maya had",
              places == [0.0, 0.02, 0.04], places)

    print("\nanimated visibility")
    check("the import reported one animated visibility",
          result["visibility_animation_count"] == 1,
          result["visibility_animation_count"])
    blink = bpy.data.objects.get("blinkCube")
    check("the blinking mesh arrived", blink is not None)
    if blink:
        action = getattr(
            getattr(blink, "animation_data", None), "action", None
        )
        paths = sorted(set(c.data_path for c in fcurves_of(action)))
        # Both flags: hiding only the viewport would still render it.
        check("both hide flags are keyed",
              paths == ["hide_render", "hide_viewport"], paths)
        check("and the keys step rather than ease",
              all(p.interpolation == "CONSTANT"
                  for c in fcurves_of(action) for p in c.keyframe_points),
              sorted(set(p.interpolation for c in fcurves_of(action)
                         for p in c.keyframe_points)))
        scene = bpy.context.scene
        original_frame = scene.frame_current
        states = []
        for frame in (1, 10, 20):
            scene.frame_set(frame)
            states.append((frame, blink.hide_render, blink.hide_viewport))
        scene.frame_set(original_frame)
        check("it blinks the way Maya did",
              states == [(1, False, False), (10, True, True),
                         (20, False, False)],
              states)
    steady = bpy.data.objects.get("stdSurfCube")
    check("a mesh that does not blink stays unkeyed",
          steady is not None
          and getattr(steady, "animation_data", None) is None,
          getattr(steady, "animation_data", None))

    print("\nblend shaders")
    mixed = material_for("mixCube")
    check("the mix material exists", mixed is not None)
    if mixed:
        nodes = mixed.node_tree.nodes
        mix_nodes = [n for n in nodes if n.bl_idname == "ShaderNodeMixShader"]
        bsdfs = [n for n in nodes
                 if n.bl_idname == "ShaderNodeBsdfPrincipled"]
        check("built as one Mix Shader over two Principled BSDFs",
              len(mix_nodes) == 1 and len(bsdfs) == 2,
              (len(mix_nodes), len(bsdfs)))
        outputs = [n for n in nodes
                   if n.bl_idname == "ShaderNodeOutputMaterial"]
        # Each layer builder makes its own output; all but one must go, or
        # Blender renders whichever it decides is active.
        check("with exactly one material output", len(outputs) == 1,
              len(outputs))
        if mix_nodes:
            mix = mix_nodes[0]
            check("the factor is Maya's mix, unflipped",
                  abs(mix.inputs[0].default_value - 0.25) < 1e-5,
                  mix.inputs[0].default_value)
            # Slot 1 is the base, slot 2 the upper: the two roughnesses tell
            # them apart, so a swap cannot pass.
            lower = mix.inputs[1].links[0].from_node
            upper = mix.inputs[2].links[0].from_node
            check("shader1 landed in the lower slot",
                  abs(lower.inputs["Roughness"].default_value - 0.15) < 1e-4,
                  lower.inputs["Roughness"].default_value)
            check("and shader2 in the upper one",
                  abs(upper.inputs["Roughness"].default_value - 0.65) < 1e-4,
                  upper.inputs["Roughness"].default_value)

    layered = material_for("layerCube")
    check("the layer material exists", layered is not None)
    if layered:
        nodes = layered.node_tree.nodes
        mix_nodes = [n for n in nodes if n.bl_idname == "ShaderNodeMixShader"]
        bsdfs = [n for n in nodes
                 if n.bl_idname == "ShaderNodeBsdfPrincipled"]
        # Two enabled layers, one disabled: three BSDFs would mean the
        # disabled slot came along.
        check("only the enabled layers were built",
              len(bsdfs) == 2 and len(mix_nodes) == 1,
              (len(bsdfs), len(mix_nodes)))
        if mix_nodes:
            check("its factor is mix2",
                  abs(mix_nodes[0].inputs[0].default_value - 0.4) < 1e-5,
                  mix_nodes[0].inputs[0].default_value)

    print("\nphong and phongE")
    # Both were unsupported until measured, so their materials arrived from
    # the fallback path with a pinned roughness and an "unsupported" warning.
    phong = material_for("phongCube")
    check("phong material exists", phong is not None)
    if phong:
        check("its roughness came from cosinePower 30",
              abs(value(phong, "Roughness") - 0.25) < 1e-5,
              value(phong, "Roughness"))
        check("and its base colour survived",
              abs(value(phong, "Base Color")[1] - 0.6) < 1e-3,
              list(value(phong, "Base Color"))[:3])
    phong_e = material_for("phongECube")
    check("phongE material exists", phong_e is not None)
    if phong_e:
        check("its roughness came from its own roughness attribute",
              abs(value(phong_e, "Roughness") - 0.8) < 1e-5,
              value(phong_e, "Roughness"))
    check("neither was reported as unsupported",
          not [w for w in result["warnings"]
               if "Unsupported" in w and ("phong" in w or "phongE" in w)],
          [w for w in result["warnings"] if "Unsupported" in w])

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

    # Last, because importing replaces the scene: everything above is read
    # from the baked package and would be gone after this.
    print("\nramp texture, unbaked package")
    packages = sorted(
        glob.glob(os.path.join(TEST_ROOT, "unbaked", "mLender_*"))
    )
    check("the unbaked package is there", bool(packages), TEST_ROOT)
    if packages:
        unbaked_result = zi.import_scene_package(packages[-1], import_scale=1.0)
        unbaked_material = material_for("rampTexCube")
        check("its ramp material exists", unbaked_material is not None)
        if unbaked_material:
            nodes = unbaked_material.node_tree.nodes
            ramps = [n for n in nodes if n.bl_idname == "ShaderNodeValToRGB"]
            images = [n for n in nodes if n.bl_idname == "ShaderNodeTexImage"]
            # A Color Ramp and no image: rebuilt, not baked.
            check("built as a Color Ramp with no image",
                  len(ramps) == 1 and not images, (len(ramps), len(images)))
            if ramps:
                unbaked_ramp = ramps[0]
                stops = unbaked_ramp.color_ramp.elements
                check("with all three stops in order",
                      [round(e.position, 3) for e in stops] == [0.0, 0.5, 1.0],
                      [e.position for e in stops])
                # Measured by baking a red-to-blue V ramp and reading the
                # image: position 0 sits at v = 0, so nothing is inverted.
                check("position 0 is the colour Maya had at v = 0",
                      [round(v, 3) for v in stops[0].color[:3]]
                      == [1.0, 0.0, 0.0],
                      list(stops[0].color)[:3])
                check("its interpolation came from the node",
                      unbaked_ramp.color_ramp.interpolation == "EASE",
                      unbaked_ramp.color_ramp.interpolation)
                # Driven by V, not U: read through X it would run sideways.
                driver = unbaked_ramp.inputs[0].links[0].from_node
                # Not "socket": that name is a helper used throughout this
                # file, and binding it locally shadows it for the whole
                # function.
                component = unbaked_ramp.inputs[0].links[0].from_socket.name
                check("driven by the V component of the UV",
                      driver.bl_idname == "ShaderNodeSeparateXYZ"
                      and component == "Y",
                      (driver.bl_idname, component))
                feeder = driver.inputs[0].links[0]
                check("which comes from the texture coordinate UV",
                      feeder.from_node.bl_idname == "ShaderNodeTexCoord"
                      and feeder.from_socket.name == "UV",
                      (feeder.from_node.bl_idname, feeder.from_socket.name))
        # A shape one Color Ramp cannot make must say so rather than arrive
        # as a gradient in the wrong shape.
        check("a circular ramp is refused with a warning",
              any("Circular Ramp" in item
                  for item in unbaked_result["warnings"]),
              [w for w in unbaked_result["warnings"] if "Ramp" in w])

        print("\ntexture projection, unbaked package")
        check("the import reported a placement",
              unbaked_result["placement_count"] >= 1,
              unbaked_result["placement_count"])
        projected = material_for("projCube")
        check("the projected material exists", projected is not None)
        if projected:
            nodes = projected.node_tree.nodes
            images = [n for n in nodes
                      if n.bl_idname == "ShaderNodeTexImage"]
            check("built from one image texture", len(images) == 1,
                  len(images))
            if images:
                node = images[0]
                check("projected flat, not wrapped on the UVs",
                      node.projection == "FLAT", node.projection)
                mapping = node.inputs["Vector"].links[0].from_node
                check("through a Mapping node",
                      mapping.bl_idname == "ShaderNodeMapping",
                      mapping.bl_idname)
                if mapping.bl_idname == "ShaderNodeMapping":
                    # Measured: -90 about X puts the texture back in Maya's
                    # space and +0.5 moves its -0.5..0.5 onto Blender's 0..1.
                    # +90 renders vertically flipped.
                    rotation = [round(math.degrees(v), 1)
                                for v in mapping.inputs["Rotation"].default_value]
                    offset = [round(v, 3)
                              for v in mapping.inputs["Location"].default_value]
                    check("rotated -90 about X", rotation == [-90.0, 0.0, 0.0],
                          rotation)
                    check("and moved by half", offset == [0.5, 0.5, 0.0],
                          offset)
                    coord = mapping.inputs["Vector"].links[0].from_node
                    check("reading object coordinates",
                          coord.bl_idname == "ShaderNodeTexCoord"
                          and mapping.inputs["Vector"].links[0]
                          .from_socket.name == "Object",
                          (coord.bl_idname,
                           mapping.inputs["Vector"].links[0].from_socket.name))
                    # An Empty standing in for the place3dTexture, and the
                    # coordinates must actually be read from it.
                    check("from the placement Empty",
                          coord.object is not None
                          and coord.object.get("ml_maya_placement")
                          == "projPlacement",
                          getattr(coord.object, "name", None))
                    if coord.object:
                        # Maya put it 4 units up in a centimetre scene, and
                        # scaled it 2 in X, which sets the projection size.
                        place = coord.object
                        check("placed where Maya had it",
                              abs(place.matrix_world.translation.z - 0.04)
                              < 1e-4,
                              round(place.matrix_world.translation.z, 5))
                        # Maya's scaleX of 2, times the scene unit. The unit
                        # belongs here and was missing at first: Maya projects
                        # over half a *Maya unit* while object coordinates
                        # come out in metres, so without it a centimetre
                        # scene projected the image a hundred times too
                        # small. A scale of exactly 2.0 is that bug.
                        check("with its scale kept, scene unit included",
                              abs(place.matrix_world.to_scale().x - 0.02)
                              < 1e-5,
                              round(place.matrix_world.to_scale().x, 5))
        # A type this build does not reproduce must say so.
        check("a Ball projection is refused with a warning",
              any("Ball" in item for item in unbaked_result["warnings"]),
              [w for w in unbaked_result["warnings"] if "projection" in w])

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
