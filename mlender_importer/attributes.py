# -*- coding: utf-8 -*-
"""User attributes from Maya, as Blender custom properties.

Pipelines hang their own data off Maya nodes -- an asset id, a variant name, a
LOD level -- and Blender has exactly the same idea. They travel under their own
names rather than a prefixed one, because the point is that a script written
against the Maya scene keeps working: ``obj["assetId"]`` on both sides.

Names are the one hazard that follows from that. The tool's own metadata lives
on the same object under ``ml_``, so a Maya attribute called ``ml_generated``
would quietly overwrite the marker that tells an import which objects it made
-- and Merge depends on that marker to know what it may adopt. Anything
starting with the tool's prefix is refused and reported.
"""

from .constants import PROPERTY_PREFIX


def apply_custom_attributes(obj, record, warnings):
    """Copy a record's user attributes onto the object. Returns how many."""
    attributes = (record or {}).get("custom_attributes") or {}
    if not attributes or obj is None:
        return 0

    applied = 0
    for name, value in attributes.items():
        name = str(name)
        if name.startswith(PROPERTY_PREFIX):
            warnings.append(
                'Maya attribute "{0}" on {1} was not copied: names starting '
                'with "{2}" belong to the importer, and overwriting one would '
                "break how it tracks its own objects.".format(
                    name, obj.name, PROPERTY_PREFIX
                )
            )
            continue
        try:
            obj[name] = _blender_value(value)
        except Exception as exc:
            warnings.append(
                'Maya attribute "{0}" on {1} could not be copied: {2}'.format(
                    name, obj.name, exc
                )
            )
            continue
        applied += 1
    return applied


def _blender_value(value):
    """Custom properties take numbers, strings, bools and number sequences."""
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value
    if isinstance(value, (list, tuple)):
        return [float(item) for item in value]
    return str(value)
