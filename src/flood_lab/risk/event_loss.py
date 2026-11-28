"""F6 step 4: the event-loss table of the study (FR4), held by ``crc_event_loss``.

One event per catalogue run. Each run is one synthetic year's storm (RainyDay keeps the largest
storm of each of M = 1,000 synthetic years, ``hazard/catalogue.py``), so the event id and the
year id are the run's label, and the years carry the catalogue's own block weights (weight / M),
exactly the weights the F4 frequency used. The 150 runs are those of ``f4/selection.json``, read
from the per-run arrays of the F4 check run on the catalogue with rain on the whole square
(CH-26: ``f4/frequency_cover/per_run/<label>.npz``); the 12 design storms ``ds_*`` in the same
folder are not part of the catalogue and are not read.

Depths (``hazard/at_assets.py``, written by ``checks/f4_catalogue.extract``):

* ``walls``: water depth at each building's walls, metres above ground (the deepest readable
  1 m pixel in a 2 m band around the footprint), one value per footprint of
  ``f3_model.study_footprints`` in that order; NaN where the band has no readable pixel. The
  order is checked against the key stored in each file. A footprint is joined to its asset by
  ``detail_doitt_id`` of F1's ``buildings_detail.csv``.
* ``site_lead``: the depth exceeded on 25 m2 of the substation site's open ground (the lead-asset
  measure), metres, one per kept site in ``site_ids`` order.

Damage ratios come from CRC (``Impact.evaluate`` inside ``EventLossTable.from_intensities``):

* buildings: the Hazus curve of ``curves.yaml`` named by the asset's ``curve_id``, read at
  ``building_depth.curve_depth`` (rules BD-1 to BD-5 of ``docs/flood/loss-rules.md``); the cases
  ``NO_LOSS`` are absent pairs (no loss, counted by the extension), the cases ``FAILED`` are kept in
  this module's failure ledger and the building is left out of every sum, named;
* substations: one table per curve family of C-3 (low, high, williams_min, bor), the curve of each
  family chosen for the site by C-5 (``envelope.envelope_for``, basis "role"; "hazus_kv" for the
  sensitivity), read at the lead depth.

**The dry threshold.** A depth below ``dry_below_m`` counts as 0 before BD-1 applies. The main
case uses the catalogue's wet rule, ``catalogue.WET_M`` = 0.05 m [P], the same rule the depth
frequency of FH7 (and so CRC's curves at the assets) applies. With 0 (BD-1 read literally) about
10,900 buildings are "wet" in every run by depths of 1e-6 to 4e-5 m (float32 differences of level
and ground), and a building with a basement then reads its basement curve at -4 ft every year;
this is reported as a sensitivity, not the main case.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pyarrow as pa

from crc_event_loss import (
    AnnualLosses,
    AnnualMeasure,
    EventLossTable,
    EventSet,
    Exposure,
    FailurePolicy,
    YearWeights,
    annual_losses,
)
from flood_lab import cache, paths
from flood_lab.curves import envelope
from flood_lab.risk import building_depth, crc_adapter

SELECTION = "f4/selection.json"
PER_RUN = "f4/frequency_cover/per_run"
BUILDINGS_DETAIL = "assets/buildings_detail.csv"
EXPOSURES = paths.SITE / "data" / "exposures.csv"
ASSETS = paths.SITE / "data" / "assets_oed.csv"
NSI = "usace-national-structure-inventory/nsi_f1_box.json"
CURRENCY = "USD"
VALUATION = "2026 USD (USACE CWCCIS 4Q26, V-2); value as exposures.csv states it"
#: the four substation curve families of C-3, in the order of ``exposures.csv`` ``curve_id``
FAMILIES = ("low", "high", "williams_min", "bor")
FAMILY_NAMES = {
    "low": "Nirandjan F2 (Hazus-type)",
    "high": "Williams max (role tier)",
    "williams_min": "Williams min (role tier)",
    "bor": "Bor 2026 (HV > 345 kV, anchored)",
}
VALUE_LEVELS = ("low", "mid", "high")

# failure reasons (never counted as zero; the building is left out of every sum)
NOT_IN_HAZARD = "no footprint of the hazard's set (F3/F4 select footprints by another rule)"
NOT_READ = "wall band has no readable pixel in the runs (F4 'buildings_not_read')"
NO_CURVE = "no structure curve (A-12) and wet"
BD_FAILED = "BD rule failed (BD-3 unknown basement, BD-4 above 24 ft or BD-5 no height) when wet"


@dataclass(frozen=True)
class Catalogue:
    """The runs, their weights (summing to M) and the event set built on them."""

    labels: tuple[str, ...]
    weights: np.ndarray  # years each run stands for; sums to m
    m: int
    strata: tuple[str, ...]
    ranks: tuple[int, ...]
    events: EventSet
    not_read: tuple[str, ...]  # files in the per-run folder that are not catalogue runs


def read_catalogue(root: Path) -> Catalogue:
    selection = json.loads((root / SELECTION).read_text())
    ms = {int(x["synthetic_years"]) for x in selection}
    if len(ms) != 1:
        raise ValueError(f"selection names several M: {sorted(ms)}")
    m = ms.pop()
    selection = sorted(selection, key=lambda x: x["rank"])
    labels = tuple(x["label"] for x in selection)
    weights = np.array([float(x["weight"]) for x in selection])
    if abs(weights.sum() - m) > 1e-9:
        raise ValueError(f"run weights sum to {weights.sum()}, not M = {m}")
    folder = root / PER_RUN
    missing = [x for x in labels if not (folder / f"{x}.npz").exists()]
    if missing:
        raise FileNotFoundError(f"{len(missing)} catalogue runs have no per-run file: {missing}")
    present = sorted(p.stem for p in folder.glob("*.npz"))
    others = tuple(x for x in present if x not in set(labels))
    years = YearWeights(labels, tuple(w / m for w in weights))
    events = EventSet.synthetic_years(
        {x: x for x in labels},
        years=years,
        description=(
            f"F4 storm catalogue with rain on the whole square (CH-26): {len(labels)} solver runs "
            f"of M = {m} RainyDay synthetic years, one storm a year, sampled by rainfall rank in "
            "strata T1/T2/T3; each run stands for its block of years (weight / M)"
        ),
        provenance={
            "selection": SELECTION,
            "per_run": PER_RUN,
            "M": str(m),
            "runs": str(len(labels)),
        },
    )
    return Catalogue(
        labels,
        weights,
        m,
        tuple(x["stratum"] for x in selection),
        tuple(int(x["rank"]) for x in selection),
        events,
        others,
    )


@dataclass
class Depths:
    """Depths per run (rows in ``Catalogue.labels`` order)."""

    walls: np.ndarray  # runs x footprints, metres, NaN not read
    footprint_ids: list[str]  # doitt_id per footprint column
    lead: np.ndarray  # runs x sites, metres
    site_ids: list[str]
    keys: dict[str, str] = field(default_factory=dict)


def read_depths(root: Path, cat: Catalogue, footprint_ids: list[str] | None = None) -> Depths:
    """The per-run arrays of the F4 check. With ``footprint_ids`` (doitt_id of
    ``f3_model.study_footprints`` in order) the footprint key in each file is checked against
    them, as the F4 check computes it."""
    walls, lead, site_ids, keys = [], [], None, {}
    for label in cat.labels:
        with np.load(root / PER_RUN / f"{label}.npz", allow_pickle=False) as z:
            walls.append(z["walls"].astype("float64"))
            lead.append(z["site_lead"].astype("float64"))
            ids = [str(s) for s in z["site_ids"]]
            keys[label] = str(z["key"])
        if site_ids is None:
            site_ids = ids
        elif ids != site_ids:
            raise ValueError(f"{label}: substation sites differ from the first run's")
    if footprint_ids is not None:
        from flood_lab.checks.f4_catalogue import _sha_text

        want = _sha_text("\n".join(f"bldg-{i}" for i in footprint_ids))
        bad = [x for x, k in keys.items() if json.loads(k)["footprints"] != want]
        if bad:
            raise ValueError(f"{len(bad)} runs were extracted for another footprint order")
    w = np.stack(walls)
    if footprint_ids is not None and w.shape[1] != len(footprint_ids):
        raise ValueError(f"{w.shape[1]} wall depths for {len(footprint_ids)} footprints")
    return Depths(w, list(footprint_ids or []), np.stack(lead), site_ids or [], keys)


def study_footprints(root: Path):
    """The footprints the F3/F4 asset depths are read for, in their order (a GeoDataFrame in the
    project CRS, ``doitt_id`` as strings)."""
    import geopandas as gpd

    from flood_lab import domain
    from flood_lab.checks import f3_model

    study = gpd.read_file(f3_model.STUDY_AREA).to_crs(domain.CRS).geometry.union_all()
    fp = f3_model.study_footprints(root, study)
    fp["doitt_id"] = fp["doitt_id"].astype(str)
    return fp


def read_exposures(path: Path = EXPOSURES) -> pd.DataFrame:
    frame = pd.read_csv(path, low_memory=False, dtype={"basement": str, "curve_id": str})
    frame["basement"] = frame["basement"].fillna("")
    frame["curve_id"] = frame["curve_id"].fillna("")
    for c in ("lot_shared_with_nsi", "value_substitute"):
        frame[c] = frame[c].astype(str).eq("True")
    return frame


def alt_first_floors(root: Path) -> pd.Series:
    """FF-4's ``ffh_alt_m`` by LocNumber (NaN where none), from ``floors_values.first_floors``."""
    from flood_lab.assets import floors_values

    assets = pd.read_csv(ASSETS, dtype={"lab_nsi_id": str}, low_memory=False)
    floors = floors_values.first_floors(assets, root / NSI)
    return floors.set_index("LocNumber")["ffh_alt_m"].astype("float64")


