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


def test_asset_knots_carry_dry_mass_exactly():
    probs, values = crc_load.asset_knots(
        np.array([0.0, 0.01, 0.4, 0.2]), np.array([5, 3, 1, 1.0]), 10
    )
    assert probs == [0.0, 0.8, 0.9, 1.0] and values == [0.0, 0.0, 0.2, 0.4]


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
