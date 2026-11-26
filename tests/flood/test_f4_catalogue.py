"""F4 selection, weights and per-cell depth frequency (flood_lab.hazard.catalogue)."""

import numpy as np

from flood_lab.hazard import catalogue as c


def test_strata_cover_every_rank_once():
    sel = c.select(1000)
    assert len(sel) == 150
    covered = sorted(r for x in sel for r in range(x["block_first"], x["block_last"] + 1))
    assert covered == list(range(1, 1001))
    assert all(x["block_first"] <= x["rank"] <= x["block_last"] for x in sel)
    assert sum(x["weight"] for x in sel) == 1000
    assert [x["order"] for x in sel] == list(range(1, 151))


def test_selection_is_reproducible_and_interleaved():
    a, b = c.select(1000), c.select(1000)
    assert [x["rank"] for x in a] == [x["rank"] for x in b]
    first60 = [x["stratum"] for x in a[:60]]
    assert first60.count("T1") == 12 and first60.count("T2") == 24 and first60.count("T3") == 24


def test_interim_weights_sum_to_covered_strata():
    sel = c.select(1000)
    done = {x["label"] for x in sel[:60]}
    w = c.weights(sel, done, 1000)
    assert abs(sum(w.values()) - 1000) < 1e-9
    assert c.covered_years(sel, {x["label"] for x in sel}, 1000) == 1000


def test_depth_at_matches_rank_convention():
    m = 1000
    depth = np.arange(m, 0, -1, dtype=float)[:, None] / 100.0  # rank r has depth (M - r + 1) / 100
    w = np.ones(m)
    out = c.depth_at(depth, w, m, aeps=(0.002, 0.01, 0.5))
    assert out[:, 0].tolist() == [depth[1, 0], depth[9, 0], depth[499, 0]]


def test_dry_mass_and_zero_below_wet_probability():
    depth = np.array([[0.5], [0.2], [0.01], [0.0]])
    w = np.array([1.0, 1.0, 4.0, 4.0])
    m = 10.0
    assert c.wet_probability(depth, w, m)[0] == 0.2
    out = c.depth_at(depth, w, m, aeps=(0.5, 0.2, 0.1))
    assert out[:, 0].tolist() == [0.0, 0.2, 0.5]
    cleaned, changed = c.make_non_decreasing(out)
    assert changed == 0


def test_clean_up_counts_changed_cells():
    curves = np.array([[0.1, 0.1], [0.05, 0.2]])
    cleaned, changed = c.make_non_decreasing(curves)
    assert changed == 1 and cleaned[:, 0].tolist() == [0.1, 0.1]
