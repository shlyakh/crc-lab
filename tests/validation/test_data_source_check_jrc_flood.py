"""JRC flood assessment on small constructed publisher folders, offline.

Two folders are built, laid out as the publisher's: GloFAS with two tiles that meet at a
seam and seven return periods, EFAS with one raster and nine. The pixels are made to sit on
every rule's boundary: wet at three and at four return periods, the same depth at every
return period, a depth that decreases, dry everywhere, and a box whose edges fall inside
pixels and across the seam. The reference reader reads the folders in place; crc-sdk is
pointed at them as if they were the publisher.

One 256 by 256 block as stored in a publisher file (block 554 of
``RP100/ID18_N40_W130_RP100_depth.tif``, GloFAS 2.1.2, downloaded 2026-11-17, file SHA-256
035960c9...b66624a2) tests the decoder on real bytes.
"""

import hashlib
import json
from dataclasses import replace
from pathlib import Path

import numpy as np
import pyarrow  # noqa: F401  (before rasterio: see the note in adapters/crc/jrc_flood.py)
import pytest
import rasterio
from rasterio.transform import from_origin

from data_source_check.assessments import jrc_flood as assessment
from data_source_check.core import inventory
from data_source_check.reference import jrc_flood as reference

FIXTURES = Path(__file__).parent / "fixtures"
VERSIONS = {"crc-sdk": "test"}
STEP = 1 / 1200  # three arc seconds, as the publisher's grids
NODATA = -9999.0
GLOFAS_PERIODS = (10, 20, 50, 75, 100, 200, 500)
EFAS_PERIODS = (10, 20, 30, 40, 50, 75, 100, 200, 500)
ROWS, COLUMNS = 40, 48
WEST, NORTH = -100.0, 31.0
SEAM = WEST + COLUMNS * STEP
# edges fall 0.6 of a pixel inside a pixel, so "touched" and "rounded" windows differ;
# the box crosses the seam between the two tiles
BOX = (WEST + 11.6 * STEP, NORTH - 30.6 * STEP, SEAM + 20.6 * STEP, NORTH - 4.4 * STEP)
FAR = (10.0, 10.0, 10.2, 10.2)
AREA = assessment.Area("glofas-test", "glofas", BOX, 9, "constructed box")
EUROPE = assessment.Area("efas-test", "efas", (8.0 + 3.6 * STEP, 50.0 - 20.6 * STEP,
                                               8.0 + 30.4 * STEP, 50.0 - 2.4 * STEP), 7,
                         "constructed box")  # fmt: skip
OUTSIDE = assessment.Area("efas-far", "efas", FAR, 7, "a box outside the raster")
# (row, column) of pixels inside the box, in the first tile
THREE, FOUR, FLAT, DOWN, DRY = (10, 20), (10, 21), (12, 20), (12, 21), (14, 20)


def _stack(periods: tuple[int, ...], seed: int) -> np.ndarray:
    """Depths that increase with the return period; a third of the pixels start dry."""
    rng = np.random.default_rng(seed)
    steps = rng.uniform(0.05, 0.6, (len(periods), ROWS, COLUMNS))
    stack = (rng.uniform(0.1, 3.0, (ROWS, COLUMNS)) + np.cumsum(steps, axis=0)).astype("<f4")
    first_wet = rng.integers(0, len(periods), (ROWS, COLUMNS))
    first_wet[rng.random((ROWS, COLUMNS)) < 0.6] = 0
    for index in range(len(periods)):
        stack[index][first_wet > index] = NODATA
    stack[:, rng.random((ROWS, COLUMNS)) < 0.2] = NODATA  # never wet
    return stack


def _specials(stack: np.ndarray) -> None:
    count = stack.shape[0]
    rising = np.linspace(0.5, 2.0, count).astype("<f4")
    for (row, column), wet in ((THREE, 3), (FOUR, 4)):
        stack[:, row, column] = rising
        stack[: count - wet, row, column] = NODATA
    stack[:, FLAT[0], FLAT[1]] = 1.0
    stack[:, DOWN[0], DOWN[1]] = rising
    stack[3, DOWN[0], DOWN[1]] = 0.2
    stack[:, DRY[0], DRY[1]] = NODATA


