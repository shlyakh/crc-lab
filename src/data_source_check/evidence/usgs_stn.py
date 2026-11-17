"""USGS Short-Term Network (STN) high-water marks of one flood event (default: Harvey 2017).

The STN services moved: ``stn.wim.usgs.gov`` now redirects every path to
``apps.usgs.gov/stnweb``, which answered 403 on 2026-11-17. The Flood Event Viewer
(``apps.usgs.gov/fev``) reads ``api.waterdata.usgs.gov/stnservices``, which answered without a
key. Three replies are kept:

- ``events/``: every event, to find the event's id by its exact name;
- ``hwms/filteredhwms/?event=<id>&states=<state>``: the marks of one state with names of
  their type, quality, datum and site (no survey date);
- ``hwms/?event=<id>``: the raw marks of the event, all states, with ``survey_date``,
  ``stillwater`` and ``uncertainty``, joined to the first by mark id.

Elevations are in feet above the stated vertical datum (mostly NAVD88; a few NGVD29 or a
"local control point", which is not a geodetic datum); height above ground is in feet.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from data_source_check.evidence import _store

BASE = "https://api.waterdata.usgs.gov/stnservices"
EVENT = "2017 Harvey"


def event_id(text: str, name: str = EVENT) -> int:
    """The id of the event whose name is exactly ``name`` in an ``events/`` reply."""
    found = [e["id"] for e in json.loads(text) if e.get("name") == name]
    if len(found) != 1:
        raise LookupError(f"{len(found)} events are named {name!r}")
    return int(found[0])


def _number(value: Any) -> float | None:
    if value is None or value == "":
        return None
    return float(value)


def marks(text: str, details: str | None = None) -> list[dict[str, Any]]:
    """High-water marks of a ``filteredhwms`` reply, with survey details joined by id.

    Rows: id, latitude, longitude (decimal degrees; horizontal_datum), elevation_ft and
    vertical_datum, height_above_ground_ft (None where not given), quality (the publisher's
    label, with its stated tolerance), environment ("Riverine" or "Coastal"), type, flag_date,
    survey_date, stillwater and uncertainty_ft (from ``details``, the raw ``hwms/?event=``
    reply; None without it), site_number, site_description, location_description, county,
    waterbody, label.
    """
    extra = {int(r["id"]): r for r in json.loads(details)} if details else {}
    out = []
    for r in json.loads(text):
        more = extra.get(int(r["id"]), {})
        out.append({
            "id": int(r["id"]),
            "latitude": _number(r.get("latitude_dd", r.get("latitude"))),
            "longitude": _number(r.get("longitude_dd", r.get("longitude"))),
            "horizontal_datum": r.get("horizontal_datum_name", ""),
            "elevation_ft": _number(r.get("elev_ft")),
            "vertical_datum": r.get("vertical_datum_name", ""),
            "height_above_ground_ft": _number(r.get("height_above_ground")),
            "quality": r.get("hwm_quality_name", ""),
            "environment": r.get("environment", ""),
            "type": r.get("hwm_type_name", ""),
            "flag_date": r.get("flag_date"),
            "survey_date": more.get("survey_date"),
            "stillwater": more.get("stillwater"),
            "uncertainty_ft": _number(more.get("uncertainty")),
            "site_number": r.get("site_number", ""),
            "site_description": r.get("site_description", ""),
            "location_description": r.get("location_description", ""),
            "county": r.get("county_name", ""), "waterbody": r.get("waterbody", ""),
            "label": r.get("label", ""),
        })  # fmt: skip
    return out


def _json_list(body: bytes) -> None:
    if not isinstance(json.loads(body), list):
        raise ValueError(f"not a list: {body[:200]!r}")


def fetch(folder: Path, *, live: bool, event: str = EVENT, state: str = "TX") -> dict[str, Any]:
    """High-water marks of ``event`` in ``state``, fetched (``live``) or read from ``folder``.

    Replies are kept under ``folder/usgs-stn/<event>-<state>/`` with a sidecar each and a
    ``manifest.json`` written last. Returns the manifest: the event's id and dates, the three
    reply records, and counts.
    """
    here = folder / "usgs-stn" / f"{event.replace(' ', '-')}-{state}"
    done = _store.manifest(here / "manifest.json", live=live)
    if done is not None:
        return {**done, "folder": str(here)}
    events = _store.store(f"{BASE}/events/", here / "events.json", live=live, check=_json_list)
    events_text = (here / "events.json").read_text(encoding="utf-8")
    number = event_id(events_text, event)
    described = next(e for e in json.loads(events_text) if e["id"] == number)
    filtered_url = _store.url_of(f"{BASE}/hwms/filteredhwms/", {"event": number, "states": state})
    filtered = _store.store(filtered_url, here / "hwms-filtered.json", live=live,
                            check=_json_list, timeout=300)  # fmt: skip
    raw_url = _store.url_of(f"{BASE}/hwms/", {"event": number})
    raw = _store.store(raw_url, here / "hwms-event.json", live=live, check=_json_list,
                       timeout=300)  # fmt: skip
    rows = marks((here / "hwms-filtered.json").read_text(encoding="utf-8"),
                 (here / "hwms-event.json").read_text(encoding="utf-8"))  # fmt: skip
    record: dict[str, Any] = {
        "source": "USGS Short-Term Network (STN) services",
        "service": BASE,
        "event": {
            k: described.get(k)
            for k in ("id", "name", "start_date", "end_date", "description", "last_updated")
        },  # fmt: skip
        "state": state,
        "replies": {
            "events": {**events, "file": "events.json"},
            "filtered": {**filtered, "file": "hwms-filtered.json"},
            "event_marks": {**raw, "file": "hwms-event.json"},
        },  # fmt: skip
        "marks": len(rows),
        "marks_with_survey_details": sum(1 for r in rows if r["survey_date"] is not None),
        "bytes": events["bytes"] + filtered["bytes"] + raw["bytes"],
        "retrieved_at": max(
            events["retrieved_at"], filtered["retrieved_at"], raw["retrieved_at"]
        ),  # fmt: skip
    }
    _store.write_json(here / "manifest.json", record)
    return {**record, "folder": str(here)}


def read(record: dict[str, Any]) -> list[dict[str, Any]]:
    """The marks a ``fetch`` record lists, parsed and joined."""
    folder = Path(record["folder"])
    replies = record["replies"]
    return marks((folder / replies["filtered"]["file"]).read_text(encoding="utf-8"),
                 (folder / replies["event_marks"]["file"]).read_text(encoding="utf-8"))  # fmt: skip
