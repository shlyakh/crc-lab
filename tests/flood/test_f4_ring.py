"""Pure helpers of the ring sensitivity (``sfincs_ring``, ``checks/f4_ring``), offline."""

from __future__ import annotations

import json

import numpy as np
import pytest

from flood_lab import domain
from flood_lab.checks import f4_ring
from flood_lab.hazard import sfincs_ring as ring


def test_ring_is_the_square_plus_the_terrain_margin():
    assert ring.SQUARE == domain.SQUARE
    assert ring.MARGIN_M == domain.TERRAIN_MARGIN_M
    assert ring.RING == (585_000.0, 4_504_000.0, 590_000.0, 4_509_000.0)
    assert ring.grid_shape() == (1000, 1000)


def test_square_window_cuts_the_square_cells():
    rows, cols = ring.square_window()
    assert (rows.start, rows.stop, cols.start, cols.stop) == (100, 900, 100, 900)
    with pytest.raises(ValueError):
        ring.square_window(inner=(585_502.0, 4_504_500.0, 589_500.0, 4_508_500.0))
    with pytest.raises(ValueError):
        ring.square_window(inner=(584_000.0, 4_504_500.0, 589_500.0, 4_508_500.0))


def test_inner_lines_close_the_square_counter_clockwise_on_cell_faces():
    lines = ring.inner_lines()
    assert len(lines) == 4 * 80
    for edge in ring.EDGES:
        pieces = [v for k, v in lines.items() if k.startswith(f"in_{edge}_")]
        assert len(pieces) == 80
        for a, b in zip(pieces[:-1], pieces[1:], strict=True):
            assert a[1] == b[0]  # contiguous
        for (x0, y0), (x1, y1) in pieces:
            assert abs(x1 - x0) + abs(y1 - y0) == pytest.approx(50.0)
            for v in (x0, y0, x1, y1):
                assert v % 5.0 == 0.0  # on a face of the 5 m grid
    w, s, e, n = domain.SQUARE
    assert lines["in_south_000"][0] == (w, s) and lines["in_south_079"][1] == (e, s)
    assert lines["in_east_000"][0] == (e, s) and lines["in_north_000"][0] == (e, n)
    assert lines["in_west_079"][1] == (w, s)
    with pytest.raises(ValueError):
        ring.inner_lines(piece_m=30.0)


def test_outer_lines_are_one_cell_inside_the_ring():
    lines = ring.outer_lines()
    assert lines["out_south"] == [(585_005.0, 4_504_005.0), (589_995.0, 4_504_005.0)]
    assert lines["out_west"][1] == (585_005.0, 4_504_005.0)


def test_edge_fluxes_split_inflow_and_outflow_per_piece():
    names = ["out_south", "in_south_000", "in_south_001", "in_east_000"]
    t = np.array([0.0, 10.0, 20.0])
    q = np.array(
        [
            [-1.0, 2.0, -1.0, 0.0],
            [-1.0, 2.0, -1.0, 0.0],
            [-1.0, 2.0, -1.0, 0.0],
        ]
    )
    out = ring.edge_fluxes(names, q, t)
    south = out["inner"]["south"]
    assert south["inflow_m3"] == pytest.approx(40.0)
    assert south["outflow_m3"] == pytest.approx(20.0)
    assert south["net_inward_m3"] == pytest.approx(20.0)
    assert south["pieces"] == 2
    assert out["inner"]["east"]["pieces"] == 1
    assert out["outer_inward_m3"] == {"south": pytest.approx(-20.0)}
    with pytest.raises(ValueError):
        ring.edge_fluxes(["x"], q[:, :1], t)
    with pytest.raises(ValueError):
        ring.edge_fluxes(names[:3], q, t)


def test_split_integrals_split_at_output_times():
    pos, neg = ring.split_integrals(np.array([[1.0], [-1.0]]), np.array([0.0, 2.0]))
    assert pos == [1.0] and neg == [1.0]


