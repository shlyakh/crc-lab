"""USGS stream gauges in a box, their annual peak streamflow and gage height, and NWS flood stages.

Sources, as probed on 2026-11-17 (both legacy NWIS services still answered):

- gauges: ``waterservices.usgs.gov/nwis/site`` (RDB), site type ST, with peak data
  (``hasDataTypeCd=pk``), active and inactive;
- annual peaks: ``nwis.waterdata.usgs.gov/nwis/peak`` (RDB), one request per gauge;
- flood stages: NOAA NWPS ``api.water.noaa.gov/nwps/v1/gauges/{USGS site number}``, which
  answers 404 for a gauge NWS does not forecast or monitor.

Units are the publisher's: discharge in cubic feet per second, gage height in feet above the
gauge's own datum (``alt_va`` with ``alt_datum_cd`` gives that datum's altitude where known),
drainage area in square miles. Peaks may be provisional (see the RDB header).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from urllib.error import HTTPError

from data_source_check.evidence import _store
from data_source_check.evidence._store import Bounds

SITE_SERVICE = "https://waterservices.usgs.gov/nwis/site/"
PEAK_SERVICE = "https://nwis.waterdata.usgs.gov/nwis/peak"
NWPS_GAUGE = "https://api.water.noaa.gov/nwps/v1/gauges/{}"


# ---------------------------------------------------------------------------- parsers
def _rdb(text: str) -> list[dict[str, str]]:
    """Rows of a USGS tab-separated RDB text: comments skipped, the format line dropped."""
    lines = [line for line in text.splitlines() if line and not line.startswith("#")]
    if not lines:
        return []
    header = lines[0].split("\t")
    rows = []
    for line in lines[2:]:  # lines[1] gives the column widths and types ("5s", "15s")
        values = line.split("\t")
        values += [""] * (len(header) - len(values))
        rows.append({k: v.strip() for k, v in zip(header, values, strict=False)})
    return rows


def _number(text: str) -> float | None:
    text = text.strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def sites(text: str) -> list[dict[str, Any]]:
    """Gauges of a site-service RDB reply (``siteOutput=expanded``).

    Rows: site_no, name, lat, lon (decimal degrees) and their datum, drainage_area_sqmi,
    contrib_drainage_area_sqmi, gage_altitude_ft (altitude of the gauge datum or land
    surface, ``alt_va``), its accuracy (ft) and vertical datum, huc, site type.
    """
    out = []
    for row in _rdb(text):
        out.append({
            "site_no": row["site_no"], "name": row.get("station_nm", ""),
            "lat": _number(row.get("dec_lat_va", "")), "lon": _number(row.get("dec_long_va", "")),
            "coord_datum": row.get("dec_coord_datum_cd", ""),
            "drainage_area_sqmi": _number(row.get("drain_area_va", "")),
            "contrib_drainage_area_sqmi": _number(row.get("contrib_drain_area_va", "")),
            "gage_altitude_ft": _number(row.get("alt_va", "")),
            "gage_altitude_accuracy_ft": _number(row.get("alt_acy_va", "")),
            "gage_altitude_datum": row.get("alt_datum_cd", ""),
            "huc": row.get("huc_cd", ""), "site_type": row.get("site_tp_cd", ""),
        })  # fmt: skip
    return out


def water_year(date: str) -> int | None:
    """USGS water year (1 October to 30 September) of a YYYY-MM-DD date; None if the month is 00.

    The peak file writes an unknown month or day as 00.
    """
    try:
        year, month = int(date[0:4]), int(date[5:7])
    except ValueError:
        return None
    if month == 0:
        return None
    return year + 1 if month >= 10 else year


def peaks(text: str) -> list[dict[str, Any]]:
    """Annual peaks of a peak-service RDB reply (one or several gauges).

    Rows: site_no, water_year (from the date; None when its month is unknown), date and time
    as written, discharge_cfs, discharge_codes (``peak_cd`` verbatim), gage_height_ft,
    gage_height_codes (verbatim), year_last_peak, and the year's highest gage height when it
    was not at the peak (max_gage_height_date, max_gage_height_ft, max_gage_height_codes).
    """
    out = []
    for row in _rdb(text):
        date = row.get("peak_dt", "")
        out.append({
            "site_no": row["site_no"], "water_year": water_year(date), "date": date,
            "time": row.get("peak_tm", ""),
            "discharge_cfs": _number(row.get("peak_va", "")),
            "discharge_codes": row.get("peak_cd", ""),
            "gage_height_ft": _number(row.get("gage_ht", "")),
            "gage_height_codes": row.get("gage_ht_cd", ""),
            "year_last_peak": row.get("year_last_pk", ""),
            "max_gage_height_date": row.get("ag_dt", ""),
            "max_gage_height_ft": _number(row.get("ag_gage_ht", "")),
            "max_gage_height_codes": row.get("ag_gage_ht_cd", ""),
        })  # fmt: skip
    return out


def flood_stage(text: str) -> dict[str, Any]:
    """NWS flood categories of one NWPS gauge reply.

    Returns lid, usgs_id, name, stage_units, flow_units, the action, minor, moderate and
    major stage and flow (None where NWPS writes -9999), and the vertical datums NWPS lists.
    NWPS stages are on the gauge's reading scale, which for a USGS gauge is normally its
    gage height; this is not checked here.
    """
    reply = json.loads(text)
    flood = reply.get("flood") or {}
    categories = flood.get("categories") or {}

    def value(name: str, key: str) -> float | None:
        number = (categories.get(name) or {}).get(key)
        return None if number is None or number <= -9999 else float(number)

    datums = ((reply.get("datums") or {}).get("vertical") or {}).get("value") or []
    out: dict[str, Any] = {
        "lid": reply.get("lid"), "usgs_id": reply.get("usgsId"), "name": reply.get("name"),
        "stage_units": flood.get("stageUnits"), "flow_units": flood.get("flowUnits"),
        "vertical_datums": [d.get("abbrev") for d in datums],
    }  # fmt: skip
    for name in ("action", "minor", "moderate", "major"):
        out[f"{name}_stage"] = value(name, "stage")
        out[f"{name}_flow"] = value(name, "flow")
    return out


# ---------------------------------------------------------------------------- fetching
def _not_html(body: bytes) -> None:
    if body.lstrip()[:1] == b"<":
        raise ValueError(f"an HTML page, not RDB: {body[:200]!r}")


def site_url(bounds: Bounds) -> str:
    west, south, east, north = bounds
    return _store.url_of(SITE_SERVICE, {
        "format": "rdb", "bBox": f"{west:.6f},{south:.6f},{east:.6f},{north:.6f}",
        "siteType": "ST", "hasDataTypeCd": "pk", "siteOutput": "expanded", "siteStatus": "all",
    })  # fmt: skip


def peak_url(site_no: str) -> str:
    return _store.url_of(PEAK_SERVICE, {"site_no": site_no, "agency_cd": "USGS", "format": "rdb"})


def fetch(bounds: Bounds, folder: Path, *, live: bool, stages: bool = True) -> dict[str, Any]:
    """Gauges of a box with their annual peaks (and NWS flood stages), fetched or read back.

    Responses are kept under ``folder/usgs-peaks/<box>/`` with a sidecar each and a
    ``manifest.json`` written last. Returns the manifest: the site-list record, one record
    per gauge's peaks, one per NWPS reply (or the HTTP status when NWPS has no such gauge),
    counts and failures, verbatim.
    """
    here = folder / "usgs-peaks" / _store.box_key(bounds)
    done = _store.manifest(here / "manifest.json", live=live)
    if done is not None:
        return {**done, "folder": str(here)}
    site_path = here / "sites.rdb"
    site_record = _store.store(site_url(bounds), site_path, live=live, check=_not_html)
    gauges = sites(site_path.read_text(encoding="utf-8"))
    peak_records: dict[str, Any] = {}
    stage_records: dict[str, Any] = {}
    failures: list[str] = []
    count = 0
    for gauge in gauges:
        number = gauge["site_no"]
        path = here / "peaks" / f"{number}.rdb"
        try:
            kept = _store.store(peak_url(number), path, live=live, check=_not_html)
            peak_records[number] = {**kept, "file": f"peaks/{path.name}"}
            count += len(peaks(path.read_text(encoding="utf-8")))
        except (HTTPError, OSError, ValueError) as error:
            if isinstance(error, FileNotFoundError):
                raise
            failures.append(f"peaks {number}: {error}")
        if not stages:
            continue
        path = here / "nwps" / f"{number}.json"
        try:
            stage_records[number] = {**_store.store(NWPS_GAUGE.format(number), path, live=live),
                                     "file": f"nwps/{path.name}"}  # fmt: skip
        except HTTPError as error:
            stage_records[number] = {"url": NWPS_GAUGE.format(number), "status": error.code}
        except OSError as error:
            if isinstance(error, FileNotFoundError):
                raise
            failures.append(f"nwps {number}: {error}")
    record: dict[str, Any] = {
        "source": "USGS NWIS site and peak services; NOAA NWPS gauges",
        "bounds": list(bounds),
        "sites": {**site_record, "file": site_path.name, "count": len(gauges)},
        "peaks": peak_records,
        "peak_rows": count,
        "stages": stage_records,
        "stages_found": sum(1 for r in stage_records.values() if "file" in r),
        "bytes": site_record["bytes"]
        + sum(
            r.get("bytes", 0) for r in [*peak_records.values(), *stage_records.values()]
        ),  # fmt: skip
        "failures": failures,
        "retrieved_at": max(
            [site_record["retrieved_at"]] + [r["retrieved_at"] for r in peak_records.values()]
        ),  # fmt: skip
    }
    _store.write_json(here / "manifest.json", record)
    return {**record, "folder": str(here)}


def read(record: dict[str, Any]) -> dict[str, Any]:
    """The gauges, peaks and flood stages a ``fetch`` record lists, parsed."""
    folder = Path(record["folder"])
    text = (folder / record["sites"]["file"]).read_text(encoding="utf-8")
    return {
        "sites": sites(text),
        "peaks": [row for r in record["peaks"].values()
                  for row in peaks((folder / r["file"]).read_text(encoding="utf-8"))],
        "stages": [flood_stage((folder / r["file"]).read_text(encoding="utf-8"))
                   for r in record["stages"].values() if "file" in r],
    }  # fmt: skip