def wall_columns(footprint_ids: list[str], detail: pd.DataFrame, locs: list[str]) -> np.ndarray:
    """Column of ``walls`` for each building LocNumber (-1: no footprint of the hazard's set).
    A doitt_id that occurs twice among the footprints is an error."""
    position: dict[str, int] = {}
    for i, d in enumerate(footprint_ids):
        if d in position:
            raise ValueError(f"doitt_id {d} occurs twice among the study footprints")
        position[d] = i
    doitt = detail.set_index("LocNumber")["detail_doitt_id"].astype(str)
    return np.array([position.get(doitt.get(loc, ""), -1) for loc in locs], dtype=np.int64)


# --- buildings --------------------------------------------------------------------------------


@dataclass
class BuildingCases:
    """Per run and building: the curve depth (NaN unless READ) and the case."""

    locs: list[str]
    depth: np.ndarray  # runs x buildings, depth above ground used (after the dry threshold)
    at: np.ndarray  # runs x buildings, depth above first floor to read, NaN unless READ
    case: np.ndarray  # runs x buildings, building_depth.Case
    reason: list[str]  # per building: "" or the failure reason


def building_cases(
    buildings: pd.DataFrame,
    walls: np.ndarray,
    columns: np.ndarray,
    curves: dict[str, Any],
    *,
    dry_below_m: float,
    ffh_column: str = "ffh_m",
) -> BuildingCases:
    """Apply the dry threshold and BD-1..BD-5 to every run and building."""
    runs = walls.shape[0]
    n = len(buildings)
    depth = np.full((runs, n), np.nan)
    have = columns >= 0
    depth[:, have] = walls[:, columns[have]]
    depth = np.where(np.isfinite(depth) & (depth < dry_below_m), 0.0, depth)
    points = {c["id"]: c["points"] for c in curves["building_curves"]}
    at = np.full((runs, n), np.nan)
    case = np.full((runs, n), int(building_depth.Case.NO_LOSS), dtype=np.int8)
    reason = [""] * n
    ffh = buildings[ffh_column].to_numpy(dtype=float)
    flags = buildings["basement"].to_numpy(dtype=object)
    curve_ids = buildings["curve_id"].to_list()
    for j in range(n):
        d = depth[:, j]
        if not have[j]:
            case[:, j] = building_depth.Case.FAILED
            reason[j] = NOT_IN_HAZARD
            continue
        if np.isnan(d).any():
            case[:, j] = building_depth.Case.FAILED
            reason[j] = NOT_READ
            continue
        cid = curve_ids[j]
        if not cid:
            wet = d > 0
            case[wet, j] = building_depth.Case.FAILED
            if wet.any():
                reason[j] = NO_CURVE
            continue
        p = points[cid]
        a, c = building_depth.curve_depth(
            d,
            np.full(runs, ffh[j]),
            np.full(runs, flags[j], dtype=object),
            float(p[0][0]),
            float(p[-1][0]),
        )
        at[:, j], case[:, j] = a, c
        if (c == building_depth.Case.FAILED).any():
            reason[j] = BD_FAILED
    return BuildingCases(list(buildings["LocNumber"]), depth, at, case, reason)