def test_index_range_and_cut_transposed():
    lat = np.arange(10) * 1.0
    assert ring.index_range(lat, 3.2, 5.5) == (2, 8)
    with pytest.raises(ValueError):
        ring.index_range(lat, 0.2, 5.0)
    parent = np.arange(2 * 10 * 10, dtype=float).reshape(2, 10, 10)
    block = ring.cut_transposed(parent, shift_y=2, shift_x=-1, rows=(4, 6), cols=(3, 5))
    # domain cell (r, c) holds the parent's (r - 2, c + 1)
    assert np.array_equal(block, parent[:, 2:4, 4:6])
    with pytest.raises(ValueError):
        ring.cut_transposed(parent, shift_y=5, shift_x=0, rows=(0, 3), cols=(0, 3))


def test_extend_axis_keeps_the_pixels_and_adds_whole_ones():
    axis, before = ring.extend_axis([10.0, 20.0, 30.0], 0.0, 40.0, pad=1)
    assert before == 2 and axis.tolist() == [-10.0, 0.0, 10.0, 20.0, 30.0, 40.0, 50.0]
    axis, before = ring.extend_axis([30.0, 20.0, 10.0], 12.0, 28.0, pad=1)
    assert before == 1 and axis.tolist() == [40.0, 30.0, 20.0, 10.0, 0.0]
    with pytest.raises(ValueError):
        ring.extend_axis([0.0, 1.0, 3.0], 0.0, 1.0)


def test_lowest_ranks_takes_finished_runs_only():
    sel = [{"label": f"r{k}", "rank": k} for k in (5, 1, 3, 2)]
    assert [x["label"] for x in ring.lowest_ranks(sel, {"r5", "r3", "r2"})] == ["r2", "r3"]


def test_analyse_on_a_synthetic_ring_run(tmp_path):
    xr = pytest.importorskip("xarray")
    n = 1000
    msk = np.ones((n, n), dtype="int8")
    msk[0, :] = msk[-1, :] = msk[:, 0] = msk[:, -1] = 3
    rain = np.full((1, n, n), 0.01, dtype="float32")
    vol = np.zeros((2, n, n), dtype="float32")
    vol[1, 100:900, 100:900] = 0.25  # 1 cm over each 25 m2 cell of the square
    zsmax = np.full((1, n, n), np.nan, dtype="float32")
    zsmax[0, 0, 0] = 2.0  # south-west corner
    times = np.array(["2026-01-01T00:00", "2026-01-01T01:00"], dtype="datetime64[ns]")
    xr.Dataset(
        {
            "msk": (("n", "m"), msk),
            "cumprcp": (("timemax", "n", "m"), rain),
            "cuminf": (("timemax", "n", "m"), np.zeros_like(rain)),
            "subgrid_volume": (("time", "n", "m"), vol),
            "zsmax": (("timemax", "n", "m"), zsmax),
            "zb": (("n", "m"), np.zeros((n, n), dtype="float32")),
        },
        coords={"time": times},
    ).to_netcdf(tmp_path / "sfincs_map.nc", engine="scipy")
    names = list(ring.all_lines())
    t = np.array(["2026-01-01T00:00", "2026-01-01T00:00:10"], dtype="datetime64[ns]")
    q = np.zeros((2, len(names)))
    q[:, names.index("in_south_000")] = 1.0  # 10 m3 in
    q[:, names.index("in_west_003")] = -0.5  # 5 m3 out
    xr.Dataset(
        {
            "crosssection_discharge": (("time", "sections"), q),
            "crosssection_name": (("sections",), np.array(names, dtype="S16")),
        },
        coords={"time": t},
    ).to_netcdf(tmp_path / "sfincs_his.nc", engine="scipy")
    bal = ring.analyse(tmp_path)
    assert bal["analysed_by"] == "sfincs_ring"
    sq = bal["square"]
    assert sq["rain_m3"] == pytest.approx(640_000 * 25 * 0.01, rel=1e-6)
    assert sq["inflow_m3"] == pytest.approx(10.0) and sq["outflow_m3"] == pytest.approx(5.0)
    assert sq["by_edge"]["south"]["inflow_m3"] == pytest.approx(10.0)
    assert sq["stored_m3"] == pytest.approx(640_000 * 0.25, rel=1e-6)
    assert sq["residual_m3"] == pytest.approx(sq["rain_m3"] + 5.0 - sq["stored_m3"], rel=1e-6)
    import rasterio

    with rasterio.open(tmp_path / "zsmax.tif") as src:
        assert src.transform.c == 585_000.0 and src.transform.f == 4_509_000.0
        z = src.read(1)
    assert z[-1, 0] == 2.0  # map row 0 (south) is the raster's last row
    assert json.loads((tmp_path / "balance.json").read_text())["extent"] == list(ring.RING)


