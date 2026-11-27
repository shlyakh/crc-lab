"""The event-loss table (interface draft, not implemented)."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

import crc_framework as cf
import pyarrow as pa

from ._events import EventSet


class MissingIntensity(Enum):
    """What an (event, component) pair absent from the intensity table means. A closed choice."""

    #: the event does not reach the component: loss 0, counted in the diagnostics
    NO_LOSS = "no_loss"
    #: every pair must be present; an absent pair is an error
    ERROR = "error"


class FailurePolicy(Enum):
    """What aggregation does with rows the impact refused (``ImpactError``). A closed choice."""

    #: aggregation is refused while any failure row exists
    REFUSE = "refuse"
    #: the components with any failure are left out of every sum, and named in the diagnostics
    EXCLUDE_COMPONENT = "exclude_component"


@dataclass(frozen=True)
class Exposure:
    """One component (an asset or any other unit of loss) and what its loss is measured against.

    ``value`` is the amount a damage ratio of 1 corresponds to, in the table's currency and
    valuation basis. ``impact`` names an entry of the impacts given to ``from_intensities``.
    """

    component_id: str
    value: float
    impact: str


@dataclass(frozen=True)
class Failure:
    """One row the impact refused: event, component, the intensity, and CRC's error code."""

    event_id: str
    component_id: str
    intensity: float
    code: str
    message: str


class EventLossTable:
    """Loss per event and component, with its measurement, currency and valuation basis.

    Rows hold event id, component id, intensity (when built from intensities), damage ratio and
    loss. Pairs with no loss need not be stored. Failure rows are kept apart, never dropped, and
    every count of what was left out travels in ``diagnostics``. ``label`` is an open string
    naming the choice behind the table (for example which of several damage curves was used),
    so several tables over one event set can stand side by side.
    """

    events: EventSet
    currency: str
    valuation_basis: str
    label: str
    loss: cf.Measurement
    failures: tuple[Failure, ...]
    diagnostics: tuple[cf.Diagnostic, ...]

    @classmethod
    def from_intensities(
        cls,
        events: EventSet,
        intensities: pa.Table,
        *,
        intensity: cf.Measurement,
        exposures: tuple[Exposure, ...],
        impacts: Mapping[str, cf.Impact],
        currency: str,
        valuation_basis: str,
        label: str,
        missing: MissingIntensity = MissingIntensity.NO_LOSS,
    ) -> EventLossTable:
        """Damage ratios from CRC, ``impact.evaluate``, times each component's value.

        ``intensities`` has the columns ``event_id`` (string), ``component_id`` (string) and
        ``value`` (float64), in the measurement ``intensity``, which must equal the ``input`` of
        every impact used; every impact's ``output`` must be a ``cf.Ratio``. An event or
        component not in ``events`` or ``exposures`` is an error. A value the impact refuses
        becomes a ``Failure`` with CRC's error code; the other rows of the same impact are still
        evaluated.
        """
        raise NotImplementedError

    @classmethod
    def from_losses(
        cls,
        events: EventSet,
        losses: pa.Table,
        *,
        currency: str,
        valuation_basis: str,
        label: str,
    ) -> EventLossTable:
        """A table of losses computed elsewhere: columns ``event_id``, ``component_id``,
        ``loss`` (float64, finite, non-negative)."""
        raise NotImplementedError

    @property
    def component_ids(self) -> tuple[str, ...]:
        raise NotImplementedError

    def to_arrow(self) -> pa.Table:
        """The rows, with the table's metadata in the schema metadata."""
        raise NotImplementedError

    def write(self, path: Path, *, overwrite: bool = False) -> Path:
        """Parquet, written atomically; an existing file is kept unless ``overwrite``.

        The event set, measurement, currency, label, failures and diagnostics are stored in the
        file's metadata with a format name and version, so that ``read`` gives back an equal table.
        """
        raise NotImplementedError

    @classmethod
    def read(cls, path: Path) -> EventLossTable:
        raise NotImplementedError
