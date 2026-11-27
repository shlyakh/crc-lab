"""Damage curves of ``curves.yaml`` as CRC impacts (FR1): ``Impact.tabulated``, linear between
points, a depth outside the table an error (``ImpactError`` ``out_of_domain``)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import crc_framework as cf
import yaml

CURVES = Path(__file__).resolve().parents[1] / "curves" / "curves.yaml"

DEPTH = cf.DepthAboveGround(unit=cf.LengthUnit.METRE)
#: Hazus building curves are indexed by depth above the top of the finished first floor; CRC has
#: no measurement for it, so it is an open one (crc-sdk rules: custom quantities need no registry)
DEPTH_ABOVE_FIRST_FLOOR = cf.Measurement(quantity="depth_above_first_floor", unit="m")


def load(path: Path = CURVES) -> dict[str, Any]:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def impact(entry: dict[str, Any]) -> cf.Impact:
    """One curve of ``curves.yaml`` as a CRC impact, its input chosen by the curve's datum."""
    datum = entry["datum"]
    if datum == "above ground":
        measurement = DEPTH
    elif datum == "above first floor":
        measurement = DEPTH_ABOVE_FIRST_FLOOR
    else:
        raise ValueError(f"{entry['id']}: unknown datum {datum!r}")
    points = [(float(d), float(r)) for d, r in entry["points"]]
    return cf.Impact.tabulated(points, input=measurement, output=cf.Ratio())


def substation_impacts(curves: dict[str, Any] | None = None) -> dict[str, cf.Impact]:
    curves = load() if curves is None else curves
    return {e["id"]: impact(e) for e in curves["substation_curves"]}


def building_impacts(curves: dict[str, Any] | None = None) -> dict[str, cf.Impact]:
    curves = load() if curves is None else curves
    return {e["id"]: impact(e) for e in curves["building_curves"]}
