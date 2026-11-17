"""JRC flood maps as crc-sdk delivers them. The only place that calls ``HazardDataset.glofas``
and ``HazardDataset.efas``.

crc-sdk's own cache folder (its cropped GeoTIFFs and manifest) and the canonical Parquet file
it writes are kept under the assessment's cache, so that a run without the network reads the
same answers again. Functions return plain Python values or numpy arrays.

Parquet files are opened as plain Python files. Where GDAL is built with its own copy of
Arrow (Homebrew's is), pyarrow can no longer create its local file system once GDAL is
loaded in the same process ("scheme 'file' is already registered"); a file handle avoids it.
"""

from __future__ import annotations

import json
import resource
import sys
import threading
import time
import warnings
from collections.abc import Sequence
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
from typing import Any

_LOCK = threading.Lock()


def facts(dataset: str) -> dict[str, Any]:
    """What crc-sdk states about a dataset without reading a raster."""
    from importlib.metadata import version

    from crc_sdk.providers import jrc

    declared = jrc.jrc_dataset(dataset)
    out: dict[str, Any] = {
        "dataset": declared.name,
        "layout": declared.layout,
        "base_url": declared.base_url,
        "readme_url": declared.readme_url,
        "tile_index_url": declared.tile_index_url,
        "configured_version": declared.version,
        "return_periods": list(declared.available_return_periods),
        "hazard_name": declared.hazard_name,
        "indicator_id": declared.indicator_id,
        "units": declared.units,
        "pathway": declared.pathway,
        "horizon": declared.horizon,
        "crc_sdk_version": version("crc-sdk"),
        "resolved_version": "",
        "error": "",
    }
    try:
        out["resolved_version"] = jrc.JRCProvider(declared).resolve_version("latest")
    except Exception as error:  # the error is the result
        out["error"] = f"{type(error).__name__}: {error}"
    return out


def resources(dataset: str, bounds: Sequence[float], periods: Sequence[int]) -> dict[str, Any]:
    """The tiles and file addresses crc-sdk chooses for a box."""
    from crc_sdk.providers import jrc

    provider = jrc.JRCProvider.for_dataset(dataset)
    chosen = provider.resources_for(tuple(bounds), return_periods=list(periods))
    return {
        "tiles": list(provider.tiles_for(tuple(bounds))),
        "resources": [
            {"source_id": r.source_id, "urls": {str(p): u for p, u in r.urls.items()}}
            for r in chosen
        ],
    }


@contextmanager
def publisher_at(dataset: str, folder: Path | None):  # noqa: ANN201
    """Within the block, crc-sdk reads ``dataset`` from a local folder laid out as the
    publisher's (None: unchanged). Used by the offline tests only."""
    from crc_sdk.providers import jrc

    if folder is None:
        yield
        return
    with _LOCK:
        original = jrc.JRC_DATASETS[dataset]
        base = folder.resolve().as_uri()
        index = f"{base}/tile_extents.geojson" if original.tile_index_url else None
        jrc.JRC_DATASETS[dataset] = replace(original, base_url=base, tile_index_url=index)  # type: ignore[index]
        try:
            yield
        finally:
            jrc.JRC_DATASETS[dataset] = original  # type: ignore[index]


def _plan(dataset: str, bounds: Sequence[float], resolution: int | str, cache: Path | None) -> Any:
    from crc_sdk.workflows import HazardDataset, JRCFloodPolicy

    source = HazardDataset.efas if dataset == "efas" else HazardDataset.glofas
    area = source(version="latest").for_area(tuple(bounds))
    area = area.cache(cache, mode="reuse") if cache is not None else area.cache(None, mode="stream")
    return area.source_periods("all").canonicalize(
        policy=JRCFloodPolicy.curated(h3_resolution=resolution)  # type: ignore[arg-type]
    )


