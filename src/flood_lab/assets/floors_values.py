"""First-floor heights, basements and values of the assets, for the loss stage F6 (FR3, FD4, FD5).

Two tables are taken from the asset table ``assets_oed.csv`` (F1) and nothing new is estimated:

* ``first_floors``: one row per building. Hazus building curves take depth above the top of the
  finished first floor, that is inundation depth above ground less the first-floor height above
  grade (CH-25), so each building needs that height. The order of the sources is fixed:

  1. the city's Building Elevation and Subgrade table (``lab_first_floor_height_m``, z_floor less
     z_grade, converted to metres in F1), source ``"city table"``, tag S;
  2. else the National Structure Inventory's ``found_ht`` of the building's inventory point (the
     point of largest ``val_struct``, ``lab_nsi_id``), feet converted to metres here, source
     ``"NSI found_ht"``. Its tag is ``"default"``, the publisher's own word for it: "Foundation
     heights are assigned by foundation type. For example, RES1 slab foundations are assigned a
     default height of 0.75 feet and basement foundations are assigned a default height of 2
     feet." (NSI technical documentation, section on foundations, cached as
     ``usace-national-structure-inventory/docs/technical-documentation.html``). It is not a
     measurement of the building and is never labelled as one;
  3. else empty, source ``""``. No default from any other table is filled in here (the Hazus 7
     Inventory Technical Manual's Table 5-13 would fill none of the empty ones).

  Rules FF-1 to FF-5 of ``docs/flood/loss-rules.md`` (accepted by Yuri 2026-11-27, CH-29), all
  thresholds [P]:

  * FF-1: the city's height is the main case, as the table holds it (negative values kept);
  * FF-2: a city height above ``FLAG_ABOVE_M`` is used and flagged ``above_3m``;
  * FF-3: a city height above ``SUSPECT_ABOVE_M`` is taken as a data error: it is not used
    (``ffh_city_m`` keeps it for display), the building falls to step 2, flag ``city_suspect``;
  * FF-4: where the city marks the grade as estimated, ``ffh_alt_m`` is the first-floor elevation
    less our 1 m terrain at the footprint centre, for a sensitivity run, flag ``grade_estimated``
    (subject to FF-3 too: above ``SUSPECT_ABOVE_M`` it is left empty);
  * FF-5: a city height below 0 m is used and flagged ``below_grade``.

  ``basement`` is the city's subgrade flag (``lab_subgrade``, ``"Y"`` or ``"N"``); where that is
  empty, it is ``"Y"`` when the inventory point's ``found_type`` is ``"B"`` (basement) and ``"N"``
  for any other stated foundation type, source ``"NSI found_type"``; else empty. The city's ``"N"``
  means "none seen from the street" (its guidance), the inventory's type is assigned from
  tax-assessor data and regional distributions: neither is a survey of the building's interior.

* ``asset_values``: one row per asset kept in the study, with the low, mid and high value exactly
  as the asset table holds them, their tag and source, and the price year each source states.
  A substation whose review says "removed..." is left out. A value with no tag S, I or P stops the
  build. No figure is converted to another price year: requirement §5 asks for 2026 dollars with a
  stated index, and the index is Yuri's choice.

Empty means not known: a missing number is ``<NA>`` in the frame and an empty cell in a CSV, never
zero. This module imports no crc package.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

import pandas as pd

from flood_lab.assets.buildings import FOOT_M

FIRST_FLOOR_COLUMNS = (
    "LocNumber",
    "ffh_m",
    "ffh_source",
    "ffh_tag",
    "basement",
    "basement_source",
    "ffh_flags",
    "ffh_city_m",
    "ffh_alt_m",
)
VALUE_COLUMNS = (
    "LocNumber",
    "asset_type",
    "value_low_usd",
    "value_mid_usd",
    "value_high_usd",
    "value_tag",
    "value_source",
    "price_year",
    "price_year_source",
)
VALUE_TAGS = ("S", "I", "P")

CITY = "city table"
NSI_HEIGHT = "NSI found_ht"
NSI_TYPE = "NSI found_type"
CITY_FLAG = CITY  # the subgrade flag of the same table
#: FF-2: a city height above this is flagged, metres [P] (docs/flood/loss-rules.md)
FLAG_ABOVE_M = 3.0
#: FF-3: a city height above this is taken as a data error and not used, metres [P]
SUSPECT_ABOVE_M = 6.0
#: the phrase of ``lab_ground_elev_source`` that marks an estimated grade (assets/buildings.py)
GRADE_ESTIMATED = "estimated"
#: the tag of each first-floor source: S stated by the source; "default" is the inventory's own word
FFH_TAGS = {CITY: "S", NSI_HEIGHT: "default"}

#: the price year of the inventory's values and the passages that state it
NSI_PRICE_YEAR = "2025-08"
NSI_PRICE_YEAR_SOURCE = (
    "NSI technical documentation (usace-national-structure-inventory/docs/"
    "technical-documentation.html, 'Full Replacement Cost'): 'All values are reported in August "
    "2025 price levels.'; same file, 'Version Notes': 'Price level: August 2025'; FAQ "
    "(frequently-asked-questions.html, 'What is the price level of the NSI?'): 'NSI dollar values "
    "represent estimated replacement costs as of approximately August 2025.'"
)
#: why the substation figures carry no price year
SUBSTATION_PRICE_YEAR_SOURCE = (
    "not stated unambiguously by either source, left empty. Low (MISO Transmission Cost "
    "Estimation Guide for MTEP24, f1/cost/miso-mtep24-guide-20240501.pdf, PDF page 2): 'All cost "
    "estimate data in this document are in 2023 U.S. dollars. Cost data was escalated from 2023 "
    "U.S. dollars to 2024 U.S. dollars at a rate of 5%.' (2023 or 2024: the two sentences "
    "disagree). High (Con Edison Idlewild petition, NY PSC Case 22-E-0064, "
    "f1/cost/coned-idlewild-petition-20230822.pdf, annex 'Basis for Estimate', printed page 7): "
    "'The funding request is based on order of magnitude estimates' with a request by year 2023 "
    "to 2028; no price year or escalation is stated. Mid: the geometric mean of the two, "
    "no price year of its own."
)


def _empty(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return value.strip() == ""
    try:
        return bool(pd.isna(value))
    except (TypeError, ValueError):
        return False


def _number(value: Any) -> float | None:
    if _empty(value):
        return None
    return float(value)


def _text(value: Any) -> str:
    return "" if _empty(value) else str(value).strip()


def _id(value: Any) -> str:
    """An inventory id as digits: ``74109145``, ``74109145.0`` and ``"74109145"`` are the same."""
    text = _text(value)
    if text.endswith(".0"):
        text = text[:-2]
    return text


def read_nsi_points(nsi: Path) -> dict[str, dict[str, Any]]:
    """``found_ht`` (feet) and ``found_type`` of each inventory point, by ``fd_id``."""
    document = json.loads(Path(nsi).read_text(encoding="utf-8"))
    points: dict[str, dict[str, Any]] = {}
    for feature in document["features"]:
        properties = feature["properties"]
        points[_id(properties.get("fd_id"))] = {
            "found_ht": properties.get("found_ht"),
            "found_type": properties.get("found_type"),
        }
    return points


def first_floors(assets: pd.DataFrame, nsi: Path) -> pd.DataFrame:
    """First-floor height above grade (metres) and basement flag of every building."""
    points = read_nsi_points(nsi)
    rows = []
    for _, asset in assets[assets["lab_asset_type"] == "building"].iterrows():
        point = points.get(_id(asset.get("lab_nsi_id")), {})
        city = _number(asset.get("lab_first_floor_height_m"))
        found_ht = _number(point.get("found_ht"))
        flags = []
        alt = None
        if city is not None:
            if city > SUSPECT_ABOVE_M:
                flags.append("city_suspect")
            elif city > FLAG_ABOVE_M:
                flags.append("above_3m")
            elif city < 0:
                flags.append("below_grade")
            if GRADE_ESTIMATED in _text(asset.get("lab_ground_elev_source")):
                flags.append("grade_estimated")
                floor = _number(asset.get("lab_first_floor_elev_m"))
                terrain = _number(asset.get("lab_terrain_elev_m"))
                if floor is not None and terrain is not None:
                    alt = floor - terrain
                    if alt > SUSPECT_ABOVE_M:
                        alt = None
        usable = city is not None and city <= SUSPECT_ABOVE_M
        if usable:
            height, source = city, CITY
        elif found_ht is not None:
            height, source = found_ht * FOOT_M, NSI_HEIGHT
        else:
            height, source = None, ""
        flag = _text(asset.get("lab_subgrade"))
        found_type = _text(point.get("found_type"))
        if flag in ("Y", "N"):
            basement, basement_source = flag, CITY_FLAG
        elif flag:
            raise ValueError(f"{asset['LocNumber']}: lab_subgrade is {flag!r}, not Y, N or empty")
        elif found_type:
            basement, basement_source = ("Y" if found_type == "B" else "N"), NSI_TYPE
        else:
            basement, basement_source = "", ""
        rows.append(
            {
                "LocNumber": asset["LocNumber"],
                "ffh_m": height,
                "ffh_source": source,
                "ffh_tag": FFH_TAGS.get(source, ""),
                "basement": basement,
                "basement_source": basement_source,
                "ffh_flags": ";".join(flags),
                "ffh_city_m": city,
                "ffh_alt_m": alt,
            }
        )
    frame = pd.DataFrame(rows, columns=list(FIRST_FLOOR_COLUMNS))
    for column in ("ffh_m", "ffh_city_m", "ffh_alt_m"):
        frame[column] = frame[column].astype("Float64")
    return frame


def is_removed(asset: pd.Series) -> bool:
    """A substation whose imagery review removed it from the study (the row stays in the table)."""
    return asset["lab_asset_type"] == "substation" and _text(asset.get("lab_reviewed")).startswith(
        "removed"
    )


def _price_year(kind: str, source: str) -> tuple[str, str]:
    if kind == "building" and "NSI" in source and "val_struct" in source:
        return NSI_PRICE_YEAR, NSI_PRICE_YEAR_SOURCE
    if kind == "substation" and "MISO" in source and "Con Edison" in source:
        return "", SUBSTATION_PRICE_YEAR_SOURCE
    return "", "price year not determined: the value's source is not one read for F6"


def asset_values(assets: pd.DataFrame) -> pd.DataFrame:
    """Low, mid and high value of every asset kept in the study, with tag, source and price year."""
    rows = []
    for _, asset in assets.iterrows():
        if is_removed(asset):
            continue
        values = {
            level: _number(asset.get(f"lab_value_{level}_usd")) for level in ("low", "mid", "high")
        }
        tag = _text(asset.get("lab_value_tag"))
        source = _text(asset.get("lab_value_source"))
        given = [v for v in values.values() if v is not None]
        if given and tag not in VALUE_TAGS:
            raise ValueError(f"{asset['LocNumber']}: a value without a tag S, I or P ({tag!r})")
        if any(v == 0 for v in given):
            raise ValueError(f"{asset['LocNumber']}: a value of zero; an unknown value is empty")
        year, year_source = _price_year(asset["lab_asset_type"], source) if given else ("", "")
        rows.append(
            {
                "LocNumber": asset["LocNumber"],
                "asset_type": asset["lab_asset_type"],
                "value_low_usd": values["low"],
                "value_mid_usd": values["mid"],
                "value_high_usd": values["high"],
                "value_tag": tag if given else "",
                "value_source": source if given else "",
                "price_year": year,
                "price_year_source": year_source,
            }
        )
    frame = pd.DataFrame(rows, columns=list(VALUE_COLUMNS))
    for level in ("low", "mid", "high"):
        frame[f"value_{level}_usd"] = frame[f"value_{level}_usd"].astype("Float64")
    return frame


def write_csv(frame: pd.DataFrame, path: Path) -> None:
    """Write a table atomically; an unknown number is an empty cell."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(handle, "w", newline="", encoding="utf-8") as stream:
            frame.to_csv(stream, index=False, na_rep="")
        os.replace(temporary, path)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise
