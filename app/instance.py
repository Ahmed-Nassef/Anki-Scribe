"""One Anki Scribe per data folder.

Two processes writing the same JSON files is how drafts get overwritten. The
port scan in ``run.py`` is not enough on its own: it must also tell "the app for
this data folder" from "some other copy of the app, started with a different
data folder", which is exactly the confusion that once made a fresh app look
like every saved card had vanished.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

LOCK_NAME = "instance.lock"
STILL_ACTIVE = 259


def _alive(pid) -> bool:
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return False
    if pid <= 0:
        return False
    if os.name == "nt":
        try:
            import ctypes

            kernel32 = ctypes.windll.kernel32
            handle = kernel32.OpenProcess(0x1000, False, pid)  # QUERY_LIMITED
            if not handle:
                return False
            try:
                code = ctypes.c_ulong()
                kernel32.GetExitCodeProcess(handle, ctypes.byref(code))
                return code.value == STILL_ACTIVE
            finally:
                kernel32.CloseHandle(handle)
        except Exception:
            return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


class InstanceLock:
    def __init__(self, directory: Path) -> None:
        self.path = Path(directory) / LOCK_NAME

    def read(self) -> dict:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        return raw if isinstance(raw, dict) else {}

    def holder(self) -> dict | None:
        """The live process that owns this data folder, if there is one."""
        raw = self.read()
        if raw and _alive(raw.get("pid")):
            return raw
        return None

    def acquire(self) -> dict | None:
        """Take the lock, or return the holder that already has it."""
        for _ in range(2):
            holder = self.holder()
            if holder:
                return holder
            try:
                descriptor = os.open(
                    self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY
                )
            except FileExistsError:
                # Either a live instance won the race, or the file is stale.
                holder = self.holder()
                if holder:
                    return holder
                try:
                    self.path.unlink(missing_ok=True)
                except OSError:
                    return {}
                continue
            except OSError:
                return None
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                json.dump(
                    {"pid": os.getpid(), "port": 0, "started": time.time()}, handle
                )
            return None
        return {}

    def set_port(self, port: int) -> None:
        payload = self.read()
        payload.update({"pid": os.getpid(), "port": int(port)})
        payload.setdefault("started", time.time())
        try:
            self.path.write_text(json.dumps(payload), encoding="utf-8")
        except OSError:
            pass

    def release(self) -> None:
        try:
            if int(self.read().get("pid") or 0) == os.getpid():
                self.path.unlink(missing_ok=True)
        except (OSError, TypeError, ValueError):
            pass
