"""The cache root, which a worktree may borrow from another checkout (requirement FG7).

``paths.CACHE`` is the cache of this checkout. A git worktree has none of its own, so the variable
``FLOOD_CACHE``, when set, names the cache to read from and write to instead:

    FLOOD_CACHE=/path/to/crc-lab/data/cache/flood uv run python -m flood_lab.terrain
"""

from __future__ import annotations

import os
from pathlib import Path

from . import paths

VARIABLE = "FLOOD_CACHE"


def root() -> Path:
    """``$FLOOD_CACHE`` when it is set and not empty, else ``paths.CACHE``."""
    value = os.environ.get(VARIABLE, "").strip()
    return Path(value).expanduser() if value else paths.CACHE
