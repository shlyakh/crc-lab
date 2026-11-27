"""crc_event_loss: an event-loss table and event-based loss aggregation for Climate Risk Commons.

An extension of crc-framework, not part of it and not reviewed by its authors. It holds an event
set, a table of losses per event and component, and the sums of those losses within an event and
within a year; every figure of a loss distribution is then CRC's own
(``crc_framework.Distribution``).
It imports crc_framework, numpy and pyarrow, and nothing that names a hazard, place or asset type.

Interface draft for review; nothing is implemented yet.
"""

from ._aggregate import (
    AnnualLosses,
    AnnualMeasure,
    Bracket,
    IndependenceMethod,
    annual_losses,
    brackets,
    occurrence_distribution,
    summary_inputs,
)
from ._events import EventSet, Timeline, YearWeights
from ._table import EventLossTable, Exposure, Failure, FailurePolicy, MissingIntensity

FORMAT = "crc-event-loss"
FORMAT_VERSION = "0.1"

__all__ = [
    "FORMAT",
    "FORMAT_VERSION",
    "AnnualLosses",
    "AnnualMeasure",
    "Bracket",
    "EventLossTable",
    "EventSet",
    "Exposure",
    "Failure",
    "FailurePolicy",
    "IndependenceMethod",
    "MissingIntensity",
    "Timeline",
    "YearWeights",
    "annual_losses",
    "brackets",
    "occurrence_distribution",
    "summary_inputs",
]
