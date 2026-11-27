"""FastAPI surface for Anki Scribe."""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import re
import uuid
from datetime import date
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field
from starlette.middleware.trustedhost import TrustedHostMiddleware

from . import (
    ai_answers,
    anki,
    answers,
    batch_jobs,
    cards_quality,
    chapters,
    diagnostics,
    figures,
    images,
    llm,
    objectives,
    picker,
    planner,
    reviews,
    split,
    study,
)
from .config import Settings, data_dir, data_fingerprint
from .drafts import DraftStore
from .library import UNSORTED_ID, Library, LibraryError
from .logging_setup import log_path
from .masks import MaskStore
from .sent import SentStore
from .store import MAX_UPLOAD_BYTES, Store

logger = logging.getLogger("anki_scribe")

STATIC_DIR = Path(__file__).resolve().parent / "static"
ALLOWED_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp"}
ALLOWED_TRANSCRIPT_SUFFIXES = {".srt", ".vtt", ".txt", ".md"}
ALLOWED_BOOK_SUFFIXES = {".epub"}
ALLOWED_DOCUMENT_SUFFIXES = {".pdf", ".pptx"} | ALLOWED_IMAGE_SUFFIXES | ALLOWED_BOOK_SUFFIXES

# What the sent ledger keeps about a card's origin. A whitelist, not the whole
# client object: the ledger is long-lived and should not inherit new client
# fields by accident.
SOURCE_KEYS = (
    "kind",
    "label",
    "file",
    "pages",
    "segments",
    "location",
    "quote",
    "evidence",
    "chapterPath",
    "chapterTitle",
    "deckPath",
    "sourceTitle",
)


class GenerateBody(BaseModel):
    text: str = Field(min_length=1, max_length=20_000)
    mode: Literal["basic", "cloze"] = "basic"
    count: int | None = Field(default=None, ge=1, le=llm.MAX_CARDS)
    filename: str | None = None
    page: str | None = None
    whole_file: bool = False
    strict: bool = False
    style: str = Field(default=llm.DEFAULT_STYLE, max_length=40)


class FigureBody(BaseModel):
    page: int = Field(ge=0, le=10_000)
    x0: float
    y0: float
    x1: float
    y1: float


class RegenBody(BaseModel):
    text: str = Field(min_length=1, max_length=20_000)
    mode: Literal["basic", "cloze"] = "basic"
    nudge: str = Field(default=llm.DEFAULT_NUDGE, max_length=20)
    question: str = Field(default="", max_length=2000)
    answer: str = Field(default="", max_length=4000)
    cloze_text: str = Field(default="", max_length=2000)
    filename: str | None = None
    style: str = Field(default=llm.DEFAULT_STYLE, max_length=40)


class PushCard(BaseModel):
    mode: Literal["basic", "cloze", "figure"] = "basic"
    question: str = ""
    answer: str = ""
    text: str = ""
    extra: str = ""
    tags: list[str] = Field(default_factory=list)
    uid: str = Field(default="", max_length=64)
    type: str = Field(default="", max_length=40)
    evidence: str = Field(default="", max_length=500)
    sourceLabel: str = Field(default="", max_length=200)
    sourcePage: str = Field(default="", max_length=80)
    source: dict | None = None
    figure: dict | None = None
    image: dict | None = None


class PushBody(BaseModel):
    deck: str = Field(min_length=1, max_length=200)
    tags: str = Field(default="", max_length=200)
    cards: list[PushCard] = Field(min_length=1, max_length=100)
    allow_blocked: bool = False
    source_path: str = Field(default="", max_length=4096)
    filename: str = Field(default="", max_length=500)


class DraftBody(BaseModel):
    path: str = Field(min_length=1, max_length=4096)
    filename: str = Field(default="", max_length=500)
    cards: list[dict] = Field(default_factory=list, max_length=2000)


class AnswerCardBody(BaseModel):
    model_config = ConfigDict(extra="ignore")

    uid: str = Field(default="", max_length=120)
    mode: str = Field(default="basic", max_length=20)
    type: str = Field(default="", max_length=40)
    text: str = Field(default="", max_length=8000)
    question: str = Field(default="", max_length=8000)
    answer: str = Field(default="", max_length=8000)
    source: dict = Field(default_factory=dict)


class AnswerMasksBody(BaseModel):
    cards: list[AnswerCardBody] = Field(default_factory=list, max_length=answers.MAX_CARDS)


class AiAnswerMasksBody(BaseModel):
    cards: list[AnswerCardBody] = Field(
        default_factory=list, max_length=ai_answers.MAX_AI_CARDS
    )


class MaskBody(BaseModel):
    path: str = Field(min_length=1, max_length=4096)
    masks: list[dict] = Field(default_factory=list, max_length=3000)


class PlanBody(BaseModel):
    start: date
    deadline: date
    cards: int = Field(ge=1, le=planner.MAX_CARDS)
    minutes: int = Field(default=60, ge=5, le=1440)
    weekdays: list[int] = Field(
        default_factory=lambda: [0, 1, 2, 3, 4, 5, 6],
        min_length=1,
        max_length=7,
    )
    buffer_days: int = Field(default=2, ge=0, le=60)
    retention: float = Field(default=0.9, ge=0.70, le=0.99)
    rating: int = Field(default=3, ge=2, le=4)
    new_seconds: int = Field(default=60, ge=5, le=600)
    review_seconds: int = Field(default=15, ge=3, le=600)


class PlanSourcesBody(BaseModel):
    file_ids: list[str] = Field(default_factory=list, max_length=200)


class BatchJobBody(BaseModel):
    file_ids: list[str] = Field(default_factory=list, max_length=200)
    mode: str = Field(default="basic", max_length=20)
    style: str = Field(default="balanced", max_length=40)
    strict: bool = False
    send_to_anki: bool = False
    deck: str = Field(default="", max_length=300)
    deck_mode: str = Field(default="parent", max_length=20)
    tags: str = Field(default="", max_length=500)


