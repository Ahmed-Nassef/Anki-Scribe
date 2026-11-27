"""Persistent batch-generation jobs.

The Library's batch button used to drive a loop in the browser: closing the tab
stopped the run, and a crash lost everything after the current file. This module
moves that loop to the server. A job is persisted in ``batch_jobs.json`` and a
daemon thread processes one library file at a time: extract the file into
section-sized chunks, ask DeepSeek for cards, merge them into that file's drafts,
and record progress after every chunk.

If the app exits mid-run the job remains ``running`` in the JSON. On the next
startup :meth:`BatchJobStore.resume` re-queues it. A file is safe to retry: the
draft merge de-duplicates by question/cloze text, so cards generated before the
crash are not added twice.
"""

from __future__ import annotations

import re
import threading
import time
import uuid
from pathlib import Path
from typing import Any

from . import anki, cards_quality, llm, storage
from .config import data_dir
from .drafts import DraftStore
from .library import Library, LibraryError
from .sent import SentStore
from .store import Store

MAX_JOBS = 30
MAX_DRAFT_CARDS = 2000


def _card_key(card: dict) -> str:
    base = card.get("text") if card.get("mode") == "cloze" else card.get("question")
    return " ".join(str(base or "").lower().split())


def _error_is_fatal(message: str) -> bool:
    return bool(re.search(r"api key|settings|insufficient balance|401|402|429", message, re.I))


