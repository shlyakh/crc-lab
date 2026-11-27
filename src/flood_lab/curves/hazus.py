"""F6: Hazus building depth-damage functions (FR3), as SPHERE and FEMA's FAST tool ship them.

Primary copy (values): SPHERE, github.com/Niyam-Projects/sphere, commit
2967fe660981a185579d6257c3d9df341b695687, folder ``packages/data/src/sphere/data``, files
``flBldgDmgFn.csv`` (structure library), ``flContDmgFn.csv``, ``flInvDmgFn.csv`` and
``flDmgXRef.csv`` (default assignment); MIT licence (NiyamIT, Inc.); the values are FEMA Hazus
data. Columns ft04m..ft01m, ft00..ft24: -4 to 24 ft in 1 ft steps. Checked against
``facts/sphere-hazus-data.toml``.

Cross-check and listed alternative: the Hazus 4.0 lookup tables in FAST
(github.com/nhrap-hazus/FAST, commit 8e285a9daf7bc762c171c68fb81c4daeedf46efc, folder
``Lookuptables``; GPL-3.0); columns m4..m1, p0..p24. Every FAST structure row has the same id and
the same 29 values in SPHERE (``sphere-hazus-data.toml``, fact ``equal_to_fast``). Checked
against ``facts/hazus-flood-functions.toml``.

Depth is in feet above the top of the finished first floor, damage in percent.

``assign_structure_curve`` reproduces FAST's own default assignment: hazpy commit
a207732fdb08723d91c34d4671f4770286f8a962, ``hazpy/flood/modules/UDF.py`` lines 320-325 (a record
with an empty required field is not processed), 393-418 (the Specific Occupancy ID from occupancy,
stories and foundation type) and 591-620 (the first LUT row with that ID gives the DDF_ID; no row,
"Unmatched"). ``sphere_structure_curve`` reproduces SPHERE's cross-reference match
(``packages/flood/src/sphere/flood/default_vulnerability.py`` at the commit above, lines 116,
154-163 and 194-222). Which one the build uses is stated in ``build.py``.

No crc import here (``tests/flood/test_package_rules.py``).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from .readers import FOOT_M, PointCurve, verified

HAZUS_FACTS = "hazus-flood-functions.toml"
FAST_COMMIT = "8e285a9"
FAST_COMMIT_FULL = "8e285a9daf7bc762c171c68fb81c4daeedf46efc"
DEPTH_FT: tuple[int, ...] = tuple(range(-4, 25))
DEPTH_COLUMNS: tuple[str, ...] = tuple(f"m{-d}" if d < 0 else f"p{d}" for d in DEPTH_FT)
#: id column of each FAST library, as spelt in the files
ID_COLUMNS = {"BldgDmgFnID": "struct", "ContDmgFnId": "cont", "InvDmgFnId": "inv"}
_LUT_REQUIRED = ("Occupancy", "SpecificOccupId", "DDF_ID", *DEPTH_COLUMNS)

SPHERE_FACTS = "sphere-hazus-data.toml"
SPHERE_COMMIT = "2967fe6"
SPHERE_COMMIT_FULL = "2967fe660981a185579d6257c3d9df341b695687"
SPHERE_DATA_DIR = "packages/data/src/sphere/data"
SPHERE_DEPTH_COLUMNS: tuple[str, ...] = tuple(
    f"ft{-d:02d}m" if d < 0 else f"ft{d:02d}" for d in DEPTH_FT
)
#: id column and kind of each SPHERE library
SPHERE_LIBRARIES = {
    "flBldgDmgFn.csv": ("BldgDmgFnId", "struct"),
    "flContDmgFn.csv": ("ContDmgFnId", "cont"),
    "flInvDmgFn.csv": ("InvDmgFnId", "inv"),
}
_XREF_COLUMNS = (
    "BldgDmgFnId",
    "ContDmgFnId",
    "InvDmgFnId",
    "Occupancy",
    "Basement",
    "StoriesMin",
    "StoriesMax",
    "HazardR",
    "HazardCA",
    "HazardCV",
)


@dataclass(frozen=True)
class HazusCurve:
    """One row of a FAST depth-damage library, as in the file."""

    ddf_id: int
    occupancy: str
    source: str  # the row's Source column, e.g. "USACE - IWR"
    description: str
    depth_ft: tuple[int, ...]  # -4 .. 24 (m4..m1, p0..p24)
    percent: tuple[float, ...]  # 0..100
    library: str = "flBldgStructDmgFn.csv"  # the file the row was read from
    origin: str = "fast"  # "fast" or "sphere"

    @property
    def kind(self) -> str:
        """``struct``, ``cont`` or ``inv``."""
        if self.origin == "sphere":
            return SPHERE_LIBRARIES[self.library][1]
        return {"flBldgContDmgFn.csv": "cont", "flBldgInvDmgFn.csv": "inv"}.get(
            self.library, "struct"
        )

    def to_points(self) -> PointCurve:
        """Metres (ft * FOOT_M) and ratio (percent / 100) above first floor; tag I (conversion)."""
        if self.origin == "sphere":
            comment = f"; comment: {self.description}" if self.description else ""
            source = (
                f"SPHERE (NiyamIT, MIT licence; FEMA Hazus data), commit {SPHERE_COMMIT}, "
                f"{SPHERE_DATA_DIR}/{self.library}, row id {self.ddf_id} "
                f"({self.source}{comment})"
            )
        else:
            source = (
                f"FEMA FAST (Hazus 4.0 lookup tables, GPL-3.0), commit {FAST_COMMIT}, "
                f"Lookuptables/{self.library}, row id {self.ddf_id} ({self.occupancy}, "
                f"{self.source}: {self.description})"
            )
        return PointCurve(
            id=f"hazus_{self.kind}_{self.ddf_id}",
            depth_m=tuple(d * FOOT_M for d in self.depth_ft),
            ratio=tuple(p / 100.0 for p in self.percent),
            datum="above first floor",
            source=source,
            tag="I",
            note="feet to metres and percent to fraction; values as published at 1 ft steps",
        )


def _id_column(columns: list[str] | pd.Index) -> str:
    found = [c for c in ID_COLUMNS if c in columns]
    if len(found) != 1:
        raise ValueError(f"expected one id column of {list(ID_COLUMNS)}, found {found}")
    return found[0]


def _parse_library(path: Path) -> dict[int, HazusCurve]:
    """Parse a FAST library without the checksum check."""
    path = Path(path)
    df = pd.read_csv(path, dtype=str, keep_default_na=False)
    idc = _id_column(df.columns)
    missing = [c for c in ("Occupancy", "Source", "Description", *DEPTH_COLUMNS) if c not in df]
    if missing:
        raise ValueError(f"{path}: columns missing: {missing}")
    out: dict[int, HazusCurve] = {}
    for row in df.itertuples(index=False):
        rec = dict(zip(df.columns, row, strict=True))
        ddf_id = int(rec[idc])
        if ddf_id in out:
            raise ValueError(f"{path}: id {ddf_id} appears twice")
        percent = tuple(float(rec[c]) for c in DEPTH_COLUMNS)
        if any(not (0.0 <= p <= 100.0) for p in percent):
            raise ValueError(f"{path}: id {ddf_id} has a percentage outside 0..100")
        out[ddf_id] = HazusCurve(
            ddf_id=ddf_id,
            occupancy=rec["Occupancy"].strip(),
            source=rec["Source"].strip(),
            description=rec["Description"].strip(),
            depth_ft=DEPTH_FT,
            percent=percent,
            library=path.name,
        )
    return out


def read_library(path: Path) -> dict[int, HazusCurve]:
    """A FAST library (flBldgStructDmgFn.csv, flBldgContDmgFn.csv or flBldgInvDmgFn.csv) by id.

    The id column (BldgDmgFnID, ContDmgFnId or InvDmgFnId) is detected. The file must match its
    ``[[file]]`` entry in ``hazus-flood-functions.toml``; else ``ValueError``.
    """
    verified(path, HAZUS_FACTS)
    return _parse_library(path)


def _parse_assignment(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path, dtype={"Occupancy": str, "SpecificOccupId": str, "Source": str})
    missing = [c for c in _LUT_REQUIRED if c not in df.columns]
    if missing:
        raise ValueError(f"{path}: columns missing: {missing}")
    return df


def read_assignment(path: Path) -> pd.DataFrame:
    """A FAST default-assignment table, e.g. Building_DDF_Riverine_LUT_Hazus4p0.csv, as in the file.

    The file must match its ``[[file]]`` entry in ``hazus-flood-functions.toml``; else
    ``ValueError``.
    """
    verified(path, HAZUS_FACTS)
    return _parse_assignment(path)


def specific_occupancy_id(occupancy: str, stories: float, basement: bool) -> str:
    """FAST's Specific Occupancy ID (hazpy a207732, flood/modules/UDF.py lines 393-418).

    Prefix ``OC[:1] + OC[-(len(OC)-3):]`` (REL1 gives ``RE1``); middle: RES3 ``5`` above 4
    stories, ``3`` above 2, else ``1``; RES1 stories capped at 3, the integer, or ``S`` (split
    level) if not an integer; RES2 ``1``; all others ``H`` above 6, ``M`` above 3, else ``L``;
    suffix ``B`` for a basement (foundation type 4), else ``N``.
    """
    oc = occupancy
    sopre = oc[:1] + oc[-(len(oc) - 3) :] if oc != "REL1" else "RE1"
    sosuf = "B" if basement else "N"
    n = float(stories)
    if oc[:4] == "RES3":
        somid = "5" if n > 4 else "3" if n > 2 else "1"
    elif oc[:4] == "RES1":
        n = 3 if n > 3.0 else n
        somid = str(round(n)) if n - round(n) == 0 else "S"
    elif oc[:4] == "RES2":
        somid = "1"
    else:
        somid = "H" if n > 6 else "M" if n > 3 else "L"
    return sopre + somid + sosuf


def assign_structure_curve(
    lut: pd.DataFrame, occupancy: str, stories: int | None, basement: bool | None
) -> int | None:
    """The DDF_ID FAST assigns by default to a structure (riverine LUT), or None.

    None where FAST assigns nothing: an empty occupancy, stories or basement flag (FAST skips the
    record, UDF.py lines 320-325), or a Specific Occupancy ID with no LUT row (FAST marks it
    "Unmatched", lines 610-620), as for NSI occtypes with suffixes such as "RES1-2SWB". The
    occupancy is stripped of surrounding spaces, as FAST's ``getValue`` does (line 328).
    """
    if occupancy is None or stories is None or basement is None:
        return None
    oc = str(occupancy).strip()
    if oc == "":
        return None
    soid = specific_occupancy_id(oc, stories, basement)
    hits = lut.loc[lut["SpecificOccupId"].astype(str) == soid, "DDF_ID"]
    if hits.empty:
        return None
    return int(hits.iloc[0])  # FAST takes the first matching row (break, line 609)


def lut_library_mismatches(lut: pd.DataFrame, library: dict[int, HazusCurve]) -> list[str]:
    """Rows of an assignment table whose 29 values differ from the library row with its DDF_ID."""
    faults = []
    for _, row in lut.iterrows():
        ddf_id = int(row["DDF_ID"])
        curve = library.get(ddf_id)
        if curve is None:
            faults.append(f"{row['SpecificOccupId']}: DDF_ID {ddf_id} not in the library")
            continue
        values = tuple(float(row[c]) for c in DEPTH_COLUMNS)
        if values != curve.percent:
            faults.append(f"{row['SpecificOccupId']}: values differ from library row {ddf_id}")
    return faults


# --- SPHERE --------------------------------------------------------------------------------------


def _parse_sphere_library(path: Path) -> dict[int, HazusCurve]:
    """Parse a SPHERE library (UTF-8 with BOM) without the checksum check.

    A row whose last depth cells are empty (flBldgDmgFn.csv rows 740-743 stop at 16 ft) keeps the
    points up to its last value; an empty cell between two values is an error.
    """
    path = Path(path)
    if path.name not in SPHERE_LIBRARIES:
        raise ValueError(f"{path}: not a SPHERE library name ({list(SPHERE_LIBRARIES)})")
    idc = SPHERE_LIBRARIES[path.name][0]
    df = pd.read_csv(path, dtype=str, keep_default_na=False, encoding="utf-8-sig")
    missing = [c for c in (idc, "Source", *SPHERE_DEPTH_COLUMNS, "Comment") if c not in df]
    if missing:
        raise ValueError(f"{path}: columns missing: {missing}")
    out: dict[int, HazusCurve] = {}
    for row in df.itertuples(index=False):
        rec = dict(zip(df.columns, row, strict=True))
        ddf_id = int(rec[idc])
        if ddf_id in out:
            raise ValueError(f"{path}: id {ddf_id} appears twice")
        cells = [rec[c].strip() for c in SPHERE_DEPTH_COLUMNS]
        n = len(cells)
        while n and cells[n - 1] == "":
            n -= 1
        if n == 0 or any(c == "" for c in cells[:n]):
            raise ValueError(f"{path}: id {ddf_id} has an empty depth cell")
        percent = tuple(float(c) for c in cells[:n])
        if any(not (0.0 <= p <= 100.0) for p in percent):
            raise ValueError(f"{path}: id {ddf_id} has a percentage outside 0..100")
        out[ddf_id] = HazusCurve(
            ddf_id=ddf_id,
            occupancy="",  # SPHERE's libraries have no occupancy column
            source=rec["Source"].strip(),
            description=rec["Comment"].strip(),
            depth_ft=DEPTH_FT[:n],
            percent=percent,
            library=path.name,
            origin="sphere",
        )
    return out


def read_sphere_library(path: Path) -> dict[int, HazusCurve]:
    """A SPHERE library (flBldgDmgFn.csv, flContDmgFn.csv or flInvDmgFn.csv) by id.

    The file must match its ``[[file]]`` entry in ``sphere-hazus-data.toml``; else ``ValueError``.
    """
    verified(path, SPHERE_FACTS)
    return _parse_sphere_library(path)


def _parse_sphere_xref(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path, dtype={"Occupancy": str}, encoding="utf-8-sig")
    missing = [c for c in _XREF_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"{path}: columns missing: {missing}")
    return df


def read_sphere_xref(path: Path) -> pd.DataFrame:
    """SPHERE's damage-function cross-reference flDmgXRef.csv, as in the file.

    The file must match its ``[[file]]`` entry in ``sphere-hazus-data.toml``; else ``ValueError``.
    """
    verified(path, SPHERE_FACTS)
    return _parse_sphere_xref(path)


def sphere_structure_matches(
    xref: pd.DataFrame,
    occupancy: str,
    stories: float | None,
    basement: bool | None,
    hazard: str = "R",
) -> list[int]:
    """BldgDmgFnId of every cross-reference row that matches, in file order.

    SPHERE's rule (default_vulnerability.py at commit 2967fe6): occupancy equal to ``Occupancy``
    (no stripping), basement flag equal to ``Basement`` (1 for foundation type ``B`` or ``4``,
    line 116), ``StoriesMin <= stories < StoriesMax`` and ``Hazard<hazard> == 1`` (lines
    154-163, again 204-213). An empty field matches nothing here.
    """
    if occupancy is None or stories is None or basement is None:
        return []
    s = float(stories)
    hit = (
        (xref["Occupancy"].astype(str) == str(occupancy))
        & (xref["Basement"].astype(int) == int(bool(basement)))
        & (xref["StoriesMin"] <= s)
        & (s < xref["StoriesMax"])
        & (xref[f"Hazard{hazard}"] == 1)
    )
    return [int(i) for i in xref.loc[hit, "BldgDmgFnId"]]


def sphere_structure_curve(
    xref: pd.DataFrame, occupancy: str, stories: float | None, basement: bool | None
) -> int | None:
    """The riverine structure curve SPHERE's pandas path assigns, or None.

    The first matching row (``argmax``, lines 216-219); no match gives 0 in SPHERE (line 222),
    None here. SPHERE's DuckDB path instead averages over all matching rows with weight
    1/count (lines 425-448, weight line 429) and, with no match, falls back to the first row
    of the same four-letter occupancy prefix (lines 460-488); neither is reproduced.
    """
    ids = sphere_structure_matches(xref, occupancy, stories, basement)
    return ids[0] if ids else None
