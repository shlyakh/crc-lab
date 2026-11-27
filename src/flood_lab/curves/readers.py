"""F6: substation damage curves (FR1, FR2), read from sources or computed from stated parameters.

* ``read_nirandjan_f2``: curves F2.1 to F2.3 of Nirandjan et al. 2024 (Zenodo 13889558 v1.1.0,
  Table D2, sheet ``F_Vuln_Depth``), read point by point from the workbook. The file's sha256 must
  equal the ``[[file]]`` entry of ``facts/substation-curves-nirandjan.toml``.
* ``bor_expected_damage`` and ``bor_curve``: the expected damage ratio of the lognormal fragility
  curves of Bor et al. 2026 (arXiv 2605.23053v1, Table 1, flood row, HV >345 kV anchored); the
  parameters are stated by the source **[S]**, the expected ratio is our calculation **[I]**.

No crc import here (``tests/flood/test_package_rules.py``): numpy, openpyxl and the stdlib only.
"""

from __future__ import annotations

import hashlib
import math
import tomllib
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from numpy.typing import ArrayLike

from .. import paths

FOOT_M = 0.3048  # international foot, exact by definition

NIRANDJAN_FACTS = "substation-curves-nirandjan.toml"
NIRANDJAN_SHEET = "F_Vuln_Depth"
NIRANDJAN_IDS = ("F2.1", "F2.2", "F2.3")
NIRANDJAN_SOURCE = (
    "Nirandjan et al. 2024, Zenodo 13889558 v1.1.0, "
    "Table_D2_Hazard_Fragility_and_Vulnerability_Curves_V1.1.0.xlsx sheet F_Vuln_Depth"
)
_ID_ROW = 1  # row holding the curve ids ("ID number" in column A)
_HEADER_ROW = 5  # row holding "Depth (m)" and "Damage factor"
_FIRST_DATA_ROW = 6

#: Bor et al. 2026, arXiv 2605.23053v1, Table 1, flood row, substation HV >345 kV anchored [S]:
#: (damage state, median depth theta in m, dispersion beta, damage ratio)
BOR_CITATION = "Bor et al. 2026, arXiv 2605.23053v1, Table 1, flood row, HV >345 kV anchored"
BOR_STATES: tuple[tuple[str, float, float, float], ...] = (
    ("slight", 0.50, 0.40, 0.05),
    ("moderate", 1.00, 0.40, 0.20),
    ("extensive", 1.50, 0.40, 0.50),
    ("complete", 3.00, 0.40, 1.00),
)


@dataclass(frozen=True)
class SourceFile:
    """A file that was read, for the record."""

    path: str
    sha256: str
    bytes: int


@dataclass(frozen=True)
class PointCurve:
    """A damage curve as points: linear between them, nothing outside them."""

    id: str
    depth_m: tuple[float, ...]  # strictly increasing, metres, in the curve's native datum
    ratio: tuple[float, ...]  # damage as a fraction 0..1
    datum: str  # "above ground" or "above first floor"
    source: str
    tag: str  # "S" read as published, "I" converted or computed, "P" our construction
    note: str = ""

    def __post_init__(self) -> None:
        if len(self.depth_m) != len(self.ratio) or len(self.depth_m) < 2:
            raise ValueError(f"{self.id}: needs two or more (depth, ratio) pairs of equal length")
        if any(b <= a for a, b in zip(self.depth_m, self.depth_m[1:], strict=False)):
            raise ValueError(f"{self.id}: depths are not strictly increasing")
        if any(not (0.0 <= r <= 1.0) for r in self.ratio):
            raise ValueError(f"{self.id}: a ratio lies outside 0..1")
        if self.datum not in ("above ground", "above first floor"):
            raise ValueError(f"{self.id}: unknown datum {self.datum!r}")
        if self.tag not in ("S", "I", "P"):
            raise ValueError(f"{self.id}: tag must be S, I or P, not {self.tag!r}")


# --- files and checksums -------------------------------------------------------------------------


def _file_entries(facts_file: str) -> list[dict]:
    with open(paths.FACTS / facts_file, "rb") as f:
        return tomllib.load(f).get("file", [])


