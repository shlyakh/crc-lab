"""JRC flood maps through crc-sdk 1.x: the only code of this source that imports crc-sdk.

A read is run in a process of its own (``python -m data_source_check.adapters.crc.jrc_flood``)
so that its run time and peak memory are its own, and so that a read too large for this machine
ends that process and not the assessment. The rows go to ``rows.parquet`` and everything else
crc-sdk reported to ``run.json``; a folder that holds both is not run again.

``publisher`` names a local folder laid out as the publisher's directory. crc-sdk then reads
those files in place of the publisher's server: its decoding is exercised, its downloads are not.
The layout table that is swapped for this (``crc_sdk._providers.jrc.JRC_DATASETS``) is private.
"""

from __future__ import annotations

import json
import os
import resource
import subprocess
import sys
import time
import warnings
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
from typing import Any

PRODUCTS = ("glofas", "efas")


def facts(dataset: str) -> dict[str, Any]:
    """What crc-sdk states about a product in its own layout table."""
    from crc_sdk._providers import jrc

    entry = jrc.JRC_DATASETS[dataset]
    return {
        "base_url": entry.base_url,
        "tile_index_url": entry.tile_index_url,
        "filename_template": entry.filename_template,
        "layout": entry.layout,
        "return_periods": list(entry.available_return_periods),
        "version": entry.version,
        "units": entry.units,
    }


@contextmanager
def publisher_at(dataset: str, folder: Path | None) -> Iterator[None]:
    """Within the block crc-sdk reads ``dataset`` from a local folder (None: the publisher)."""
    from crc_sdk._providers import jrc

    if folder is None:
        yield
        return
    original = jrc.JRC_DATASETS[dataset]
    base = folder.resolve().as_uri()
    index = f"{base}/tile_extents.geojson" if original.tile_index_url else None
    jrc.JRC_DATASETS[dataset] = replace(original, base_url=base, tile_index_url=index)  # type: ignore[index]
    try:
        yield
    finally:
        jrc.JRC_DATASETS[dataset] = original  # type: ignore[index]


def _time(value: Any) -> str | None:
    return None if value is None else value.isoformat(timespec="seconds")


def _identity(identity: Any) -> dict[str, Any]:
    release = identity.release
    return {
        "provider": identity.provider,
        "product": identity.product,
        "release": None
        if release is None
        else {
            "id": release.id,
            "sha256": release.sha256,
            "retrieved_at": _time(release.retrieved_at),
        },  # fmt: skip
        "resources": [
            {
                "uri": r.uri,
                "sha256": r.sha256,
                "license": r.license,
                "attribution": r.attribution,
                "retrieved_at": _time(r.retrieved_at),
            }
            for r in identity.resources
        ],  # fmt: skip
    }


