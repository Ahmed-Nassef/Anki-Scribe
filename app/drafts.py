"""Local draft-card persistence, keyed by source file path."""

from __future__ import annotations

import os
import threading
import time
from pathlib import Path

from . import storage
from .config import data_dir, quarantine_file

MAX_CARDS_PER_DRAFT = 2000
MAX_DRAFTS = 200


class DraftStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or (data_dir() / "drafts.json")
        self._lock = threading.RLock()
        self._drafts: dict[str, dict] = {}
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
            if isinstance(value, dict) and isinstance(value.get("cards"), list):
                self._drafts[str(key)] = value

    def _save(self) -> None:
        storage.write_json(self.path, self._drafts)

    def get(self, source_path: str) -> dict:
        key = self._key(source_path)
        with self._lock:
            draft = self._drafts.get(key)
            if draft is None:
                return {
                    "path": str(Path(source_path).absolute()),
                    "filename": "",
                    "cards": [],
                    "updatedAt": 0,
                }
            return {
                "path": draft.get("path", str(Path(source_path).absolute())),
                "filename": draft.get("filename", ""),
                "cards": draft.get("cards", []),
                "updatedAt": draft.get("updatedAt", 0),
            }

    def put(self, source_path: str, filename: str, cards: list[dict]) -> dict:
        key = self._key(source_path)
        if len(cards) > MAX_CARDS_PER_DRAFT:
            raise ValueError(f"A source can keep at most {MAX_CARDS_PER_DRAFT} draft cards.")
        clean_cards = [card for card in cards if isinstance(card, dict)]
        draft = {
            "path": str(Path(source_path).absolute()),
            "filename": filename or Path(source_path).name,
            "cards": clean_cards,
            "updatedAt": time.time(),
        }
        with self._lock:
            self._drafts[key] = draft
            if len(self._drafts) > MAX_DRAFTS:
                ordered = sorted(
                    self._drafts.items(),
                    key=lambda item: float(item[1].get("updatedAt", 0)),
                    reverse=True,
                )
                self._drafts = dict(ordered[:MAX_DRAFTS])
            self._save()
        return {
            "path": draft["path"],
            "filename": draft["filename"],
            "cards": draft["cards"],
            "updatedAt": draft["updatedAt"],
        }

    def delete(self, source_path: str) -> None:
        key = self._key(source_path)
        with self._lock:
            if self._drafts.pop(key, None) is not None:
                self._save()

    def counts(self) -> dict[str, int]:
        """How many draft cards each source holds, keyed like the store."""
        with self._lock:
            return {
                key: len(draft.get("cards", []))
                for key, draft in self._drafts.items()
                if isinstance(draft, dict)
            }