class BatchJobStore:
    def __init__(
        self,
        store: Store,
        library: Library,
        drafts: DraftStore,
        sent: SentStore,
        settings: Any,
        path: Path | None = None,
    ) -> None:
        self.store = store
        self.library = library
        self.drafts = drafts
        self.sent = sent
        self.settings = settings
        self.path = path or (data_dir() / "batch_jobs.json")
        self._lock = threading.RLock()
        self._jobs: dict[str, dict] = {}
        self._threads: dict[str, threading.Thread] = {}
        self._load()

    # -- persistence -----------------------------------------------------

    def _load(self) -> None:
        payload, source = storage.read_json(self.path)
        if source == "unreadable":
            return
        if not isinstance(payload, dict):
            return
        for job_id, job in payload.items():
            if isinstance(job, dict) and job.get("fileIds"):
                job["id"] = str(job_id)
                self._jobs[str(job_id)] = job

    def _save(self) -> None:
        with self._lock:
            ordered = sorted(
                self._jobs.items(),
                key=lambda item: float(item[1].get("updatedAt", 0)),
                reverse=True,
            )[:MAX_JOBS]
            self._jobs = dict(ordered)
            storage.write_json(self.path, self._jobs)

    # -- public API ------------------------------------------------------

    def create(
        self,
        file_ids: list[str],
        *,
        mode: str = "basic",
        style: str = "balanced",
        strict: bool = False,
        send_to_anki: bool = False,
        deck: str = "",
        deck_mode: str = "parent",
        tags: str = "",
        start: bool = True,
    ) -> dict:
        files: list[dict] = []
        for file_id in file_ids:
            try:
                file = self.library.get_file(file_id)
            except LibraryError as exc:
                raise ValueError(str(exc)) from exc
            if not Path(file.path).is_file():
                continue
            files.append({"id": file.id, "name": file.name})
        if not files:
            raise ValueError("None of those files are available on disk.")
        with self._lock:
            if any(
                job.get("status") in {"queued", "running"}
                for job in self._jobs.values()
            ):
                raise ValueError("A batch is already running; wait for it or stop it first.")
        job_id = uuid.uuid4().hex
        now = time.time()
        job = {
            "id": job_id,
            "status": "queued",
            "createdAt": now,
            "updatedAt": now,
            "fileIds": [file["id"] for file in files],
            "files": files,
            "options": {
                "mode": mode,
                "style": style,
                "strict": bool(strict),
                "send_to_anki": bool(send_to_anki),
                "deck": deck[:300],
                "deck_mode": "exact" if deck_mode == "exact" else "parent",
                "tags": tags[:500],
            },
            "nextFile": 0,
            "currentFile": None,
            "currentIndex": 0,
            "totalChunks": 0,
            "doneChunks": 0,
            "cards": 0,
            "sent": 0,
            "duplicates": 0,
            "blocked": 0,
            "results": [],
            "error": "",
            "cancelled": False,
        }
        with self._lock:
            self._jobs[job_id] = job
            self._save()
        if start:
            self._start(job_id)
        return self.status(job_id)

    def status(self, job_id: str) -> dict:
        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                raise KeyError(job_id)
            return {
                "id": job["id"],
                "status": job.get("status", "queued"),
                "fileIds": list(job.get("fileIds", [])),
                "files": list(job.get("files", [])),
                "nextFile": int(job.get("nextFile", 0)),
                "currentFile": job.get("currentFile"),
                "currentIndex": int(job.get("currentIndex", 0)),
                "totalChunks": int(job.get("totalChunks", 0)),
                "doneChunks": int(job.get("doneChunks", 0)),
                "cards": int(job.get("cards", 0)),
                "sent": int(job.get("sent", 0)),
                "duplicates": int(job.get("duplicates", 0)),
                "blocked": int(job.get("blocked", 0)),
                "results": list(job.get("results", [])),
                "error": str(job.get("error", "")),
                "createdAt": job.get("createdAt", 0),
                "updatedAt": job.get("updatedAt", 0),
                "percent": (
                    round(
                        100
                        * (
                            int(job.get("nextFile", 0))
                            + (
                                int(job.get("doneChunks", 0))
                                / max(1, int(job.get("totalChunks", 0)))
                                if int(job.get("totalChunks", 0))
                                else 0
                            )
                        )
                        / max(1, len(job.get("fileIds", [])))
                    )
                    if job.get("fileIds")
                    else 0
                ),
            }

    def active(self) -> list[dict]:
        with self._lock:
            ids = [
                job["id"]
                for job in self._jobs.values()
                if job.get("status") in {"queued", "running"}
            ]
        return [self.status(job_id) for job_id in ids]

    def recent(self, limit: int = 10) -> list[dict]:
        with self._lock:
            ids = [
                job["id"]
                for job in sorted(
                    self._jobs.values(),
                    key=lambda item: float(item.get("updatedAt", 0)),
                    reverse=True,
                )[: max(1, limit)]
            ]
        return [self.status(job_id) for job_id in ids]

    def cancel(self, job_id: str) -> dict:
        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                raise KeyError(job_id)
            if job.get("status") in {"queued", "running"}:
                job["cancelled"] = True
                job["status"] = "cancelled"
                job["updatedAt"] = time.time()
                self._save()
        return self.status(job_id)

    def resume(self) -> None:
        with self._lock:
            pending = [
                job_id
                for job_id, job in self._jobs.items()
                if job.get("status") in {"queued", "running"}
            ]
        for job_id in pending:
            self._start(job_id)

    # -- worker ----------------------------------------------------------

    def _start(self, job_id: str) -> None:
        with self._lock:
            existing = self._threads.get(job_id)
            if existing and existing.is_alive():
                return
            job = self._jobs.get(job_id)
            if not job or job.get("cancelled"):
                return
            if job.get("status") in {"completed", "error", "cancelled"}:
                return
            job["status"] = "running"
            job["updatedAt"] = time.time()
            self._save()
            thread = threading.Thread(
                target=self._run,
                args=(job_id,),
                name=f"batch-{job_id[:8]}",
                daemon=True,
            )
            self._threads[job_id] = thread
            thread.start()

    def run_sync(self, job_id: str) -> dict:
        """Test helper: run a job on the calling thread."""
        self._run(job_id)
        return self.status(job_id)

    def _run(self, job_id: str) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
        if not job:
            return
        try:
            self._run_job(job)
        except Exception as exc:  # pragma: no cover - last resort
            with self._lock:
                job["status"] = "error"
                job["error"] = str(exc)
                job["updatedAt"] = time.time()
                self._save()

    def _run_job(self, job: dict) -> None:
        options = job.get("options") or {}
        mode = options.get("mode") if options.get("mode") in {"basic", "cloze"} else "basic"
        while True:
            with self._lock:
                if job.get("cancelled"):
                    job["status"] = "cancelled"
                    job["updatedAt"] = time.time()
                    self._save()
                    return
                index = int(job.get("nextFile", 0))
                files = list(job.get("fileIds", []))
            if index >= len(files):
                break
            file_id = files[index]
            try:
                file = self.library.get_file(file_id)
            except LibraryError as exc:
                self._record_file(job, index, file_id, "", 0, str(exc))
                continue
            with self._lock:
                job["currentFile"] = file.name
                job["currentIndex"] = index
                job["doneChunks"] = 0
                job["totalChunks"] = 0
                job["updatedAt"] = time.time()
                self._save()
            try:
                result = self._process_file(job, file, mode)
            except Exception as exc:
                self._record_file(
                    job,
                    index,
                    file.id,
                    file.name,
                    {"cards": 0, "sent": 0, "duplicates": 0, "blocked": 0},
                    str(exc),
                )
                if _error_is_fatal(str(exc)):
                    with self._lock:
                        job["status"] = "error"
                        job["error"] = str(exc)
                        job["updatedAt"] = time.time()
                        self._save()
                    return
                continue
            self._record_file(job, index, file.id, file.name, result, "")
        with self._lock:
            if job.get("cancelled"):
                job["status"] = "cancelled"
            else:
                job["status"] = "completed"
            job["currentFile"] = None
            job["updatedAt"] = time.time()
            self._save()

    def _record_file(
        self,
        job: dict,
        index: int,
        file_id: str,
        name: str,
        result: dict,
        error: str,
    ) -> None:
        with self._lock:
            results = job.setdefault("results", [])
            results.append(
                {
                    "fileId": file_id,
                    "name": name,
                    "cards": int(result.get("cards") or 0),
                    "sent": int(result.get("sent") or 0),
                    "duplicates": int(result.get("duplicates") or 0),
                    "blocked": int(result.get("blocked") or 0),
                    "warning": str(result.get("warning") or ""),
                    "ok": not error,
                    "error": error,
                }
            )
            job["nextFile"] = index + 1
            job["cards"] = int(job.get("cards", 0)) + int(result.get("cards") or 0)
            job["sent"] = int(job.get("sent", 0)) + int(result.get("sent") or 0)
            job["duplicates"] = int(job.get("duplicates", 0)) + int(
                result.get("duplicates") or 0
            )
            job["blocked"] = int(job.get("blocked", 0)) + int(
                result.get("blocked") or 0
            )
            job["currentFile"] = None
            job["doneChunks"] = 0
            job["totalChunks"] = 0
            job["updatedAt"] = time.time()
            self._save()

    def _open_file(self, file) -> Any:
        path = Path(file.path)
        existing = self.store.find_by_source(path)
        if existing is not None:
            return existing
        suffix = path.suffix.lower()
        if suffix == ".pdf":
            return self.store.create_pdf_path(path, file.name)
        if suffix == ".pptx":
            return self.store.create_presentation_path(path, file.name)
        if suffix == ".epub":
            return self.store.create_epub_path(path, file.name)
        if suffix in {".srt", ".vtt", ".txt", ".md"}:
            return self.store.create_transcript_path(path, file.name)
        return self.store.create_image_path(path, file.name)

    def _process_file(self, job: dict, file, mode: str) -> dict:
        doc = self._open_file(file)
        suffix = Path(file.path).suffix.lower()
        max_chars = 6000 if suffix in {".srt", ".vtt", ".txt", ".md"} else 3500
        extract = self.store.extract_chunks(doc, max_chars=max_chars)
        chunks = extract.get("chunks") if isinstance(extract, dict) else []
        if not isinstance(chunks, list):
            chunks = []
        with self._lock:
            job["totalChunks"] = len(chunks)
            job["doneChunks"] = 0
            job["updatedAt"] = time.time()
            self._save()
        existing = self.drafts.get(file.path).get("cards", [])
        if not isinstance(existing, list):
            existing = []
        seen = {_card_key(card) for card in existing if isinstance(card, dict)}
        added = 0
        all_fresh: list[dict] = []
        for position, chunk in enumerate(chunks, start=1):
            with self._lock:
                if job.get("cancelled"):
                    raise RuntimeError("Batch cancelled.")
            text = str(chunk.get("text") or "")
            if not text.strip():
                with self._lock:
                    job["doneChunks"] = position
                continue
            try:
                result = llm.generate_cards(
                    self.settings,
                    text,
                    mode=mode,
                    count=None,
                    filename=doc.filename,
                    page=str(chunk.get("label") or ""),
                    whole_file=True,
                    strict=bool((job.get("options") or {}).get("strict")),
                    style=str((job.get("options") or {}).get("style") or "balanced"),
                )
            except llm.LLMError as exc:
                if _error_is_fatal(str(exc)):
                    raise
                with self._lock:
                    job["doneChunks"] = position
                    job["error"] = str(exc)
                    job["updatedAt"] = time.time()
                    self._save()
                continue
            except Exception as exc:
                if _error_is_fatal(str(exc)):
                    raise
                with self._lock:
                    job["doneChunks"] = position
                    job["updatedAt"] = time.time()
                    self._save()
                continue
            pages = chunk.get("pages")
            segments = chunk.get("segments")
            source = {
                "kind": "transcript" if doc.kind == "transcript" else "chunk",
                "label": str(chunk.get("label") or ""),
                "file": doc.filename,
                "location": [],
                "pages": (
                    [int(pages[0]) - 1, int(pages[1]) - 1]
                    if isinstance(pages, list) and len(pages) >= 2
                    else []
                ),
                "segments": list(segments) if isinstance(segments, list) else [],
                "quote": "",
                "sourceTitle": Path(file.name).stem,
                "chapterPath": [],
                "chapterTitle": "",
                "deckPath": [Path(file.name).stem],
            }
            fresh: list[dict] = []
            for raw in result.get("cards", []) if isinstance(result, dict) else []:
                if not isinstance(raw, dict):
                    continue
                card = {
                    **raw,
                    "uid": uuid.uuid4().hex,
                    "mode": mode,
                    "selected": True,
                    "source": {
                        **source,
                        "evidence": str(raw.get("evidence") or ""),
                        "quote": str(raw.get("evidence") or ""),
                    },
                }
                key = _card_key(card)
                if not key or key in seen:
                    continue
                seen.add(key)
                fresh.append(card)
                added += 1
            if fresh:
                merged = existing + fresh
                if len(merged) > MAX_DRAFT_CARDS:
                    raise ValueError(
                        f"{file.name} already has {len(existing)} drafts; "
                        f"the batch would exceed {MAX_DRAFT_CARDS}."
                    )
                existing = merged
                self.drafts.put(file.path, file.name, existing)
                all_fresh.extend(fresh)
            with self._lock:
                job["doneChunks"] = position
                job["updatedAt"] = time.time()
                self._save()
        return self._push_fresh(
            file,
            all_fresh,
            job.get("options") or {},
            {"cards": added, "sent": 0, "duplicates": 0, "blocked": 0},
        )

    def _push_fresh(
        self, file, fresh: list[dict], options: dict, result: dict
    ) -> dict:
        """Push the cards generated for one file, if the batch asked for it."""
        if not options.get("send_to_anki") or not fresh:
            return result
        report = cards_quality.blocked_cards(fresh)
        result["blocked"] = int(report.get("count") or 0)
        blocked_uids = {
            str(card.get("uid") or "")
            for card, faults in zip(
                fresh, cards_quality.evaluate_batch(fresh)
            )
            if cards_quality.blocking_faults(faults)
        }
        eligible = [
            card
            for card in fresh
            if str(card.get("uid") or "") not in blocked_uids
        ]
        if not eligible:
            result["warning"] = (
                f"{result['blocked']} generated card"
                f"{'' if result['blocked'] == 1 else 's'} needed fixing before Anki."
            )
            return result
        base = (
            str(options.get("deck") or "").strip()
            or str(self.settings.default_deck or "").strip()
            or "Anki Scribe"
        )
        deck = (
            base
            if options.get("deck_mode") == "exact"
            else f"{base}::{Path(file.name).stem}"
        )
        tags = str(options.get("tags") or "")
        try:
            pushed = anki.push_cards(
                self.settings,
                deck,
                eligible,
                tags,
            )
        except anki.AnkiError as exc:
            result["warning"] = f"Cards stayed in drafts: {exc}"
            return result
        note_ids = list(pushed.get("noteIds") or [])
        entries: list[dict] = []
        created_uids: set[str] = set()
        for card, note_id in zip(eligible, note_ids):
            if not note_id:
                continue
            uid = str(card.get("uid") or "")
            created_uids.add(uid)
            entries.append(
                {
                    "id": uid,
                    "noteId": int(note_id),
                    "deck": deck,
                    "mode": str(card.get("mode") or "basic"),
                    "type": cards_quality.card_type(card),
                    "question": str(card.get("question") or card.get("text") or ""),
                    "answer": str(card.get("answer") or ""),
                    "tags": card.get("tags") or [],
                    "source": card.get("source") or {},
                }
            )
        if entries:
            try:
                self.sent.append(file.path, file.name, entries)
            except OSError as exc:
                result["warning"] = f"Sent cards, but the ledger failed: {exc}"
            existing = self.drafts.get(file.path).get("cards", [])
            if isinstance(existing, list):
                self.drafts.put(
                    file.path,
                    file.name,
                    [
                        card
                        for card in existing
                        if str(card.get("uid") or "") not in created_uids
                    ],
                )
        result["sent"] = int(pushed.get("created") or 0)
        result["duplicates"] = int(pushed.get("duplicates") or 0)
        return result
