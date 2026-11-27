"""Write ``curves.yaml``, the one file of damage curves (FR1), from the readers and the envelope.

``uv run python -m flood_lab.curves.build``. Generated, not typed: each curve carries its source,
tag, native hazard metric, datum and the checksums of the files it was read from. Building curves
are every structure curve the FAST riverine default-assignment table names, with their values and
source text from SPHERE's copy of the Hazus tables (``flBldgDmgFn.csv``, MIT licence; FEMA Hazus
data; Yuri, 2026-11-27), in depth above the first floor as published. FAST's library
(``flBldgStructDmgFn.csv``, GPL-3.0) is the cross-check: the build stops if a curve's values
differ. The assignment stays FAST's rule: SPHERE's riverine cross-reference ``flDmgXRef.csv``
gives a different curve for a building of the asset table (EDU2 recorded with 1900 storeys), so
it is not used to choose the curves.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import yaml

from flood_lab import paths
from flood_lab.curves import envelope, hazus
from flood_lab.curves.readers import PointCurve, read_nirandjan_f2, source_file

OUT = Path(__file__).resolve().parent / "curves.yaml"
NIRANDJAN = (
    paths.CACHE
    / "substation-curves-nirandjan"
    / ("Table_D2_Hazard_Fragility_and_Vulnerability_Curves_V1.1.0.xlsx")
)
FAST = paths.CACHE / "hazus-flood-functions" / "fast"
SPHERE = paths.CACHE / "hazus-flood-functions" / "sphere"
SPHERE_LICENCE = (
    f"MIT (SPHERE, Copyright (c) 2025-2026 NiyamIT, Inc., commit {hazus.SPHERE_COMMIT}); "
    "values are FEMA Hazus data"
)
FAST_LICENCE = f"GPL-3.0 (FEMA FAST, commit {hazus.FAST_COMMIT})"


def building_curves(lut, sphere: dict, fast: dict) -> list:
    """SPHERE's curve for every DDF_ID of FAST's riverine table; ``ValueError`` if FAST differs."""
    ids = sorted({int(i) for i in lut["DDF_ID"].dropna()})
    faults = [
        i
        for i in ids
        if i not in sphere
        or i not in fast
        or (sphere[i].depth_ft, sphere[i].percent) != (fast[i].depth_ft, fast[i].percent)
    ]
    if faults:
        raise ValueError(f"structure curves missing or different in SPHERE and FAST: {faults}")
    return [sphere[i] for i in ids]


def _entry(curve: PointCurve, family: str, confidence: str) -> dict:
    return {
        "id": curve.id,
        "family": family,
        "hazard_metric": "inundation depth",
        "unit": "m",
        "datum": curve.datum,
        "output": "damage ratio (fraction of replacement value)",
        "source": curve.source,
        "tag": curve.tag,
        "confidence": confidence,
        "note": curve.note,
        "points": [
            [round(d, 6), round(r, 6)] for d, r in zip(curve.depth_m, curve.ratio, strict=True)
        ],
    }


def build() -> dict:
    _, nirandjan_file = read_nirandjan_f2(NIRANDJAN)
    lut_path = FAST / "Building_DDF_Riverine_LUT_Hazus4p0.csv"
    lib_path = FAST / "flBldgStructDmgFn.csv"
    sphere_path = SPHERE / "flBldgDmgFn.csv"
    lut = hazus.read_assignment(lut_path)
    library = hazus.read_library(lib_path)
    sphere = hazus.read_sphere_library(sphere_path)
    confidence = {
        "nirandjan_F2": "low bound of the envelope; Hazus-type, read from a compilation",
        "bor": "alternative; preprint, HV >345 kV anchored only",
    }
    substations = [
        _entry(c, "substation", confidence.get(c.id, "expert elicitation, New Zealand"))
        for c in envelope.substation_curves(NIRANDJAN).values()
    ]
    buildings = []
    for c in building_curves(lut, sphere, library):
        entry = _entry(c.to_points(), "building", "Hazus default")
        fast = library[c.ddf_id]
        entry["note"] += (
            f"; identical row in FAST {hazus.FAST_COMMIT} flBldgStructDmgFn.csv "
            f"({fast.occupancy}: {fast.description})"
        )
        buildings.append(entry)
    sources = [
        {"path": str(Path(f.path).relative_to(paths.ROOT)), "sha256": f.sha256, "bytes": f.bytes}
        for f in (
            nirandjan_file,
            source_file(sphere_path),
            source_file(lut_path),
            source_file(lib_path),
        )
    ]
    roles = [
        ("CC BY 4.0", "substation curves"),
        (SPHERE_LICENCE, "building curve values"),
        (FAST_LICENCE, "building curve assignment (riverine default)"),
        (FAST_LICENCE, "cross-check of the building curve values (identical)"),
    ]
    for entry, (licence, role) in zip(sources, roles, strict=True):
        entry["licence"] = licence
        entry["used_for"] = role
    sources += [
        {"cited": envelope.WILLIAMS_CITATION, "licence": "CC BY-NC-ND (values cited, not copied)"},
        {"cited": "Bor et al. 2026, arXiv 2605.23053v1, Table 1", "licence": "CC BY 4.0"},
    ]
    return {
        "generated_by": "flood_lab.curves.build",
        "max_depth_m": {"value": envelope.MAX_DEPTH_M, "tag": "P"},
        "rules": {
            "substations": envelope.__doc__.split("Rules that are ours")[1]
            .split("No crc")[0]
            .strip(),
            "buildings": (
                "Depth above the top of the finished first floor = inundation depth above ground "
                "minus first-floor height above grade (Hazus 7.0 Flood TM p. 2-3, 8-2) [S]. "
                "Points from -4 to 24 ft as published, in metres [I]. The rule for a dry "
                "building and for depths outside -4..24 ft is set at the event-loss step."
            ),
        },
        "sources": sources,
        "substation_curves": substations,
        "building_curves": buildings,
    }


def main() -> None:
    text = yaml.safe_dump(build(), sort_keys=False, width=100, allow_unicode=True)
    fd, tmp = tempfile.mkstemp(dir=OUT.parent, suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write("# Generated by `uv run python -m flood_lab.curves.build`; do not edit.\n" + text)
    os.replace(tmp, OUT)
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