def materialize(dataset: str, bounds: Sequence[float], resolution: int | str, folder: Path, *,
                live: bool = True, cached: bool = True) -> dict[str, Any]:  # fmt: skip
    """Run crc-sdk's plan for a box into ``folder`` and say what happened.

    ``folder/cache`` is crc-sdk's cache directory (``cached``; otherwise it streams),
    ``folder/hazard.parquet`` its output and ``folder/run.json`` this summary. An existing
    complete run is not repeated.
    """
    folder = folder.resolve()  # crc-sdk's manifest records the cache paths as they are given
    summary_path = folder / "run.json"
    output = folder / "hazard.parquet"
    if summary_path.exists():
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        if summary["error"] or output.exists():
            return summary
    if not live:
        raise FileNotFoundError(f"no stored crc-sdk run in {folder.name}; run with --live")
    folder.mkdir(parents=True, exist_ok=True)
    cache = folder / "cache" if cached else None
    summary: dict[str, Any] = {
        "request": {"dataset": dataset, "bounds": list(bounds), "h3_resolution": resolution,
                    "cache_mode": "reuse" if cached else "stream", "source_periods": "all",
                    "policy": "JRCFloodPolicy.curated"},
        "explain": "", "rows": 0, "source_version": "", "seconds": 0.0, "peak_memory_mb": 0.0,
        "error": "", "error_type": "", "warnings": [], "progress": {},
    }  # fmt: skip
    started = time.monotonic()
    stages: dict[str, int] = {}

    def progress(stage: str, _: dict[str, Any]) -> None:
        stages[stage] = stages.get(stage, 0) + 1

    try:
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            plan = _plan(dataset, bounds, resolution, cache)
            summary["explain"] = plan.explain()
            hazard = plan.materialize(output, progress=progress)
            result = hazard.materialization
            summary["rows"] = int(result.canonical_rows)
            summary["source_version"] = result.source_version
        summary["warnings"] = sorted({f"{w.category.__name__}: {w.message}" for w in caught})
    except Exception as error:  # the error is the result: it is recorded, not hidden
        summary["error"], summary["error_type"] = str(error), type(error).__name__
    summary["seconds"] = round(time.monotonic() - started, 1)
    summary["progress"] = stages
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    # bytes on macOS, kilobytes on Linux; the peak of the whole process so far
    summary["peak_memory_mb"] = round(peak / (1 << 20 if sys.platform == "darwin" else 1 << 10))
    temporary = summary_path.with_suffix(".tmp")
    temporary.write_text(json.dumps(summary, indent=1), encoding="utf-8")
    temporary.replace(summary_path)
    return summary


def manifest(folder: Path) -> dict[str, Any] | None:
    """crc-sdk's cache manifest of a run: the crops it wrote and the checksums it recorded."""
    found = sorted((folder / "cache").rglob("*.json")) if (folder / "cache").exists() else []
    for path in found:
        document = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(document, dict) and document.get("provider") == "jrc":
            return {**document, "manifest_file": path.name}
    return None


def file_checksum(path: Path) -> str:
    """A file's checksum as crc-sdk's cache computes it."""
    from crc_sdk.workflows._remote import file_checksum as checksum

    return str(checksum(path))


def labels(folder: Path) -> dict[str, Any]:
    """Everything the canonical file says about itself: metadata, schema, file key-values."""
    import pyarrow.parquet as pq
    from crc_sdk.connectors.parquet import read_hazard_metadata

    path = folder / "hazard.parquet"
    # opened as a plain file: see the module note on pyarrow's file system and GDAL
    with path.open("rb") as handle:
        metadata = read_hazard_metadata(handle)
    with path.open("rb") as handle:
        file = pq.ParquetFile(handle)
        raw = file.schema_arrow.metadata or {}
        rows = file.metadata.num_rows
        names = list(file.schema_arrow.names)
    return {
        "metadata": json.loads(metadata.model_dump_json()),
        "columns": names,
        "file_keys": sorted(key.decode() for key in raw),
        "rows": rows,
        "bytes": path.stat().st_size,
    }


