# -*- coding: utf-8 -*-
import bpy

def rebuild_aovs(aov_records):
    """Enable corresponding view layer passes based on Maya AOVs."""
    if not aov_records:
        return
        
    view_layer = bpy.context.scene.view_layers[0]
    
    for aov in aov_records:
        name = aov.get("name", "").lower()
        
        if "z" in name or "depth" in name:
            view_layer.use_pass_z = True
        elif "normal" in name or "n" == name:
            view_layer.use_pass_normal = True
        elif "vector" in name or "motion" in name or "mv" in name:
            view_layer.use_pass_vector = True
        elif "uv" in name:
            view_layer.use_pass_uv = True
        elif "crypto" in name:
            view_layer.use_pass_cryptomatte_object = True
            view_layer.use_pass_cryptomatte_material = True
        elif "emission" in name:
            view_layer.use_pass_emit = True
        elif "diffuse" in name or "albedo" in name:
            view_layer.use_pass_diffuse_color = True
            view_layer.use_pass_diffuse_direct = True
            view_layer.use_pass_diffuse_indirect = True
        elif "specular" in name or "reflection" in name:
            view_layer.use_pass_glossy_color = True
            view_layer.use_pass_glossy_direct = True
            view_layer.use_pass_glossy_indirect = True
        else:
            # Create a custom AOV for unmapped ones
            try:
                aov_slot = view_layer.aovs.add()
                aov_slot.name = aov.get("name")
            except Exception:
                pass
