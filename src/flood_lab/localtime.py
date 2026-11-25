"""Local days in New York (requirements section 5): times stored in GMT, days counted in local time.

No function here reads a file.
"""

from __future__ import annotations

from collections.abc import Iterable

import pandas as pd

ZONE = "America/New_York"


def local_day(gmt_times: Iterable[str] | pd.Series) -> pd.Series:
    """The New York calendar day (``YYYY-MM-DD``) of each time given in GMT.

    A time without a zone is read as GMT, as FloodNet writes it; the offset is four hours in
    summer time and five in winter time, as the zone database gives it.
    """
    start = pd.to_datetime(pd.Series(gmt_times), utc=True)
    return start.dt.tz_convert(ZONE).dt.strftime("%Y-%m-%d")
