"""The substation damage-curve envelope (FR1, FR2; CH-27) and the rules that complete each curve.

Four curve families, never one curve (FR2):

* ``low``: Nirandjan et al. 2024 F2.1-F2.3, the Hazus-type curve (identical for the three voltage
  classes), read from the spreadsheet; it stops at 3.05 m.
* ``high``: Williams et al. 2025, Data S4, the aggregated "maximum hazard condition" points of the
  component matching the asset's voltage tier; ``williams_min`` is the minimum-hazard-condition
  curve of the same component, kept beside it.
* ``bor``: Bor et al. 2026, the expected damage ratio of the lognormal fragility set, tabulated.

Rules that are ours and placeholders [P] (CH-27, accepted by Yuri 2026-11-27, and FR1):

* every table runs from 0 m to ``MAX_DEPTH_M``; a modelled depth above it is an error that a
  test against the catalogue must catch;
* a curve whose source stops short of ``MAX_DEPTH_M`` holds its last value from there on;
* Williams has no point at 0 m: the curve is 0 at 0 m and linear to the 0.5 m point;
* depth is read as inundation depth above ground (no datum is stated by Williams; Nirandjan and
  Bor are depth above ground);
* Williams names three substation components but gives no voltages, so each asset is matched
  to one by its role (C-5, Yuri 2026-11-28): an OpenStreetMap ``substation=transmission`` site
  takes "grid exit point" and a ``substation=distribution`` site (Con Edison's area substations)
  takes "substation"; Williams's "distribution substation" (labelled "low-voltage substation",
  p. 6) is used for none of the study's assets. Hazus's voltage classes (Hazus 7.0
  Inventory TM p. 9-15: high 350 kV and above, medium 150-350 kV, low 34.5-150 kV) are kept as
  the sensitivity basis ``hazus_kv``: on it the 345 kV Farragut site is "medium" and the 138 kV
  sites "low".

No crc import here: the tables go to CRC through ``flood_lab.risk.crc_adapter``.
"""

from __future__ import annotations

from pathlib import Path

from flood_lab.curves.readers import PointCurve, bor_curve, read_nirandjan_f2

#: the largest depth every substation table reaches, metres [P]. The deepest value read so far
#: is 5.84 m in any 5 m cell and 0.51 m at a substation, over the 162 runs kept on 2026-11-27,
#: before the CH-26 rerun; the test against the final catalogue decides whether it holds.
MAX_DEPTH_M = 6.0
#: step of the tabulated Bor curve, metres [P]; its interpolation error is in the curve's note
BOR_STEP_M = 0.01

#: Hazus 7.0 Inventory Technical Manual (June 2025) p. 9-15, voltage classes [S]:
#: high 350 kV and above, medium 150-350 kV, low 34.5-150 kV
HAZUS_TIERS_KV = (("high", 350.0), ("medium", 150.0), ("low", 34.5))
#: Williams et al. 2025 p. 6: grid exit point [high-voltage substation], substation
#: [medium-voltage substation], distribution substation [low-voltage substation] [S]
#: C-5 (Yuri 2026-11-28), the main case [P]: OSM substation role to Williams tier
ROLE_TIER = {"transmission": "high", "distribution": "medium"}
#: the bases ``tier_for`` accepts: the role (main case) and Hazus's kV classes (sensitivity)
TIER_BASES = ("role", "hazus_kv")
WILLIAMS_COMPONENT = {
    "high": "grid exit point",
    "medium": "substation",
    "low": "distribution substation",
}
WILLIAMS_DEPTHS_M = (0.5, 1.0, 2.0, 3.0)
#: Data S4 p. 1 (Energy rows), aggregated value (expertise-weighted mean, Eq. 1), percent [S];
#: read 2026-11-27 (facts file substation-curves-other, fact williams_substation_points).
#: Cited, not the supplement copied: the article is CC BY-NC-ND.
WILLIAMS_PERCENT = {
    ("grid exit point", "max"): (34.1, 45.5, 61.0, 69.7),
    ("grid exit point", "min"): (14.0, 22.0, 36.7, 48.8),
    ("substation", "max"): (33.4, 48.4, 64.8, 75.5),
    ("substation", "min"): (14.3, 25.0, 42.0, 52.4),
    ("distribution substation", "max"): (34.7, 51.0, 66.2, 76.5),
    ("distribution substation", "min"): (14.6, 27.4, 43.3, 51.3),
}
WILLIAMS_CITATION = (
    "Williams et al. 2025, J. Flood Risk Manag. 18(2):e70045, Data S4 p. 1, aggregated values"
)