def _write(path: Path, data: np.ndarray, west: float, north: float, **more: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    profile = {"driver": "GTiff", "dtype": data.dtype.name, "count": 1, "width": data.shape[1],
               "height": data.shape[0], "crs": "EPSG:4326", "nodata": NODATA,
               "transform": from_origin(west, north, STEP, STEP), "compress": "deflate",
               "tiled": True, "blockxsize": 16, "blockysize": 16, **more}  # fmt: skip
    with rasterio.open(path, "w", **profile) as target:
        target.write(data, 1)


def build_publisher(root: Path, flat_then_a_jump: bool = False) -> dict[str, Path]:
    glofas, efas = root / "glofas", root / "efas"
    tiles = {"ID1_N31_W100": WEST, "ID2_N31_W099": SEAM}
    for number, (tile, west) in enumerate(tiles.items()):
        stack = _stack(GLOFAS_PERIODS, seed=number + 1)
        if number == 0:
            _specials(stack)
            if flat_then_a_jump:  # the depths crc-framework's optimizer does not converge on
                stack[:, 16, 20] = (1.0, 1.0, 1.0, 1.0, 1.0, 1.016, 1.13)
        for index, period in enumerate(GLOFAS_PERIODS):
            _write(glofas / f"RP{period}" / f"{tile}_RP{period}_depth.tif", stack[index],
                   west, NORTH)  # fmt: skip
    features = [
        {"type": "Feature", "properties": {"id": int(tile[2]), "name": tile[4:]},
         "geometry": {"type": "Polygon", "coordinates": [[
             [west, NORTH], [west + COLUMNS * STEP, NORTH],
             [west + COLUMNS * STEP, NORTH - ROWS * STEP], [west, NORTH - ROWS * STEP],
             [west, NORTH]]]}}
        for tile, west in tiles.items()
    ]  # fmt: skip
    (glofas / "tile_extents.geojson").write_text(
        json.dumps({"type": "FeatureCollection", "features": features}), encoding="utf-8"
    )
    stack = _stack(EFAS_PERIODS, seed=7)
    _specials(stack)
    for index, period in enumerate(EFAS_PERIODS):
        _write(efas / f"Europe_RP{period}_filled_depth.tif", stack[index], 8.0, 50.0)
    for folder, release in ((glofas, "2.1.2"), (efas, "3.1.1")):
        (folder / "README.txt").write_text(
            f"GENERAL INFORMATION\n\nG01. Dataset version {release}\n"
            "D01. Horizontal coverage: constructed\n"
            "A02. License information, restrictions on use: constructed licence\n",
            encoding="utf-8",
        )
        (folder / "copyright.txt").write_text("constructed", encoding="utf-8")
    return {"glofas": glofas, "efas": efas}


@pytest.fixture
def publisher(tmp_path: Path) -> dict[str, Path]:
    return build_publisher(tmp_path / "publisher")


def _run(tmp_path: Path, publisher: dict[str, Path], *, live: bool = True,
         rules: reference.Rules | None = None, name: str = "cache") -> dict:  # fmt: skip
    return assessment.assess(
        tmp_path / name, live=live, versions=VERSIONS, rules=rules, publisher=publisher,
        areas=(AREA, EUROPE), outside=(OUTSIDE,), sample_values=500, sample_pixels=200,
        strip_rows=7,
    )  # fmt: skip


def _outcomes(run: dict) -> dict[str, str]:
    return {check["check"]: check["outcome"] for check in run["checks"]}


# ---------------------------------------------------------------------------- the TIFF reader
@pytest.mark.parametrize(
    ("dtype", "options"),
    [
        ("float32", {}),
        ("float32", {"tiled": False}),
        ("float32", {"compress": "none"}),
        ("float64", {"blockxsize": 32, "blockysize": 16}),
        ("uint8", {"nodata": 0}),
    ],
)
def test_the_reader_agrees_with_gdal(tmp_path: Path, dtype: str, options: dict) -> None:
    data = (np.random.default_rng(3).random((37, 53)) * 200).astype(dtype)
    profile = {"driver": "GTiff", "dtype": dtype, "count": 1, "width": 53, "height": 37,
               "crs": "EPSG:4326", "nodata": NODATA, "compress": "deflate", "tiled": True,
               "transform": from_origin(WEST, NORTH, STEP, STEP),
               "blockxsize": 16, "blockysize": 16, **options}  # fmt: skip
    if not profile["tiled"]:
        del profile["blockxsize"], profile["blockysize"]
    path = tmp_path / "one.tif"
    with rasterio.open(path, "w", **profile) as target:
        target.write(data, 1)
    with reference.Tiff(path) as tiff, rasterio.open(path) as gdal:
        assert np.array_equal(tiff.read(), gdal.read(1))
        assert np.array_equal(tiff.read((5, 3, 41, 30)), gdal.read(1)[3:30, 5:41])
        assert tiff.bounds == pytest.approx(tuple(gdal.bounds), abs=1e-12)
        assert tiff.nodata == gdal.nodata
        assert tiff.tiled == profile["tiled"]
        assert tiff.geographic["geographic"] == 4326


def test_the_reader_decodes_a_block_cut_from_a_publisher_file() -> None:
    raw = (FIXTURES / "jrc_glofas_ID18_RP100_block.bin").read_bytes()
    block = reference.decode_block(raw, 8, np.dtype("<f4"), 256, 256)
    assert hashlib.sha256(block.tobytes()).hexdigest() == (
        "99e5e0a9eecf551af2dcc44857f0c23dfb9fb8cdcd51d73be30581c31f35aa67"
    )  # the same block read through GDAL
    wet = block[block != NODATA]
    assert len(wet) == 6679
    assert float(wet.max()) == pytest.approx(20.34)
    assert float(wet.min()) >= 0.1  # dry pixels hold the nodata value, never zero


def test_the_reader_refuses_what_it_does_not_understand(tmp_path: Path) -> None:
    path = tmp_path / "lzw.tif"
    _write(path, np.ones((16, 16), "<f4"), WEST, NORTH, compress="lzw")
    with pytest.raises(reference.TiffError, match="compression"):
        reference.Tiff(path)
    (tmp_path / "text.tif").write_bytes(b"not a tiff at all")
    with pytest.raises(reference.TiffError, match="not a TIFF"):
        reference.Tiff(tmp_path / "text.tif")


# ---------------------------------------------------------------------------- the rules
def test_reference_rules_on_small_series() -> None:
    periods = (10, 20, 50, 100, 500)
    nan = np.nan
    values = np.array([
        [0.5, nan, 1.0, 2.0, nan],
        [0.9, nan, 1.0, 1.5, nan],
        [1.4, 0.3, 1.0, 1.7, nan],
        [1.8, 0.6, 1.0, 2.5, 0.2],
        [2.6, 1.1, 1.0, 3.0, 0.4],
    ])  # fmt: skip
    fitted = reference.fit(periods, values)
    assert fitted["knots"].tolist() == [5, 3, 5, 5, 2]
    assert fitted["enough"].tolist() == [True, False, True, True, False]
    assert fitted["constant"].tolist() == [False, False, True, False, False]
    assert fitted["increasing"].tolist() == [True, True, True, False, True]
    # a straight line in the reduced variate is fitted exactly
    y = reference.reduced_variate(periods)
    line = (0.7 + 0.45 * y)[:, None]
    exact = reference.fit(periods, line)
    assert exact["location"][0] == pytest.approx(0.7, abs=1e-12)
    assert exact["scale"][0] == pytest.approx(0.45, abs=1e-12)
    assert reference.quantile(exact["location"], exact["scale"], 50)[0] == pytest.approx(
        float(line[2, 0]), abs=1e-12
    )
    # nodata and the window of every pixel a box touches
    raw = np.array([[NODATA, 0.1, np.inf]], dtype="<f4")
    assert np.isnan(reference.depths(raw, NODATA)).tolist() == [[True, False, True]]
    assert reference.tiles_for(
        {"features": [{"properties": {"id": 1, "name": "a"}, "geometry": {"coordinates": [[
            [0, 1], [1, 1], [1, 0], [0, 0], [0, 1]]]}}]}, (1.0, 0.2, 2.0, 0.4)
    ) == ["ID1_a"]  # a tile that only touches the box counts  # fmt: skip


def test_version_and_statements_are_read_from_the_readme() -> None:
    readme = ("G01. Dataset version 2.1.2 \nD01. Horizontal coverage: Global \n"
              "A02. License information, restrictions on use: Open Database License\n")  # fmt: skip
    assert reference.version(readme) == "2.1.2"
    assert reference.stated(readme)["licence"] == "Open Database License"
    assert reference.stated(readme)["coverage"] == "Global"
    assert reference.version("no version here") == ""


def test_cells_of_a_pixel_are_those_its_square_overlaps() -> None:
    import h3

    box = (WEST, NORTH - STEP, WEST + STEP, NORTH)
    cells = reference.cells_of_box(box, 10)
    centre = h3.str_to_int(h3.latlng_to_cell(NORTH - STEP / 2, WEST + STEP / 2, 10))
    assert centre in cells and len(cells) > 1  # a 90 m pixel is wider than a resolution-10 cell
    assert reference.cells_of_box(box, 10, reference.Rules(cells_overlapping=False)) == [centre]
    assert len(reference.cells_of_box(box, 5)) == 1


# ---------------------------------------------------------------------------- the assessment
def test_assessment_on_the_constructed_publisher(tmp_path: Path, publisher: dict) -> None:
    run = _run(tmp_path, publisher)
    outcomes = _outcomes(run)
    assert set(outcomes.values()) == {"confirmed"}, outcomes
    assert len(outcomes) == 2 + 8 * 2 + 1
    by_name = {check["check"]: check["result"] for check in run["checks"]}
    crop = by_name["crop[glofas-test]"]
    assert crop["tiles"] == 2  # the box crosses the seam
    assert crop["pixels_compared"] == 7 * 27 * (37 + 21) and crop["pixels_differing"] == 0
    curves = by_name["curves[glofas-test]"]
    assert curves["curves_reference"] == curves["curves_framework"] > 500
    assert curves["no_curve"]["all_depths_equal"] == 1
    assert curves["no_curve"]["a_depth_decreases"] == 1
    assert curves["no_curve"]["fewer_than_four_depths"] > 50
    assert by_name["source-id[glofas-test]"]["equal_to_the_publisher_file_position"] == 0
    assert by_name["provenance[glofas-test]"]["empty_fields"] == [
        "licence", "attribution", "retrieved_at", "checksum"]  # fmt: skip
    assert by_name["coverage[efas-far]"]["crc_sdk_error_type"] == "LookupError"
    areas = {area["area"]: area for area in run["exploration"]["areas"]}
    assert areas["glofas-test"]["fitted"] == curves["curves_reference"]
    assert areas["glofas-test"]["ever_wet"] > areas["glofas-test"]["fitted"]
    assert all(check["summary"] for check in run["checks"])
    assert run["chart"]["default"] in run["chart"]["series"]


@pytest.mark.parametrize(
    ("change", "check"),
    [
        ({"nodata_is_missing": False}, "curves"),
        ({"minimum_knots": 3}, "curves"),
        ({"touched_pixels": False}, "crop"),
        ({"reduced_variate": False}, "curves"),
        ({"cells_overlapping": False}, "cells"),
    ],
)
def test_a_wrong_reference_rule_ends_as_differs_fault(
    tmp_path: Path, publisher: dict, change: dict, check: str
) -> None:
    run = _run(tmp_path, publisher, rules=replace(reference.Rules(), **change))
    assert _outcomes(run)[f"{check}[glofas-test]"] == "differs"


def test_a_changed_pixel_in_a_crop_ends_as_differs_fault(tmp_path: Path, publisher: dict) -> None:
    _run(tmp_path, publisher)
    # the publisher's file changes after crc-sdk cropped it
    path = publisher["glofas"] / "RP50" / "ID1_N31_W100_RP50_depth.tif"
    with rasterio.open(path) as source:
        data, profile = source.read(1), source.profile
    data[FOUR] += 0.25
    with rasterio.open(path, "w", **profile) as target:
        target.write(data, 1)
    run = _run(tmp_path, publisher)
    result = next(c for c in run["checks"] if c["check"] == "crop[glofas-test]")
    assert result["outcome"] == "differs" and result["result"]["pixels_differing"] == 1


def test_depths_the_optimizer_does_not_converge_on_are_seen(tmp_path: Path) -> None:
    """crc-framework 0.6.0 gives up on depths that are flat and then rise (CRC-013-FWK)."""
    publisher = build_publisher(tmp_path / "publisher", flat_then_a_jump=True)
    run = _run(tmp_path, publisher)
    result = next(c for c in run["checks"] if c["check"] == "curves[glofas-test]")
    assert result["outcome"] == "differs"
    assert result["result"]["only_in_reference"] == 1
    assert result["result"]["values_differing"] == 0
    example = result["result"]["examples"][0]
    assert (example["row"], example["column"]) == (16, 20)
    assert example["values"] == [1.0, 1.0, 1.0, 1.0, 1.0, 1.016, 1.13]


def test_a_second_run_from_the_stored_answers_gives_the_same_records(
    tmp_path: Path, publisher: dict
) -> None:
    def comparable(run: dict) -> list:
        return [{k: v for k, v in check.items() if k not in ("run_at", "inputs")}
                for check in run["checks"]]  # fmt: skip

    first = _run(tmp_path, publisher)
    again = _run(tmp_path, publisher, live=False)
    assert comparable(first) == comparable(again)
    with pytest.raises(FileNotFoundError, match="--live"):
        _run(tmp_path, publisher, live=False, name="empty")


def test_checks_name_only_steps_of_the_statement(tmp_path: Path, publisher: dict) -> None:
    source = next(s for s in inventory.load_sources("crc_sdk") if s.id == "jrc-flood")
    steps = {step.id for step in source.statement}
    named = {step for check in _run(tmp_path, publisher)["checks"] for step in check["steps"]}
    assert named <= steps
    assert steps - named == set(), "a step no check bears on needs a note saying why"
