"""Try a download again when the connection fails part-way. Standard library only.

Publishers drop a small share of requests on some days (resets, read timeouts). An answer
from the publisher, including a 404, is not a failure and is never retried.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from http.client import HTTPException
from urllib.error import HTTPError

ATTEMPTS = 4
PAUSE = 5.0  # seconds, multiplied by the number of tries so far


def again[T](action: Callable[[], T], *, attempts: int = ATTEMPTS, pause: float = PAUSE) -> T:
    """Run ``action``; on a connection error run it again, up to ``attempts`` times in all."""
    for attempt in range(1, attempts + 1):
        try:
            return action()
        except (HTTPError, FileNotFoundError):  # an answer, or no cached copy offline
            raise
        except (OSError, HTTPException):
            if attempt == attempts:
                raise
            time.sleep(pause * attempt)
    raise AssertionError("unreachable")
