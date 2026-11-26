"""Local configuration, stored outside the project so it survives moves."""

from __future__ import annotations

import hashlib
import os
import time
from dataclasses import asdict, dataclass
from pathlib import Path

import httpx

from . import storage

APP_NAME = "AnkiScribe"
CONFIG_FILENAME = "config.json"

DEFAULT_BASE_URL = "https://api.deepseek.com"
DEFAULT_MODEL = "deepseek-chat"
DEFAULT_ANKI_URL = "http://127.0.0.1:8765"
DEFAULT_DECK = "Anki Scribe"
DEFAULT_TAGS = "anki-scribe"


def data_dir() -> Path:
    """Where uploads and config live. Override with ANKI_SCRIBE_DATA (tests)."""
    override = os.environ.get("ANKI_SCRIBE_DATA")
    if override:
        path = Path(override)
    elif os.name == "nt":
        path = Path(os.environ.get("LOCALAPPDATA", Path.home())) / APP_NAME
    else:
        path = Path.home() / ".local" / "share" / "anki-scribe"
    path.mkdir(parents=True, exist_ok=True)
    return path


def data_fingerprint() -> str:
    """A short id for this data folder.

    A second launch scans local ports for a running instance; without this it
    cannot tell "my data" from "some other copy of the app pointed at another
    folder", which is how a fresh, empty instance once looked like lost data.
    """
    return hashlib.sha256(str(data_dir().resolve()).encode("utf-8")).hexdigest()[:12]


def quarantine_file(path: Path) -> Path | None:
    """Move an unreadable data file aside instead of letting the next save win.

    A truncated write used to look exactly like "the user never had any cards",
    and the following save made that true. Renaming the file keeps the evidence
    and lets the app start with an empty store.
    """
    try:
        target = path.with_name(f"{path.name}.corrupt-{int(time.time())}")
        path.replace(target)
        return target
    except OSError:
        return None


@dataclass
class Settings:
    api_key: str = ""
    base_url: str = DEFAULT_BASE_URL
    model: str = DEFAULT_MODEL
    anki_url: str = DEFAULT_ANKI_URL
    default_deck: str = DEFAULT_DECK
    default_tags: str = DEFAULT_TAGS

    # -- persistence -----------------------------------------------------

    @classmethod
    def load(cls, path: Path | None = None) -> "Settings":
        path = path or data_dir() / CONFIG_FILENAME
        settings = cls()
        payload, source = storage.read_json(path)
        if source == "backup" and isinstance(payload, dict):
            # The live file was damaged; the last good copy still has the key.
            storage.heal(path, payload)
        elif source == "unreadable":
            quarantine_file(path)
        raw: dict = payload if isinstance(payload, dict) else {}
        for field_name in cls.__dataclass_fields__:
            value = raw.get(field_name)
            if isinstance(value, str):
                setattr(settings, field_name, value.strip())
        env_key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
        if env_key:
            settings.api_key = env_key
        if not settings.base_url:
            settings.base_url = DEFAULT_BASE_URL
        if not settings.model:
            settings.model = DEFAULT_MODEL
        if not settings.anki_url:
            settings.anki_url = DEFAULT_ANKI_URL
        return settings

    def save(self, path: Path | None = None) -> None:
        path = path or data_dir() / CONFIG_FILENAME
        storage.write_json(path, asdict(self))

    # -- API surface -----------------------------------------------------

    def public(self) -> dict:
        """Never send the raw key back to the browser."""
        return {
            "has_key": bool(self.api_key),
            "key_hint": self.api_key[-4:] if len(self.api_key) >= 8 else "",
            "base_url": self.base_url,
            "model": self.model,
            "anki_url": self.anki_url,
            "default_deck": self.default_deck,
            "default_tags": self.default_tags,
        }

    def update(self, payload: dict) -> None:
        def clean_text(key: str, *, max_len: int = 200) -> str:
            value = payload.get(key)
            if value is None:
                return getattr(self, key)
            if not isinstance(value, str):
                raise ValueError(f"{key} must be text.")
            return value.strip()[:max_len]

        if "api_key" in payload:
            key = payload["api_key"]
            if not isinstance(key, str):
                raise ValueError("API key must be text.")
            key = key.strip()
            if key:
                self.api_key = key[:400]
        if payload.get("clear_api_key"):
            self.api_key = ""

        base_url = clean_text("base_url").rstrip("/")
        if base_url:
            if not base_url.startswith(("http://", "https://")):
                raise ValueError("DeepSeek base URL must start with http:// or https://.")
            try:
                httpx.URL(base_url)
            except httpx.InvalidURL as exc:
                raise ValueError("That DeepSeek base URL isn't a valid URL.") from exc
            self.base_url = base_url
        model = clean_text("model", max_len=100)
        if model:
            self.model = model
        anki_url = clean_text("anki_url").rstrip("/")
        if anki_url:
            if not anki_url.startswith(("http://", "https://")):
                raise ValueError("AnkiConnect URL must start with http:// or https://.")
            try:
                httpx.URL(anki_url)
            except httpx.InvalidURL as exc:
                raise ValueError("That AnkiConnect URL isn't a valid URL.") from exc
            self.anki_url = anki_url
        deck = clean_text("default_deck", max_len=80)
        if deck:
            self.default_deck = deck
        tags = clean_text("default_tags", max_len=200)
        if "default_tags" in payload:
            self.default_tags = tags
