"""Support bundle: what a maintainer needs to diagnose a failure.

Deliberately narrow. It carries the shape of the installation — versions,
counts, which engines are available, the tail of the log — and none of the
student's content: no card text, no page text, no API key, no directory names.
"""

from __future__ import annotations

import io
import json
import platform
import time
import zipfile
from pathlib import Path

from . import __version__
from .logging_setup import LOG_FILENAME

README = """Anki Scribe diagnostics
=======================

diagnostics.json  Versions, counts and settings with the API key removed.
anki-scribe.log   The last few days of log lines (if logging had started).

What is NOT in here: card text, extracted page text, your API key, or the
folder names your lectures live in. File names are shortened to base names
because that is usually enough to identify a document.
"""


def _host(url: str) -> str:
    """scheme://host only — never a path, query or credentials."""
    text = str(url or "")
    if "://" not in text:
        return ""
    scheme, rest = text.split("://", 1)
    host = rest.split("/", 1)[0]
    if "@" in host:
        host = host.rsplit("@", 1)[-1]
    return f"{scheme}://{host}"


def _documents(store) -> list[dict]:
    rows = []
    try:
        for summary in store.list():
            pages = summary.get("pages") or []
            rows.append(
                {
                    "kind": summary.get("kind"),
                    "filename": summary.get("filename"),
                    "pageCount": summary.get("pageCount"),
                    "segmentCount": summary.get("segmentCount"),
                    "needsOcrPages": sum(1 for page in pages if page.get("needsOcr")),
                }
            )
    except Exception as exc:  # a broken store must not break the bundle
        rows.append({"error": str(exc)})
    return rows


def snapshot(settings, store, sent, drafts, library) -> dict:
    try:
        draft_counts = drafts.counts()
    except Exception:
        draft_counts = {}
    try:
        sent_rows = sent.sources()
    except Exception:
        sent_rows = []
    try:
        library_snapshot = library.snapshot()
    except Exception:
        library_snapshot = {"groups": [], "files": []}

    files = library_snapshot.get("files", [])
    return {
        "generatedAt": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "app": {
            "name": "anki-scribe",
            "version": __version__,
            "python": platform.python_version(),
            "platform": platform.platform(),
        },
        "settings": {
            "hasKey": bool(settings.api_key),
            "keyHint": settings.api_key[-4:] if len(settings.api_key) >= 8 else "",
            "baseUrl": _host(settings.base_url),
            "model": settings.model,
            "ankiUrl": _host(settings.anki_url),
            "defaultDeck": settings.default_deck,
            "defaultTags": settings.default_tags,
        },
        "documents": _documents(store),
        "drafts": {
            "sources": len(draft_counts),
            "cards": sum(draft_counts.values()),
        },
        "sent": {
            "sources": len(sent_rows),
            "cards": sum(int(row.get("count", 0)) for row in sent_rows),
        },
        "library": {
            "groups": len(library_snapshot.get("groups", [])),
            "files": len(files),
            "missing": sum(1 for item in files if not item.get("exists", True)),
        },
    }


def bundle(payload: dict, log_file: Path | None = None) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            "diagnostics.json", json.dumps(payload, indent=2, ensure_ascii=False)
        )
        archive.writestr("README.txt", README)
        if log_file is not None and Path(log_file).is_file():
            try:
                archive.write(log_file, LOG_FILENAME)
            except OSError:
                pass
    return buffer.getvalue()
