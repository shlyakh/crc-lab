"""What the installed crc-sdk offers: its source providers, constructors for a user's own data,
and the option values each provider declares.

From 1.0 crc-sdk exports everything from the top-level package. A provider is an exported class
that can ``select`` and takes a ``release``; its options are the enumerations it carries
(``JRC.Product``, ``ERA5.Indicator``, ``IBTrACS.Agency``). Models, scenarios and members of the
projection sources are open strings upstream and are not enumerated here.
"""

from __future__ import annotations

import enum
import importlib
import importlib.metadata
import inspect
from typing import Any

#: provider class -> id of its entry in the inventory
PROVIDER_SOURCE = {
    "CHIRPS": "chirps",
    "CMIP6": "cmip6",
    "CRCOpen": "crc-open",
    "ECCCDaily": "eccc-daily",
    "ECCCIDF": "eccc-idf",
    "EDO": "jrc-edo",
    "ERA5": "era5",
    "FieldsOfTheWorld": "ftw-fields",
    "GHCNh": "ghcnh",
    "HYDAT": "hydat",
    "IBTrACS": "ibtracs",
    "ISD": "isd",
    "JRC": "jrc-flood",
    "NEX": "nex-gddp-cmip6",
    "NOAASeaLevel": "noaa-sea-level",
    "NOAAWaterLevels": "noaa-water-levels",
    "USDACropland": "usda-cdl",
    "USGS": "usgs-streamflow",
}
#: classes whose ``from_*`` constructors take a user's own data
OWN_DATA = ("Dataset", "Samples", "Observations", "Projections", "Layer")
#: public names that are not sources
IGNORED: dict[str, str] = {}


def versions() -> dict[str, str]:
    return {name: importlib.metadata.version(name) for name in ("crc-sdk", "crc-framework")}


def providers() -> dict[str, type]:
    """Exported classes that read an outside source."""
    sdk = importlib.import_module("crc_sdk")
    found = {}
    for name in sdk.__all__:
        value = getattr(sdk, name)
        if not (inspect.isclass(value) and hasattr(value, "select")):
            continue
        try:
            parameters = inspect.signature(value).parameters
        except (TypeError, ValueError):
            continue
        if "release" in parameters:
            found[name] = value
    return found


def _options(provider: type) -> dict[str, list[str]]:
    return {
        name.lower(): sorted(str(member.value) for member in value)
        for name, value in vars(provider).items()
        if inspect.isclass(value) and issubclass(value, enum.Enum)
    }


def offered() -> dict[str, Any]:
    """Entry points and option values found in the installed crc-sdk."""
    sdk = importlib.import_module("crc_sdk")
    found = providers()
    symbols = list(found)
    for name in OWN_DATA:
        cls = getattr(sdk, name, None)
        symbols += [
            f"{name}.{method}"
            for method, value in (vars(cls).items() if cls is not None else ())
            if method.startswith("from_") and isinstance(value, classmethod | staticmethod)
        ]
    options: dict[str, dict[str, list[str]]] = {}
    for name, provider in found.items():
        table = _options(provider)
        if table:
            options[PROVIDER_SOURCE.get(name, name)] = table
    return {
        "framework": "crc-sdk",
        "versions": versions(),
        "symbols": sorted(symbols),
        "ignored": IGNORED,
        "options": options,
        "could_not_enumerate": sorted(set(PROVIDER_SOURCE) - set(found)),
    }