class StudyReviewBody(BaseModel):
    uid: str = Field(min_length=1, max_length=120)
    question: str = Field(default="", max_length=500)
    mode: str = Field(default="basic", max_length=20)
    rating: int = Field(ge=1, le=4)
    seconds: float = Field(default=0, ge=0, le=3600)


class StudySessionBody(BaseModel):
    at: float | None = None
    total: int = Field(default=0, ge=0, le=10_000)
    correct: int = Field(default=0, ge=0, le=10_000)
    seconds: float = Field(default=0, ge=0, le=86_400)
    streak: int = Field(default=0, ge=0, le=10_000)
    grades: dict[str, int] = Field(default_factory=dict)


class DeckBody(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    parent: str = Field(default="", max_length=200)


class RenameDeckBody(BaseModel):
    old: str = Field(min_length=1, max_length=200)
    new: str = Field(min_length=1, max_length=200)


class LibraryPickBody(BaseModel):
    group_id: str = Field(default=UNSORTED_ID, max_length=80)


class LibraryImportBody(BaseModel):
    paths: list[str] = Field(min_length=1, max_length=100)
    group_id: str = Field(default=UNSORTED_ID, max_length=80)


class LibraryMoveBody(BaseModel):
    group_id: str = Field(min_length=1, max_length=80)


class SplitBody(BaseModel):
    output_dir: str | None = Field(default=None, max_length=1024)


class CardImageBody(BaseModel):
    page: int = Field(ge=0, le=10_000)
    x0: float
    y0: float
    x1: float
    y1: float


class RevealBody(BaseModel):
    path: str = Field(min_length=1, max_length=1024)


class GroupBody(BaseModel):
    name: str = Field(min_length=1, max_length=80)


class SettingsBody(BaseModel):
    model_config = ConfigDict(extra="ignore")

    api_key: str | None = None
    clear_api_key: bool = False
    base_url: str | None = None
    model: str | None = None
    anki_url: str | None = None
    default_deck: str | None = None
    default_tags: str | None = None


def _page_or_404(store: Store, doc_id: str, index: int):
    try:
        doc = store.require(doc_id)
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc
    if index < 0 or index >= len(doc.pages):
        raise HTTPException(404, "That page doesn't exist.")
    return doc, doc.pages[index]


def _card_media(store: Store, cards: list[dict]) -> list[dict]:
    """Read the PNGs a batch references, as base64 for AnkiConnect.

    Figures carry a masked/revealed pair; an attached image is a single file.
    Both are uploaded before the notes that point at them.
    """
    wanted: list[tuple[str, str]] = []
    for card in cards:
        figure = card.get("figure")
        if isinstance(figure, dict):
            doc_id = str(figure.get("docId") or "")
            for side in ("masked", "revealed"):
                name = str(figure.get(side) or "")
                if figures.valid_name(name):
                    wanted.append((doc_id, name))
        image = card.get("image")
        if isinstance(image, dict):
            name = str(image.get("name") or "")
            if images.valid_name(name):
                wanted.append((str(image.get("docId") or ""), name))

    media: list[dict] = []
    seen: set[str] = set()
    for doc_id, name in wanted:
        if not doc_id or name in seen:
            continue
        try:
            doc = store.require(doc_id)
        except KeyError:
            continue
        path = doc.directory / name
        if not path.is_file():
            continue
        try:
            data = base64.b64encode(path.read_bytes()).decode("ascii")
        except OSError:
            continue
        seen.add(name)
        media.append({"filename": name, "data": data})
    return media


def _compose_deck_name(parent: str, name: str) -> str:
    parts = [
        part.strip()
        for part in f"{parent}::{name}".split("::")
        if part.strip()
    ]
    if not parts:
        raise ValueError("Enter a deck name.")
    full = "::".join(parts)
    if len(full) > 200:
        raise ValueError("That deck path is too long.")
    if any(ord(character) < 32 for character in full):
        raise ValueError("Deck names can't contain line breaks or tabs.")
    return full


def _fingerprint(card: dict) -> str:
    """Stable hash of a card's front, used to spot a re-push later."""
    base = card.get("text") if card.get("mode") == "cloze" else card.get("question")
    text = str(base or "")
    text = re.sub(r"\{\{c\d+::(.+?)\}\}", r"\1", text)
    text = re.sub(r"[^0-9a-z]+", " ", text.casefold()).strip()
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:16]


def _ledger_entry(card: dict, note_id: int | None, deck: str) -> dict:
    """One durable record of a card that now lives in Anki."""
    raw_source = card.get("source")
    source = (
        {key: raw_source[key] for key in SOURCE_KEYS if key in raw_source}
        if isinstance(raw_source, dict)
        else {}
    )
    source["label"] = card.get("sourcePage") or card.get("sourceLabel") or source.get("label", "")
    source["evidence"] = card.get("evidence") or source.get("evidence", "")
    return {
        "id": str(card.get("uid") or ""),
        "noteId": note_id,
        "deck": deck,
        "mode": card.get("mode", "basic"),
        "type": cards_quality.card_type(card),
        "question": card.get("question") or card.get("text", ""),
        "answer": card.get("answer", ""),
        "fingerprint": _fingerprint(card),
        "tags": card.get("tags", []),
        "source": source,
    }


def _refuse_blocked(cards: list[dict]) -> None:
    """Stop a push before Anki is touched when a card cannot be answered.

    Runs before ``anki.build_notes`` so a refusal cannot create a deck, upload
    media or add a note: a blocked push leaves no trace in the collection.
    """
    report = cards_quality.blocked_cards(cards)
    count = report["count"]
    if not count:
        return
    raise HTTPException(
        status_code=400,
        detail={
            "error": "blocked_cards",
            "message": (
                f"{count} card{'' if count == 1 else 's'} "
                f"{'has' if count == 1 else 'have'} a blocking quality fault."
            ),
            "blocked": report["cards"],
        },
    )


