"""FEMA National Flood Hazard Layer (NFHL): flood hazard zone polygons in a box.

Read from FEMA's public ArcGIS map service, layer "Flood Hazard Zones" (id 28 when probed
on 2026-11-17). The layer has no effective-date field, so the FIRM panels of the box
(layer "FIRM Panels", with ``EFF_DATE``) are fetched as well and their dates reported.

Geometry is asked for in WGS84 (``outSR=4326``; the service's own reference is NAD83,
EPSG:4269, and no datum transformation is requested), rounded to 6 decimals and generalised
by the server to ``simplify`` degrees (default 0.00001, about 1 m), because full-detail
polygons run to about 17 kB each.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.error import HTTPError

from data_source_check.evidence import _store
from data_source_check.evidence._store import Bounds

SERVICES = (
    "https://hazards.fema.gov/arcgis/rest/services/public/NFHL/MapServer",
    "https://hazards.fema.gov/gis/nfhl/rest/services/public/NFHL/MapServer",
)
ZONE_LAYER = "Flood Hazard Zones"
PANEL_LAYER = "FIRM Panels"
FIELDS = ("OBJECTID", "FLD_ZONE", "ZONE_SUBTY", "SFHA_TF", "STATIC_BFE", "V_DATUM", "DFIRM_ID")
PANEL_FIELDS = ("OBJECTID", "DFIRM_ID", "FIRM_PAN", "PANEL_TYP", "EFF_DATE")
MAX_SPLITS = 4  # a tile is cut in four at most this many times over


class ServiceError(RuntimeError):
    """The map service answered with an error, or a page it sent is not usable."""


# ---------------------------------------------------------------------------- the class rule
def zone_class(properties: dict[str, Any]) -> tuple[str, bool]:
    """Class and floodway flag of one zone, from its FLD_ZONE, ZONE_SUBTY and SFHA_TF.

    The rule, in order (zone and subtype compared trimmed and in capitals):

    1. zone starts with "V" (V, VE, V1-30): "1pct-coastal";
    2. SFHA_TF is "T" and zone starts with "A" (A, AE, AH, AO, AR, A99, A1-30): "1pct-riverine";
    3. zone is "X" and subtype contains "0.2 PCT": "0.2pct";
    4. anything else (X minimal, X levee, X "1 PCT DEPTH LESS THAN 1 FOOT", D, OPEN WATER,
       an A zone with SFHA_TF not "T"): "other".

    The floodway flag is set when the subtype contains "FLOODWAY", whatever the class.
    "riverine" is a name for the A zones only: FEMA's A zones near a coast can be mapped from
    storm surge too, and the layer does not say which.
    """
    zone = str(properties.get("FLD_ZONE") or "").strip().upper()
    subtype = str(properties.get("ZONE_SUBTY") or "").strip().upper()
    sfha = str(properties.get("SFHA_TF") or "").strip().upper() == "T"
    floodway = "FLOODWAY" in subtype
    if zone.startswith("V"):
        return "1pct-coastal", floodway
    if sfha and zone.startswith("A"):
        return "1pct-riverine", floodway
    if zone == "X" and "0.2 PCT" in subtype:
        return "0.2pct", floodway
    return "other", floodway


def zones(pages: Iterable[dict[str, Any] | str | bytes]) -> list[dict[str, Any]]:
    """Each polygon of the stored GeoJSON pages with its shapely geometry and class.

    A polygon met in more than one page (tiles overlap at their edges) is kept once, by
    OBJECTID. Rows: objectid, geometry, zone, subtype, sfha, static_bfe (None for -9999),
    v_datum, dfirm_id, class, floodway, valid. See ``zone_class`` for the rule.

    ``valid`` is shapely's ``is_valid``: the server's generalisation (``simplify``) leaves
    some polygons self-intersecting; they are returned as sent, not repaired.
    """
    from shapely.geometry import shape

    out: list[dict[str, Any]] = []
    seen: set[int] = set()
    for page in pages:
        collection = json.loads(page) if isinstance(page, str | bytes) else page
        for feature in collection.get("features", []):
            p = feature.get("properties") or {}
            objectid = int(p.get("OBJECTID", feature.get("id", -1)))
            if objectid in seen:
                continue
            seen.add(objectid)
            klass, floodway = zone_class(p)
            bfe = p.get("STATIC_BFE")
            geometry = shape(feature["geometry"]) if feature.get("geometry") else None
            out.append({
                "objectid": objectid, "geometry": geometry,
                "valid": geometry is not None and geometry.is_valid,
                "zone": p.get("FLD_ZONE"), "subtype": p.get("ZONE_SUBTY"),
                "sfha": str(p.get("SFHA_TF") or "").upper() == "T",
                "static_bfe": None if bfe is None or bfe <= -9999 else float(bfe),
                "v_datum": p.get("V_DATUM") or "", "dfirm_id": p.get("DFIRM_ID"),
                "class": klass, "floodway": floodway,
            })  # fmt: skip
    return out


def panel_dates(pages: Iterable[dict[str, Any] | str | bytes]) -> dict[str, list[str]]:
    """Effective dates (YYYY-MM-DD, UTC) of the FIRM panels, per DFIRM_ID, sorted."""
    dates: dict[str, set[str]] = {}
    for page in pages:
        reply = json.loads(page) if isinstance(page, str | bytes) else page
        for feature in reply.get("features", []):
            a = feature.get("attributes") or {}
            if a.get("EFF_DATE") is None:
                continue
            day = datetime.fromtimestamp(a["EFF_DATE"] / 1000, UTC).date().isoformat()
            dates.setdefault(str(a.get("DFIRM_ID")), set()).add(day)
    return {k: sorted(v) for k, v in sorted(dates.items())}


def read_pages(record: dict[str, Any], kind: str = "zones") -> list[dict[str, Any]]:
    """The stored pages a ``fetch`` record lists (``kind`` "zones" or "panels"), parsed."""
    folder = Path(record["folder"])
    return [json.loads((folder / p["file"]).read_text(encoding="utf-8")) for p in record[kind]]


# ---------------------------------------------------------------------------- fetching
def _reply(body: bytes) -> dict[str, Any]:
    try:
        reply = json.loads(body)
    except ValueError as error:
        raise ServiceError(f"not JSON: {body[:200]!r}") from error
    if isinstance(reply, dict) and "error" in reply:
        raise ServiceError(json.dumps(reply["error"])[:500])
    return reply


def _check(body: bytes) -> None:
    _reply(body)


def _service(folder: Path, live: bool) -> tuple[str, dict[str, Any], dict[str, Any]]:
    """The first service address that answers, its description and its record."""
    failures = []
    for index, base in enumerate(SERVICES):
        path = folder / f"service-{index}.json"
        try:
            record = _store.store(_store.url_of(base, {"f": "json"}), path, live=live,
                                  check=_check)  # fmt: skip
        except FileNotFoundError:
            if live:
                raise
            continue
        except (HTTPError, OSError, ServiceError) as error:
            failures.append(f"{base}: {error}")
            continue
        return base, json.loads(path.read_text(encoding="utf-8")), record
    if not live:
        raise FileNotFoundError(f"no stored NFHL service description in {folder}; run with --live")
    raise ServiceError("no NFHL service answered: " + "; ".join(failures))


def _layer_id(service: dict[str, Any], name: str) -> int:
    for layer in service.get("layers", []):
        if layer.get("name") == name:
            return int(layer["id"])
    raise ServiceError(f"the service has no layer named {name!r}")


def _quarters(tile: Bounds) -> list[Bounds]:
    w, s, e, n = tile
    x, y = (w + e) / 2, (s + n) / 2
    return [(w, s, x, y), (x, s, e, y), (w, y, x, n), (x, y, e, n)]


def _query(tile: Bounds, fields: Iterable[str], **extra: Any) -> dict[str, Any]:
    return {
        "where": "1=1",
        "geometry": ",".join(f"{v:.6f}" for v in tile),
        "geometryType": "esriGeometryEnvelope",
        "inSR": 4326,
        "spatialRel": "esriSpatialRelIntersects",
        "outFields": ",".join(fields),
        **extra,
    }


def _pages(
    base: str,
    layer: int,
    tile: Bounds,
    folder: Path,
    prefix: str,
    live: bool,
    params: dict[str, Any],
    page_size: int,
    fields: Iterable[str],
) -> Iterator[dict[str, Any]]:
    """Stored pages of one tile, in order; raises ServiceError when the tile is truncated."""
    key = _store.box_key(tile)
    count_url = _store.url_of(f"{base}/{layer}/query",
                              _query(tile, fields, returnCountOnly="true", f="json"))  # fmt: skip
    count_path = folder / f"{prefix}-{key}-count.json"
    _store.store(count_url, count_path, live=live, check=_check, attempts=2)
    expected = int(json.loads(count_path.read_text(encoding="utf-8"))["count"])
    offset, got = 0, 0
    while True:
        query = _query(tile, fields, orderByFields="OBJECTID", resultOffset=offset,
                       resultRecordCount=page_size, **params)  # fmt: skip
        url = _store.url_of(f"{base}/{layer}/query", query)
        path = folder / f"{prefix}-{key}-{offset:06d}.{params['f']}"
        record = _store.store(url, path, live=live, check=_check, attempts=2, timeout=180)
        reply = json.loads(path.read_text(encoding="utf-8"))
        features = reply.get("features", [])
        more = bool(reply.get("exceededTransferLimit")
                    or (reply.get("properties") or {}).get("exceededTransferLimit"))  # fmt: skip
        got += len(features)
        yield {**record, "file": path.name, "tile": list(tile), "offset": offset,
               "features": len(features)}  # fmt: skip
        if not more or not features:
            break
        offset += len(features)
    if got != expected:
        raise ServiceError(f"tile {key}: {got} features returned, {expected} counted")


def _collect(
    base: str,
    layer: int,
    bounds: Bounds,
    folder: Path,
    prefix: str,
    live: bool,
    params: dict[str, Any],
    page_size: int,
    fields: Iterable[str],
    failures: list[str],
) -> list[dict[str, Any]]:
    """Pages of the box; a tile that fails or is truncated is cut in four and asked again."""
    queue: list[tuple[Bounds, int]] = [(bounds, 0)]
    done: list[dict[str, Any]] = []
    while queue:
        tile, depth = queue.pop(0)
        try:
            done.extend(_pages(base, layer, tile, folder, prefix, live, params, page_size,
                               fields))  # fmt: skip
        except (HTTPError, OSError, ServiceError) as error:
            if isinstance(error, FileNotFoundError) or depth >= MAX_SPLITS:
                raise
            failures.append(f"{prefix} {_store.box_key(tile)}: {error}; split in four")
            queue.extend((quarter, depth + 1) for quarter in _quarters(tile))
            done = [p for p in done if p["tile"] != list(tile)]
    return done


def fetch(bounds: Bounds, folder: Path, *, live: bool, simplify: float = 0.00001) -> dict[str, Any]:
    """Flood hazard zones and FIRM panels of a box, fetched (``live``) or read from ``folder``.

    Pages are kept under ``folder/fema-nfhl/<box>/`` with a sidecar each (url, sha256, bytes,
    retrieved_at) and a ``manifest.json`` written last; a box already fetched is not fetched
    again. Returns the manifest: service address and currentVersion, layer names and ids,
    page records, feature counts, the panels' effective dates per DFIRM_ID, and failures met
    on the way (tiles that were split).
    """
    here = folder / "fema-nfhl" / _store.box_key(bounds)
    done = _store.manifest(here / "manifest.json", live=live)
    if done is not None:
        return {**done, "folder": str(here)}
    base, service, service_record = _service(here, live)
    zone_layer, panel_layer = _layer_id(service, ZONE_LAYER), _layer_id(service, PANEL_LAYER)
    layer_path = here / f"layer-{zone_layer}.json"
    layer_record = _store.store(_store.url_of(f"{base}/{zone_layer}", {"f": "json"}),
                                layer_path, live=live, check=_check)  # fmt: skip
    layer = json.loads(layer_path.read_text(encoding="utf-8"))
    page_size = int(layer.get("maxRecordCount") or 1000)
    failures: list[str] = []
    zone_params = {"outSR": 4326, "geometryPrecision": 6, "maxAllowableOffset": simplify,
                   "f": "geojson"}  # fmt: skip
    zone_pages = _collect(base, zone_layer, bounds, here, "zones", live, zone_params,
                          page_size, FIELDS, failures)  # fmt: skip
    panel_pages = _collect(base, panel_layer, bounds, here, "panels", live,
                           {"returnGeometry": "false", "f": "json"}, page_size,
                           PANEL_FIELDS, failures)  # fmt: skip
    record: dict[str, Any] = {
        "source": "FEMA National Flood Hazard Layer",
        "bounds": list(bounds),
        "service": base,
        "service_record": service_record,
        "current_version": service.get("currentVersion"),
        "max_record_count": page_size,
        "zone_layer": {
            "id": zone_layer,
            "name": layer.get("name"),
            "record": layer_record,
            "date_fields": [
                f["name"] for f in layer.get("fields", []) if f.get("type") == "esriFieldTypeDate"
            ],
            "editing_info": layer.get("editingInfo"),
        },  # fmt: skip
        "panel_layer": {"id": panel_layer, "name": PANEL_LAYER},
        "query": {"fields": list(FIELDS), **zone_params, "spatialRel": "intersects"},
        "zones": zone_pages,
        "panels": panel_pages,
        "features_returned": sum(p["features"] for p in zone_pages),
        "bytes": sum(p["bytes"] for p in zone_pages + panel_pages),
        "failures": failures,
    }
    zone_rows = zones(json.loads((here / p["file"]).read_text(encoding="utf-8"))
                      for p in zone_pages)  # fmt: skip
    record["features_unique"] = len(zone_rows)
    record["classes"] = {k: sum(1 for z in zone_rows if z["class"] == k)
                         for k in ("1pct-riverine", "1pct-coastal", "0.2pct", "other")}  # fmt: skip
    record["floodway"] = sum(1 for z in zone_rows if z["floodway"])
    panels = [json.loads((here / p["file"]).read_text(encoding="utf-8")) for p in panel_pages]
    record["panel_effective_dates"] = panel_dates(panels)
    record["retrieved_at"] = max(p["retrieved_at"] for p in zone_pages + panel_pages)
    _store.write_json(here / "manifest.json", record)
    return {**record, "folder": str(here)}


__all__ = ["fetch", "panel_dates", "read_pages", "zone_class", "zones", "ServiceError"]
