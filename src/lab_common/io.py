"""Atomic file writes shared by the projects (temporary file, then ``os.replace``).

Kept free of crc-sdk imports so that every project can use it whatever the state of its port.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path


def write_text_atomic(path: Path, text: str) -> None:
    """Write text through a temporary file in the same folder, then ``os.replace``."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".part")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
        os.chmod(tmp, 0o644)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def write_json_atomic(path: Path, payload: object, **dumps: object) -> None:
    """Write JSON atomically; other keywords go to ``json.dumps``.

    The separators are compact, ``(",", ":")``, unless the caller passes ``separators``, also when
    it passes ``indent``: the bytes are those the writer in ``lab_common.texas`` always wrote.
    """
    dumps.setdefault("separators", (",", ":"))
    write_text_atomic(path, json.dumps(payload, **dumps))  # type: ignore[arg-type]