def source_file(path: Path) -> SourceFile:
    """sha256 and size of a file, as read now."""
    data = Path(path).read_bytes()
    return SourceFile(str(path), hashlib.sha256(data).hexdigest(), len(data))


def verified(path: Path, facts_file: str) -> SourceFile:
    """The file's record, after checking it against the ``[[file]]`` entry of the same name.

    Raises ``ValueError`` when the facts file has no entry for it, or when its sha256 or size
    differs from the entry.
    """
    path = Path(path)
    entries = [e for e in _file_entries(facts_file) if Path(e["path"]).name == path.name]
    if len(entries) != 1:
        raise ValueError(f"{facts_file} has {len(entries)} [[file]] entries named {path.name}")
    entry = entries[0]
    got = source_file(path)
    if got.sha256 != entry["sha256"] or got.bytes != entry["bytes"]:
        raise ValueError(
            f"{path}: sha256 {got.sha256} ({got.bytes} bytes) differs from {facts_file} "
            f"({entry['sha256']}, {entry['bytes']} bytes)"
        )
    return got


# --- Nirandjan et al. 2024 -----------------------------------------------------------------------


def _column_letter(index: int) -> str:
    from openpyxl.utils import get_column_letter

    return get_column_letter(index + 1)


def _read_f2_sheet(path: Path, ids: tuple[str, ...] = NIRANDJAN_IDS) -> dict[str, PointCurve]:
    """Parse the curves ``ids`` from sheet F_Vuln_Depth, without the checksum check.

    The depth column is the one headed "Depth (m)" in row 5 (column A in v1.1.0); each curve's
    column is found by its id in row 1 and must be headed "Damage factor" in row 5. Points run from
    row 6 to the last populated cell of the curve's column; an empty cell between populated ones, a
    missing depth, or a depth with no curve value before the end is an error.
    """
    import openpyxl

    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    try:
        rows = list(wb[NIRANDJAN_SHEET].iter_rows(values_only=True))
    finally:
        wb.close()
    id_row, header = rows[_ID_ROW - 1], rows[_HEADER_ROW - 1]
    depth_cols = [
        i for i, v in enumerate(header) if isinstance(v, str) and v.strip() == "Depth (m)"
    ]
    if len(depth_cols) != 1:
        raise ValueError(f"{path}: expected one 'Depth (m)' column in row 5, found {depth_cols}")
    dcol = depth_cols[0]
    data = rows[_FIRST_DATA_ROW - 1 :]
    curves = {}
    for cid in ids:
        cols = [i for i, v in enumerate(id_row) if isinstance(v, str) and v.strip() == cid]
        if len(cols) != 1:
            raise ValueError(f"{path}: curve id {cid} found {len(cols)} times in row 1")
        col = cols[0]
        if str(header[col]).strip() != "Damage factor":
            raise ValueError(
                f"{path}: column of {cid} is headed {header[col]!r}, not Damage factor"
            )
        values = [r[col] if col < len(r) else None for r in data]
        filled = [k for k, v in enumerate(values) if v is not None]
        if not filled:
            raise ValueError(f"{path}: curve {cid} has no values")
        last = filled[-1]
        depth, ratio = [], []
        for k in range(last + 1):
            d, v = data[k][dcol], values[k]
            if d is None or v is None:
                raise ValueError(f"{path}: {cid} row {_FIRST_DATA_ROW + k}: empty depth or value")
            depth.append(float(d))
            ratio.append(float(v))
        letter = _column_letter(col)
        curves[cid] = PointCurve(
            id=f"nirandjan_{cid}",
            depth_m=tuple(depth),
            ratio=tuple(ratio),
            datum="above ground",
            source=(
                f"{NIRANDJAN_SOURCE}, column {cid} (column {letter}, depth column "
                f"{_column_letter(dcol)}, rows {_FIRST_DATA_ROW}-{_FIRST_DATA_ROW + last})"
            ),
            tag="S",
            note=(
                f"{len(depth)} points read as published; the source gives no values above "
                f"{depth[-1]} m"
            ),
        )
    return curves