def curves(folder: Path) -> dict[str, Any]:
    """The rows of the canonical file as arrays, one entry per row, in the file's order.

    ``box`` holds west, south, east, north of each row's source pixel, read from the row's
    geometry (a five-point polygon in WKB, decoded here as numbers).
    """
    import numpy as np
    import pyarrow.parquet as pq

    names = ("hazard_name", "horizon", "pathway", "curve_kind", "curve_type", "curve_shape")
    distinct: dict[str, set[str]] = {name: set() for name in names}
    cells, boxes, locations, scales = [], [], [], []
    other_geometry = 0
    with (folder / "hazard.parquet").open("rb") as handle:
        file = pq.ParquetFile(handle)
        columns = ["cell_index", "source_geometry", "curve_location", "curve_scale", *names]
        for batch in file.iter_batches(batch_size=1 << 18, columns=columns):
            for name in names:
                distinct[name].update(str(v) for v in batch.column(name).unique().to_pylist())
            cells.append(batch.column("cell_index").to_numpy().astype(np.uint64))
            locations.append(batch.column("curve_location").to_numpy(zero_copy_only=False))
            scales.append(batch.column("curve_scale").to_numpy(zero_copy_only=False))
            geometry = batch.column("source_geometry")
            offsets = np.frombuffer(geometry.buffers()[1], dtype=np.int32)[
                geometry.offset : geometry.offset + len(geometry) + 1
            ]
            data = np.frombuffer(geometry.buffers()[2], dtype=np.uint8)
            sizes = np.diff(offsets)
            head = bytes.fromhex("01030000000100000005000000")  # one ring of five points
            if len(sizes) and (sizes == 93).all():
                block = data[offsets[0] : offsets[-1]].reshape(-1, 93)
                other_geometry += int((block[:, :13] != np.frombuffer(head, np.uint8)).any(1).sum())
                points = block[:, 13:].copy().view("<f8").reshape(-1, 5, 2)
                xs, ys = points[:, :, 0], points[:, :, 1]
                boxes.append(np.column_stack([xs.min(1), ys.min(1), xs.max(1), ys.max(1)]))
            else:
                import shapely

                other_geometry += len(sizes)
                shapes = shapely.from_wkb(geometry.to_numpy(zero_copy_only=False))
                boxes.append(shapely.bounds(shapes))
    empty = np.empty(0)
    return {
        "cell": np.concatenate(cells) if cells else empty.astype(np.uint64),
        "box": np.concatenate(boxes) if boxes else empty.reshape(0, 4),
        "location": np.concatenate(locations) if locations else empty,
        "scale": np.concatenate(scales) if scales else empty,
        "geometry_not_a_five_point_ring": other_geometry,
        "distinct": {name: sorted(values) for name, values in distinct.items()},
    }


def source_ids(folder: Path, rows: Sequence[int]) -> list[str]:
    """The ``source_id`` of the given rows (positions in the file's order)."""
    import numpy as np
    import pyarrow.parquet as pq

    wanted = np.asarray(sorted(rows), dtype=np.int64)
    found: dict[int, str] = {}
    start = 0
    with (folder / "hazard.parquet").open("rb") as handle:
        for batch in pq.ParquetFile(handle).iter_batches(batch_size=1 << 18, columns=["source_id"]):
            here = wanted[(wanted >= start) & (wanted < start + len(batch))]
            column = batch.column("source_id")
            for position in here.tolist():
                found[position] = column[position - start].as_py()
            start += len(batch)
    return [found[position] for position in rows]


def quantiles(location: Any, scale: Any, return_periods: Sequence[float]) -> Any:
    """Depths of Gumbel curves at return periods, evaluated by crc-framework.

    One row per curve, one column per return period.
    """
    import numpy as np
    from crc_framework.distributions import FittedDistribution

    probabilities = [1.0 - 1.0 / period for period in return_periods]
    out = np.empty((len(location), len(probabilities)))
    for index, (loc, sc) in enumerate(zip(location, scale, strict=True)):
        curve = FittedDistribution.from_parameters("gumbel_r", location=float(loc), scale=float(sc))
        out[index] = [curve.ppf(p) for p in probabilities]
    return out


def depths_at(folder: Path, return_period: float) -> tuple[Any, Any]:
    """Every row's cell and its curve's depth at a return period, evaluated by crc-sdk.

    The call crc-docs' ``flood_risk_by_province`` notebook makes (``curve_quantiles_at``).
    """
    import numpy as np
    import pyarrow.parquet as pq
    from crc_sdk.connectors import read_hazard_metadata
    from crc_sdk.workflows import curve_quantiles_at, return_periods_to_probabilities

    target = folder / "hazard.parquet"
    tail = read_hazard_metadata(target).return_period_tail
    probability = return_periods_to_probabilities([return_period], tail=tail)[0]
    with target.open("rb") as handle:
        table = pq.read_table(handle, columns=[
            "cell_index", "curve_kind", "curve_type", "curve_shape", "curve_location",
            "curve_scale", "curve_atom_probability", "curve_atom_location",
            "curve_probabilities", "curve_values",
        ])  # fmt: skip
    depths = np.asarray(curve_quantiles_at(table, probability, max_workers=1), dtype=float)
    return table["cell_index"].to_numpy().astype(np.uint64), depths


def source_identity(provider: str, path: str, row: int, column: int) -> str:
    """The identifier crc-sdk gives a source pixel (its own function, called as is)."""
    from crc_sdk.connectors.adapters import _source_id

    return str(_source_id(provider, path, row, column))
