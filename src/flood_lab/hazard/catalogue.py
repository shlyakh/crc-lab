"""F4: which synthetic years are run through the solver, with what weight, and the per-cell depth
frequency that follows (FH5, FH7). Numpy only; no CRC here (the load into CRC is ``crc_load``).

**The design.** RainyDay writes ``M`` synthetic years, one storm per year (its annual maximum
of ``DURATION``-hour rainfall over the study box), ranked by that rainfall. The solver cannot run
all ``M``, so the years are split by rank into strata and sampled:

* ``T1``, ranks 1 to ``top`` (the rarest years): every year is run.
* ``T2``, ranks ``top + 1`` to ``mid_end``: ``mid_n`` years, one drawn at random from each of
  ``mid_n`` equal blocks of consecutive ranks.
* ``T3``, the remaining ranks to ``M``: ``low_n`` years, one drawn at random from each of ``low_n``
  equal blocks (the last block takes the remainder).

A run stands for its block: its weight is the block's number of years. This is stratified
sampling by rainfall rank; it is unbiased for any per-cell statistic whatever the relation
between rainfall rank and depth, and its error is smallest where depth follows rainfall.

**Run order and figures made before the batch completes.** The runs are ordered so that the
three strata progress together (T1 : T2 : T3 in proportion to their run counts, random order
within each, a fixed seed). Until a stratum is complete its finished runs are treated as a simple
random sample of that stratum: weight = years in the stratum / runs finished in it. That
interim weight is stated on every figure with the number of storms behind it (requirements §15).

**Depth frequency per cell.** With depth ``D_i`` of run ``i`` and weight ``w_i`` (summing to ``M``),
the annual exceedance probability of depth ``d`` is ``P(D > d) = sum_i w_i [D_i > d] / M``: one
storm per synthetic year makes the annual maximum depth that storm's depth. This takes the
largest-rainfall storm of a year as the year's worst flood, a limit stated in the report. A cell
is dry in a year when ``D_i < WET_M``; the dry-year mass is ``sum of w_i over dry runs / M``.
The depth at probability ``p`` is the largest ``d`` with ``P(D >= d) >= p``, so that rank ``r`` of
``M`` equally weighted years has return period ``M / r`` as in RainyDay's own frequency output
(empirical, no fit, no interpolation between storms); it is 0 while ``p`` is above the
cell's wet probability (at ``p`` equal to it, the smallest wet depth).
Such quantiles cannot decrease as ``p`` falls, so the non-decreasing clean-up of FH7 has nothing
to change; it is still applied and the count of changed cells reported.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

WET_M = 0.05  # [P] a cell is wet in a run at this depth or more (the same 5 cm as FH8's wet rule)
#: annual exceedance probabilities at which curves are tabulated (2 to 500 years) [P]
AEPS = (0.5, 0.2, 0.1, 0.04, 0.02, 0.01, 0.005, 0.002)


@dataclass(frozen=True)
class Stratum:
    name: str
    first: int  # first rank, 1 = the largest rainfall
    last: int  # last rank, inclusive
    runs: int

    @property
    def years(self) -> int:
        return self.last - self.first + 1


def strata(
    m: int, top: int = 30, mid_end: int = 150, mid_n: int = 60, low_n: int = 60
) -> list[Stratum]:
    if not 0 < top < mid_end < m:
        raise ValueError("need 0 < top < mid_end < M")
    if mid_n > mid_end - top or low_n > m - mid_end:
        raise ValueError("more runs than years in a stratum")
    return [
        Stratum("T1", 1, top, top),
        Stratum("T2", top + 1, mid_end, mid_n),
        Stratum("T3", mid_end + 1, m, low_n),
    ]


def blocks(s: Stratum) -> list[tuple[int, int]]:
    """Equal blocks of consecutive ranks; the last takes the remainder."""
    size = s.years // s.runs
    out = []
    for j in range(s.runs):
        a = s.first + j * size
        b = s.last if j == s.runs - 1 else a + size - 1
        out.append((a, b))
    return out


def select(m: int, seed: int = 20261126, **kw) -> list[dict]:
    """The runs in run order, each ``{label, rank, stratum, block_first, block_last, weight,
    order}``."""
    rng = np.random.default_rng(seed)
    per: dict[str, list[dict]] = {}
    for s in strata(m, **kw):
        items = []
        for a, b in blocks(s):
            rank = a if a == b else int(rng.integers(a, b + 1))
            items.append(
                {
                    "label": f"cat_r{rank:04d}",
                    "rank": rank,
                    "stratum": s.name,
                    "block_first": a,
                    "block_last": b,
                    "weight": float(b - a + 1),
                }
            )
        rng.shuffle(items)
        per[s.name] = items
    # interleave: at each step take from the stratum furthest behind its share
    total = {k: len(v) for k, v in per.items()}
    taken = dict.fromkeys(per, 0)
    order = []
    while len(order) < sum(total.values()):
        k = min((k for k in per if taken[k] < total[k]), key=lambda k: (taken[k] + 1) / total[k])
        order.append(per[k][taken[k]])
        taken[k] += 1
    for i, item in enumerate(order, 1):
        item["order"] = i
    return order


def weights(selection: list[dict], done: set[str], m: int, **kw) -> dict[str, float]:
    """Weight of each finished run. A complete stratum uses block weights; an incomplete one treats
    its finished runs as a simple random sample of the stratum."""
    out = {}
    for s in strata(m, **kw):
        mine = [x for x in selection if x["stratum"] == s.name]
        fin = [x for x in mine if x["label"] in done]
        if not fin:
            continue
        if len(fin) == len(mine):
            out.update({x["label"]: x["weight"] for x in fin})
        else:
            out.update({x["label"]: s.years / len(fin) for x in fin})
    return out


def covered_years(selection: list[dict], done: set[str], m: int, **kw) -> int:
    """Synthetic years represented by the finished runs (M when every stratum has a run)."""
    return int(round(sum(weights(selection, done, m, **kw).values())))


def exceedance(depth: np.ndarray, w: np.ndarray, m: float) -> callable:
    """``depth`` (runs, cells); returns f(d) -> P(D > d) per cell."""
    w = np.asarray(w, float)

    def f(d: float | np.ndarray) -> np.ndarray:
        return ((depth > d) * w[:, None]).sum(axis=0) / m

    return f


def wet_probability(depth: np.ndarray, w: np.ndarray, m: float, wet: float = WET_M) -> np.ndarray:
    """Annual probability that a cell is wet (1 minus the dry-year mass)."""
    return ((depth >= wet) * np.asarray(w, float)[:, None]).sum(axis=0) / m


def depth_at(
    depth: np.ndarray, w: np.ndarray, m: float, aeps=AEPS, wet: float = WET_M
) -> np.ndarray:
    """Depth per cell at each annual exceedance probability, shape (len(aeps), cells).

    Dry runs (depth below ``wet``) count as depth 0. For each cell the runs are sorted by depth
    descending and their weights accumulated: the depth at ``p`` is the depth of the first run at
    which the accumulated probability reaches ``p`` (0 if none)."""
    d = np.where(depth >= wet, depth, 0.0)
    w = np.asarray(w, float)
    order = np.argsort(-d, axis=0, kind="stable")
    ds = np.take_along_axis(d, order, axis=0)
    cum = np.cumsum(w[order], axis=0) / m  # P(D >= ds[k]) for each k
    out = np.zeros((len(aeps), d.shape[1]))
    for j, p in enumerate(aeps):
        # first k with cum >= p (tolerance for summation): RainyDay's convention, in which rank r
        # of M years has return period M / r
        k = (cum < p * (1 - 1e-9)).sum(axis=0)
        valid = k < d.shape[0]
        out[j, valid] = ds[k[valid], np.nonzero(valid)[0]]
    return out


def make_non_decreasing(curves: np.ndarray) -> tuple[np.ndarray, int]:
    """``curves`` (len(aeps), cells) with aeps falling: depth must not fall as p falls.
    Returns the cleaned curves (running maximum) and the number of cells changed."""
    cleaned = np.maximum.accumulate(curves, axis=0)
    changed = int(np.any(cleaned != curves, axis=0).sum())
    return cleaned, changed
