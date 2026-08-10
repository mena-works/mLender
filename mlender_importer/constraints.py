# -*- coding: utf-8 -*-
import bpy

def rebuild_constraints(constraint_records):
    """Rebuild Maya constraints on Blender objects."""
    if not constraint_records:
        return
        
    for record in constraint_records:
        owner_name = record.get("owner", "").split("|")[-1]
        owner = bpy.data.objects.get(owner_name)
        if not owner:
            # Maybe it has a namespace or suffix. Let's try matching exactly or skip.
            continue

            
        ctype = record.get("type")
        targets = record.get("targets", [])
        weights = record.get("weights", [])
        properties = record.get("properties", {})
        
        # We only support one target for simplicity in this implementation,
        # but Blender supports multiple via multiple constraints or custom setups.
        if not targets:
            continue
            
        target_name = targets[0].split("|")[-1]
        target = bpy.data.objects.get(target_name)
        if not target:
            continue
            
        # Determine Blender constraint type
        b_type = None
        if ctype == "parentConstraint":
            b_type = "CHILD_OF"
        elif ctype == "pointConstraint":
            b_type = "COPY_LOCATION"
        elif ctype == "orientConstraint":
            b_type = "COPY_ROTATION"
        elif ctype == "scaleConstraint":
            b_type = "COPY_SCALE"
        elif ctype == "aimConstraint":
            b_type = "TRACK_TO"
            
        if not b_type:
            continue
            
        # Add constraint
        con = owner.constraints.new(type=b_type)
        con.target = target
        
        # Set weight if available
        if weights:
            try:
                con.influence = float(weights[0])
            except Exception:
                pass
                
        # Set specific properties for Track To (Aim)
        if b_type == "TRACK_TO":
            # In Maya, aimVector determines the facing axis
            aim_vec = properties.get("aimVector", [1.0, 0.0, 0.0])
            if aim_vec[0] > 0.9: con.track_axis = "TRACK_X"
            elif aim_vec[0] < -0.9: con.track_axis = "TRACK_NEGATIVE_X"
            elif aim_vec[1] > 0.9: con.track_axis = "TRACK_Y"
            elif aim_vec[1] < -0.9: con.track_axis = "TRACK_NEGATIVE_Y"
            elif aim_vec[2] > 0.9: con.track_axis = "TRACK_Z"
            elif aim_vec[2] < -0.9: con.track_axis = "TRACK_NEGATIVE_Z"
            
            up_vec = properties.get("upVector", [0.0, 1.0, 0.0])
            if up_vec[0] > 0.9: con.up_axis = "UP_X"
            elif up_vec[1] > 0.9: con.up_axis = "UP_Y"
            elif up_vec[2] > 0.9: con.up_axis = "UP_Z"