def create_app(
    store: Store | None = None,
    settings: Settings | None = None,
    library: Library | None = None,
    drafts: DraftStore | None = None,
    sent: SentStore | None = None,
    mask_store: MaskStore | None = None,
) -> FastAPI:
    app = FastAPI(
        title="Anki Scribe",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    # Binding to 127.0.0.1 is not a security boundary: DNS rebinding makes this
    # API same-origin for a hostile page. Rejecting any Host that is not this
    # machine is the control that closes it.
    app.add_middleware(
        TrustedHostMiddleware,
        allowed_hosts=["127.0.0.1", "localhost"],
    )

    @app.middleware("http")
    async def revalidate_static_files(request, call_next):
        # Local JS changes on every update; a stale cached documents.js used to
        # break PDF loading after a restart. Revalidate static files so the UI
        # picks up the matching client immediately.
        response = await call_next(request)
        if request.url.path.startswith("/static/"):
            response.headers["Cache-Control"] = "no-cache"
        return response

    app.state.store = store or Store()
    app.state.settings = settings or Settings.load()
    app.state.library = library or Library()
    app.state.drafts = drafts or DraftStore()
    app.state.sent = sent or SentStore()
    app.state.masks = mask_store or MaskStore()
    app.state.batch_jobs = batch_jobs.BatchJobStore(
        app.state.store,
        app.state.library,
        app.state.drafts,
        app.state.sent,
        app.state.settings,
        path=app.state.store.root.parent / "batch_jobs.json",
    )
    app.state.batch_jobs.resume()
    app.state.reviews = reviews.ReviewStore(
        path=app.state.store.root.parent / "study_reviews.json"
    )
    # Automatic masks are a pure function of the document and its cards, but
    # computing them walks every page. Toggling study mode on and off should
    # feel instant, so the last few results stay in memory.
    app.state.answer_cache = {}
    app.state.ai_answer_cache = {}

    @app.exception_handler(Exception)
    async def unhandled_error(request, exc):  # pragma: no cover - production path
        reference = uuid.uuid4().hex[:6]
        logger.exception("unhandled ref=%s path=%s", reference, request.url.path)
        return JSONResponse(
            status_code=500,
            content={
                "detail": f"Something went wrong inside Anki Scribe (ref {reference})."
            },
        )

    @app.get("/", include_in_schema=False)
    def index() -> FileResponse:
        return FileResponse(
            STATIC_DIR / "index.html",
            headers={"Cache-Control": "no-cache"},
        )

    @app.get("/favicon.svg", include_in_schema=False)
    def favicon() -> FileResponse:
        return FileResponse(STATIC_DIR / "favicon.svg", media_type="image/svg+xml")

    @app.get("/api/health")
    def health() -> dict:
        return {"ok": True, "app": "anki-scribe", "data": data_fingerprint()}

    # -- diagnostics -----------------------------------------------------

    def _diagnostic_payload() -> dict:
        return diagnostics.snapshot(
            app.state.settings,
            app.state.store,
            app.state.sent,
            app.state.drafts,
            app.state.library,
        )

    @app.get("/api/diagnostics")
    def get_diagnostics() -> dict:
        return _diagnostic_payload()

    @app.get("/api/diagnostics/bundle")
    def get_diagnostics_bundle() -> Response:
        data = diagnostics.bundle(_diagnostic_payload(), log_path(data_dir()))
        return Response(
            content=data,
            media_type="application/zip",
            headers={
                "Content-Disposition": 'attachment; filename="anki-scribe-diagnostics.zip"',
                "Cache-Control": "no-store",
            },
        )

    # -- documents -------------------------------------------------------

    def chapter_plan(doc) -> dict:
        """Chapters from the file's own contents, or from the model if it has none.

        A PDF with bookmarks or an EPUB with a table of contents needs no model
        call; an unstructured file gets one compact outline prompt instead of
        being sent whole.
        """
        plan = chapters.build_plan(doc)
        total = plan.get("segmentCount") if doc.kind == "transcript" else plan.get("pageCount")
        if (
            plan.get("strategy") == "fallback"
            and app.state.settings.api_key
            and isinstance(total, int)
            and total >= 8
        ):
            try:
                proposed = llm.identify_chapters(
                    app.state.settings,
                    plan.get("sourceTitle", doc.filename),
                    chapters.outline(doc),
                    plan.get("unit", "pages"),
                    total,
                )
                improved = chapters.plan_from_proposals(doc, proposed, plan)
                if improved:
                    plan = improved
            except Exception as exc:  # keep the local fallback
                plan["warning"] = f"Chapter planning model failed: {exc}"
        return plan

    @app.get("/api/documents")
    def documents() -> dict:
        return {"documents": app.state.store.list()}

    @app.get("/api/documents/{doc_id}")
    def document(doc_id: str) -> dict:
        try:
            return app.state.store.require(doc_id).summary()
        except KeyError as exc:
            raise HTTPException(404, str(exc)) from exc

    @app.post("/api/documents")
    def upload_document(file: UploadFile = File(...)) -> dict:
        original = Path(file.filename or "upload").name
        suffix = Path(original).suffix.lower()
        if suffix not in ALLOWED_DOCUMENT_SUFFIXES:
            raise HTTPException(
                415,
                "Use a PDF, EPUB, PowerPoint, PNG, JPG or WEBP file (HEIC isn't supported).",
            )
        incoming = data_dir() / "incoming"
        incoming.mkdir(parents=True, exist_ok=True)
        temp_path = incoming / f"{uuid.uuid4().hex}{suffix}"
        size = 0
        try:
            with temp_path.open("wb") as out:
                while chunk := file.file.read(512 * 1024):
                    size += len(chunk)
                    if size > MAX_UPLOAD_BYTES:
                        limit = MAX_UPLOAD_BYTES // (1024 * 1024)
                        raise HTTPException(413, f"That file is larger than {limit} MB.")
                    out.write(chunk)
            if size == 0:
                raise HTTPException(400, "That file is empty.")
            store_ = app.state.store
            try:
                if suffix == ".pdf":
                    doc = store_.create_pdf(temp_path, original)
                elif suffix == ".pptx":
                    doc = store_.create_presentation_path(temp_path, original)
                elif suffix == ".epub":
                    doc = store_.create_epub_path(temp_path, original)
                else:
                    doc = store_.create_image(temp_path, original)
            except ValueError as exc:
                raise HTTPException(400, str(exc)) from exc
            if any(page.needs_ocr for page in doc.pages):
                store_.start_ocr(doc)
        finally:
            temp_path.unlink(missing_ok=True)
        logger.info(
            "opened %s kind=%s pages=%s segments=%s",
            doc.filename,
            doc.kind,
            len(doc.pages),
            len(doc.segments),
        )
        return doc.summary()

    @app.get("/api/documents/{doc_id}/pages/{index}/image")
    def page_image(doc_id: str, index: int) -> FileResponse:
        doc, page = _page_or_404(app.state.store, doc_id, index)
        try:
            path = app.state.store.render_page(doc, index)
        except Exception as exc:
            raise HTTPException(500, f"Couldn't render that page: {exc}") from exc
        return FileResponse(
            path,
            media_type="image/png",
            headers={"Cache-Control": "private, max-age=3600"},
        )

    @app.get("/api/documents/{doc_id}/pages/{index}/lines")
    def page_lines(doc_id: str, index: int) -> dict:
        doc, page = _page_or_404(app.state.store, doc_id, index)
        try:
            lines, used_ocr = app.state.store.page_lines(doc, index)
        except Exception as exc:
            raise HTTPException(
                502, f"Couldn't read the text on this page: {exc}"
            ) from exc
        return {
            "page": index,
            "width": page.width,
            "height": page.height,
            "lines": lines,
            "ocr": used_ocr or page.ocr_done,
        }

    # -- automatic OCR ---------------------------------------------------

    @app.get("/api/documents/{doc_id}/ocr")
    def document_ocr_status(doc_id: str) -> dict:
        try:
            doc = app.state.store.require(doc_id)
        except KeyError as exc:
            raise HTTPException(404, str(exc)) from exc
        return app.state.store.ocr_status(doc)

    @app.post("/api/documents/{doc_id}/ocr")
    def document_ocr_start(doc_id: str) -> dict:
        try:
            doc = app.state.store.require(doc_id)
        except KeyError as exc:
            raise HTTPException(404, str(exc)) from exc
        return app.state.store.start_ocr(doc)

    @app.post("/api/documents/{doc_id}/ocr/cancel")
    def document_ocr_cancel(doc_id: str) -> dict:
        try:
            doc = app.state.store.require(doc_id)
        except KeyError as exc:
            raise HTTPException(404, str(exc)) from exc
        return app.state.store.cancel_ocr(doc)

    @app.post("/api/documents/{doc_id}/answer-masks")
    def document_answer_masks(doc_id: str, body: AnswerMasksBody) -> dict:
        """Where each card's answer sits on the page, for the PDF study view."""
        try:
            doc = app.state.store.require(doc_id)
        except KeyError as exc:
            raise HTTPException(404, str(exc)) from exc
        cards = [card.model_dump() for card in body.cards]
        cache = app.state.answer_cache
        signature = hashlib.sha1(
            json.dumps([doc_id, cards], sort_keys=True, ensure_ascii=False).encode("utf-8")
        ).hexdigest()
        if signature in cache:
            return cache[signature]
        try:
            result = answers.build_masks(
                doc,
                cards,
                page_lines=lambda page: app.state.store.page_lines(doc, page)[0],
            )
        except Exception as exc:
            logger.exception("answer masks failed doc=%s", doc_id)
            raise HTTPException(500, f"Couldn't find the answers on these pages: {exc}") from exc
        cache[signature] = result
        while len(cache) > 4:
            cache.pop(next(iter(cache)))
        logger.info(
            "answer masks doc=%s cards=%s masks=%s",
            doc_id,
            result["stats"]["cards"],
            result["stats"]["masks"],
        )
        return result

    @app.post("/api/documents/{doc_id}/ai-answer-masks")
    def document_ai_answer_masks(doc_id: str, body: AiAnswerMasksBody) -> dict:
        """Use the model to find answer quotes when the local matcher missed."""
        try:
            doc = app.state.store.require(doc_id)
        except KeyError as exc:
            raise HTTPException(404, str(exc)) from exc
        cards = [card.model_dump() for card in body.cards]
        if not cards:
            return {"masks": [], "stats": {"cards": 0, "masks": 0}}
        cache = app.state.ai_answer_cache
        signature = hashlib.sha1(
            json.dumps([doc_id, cards], sort_keys=True, ensure_ascii=False).encode("utf-8")
        ).hexdigest()
        if signature in cache:
            return cache[signature]
        try:
            result = ai_answers.build_ai_masks(
                doc,
                cards,
                app.state.settings,
                page_lines=lambda page: app.state.store.page_lines(doc, page)[0],
            )
        except llm.LLMError as exc:
            raise HTTPException(exc.status_code, str(exc)) from exc
        except Exception as exc:
            logger.exception("AI answer masks failed doc=%s", doc_id)
            raise HTTPException(500, f"Couldn't find answers with AI: {exc}") from exc
        cache[signature] = result
        while len(cache) > 4:
            cache.pop(next(iter(cache)))
        logger.info(
            "AI answer masks doc=%s cards=%s masks=%s calls=%s",
            doc_id,
            result["stats"].get("cards"),
            result["stats"].get("masks"),
            result["stats"].get("calls"),
        )
        return result

    @app.get("/api/documents/{doc_id}/coverage")
    def document_coverage(doc_id: str) -> dict:
        try:
            doc = app.state.store.require(doc_id)
        except KeyError as exc:
            raise HTTPException(404, str(exc)) from exc
        try:
            return app.state.store.coverage(doc)
        except Exception as exc:
            raise HTTPException(
                502, f"Couldn't read this document: {exc}"
            ) from exc

    @app.get("/api/documents/{doc_id}/chapters")
    def document_chapters(doc_id: str) -> dict:
        try:
            doc = app.state.store.require(doc_id)
        except KeyError as exc:
            raise HTTPException(404, str(exc)) from exc
        try:
            return chapter_plan(doc)
        except Exception as exc:
            raise HTTPException(502, f"Couldn't plan chapters: {exc}") from exc

    @app.post("/api/documents/{doc_id}/split")
    def split_chapters(doc_id: str, body: SplitBody | None = None) -> dict:
        """Write one file per chapter, so a book can be fed to a model piecewise."""
        try:
            doc = app.state.store.require(doc_id)
        except KeyError as exc:
            raise HTTPException(404, str(exc)) from exc
        try:
            plan = chapter_plan(doc)
            return split.split_document(
                app.state.store,
                doc,
                plan,
                body.output_dir if body else None,
            )
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        except Exception as exc:
            logger.exception("split failed doc=%s", doc_id)
            raise HTTPException(
                502, f"Couldn't split this file into chapters: {exc}"
            ) from exc

    @app.post("/api/reveal")
    def reveal_folder(body: RevealBody) -> dict:
        """Show a folder in Explorer; only ever called for our own output."""
        target = Path(body.path).expanduser()
        if not target.exists():
            raise HTTPException(404, "That folder no longer exists.")
        if os.name != "nt":
            raise HTTPException(501, "Opening a folder is only supported on Windows.")
        try:
            os.startfile(str(target))  # noqa: S606 - local file, user-initiated
        except OSError as exc:
            raise HTTPException(500, f"Couldn't open that folder: {exc}") from exc
        return {"opened": str(target)}

    @app.post("/api/documents/{doc_id}/figures")
    def create_figure(doc_id: str, body: FigureBody) -> dict:
        try:
            doc = app.state.store.require(doc_id)
        except KeyError as exc:
            raise HTTPException(404, str(exc)) from exc
        try:
            return figures.build(doc, body.page, body.model_dump())
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        except Exception as exc:
            logger.exception("figure failed page=%s", body.page)
            raise HTTPException(500, f"Couldn't build that figure: {exc}") from exc

    @app.get("/api/documents/{doc_id}/figures/{name}")
    def get_figure(doc_id: str, name: str) -> FileResponse:
        try:
            doc = app.state.store.require(doc_id)
        except KeyError as exc:
            raise HTTPException(404, str(exc)) from exc
        try:
            path = figures.figure_path(doc, name)
        except ValueError as exc:
            raise HTTPException(404, str(exc)) from exc
        return FileResponse(
            path,
            media_type="image/png",
            headers={"Cache-Control": "private, max-age=3600"},
        )

    # -- images attached to a card ---------------------------------------

    @app.post("/api/documents/{doc_id}/images/crop")
    def crop_card_image(doc_id: str, body: CardImageBody) -> dict:
        try:
            doc = app.state.store.require(doc_id)
        except KeyError as exc:
            raise HTTPException(404, str(exc)) from exc
        try:
            return images.crop(doc, body.page, body.model_dump())
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        except Exception as exc:
            logger.exception("image crop failed page=%s", body.page)
            raise HTTPException(500, f"Couldn't cut that image: {exc}") from exc

    @app.post("/api/documents/{doc_id}/images")
    def upload_card_image(doc_id: str, file: UploadFile = File(...)) -> dict:
        try:
            doc = app.state.store.require(doc_id)
        except KeyError as exc:
            raise HTTPException(404, str(exc)) from exc
        limit = images.MAX_UPLOAD_BYTES
        data = file.file.read(limit + 1)
        if len(data) > limit:
            raise HTTPException(
                413, f"That image is larger than {limit // (1024 * 1024)} MB."
            )
        try:
            return images.store_upload(doc, data)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        except Exception as exc:
            logger.exception("image upload failed")
            raise HTTPException(500, f"Couldn't keep that image: {exc}") from exc

    @app.get("/api/documents/{doc_id}/images/{name}")
    def get_card_image(doc_id: str, name: str) -> FileResponse:
        try:
            doc = app.state.store.require(doc_id)
        except KeyError as exc:
            raise HTTPException(404, str(exc)) from exc
        try:
            path = images.image_path(doc, name)
        except ValueError as exc:
            raise HTTPException(404, str(exc)) from exc
        return FileResponse(
            path,
            media_type="image/png",
            headers={"Cache-Control": "private, max-age=3600"},
        )

    @app.get("/api/documents/{doc_id}/objectives")
    def document_objectives(doc_id: str) -> dict:
        try:
            doc = app.state.store.require(doc_id)
        except KeyError as exc:
            raise HTTPException(404, str(exc)) from exc
        try:
            return {"objectives": objectives.detect(doc)}
        except Exception as exc:
            raise HTTPException(502, f"Couldn't read the objectives: {exc}") from exc

    @app.get("/api/documents/{doc_id}/extract")
    def extract_document(
        doc_id: str,
        max_chars: int = 6000,
        start_page: int | None = None,
        end_page: int | None = None,
        start_segment: int | None = None,
        end_segment: int | None = None,
    ) -> dict:
        try:
            doc = app.state.store.require(doc_id)
        except KeyError as exc:
            raise HTTPException(404, str(exc)) from exc
        try:
            return app.state.store.extract_chunks(
                doc,
                max_chars=max_chars,
                start_page=start_page,
                end_page=end_page,
                start_segment=start_segment,
                end_segment=end_segment,
            )
        except Exception as exc:
            raise HTTPException(
                502, f"Couldn't read this document: {exc}"
            ) from exc

    # -- draft persistence ----------------------------------------------

    @app.get("/api/drafts")
    def get_drafts(path: str) -> dict:
        try:
            return app.state.drafts.get(path)
        except Exception as exc:
            raise HTTPException(400, f"Couldn't read draft cards: {exc}") from exc

    @app.post("/api/drafts")
    def save_drafts(body: DraftBody) -> dict:
        try:
            return app.state.drafts.put(body.path, body.filename, body.cards)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        except Exception as exc:
            raise HTTPException(500, f"Couldn't save draft cards: {exc}") from exc

    # -- sent ledger -----------------------------------------------------

    @app.get("/api/sent")
    def get_sent(path: str) -> dict:
        try:
            return app.state.sent.get(path)
        except Exception as exc:
            raise HTTPException(400, f"Couldn't read sent history: {exc}") from exc

    @app.delete("/api/sent")
    def clear_sent(path: str) -> dict:
        try:
            app.state.sent.delete(path)
        except Exception as exc:
            raise HTTPException(500, f"Couldn't clear sent history: {exc}") from exc
        return {"cleared": True}

    # -- manual answer hides ---------------------------------------------

    @app.get("/api/masks")
    def get_masks(path: str) -> dict:
        try:
            return app.state.masks.get(path)
        except Exception as exc:
            raise HTTPException(400, f"Couldn't read hidden text: {exc}") from exc

    @app.post("/api/masks")
    def save_masks(body: MaskBody) -> dict:
        try:
            return app.state.masks.put(body.path, body.masks)
        except (TypeError, ValueError) as exc:
            raise HTTPException(400, f"That hidden text isn't valid: {exc}") from exc
        except Exception as exc:
            raise HTTPException(500, f"Couldn't save hidden text: {exc}") from exc

    @app.delete("/api/masks")
    def clear_masks(path: str) -> dict:
        try:
            app.state.masks.delete(path)
        except Exception as exc:
            raise HTTPException(500, f"Couldn't clear hidden text: {exc}") from exc
        return {"cleared": True}

    # -- study sheets ----------------------------------------------------

    def _study_response(body: study.StudyBody, suffix: str) -> Response:
        try:
            if suffix == "pdf":
                data = study.build_pdf(body)
                media_type = "application/pdf"
            else:
                data = study.build_html(body).encode("utf-8")
                media_type = "text/html; charset=utf-8"
        except Exception as exc:
            raise HTTPException(
                500, f"Couldn't build the study sheet: {exc}"
            ) from exc
        return Response(
            content=data,
            media_type=media_type,
            headers={
                "Content-Disposition": (
                    f'attachment; filename="{study.filename(body, suffix)}"'
                ),
                "Cache-Control": "no-store",
            },
        )

    @app.post("/api/study/pdf")
    def study_pdf(body: study.StudyBody) -> Response:
        return _study_response(body, "pdf")

    @app.post("/api/study/html")
    def study_html(body: study.StudyBody) -> Response:
        return _study_response(body, "html")

    # -- study plan ------------------------------------------------------

    @app.post("/api/plan")
    def make_plan(body: PlanBody) -> dict:
        """A day-by-day FSRS plan from an exam date and daily study time."""
        try:
            return planner.build_plan(
                planner.PlanInput(
                    start=body.start,
                    deadline=body.deadline,
                    cards=body.cards,
                    minutes_per_day=body.minutes,
                    weekdays=tuple(body.weekdays),
                    buffer_days=body.buffer_days,
                    retention=body.retention,
                    rating=body.rating,
                    new_seconds=body.new_seconds,
                    review_seconds=body.review_seconds,
                )
            )
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        except Exception as exc:
            logger.exception("study plan failed")
            raise HTTPException(500, f"Couldn't build the study plan: {exc}") from exc

    @app.post("/api/plan/sources")
    def plan_sources(body: PlanSourcesBody) -> dict:
        """Study-item counts for selected library files, without opening them."""
        rows: list[dict] = []
        for file_id in body.file_ids:
            try:
                file = app.state.library.get_file(file_id)
            except LibraryError:
                continue
            cards: list[dict] = []
            try:
                cards.extend(app.state.drafts.get(file.path).get("cards", []))
                cards.extend(app.state.sent.get(file.path).get("cards", []))
            except Exception:
                logger.exception("plan source read failed file=%s", file_id)
                continue
            counts = planner.item_counts(cards)
            try:
                masks = app.state.masks.get(file.path).get("masks", [])
            except Exception:
                masks = []
            manual = len(masks) if isinstance(masks, list) else 0
            counts["manual"] = manual
            counts["total"] += manual
            rows.append(
                {
                    "fileId": file.id,
                    "name": file.name,
                    "path": file.path,
                    **counts,
                }
            )
        total = {
            key: sum(int(row.get(key) or 0) for row in rows)
            for key in ("basic", "cloze", "figure", "manual", "total")
        }
        return {"files": rows, "total": total}

    @app.post("/api/batch-jobs")
    def create_batch_job(body: BatchJobBody) -> dict:
        try:
            return app.state.batch_jobs.create(
                body.file_ids,
                mode=body.mode,
                style=body.style,
                strict=body.strict,
                send_to_anki=body.send_to_anki,
                deck=body.deck,
                deck_mode=body.deck_mode,
                tags=body.tags,
            )
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.get("/api/batch-jobs")
    def list_batch_jobs() -> dict:
        return {
            "active": app.state.batch_jobs.active(),
            "jobs": app.state.batch_jobs.recent(),
        }

    @app.get("/api/batch-jobs/{job_id}")
    def get_batch_job(job_id: str) -> dict:
        try:
            return app.state.batch_jobs.status(job_id)
        except KeyError as exc:
            raise HTTPException(404, "That batch job no longer exists.") from exc

    @app.post("/api/batch-jobs/{job_id}/cancel")
    def cancel_batch_job(job_id: str) -> dict:
        try:
            return app.state.batch_jobs.cancel(job_id)
        except KeyError as exc:
            raise HTTPException(404, "That batch job no longer exists.") from exc

    # -- study-session history -------------------------------------------

    @app.get("/api/study")
    def study_snapshot() -> dict:
        return app.state.reviews.snapshot()

    @app.post("/api/study/review")
    def study_review(body: StudyReviewBody) -> dict:
        try:
            record = app.state.reviews.review(body.model_dump(), body.rating, body.seconds)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        return {"review": record, "stats": app.state.reviews.snapshot()["stats"]}

    @app.post("/api/study/session")
    def study_session(body: StudySessionBody) -> dict:
        entry = app.state.reviews.save_session(body.model_dump())
        return {"session": entry, "stats": app.state.reviews.snapshot()["stats"]}

    @app.delete("/api/study")
    def clear_study_history() -> dict:
        app.state.reviews.clear()
        return {"cleared": True}

    # -- generation ------------------------------------------------------

    @app.get("/api/ai/balance")
    def ai_balance() -> dict:
        try:
            return llm.get_balance(app.state.settings)
        except llm.LLMError as exc:
            raise HTTPException(exc.status_code, str(exc)) from exc

    @app.post("/api/generate")
    def generate(body: GenerateBody) -> dict:
        try:
            return llm.generate_cards(
                app.state.settings,
                body.text,
                mode=body.mode,
                count=body.count,
                filename=body.filename,
                page=body.page,
                whole_file=body.whole_file,
                strict=body.strict,
                style=body.style,
            )
        except llm.LLMError as exc:
            raise HTTPException(exc.status_code, str(exc)) from exc

    @app.post("/api/generate/one")
    def generate_one(body: RegenBody) -> dict:
        try:
            return llm.regenerate_card(
                app.state.settings,
                body.text,
                mode=body.mode,
                nudge=body.nudge,
                question=body.question,
                answer=body.answer,
                cloze_text=body.cloze_text,
                filename=body.filename,
                style=body.style,
            )
        except llm.LLMError as exc:
            raise HTTPException(exc.status_code, str(exc)) from exc

    # -- library ---------------------------------------------------------

    def library_snapshot() -> dict:
        """The library rows, annotated with how much work each source holds.

        Counts are looked up across the draft and sent stores so a lecture can
        show "42 sent · 3 drafts" without opening it. Composed here rather than
        inside Library so the library keeps knowing only about paths.
        """
        snapshot = app.state.library.snapshot()
        sent = {row["key"]: row["count"] for row in app.state.sent.sources()}
        drafts = app.state.drafts.counts()
        for file in snapshot.get("files", []):
            key = os.path.normcase(os.path.abspath(file.get("path", "")))
            file["sentCount"] = sent.get(key, 0)
            file["draftCount"] = drafts.get(key, 0)
        return snapshot

    @app.get("/api/library")
    def get_library() -> dict:
        return library_snapshot()

    @app.post("/api/library/pick")
    def pick_library_files(body: LibraryPickBody | None = None) -> dict:
        group_id = body.group_id if body else UNSORTED_ID
        try:
            paths = picker.pick_files()
        except picker.PickerError as exc:
            raise HTTPException(502, str(exc)) from exc
        added, errors = app.state.library.import_paths(paths, group_id)
        return {
            "library": library_snapshot(),
            "added": [file.public() for file in added],
            "errors": errors,
        }

    @app.post("/api/library/import")
    def import_library_files(body: LibraryImportBody) -> dict:
        added, errors = app.state.library.import_paths(body.paths, body.group_id)
        return {
            "library": library_snapshot(),
            "added": [file.public() for file in added],
            "errors": errors,
        }

    @app.post("/api/library/files/{file_id}/open")
    def open_library_file(file_id: str) -> dict:
        try:
            file = app.state.library.get_file(file_id)
        except LibraryError as exc:
            raise HTTPException(404, str(exc)) from exc
        path = Path(file.path)
        if not path.is_file():
            raise HTTPException(
                400,
                "That file is missing from its saved location. Put it back or remove it from the library.",
            )
        suffix = path.suffix.lower()
        if (
            suffix not in ALLOWED_DOCUMENT_SUFFIXES
            and suffix not in ALLOWED_TRANSCRIPT_SUFFIXES
        ):
            raise HTTPException(400, "That file type isn't supported.")
        # A textbook that is already in the cache opens instantly instead of
        # being extracted again on every click.
        existing = app.state.store.find_by_source(path)
        if existing is not None:
            app.state.library.touch(file_id)
            if any(page.needs_ocr for page in existing.pages):
                app.state.store.start_ocr(existing)
            summary = existing.summary()
            summary["libraryFileId"] = file.id
            return summary
        try:
            if suffix == ".pdf":
                doc = app.state.store.create_pdf_path(path, file.name)
            elif suffix == ".pptx":
                doc = app.state.store.create_presentation_path(path, file.name)
            elif suffix == ".epub":
                doc = app.state.store.create_epub_path(path, file.name)
            elif suffix in ALLOWED_TRANSCRIPT_SUFFIXES:
                doc = app.state.store.create_transcript_path(path, file.name)
            else:
                doc = app.state.store.create_image_path(path, file.name)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        except Exception as exc:
            raise HTTPException(502, f"Couldn't open that file: {exc}") from exc
        if any(page.needs_ocr for page in doc.pages):
            app.state.store.start_ocr(doc)
        app.state.library.touch(file_id)
        summary = doc.summary()
        summary["libraryFileId"] = file.id
        return summary

    @app.patch("/api/library/files/{file_id}")
    def move_library_file(file_id: str, body: LibraryMoveBody) -> dict:
        try:
            app.state.library.move_file(file_id, body.group_id)
        except LibraryError as exc:
            raise HTTPException(400, str(exc)) from exc
        return library_snapshot()

    @app.delete("/api/library/files/{file_id}")
    def remove_library_file(file_id: str) -> dict:
        try:
            app.state.library.remove_file(file_id)
        except LibraryError as exc:
            raise HTTPException(404, str(exc)) from exc
        return library_snapshot()

    @app.post("/api/library/groups")
    def create_library_group(body: GroupBody) -> dict:
        try:
            app.state.library.create_group(body.name)
        except LibraryError as exc:
            raise HTTPException(400, str(exc)) from exc
        return library_snapshot()

    @app.patch("/api/library/groups/{group_id}")
    def rename_library_group(group_id: str, body: GroupBody) -> dict:
        try:
            app.state.library.rename_group(group_id, body.name)
        except LibraryError as exc:
            raise HTTPException(400, str(exc)) from exc
        return library_snapshot()

    @app.delete("/api/library/groups/{group_id}")
    def delete_library_group(group_id: str) -> dict:
        try:
            app.state.library.delete_group(group_id)
        except LibraryError as exc:
            raise HTTPException(400, str(exc)) from exc
        return library_snapshot()

    # -- anki ------------------------------------------------------------

    @app.post("/api/anki/review-history")
    def anki_review_history(body: PlanSourcesBody) -> dict:
        files: list[dict] = []
        all_ids: list[int] = []
        source_by_note: dict[int, dict] = {}
        for file_id in body.file_ids:
            try:
                file = app.state.library.get_file(file_id)
            except LibraryError:
                continue
            cards = app.state.sent.get(file.path).get("cards", [])
            for card in cards:
                if not isinstance(card, dict) or not card.get("noteId"):
                    continue
                note_id = int(card["noteId"])
                source_by_note.setdefault(note_id, card.get("source") or {})
            ids = sorted(
                {
                    int(card["noteId"])
                    for card in cards
                    if isinstance(card, dict) and card.get("noteId")
                }
            )
            files.append({"fileId": file.id, "name": file.name, "notes": len(ids)})
            all_ids.extend(ids)
        try:
            history = anki.read_review_history(
                app.state.settings, sorted(set(all_ids))
            )
        except anki.AnkiError as exc:
            raise HTTPException(502, str(exc)) from exc
        for leech in history.get("leeches", []):
            leech["source"] = source_by_note.get(leech.get("noteId"), {})
        return {"files": files, **history}

    @app.get("/api/anki/status")
    def anki_status() -> dict:
        return anki.status(app.state.settings)

    @app.post("/api/anki/preflight")
    def anki_preflight(body: PushBody) -> dict:
        cards = [card.model_dump() for card in body.cards]
        if not body.allow_blocked:
            _refuse_blocked(cards)
        try:
            return anki.preflight(
                app.state.settings,
                deck=body.deck,
                cards=cards,
                extra_tags=body.tags,
            )
        except anki.AnkiError as exc:
            raise HTTPException(502, str(exc)) from exc

    @app.post("/api/anki/push")
    def anki_push(body: PushBody) -> dict:
        cards = [card.model_dump() for card in body.cards]
        if not body.allow_blocked:
            _refuse_blocked(cards)
        try:
            result = anki.push_cards(
                app.state.settings,
                deck=body.deck,
                cards=cards,
                extra_tags=body.tags,
                media=_card_media(app.state.store, cards),
            )
        except anki.AnkiError as exc:
            raise HTTPException(502, str(exc)) from exc

        note_ids = result.get("noteIds") or []
        logger.info(
            "push deck=%s cards=%s created=%s duplicates=%s",
            result["deck"],
            len(cards),
            result.get("created", 0),
            result.get("duplicates", 0),
        )
        entries = [
            _ledger_entry(card, note_ids[index] if index < len(note_ids) else None, result["deck"])
            for index, card in enumerate(cards)
        ]
        saved = False
        warning = ""
        if body.source_path and entries:
            try:
                app.state.sent.append(body.source_path, body.filename, entries)
                saved = True
            except OSError as exc:
                # The cards are in Anki; a failed ledger write must not look
                # like a failed push.
                warning = f"Sent history couldn't be saved: {exc}"
        result["ledger"] = {
            "saved": saved,
            "path": body.source_path,
            "cards": entries,
            "warning": warning,
        }
        return result

    @app.post("/api/anki/decks")
    def anki_create_deck(body: DeckBody) -> dict:
        try:
            full = _compose_deck_name(body.parent, body.name)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        try:
            anki.create_deck(app.state.settings, full)
            decks = anki.deck_names(app.state.settings)
        except anki.AnkiError as exc:
            raise HTTPException(502, str(exc)) from exc
        return {"name": full, "decks": decks}

    @app.post("/api/anki/decks/rename")
    def anki_rename_deck(body: RenameDeckBody) -> dict:
        old = body.old.strip()
        try:
            new = _compose_deck_name("", body.new)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        try:
            anki.rename_deck(app.state.settings, old, new)
            decks = anki.deck_names(app.state.settings)
        except anki.AnkiError as exc:
            raise HTTPException(502, str(exc)) from exc
        return {"name": new, "decks": decks}

    # -- settings --------------------------------------------------------

    @app.get("/api/settings")
    def get_settings() -> dict:
        return app.state.settings.public()

    @app.put("/api/settings")
    def put_settings(body: SettingsBody) -> dict:
        payload = body.model_dump(exclude_unset=True, exclude_none=True)
        try:
            app.state.settings.update(payload)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        app.state.settings.save()
        return app.state.settings.public()

    if STATIC_DIR.exists():
        app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    return app
