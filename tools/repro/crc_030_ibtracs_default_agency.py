# /// script
# requires-python = ">=3.11"
# dependencies = ["crc-sdk==1.1.0", "crc-framework==1.1.0"]
# ///
"""IBTrACS: the documentation says the agency is explicit; the constructor has a default.

docs/sources.md describes IBTrACS as observations "for an explicit `Agency`". `IBTrACS()` with
no argument is accepted and reads one agency (USA) chosen by the library. Offline: nothing is
downloaded (building a plan does no I/O).

    uv run crc_030_ibtracs_default_agency.py
"""

import inspect
import json
from importlib import resources
from importlib.metadata import version

from crc_sdk import IBTrACS

# Quoted from the crc-sdk v1.0.0 source tree; docs/ is not shipped in the wheel.
DOC_FILE, DOC_LINE = "docs/sources.md", 43
DOC_TEXT = (
    "| `IBTrACS` | Native storm point observations for an explicit `Agency`; "
    "event groups and positions remain distinct |"
)

print(f"crc-sdk {version('crc-sdk')}, crc-framework {version('crc-framework')}")
print(f"documented: {DOC_FILE}:{DOC_LINE}: {DOC_TEXT}")

signature = inspect.signature(IBTrACS)
default = signature.parameters["agency"].default
contract = json.loads(
    resources.files("crc_sdk").joinpath("contracts/api/public-api.json").read_text("utf-8")
)


def find_ibtracs(node):
    """The IBTrACS entry of the shipped public-api.json, wherever it sits."""
    if isinstance(node, dict):
        if "IBTrACS" in node and isinstance(node["IBTrACS"], dict):
            return node["IBTrACS"]
        for value in node.values():
            if (found := find_ibtracs(value)) is not None:
                return found
    return None


entry = find_ibtracs(contract)
declared = next(p for p in entry["constructor"]["parameters"] if p["name"] == "agency")

try:
    plan = IBTrACS()
    accepted = "accepted"
except Exception as error:  # noqa: BLE001  the outcome is what is printed
    plan, accepted = None, f"refused: {type(error).__name__}: {error}"

print("call:      IBTrACS()")
print(f"signature: IBTrACS{signature}")
print(f"public-api.json declares agency default: {declared.get('default')}")
print("expected:  no agency is read unless the caller names one (constructor requires `agency`)")
print(f"observed:  IBTrACS() {accepted}; agency defaults to {default!r}")
if plan is not None:
    print(f"explain(): {plan.explain().operations[0].description}")
reproduced = plan is not None and default is IBTrACS.Agency.USA
print("REPRODUCED" if reproduced else "NOT REPRODUCED")