def building_table(
    cat: Catalogue,
    buildings: pd.DataFrame,
    cases: BuildingCases,
    *,
    value_column: str,
    label: str,
) -> tuple[EventLossTable, list[str]]:
    """The buildings' event-loss table: READ cases go to CRC, the rest are absent (no loss).
    Buildings with any failure, and buildings without a value in ``value_column``, are left out
    of the table; returned with the table as the list of their LocNumbers."""
    value = buildings[value_column].to_numpy(dtype=float)
    failed = np.array([bool(r) for r in cases.reason])
    keep = ~failed & np.isfinite(value)
    impacts = crc_adapter.building_impacts()
    exposures = tuple(
        Exposure(loc, float(v), cid)
        for loc, v, cid, k in zip(cases.locs, value, buildings["curve_id"], keep, strict=True)
        if k and cid
    )
    with_curve = {e.component_id for e in exposures}
    read = cases.case == building_depth.Case.READ
    r, b = np.nonzero(read)
    mask = np.array([cases.locs[j] in with_curve for j in b], dtype=bool)
    r, b = r[mask], b[mask]
    intensities = pa.table(
        {
            "event_id": pa.array([cat.labels[i] for i in r], pa.string()),
            "component_id": pa.array([cases.locs[j] for j in b], pa.string()),
            "value": pa.array(cases.at[r, b], pa.float64()),
        }
    )
    table = EventLossTable.from_intensities(
        cat.events,
        intensities,
        intensity=crc_adapter.DEPTH_ABOVE_FIRST_FLOOR,
        exposures=exposures,
        impacts=impacts,
        currency=CURRENCY,
        valuation_basis=VALUATION,
        label=label,
    )
    left_out = [loc for loc, k in zip(cases.locs, keep, strict=True) if not k]
    return table, left_out


