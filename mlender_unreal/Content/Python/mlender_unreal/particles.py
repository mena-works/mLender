# -*- coding: utf-8 -*-
"""Maya particle points, and the positions the instancers scatter onto.

Unreal has no point-cloud primitive an add-on can fill: Niagara is the real
answer and authoring a Niagara system from Python means building a graph, which
is a project rather than a module. The point cloud plugins are absent from this
engine build -- ``PointCloud`` and ``LidarPointCloud`` both probed missing.

So a particle system arrives as an **anchor** at its transform carrying the
count and the render type, and its points are exposed for
:mod:`instancers`, which is where the points actually become something you can
see. The Blender receiver builds a vertex-only mesh for this; Unreal has no
equivalent that costs less than a Niagara graph, and that is said out loud
rather than left as an empty space in the level.

The per-frame samples are not carried either, and that is reported: a particle
system frozen on one frame looks like a working import until it is played.
"""

import unreal

from .objects import record_metadata, spawn
from .utils import scalar


FOLDER = "mLender Particles"


def point_triples(record):
    """Particle positions as (x, y, z) triples.

    The exporter writes them **flat** -- nine floats for three particles -- so
    a caller that iterates the list straight away gets floats and fails with
    "'float' object is not iterable", which is exactly what happened. Both
    shapes are accepted because a flat list is what is measured today and a
    nested one is the obvious future change.
    """
    values = list((record or {}).get("positions") or [])
    if not values:
        return []
    if isinstance(values[0], (list, tuple)):
        return [
            (scalar(v[0], 0.0), scalar(v[1], 0.0), scalar(v[2], 0.0))
            for v in values if len(v) >= 3
        ]
    triples = []
    for index in range(0, len(values) - 2, 3):
        triples.append((
            scalar(values[index], 0.0),
            scalar(values[index + 1], 0.0),
            scalar(values[index + 2], 0.0),
        ))
    return triples


def import_particles(package_data, unreal_scale, warnings):
    """Anchors for the particle systems, plus their positions for instancers.

    Returns the positions keyed by both the particle path and the shape path,
    because an instancer's ``points_path`` may name either.
    """
    records = list((package_data or {}).get("particles") or [])
    positions = {}
    created = 0

    for record in records:
        label = (
            record.get("particle_full_name") or record.get("particle")
            or "Particles"
        )
        points = point_triples(record)
        for key in (record.get("particle_path"), record.get("shape_path"),
                    record.get("particle")):
            if key:
                positions[str(key)] = points

        try:
            actor = spawn(unreal.Actor, record, unreal_scale, label, FOLDER)
            record_metadata(actor, (
                ("particle_count", record.get("count")),
                ("particle_render_type", record.get("render_type")),
                ("particle_points", len(points)),
            ))
            created += 1
        except Exception as exc:
            warnings.append(
                'Particle system "{0}" could not be created: {1}'.format(
                    label, exc
                )
            )
            continue

        warnings.append(
            'Particle system "{0}" carries {1} point(s); Unreal has no point '
            "cloud this build can fill, so it arrived as an anchor. Its points "
            "are used by any instancer that scatters onto it.".format(
                label, len(points)
            )
        )
        if record.get("samples"):
            warnings.append(
                'Particle system "{0}" carries per-frame samples, which this '
                "build does not animate in Unreal.".format(label)
            )

    return {"particle_count": created, "positions": positions}