def read(dataset: str, bounds: Sequence[float], folder: Path, *,
         publisher: Path | None = None) -> dict[str, Any]:  # fmt: skip
    """One crc-sdk read of a box, in this process. Writes ``rows.parquet`` and ``run.json``."""
    import pyarrow as pa
    import pyarrow.compute as pc
    import pyarrow.parquet as pq
    from crc_sdk import JRC, Bounds

    folder.mkdir(parents=True, exist_ok=True)
    west, south, east, north = (float(v) for v in bounds)
    run: dict[str, Any] = {
        "dataset": dataset, "bounds": [west, south, east, north],
        "read_from": "a local copy of the publisher's files" if publisher else "the publisher",
        "error": "", "error_type": "", "rows": 0,
    }  # fmt: skip
    started = time.perf_counter()
    try:
        with publisher_at(dataset, publisher), warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            plan = JRC(product=JRC.Product(dataset)).select(
                area=Bounds(west=west, south=south, east=east, north=north)
            )
            result = plan.read()
        table, report = result.table, result.report
        curve = table["curve"]
        knots = pc.struct_field(curve, "quantile_curve")
        slim = pa.table({
            "support_id": table["support_id"],
            "cell_id": table["cell_id"],
            "probabilities": pc.struct_field(knots, "probabilities"),
            "values": pc.struct_field(knots, "values"),
        })  # fmt: skip
        pq.write_table(slim, folder / "rows.parquet", compression="zstd")
        kinds = pc.value_counts(pc.struct_field(curve, "kind")).to_pylist()
        run |= {
            "rows": table.num_rows,
            "columns": table.schema.names,
            "variable_ids": pc.unique(table["variable_id"]).to_pylist(),
            "scenario_ids": pc.unique(table["scenario_id"]).to_pylist(),
            "period_ids": pc.unique(table["period_id"]).to_pylist(),
            "curve_kinds": {str(k["values"]): int(k["counts"]) for k in kinds},
            "fit_present": table.num_rows - table["fit"].null_count,
            "failure_present": table.num_rows - table["failure"].null_count,
            "geometry_present": table.num_rows - table["geometry"].null_count,
            "counts": {name: int(getattr(report.counts, name))
                       for name in ("requested", "produced", "skipped", "no_data")},
            "complete": bool(report.complete), "valid": report.valid,
            "diagnostics": [
                {"code": d.code, "severity": d.severity.value, "stage": d.stage.value,
                 "message": d.message, "support_id": d.support_id}
                for d in report.diagnostics
            ],
            "identities": [_identity(i) for i in report.source_identities],
            "spatial": json.loads(result.metadata.to_json()).get("spatial"),
            "warnings": sorted({f"{w.category.__name__}: {w.message}"[:300] for w in caught
                                if w.category.__module__.startswith("crc_")}),
        }  # fmt: skip
    except Exception as error:  # noqa: BLE001  what crc-sdk raises is the result
        run |= {"error": str(error)[:1500], "error_type": type(error).__name__}
    # ru_maxrss is in bytes on macOS and in kilobytes on Linux
    scale = 1 << 20 if sys.platform == "darwin" else 1 << 10
    run |= {
        "seconds": round(time.perf_counter() - started, 2),
        "peak_memory_mb": round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / scale, 1),
    }
    temporary = folder / "run.json.tmp"
    temporary.write_text(json.dumps(run, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, folder / "run.json")
    return run


def materialize(
    dataset: str,
    bounds: Sequence[float],
    folder: Path,
    *,
    live: bool,
    publisher: Path | None = None,
    isolated: bool = True,
) -> dict[str, Any]:
    """The stored answer of a read, made first if the folder does not hold it."""
    stored = folder / "run.json"
    if not stored.exists():
        if not live and publisher is None:
            raise FileNotFoundError(f"no stored crc-sdk read in {folder}; run with --live")
        if isolated:
            request = {"dataset": dataset, "bounds": list(bounds), "folder": str(folder),
                       "publisher": None if publisher is None else str(publisher)}  # fmt: skip
            done = subprocess.run(
                [sys.executable, "-m", __name__, json.dumps(request)],
                capture_output=True, text=True, check=False,
            )  # fmt: skip
            if not stored.exists():  # the process ended without an answer (killed, out of memory)
                folder.mkdir(parents=True, exist_ok=True)
                stored.write_text(json.dumps({
                    "dataset": dataset, "bounds": list(bounds), "rows": 0,
                    "error": f"the read ended with exit code {done.returncode}: "
                             f"{done.stderr.strip()[-600:]}",
                    "error_type": "ProcessEnded",
                }, indent=1) + "\n", encoding="utf-8")  # fmt: skip
        else:
            read(dataset, bounds, folder, publisher=publisher)
    return json.loads(stored.read_text(encoding="utf-8"))


def rows(folder: Path) -> Any:
    """The rows of a stored read as an Arrow table (None if the read gave none)."""
    import pyarrow.parquet as pq

    path = folder / "rows.parquet"
    return pq.read_table(path) if path.exists() else None


if __name__ == "__main__":
    asked = json.loads(sys.argv[1])
    read(asked["dataset"], asked["bounds"], Path(asked["folder"]),
         publisher=Path(asked["publisher"]) if asked["publisher"] else None)  # fmt: skip
