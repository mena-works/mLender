# -*- coding: utf-8 -*-
"""End-to-end import test against a real headless Blender.

Imports the package written by maya_export_test.py and asserts on the actual
node trees and light data Blender ends up with.

    "C:\\Program Files\\Blender Foundation\\Blender 5.2\\blender.exe" ^
        --background --factory-startup --python tests/blender_import_test.py

Run maya_export_test.py first; this reads its output from
<temp>/za_lookdev_test/MTB_Z_A_01.
"""
import glob
import math
import os
import sys
import tempfile

import bpy

TOOL_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEST_ROOT = os.path.join(tempfile.gettempdir(), "za_lookdev_test")

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
    packages = sorted(glob.glob(os.path.join(TEST_ROOT, "MTB_Z_A_*")))
    if not packages:
        raise SystemExit(
            "No package in {0}. Run maya_export_test.py first.".format(TEST_ROOT)
        )
    return packages[-1]


def material_for(fragment):
    for material in bpy.data.materials:
        if fragment.lower() in str(material.get("za_maya_material", "")).lower():
            return material
    return None


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
    import za_lookdev_importer as zi

    print("Blender {0}, importer build {1}".format(
        bpy.app.version_string, zi.BUILD_VERSION))

    result = zi.import_lookdev_package(find_package(), import_scale=1.0)
    print("meshes={0} materials={1} subdiv={2} lights={3} domes={4}".format(
        result["mesh_count"], result["material_count"],
        result["subdivision_count"], result["light_count"],
        result["dome_count"]))
    for warning in result["warnings"]:
        print("  warn: {0}".format(warning))

    print("\nscene")
    check("7 meshes imported", result["mesh_count"] == 7, result["mesh_count"])
    check("7 materials built", result["material_count"] == 7,
          result["material_count"])
    # Three of the five cubes asked for subdivision in Maya; the other two
    # must arrive unmodified.
    check("only the meshes that asked are subdivided",
          result["subdivision_count"] == 3, result["subdivision_count"])

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

        hue_sat = by_name.get("ZA_CC_Hue_Saturation")
        check("saturation 0.5 rebuilt", hue_sat is not None
              and abs(hue_sat.inputs[1].default_value - 0.5) < 1e-5)
        check("hue left neutral at 0.5", hue_sat is not None
              and abs(hue_sat.inputs[0].default_value - 0.5) < 1e-5)

        # exposure 1 folds into multiply, so the red channel is 2 * 2 = 4.
        multiply = by_name.get("ZA_CC_Multiply")
        check("exposure folded into the multiply", multiply is not None
              and abs(multiply.inputs[2].default_value[0] - 4.0) < 1e-5,
              multiply.inputs[2].default_value[:] if multiply else None)
        check("green channel carries exposure alone", multiply is not None
              and abs(multiply.inputs[2].default_value[1] - 2.0) < 1e-5)

        check("the corrected colour, not the raw image, reaches the socket",
              socket(std, "Base Color").links[0].from_node.name.startswith("ZA_CC"),
              socket(std, "Base Color").links[0].from_node.name)

        check("the unrebuildable remapValue was reported",
              any("remapValue" in warning for warning in result["warnings"]),
              result["warnings"])

    print("\naiOpenPBRSurface")
    pbr = material_for("openPbrCube")
    check("material exists", pbr is not None)
    if pbr:
        check("metallic 1.0", abs(value(pbr, "Metallic") - 1.0) < 1e-5)
        check("alpha 0.25", abs(value(pbr, "Alpha") - 0.25) < 1e-5)
        check("250 nits scaled to emission strength 2.5",
              abs(value(pbr, "Emission Strength") - 2.5) < 1e-5,
              value(pbr, "Emission Strength"))

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
        check("thin walled recorded", glass.get("za_thin_walled") is True,
              glass.get("za_thin_walled"))
        check("material mode recorded",
              glass.get("za_material_mode") == "GLASS_BSDF",
              glass.get("za_material_mode"))
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
        check("udim marked on the image", image.get("za_udim") is True)
        check("all three tiles registered", len(image.tiles) == 3,
              [tile.number for tile in image.tiles])

    print("\nsubdivision")

    def modifier_of(fragment):
        obj = None
        for candidate in bpy.data.objects:
            if (candidate.type == "MESH"
                    and fragment.lower() in candidate.name.lower()):
                obj = candidate
        return obj, (obj.modifiers.get("Z-A Subdivision") if obj else None)

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
    check("both cameras imported", len(cams) == 2, sorted(cams))
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
    check("camera count reported", result["camera_count"] == 2,
          result["camera_count"])

    print("\nlights")
    lights = {obj.data.get("za_source_node_type"): obj
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
              area.data.get("za_source_normalized") is True,
              area.data.get("za_source_normalized"))
        check("source renderer recorded in metadata",
              area.data.get("za_source_renderer") == "arnold",
              area.data.get("za_source_renderer"))
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
