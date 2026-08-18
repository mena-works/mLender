# -*- coding: utf-8 -*-
"""Maya render passes as Blender view layer passes.

Matching is by name, because that is all the package carries beyond the
engine and Arnold's raw type integer. Two of the old substring tests were
wrong and the fixture now proves it:

* ``"z" in name`` caught every AOV with a z anywhere in it. OpenPBR calls its
  sheen lobe **fuzz**, so a fuzz AOV silently turned on the depth pass and
  nothing else. The test is now an exact match on Arnold's ``Z``.
* A bare ``albedo`` turned on diffuse direct and indirect as well as colour.
  Albedo is the colour pass alone; the other two are light transport that
  nobody asked for.

Anything unmapped becomes a named custom AOV slot, and that is **reported**.
A Blender custom AOV renders black unless a shader writes into it, so a slot
with no writer looks like a pass that arrived and is empty -- which is worse
than one that never arrived, because only the second is visible.
"""

import bpy


# Names that mean the same pass wherever they come from. Kept as a table so a
# new spelling is a line here rather than another branch.
DEPTH_NAMES = ("z", "depth", "zdepth")
NORMAL_NAMES = ("n", "normal")


def _set(view_layer, name, value=True):
    """Set a pass flag only if this Blender has it."""
    if not hasattr(view_layer, name):
        return False
    try:
        setattr(view_layer, name, value)
        return True
    except Exception:
        return False


def rebuild_aovs(aov_records, warnings=None):
    """Enable the view layer passes the Maya AOVs correspond to.

    Returns the number of records that reached a real pass; the rest are
    counted in the warnings.
    """
    if warnings is None:
        warnings = []
    if not aov_records:
        return {"mapped": 0, "custom": 0}

    view_layer = bpy.context.scene.view_layers[0]
    mapped = 0
    custom = []

    for aov in aov_records:
        raw = str(aov.get("name") or "")
        name = raw.lower()

        # Exact, not "contains": see the fuzz trap above.
        if name in DEPTH_NAMES:
            _set(view_layer, "use_pass_z")
        elif name in NORMAL_NAMES:
            _set(view_layer, "use_pass_normal")
        elif "vector" in name or "motion" in name or name == "mv":
            _set(view_layer, "use_pass_vector")
        elif name == "uv":
            _set(view_layer, "use_pass_uv")
        elif "crypto" in name:
            _set(view_layer, "use_pass_cryptomatte_object")
            _set(view_layer, "use_pass_cryptomatte_material")
            # Blender has an asset level too, which the old mapping left off.
            _set(view_layer, "use_pass_cryptomatte_asset")
        elif "emission" in name or name == "emit":
            _set(view_layer, "use_pass_emit")
        elif "albedo" in name and "diffuse" not in name:
            # The colour pass alone. Direct and indirect are light transport,
            # not albedo.
            _set(view_layer, "use_pass_diffuse_color")
        elif "diffuse" in name:
            _set(view_layer, "use_pass_diffuse_color")
            _set(view_layer, "use_pass_diffuse_direct")
            _set(view_layer, "use_pass_diffuse_indirect")
        elif "specular" in name or "reflection" in name:
            _set(view_layer, "use_pass_glossy_color")
            _set(view_layer, "use_pass_glossy_direct")
            _set(view_layer, "use_pass_glossy_indirect")
        else:
            try:
                slot = view_layer.aovs.add()
                slot.name = raw
                custom.append(raw)
            except Exception as exc:
                warnings.append(
                    'AOV "{0}" has no Blender pass and no custom slot could '
                    "be made for it: {1}".format(raw, exc)
                )
            continue
        mapped += 1

    if custom:
        warnings.append(
            "{0} AOV(s) have no Blender pass and arrived as empty custom "
            "slots: {1}. A custom AOV renders black unless a shader writes "
            "into it, so these are named but not filled.".format(
                len(custom), ", ".join(sorted(custom))
            )
        )
    return {"mapped": mapped, "custom": len(custom)}