def read_nirandjan_f2(path: Path) -> tuple[dict[str, PointCurve], SourceFile]:
    """Curves F2.1, F2.2, F2.3 (substations: low, medium, high voltage), keyed by id, tag S.

    The file's sha256 and size must equal the ``[[file]]`` entry of
    ``substation-curves-nirandjan.toml``; else ``ValueError``.
    """
    record = verified(path, NIRANDJAN_FACTS)
    return _read_f2_sheet(Path(path)), record


# --- Bor et al. 2026 -----------------------------------------------------------------------------


def _ndtr(x: np.ndarray) -> np.ndarray:
    """Standard normal CDF."""
    erf = np.vectorize(math.erf, otypes=[float])
    return 0.5 * (1.0 + erf(x / math.sqrt(2.0)))


def _exceedance(depth: np.ndarray) -> np.ndarray:
    """P(DS >= k | d) for the four states, shape ``depth.shape + (4,)``; 0 where d == 0."""
    out = np.zeros(depth.shape + (len(BOR_STATES),))
    wet = depth > 0
    for k, (_, theta, beta, _) in enumerate(BOR_STATES):
        out[wet, k] = _ndtr(np.log(depth[wet] / theta) / beta)
    return out


def bor_expected_damage(depth_m: ArrayLike) -> np.ndarray:
    """Expected damage ratio E(d) = sum_k [P(DS>=k|d) - P(DS>=k+1|d)] * dr_k, P(DS>=5) = 0.

    With P(DS>=k|d) = Phi(ln(d/theta_k)/beta_k) from ``BOR_STATES`` [S]; E(0) = 0. The four
    curves share one beta and their thetas increase, so they do not cross and the differences are
    the probabilities of each state; this is asserted at every depth. A negative or non-finite
    depth is an error.
    """
    d = np.asarray(depth_m, dtype=float)
    if not np.all(np.isfinite(d)) or np.any(d < 0):
        raise ValueError("depths must be finite and >= 0 m")
    p = _exceedance(d)
    if np.any(np.diff(p, axis=-1) > 0):
        raise AssertionError("P(DS>=k) increases with k: the fragility curves cross")
    p_next = np.concatenate([p[..., 1:], np.zeros(d.shape + (1,))], axis=-1)
    dr = np.array([s[3] for s in BOR_STATES])
    return ((p - p_next) * dr).sum(axis=-1)


def _grid(max_depth_m: float, step_m: float) -> np.ndarray:
    if step_m <= 0 or max_depth_m <= 0:
        raise ValueError("max_depth_m and step_m must be > 0")
    n = round(max_depth_m / step_m)
    if abs(n * step_m - max_depth_m) > 1e-9:
        raise ValueError(f"max_depth_m {max_depth_m} is not a multiple of step_m {step_m}")
    return np.arange(n + 1) * step_m


def bor_interpolation_error(max_depth_m: float, step_m: float) -> float:
    """Largest |linear interpolation of the table - exact E(d)| on a grid 10 times finer."""
    coarse = _grid(max_depth_m, step_m)
    fine = np.arange(10 * (len(coarse) - 1) + 1) * (step_m / 10)
    fine[-1] = coarse[-1]
    approx = np.interp(fine, coarse, bor_expected_damage(coarse))
    return float(np.max(np.abs(approx - bor_expected_damage(fine))))


def bor_curve(max_depth_m: float, step_m: float) -> PointCurve:
    """``bor_expected_damage`` tabulated at 0, step, ..., max_depth_m; tag I (our calculation)."""
    depth = _grid(max_depth_m, step_m)
    ratio = bor_expected_damage(depth)
    err = bor_interpolation_error(max_depth_m, step_m)
    return PointCurve(
        id="bor_hv345_anchored",
        depth_m=tuple(float(x) for x in depth),
        ratio=tuple(float(x) for x in ratio),
        datum="above ground",
        source=(
            f"{BOR_CITATION}: medians, dispersions and damage ratios [S]; expected damage ratio "
            "computed by flood_lab.curves.readers.bor_expected_damage [I]"
        ),
        tag="I",
        note=(
            f"tabulated every {step_m} m to {max_depth_m} m; largest |linear interpolation - "
            f"exact formula| on a grid 10 times finer: {err:.3g} [I]"
        ),
    )
