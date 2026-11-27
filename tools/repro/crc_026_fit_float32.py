# /// script
# requires-python = ">=3.11"
# dependencies = ["crc-framework==1.1.0", "numpy"]
# ///
"""Gumbel quantile fit: the outcome depends on how the same depths are written.

Expected: fit_quantiles gives the same outcome for the same depths whether they arrive as
32-bit floats (as in a GeoTIFF) or as their decimal values. Observed: one form converges and
the other raises FitError. Offline; the depths are two flood-map pixels (flat, then rising at
the two longest return periods), written in the script.

    uv run crc_026_fit_float32.py
"""

import json
from importlib.metadata import version

import numpy as np
from crc_framework import DistributionFamily, QuantileCurve, QuantileFit, fit_quantiles

PERIODS = (10, 20, 50, 75, 100, 200, 500)  # return periods, years
PIXELS = ((1, 1, 1, 1, 1, 2.639, 3.768), (1, 1, 1, 1, 1, 1.016, 1.13))  # depths, m
probabilities = [1 - 1 / t for t in PERIODS]
spec = QuantileFit(family=DistributionFamily.GUMBEL_RIGHT)


def outcome(values: list[float]) -> str:
    try:
        fitted = fit_quantiles(QuantileCurve(probabilities, values), spec)
    except Exception as error:  # noqa: BLE001  the outcome is what is printed
        return f"{type(error).__name__}: {str(error).rsplit(': ', 1)[-1]}"
    record = json.loads(fitted.record.to_json())
    iterations = record["attempts"][record["selected_attempt"]]["diagnostic"]["iterations"]
    return f"converged after {iterations} iterations"


print(f"crc-framework {version('crc-framework')}, numpy {version('numpy')}")
print(f"call: fit_quantiles(QuantileCurve([1 - 1/T for T in {PERIODS}], depths),")
print("                    QuantileFit(family=DistributionFamily.GUMBEL_RIGHT))")
print("expected: the same outcome for both forms of each pixel")
print(f"{'depths (last two)':<20} {'written as':<12} observed")
differs = []
for depths in PIXELS:
    as_float32 = [float(np.float32(d)) for d in depths]  # e.g. 2.639 -> 2.6389999389648438
    as_decimal = [float(d) for d in depths]
    results = [outcome(as_float32), outcome(as_decimal)]
    for kind, text in zip(("float32", "decimal"), results, strict=True):
        print(f"{str(depths[-2:]):<20} {kind:<12} {text}")
    differs.append(results[0].startswith("converged") != results[1].startswith("converged"))
print(f"observed: the two forms differ in outcome for {sum(differs)} of {len(PIXELS)} pixels")
print("REPRODUCED" if all(differs) else "NOT REPRODUCED")