# --- the comparison ------------------------------------------------------------------------------


def test_edge_distance_and_nearest_edge():
    d = f4_ring.edge_distance(4, 5.0)
    assert d[0, 0] == 2.5 and d[1, 1] == 7.5 and d[1, 2] == 7.5
    e = f4_ring.nearest_edge(4)
    names = ring.EDGES
    assert names[e[3, 1]] == "south" and names[e[1, 3]] == "east"
    assert names[e[0, 1]] == "north" and names[e[2, 0]] == "west"


def test_change_summary_counts_and_distances():
    sq = np.zeros((10, 10))
    rg = sq.copy()
    rg[9, 5] = 0.2  # deeper, at the south edge
    rg[3, 4] = -0.1  # shallower, inside, nearest the north edge
    rg[0, 0] = 0.04  # below the threshold
    where = np.ones_like(sq, dtype=bool)
    out = f4_ring.change_summary(sq, rg, where)
    assert out["changed"] == 2 and out["deeper"] == 1 and out["shallower"] == 1
    assert out["by_nearest_edge"]["south"] == 1 and out["by_nearest_edge"]["north"] == 1
    assert out["distance_m"]["bins"]["0-50"] == 2  # 2.5 m and 17.5 m
    assert out["largest_increase_m"] == 0.2


def test_wet_counts_and_site_pairs():
    depth = np.array([[0.0, 0.05], [0.3, 1.0]])
    assert f4_ring.wet_counts(depth, np.ones_like(depth, bool)) == {"wet_005": 3, "wet_030": 2}
    a = [{"LocNumber": "S-1", "name": "x", "depth_on_25m2_m": 0.2, "meets_lead_rule": False}]
    b = [{"LocNumber": "S-1", "name": "x", "depth_on_25m2_m": 0.35, "meets_lead_rule": True}]
    pair = f4_ring.site_pairs(a, b)[0]
    assert pair["change_m"] == 0.15 and pair["ring_meets_lead_rule"]
    with pytest.raises(ValueError):
        f4_ring.site_pairs(a, [{**b[0], "LocNumber": "S-2"}])


def test_run_on_table_shares():
    e = {"inflow_m3": 10.0, "outflow_m3": 2.0, "net_inward_m3": 8.0}
    bal = {
        "square": {
            "rain_m3": 100.0,
            "inflow_m3": 40.0,
            "outflow_m3": 8.0,
            "net_inward_m3": 32.0,
            "by_edge": {k: dict(e) for k in ring.EDGES},
        }
    }
    t = f4_ring.run_on_table(bal)
    assert t["inflow_share_of_square_rain"] == 0.4
    assert t["by_edge"]["west"]["inflow_share_of_square_rain"] == 0.1


def test_ring_status_names_missing_and_raw_runs(tmp_path):
    (tmp_path / "a").mkdir()
    (tmp_path / "a" / "balance.json").write_text(json.dumps({"analysed_by": "sfincs_ring"}))
    (tmp_path / "b").mkdir()
    (tmp_path / "b" / "balance.json").write_text(json.dumps({"rain_m3": 1.0}))
    queue = [{"label": "a"}, {"label": "b"}, {"label": "c"}]
    assert f4_ring.ring_status(tmp_path, queue) == (["c"], ["b"])
