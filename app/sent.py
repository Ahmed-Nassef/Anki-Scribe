"""Persistent record of cards that have already been pushed to Anki.

Drafts answer "what am I still working on". The sent ledger answers "what have I
already done": it survives a push, so coverage and the source map stay honest
after the cards leave for Anki, and it keeps the Anki note id so review results
can be matched back to a page later.

Keyed by source path exactly like :class:`app.drafts.DraftStore`, so the two
stores always agree on which document a record belongs to.
"""

from __future__ import annotations

import os
import threading
import time
from pathlib import Path

from . import storage
from .config import data_dir, quarantine_file

MAX_SENT_PER_SOURCE = 5_000
MAX_SOURCES = 200


class SentStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or (data_dir() / "sent.json")
        self._lock = threading.RLock()
        self._sources: dict[str, dict] = {}
        self._load()

    # -- persistence -----------------------------------------------------

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
                self._sources[str(key)] = value

    def _save(self) -> None:
        storage.write_json(self.path, self._sources)

    # -- reading ---------------------------------------------------------

    @staticmethod
    def _empty(source_path: str) -> dict:
        return {
            "path": str(Path(source_path).absolute()),
            "filename": "",
            "cards": [],
            "updatedAt": 0,
        }

    def get(self, source_path: str) -> dict:
        key = self._key(source_path)
        with self._lock:
            source = self._sources.get(key)
            if source is None:
                return self._empty(source_path)
            return {
                "path": source.get("path", str(Path(source_path).absolute())),
                "filename": source.get("filename", ""),
                "cards": list(source.get("cards", [])),
                "updatedAt": source.get("updatedAt", 0),
            }

    def count(self, source_path: str) -> int:
        with self._lock:
            source = self._sources.get(self._key(source_path))
            return len(source.get("cards", [])) if source else 0

    # -- writing ---------------------------------------------------------

    @staticmethod
    def _card_id(card: dict) -> str:
        return str(card.get("id") or card.get("uid") or "")

    def append(self, source_path: str, filename: str, cards: list[dict]) -> dict:
        """Add pushed cards to the ledger, replacing any with the same id.

        Cards without an id are kept but cannot be de-duplicated, so callers
        should always pass the draft ``uid`` through as ``id``.
        """
        clean = [card for card in cards if isinstance(card, dict)]
        if not clean:
            return self.get(source_path)

        key = self._key(source_path)
        with self._lock:
            source = self._sources.get(key)
            if not isinstance(source, dict):
                source = self._empty(source_path)
            existing: list[dict] = [
                card for card in source.get("cards", []) if isinstance(card, dict)
            ]
            index = {
                self._card_id(card): position
                for position, card in enumerate(existing)
                if self._card_id(card)
            }
            for card in clean:
                entry = dict(card)
                entry.setdefault("pushedAt", time.time())
                card_id = self._card_id(entry)
                if card_id and card_id in index:
                    existing[index[card_id]] = entry
                else:
                    if card_id:
                        index[card_id] = len(existing)
                    existing.append(entry)

            if len(existing) > MAX_SENT_PER_SOURCE:
                existing = existing[-MAX_SENT_PER_SOURCE:]

            self._sources[key] = {
                "path": str(Path(source_path).absolute()),
                "filename": filename or Path(source_path).name,
                "cards": existing,
                "updatedAt": time.time(),
            }
            self._prune()
            self._save()
        return self.get(source_path)

    def _prune(self) -> None:
        if len(self._sources) <= MAX_SOURCES:
            return
        ordered = sorted(
            self._sources.items(),
            key=lambda item: float(item[1].get("updatedAt", 0)),
            reverse=True,
        )
        self._sources = dict(ordered[:MAX_SOURCES])

    def delete(self, source_path: str) -> None:
        key = self._key(source_path)
        with self._lock:
            if self._sources.pop(key, None) is not None:
                self._save()

    def sources(self) -> list[dict]:
        """Small read model for the library: one row per source with history."""
        with self._lock:
            rows = []
            for key, source in self._sources.items():
                cards = source.get("cards", [])
                rows.append(
                    {
                        "key": key,
                        "path": source.get("path", ""),
                        "filename": source.get("filename", ""),
                        "count": len(cards) if isinstance(cards, list) else 0,
                        "updatedAt": source.get("updatedAt", 0),
                    }
                )
        return rows
