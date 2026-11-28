"""Exposures: occupancy, storeys, basement, first floor, value and curve of every asset (F6, CH-31).

One row per asset of ``assets_oed.csv`` (buildings and substations), written to
``site/flood/data/exposures.csv`` beside the asset table. For each quantity the row holds the value,
a ``*_source`` naming where it came from and a ``*_substitute`` flag that is True when the value is
a substitute rather than stated for this asset; ``asset_substitute_class`` lists every substitute
kind that applies. Rules A-1 to A-12 and V-6 of ``docs/flood/loss-rules.md`` (section "Occupancy,
storeys and value gaps (A)"); the IDs are cited at the code that applies them.

Every building lands in exactly one route (``route``):

* ``nsi``: the National Structure Inventory (NSI) point gives occupancy, storeys and value; the
  Hazus structure curve follows FAST's rule (C-2).
* ``nsi suffix``: the NSI occupancy carries a suffix (``RES1-2SWB``), which FAST cannot match.
  A-1: base class RES1, storeys from ``NumberOfStoreys``, basement from our flag.
* ``pluto``: no NSI point; PLUTO's building class of the lot maps to a Hazus class (A-2, table
  ``PLUTO_CLASS``).
* ``neighbour``: no NSI point and no usable PLUTO class; the most common class among NSI
  buildings within ``NEIGHBOUR_M`` (A-6), else the study-area mode.

Values of buildings without an NSI point are Hazus 7 Inventory TM Table 6-2 / 6-3 cost per square
foot times floor area (footprint area times storeys), A-8; they carry no location factor (the
manual's county factors are in the Hazus database, not in the manual) and no depreciation. Every
value is converted to 2026 dollars by V-2 (USACE CWCCIS, feature code 19, target 4Q26).

Empty means not known: never zero. This module imports no crc package.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import tempfile
from collections import Counter
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import shapely

from flood_lab import cache, paths
from flood_lab.assets import buildings, floors_values
from flood_lab.curves import envelope, hazus
from flood_lab.sources import nyc_pluto

OUT_CSV = paths.SITE / "data" / "exposures.csv"
OUT_SUMMARY = paths.SITE / "data" / "exposures_summary.json"

# --- V-2, V-4, V-5, V-6: price conversion ------------------------------------------------------

#: USACE CWCCIS tables of 31 March 2026, Table 1, feature code 19 "Buildings, grounds &
#: utilities" [S] (facts usace-cwccis, fact index_values_quarterly_2023_to_2026; 4Q22 from
#: Table 1 page 22, columns 1Q22 to 4Q23: 1129.16 1162.67 1169.55 1143.96 ...)
CWCCIS_19 = {"4Q22": 1143.96, "4Q24": 1137.95, "4Q25": 1175.35, "4Q26": 1207.05}
#: V-3: target quarter [P], accepted
TARGET_QUARTER = "4Q26"
#: V-5 (buildings, NSI, August 2025) and V-5 (substations) [P], accepted
NSI_QUARTER = "4Q25"
SUBSTATION_QUARTER = "4Q24"
#: V-6 (proposed): Hazus 7 Table 6-2/6-3 prices are "(2022)" with no month; the middle of
#: calendar 2022 (July-September 2022) is fiscal 4Q22, as V-5 does for "2024" [P]
HAZUS_QUARTER = "4Q22"


def to_2026(value: float | None, quarter: str) -> float | None:
    """V-2: value x index(4Q26) / index(source quarter), both feature code 19; None stays None."""
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return None
    return float(value) * CWCCIS_19[TARGET_QUARTER] / CWCCIS_19[quarter]


def factor(quarter: str) -> float:
    return CWCCIS_19[TARGET_QUARTER] / CWCCIS_19[quarter]


# --- A-8: Hazus replacement cost per square foot -----------------------------------------------

#: Hazus 7.0 Inventory Technical Manual (FEMA, June 2025), Table 6-2 "Default Full Structure
#: Replacement Cost", Structure Replacement Cost/ft2 (2022), printed pages 6-2 and 6-3 [S]
HAZUS_COST_FT2 = {
    "RES3A": 134.57,
    "RES3B": 118.30,
    "RES3C": 250.19,
    "RES3D": 232.69,
    "RES3E": 217.05,
    "RES3F": 198.83,
    "RES4": 204.58,
    "RES5": 225.12,
    "RES6": 261.45,
    "COM1": 133.61,
    "COM2": 135.47,
    "COM3": 162.58,
    "COM4": 204.43,
    "COM5": 303.88,
    "COM6": 392.76,
    "COM7": 279.38,
    "COM8": 259.48,
    "COM9": 213.33,
    "COM10": 93.88,
    "IND1": 162.65,
    "IND2": 135.47,
    "IND3": 230.43,
    "IND4": 230.43,
    "IND5": 230.43,
    "IND6": 135.47,
    "AGR1": 135.47,
    "REL1": 222.10,
    "GOV1": 174.35,
    "GOV2": 284.46,
    "EDU1": 237.73,
    "EDU2": 197.10,
}
#: Table 6-3 "Replacement Costs for RES1 Structures", 2022 average cost per ft2, printed page
#: 6-4 [S]: (construction class, storeys) -> (no basement, finished basement, unfinished basement)
HAZUS_RES1_FT2 = {
    ("Economy", 1): (114.63, 148.48, 125.03),
    ("Economy", 2): (121.00, 139.95, 127.75),
    ("Economy", 3): (121.00, 139.95, 127.75),
    ("Average", 1): (128.20, 168.75, 140.95),
    ("Average", 2): (132.88, 158.08, 140.98),
    ("Average", 3): (137.43, 156.88, 143.73),
    ("Custom", 1): (172.73, 234.63, 196.98),
    ("Custom", 2): (174.96, 210.21, 189.21),
    ("Custom", 3): (179.34, 204.94, 189.84),
    ("Luxury", 1): (209.44, 274.34, 234.29),
    ("Luxury", 2): (212.86, 250.56, 227.86),
    ("Luxury", 3): (218.28, 245.93, 229.53),
}
#: A-9 [P]: Table 6-3's construction classes for low, mid and high (the table's full range)
RES1_LEVELS = {"low": "Economy", "mid": "Average", "high": "Luxury"}
#: Table 6-8, Middle Atlantic (NJ, NY, PA; Table 3-1 p. 3-3): 58% with basement, 42% without [S];
#: Hazus's own weighting where a basement is not known, basement then taken unfinished
#: (Equation 6-1 text, p. 6-8) [S]
MIDDLE_ATLANTIC_BASEMENT = 0.58
#: square feet per square metre, from the international foot [I]
FT2_PER_M2 = 1.0 / (buildings.FOOT_M**2)


def hazus_cost(occupancy: str, storeys: int | None, basement: str) -> dict[str, float | None]:
    """A-8/A-9: cost per ft2 (2022 USD) for low, mid, high; RES1 by Table 6-3, else Table 6-2.

    Outside RES1 only ``mid`` is given (Table 6-2 has one figure). Unknown occupancy gives None.
    """
    empty: dict[str, float | None] = {"low": None, "mid": None, "high": None}
    if occupancy == "RES1":
        if storeys is None:
            return empty
        height = min(max(int(storeys), 1), 3)  # A-9: above three storeys, Table 6-3's three-story
        out: dict[str, float | None] = {}
        for level, klass in RES1_LEVELS.items():
            none, _finished, unfinished = HAZUS_RES1_FT2[(klass, height)]
            if basement == "Y":
                out[level] = unfinished
            elif basement == "N":
                out[level] = none
            else:
                w = MIDDLE_ATLANTIC_BASEMENT
                out[level] = w * unfinished + (1 - w) * none
        return out
    cost = HAZUS_COST_FT2.get(occupancy)
    return {"low": None, "mid": cost, "high": None} if cost is not None else empty


def hazus_value(
    occupancy: str, storeys: int | None, basement: str, footprint_m2: float | None
) -> dict[str, float | None]:
    """A-8: cost per ft2 x footprint area x storeys, in 2026 USD (V-2 from ``HAZUS_QUARTER``)."""
    if storeys is None or footprint_m2 is None or not footprint_m2 > 0 or storeys < 1:
        return {"low": None, "mid": None, "high": None}
    area_ft2 = footprint_m2 * FT2_PER_M2 * storeys
    return {
        level: to_2026(cost * area_ft2, HAZUS_QUARTER) if cost is not None else None
        for level, cost in hazus_cost(occupancy, storeys, basement).items()
    }


# --- A-1: NSI suffix pre-step ------------------------------------------------------------------


def suffix_parts(occupancy: str) -> tuple[str, int, str] | None:
    """``RES1-2SWB`` -> ("RES1", 2, "Y"); ``RES1-3SNB`` -> ("RES1", 3, "N"); else None."""
    text = (occupancy or "").strip()
    if not text.startswith("RES1-") or len(text) != 9:
        return None
    middle = text[5:]
    if not (middle[0].isdigit() and middle[1] == "S" and middle[2:] in ("WB", "NB")):
        return None
    return "RES1", int(middle[0]), "Y" if middle[2:] == "WB" else "N"


# --- A-2: PLUTO building class to Hazus occupancy ----------------------------------------------

BY_UNITS = "RES3 by units"
#: A-3 [P]: residential units on the lot to Hazus RES3 (Table 4-1, p. 4-2 [S]: RES3A duplex,
#: RES3B 3-4 units, RES3C 5-9, RES3D 10-19, RES3E 20-49, RES3F 50+); a lot with one unit or two
#: takes RES3A, since Table 4-1 has no RES3 class below the duplex
UNIT_CLASSES = ((50, "RES3F"), (20, "RES3E"), (10, "RES3D"), (5, "RES3C"), (3, "RES3B"))

#: A-2 [P], every row: PLUTO 26v3 building class (data dictionary Appendix C, pp. 51-54) ->
#: Hazus specific occupancy (Inventory TM Table 4-1, p. 4-2), and the reason. An empty target
#: means the class names no building use (vacant land, easement, other): the building takes
#: route ``neighbour`` (A-6).
PLUTO_CLASS: dict[str, tuple[str, str]] = {
    **{f"A{d}": ("RES1", "one family dwelling") for d in "0123456789"},
    **{f"B{d}": ("RES3A", "two family dwelling: duplex") for d in "1239"},
    "C0": ("RES3B", "three families: 3-4 units"),
    "C3": ("RES3B", "four families: 3-4 units"),
    "C2": ("RES3C", "five to six families: 5-9 units"),
    **{
        f"C{d}": (BY_UNITS, "walk-up apartments, size from the lot's units")
        for d in ("1", "4", "5", "6", "7", "8", "9", "B", "M")
    },
    **{
        f"D{d}": (BY_UNITS, "elevator apartments, size from the lot's units") for d in "0123456789B"
    },
    **{f"E{d}": ("IND2", "warehouse: Table 6-2 warehouse model") for d in "12349"},
    "E7": ("IND2", "self-storage warehouse: Table 6-2 warehouse model"),
    **{f"F{d}": ("IND1", "heavy or fireproof factory") for d in "1248"},
    "F5": ("IND2", "light manufacturing"),
    "F9": ("IND2", "miscellaneous factory"),
    "G0": ("COM10", "residential garage"),
    "G1": ("COM10", "parking garage"),
    "G2": ("COM3", "auto body or repair"),
    "G3": ("COM1", "gas station with retail store"),
    "G4": ("COM3", "gas station with auto repair"),
    "G5": ("COM1", "gas station"),
    "G6": ("COM10", "licensed parking lot"),
    "G7": ("COM10", "unlicensed parking lot"),
    "G8": ("COM1", "car sales with showroom"),
    "G9": ("COM3", "miscellaneous garage or gas station"),
    "GU": ("COM1", "car sales without showroom"),
    "GW": ("COM3", "car wash or lubritorium"),
    **{f"H{d}": ("RES4", "hotel: temporary lodging") for d in ("1", "2", "3", "4", "5", "9")},
    "HB": ("RES4", "boutique hotel"),
    "HH": ("RES4", "hostel"),
    "HR": ("RES4", "single room occupancy"),
    "HS": ("RES4", "extended stay"),
    "H6": (BY_UNITS, "apartment hotel (land use 03, multi-family elevator)"),
    "H7": (BY_UNITS, "apartment hotel, co-op (land use 03)"),
    "H8": ("RES5", "dormitory"),
    "I1": ("COM6", "hospital"),
    "I2": ("COM6", "infirmary"),
    "I3": ("COM7", "dispensary"),
    "I4": ("COM7", "staff facilities of a hospital"),
    "I5": ("COM7", "health centre, clinic"),
    "I6": ("RES6", "nursing home"),
    "I7": ("RES6", "adult care facility"),
    "I9": ("COM7", "miscellaneous health"),
    **{f"J{d}": ("COM9", "theatre") for d in "12345789"},
    "J6": ("COM4", "television studio"),
    **{f"K{d}": ("COM1", "store building: retail trade") for d in "12346889"},
    "K5": ("COM8", "stand-alone food establishment (Table 6-2 model: restaurant)"),
    "K7": ("COM5", "banking facility"),
    **{f"L{d}": ("IND2", "loft building (land use 06)") for d in "12389"},
    **{f"M{d}": ("REL1", "church, synagogue, mission, parsonage, convent") for d in "12349"},
    **{f"N{d}": ("RES6", "asylum or home") for d in "12349"},
    **{f"O{d}": ("COM4", "office building") for d in "12345679"},
    "O8": (BY_UNITS, "office with apartments only (land use 04)"),
    "P1": ("COM9", "concert hall"),
    "P2": ("COM8", "lodge rooms"),
    "P3": ("COM8", "YMCA and similar"),
    "P4": ("COM8", "beach club"),
    "P5": ("COM8", "community centre"),
    "P6": ("COM8", "amusement place"),
    "P7": ("COM8", "museum"),
    "P8": ("EDU1", "library (Table 4-1: schools/libraries)"),
    "P9": ("COM8", "miscellaneous place of assembly"),
    **{f"Q{d}": ("COM8", "outdoor recreation facility") for d in "0123456789"},
    "QG": ("COM8", "community garden"),
    "R0": (BY_UNITS, "condominium billing lot"),
    **{f"R{d}": (BY_UNITS, "residential condominium unit") for d in "12346"},
    "RD": (BY_UNITS, "residential condominium"),
    "RM": (BY_UNITS, "mixed residential and commercial condominium"),
    "RR": (BY_UNITS, "condominium rentals"),
    "RX": (BY_UNITS, "mixed residential, commercial and industrial condominium"),
    "RZ": (BY_UNITS, "mixed residential and warehouse condominium"),
    "R9": (BY_UNITS, "co-op within a condominium"),
    "R5": ("COM1", "miscellaneous commercial condominium"),
    "R7": ("COM1", "commercial unit of 1-3 unit building"),
    "R8": ("COM1", "commercial unit of 2-10 unit building"),
    "RA": ("COM4", "cultural, medical, educational condominium"),
    "RB": ("COM4", "office condominium"),
    "RC": ("COM1", "commercial condominium"),
    "RG": ("COM10", "indoor parking condominium"),
    "RH": ("RES4", "hotel condominium"),
    "RI": ("IND2", "mixed warehouse/industrial and commercial condominium"),
    "RK": ("COM1", "retail condominium"),
    "RP": ("COM10", "outdoor parking condominium"),
    "RS": ("COM2", "non-business storage condominium"),
    "RT": (BY_UNITS, "terraces, gardens, cabanas of a condominium"),
    "RW": ("IND2", "warehouse/factory/industrial condominium"),
    "S0": ("RES1", "primarily one family with two stores or offices"),
    "S1": ("RES1", "primarily one family with one store or office"),
    "S2": ("RES3A", "primarily two family with one store or office"),
    "S3": ("RES3B", "primarily three family with one store or office"),
    "S4": ("RES3B", "primarily four family with one store or office"),
    "S5": ("RES3C", "primarily five to six family with one store or office"),
    "S9": (BY_UNITS, "single or multiple dwelling with stores or offices"),
    "T1": ("COM4", "airport terminal"),
    "T2": ("IND2", "pier, dock, bulkhead"),
    "T9": ("IND2", "miscellaneous transportation facility"),
    **{f"U{d}": ("IND2", "utility property") for d in "0123456789"},
    **{f"V{d}": ("", "vacant land: names no building use") for d in "0123456789"},
    **{f"W{d}": ("EDU1", "school") for d in "123489"},
    "W5": ("EDU2", "city university"),
    "W6": ("EDU2", "other college and university"),
    "W7": ("EDU2", "theological seminary"),
    "Y1": ("GOV2", "fire department"),
    "Y2": ("GOV2", "police department"),
    **{f"Y{d}": ("GOV1", "selected government installation") for d in "3456789"},
    "Z0": ("", "tennis court, pool, shed: names no building use"),
    "Z1": ("GOV1", "court house"),
    "Z2": ("COM10", "public parking area"),
    "Z3": ("GOV1", "post office"),
    "Z4": ("GOV1", "foreign government"),
    "Z5": ("GOV1", "United Nations"),
    "Z7": ("", "easement: names no building use"),
    "Z8": ("REL1", "cemetery"),
    "Z9": ("", "other: names no building use"),
    "": ("", "no building class"),
}


def units_class(units: float | None) -> str:
    """A-3: Hazus RES3 class by residential units; "" when units are not known (0 or empty)."""
    if units is None or (isinstance(units, float) and math.isnan(units)) or units <= 0:
        return ""
    for low, klass in UNIT_CLASSES:
        if units >= low:
            return klass
    return "RES3A"


def pluto_occupancy(building_class: str, units: float | None) -> tuple[str, str]:
    """A-2/A-3: (Hazus occupancy or "", reason). A class not in the table raises ``KeyError``."""
    target, reason = PLUTO_CLASS[building_class.strip()]
    if target == BY_UNITS:
        klass = units_class(units)
        return klass, f"{reason}; {units:g} units" if klass else f"{reason}; units not known"
    return target, reason


# --- A-5: basement from PLUTO ------------------------------------------------------------------

#: PLUTO data dictionary 26v3, BASEMENT TYPE/GRADE (BsmtCode), p. 32 [S]: 0 none, 1 above grade
#: full, 2 below grade full, 3 above grade partial, 4 below grade partial, 5 unknown; "This
#: information is available for one, two or three family structures."
BSMT_MEANING = {"0": "N", "1": "Y", "2": "Y", "3": "Y", "4": "Y"}
#: A-5 [P]: the dictionary's "one, two or three family structures" as building classes
ONE_TO_THREE_FAMILY = (
    tuple(f"A{d}" for d in "0123456789") + tuple(f"B{d}" for d in "1239") + ("C0",)
)


def pluto_basement(code: str, building_class: str, single_building: bool) -> str:
    """A-5: Y or N from BsmtCode on a single-building lot of a 1-3 family class; else ""."""
    if not single_building or building_class not in ONE_TO_THREE_FAMILY:
        return ""
    return BSMT_MEANING.get((code or "").strip(), "")


# --- A-6, A-7: neighbours and storeys ----------------------------------------------------------

#: A-6 [P]: radius for the most common class (and storeys) among NSI buildings, metres
NEIGHBOUR_M = 100.0
#: A-10 [P]: a footprint smaller than this, square metres, or a garage, is a minor structure
MINOR_M2 = 40.0
GARAGE_CODE = "5110"


def round_storeys(value: float | None) -> int | None:
    """A-4: a storey count as a whole number, half up (a partial floor counts); None if < 0.5."""
    if value is None or (isinstance(value, float) and math.isnan(value)) or value < 0.5:
        return None
    return int(math.floor(value + 0.5))


def mode(values: list[Any]) -> Any:
    """Most common value; ties to the smallest (deterministic); None for no values."""
    if not values:
        return None
    counts = Counter(values)
    top = max(counts.values())
    return min(v for v, c in counts.items() if c == top)


# --- inputs ------------------------------------------------------------------------------------


def read_footprint_lots(path: Path) -> pd.DataFrame:
    """Every footprint of the box: doitt_id, base_bbl, mappluto_bbl, height_roof (ft), area."""
    document = json.loads(Path(path).read_text(encoding="utf-8"))
    rows = []
    for feature in document["features"]:
        p = feature["properties"]
        rows.append(
            {
                "doitt_id": str(p.get("doitt_id") or ""),
                "base_bbl": nyc_pluto.normal_bbl(p.get("base_bbl")),
                "mappluto_bbl": nyc_pluto.normal_bbl(p.get("mappluto_bbl")),
                "height_roof_ft": pd.to_numeric(p.get("height_roof"), errors="coerce"),
            }
        )
    frame = buildings.read_footprints(path)
    out = pd.DataFrame(rows)
    out["geometry"] = frame["geometry"].to_numpy()
    out["area_m2"] = shapely.area(out["geometry"].to_numpy())
    return out


def footprint_points(footprints: pd.DataFrame, nsi: pd.DataFrame, near_m: float) -> np.ndarray:
    """Footprint index of every NSI point (-1 if none), by F1's join (``join_inventory``)."""
    index, _ = buildings.join_inventory(
        list(footprints["geometry"]), nsi["x"].to_numpy(), nsi["y"].to_numpy(), near_m
    )
    return index


