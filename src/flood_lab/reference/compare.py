"""Comparisons of a loader's values with a second reader's (requirement FS4).

Pure functions on plain values (arrays, lists of dicts); they know nothing of loaders or files.
Each returns a dict with ``differences``, the total that ``outcome`` turns into "confirmed" (zero)
or "differs" (any). The two other outcomes of ``docs/validation/method.md``, "not checked" and
"not applicable", are for the caller to state when no comparison was run.
"""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from typing import Any

import numpy as np
import shapely

FIRST = 10


def compare_grids(a: Any, b: Any) -> dict[str, Any]:
    """Cell-by-cell equality of two arrays.

    Rule: shapes must be equal, then every cell must be equal (NaN equals NaN). Returns both
    shapes, the count of differing cells (every cell, if the shapes differ) and the (row, col)
    of the first ``FIRST`` in row order.
    """
    a, b = np.asarray(a), np.asarray(b)
    result: dict[str, Any] = {"shape_a": list(a.shape), "shape_b": list(b.shape)}
    if a.shape != b.shape:
        result.update(
            same_shape=False, differing_cells=None, first=[], differences=max(a.size, b.size, 1)
        )
        return result
    differ = a != b
    if a.dtype.kind == "f" and b.dtype.kind == "f":
        differ &= ~(np.isnan(a) & np.isnan(b))
    where = np.argwhere(differ)
    count = int(differ.sum())
    result.update(
        same_shape=True,
        differing_cells=count,
        first=[tuple(int(i) for i in cell) for cell in where[:FIRST]],
        differences=count,
    )
    return result


def _key_of(row: Mapping[str, Any], key: str | Sequence[str]) -> Any:
    return row[key] if isinstance(key, str) else tuple(row[k] for k in key)


def _index(rows: Iterable[Mapping[str, Any]], key: str | Sequence[str]):
    index: dict[Any, Mapping[str, Any]] = {}
    counts: Counter[Any] = Counter()
    for row in rows:
        k = _key_of(row, key)
        counts[k] += 1
        index.setdefault(k, row)
    return index, sum(n - 1 for n in counts.values() if n > 1)


def _missing(value: Any) -> bool:
    return value is None or (isinstance(value, float) and math.isnan(value))


def _equal(x: Any, y: Any) -> bool:
    if _missing(x) and _missing(y):
        return True
    return bool(x == y)


def _close(x: Any, y: Any, tolerance: float) -> bool:
    if _missing(x) or _missing(y):
        return _missing(x) and _missing(y)
    return abs(float(x) - float(y)) <= tolerance


def compare_tables(
    a: Iterable[Mapping[str, Any]],
    b: Iterable[Mapping[str, Any]],
    key: str | Sequence[str],
    exact: Sequence[str] = (),
    close: Mapping[str, float] | None = None,
    geometry: Sequence[str] = (),
) -> dict[str, Any]:
    """Row-by-row comparison of two tables matched on ``key``.

    Rules:

    * rows are matched on ``key`` (one column or several); keys found only in ``a`` or only in
      ``b`` are counted, and so is every repeated key (rows beyond the first);
    * ``exact`` columns are compared by equality (None equals None, NaN equals NaN);
    * ``close`` columns by ``|a - b| <= tolerance``, a tolerance given per column; a missing value
      equals only a missing value;
    * ``geometry`` columns hold WKB: equal bytes count as equal; where the bytes differ, shapely's
      topological ``equals`` decides, and the rows are counted apart as ``bytes_differ_equal``
      (same point set, other encoding; not a difference of value) or ``differ`` (a difference);
    * a column missing from a row raises ``KeyError``: the tables must have the same columns.
    """
    close = dict(close or {})
    index_a, repeated_a = _index(a, key)
    index_b, repeated_b = _index(b, key)
    only_a = [k for k in index_a if k not in index_b]
    only_b = [k for k in index_b if k not in index_a]
    shared = [k for k in index_a if k in index_b]
    columns: dict[str, dict[str, Any]] = {}
    for name in exact:
        bad = [k for k in shared if not _equal(index_a[k][name], index_b[k][name])]
        columns[name] = {"rule": "exact", "differ": len(bad), "first": bad[:FIRST]}
    for name, tolerance in close.items():
        bad = [k for k in shared if not _close(index_a[k][name], index_b[k][name], tolerance)]
        columns[name] = {
            "rule": f"abs <= {tolerance}",
            "differ": len(bad),
            "first": bad[:FIRST],
        }
    for name in geometry:
        recoded, bad = [], []
        for k in shared:
            x, y = index_a[k][name], index_b[k][name]
            if _missing(x) or _missing(y):
                if not (_missing(x) and _missing(y)):
                    bad.append(k)
                continue
            if bytes(x) == bytes(y):
                continue
            if shapely.equals(shapely.from_wkb(bytes(x)), shapely.from_wkb(bytes(y))):
                recoded.append(k)
            else:
                bad.append(k)
        columns[name] = {
            "rule": "WKB bytes, else topological equality",
            "bytes_differ_equal": len(recoded),
            "differ": len(bad),
            "first": bad[:FIRST],
        }
    differences = (
        len(only_a)
        + len(only_b)
        + repeated_a
        + repeated_b
        + sum(column["differ"] for column in columns.values())
    )
    return {
        "rows_a": len(index_a) + repeated_a,
        "rows_b": len(index_b) + repeated_b,
        "only_in_a": len(only_a),
        "only_in_b": len(only_b),
        "first_only_in_a": only_a[:FIRST],
        "first_only_in_b": only_b[:FIRST],
        "repeated_keys_a": repeated_a,
        "repeated_keys_b": repeated_b,
        "columns": columns,
        "differences": differences,
    }


def outcome(result: Mapping[str, Any]) -> str:
    """ "confirmed" when a comparison found nothing different, "differs" otherwise."""
    return "confirmed" if result["differences"] == 0 else "differs"
