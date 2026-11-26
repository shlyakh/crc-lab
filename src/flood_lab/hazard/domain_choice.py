"""F4: evidence for the transposition domain (FH5).

Storm transposition is defensible only within a region whose storm-producing factors are alike
(Chow 1964, as quoted in RainyDay's tutorial). RainyDay's guidance gives no number for "alike", so
this module measures one: the mean annual maximum 1-hour and 3-hour rainfall from AORC v1.1
(2002 to the last complete year), smoothed over a square of ``SMOOTH_KM``, relative to its value
at the study area. A candidate rectangle is scored by the share of its valid pixels within
``BAND`` of the study area's value, and by its share of pixels without data (open sea, where AORC
has no values and no storm can be found).

Inputs: ``data/cache/flood/f4/ams/ams_<year>.npz`` from ``tools/flood/f4_aorc_ams.py``.
Output: ``data/cache/flood/f4/domain/domain.json`` (numbers) and ``domain_maps.npz`` (smoothed
ratio maps, for the figure). The choice itself is made by the coordinator from these numbers and
written in the F4 report.

    uv run python -m flood_lab.hazard.domain_choice
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import numpy as np
from scipy.ndimage import uniform_filter

ROOT = Path(__file__).resolve().parents[3]
AMS = ROOT / "data" / "cache" / "flood" / "f4" / "ams"
OUT = ROOT / "data" / "cache" / "flood" / "f4" / "domain"

#: the study square in geographic coordinates (corners of SQUARE, EPSG:32618, reprojected)
BOX = {"lat": (40.6865, 40.7230), "lon": (-73.9882, -73.9403)}
#: [P] smoothing square for a pixel's climate; single pixels are noisy over 24 years
SMOOTH_KM = 25.0
BAND = 0.15  # [P] a pixel is "alike" within +-15% of the study area's smoothed value
#: candidate rectangles (lat_min, lat_max, lon_min, lon_max) [P]; all inside the download window
CANDIDATES = {
    "A_coastal_small": (39.8, 41.4, -75.0, -72.4),
    "B_coastal_medium": (39.3, 41.6, -75.6, -71.8),
    "C_coastal_large": (38.8, 42.0, -76.5, -71.0),
    "D_window_all": (38.0, 44.0, -78.5, -69.5),
    "E_nyc_bight": (40.0, 41.3, -74.8, -72.6),
}


def load() -> tuple[np.ndarray, np.ndarray, dict[str, np.ndarray], list[int]]:
    files = sorted(AMS.glob("ams_*.npz"))
    years = [int(f.stem.split("_")[1]) for f in files]
    stacks: dict[str, list[np.ndarray]] = {"max1": [], "max3": [], "max6": []}
    lat = lon = None
    for f in files:
        z = np.load(f)
        lat, lon = z["lat"], z["lon"]
        for k in stacks:
            stacks[k].append(z[k])
    return lat, lon, {k: np.stack(v) for k, v in stacks.items()}, years


def smoothed_mean(stack: np.ndarray, px: int) -> np.ndarray:
    """Mean over years, then a moving mean over px x px pixels that ignores pixels without data."""
    mean = np.nanmean(stack, axis=0) if np.isfinite(stack).any() else stack[0]
    valid = np.isfinite(stack).all(axis=0)
    filled = np.where(valid, mean, 0.0)
    num = uniform_filter(filled, px, mode="constant")
    den = uniform_filter(valid.astype(float), px, mode="constant")
    out = np.where(valid & (den > 0.5), num / np.maximum(den, 1e-9), np.nan)
    return out


def box_value(field: np.ndarray, lat: np.ndarray, lon: np.ndarray) -> float:
    iy = (lat >= BOX["lat"][0]) & (lat <= BOX["lat"][1])
    ix = (lon >= BOX["lon"][0]) & (lon <= BOX["lon"][1])
    return float(np.nanmean(field[np.ix_(iy, ix)]))


def score(ratio: np.ndarray, lat: np.ndarray, lon: np.ndarray, rect: tuple) -> dict:
    iy = (lat >= rect[0]) & (lat <= rect[1])
    ix = (lon >= rect[2]) & (lon <= rect[3])
    r = ratio[np.ix_(iy, ix)]
    valid = np.isfinite(r)
    v = r[valid]
    return {
        "pixels": int(r.size),
        "share_without_data": round(float(1 - valid.mean()), 4),
        "share_within_band": round(float((np.abs(v - 1) <= BAND).mean()), 4),
        "ratio_p05": round(float(np.percentile(v, 5)), 3),
        "ratio_median": round(float(np.median(v)), 3),
        "ratio_p95": round(float(np.percentile(v, 95)), 3),
    }


def main() -> None:
    lat, lon, st, years = load()
    dy_km = float(np.mean(np.diff(lat))) * 111.2
    px = max(3, int(round(SMOOTH_KM / dy_km)) | 1)
    result: dict = {
        "years": years,
        "smooth_km": SMOOTH_KM,
        "smooth_px": px,
        "band": BAND,
        "box": BOX,
        "rule": (
            "a pixel enters only if it has data in every year; missing hours inside a year count "
            "as no rain (2002 and 2003 have such gaps, up to 48 hours)"
        ),
        "durations": {},
    }
    maps = {"lat": lat, "lon": lon}
    for k in ("max1", "max3", "max6"):
        sm = smoothed_mean(st[k], px)
        site = box_value(sm, lat, lon)
        raw_site = box_value(np.nanmean(st[k], axis=0), lat, lon)
        ratio = sm / site
        maps[f"ratio_{k}"] = ratio.astype(np.float32)
        result["durations"][k] = {
            "site_smoothed_mean_annual_max_mm": round(site, 2),
            "site_box_mean_annual_max_mm": round(raw_site, 2),
            "candidates": {
                name: score(ratio, lat, lon, rect) | {"rect": rect}
                for name, rect in CANDIDATES.items()
            },
        }
    OUT.mkdir(parents=True, exist_ok=True)
    tmp = OUT / "domain.json.tmp"
    tmp.write_text(json.dumps(result, indent=1))
    os.replace(tmp, OUT / "domain.json")
    np.savez_compressed(OUT / "domain_maps.npz", **maps)
    print(json.dumps(result, indent=1))


if __name__ == "__main__":
    main()