def nsi_floor_area(footprints: pd.DataFrame, nsi: pd.DataFrame, index: np.ndarray) -> dict:
    """Sum of NSI ``sqft`` (floor area, ft2) of the points on each footprint, by doitt_id."""
    sqft = pd.to_numeric(nsi["sqft"], errors="coerce").to_numpy() if "sqft" in nsi else []
    out: dict[str, float] = {}
    for row, i in enumerate(index):
        if i >= 0 and np.isfinite(sqft[row]) and sqft[row] > 0:
            doitt = footprints["doitt_id"].iat[int(i)]
            out[doitt] = out.get(doitt, 0.0) + float(sqft[row])
    return out


def gap_causes(
    footprints: pd.DataFrame,
    nsi: pd.DataFrame,
    index: np.ndarray,
    unmatched_doitt: list[str],
    near_m: float,
) -> dict[str, str]:
    """A-11 diagnosis of each building without an NSI point: "A", "B" or "C".

    A: another footprint on the same tax lot (base_bbl) holds NSI points; B: an NSI point lies
    within ``near_m`` of the footprint but went to a footprint on another lot; C: neither.
    ``index`` is ``footprint_points``.
    """
    shapes = list(footprints["geometry"])
    points_on = Counter(int(i) for i in index if i >= 0)
    lot_points: Counter[str] = Counter()
    for i, lot in enumerate(footprints["base_bbl"]):
        lot_points[lot] += points_on.get(i, 0)
    tree = shapely.STRtree(shapely.points(nsi["x"].to_numpy(), nsi["y"].to_numpy()))
    by_id = {d: i for i, d in reversed(list(enumerate(footprints["doitt_id"])))}
    out = {}
    for doitt in unmatched_doitt:
        i = by_id.get(doitt)
        if i is None:
            out[doitt] = ""
            continue
        lot = footprints["base_bbl"].iat[i]
        if lot and lot_points[lot] > 0:
            out[doitt] = "A"
        elif len(tree.query(shapes[i], predicate="dwithin", distance=near_m)):
            out[doitt] = "B"
        else:
            out[doitt] = "C"
    return out


