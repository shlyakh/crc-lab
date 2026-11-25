"""The asset table ``site/flood/data/assets_oed.csv`` in OED column names (requirement FD6).

Rows of ``substations.build`` and ``buildings.build`` become table rows with exactly
``schema.COLUMNS``: substations first, then buildings, each sorted by ``LocNumber``. Numbers are
written with fixed decimals (coordinates 7, metres 3, dollars 0), an unknown value as an empty cell.
The file is written atomically and only when ``schema.validate`` reports no fault; the same
rows give the same bytes.

OED codes, checked against the OED specification 5.0.0 (``OasisLMF/ODS_OpenExposureData``, tag
``5.0.0``, files ``OEDInputFields.csv``, ``OccupancyValues.csv``, ``PerilValues.csv``,
``OtherValues.csv``, ``CountryValues.csv``, ``CurrencyValues.csv``):

* ``CountryCode`` ``US`` (ISO 3166 alpha-2), ``LocCurrency`` ``USD`` (ISO 4217);
* ``LocPerilsCovered`` ``OSF``, "Flash / Surface / Pluvial Flood";
* ``FirstFloorHeightUnit`` ``2``, "Meters (Distance)" (the default, 1, is feet);
* ``OccupancyCode`` ``1300``, "Utilities, Electrical", for a substation; buildings are left empty,
  because no mapping from the inventory's Hazus classes to OED codes has been read;
* ``ConstructionCode`` empty: no source gives it (the OED default 5000, "Unknown", is a default and
  is not written).
"""

from __future__ import annotations

import csv
import io
import os
import tempfile
from pathlib import Path
from typing import Any

from flood_lab import paths
from flood_lab.assets import schema

TABLE = paths.SITE / "data" / "assets_oed.csv"
PORT_NUMBER = "1"
ACC_NUMBER = "1"
COUNTRY = "US"
CURRENCY = "USD"
PERILS = "OSF"
METRES = "2"
OCCUPANCY_SUBSTATION = "1300"
#: OED LocName is nvarchar(20)
NAME_LENGTH = 20

DECIMALS = {
    "Latitude": 7,
    "Longitude": 7,
    "BuildingTIV": 0,
    "FirstFloorHeight": 3,
    "lab_x_m": 3,
    "lab_y_m": 3,
    "lab_ground_elev_m": 3,
    "lab_terrain_elev_m": 3,
    "lab_first_floor_elev_m": 3,
    "lab_first_floor_height_m": 3,
    "lab_voltage_kv": 3,
    "lab_value_low_usd": 0,
    "lab_value_mid_usd": 0,
    "lab_value_high_usd": 0,
    "lab_customers_served": 0,
}
INTEGERS = ("NumberOfStoreys", "YearBuilt", "lab_outlines")


class TableFault(ValueError):
    """The table breaks a rule of ``schema.validate``; nothing was written."""


def short_name(name: str) -> str:
    """A name that fits OED's 20 characters: a trailing " Substation" is dropped, then cut."""
    if len(name) > NAME_LENGTH and name.endswith(" Substation"):
        name = name[: -len(" Substation")]
    return name[:NAME_LENGTH]


def cell(column: str, value: Any) -> str:
    if value is None or value == "" or (isinstance(value, float) and value != value):
        return ""  # unknown, NaN included
    if isinstance(value, bool):
        return "true" if value else "false"
    if column in DECIMALS:
        number = float(value)
        text = f"{number:.{DECIMALS[column]}f}"
        return text[1:] if text.startswith("-") and float(text) == 0 else text  # no "-0.000"
    if column in INTEGERS:
        return str(int(value))
    return str(value)


def table_row(asset: dict[str, Any]) -> dict[str, str]:
    """One table row with exactly the schema's columns, in order, as text."""
    full = {column: asset.get(column) for column in schema.COLUMNS}
    full["PortNumber"] = PORT_NUMBER
    full["AccNumber"] = ACC_NUMBER
    full["CountryCode"] = COUNTRY
    full["LocCurrency"] = CURRENCY
    full["LocPerilsCovered"] = PERILS
    if asset["lab_asset_type"] == "substation":
        full["LocName"] = short_name(asset.get("lab_name", ""))
        full["OccupancyCode"] = OCCUPANCY_SUBSTATION
        full["BuildingTIV"] = asset.get("lab_value_mid_usd")
    if full.get("FirstFloorHeight") not in (None, ""):
        full["FirstFloorHeightUnit"] = METRES
    return {column: cell(column, full[column]) for column in schema.COLUMNS}


def table(
    substations: list[dict[str, Any]], buildings: list[dict[str, Any]]
) -> list[dict[str, str]]:
    ordered = sorted(substations, key=lambda r: r["LocNumber"]) + sorted(
        buildings, key=lambda r: r["LocNumber"]
    )
    return [table_row(row) for row in ordered]


def text(rows: list[dict[str, str]]) -> str:
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=list(schema.COLUMNS), lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return buffer.getvalue()


def write(rows: list[dict[str, str]], path: Path = TABLE) -> Path:
    """Write the table atomically; refuse, and leave any old file, when it has a fault."""
    faults = schema.validate(rows)
    if faults:
        shown = "; ".join(faults[:10])
        more = f" (and {len(faults) - 10} more)" if len(faults) > 10 else ""
        raise TableFault(f"the asset table was not written: {shown}{more}")
    data = text(rows).encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_file() and path.read_bytes() == data:
        return path
    fd, temporary = tempfile.mkstemp(dir=path.parent, suffix=".part")
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
        os.chmod(temporary, 0o644)
        os.replace(temporary, path)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise
    return path
