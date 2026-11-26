"""F4: the catalogue's depth frequency into CRC 1.0.0 by both routes, and read back (FH7)."""

import numpy as np

from flood_lab.hazard import catalogue
from flood_lab.risk import crc_load

WEST, NORTH, CELL = 585_500.0, 4_508_500.0, 5.0


def _depths(runs=40, rows=6, cols=7, seed=3):
    rng = np.random.default_rng(seed)
    d = np.where(rng.random((runs, rows, cols)) < 0.6, 0.0, rng.gamma(2.0, 0.2, (runs, rows, cols)))
    d[:, 0, 0] = np.nan  # a cell that is not read
    d[:, 0, 1] = 0.0  # dry in every run
    return d


def test_asset_knots_are_steps_with_dry_mass():
    probs, values = crc_load.asset_knots(
        np.array([0.0, 0.01, 0.4, 0.2]), np.array([5, 3, 1, 1.0]), 10
    )
    g = crc_load.STEP_GAP
    assert probs == [0.0, 0.8 - g, 0.8, 0.9 - g, 0.9, 1.0]
    assert values == [0.0, 0.0, 0.2, 0.2, 0.4, 0.4]


def test_asset_knots_always_wet_and_always_dry():
    assert crc_load.asset_knots(np.zeros(3), np.ones(3), 3) == ([0.0, 1.0], [0.0, 0.0])
    probs, values = crc_load.asset_knots(np.array([0.3, 0.6]), np.ones(2), 2)
    assert probs == [0.0, 0.5 - crc_load.STEP_GAP, 0.5, 1.0] and values == [0.3, 0.3, 0.6, 0.6]


def test_point_route_reads_the_catalogue_at_every_probability():
    """CH-23: CRC's reading of the point route equals ``depth_at``, ties at a knot included."""
    d = _depths(runs=40)[:, 1:4, 3]
    d[:, 2] = np.where(np.arange(40) < 30, 0.0, 0.5)  # a jump exactly at AEP 0.25 = 10/40
    w = np.full(d.shape[0], 25.0)
    aeps = (*catalogue.AEPS, 0.25, 0.1, 0.05)
    want = catalogue.depth_at(d, w, 1000.0, aeps=aeps)
    got = crc_load.point_route_at(d, w, 1000.0, aeps=aeps)
    assert np.allclose(got, want, atol=1e-12), (got, want)


def test_grid_route_round_trip(tmp_path):
    d = _depths()
    w = np.full(d.shape[0], 25.0)
    g = crc_load.grid_curves(d, w, 1000.0)
    assert g["cells_read"] == d.shape[1] * d.shape[2] - 1
    files = crc_load.write_rasters(g["curves"], tmp_path, WEST, NORTH, CELL)
    assert sorted(files) == sorted(1 - a for a in catalogue.AEPS)
    back = crc_load.load_grid(files, g["curves"], WEST, NORTH, CELL)
    assert back["equal"], back


def test_point_route_round_trip():
    d = _depths()[:, 1:3, 2]  # (runs, 2 assets)
    w = np.full(d.shape[0], 25.0)
    assets = [
        {"id": "a", "longitude": -73.96, "latitude": 40.70},
        {"id": "b", "longitude": -73.95, "latitude": 40.71},
    ]
    back = crc_load.load_points(crc_load.points_table(assets, d, w, 1000.0))
    assert back["equal"], back