def voltage_tier(kv: float | None) -> str | None:
    """Hazus voltage class of a substation's highest tagged voltage; None when unknown or below
    34.5 kV (no class)."""
    if kv is None or kv != kv:  # empty or NaN
        return None
    for tier, floor in HAZUS_TIERS_KV:
        if kv >= floor:
            return tier
    return None


def hold_to(curve: PointCurve, max_depth_m: float = MAX_DEPTH_M) -> PointCurve:
    """The curve with its last value held to ``max_depth_m`` [P] (no point added if it reaches)."""
    if curve.depth_m[-1] >= max_depth_m:
        return curve
    return PointCurve(
        id=curve.id,
        depth_m=(*curve.depth_m, max_depth_m),
        ratio=(*curve.ratio, curve.ratio[-1]),
        datum=curve.datum,
        source=curve.source,
        tag="P",
        note=(f"{curve.note}. " if curve.note else "")
        + f"Source points to {curve.depth_m[-1]} m ({curve.tag}); last value held to "
        f"{max_depth_m} m [P].",
    )


def williams(component: str, condition: str, max_depth_m: float = MAX_DEPTH_M) -> PointCurve:
    """Williams's points for one component and hazard condition, 0 at 0 m, held above 3 m [P]."""
    percent = WILLIAMS_PERCENT[(component, condition)]
    return PointCurve(
        id=f"williams_{component.replace(' ', '_')}_{condition}",
        depth_m=(0.0, *WILLIAMS_DEPTHS_M, max_depth_m),
        ratio=(0.0, *(p / 100.0 for p in percent), percent[-1] / 100.0),
        datum="above ground",
        source=f"{WILLIAMS_CITATION}, {component}, {condition}imum hazard condition",
        tag="P",
        note=(
            "Points at 0.5, 1, 2 and 3 m are the published percentages /100 [S]; 0 at 0 m, the "
            "3 m value held above 3 m and the depth datum (above ground) are ours [P] (CH-27). "
            "New Zealand expert elicitation, not validated against observed damage."
        ),
    )


def substation_curves(nirandjan_xlsx: Path) -> dict[str, PointCurve]:
    """Every curve of the envelope, completed to ``MAX_DEPTH_M``, by id."""
    found, _ = read_nirandjan_f2(nirandjan_xlsx)
    held = hold_to(found["F2.1"])
    curves = {
        "nirandjan_F2": PointCurve(
            id="nirandjan_F2",
            depth_m=held.depth_m,
            ratio=held.ratio,
            datum=held.datum,
            source=held.source,
            tag=held.tag,
            note="F2.1, F2.2 and F2.3 are identical (checked by the reader). " + held.note,
        )
    }
    for component in WILLIAMS_COMPONENT.values():
        for condition in ("min", "max"):
            c = williams(component, condition)
            curves[c.id] = c
    bor = bor_curve(MAX_DEPTH_M, BOR_STEP_M)
    curves[bor.id] = bor
    return curves


def role_tier(kind: str | None) -> str | None:
    """Williams tier of a substation from its OpenStreetMap role (C-5, the main case) [P].

    ``kind`` is the asset table's ``lab_substation_kind`` (the OSM ``substation=*`` values of the
    site's outlines, ``;``-joined); transmission anywhere in it wins, as in the asset build. None
    when no role in ``ROLE_TIER`` is stated.
    """
    if not kind or kind != kind:  # empty or NaN
        return None
    roles = str(kind).split(";")
    if "transmission" in roles:
        return ROLE_TIER["transmission"]
    for role in roles:
        if role in ROLE_TIER:
            return ROLE_TIER[role]
    return None


def tier_for(kv: float | None, kind: str | None, basis: str = "role") -> str | None:
    """Williams tier of a substation on ``basis``: "role" (C-5, main case) or "hazus_kv"."""
    if basis == "role":
        return role_tier(kind)
    if basis == "hazus_kv":
        return voltage_tier(kv)
    raise ValueError(f"unknown tier basis {basis!r}; expected one of {TIER_BASES}")


def envelope_for(
    kv: float | None, kind: str | None = None, basis: str = "role"
) -> dict[str, str] | None:
    """Which curve of ``substation_curves`` each family uses for a substation.

    The Williams curves follow the tier on ``basis`` (``tier_for``). None when the tier is unknown:
    the asset gets no substation curve (and has no value). Bor's set is for HV substations above
    345 kV; it is offered for every tier as the alternative FR2 names, and the page must say where
    it is out of its stated range.
    """
    tier = tier_for(kv, kind, basis)
    if tier is None:
        return None
    component = WILLIAMS_COMPONENT[tier].replace(" ", "_")
    return {
        "low": "nirandjan_F2",
        "high": f"williams_{component}_max",
        "williams_min": f"williams_{component}_min",
        "bor": "bor_hv345_anchored",
    }
