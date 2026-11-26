"""Manual hides: text the student masked by hand in the PDF viewer.

Automatic answer masks are derived from cards and never stored. A manual mask
is different: it is a decision the student made about this particular page, so
it is saved beside the drafts and the sent ledger and survives a restart.
"""

from __future__ import annotations

import os
import threading
import time
from pathlib import Path

from . import storage
from .config import data_dir, quarantine_file

MAX_MASKS_PER_SOURCE = 3000
MAX_BOXES_PER_MASK = 120
MAX_SOURCES = 200


def _number(value, low: float, high: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("mask coordinate is not a number") from exc
    if not (number == number) or number in (float("inf"), float("-inf")):
        raise ValueError("mask coordinate is not a number")
    return max(low, min(high, number))


def _clean_box(raw: dict) -> dict:
    if not isinstance(raw, dict):
        raise ValueError("each mask box must be an object")
    try:
        page = int(raw.get("page"))
    except (TypeError, ValueError) as exc:
        raise ValueError("mask page is not a number") from exc
    if page < 0 or page > 100_000:
        raise ValueError("mask page is out of range")
    x = _number(raw.get("x"), 0.0, 1.0)
    y = _number(raw.get("y"), 0.0, 1.0)
    w = _number(raw.get("w"), 0.0005, 1.0)
    h = _number(raw.get("h"), 0.0005, 1.0)
    if x + w > 1.0:
        w = max(0.0005, 1.0 - x)
    if y + h > 1.0:
        h = max(0.0005, 1.0 - y)
    return {
        "page": page,
        "x": round(x, 4),
        "y": round(y, 4),
        "w": round(w, 4),
        "h": round(h, 4),
    }


def clean_mask(raw: dict) -> dict:
    if not isinstance(raw, dict):
        raise ValueError("each mask must be an object")
    boxes_raw = raw.get("boxes")
    if not isinstance(boxes_raw, list) or not boxes_raw:
        raise ValueError("a mask needs at least one box")
    boxes = [_clean_box(box) for box in boxes_raw[:MAX_BOXES_PER_MASK]]
    text = str(raw.get("text") or "").strip()[:500]
    identifier = str(raw.get("id") or "").strip()[:120]
    if not identifier:
        raise ValueError("a mask needs an id")
    return {
        "id": identifier,
        "text": text,
        "boxes": boxes,
        "createdAt": float(raw.get("createdAt") or time.time()),
    }


def clean_masks(masks: object) -> list[dict]:
    if masks is None:
        return []
    if not isinstance(masks, list):
        raise ValueError("masks must be a list")
    cleaned: list[dict] = []
    seen: set[str] = set()
    for raw in masks[:MAX_MASKS_PER_SOURCE]:
        mask = clean_mask(raw)
        if mask["id"] in seen:
            continue
        seen.add(mask["id"])
        cleaned.append(mask)
    return cleaned


class MaskStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or (data_dir() / "masks.json")
        self._lock = threading.RLock()
        self._masks: dict[str, dict] = {}
        self._load()

    @staticmethod
    def _key(source_path: str) -> str:
        return os.path.normcase(os.path.abspath(source_path))

    def _load(self) -> None:
        payload, source = storage.read_json(self.path)
        if source == "unreadable":
            quarantine_file(self.path)
            return
        if source == "backup" and isinstance(payload, dict):
            storage.heal(self.path, payload)
        if not isinstance(payload, dict):
            return
        for key, value in payload.items():
            if isinstance(value, dict) and isinstance(value.get("masks"), list):
                try:
                    self._masks[str(key)] = {
                        "path": str(value.get("path") or key),
                        "masks": clean_masks(value.get("masks")),
                        "updatedAt": float(value.get("updatedAt") or 0),
                    }
                except (TypeError, ValueError):
                    continue

    def _save(self) -> None:
        storage.write_json(self.path, self._masks)

    def get(self, source_path: str) -> dict:
        key = self._key(source_path)
        with self._lock:
            entry = self._masks.get(key)
            if entry is None:
                return {
                    "path": str(Path(source_path).absolute()),
                    "masks": [],
                    "updatedAt": 0,
                }
            return {
                "path": entry.get("path", str(Path(source_path).absolute())),
                "masks": entry.get("masks", []),
                "updatedAt": entry.get("updatedAt", 0),
            }

    def put(self, source_path: str, masks: list[dict]) -> dict:
        key = self._key(source_path)
        cleaned = clean_masks(masks)
        entry = {
            "path": str(Path(source_path).absolute()),
            "masks": cleaned,
            "updatedAt": time.time(),
        }
        with self._lock:
            self._masks[key] = entry
            if len(self._masks) > MAX_SOURCES:
                ordered = sorted(
                    self._masks.items(),
                    key=lambda item: float(item[1].get("updatedAt", 0)),
                    reverse=True,
                )
                self._masks = dict(ordered[:MAX_SOURCES])
            self._save()
        return {
            "path": entry["path"],
            "masks": entry["masks"],
            "updatedAt": entry["updatedAt"],
        }

    def delete(self, source_path: str) -> None:
        key = self._key(source_path)
        with self._lock:
            if self._masks.pop(key, None) is not None:
                self._save()

    def counts(self) -> dict[str, int]:
        with self._lock:
            return {
                key: len(entry.get("masks", []))
                for key, entry in self._masks.items()
                if isinstance(entry, dict)
            }


__all__ = ["MaskStore", "clean_mask", "clean_masks"]
