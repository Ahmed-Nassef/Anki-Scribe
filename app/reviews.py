"""Server-side card review state and study-session analytics.

The study dialog used to keep its grades only in browser localStorage. That
made the analytics disappear when the browser profile was cleared and made
them invisible to the rest of the app. This store keeps the same lightweight
scheduler on the server, in the app data folder, beside drafts and sent cards.

The scheduler is deliberately simple (Again/Hard/Good/Easy with an ease and a
day interval). It is a study-session aid; the exam plan still uses FSRS-6.
"""

from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Any

from . import storage
from .config import data_dir

MAX_REVIEWS = 10_000
MAX_SESSIONS = 500


def _number(value: Any, fallback: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return fallback


class ReviewStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or (data_dir() / "study_reviews.json")
        self._lock = threading.RLock()
        self._reviews: dict[str, dict] = {}
        self._sessions: list[dict] = []
        self._load()

    def _load(self) -> None:
        payload, source = storage.read_json(self.path)
        if source == "unreadable" or not isinstance(payload, dict):
            return
        reviews = payload.get("reviews")
        if isinstance(reviews, dict):
            for key, value in reviews.items():
                if isinstance(value, dict):
                    self._reviews[str(key)] = value
        sessions = payload.get("sessions")
        if isinstance(sessions, list):
            self._sessions = [entry for entry in sessions if isinstance(entry, dict)][
                -MAX_SESSIONS:
            ]

    def _save(self) -> None:
        storage.write_json(
            self.path,
            {"reviews": self._reviews, "sessions": self._sessions},
        )

    # -- reviews ---------------------------------------------------------

    def review(self, card: dict, rating: int, seconds: float) -> dict:
        rating = int(rating)
        if rating not in (1, 2, 3, 4):
            raise ValueError("Rating must be Again, Hard, Good or Easy.")
        key = str(card.get("uid") or card.get("id") or "").strip()[:120]
        if not key:
            raise ValueError("A card needs a uid before it can be reviewed.")
        seconds = max(0.0, min(3600.0, _number(seconds, 0.0)))
        now = time.time()
        with self._lock:
            previous = self._reviews.get(key) or {}
            ease = min(3.0, max(1.3, _number(previous.get("ease"), 2.5)))
            interval = max(0, int(_number(previous.get("interval"), 0)))
            due = now + 10 * 60
            next_ease = ease
            next_interval = interval
            if rating == 1:
                next_interval = 0
                next_ease = max(1.3, ease - 0.2)
            elif rating == 2:
                next_interval = max(1, round(interval * 1.2)) if interval else 1
                next_ease = max(1.3, ease - 0.15)
                due = now + next_interval * 86400
            elif rating == 3:
                next_interval = max(1, round(interval * ease)) if interval else 1
                due = now + next_interval * 86400
            else:
                next_interval = (
                    max(4, round(interval * ease * 1.4)) if interval else 4
                )
                next_ease = min(3.0, ease + 0.15)
                due = now + next_interval * 86400
            record = {
                "uid": str(card.get("uid") or ""),
                "question": str(card.get("question") or card.get("text") or "")[:500],
                "mode": str(card.get("mode") or "basic")[:20],
                "ease": round(next_ease, 2),
                "interval": next_interval,
                "due": due,
                "last": now,
                "reps": int(previous.get("reps") or 0) + 1,
                "lapses": int(previous.get("lapses") or 0) + (1 if rating == 1 else 0),
                "lastRating": rating,
                "seconds": round(seconds),
            }
            self._reviews[key] = record
            if len(self._reviews) > MAX_REVIEWS:
                ordered = sorted(
                    self._reviews.items(),
                    key=lambda item: _number(item[1].get("last"), 0),
                    reverse=True,
                )[:MAX_REVIEWS]
                self._reviews = dict(ordered)
            self._save()
            return record

    # -- sessions / stats ------------------------------------------------

    def save_session(self, session: dict) -> dict:
        at = _number(session.get("at"), time.time())
        if at > 1e12:
            at /= 1000
        entry = {
            "at": at,
            "total": max(0, int(_number(session.get("total"), 0))),
            "correct": max(0, int(_number(session.get("correct"), 0))),
            "seconds": max(0, _number(session.get("seconds"), 0)),
            "streak": max(0, int(_number(session.get("streak"), 0))),
            "grades": session.get("grades") if isinstance(session.get("grades"), dict) else {},
        }
        with self._lock:
            self._sessions.append(entry)
            self._sessions = self._sessions[-MAX_SESSIONS:]
            self._save()
        return entry

    def snapshot(self) -> dict:
        with self._lock:
            sessions = list(self._sessions)
            reviews = dict(self._reviews)
        total = sum(int(entry.get("total") or 0) for entry in sessions)
        correct = sum(int(entry.get("correct") or 0) for entry in sessions)
        seconds = sum(_number(entry.get("seconds"), 0) for entry in sessions)
        days = {
            time.strftime(
                "%Y-%m-%d",
                time.localtime(
                    _number(entry.get("at"), 0) / 1000
                    if _number(entry.get("at"), 0) > 1e12
                    else _number(entry.get("at"), 0)
                ),
            )
            for entry in sessions
        }
        return {
            "reviews": reviews,
            "sessions": sessions,
            "stats": {
                "sessions": len(sessions),
                "reviews": total,
                "correct": correct,
                "days": len(days),
                "retention": round(correct / total, 3) if total else 0,
                "seconds": round(seconds),
                "average": round(seconds / total, 1) if total else 0,
            },
        }

    def clear(self) -> None:
        with self._lock:
            self._reviews = {}
            self._sessions = []
            self._save()
