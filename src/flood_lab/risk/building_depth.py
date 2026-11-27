"""The depth a Hazus building curve is read at, rules BD-1 to BD-5 of ``docs/flood/loss-rules.md``.

Hazus building curves are indexed by depth above the top of the finished first floor, -4 to 24 ft
(CH-25). The model gives inundation depth above ground at the building. This module turns one into
the other and says, building by building, which of three cases holds:

* ``READ``: read the curve at the returned depth;
* ``NO_LOSS``: no damage, without reading the curve;
* ``FAILED``: no loss can be computed; the building is reported, never counted as zero.

Rules (accepted by Yuri 2026-11-27, CH-29; ours, [P]):

* BD-1 dry building: depth above ground at the building of 0 or less gives ``NO_LOSS``, whatever
  the curve says at negative depths;
* BD-2 depth above first floor = depth above ground - first-floor height above grade;
* BD-3 below the curve's lowest point: a building with a basement is read at the lowest point (the
  basement curve's value at -4 ft); one without a basement gets ``NO_LOSS``; an unknown basement
  flag gives ``FAILED``;
* BD-4 above the curve's highest point: ``FAILED`` (the curve is never extrapolated);
* BD-5 no first-floor height: ``FAILED``.

numpy only; no crc import.
"""

from __future__ import annotations

from enum import IntEnum

import numpy as np
from numpy.typing import ArrayLike


class Case(IntEnum):
    READ = 0
    NO_LOSS = 1
    FAILED = 2


def curve_depth(
    depth_above_ground_m: ArrayLike,
    first_floor_m: ArrayLike,
    basement: ArrayLike,
    lowest_m: float,
    highest_m: float,
) -> tuple[np.ndarray, np.ndarray]:
    """Depth to read each building's curve at (NaN unless ``READ``) and its ``Case``.

    ``first_floor_m`` is NaN where unknown; ``basement`` holds ``"Y"``, ``"N"`` or ``""``.
    ``lowest_m`` and ``highest_m`` are the curve's first and last depth, above first floor.
    """
    depth = np.asarray(depth_above_ground_m, dtype=float)
    ffh = np.asarray(first_floor_m, dtype=float)
    flag = np.asarray(basement, dtype=object)
    if not (depth.shape == ffh.shape == flag.shape):
        raise ValueError("depth, first-floor height and basement flag differ in shape")
    if not np.all(np.isfinite(depth)):
        raise ValueError("a depth above ground is not a number")
    if not lowest_m < highest_m:
        raise ValueError("lowest_m must be below highest_m")
    if np.any(~np.isin(flag, ("Y", "N", ""))):
        raise ValueError("basement must be 'Y', 'N' or ''")
    unknown_flag = flag == ""

    case = np.full(depth.shape, Case.READ, dtype=np.int8)
    at = depth - ffh  # BD-2; NaN where the height is unknown
    case[np.isnan(ffh)] = Case.FAILED  # BD-5
    below = ~np.isnan(at) & (at < lowest_m)
    case[below & (flag == "N")] = Case.NO_LOSS  # BD-3
    case[below & unknown_flag] = Case.FAILED
    at = np.where(below & (flag == "Y"), lowest_m, at)
    case[~np.isnan(at) & (at > highest_m)] = Case.FAILED  # BD-4
    case[depth <= 0] = Case.NO_LOSS  # BD-1, last: a dry building has no loss even if unknown
    at = np.where(case == Case.READ, at, np.nan)
    return at, case
