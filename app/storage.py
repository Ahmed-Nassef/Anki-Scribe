"""Durable JSON for the local stores.

Every store here is one small JSON file holding work the user cannot get back:
the API key, draft cards, the sent ledger, the library. A crash during a write
must not cost the previous version, and a file that fails to parse must fall
back to the last good copy instead of starting empty.
"""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path


def backup_path(path: Path) -> Path:
    return Path(path).with_suffix(Path(path).suffix + ".bak")


def write_json(path: Path, payload) -> None:
    """Write atomically, keeping the previous good file as ``*.bak``."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    data = json.dumps(payload, ensure_ascii=False)
    with open(temporary, "w", encoding="utf-8") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
    if path.is_file():
        try:
            shutil.copy2(path, backup_path(path))
        except OSError:
            pass
    os.replace(temporary, path)


def read_json(path: Path) -> tuple[object | None, str]:
    """The payload and where it came from: ``(None, "missing")`` when gone."""
    path = Path(path)
    if not path.is_file() and not backup_path(path).is_file():
        return None, "missing"
    for candidate, source in ((path, "live"), (backup_path(path), "backup")):
        if not candidate.is_file():
            continue
        try:
            return json.loads(candidate.read_text(encoding="utf-8")), source
        except (json.JSONDecodeError, OSError):
            continue
    return None, "unreadable"


def heal(path: Path, payload) -> None:
    """Put a payload recovered from the backup back in place.

    The damaged file is removed first: writing over it would otherwise copy the
    corruption onto the one good backup that is left.
    """
    path = Path(path)
    try:
        path.unlink(missing_ok=True)
        write_json(path, payload)
    except OSError:
        pass