# --- build -------------------------------------------------------------------------------------


def _num(value: Any) -> float | None:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(number) else number


def _text(value: Any) -> str:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return ""
    return str(value).strip()


SUBSTITUTE_KINDS = (
    "suffix base class",
    "PLUTO class",
    "neighbour mode class",
    "study-area mode class",
    "PLUTO lot floors (tallest building)",
    "storeys from roof height",
    "neighbour mode storeys",
    "Hazus cost per ft²",
    "NSI default first-floor height",
)


def build(
    assets: pd.DataFrame,
    detail: pd.DataFrame,
    footprints: pd.DataFrame,
    pluto: pd.DataFrame,
    floors: pd.DataFrame,
    lut: pd.DataFrame,
    causes: dict[str, str],
    nsi_sqft: dict[str, float] | None = None,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """(one row per asset, counts). Inputs are frames so that tests can pass small fixtures.

    ``assets``: the asset table; ``detail``: ``buildings_detail.csv`` (doitt_id, feature code,
    footprint area); ``footprints``: ``read_footprint_lots``; ``pluto``: ``nyc_pluto.read``;
    ``floors``: ``floors_values.first_floors``; ``lut``: FAST's riverine assignment table;
    ``causes``: ``gap_causes`` by doitt_id; ``nsi_sqft``: ``nsi_floor_area`` (only for the
    check column ``hazus_check_mid_usd_2026`` of NSI buildings).
    """
    nsi_sqft = nsi_sqft or {}
    houses = assets[assets["lab_asset_type"] == "building"].merge(
        detail, on="LocNumber", how="left", validate="one_to_one"
    )
    floors = floors.set_index("LocNumber")
    fp_by_id = footprints.drop_duplicates("doitt_id").set_index("doitt_id")
    houses["doitt"] = houses["detail_doitt_id"].map(_text)
    houses["base_bbl"] = houses["doitt"].map(fp_by_id["base_bbl"]).fillna("")
    houses["mappluto_bbl"] = houses["doitt"].map(fp_by_id["mappluto_bbl"]).fillna("")
    houses["height_roof_ft"] = houses["doitt"].map(fp_by_id["height_roof_ft"])
    # A-2: the PLUTO lot, by mappluto_bbl (the footprint layer's key to MapPLUTO), else base_bbl
    lots = set(pluto.index)
    houses["lot"] = [
        m if m in lots else (b if b in lots else "")
        for m, b in zip(houses["mappluto_bbl"], houses["base_bbl"], strict=True)
    ]
    footprints_on = Counter(
        key
        for m, b in zip(footprints["mappluto_bbl"], footprints["base_bbl"], strict=True)
        for key in [m if m in lots else (b if b in lots else "")]
        if key
    )
    largest: dict[str, str] = {}
    for doitt, m, b, area in zip(
        footprints["doitt_id"],
        footprints["mappluto_bbl"],
        footprints["base_bbl"],
        footprints["area_m2"],
        strict=True,
    ):
        key = m if m in lots else (b if b in lots else "")
        if key and (key not in largest or area > fp_by_id.at[largest[key], "area_m2"]):
            largest[key] = doitt

    matched = houses["lab_nsi_id"].map(_text) != ""
    occ_nsi = houses["lab_occupancy_hazus"].map(_text)
    base_nsi = [
        (suffix_parts(o) or (o, None, None))[0] if m else ""
        for o, m in zip(occ_nsi, matched, strict=True)
    ]
    houses["base_nsi"] = base_nsi
    storeys_nsi = pd.to_numeric(houses["NumberOfStoreys"], errors="coerce")

    # A-7: storey height [I], the median of the city's roof height over PLUTO NumFloors of the
    # study buildings that stand alone on their lot (both per building there)
    lot_floors = houses["lot"].map(pluto["numfloors"]).astype(float)
    lot_count = houses["lot"].map(pluto["numbldgs"]).astype(float)
    alone = (lot_count == 1) & houses["lot"].map(lambda k: footprints_on.get(k, 0) == 1)
    usable = alone & (houses["height_roof_ft"] > 0) & (lot_floors > 0)
    ratio = houses["height_roof_ft"] / lot_floors
    storey_ft = float(np.median(ratio[usable])) if usable.any() else None

    # A-6: neighbours among NSI buildings
    xy = np.column_stack(
        [houses["lab_x_m"].astype(float).to_numpy(), houses["lab_y_m"].astype(float).to_numpy()]
    )
    nsi_rows = np.flatnonzero(matched.to_numpy())
    tree = shapely.STRtree(shapely.points(xy[nsi_rows]))
    study_mode = mode([base_nsi[i] for i in nsi_rows])
    study_storeys = mode([int(storeys_nsi.iat[i]) for i in nsi_rows if storeys_nsi.iat[i] > 0])

    def neighbours(i: int) -> list[int]:
        hits = tree.query(shapely.points(xy[i]), predicate="dwithin", distance=NEIGHBOUR_M)
        return [int(nsi_rows[h]) for h in np.atleast_1d(hits)]

    rows = []
    for i, (_, h) in enumerate(houses.iterrows()):
        loc = h["LocNumber"]
        ff = floors.loc[loc]
        kinds: list[str] = []
        area = _num(h.get("detail_footprint_area_m2"))
        code = _text(h.get("detail_feature_code"))
        minor = code == GARAGE_CODE or (area is not None and area < MINOR_M2)
        lot = h["lot"]
        plot = pluto.loc[lot] if lot else None
        lot_buildings = _num(plot["numbldgs"]) if plot is not None else None
        single = plot is not None and lot_buildings == 1 and footprints_on.get(lot, 0) <= 1
        cause = causes.get(h["doitt"], "") if not matched.iat[i] else ""
        basement, basement_source, basement_sub = ff["basement"], ff["basement_source"], False
        storeys_source, storeys_sub = "", False
        notes = []
        if matched.iat[i]:
            parts = suffix_parts(occ_nsi.iat[i])
            storeys = round_storeys(storeys_nsi.iat[i])
            storeys_source = "NSI num_story" if storeys is not None else ""
            if parts is None:
                route, occupancy, occ_source, occ_sub = "nsi", occ_nsi.iat[i], "NSI occtype", False
            else:  # A-1
                route, occupancy, occ_sub = "nsi suffix", parts[0], True
                occ_source = f"NSI occtype {occ_nsi.iat[i]} without its suffix (A-1)"
                kinds.append("suffix base class")
                if storeys is not None and parts[1] != storeys:
                    notes.append(f"suffix storeys {parts[1]} vs num_story {storeys}")
                if basement and parts[2] != basement:
                    notes.append(f"suffix basement {parts[2]} vs flag {basement}")
        else:
            occupancy, occ_source, occ_sub = "", "", True
            if plot is not None:
                cls = _text(plot["bldgclass"])
                if cls not in PLUTO_CLASS:
                    raise KeyError(f"{loc}: PLUTO building class {cls!r} is not in PLUTO_CLASS")
                occupancy, reason = pluto_occupancy(cls, _num(plot["unitsres"]))
                occ_source = f"PLUTO {cls} ({reason}) (A-2)"
            if occupancy:
                route = "pluto"
                kinds.append("PLUTO class")
            else:  # A-6
                route = "neighbour"
                near = neighbours(i)
                found = mode([base_nsi[j] for j in near])
                why = occ_source or "no PLUTO lot"
                if found:
                    occupancy = found
                    occ_source = f"most common NSI class within {NEIGHBOUR_M:g} m ({why}) (A-6)"
                    kinds.append("neighbour mode class")
                else:
                    occupancy = study_mode
                    occ_source = f"most common NSI class of the study area ({why}) (A-6)"
                    kinds.append("study-area mode class")
            # A-4 / A-7: storeys
            floors_lot = round_storeys(_num(plot["numfloors"])) if plot is not None else None
            roof = _num(h["height_roof_ft"])
            if floors_lot is not None and single:
                storeys, storeys_source = floors_lot, "PLUTO NumFloors, single-building lot (A-4)"
            elif floors_lot is not None and largest.get(lot) == h["doitt"]:
                storeys, storeys_sub = floors_lot, True
                storeys_source = "PLUTO NumFloors of the lot's tallest building (A-4)"
                kinds.append("PLUTO lot floors (tallest building)")
            elif roof is not None and roof > 0 and storey_ft:
                storeys, storeys_sub = max(1, round_storeys(roof / storey_ft) or 1), True
                storeys_source = f"roof height {roof:g} ft / {storey_ft:.2f} ft per storey (A-7)"
                kinds.append("storeys from roof height")
            else:
                near = neighbours(i)
                storeys = mode([int(storeys_nsi.iat[j]) for j in near if storeys_nsi.iat[j] > 0])
                storeys = storeys if storeys is not None else study_storeys
                storeys_sub = True
                storeys_source = f"most common NSI storeys within {NEIGHBOUR_M:g} m (A-7)"
                kinds.append("neighbour mode storeys")
            # A-5: basement
            pb = (
                pluto_basement(_text(plot["bsmtcode"]), _text(plot["bldgclass"]), single)
                if plot is not None
                else ""
            )
            if pb:
                if basement and pb != basement:
                    notes.append(f"BsmtCode {pb} vs city flag {basement}")
                basement, basement_source = pb, f"PLUTO BsmtCode {_text(plot['bsmtcode'])} (A-5)"
        # first floor (FF rules, unchanged)
        ffh_source = ff["ffh_source"]
        ffh_sub = ffh_source == floors_values.NSI_HEIGHT
        if ffh_sub:
            kinds.append("NSI default first-floor height")
        # values
        hz = hazus_value(occupancy, storeys, basement, area)
        if matched.iat[i] and h["doitt"] in nsi_sqft:  # check only: at NSI's own floor area
            per_ft2 = hazus_cost(occupancy, storeys, basement)["mid"]
            hz = {
                "low": None,
                "mid": to_2026(per_ft2 * nsi_sqft[h["doitt"]], HAZUS_QUARTER) if per_ft2 else None,
                "high": None,
            }
        if matched.iat[i]:
            nsi_value = _num(h.get("lab_value_mid_usd"))
            values = {"low": None, "mid": to_2026(nsi_value, NSI_QUARTER), "high": None}
            value_source = (
                "NSI val_struct (asset table), August 2025 prices, V-2 4Q25 to 4Q26"
                if nsi_value is not None
                else ""
            )
            value_tag, quarter, value_sub = (
                ("S" if nsi_value is not None else ""),
                NSI_QUARTER,
                False,
            )
        else:  # A-8
            values = hz
            given = values["mid"] is not None
            value_source = (
                f"Hazus 7 Inventory TM Table {'6-3' if occupancy == 'RES1' else '6-2'} "
                f"{occupancy} cost/ft² (2022) x footprint {area:.1f} m² x {storeys} storeys, "
                "V-6 4Q22 to 4Q26; no location factor, not depreciated (A-8)"
                if given
                else ""
            )
            value_tag, quarter, value_sub = ("I" if given else ""), HAZUS_QUARTER, given
            if given:
                kinds.append("Hazus cost per ft²")
        if any(v == 0 for v in values.values() if v is not None):
            raise ValueError(f"{loc}: a value of zero; an unknown value is empty")
        # curve: FAST's rule (C-2) on the occupancy, storeys and basement of this row
        ddf = hazus.assign_structure_curve(
            lut, occupancy, storeys, {"Y": True, "N": False}.get(basement)
        )
        curve_inputs_sub = occ_sub or storeys_sub or basement_sub
        rows.append(
            {
                "LocNumber": loc,
                "asset_type": "building",
                "route": route,
                "gap_cause": cause,
                "lot_bbl": lot,
                "lot_base_bbl": h["base_bbl"],
                "lot_buildings": lot_buildings,
                "lot_footprints": footprints_on.get(lot) if lot else None,
                "lot_shared_with_nsi": cause == "A",
                "minor_structure": minor,
                "feature_code": code,
                "footprint_area_m2": area,
                "occupancy": occupancy,
                "occupancy_source": occ_source,
                "occupancy_substitute": occ_sub,
                "storeys": storeys,
                "storeys_source": storeys_source,
                "storeys_substitute": storeys_sub,
                "basement": basement,
                "basement_source": basement_source,
                "basement_substitute": basement_sub,
                "ffh_m": ff["ffh_m"],
                "ffh_source": ffh_source,
                "ffh_substitute": ffh_sub,
                "value_low_usd_2026": values["low"],
                "value_mid_usd_2026": values["mid"],
                "value_high_usd_2026": values["high"],
                "value_tag": value_tag,
                "value_source": value_source,
                "value_source_quarter": quarter if value_tag else "",
                "value_substitute": value_sub,
                "hazus_check_mid_usd_2026": hz["mid"],
                "curve_id": f"hazus_struct_{ddf}" if ddf is not None else "",
                "curve_source": "FAST default assignment, riverine (C-2)" if ddf else "",
                "curve_substitute": bool(ddf is not None and curve_inputs_sub),
                "asset_substitute_class": ";".join(k for k in SUBSTITUTE_KINDS if k in kinds),
                "notes": "; ".join(notes),
            }
        )
    rows += substation_rows(assets)
    frame = pd.DataFrame(rows, columns=COLUMNS)
    for column in FLOAT_COLUMNS:
        frame[column] = frame[column].astype("Float64")
    for column in ("storeys", "lot_buildings", "lot_footprints"):
        frame[column] = pd.to_numeric(frame[column]).astype("Int64")
    summary = summarise(frame, houses, storey_ft, study_mode, study_storeys)
    # A-8 check [I]: PLUTO BldgArea over footprint area x storeys, buildings without an NSI point
    # alone on their lot with storeys from NumFloors
    b = frame[frame["asset_type"] == "building"]
    alone = b[
        b["route"].isin(["pluto", "neighbour"])
        & (b["lot_buildings"] == 1)
        & (b["lot_footprints"] == 1)
        & b["storeys"].notna()
    ]
    area = alone["lot_bbl"].map(pluto["bldgarea"]).astype(float)
    ratio = (area / (alone["footprint_area_m2"].astype(float) * FT2_PER_M2 * alone["storeys"]))[
        area > 0
    ]
    summary["pluto_bldgarea_over_floor_area_single_lots"] = {
        "buildings": int(ratio.notna().sum()),
        **quantiles(ratio),
    }
    return frame, summary


def substation_rows(assets: pd.DataFrame) -> list[dict[str, Any]]:
    """Substations: values by V-1/V-5 (``asset_values``), curves by C-5 (``envelope_for``)."""
    values = floors_values.asset_values(assets).set_index("LocNumber")
    rows = []
    for _, s in assets[assets["lab_asset_type"] == "substation"].iterrows():
        loc = s["LocNumber"]
        kept = loc in values.index
        v = values.loc[loc] if kept else None
        chosen = envelope.envelope_for(
            _num(s.get("lab_voltage_kv")), _text(s.get("lab_substation_kind"))
        )
        level = {
            k: to_2026(_num(v[f"value_{k}_usd"]), SUBSTATION_QUARTER) if v is not None else None
            for k in ("low", "mid", "high")
        }
        tag = _text(v["value_tag"]) if v is not None else ""
        rows.append(
            {
                "LocNumber": loc,
                "asset_type": "substation",
                "route": "substation" if kept else "substation removed",
                "lot_shared_with_nsi": False,
                "minor_structure": False,
                "occupancy_substitute": False,
                "storeys_substitute": False,
                "basement_substitute": False,
                "ffh_substitute": False,
                "value_low_usd_2026": level["low"],
                "value_mid_usd_2026": level["mid"],
                "value_high_usd_2026": level["high"],
                "value_tag": tag if level["mid"] is not None else "",
                "value_source": (
                    f"{_text(v['value_source'])}; V-5 4Q24 to 4Q26 (V-2)"
                    if level["mid"] is not None
                    else ""
                ),
                "value_source_quarter": SUBSTATION_QUARTER if level["mid"] is not None else "",
                "value_substitute": False,
                "curve_id": "|".join(chosen[k] for k in ("low", "high", "williams_min", "bor"))
                if chosen
                else "",
                "curve_source": "C-5 role (OpenStreetMap substation tag)" if chosen else "",
                "curve_substitute": False,
                "asset_substitute_class": "",
                "notes": "" if kept else _text(s.get("lab_reviewed")),
            }
        )
    return rows


COLUMNS = (
    "LocNumber",
    "asset_type",
    "route",
    "gap_cause",
    "lot_bbl",
    "lot_base_bbl",
    "lot_buildings",
    "lot_footprints",
    "lot_shared_with_nsi",
    "minor_structure",
    "feature_code",
    "footprint_area_m2",
    "occupancy",
    "occupancy_source",
    "occupancy_substitute",
    "storeys",
    "storeys_source",
    "storeys_substitute",
    "basement",
    "basement_source",
    "basement_substitute",
    "ffh_m",
    "ffh_source",
    "ffh_substitute",
    "value_low_usd_2026",
    "value_mid_usd_2026",
    "value_high_usd_2026",
    "value_tag",
    "value_source",
    "value_source_quarter",
    "value_substitute",
    "hazus_check_mid_usd_2026",
    "curve_id",
    "curve_source",
    "curve_substitute",
    "asset_substitute_class",
    "notes",
)
FLOAT_COLUMNS = (
    "footprint_area_m2",
    "ffh_m",
    "value_low_usd_2026",
    "value_mid_usd_2026",
    "value_high_usd_2026",
    "hazus_check_mid_usd_2026",
)


def quantiles(values: pd.Series) -> dict[str, float | None]:
    """p10, p25, p50, p75, p90 of the known values, rounded to 3 decimals; None for no values."""
    known = pd.to_numeric(values, errors="coerce").astype(float).dropna()
    return {
        f"p{int(q * 100)}": round(float(known.quantile(q)), 3) if len(known) else None
        for q in (0.1, 0.25, 0.5, 0.75, 0.9)
    }


# --- A-11: the check on shared lots ------------------------------------------------------------


def lot_check(frame: pd.DataFrame) -> dict[str, Any]:
    """A-11 [I]: per lot holding a cause-A building, NSI value already there vs Hazus for all.

    For each such lot (``lot_base_bbl``): ``nsi`` = sum of 2026 NSI values of the lot's NSI
    buildings; ``hazus_all`` = sum of the Hazus substitute (``hazus_check_mid_usd_2026``) over
    every study building on the lot; ``added`` = the substitute values the main case adds.
    """
    b = frame[frame["asset_type"] == "building"]
    shared = set(b.loc[b["lot_shared_with_nsi"], "lot_base_bbl"])
    rows = []
    for lot, group in b[b["lot_base_bbl"].isin(shared)].groupby("lot_base_bbl"):
        nsi = group.loc[group["route"].isin(["nsi", "nsi suffix"]), "value_mid_usd_2026"].sum()
        hz = group["hazus_check_mid_usd_2026"]
        added = group.loc[group["lot_shared_with_nsi"], "value_mid_usd_2026"].sum()
        rows.append(
            {
                "lot": lot,
                "nsi": float(nsi),
                "hazus_all": float(hz.sum()) if hz.notna().all() else None,
                "added": float(added),
                "buildings_added": int(group["lot_shared_with_nsi"].sum()),
            }
        )
    if not rows:
        return {"lots": 0, "buildings_added": 0}
    table = pd.DataFrame(rows)
    known = table.dropna(subset=["hazus_all"])
    ratio = known["nsi"] / known["hazus_all"]
    exceed = known[known["nsi"] >= known["hazus_all"]]
    return {
        "lots": len(table),
        "buildings_added": int(table["buildings_added"].sum()),
        "lots_with_hazus_for_every_building": len(known),
        "ratio_nsi_to_hazus_all_quantiles": quantiles(ratio),
        "lots_where_nsi_alone_reaches_hazus_all": len(exceed),
        "buildings_added_on_those_lots": int(exceed["buildings_added"].sum()),
        "value_added_on_those_lots_usd_2026": round(float(exceed["added"].sum())),
        "value_added_all_shared_lots_usd_2026": round(float(table["added"].sum())),
        "nsi_value_on_shared_lots_usd_2026": round(float(table["nsi"].sum())),
        "excess_over_hazus_all_on_exceeding_lots_quantiles": quantiles(
            (exceed["nsi"] + exceed["added"]) / exceed["hazus_all"]
        ),
    }


def summarise(
    frame: pd.DataFrame,
    houses: pd.DataFrame,
    storey_ft: float | None,
    study_mode: str,
    study_storeys: int | None,
) -> dict[str, Any]:
    b = frame[frame["asset_type"] == "building"]
    suffix = b[b["route"] == "nsi suffix"]
    nsi_all = b[b["route"].isin(["nsi", "nsi suffix"])]
    nsi_all = nsi_all[nsi_all["hazus_check_mid_usd_2026"].notna()]
    ratio = nsi_all["value_mid_usd_2026"] / nsi_all["hazus_check_mid_usd_2026"]
    kinds = Counter(k for cell in b["asset_substitute_class"] for k in cell.split(";") if k)
    return {
        "buildings": len(b),
        "substations": int((frame["asset_type"] == "substation").sum()),
        "by_route": b["route"].value_counts().to_dict(),
        "by_gap_cause": b.loc[b["gap_cause"] != "", "gap_cause"].value_counts().to_dict(),
        "by_substitute_kind": {k: kinds.get(k, 0) for k in SUBSTITUTE_KINDS},
        "by_asset_substitute_class": b["asset_substitute_class"].value_counts().to_dict(),
        "suffix_occupancies": houses.loc[
            houses["lab_occupancy_hazus"].map(_text).map(suffix_parts).notna(),
            "lab_occupancy_hazus",
        ]
        .value_counts()
        .to_dict(),
        "suffix_storeys_disagree": int(suffix["notes"].str.contains("suffix storeys").sum()),
        "suffix_basement_disagree": int(suffix["notes"].str.contains("suffix basement").sum()),
        "suffix_storeys_above_3": int((suffix["storeys"] > 3).sum()),
        "pluto_basement_disagrees_with_city_flag": int(b["notes"].str.contains("BsmtCode").sum()),
        "buildings_with_curve": int((b["curve_id"] != "").sum()),
        "buildings_with_curve_by_route": b[b["curve_id"] != ""]["route"].value_counts().to_dict(),
        "buildings_without_curve_by_route": b[b["curve_id"] == ""]["route"]
        .value_counts()
        .to_dict(),
        "buildings_with_value": int(b["value_mid_usd_2026"].notna().sum()),
        "buildings_without_value_by_route": b[b["value_mid_usd_2026"].isna()]["route"]
        .value_counts()
        .to_dict(),
        "minor_structures_without_nsi": int(
            (b["minor_structure"] & ~b["route"].isin(["nsi", "nsi suffix"])).sum()
        ),
        "lot_shared_with_nsi": int(b["lot_shared_with_nsi"].sum()),
        "storey_height_ft": round(storey_ft, 3) if storey_ft else None,
        "study_area_mode_class": study_mode,
        "study_area_mode_storeys": study_storeys,
        "nsi_value_over_hazus_at_nsi_floor_area_quantiles": quantiles(ratio),
        "value_mid_total_usd_2026_by_route": {
            k: round(float(v)) for k, v in b.groupby("route")["value_mid_usd_2026"].sum().items()
        },
        "lot_check": lot_check(frame),
        "price_factors": {
            q: round(factor(q), 6) for q in (NSI_QUARTER, SUBSTATION_QUARTER, HAZUS_QUARTER)
        },
    }


# --- writing -----------------------------------------------------------------------------------


def write_csv(frame: pd.DataFrame, path: Path) -> None:
    """Atomic CSV; an unknown number is an empty cell (floors_values.write_csv)."""
    floors_values.write_csv(frame, path)


def write_json(document: dict[str, Any], path: Path) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            json.dump(document, stream, indent=1, sort_keys=True, default=str)
            stream.write("\n")
        os.replace(temporary, path)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--fetch", action="store_true", help="fetch the PLUTO lots first")
    args = parser.parse_args(argv)
    root = cache.root()
    assets = pd.read_csv(
        paths.SITE / "data" / "assets_oed.csv", dtype={"lab_nsi_id": str}, low_memory=False
    )
    detail = pd.read_csv(root / "assets" / "buildings_detail.csv", dtype=str)
    footprint_file = root / "nyc-building-footprints" / "footprints-box.geojson"
    nsi_file = root / "usace-national-structure-inventory" / "nsi_f1_box.json"
    footprints = read_footprint_lots(footprint_file)
    if args.fetch:
        nyc_pluto.fetch(root, set(footprints["base_bbl"]) | set(footprints["mappluto_bbl"]))
    pluto = nyc_pluto.read(root)
    floors = floors_values.first_floors(assets, nsi_file)
    lut = hazus.read_assignment(
        root / "hazus-flood-functions" / "fast" / "Building_DDF_Riverine_LUT_Hazus4p0.csv"
    )
    unmatched = detail.loc[
        detail["LocNumber"].isin(
            assets.loc[
                (assets["lab_asset_type"] == "building") & assets["lab_nsi_id"].isna(), "LocNumber"
            ]
        ),
        "detail_doitt_id",
    ].tolist()
    nsi = buildings.read_nsi(nsi_file)
    index = footprint_points(footprints, nsi, buildings.NEAR_M)
    causes = gap_causes(footprints, nsi, index, unmatched, buildings.NEAR_M)
    sqft = nsi_floor_area(footprints, nsi, index)
    frame, summary = build(assets, detail, footprints, pluto, floors, lut, causes, sqft)
    summary["pluto_version"] = sorted(set(pluto["version"]))
    summary["pluto_lots_read"] = len(pluto)
    write_csv(frame, OUT_CSV)
    write_json(summary, OUT_SUMMARY)
    print(json.dumps({k: summary[k] for k in ("by_route", "by_gap_cause")}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
