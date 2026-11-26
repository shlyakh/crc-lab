"""Sightings: reports of the same flooding, from one source or several, combined (FV5, FT5).

Rule statement (the record and the F5 report repeat it):

1. **An observation** is one report of water at a place and time, from any source: its
   ``source``, an ``id`` (with the ids of every row it stands for, ``rows``), a ``kind``, a time
   window ``start`` to ``end`` on the New York wall clock (an instant has ``start == end``), and a
   position in metres (EPSG:32618) with a ``radius_m``: 0 for a point, larger for a small named
   place drawn as a disc of the same area.
2. **Duplicates** (the strict case) are rows that record one report twice, such as one 311 request
   held under both naming schemes. ``duplicate_pairs`` pairs them: rows of two different copies
   (``copy``, e.g. the scheme), the same kind, created within ``DUPLICATE_S`` [P], and at the same
   address or within ``DUPLICATE_M`` [P]; candidates are taken closest in time first, each row in
   at most one pair. A pair becomes one observation that keeps both row ids.
3. **Near** (the general case): two observations are near when the gap between their discs is at
   most ``NEAR_M`` [P] (distance between centres less both radii, never below 0) and the gap
   between their time windows is at most ``NEAR_S`` [P] (0 when the windows overlap). Sources and
   kinds may differ: a call about a flooded street and a call about a backed-up sewer at one
   corner, a call at a FloodNet sensor, a surveyed mark beside a call.
4. **A sighting** is a group of observations joined by chains of near pairs (single linkage: A
   near B and B near C puts A, B and C in one sighting even when A is far from C). Every member is
   kept, with its source and row ids. The sighting reports its sources, kinds, time span and its
   extent (the largest distance between two member centres), so a long chain shows.
5. Grouping is order-free: the same observations give the same sightings whatever their order.
   Sightings are numbered by their first time, then position.

A sighting is the lab's grouping. It says that these reports are close enough to be about one
flooding; it does not say that they are, and a sighting with one member is not a weaker flood.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

#: rule step 2 [P]: rows of one report under two copies are created this close, s, and placed this
#: close, m (the 311 pairs found on 29 Sep 2023 lie within 317 s and 25 m)
DUPLICATE_S = 600.0
DUPLICATE_M = 25.0
#: rule step 3 [P]: "a few tens of metres" and "close in time"
NEAR_M = 50.0
NEAR_S = 12 * 3600.0


@dataclass(frozen=True)
class Observation:
    source: str
    id: str
    kind: str
    start: pd.Timestamp
    end: pd.Timestamp
    x: float
    y: float
    radius_m: float = 0.0
    rows: tuple[str, ...] = field(default=())

    def as_row(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "id": self.id,
            "rows": list(self.rows or (self.id,)),
            "kind": self.kind,
            "start": self.start.isoformat(),
            "end": self.end.isoformat(),
            "easting_m": round(float(self.x), 1),
            "northing_m": round(float(self.y), 1),
            "radius_m": round(float(self.radius_m), 1),
        }


def duplicate_pairs(
    rows: pd.DataFrame,
    *,
    copy: str,
    first: str,
    second: str,
    x: pd.Series | None = None,
    y: pd.Series | None = None,
    max_s: float = DUPLICATE_S,
    max_m: float = DUPLICATE_M,
) -> list[dict[str, Any]]:
    """Rule step 2 on a table with ``unique_key``, ``created_date``, ``kind``,
    ``incident_address`` and the column ``copy`` (rows of value ``first`` pair with rows of value
    ``second``). ``x`` and ``y`` are positions in metres on the same index; without them only the
    address is used. Returns pairs ``{first, second, seconds, same_address}`` sorted by ``first``.
    """
    a_rows = rows[rows[copy] == first]
    b_rows = rows[rows[copy] == second]
    when = pd.to_datetime(rows["created_date"])
    candidates = []
    for i, a in a_rows.iterrows():
        same = b_rows[b_rows["kind"] == a["kind"]]
        for j, b in same.iterrows():
            gap = abs((when[j] - when[i]).total_seconds())
            if gap > max_s:
                continue
            address = (
                isinstance(a["incident_address"], str)
                and a["incident_address"] == b["incident_address"]
            )
            near = (
                x is not None
                and y is not None
                and bool(pd.notna(x[i]) and pd.notna(x[j]))
                and float(np.hypot(x[i] - x[j], y[i] - y[j])) <= max_m
            )
            if address or near:
                candidates.append((gap, str(a["unique_key"]), str(b["unique_key"]), address))
    used: set[str] = set()
    pairs = []
    for gap, a, b, address in sorted(candidates):
        if a in used or b in used:
            continue
        used |= {a, b}
        pairs.append({first: a, second: b, "seconds": gap, "same_address": address})
    return sorted(pairs, key=lambda p: p[first])


def _gap_m(a: Observation, b: Observation) -> float:
    return max(0.0, float(np.hypot(a.x - b.x, a.y - b.y)) - a.radius_m - b.radius_m)


def _gap_s(a: Observation, b: Observation) -> float:
    if a.end < b.start:
        return (b.start - a.end).total_seconds()
    if b.end < a.start:
        return (a.start - b.end).total_seconds()
    return 0.0


def near(
    a: Observation,
    b: Observation,
    near_m: float = NEAR_M,
    near_s: float = NEAR_S,
    same_kind: bool = False,
) -> bool:
    """Rule step 3. ``same_kind`` keeps kinds apart (used only for the sensitivity)."""
    if same_kind and a.kind != b.kind:
        return False
    return _gap_m(a, b) <= near_m and _gap_s(a, b) <= near_s


def group(
    observations: Sequence[Observation],
    near_m: float = NEAR_M,
    near_s: float = NEAR_S,
    same_kind: bool = False,
) -> list[list[Observation]]:
    """Rule steps 4 and 5: the sightings, each a list of members, numbered by first time."""
    items = sorted(observations, key=lambda o: (o.start, o.x, o.y, o.source, o.id))
    parent = list(range(len(items)))

    def root(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i in range(len(items)):
        for j in range(i + 1, len(items)):
            if near(items[i], items[j], near_m, near_s, same_kind):
                ri, rj = root(i), root(j)
                if ri != rj:
                    parent[max(ri, rj)] = min(ri, rj)
    groups: dict[int, list[Observation]] = {}
    for i, o in enumerate(items):
        groups.setdefault(root(i), []).append(o)
    return [groups[k] for k in sorted(groups)]


def extent_m(members: Iterable[Observation]) -> float:
    pts = np.array([(o.x, o.y) for o in members], dtype="float64").reshape(-1, 2)
    if len(pts) < 2:
        return 0.0
    d = np.hypot(pts[:, None, 0] - pts[None, :, 0], pts[:, None, 1] - pts[None, :, 1])
    return float(d.max())


def describe(sightings: list[list[Observation]], prefix: str) -> list[dict[str, Any]]:
    """One row per sighting, with every member traceable."""
    out = []
    for n, members in enumerate(sightings, start=1):
        out.append(
            {
                "sighting": f"{prefix}-{n:03d}",
                "members": len(members),
                "rows": sum(len(o.rows or (o.id,)) for o in members),
                "sources": sorted({o.source for o in members}),
                "kinds": sorted({o.kind for o in members}),
                "start": min(o.start for o in members).isoformat(),
                "end": max(o.end for o in members).isoformat(),
                "easting_m": round(float(np.mean([o.x for o in members])), 1),
                "northing_m": round(float(np.mean([o.y for o in members])), 1),
                "extent_m": round(extent_m(members), 1),
                "observations": [o.as_row() for o in members],
            }
        )
    return out


def by_sources(rows: list[dict[str, Any]]) -> dict[str, int]:
    """How many sightings each combination of sources saw (``311 + FloodNet``, ...)."""
    counts: dict[str, int] = {}
    for r in rows:
        key = " + ".join(r["sources"])
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])))


def sensitivity(
    observations: Sequence[Observation],
    metres: Sequence[float],
    seconds: Sequence[float],
) -> list[dict[str, Any]]:
    """The number of sightings for each pair of thresholds, and with kinds kept apart."""
    return [
        {
            "near_m": m,
            "near_h": s / 3600.0,
            "sightings": len(group(observations, m, s)),
            "sightings_kinds_apart": len(group(observations, m, s, same_kind=True)),
        }
        for m in metres
        for s in seconds
    ]