# --- substations ------------------------------------------------------------------------------


def substation_choice(exposures: pd.DataFrame, basis: str = "role") -> dict[str, dict[str, str]]:
    """Curve id per family for every substation with a value and a curve, on C-5 ``basis``."""
    assets = pd.read_csv(ASSETS, low_memory=False).set_index("LocNumber")
    out = {}
    for _, s in exposures[exposures["asset_type"] == "substation"].iterrows():
        if not s["curve_id"] or not np.isfinite(s["value_mid_usd_2026"]):
            continue
        a = assets.loc[s["LocNumber"]]
        kv = a.get("lab_voltage_kv")
        kind = a.get("lab_substation_kind")
        chosen = envelope.envelope_for(
            float(kv) if pd.notna(kv) else None,
            str(kind) if pd.notna(kind) else None,
            basis,
        )
        if chosen is None:
            raise ValueError(f"{s['LocNumber']}: a curve in exposures.csv but none on {basis}")
        if basis == "role":
            stated = dict(zip(FAMILIES, s["curve_id"].split("|"), strict=True))
            if stated != chosen:
                raise ValueError(f"{s['LocNumber']}: exposures.csv curves {stated} != {chosen}")
        out[s["LocNumber"]] = chosen
    return out


def substation_tables(
    cat: Catalogue,
    exposures: pd.DataFrame,
    lead: np.ndarray,
    site_ids: list[str],
    *,
    dry_below_m: float,
    value_column: str = "value_mid_usd_2026",
    basis: str = "role",
) -> dict[str, EventLossTable]:
    """One event-loss table per family; every run at every valued site with depth > 0 (after the
    dry threshold) is a row."""
    choice = substation_choice(exposures, basis)
    values = exposures.set_index("LocNumber")[value_column]
    impacts = crc_adapter.substation_impacts()
    d = np.where(lead < dry_below_m, 0.0, lead)
    tables = {}
    for fam in FAMILIES:
        exp = tuple(
            Exposure(loc, float(values[loc]), choice[loc][fam])
            for loc in site_ids
            if loc in choice and np.isfinite(values[loc])
        )
        valued = {e.component_id for e in exp}
        rows = [
            (cat.labels[i], loc, float(d[i, j]))
            for j, loc in enumerate(site_ids)
            if loc in valued
            for i in range(len(cat.labels))
            if d[i, j] > 0
        ]
        intensities = pa.table(
            {
                "event_id": pa.array([x[0] for x in rows], pa.string()),
                "component_id": pa.array([x[1] for x in rows], pa.string()),
                "value": pa.array([x[2] for x in rows], pa.float64()),
            }
        )
        tables[fam] = EventLossTable.from_intensities(
            cat.events,
            intensities,
            intensity=crc_adapter.DEPTH,
            exposures=exp,
            impacts={i: impacts[i] for i in {e.impact for e in exp}},
            currency=CURRENCY,
            valuation_basis=VALUATION,
            label=f"substations, {fam} ({basis})",
        )
    return tables


# --- sums -------------------------------------------------------------------------------------


def annual(table: EventLossTable, measure: AnnualMeasure = AnnualMeasure.AGGREGATE):
    """The extension's sums; a CRC failure row leaves its component out, named (FR5)."""
    return annual_losses(table, measure=measure, failures=FailurePolicy.EXCLUDE_COMPONENT)


def combine(parts: list[AnnualLosses], label: str) -> AnnualLosses:
    """Buildings and substations of one portfolio: their per-year totals added, components side
    by side. Every part must share the years and measure; component ids must not repeat."""
    first = parts[0]
    components: dict[str, np.ndarray] = {}
    for p in parts:
        if p.years != first.years or p.measure is not first.measure:
            raise ValueError("parts differ in years or measure")
        for c, v in p.components.items():
            if c in components:
                raise ValueError(f"component {c} is in two parts")
            components[c] = v
    return AnnualLosses(
        measure=first.measure,
        years=first.years,
        totals=np.sum([p.totals for p in parts], axis=0),
        components=components,
        currency=first.currency,
        valuation_basis=first.valuation_basis,
        label=label,
        diagnostics=tuple(d for p in parts for d in p.diagnostics),
    )


def root_default() -> Path:
    return cache.root()
