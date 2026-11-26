"""Uploaded documents: PDF text extraction, page rendering and OCR fallback."""

from __future__ import annotations

import json
import math
import os
import re
import shutil
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

import pymupdf as fitz  # PyMuPDF
from PIL import Image, ImageOps

from . import formats
from .config import data_dir
from .epub import convert as convert_epub
from .ocr import ocr_lines
from .presentations import convert as convert_presentation
from .transcript import read_transcript

RENDER_SCALE = 2.0
MAX_UPLOAD_BYTES = 200 * 1024 * 1024
# A textbook is not a lecture handout: it can run to well over a thousand
# pages. Everything downstream is per page, so the ceiling only guards memory.
MAX_PAGES = 1500
MAX_DOCS = 15
MAX_IMAGE_SIDE = 4000
# A long book would otherwise keep hundreds of page images on disk. Only the
# newest stay; a page that was scrolled away is rendered again when reopened.
LARGE_DOCUMENT_PAGES = 400
PAGE_IMAGE_CACHE = 60
# Table detection is a layout analysis at roughly half a second a page. It is
# worth it on a lecture, where a table is exam material; on a 600-page book it
# would turn one split into ten minutes, so books are read as plain lines.
TABLE_DETECTION_PAGES = 250
# A PDF page of 3000 pt is 41 inches; anything larger is not a lecture handout
# and would allocate gigabytes when rendered at 2x.
MAX_PAGE_POINTS = 3000

_LIGATURES = {
    "\ufb00": "ff",
    "\ufb01": "fi",
    "\ufb02": "fl",
    "\ufb03": "ffi",
    "\ufb04": "ffl",
}


def normalize_text(text: str) -> str:
    for bad, good in _LIGATURES.items():
        text = text.replace(bad, good)
    text = text.replace("\u00ad", "")  # soft hyphen
    return re.sub(r"\s+", " ", text).strip()


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _mtime(path: Path) -> float:
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0


def extract_pdf_lines(page: "fitz.Page", scale: float, width: int, height: int) -> list[dict]:
    """One entry per visual text line, in the PDF's reading order."""
    try:
        # The default "dict" flags include TEXT_PRESERVE_IMAGES, which decodes
        # every picture on the page only for this function to discard it: 120 ms
        # a page on an illustrated textbook against 6 ms without the images.
        flags = fitz.TEXTFLAGS_DICT & ~fitz.TEXT_PRESERVE_IMAGES
        data = page.get_text("dict", flags=flags)
    except Exception:
        return []
    lines: list[dict] = []
    for block in data.get("blocks", []):
        if block.get("type") != 0:
            continue
        for line in block.get("lines", []):
            spans = [s for s in line.get("spans", []) if s.get("text")]
            if not spans:
                continue
            text = normalize_text("".join(s["text"] for s in spans))
            if not text:
                continue
            x0, y0, x1, y1 = line.get("bbox", (0, 0, 0, 0))
            x0, x1 = sorted((x0 * scale, x1 * scale))
            y0, y1 = sorted((y0 * scale, y1 * scale))
            if x1 - x0 < 1 or y1 - y0 < 1:
                continue
            # A formula is set in a mathematics font, or is mostly symbols.
            # The flag travels with the line so composition can send it as
            # $...$ instead of a sentence full of stray glyphs.
            math_chars = sum(
                len(s["text"]) for s in spans if formats.MATH_FONT.search(s.get("font", ""))
            )
            ratio = math_chars / max(1, sum(len(s["text"]) for s in spans))
            is_math = formats.looks_like_math(formats.normalise_math(text), ratio)
            entry = {
                "text": text,
                "x0": round(_clamp(x0, 0, width), 2),
                "y0": round(_clamp(y0, 0, height), 2),
                "x1": round(_clamp(x1, 0, width), 2),
                "y1": round(_clamp(y1, 0, height), 2),
            }
            if is_math:
                entry["math"] = True
            lines.append(entry)
    return lines


def _table_markdown(rows: list[list[str]]) -> str:
    cleaned: list[list[str]] = []
    for row in rows:
        cells = [
            re.sub(r"\s+", " ", str(cell or "")).replace("|", "\\|").strip()
            for cell in row
        ]
        if any(cells):
            cleaned.append(cells)
    if len(cleaned) < 2:
        return ""
    width = max(len(row) for row in cleaned)
    cleaned = [row + [""] * (width - len(row)) for row in cleaned]
    lines = [
        "| " + " | ".join(cleaned[0]) + " |",
        "| " + " | ".join(["---"] * width) + " |",
    ]
    lines.extend("| " + " | ".join(row) + " |" for row in cleaned[1:])
    return "\n".join(lines)


def _line_in_bbox(line: dict, bbox: tuple[float, float, float, float]) -> bool:
    cx = (line["x0"] + line["x1"]) / 2
    cy = (line["y0"] + line["y1"]) / 2
    return bbox[0] - 2 <= cx <= bbox[2] + 2 and bbox[1] - 2 <= cy <= bbox[3] + 2


def _split_text(text: str, limit: int) -> list[str]:
    """Split a page's text into section-sized chunks, preferring line breaks."""
    if len(text) <= limit:
        return [text]
    parts: list[str] = []
    current: list[str] = []
    length = 0
    for line in text.splitlines():
        if len(line) > limit:
            if current:
                parts.append("\n".join(current))
                current, length = [], 0
            parts.extend(line[start : start + limit] for start in range(0, len(line), limit))
            continue
        if current and length + len(line) + 1 > limit:
            parts.append("\n".join(current))
            current, length = [], 0
        current.append(line)
        length += len(line) + 1
    if current:
        parts.append("\n".join(current))
    return parts or [text[:limit]]


@dataclass
class Page:
    index: int
    width: int
    height: int
    lines: list[dict] = field(default_factory=list)
    needs_ocr: bool = False
    ocr_done: bool = False

    def to_dict(self) -> dict:
        return {
            "index": self.index,
            "width": self.width,
            "height": self.height,
            "lines": self.lines,
            "needs_ocr": self.needs_ocr,
            "ocr_done": self.ocr_done,
        }

    @classmethod
    def from_dict(cls, raw: dict) -> "Page":
        return cls(
            index=int(raw["index"]),
            width=int(raw["width"]),
            height=int(raw["height"]),
            lines=[line for line in raw.get("lines", []) if line.get("text")],
            needs_ocr=bool(raw.get("needs_ocr", False)),
            ocr_done=bool(raw.get("ocr_done", False)),
        )


@dataclass
class Document:
    id: str
    filename: str
    kind: str  # "pdf" | "image" | "transcript"
    created_at: float
    pages: list[Page]
    root: Path
    source_path: str = ""
    segments: list[dict] = field(default_factory=list)
    # Where the pages came from. "pptx" and "epub" are synthetic PDFs: the
    # page text is the deck's or the book's own, not a PDF text layer.
    format: str = ""
    # The file on disk the user opened, and when it was last read. Reopening a
    # remembered 700-page book must not extract it all over again.
    origin_path: str = ""
    origin_mtime: float = 0.0

    @property
    def directory(self) -> Path:
        return self.root / self.id

    @property
    def duration(self) -> float:
        ends = [float(segment["end"]) for segment in self.segments if segment.get("end") is not None]
        return max(ends) if ends else 0.0

    @property
    def has_timestamps(self) -> bool:
        return any(segment.get("start") is not None for segment in self.segments)

    def open_path(self) -> Path:
        return self.source

    @property
    def source(self) -> Path:
        if self.source_path:
            return Path(self.source_path)
        return self.directory / "source.pdf"

    def to_meta(self) -> dict:
        return {
            "id": self.id,
            "filename": self.filename,
            "kind": self.kind,
            "format": self.format,
            "created_at": self.created_at,
            "source_path": self.source_path,
            "origin_path": self.origin_path,
            "origin_mtime": self.origin_mtime,
            "pages": [page.to_dict() for page in self.pages],
            "segments": self.segments,
        }

    def summary(self) -> dict:
        return {
            "id": self.id,
            "filename": self.filename,
            "kind": self.kind,
            "format": self.format,
            "sourcePath": self.source_path,
            "originPath": self.origin_path,
            "pageCount": len(self.pages),
            "segmentCount": len(self.segments),
            "duration": self.duration,
            "hasTimestamps": self.has_timestamps,
            "createdAt": self.created_at,
            "pages": [
                {
                    "index": page.index,
                    "width": page.width,
                    "height": page.height,
                    "lineCount": len(page.lines),
                    "needsOcr": page.needs_ocr,
                }
                for page in self.pages
            ],
            "segments": self.segments if self.kind == "transcript" else [],
        }


class Store:
    def __init__(self, root: Path | None = None) -> None:
        self.root = root or (data_dir() / "documents")
        self.root.mkdir(parents=True, exist_ok=True)
        self._docs: dict[str, Document] = {}
        self._lock = threading.RLock()
        self._page_locks: dict[tuple[str, int], threading.RLock] = {}
        self._extract_cache: dict[tuple[str, int], dict] = {}
        self._load()

    # -- loading / persistence ------------------------------------------

    def _load(self) -> None:
        for meta_path in self.root.glob("*/meta.json"):
            try:
                raw = json.loads(meta_path.read_text(encoding="utf-8"))
                doc = Document(
                    id=raw["id"],
                    filename=raw.get("filename", "document"),
                    kind=raw["kind"],
                    created_at=float(raw.get("created_at", 0)),
                    pages=[Page.from_dict(p) for p in raw.get("pages", [])],
                    root=self.root,
                    source_path=str(raw.get("source_path") or ""),
                    segments=[
                        segment
                        for segment in raw.get("segments", [])
                        if isinstance(segment, dict) and segment.get("text")
                    ],
                    format=str(raw.get("format") or ""),
                    origin_path=str(raw.get("origin_path") or ""),
                    origin_mtime=float(raw.get("origin_mtime") or 0),
                )
                if not doc.source_path:
                    candidate = doc.directory / "source.pdf"
                    if candidate.exists():
                        doc.source_path = str(candidate)
                self._docs[doc.id] = doc
            except (KeyError, ValueError, TypeError, OSError):
                continue

    def _save_meta(self, doc: Document) -> None:
        meta_path = doc.directory / "meta.json"
        with self._lock:
            tmp = meta_path.with_suffix(".tmp")
            tmp.write_text(
                json.dumps(doc.to_meta(), ensure_ascii=False), encoding="utf-8"
            )
            tmp.replace(meta_path)

    def _page_lock(self, doc_id: str, index: int) -> threading.RLock:
        with self._lock:
            key = (doc_id, index)
            if key not in self._page_locks:
                self._page_locks[key] = threading.RLock()
            return self._page_locks[key]

    def _register(self, doc: Document) -> Document:
        with self._lock:
            self._docs[doc.id] = doc
        self._save_meta(doc)
        self._prune()
        return doc

    def _prune(self) -> None:
        with self._lock:
            docs = sorted(self._docs.values(), key=lambda d: d.created_at, reverse=True)
            for doc in docs[MAX_DOCS:]:
                self._docs.pop(doc.id, None)
                self._drop_extract_cache(doc.id)
                shutil.rmtree(doc.directory, ignore_errors=True)

    def _drop_extract_cache(self, doc_id: str) -> None:
        with self._lock:
            for key in [key for key in self._extract_cache if key[0] == doc_id]:
                self._extract_cache.pop(key, None)

    # -- creation --------------------------------------------------------

    def _new_directory(self) -> tuple[str, Path]:
        """Reserve a cache folder for a new document.

        A process started from a restricted or sandboxed terminal can read the
        data folder but not write to it. Without this guard the user just sees a
        bare ``WinError 5`` pointing at an opaque folder name.
        """
        doc_id = uuid.uuid4().hex
        directory = self.root / doc_id
        try:
            directory.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise ValueError(
                f"Anki Scribe couldn't write to its data folder ({self.root}). "
                "Check the folder's permissions; if a sandboxed tool marked this "
                "project folder low-integrity, see Troubleshooting in the README."
            ) from exc
        return doc_id, directory

    @staticmethod
    def _pdf_pages(pdf: "fitz.Document") -> list[Page]:
        if pdf.needs_pass:
            raise ValueError("That PDF is password-protected. Unlock it first.")
        if pdf.page_count == 0:
            raise ValueError("That PDF has no pages.")
        if pdf.page_count > MAX_PAGES:
            raise ValueError(f"That PDF has {pdf.page_count} pages (max {MAX_PAGES}).")
        pages: list[Page] = []
        for index, page in enumerate(pdf):
            rect = page.rect
            if rect.width > MAX_PAGE_POINTS or rect.height > MAX_PAGE_POINTS:
                raise ValueError(
                    f"Page {index + 1} is {rect.width:.0f}\u00d7{rect.height:.0f} pt. "
                    f"Pages larger than {MAX_PAGE_POINTS} pt on a side can't be rendered."
                )
            width = max(1, math.ceil(rect.width * RENDER_SCALE))
            height = max(1, math.ceil(rect.height * RENDER_SCALE))
            lines = extract_pdf_lines(page, RENDER_SCALE, width, height)
            pages.append(
                Page(
                    index=index,
                    width=width,
                    height=height,
                    lines=lines,
                    needs_ocr=not lines,
                )
            )
        return pages

    def create_pdf(self, src: Path, filename: str) -> Document:
        doc_id, directory = self._new_directory()
        try:
            with fitz.open(src) as pdf:
                pages = self._pdf_pages(pdf)
            shutil.move(str(src), str(directory / "source.pdf"))
        except Exception as exc:
            shutil.rmtree(directory, ignore_errors=True)
            if isinstance(exc, ValueError):
                raise
            raise ValueError(f"Couldn't read that PDF: {exc}") from exc
        doc = Document(
            id=doc_id,
            filename=Path(filename).name or "document.pdf",
            kind="pdf",
            created_at=time.time(),
            pages=pages,
            root=self.root,
            source_path=str(directory / "source.pdf"),
        )
        return self._register(doc)

    def create_pdf_path(self, src: Path, filename: str | None = None) -> Document:
        doc_id, directory = self._new_directory()
        source = Path(src)
        try:
            with fitz.open(source) as pdf:
                pages = self._pdf_pages(pdf)
        except Exception as exc:
            shutil.rmtree(directory, ignore_errors=True)
            if isinstance(exc, ValueError):
                raise
            raise ValueError(f"Couldn't read that PDF: {exc}") from exc
        doc = Document(
            id=doc_id,
            filename=Path(filename or source.name).name or "document.pdf",
            kind="pdf",
            created_at=time.time(),
            pages=pages,
            root=self.root,
            source_path=str(source),
            origin_path=str(source),
            origin_mtime=_mtime(source),
        )
        return self._register(doc)

    def create_image(
        self, src: Path, filename: str, source_path: Path | None = None
    ) -> Document:
        doc_id, directory = self._new_directory()
        target = directory / "page-0.png"
        try:
            with Image.open(src) as opened:
                image = ImageOps.exif_transpose(opened)
                if image.mode == "RGBA":
                    canvas = Image.new("RGB", image.size, "white")
                    canvas.paste(image, mask=image.split()[-1])
                    image = canvas
                else:
                    image = image.convert("RGB")
                image.thumbnail((MAX_IMAGE_SIDE, MAX_IMAGE_SIDE), Image.LANCZOS)
                width, height = image.size
                image.save(target, "PNG", optimize=True)
            try:
                lines = ocr_lines(target, width)
            except Exception as exc:  # pragma: no cover - depends on local OCR
                raise ValueError(f"Couldn't read text from that image: {exc}") from exc
        except Exception as exc:
            shutil.rmtree(directory, ignore_errors=True)
            if isinstance(exc, ValueError):
                raise
            raise ValueError(f"Couldn't open that image: {exc}") from exc
        page = Page(
            index=0,
            width=width,
            height=height,
            lines=lines,
            needs_ocr=False,
            ocr_done=True,
        )
        doc = Document(
            id=doc_id,
            filename=Path(filename).name or "photo.png",
            kind="image",
            created_at=time.time(),
            pages=[page],
            root=self.root,
            source_path=str(source_path) if source_path else "",
            origin_path=str(source_path) if source_path else "",
            origin_mtime=_mtime(source_path) if source_path else 0.0,
        )
        return self._register(doc)

    def create_image_path(self, src: Path, filename: str | None = None) -> Document:
        source = Path(src)
        return self.create_image(source, filename or source.name, source_path=source)

    def create_presentation_path(self, src: Path, filename: str | None = None) -> Document:
        """Import a slide deck by rendering it to a synthetic PDF first."""
        source = Path(src)
        doc_id, directory = self._new_directory()
        target = directory / "source.pdf"
        try:
            convert_presentation(source, target)
            with fitz.open(target) as pdf:
                pages = self._pdf_pages(pdf)
        except Exception as exc:
            shutil.rmtree(directory, ignore_errors=True)
            if isinstance(exc, ValueError):
                raise
            raise ValueError(f"Couldn't read that presentation: {exc}") from exc
        doc = Document(
            id=doc_id,
            filename=Path(filename or source.name).name or "slides.pptx",
            kind="pdf",
            created_at=time.time(),
            pages=pages,
            root=self.root,
            source_path=str(target),
            format="pptx",
            origin_path=str(source),
            origin_mtime=_mtime(source),
        )
        return self._register(doc)

    def create_epub_path(self, src: Path, filename: str | None = None) -> Document:
        """Import a book by laying its chapters out as a synthetic PDF.

        The EPUB's own table of contents becomes the PDF outline, so the page
        ranges handed to the model are real chapters rather than guessed ones.
        """
        source = Path(src)
        doc_id, directory = self._new_directory()
        target = directory / "source.pdf"
        try:
            book = convert_epub(source, target, RENDER_SCALE)
            pages = [
                Page(
                    index=int(item["index"]),
                    width=int(item["width"]),
                    height=int(item["height"]),
                    lines=item["lines"],
                )
                for item in book["pages"]
            ]
            if not pages:
                raise ValueError("That EPUB has no readable text.")
            if len(pages) > MAX_PAGES:
                raise ValueError(
                    f"That EPUB needs {len(pages)} pages of text (max {MAX_PAGES})."
                )
        except Exception as exc:
            shutil.rmtree(directory, ignore_errors=True)
            if isinstance(exc, ValueError):
                raise
            raise ValueError(f"Couldn't read that EPUB: {exc}") from exc
        doc = Document(
            id=doc_id,
            filename=Path(filename or source.name).name or "book.epub",
            kind="pdf",
            created_at=time.time(),
            pages=pages,
            root=self.root,
            source_path=str(target),
            format="epub",
            origin_path=str(source),
            origin_mtime=_mtime(source),
        )
        return self._register(doc)

    def create_transcript(self, src: Path, filename: str | None = None) -> Document:
        source = Path(src)
        try:
            segments = read_transcript(source)
        except ValueError:
            raise
        except Exception as exc:
            raise ValueError(f"Couldn't read that transcript: {exc}") from exc

        doc_id, directory = self._new_directory()
        try:
            doc = Document(
                id=doc_id,
                filename=Path(filename or source.name).name or source.name,
                kind="transcript",
                created_at=time.time(),
                pages=[],
                root=self.root,
                source_path=str(source),
                segments=segments,
                origin_path=str(source),
                origin_mtime=_mtime(source),
            )
            return self._register(doc)
        except Exception:
            shutil.rmtree(directory, ignore_errors=True)
            raise

    def create_transcript_path(
        self, src: Path, filename: str | None = None
    ) -> Document:
        return self.create_transcript(src, filename)

    # -- access ----------------------------------------------------------

    def get(self, doc_id: str) -> Document | None:
        return self._docs.get(doc_id)

    def find_by_source(self, path: Path | str) -> Document | None:
        """The document already imported from this file, if it is still current.

        Opening a 700-page textbook costs seconds of extraction. A library click
        that re-imported it every time would pay that again and again; the
        modification time makes sure an edited file is read anew.
        """
        source = Path(str(path))
        try:
            mtime = source.stat().st_mtime
        except OSError:
            return None
        key = os.path.normcase(os.path.abspath(str(source)))
        with self._lock:
            for doc in self._docs.values():
                origin = doc.origin_path or doc.source_path
                if not origin:
                    continue
                if os.path.normcase(os.path.abspath(origin)) != key:
                    continue
                if doc.origin_mtime and abs(doc.origin_mtime - mtime) > 0.001:
                    continue
                return doc
        return None

    def require(self, doc_id: str) -> Document:
        doc = self.get(doc_id)
        if doc is None:
            raise KeyError("Document not found — upload it again.")
        return doc

    def list(self) -> list[dict]:
        with self._lock:
            docs = sorted(self._docs.values(), key=lambda d: d.created_at, reverse=True)
        return [doc.summary() for doc in docs]

    def delete(self, doc_id: str) -> None:
        with self._lock:
            doc = self._docs.pop(doc_id, None)
            self._drop_extract_cache(doc_id)
        if doc is not None:
            shutil.rmtree(doc.directory, ignore_errors=True)

    # -- whole-document extraction --------------------------------------

    def _page_tables(self, pdf_page: "fitz.Page", page: Page) -> list[dict]:
        try:
            if not pdf_page.get_drawings():
                # No ruled lines at all: there is no bordered table to find, and
                # the layout analysis below would still cost half a second.
                return []
        except Exception:
            return []
        try:
            finder = pdf_page.find_tables()
            raw_tables = getattr(finder, "tables", []) or []
        except Exception:
            return []
        if not raw_tables:
            return []
        scale = page.width / pdf_page.rect.width if pdf_page.rect.width else RENDER_SCALE
        tables: list[dict] = []
        for table in raw_tables:
            row_count = int(getattr(table, "row_count", 0) or 0)
            col_count = int(getattr(table, "col_count", 0) or 0)
            if row_count < 2 or col_count < 2:
                continue
            try:
                raw_rows = table.extract() or []
            except Exception:
                continue
            rows: list[list[str]] = []
            cells = getattr(table, "cells", None)
            if cells and len(cells) == row_count * col_count:
                # PyMuPDF stores cells column-major; clipping each cell keeps
                # spaces that table.extract() sometimes drops.
                try:
                    for row_index in range(row_count):
                        row: list[str] = []
                        for col_index in range(col_count):
                            rect = fitz.Rect(cells[col_index * row_count + row_index])
                            value = pdf_page.get_text("text", clip=rect).strip()
                            if not value and row_index < len(raw_rows):
                                raw = raw_rows[row_index]
                                if col_index < len(raw):
                                    value = str(raw[col_index] or "")
                            row.append(normalize_text(value))
                        rows.append(row)
                except Exception:
                    rows = []
            if not rows:
                rows = [
                    [normalize_text(str(cell or "")) for cell in row]
                    for row in raw_rows
                ]
            markdown = _table_markdown(rows)
            if not markdown:
                continue
            try:
                bbox = tuple(float(value) for value in table.bbox)
            except (TypeError, ValueError):
                continue
            tables.append(
                {
                    "markdown": markdown,
                    "bbox": (
                        bbox[0] * scale,
                        bbox[1] * scale,
                        bbox[2] * scale,
                        bbox[3] * scale,
                    ),
                    "y": bbox[1] * scale,
                    "rows": len(rows),
                }
            )
        return tables

    @staticmethod
    def _compose_page(lines: list[dict], tables: list[dict]) -> str:
        """Page text with formulas marked so the model reads them as math."""
        items: list[tuple[float, int, str]] = []
        for line in lines:
            if any(_line_in_bbox(line, table["bbox"]) for table in tables):
                continue
            math = bool(line.get("math"))
            text = formats.normalise_math(line["text"], latex_symbols=math)
            if math:
                text = formats.mark_math(text, True)
            items.append((float(line["y0"]), 0, text))
        for table in tables:
            items.append((float(table["y"]), 1, f"Table:\n{table['markdown']}"))
        items.sort(key=lambda item: (item[0], item[1]))
        return "\n".join(item[2] for item in items).strip()

    def coverage(self, doc: Document) -> dict:
        """Per-page / per-segment stats used by the coverage meter.

        This reads metadata and already-extracted text only; it never triggers
        OCR on its own.
        """
        if doc.kind == "transcript":
            pages = [
                {
                    "page": index + 1,
                    "chars": len(segment.get("text", "")),
                    "images": 0,
                    "imageArea": 0.0,
                    "needsOcr": False,
                    "label": segment.get("label", f"Segment {index + 1}"),
                }
                for index, segment in enumerate(doc.segments)
            ]
            return {
                "kind": "transcript",
                "unit": "segments",
                "pageCount": len(pages),
                "pages": pages,
                "contentPages": len(pages),
                "textPages": len(pages),
                "imagePages": 0,
                "textCharacters": sum(page["chars"] for page in pages),
                "duration": doc.duration,
            }

        pages: list[dict] = []
        pdf = None
        try:
            # An EPUB is laid out as text only: its synthetic pages cannot
            # carry the book's figures, so there is nothing to count.
            if doc.kind == "pdf" and doc.format != "epub":
                pdf = fitz.open(doc.source)
            for page in doc.pages:
                text_chars = sum(len(line.get("text", "")) for line in page.lines)
                images = 0
                image_area = 0.0
                if pdf is not None:
                    pdf_page = pdf[page.index]
                    page_rect = pdf_page.rect
                    page_area = max(1.0, page_rect.width * page_rect.height)
                    infos = pdf_page.get_image_info()
                    images = len(infos)
                    covered_area = 0.0
                    for info in infos:
                        try:
                            rect = fitz.Rect(info["bbox"]) & page_rect
                        except (KeyError, TypeError, ValueError):
                            continue
                        if rect.is_empty:
                            continue
                        covered_area += rect.width * rect.height
                    image_area = min(1.0, covered_area / page_area)
                elif doc.kind == "image":
                    images = 1
                    image_area = 1.0
                pages.append(
                    {
                        "page": page.index + 1,
                        "chars": text_chars,
                        "images": images,
                        "imageArea": round(image_area, 3),
                        "needsOcr": page.needs_ocr,
                    }
                )
        finally:
            if pdf is not None:
                pdf.close()

        content_pages = [
            page
            for page in pages
            if page["chars"] > 0 or page["imageArea"] > 0.05
        ]
        return {
            "pageCount": len(pages),
            "pages": pages,
            "contentPages": len(content_pages),
            "textPages": sum(1 for page in pages if page["chars"] > 0),
            "imagePages": sum(1 for page in pages if page["imageArea"] > 0.05),
            "textCharacters": sum(page["chars"] for page in pages),
        }

    def _transcript_chunks(
        self,
        doc: Document,
        max_chars: int,
        max_chunks: int,
        start_segment: int | None = None,
        end_segment: int | None = None,
    ) -> dict:
        segments = doc.segments
        total = len(segments)
        first_index = max(0, min(total - 1, (start_segment or 1) - 1)) if total else 0
        last_index = max(
            first_index,
            min(total - 1, (end_segment or total) - 1),
        ) if total else -1
        selected = segments[first_index : last_index + 1] if total else []
        chunks: list[dict] = []
        current_parts: list[str] = []
        current_indices: list[int] = []
        current_len = 0

        def flush() -> None:
            nonlocal current_parts, current_indices, current_len
            if not current_parts:
                return
            start, end = current_indices[0], current_indices[-1]
            first, last = segments[start], segments[end]
            if doc.has_timestamps:
                label = f"{first.get('startLabel', '')}\u2013{last.get('endLabel', '')}"
            else:
                label = f"Segments {start + 1}\u2013{end + 1}"
            chunks.append(
                {
                    "label": label,
                    "text": "\n\n".join(current_parts),
                    "segments": [start + 1, end + 1],
                }
            )
            current_parts, current_indices, current_len = [], [], 0

        for index, segment in enumerate(selected, start=first_index):
            label = segment.get("label", f"Segment {index + 1}")
            block = f"--- {label} ---\n{segment.get('text', '')}"
            if len(block) > max_chars:
                flush()
                for part in _split_text(block, max_chars):
                    chunks.append(
                        {
                            "label": label,
                            "text": part,
                            "segments": [index + 1, index + 1],
                        }
                    )
                continue
            if current_parts and current_len + len(block) + 2 > max_chars:
                flush()
            current_indices.append(index)
            current_parts.append(block)
            current_len += len(block) + 2
        flush()

        truncated = len(chunks) > max_chunks
        if truncated:
            chunks = chunks[:max_chunks]
        return {
            "id": doc.id,
            "filename": doc.filename,
            "kind": "transcript",
            "pageCount": 0,
            "segmentCount": total,
            "selectedSegmentCount": len(selected),
            "startSegment": first_index + 1 if selected else None,
            "endSegment": last_index + 1 if selected else None,
            "duration": doc.duration,
            "chunks": chunks,
            "characters": sum(len(chunk["text"]) for chunk in chunks),
            "tableCount": 0,
            "truncated": truncated,
        }

    def range_texts(
        self,
        doc: Document,
        start_page: int | None = None,
        end_page: int | None = None,
    ) -> tuple[list[tuple[int, str]], int]:
        """Per-page text for a page range, with bordered tables as Markdown.

        One PDF is opened for the whole range: a book is hundreds of pages and
        reopening the file per page is what makes a split slow.
        """
        total = len(doc.pages)
        first = max(1, min(total, start_page or 1)) if total else 0
        last = max(first, min(total, end_page or total)) if total else 0
        blocks: list[tuple[int, str]] = []
        table_count = 0
        pdf = None
        try:
            # A synthetic page holds text this app wrote; there are no ruled
            # tables to find, and running the detector is wasted work. A book
            # is past the point where half a second of layout analysis a page
            # is worth its table structure.
            if (
                doc.kind == "pdf"
                and doc.format not in ("pptx", "epub")
                and len(doc.pages) <= TABLE_DETECTION_PAGES
            ):
                pdf = fitz.open(doc.source)
            for page in doc.pages[first - 1 : last]:
                if page.needs_ocr:
                    lines, _ = self.page_lines(doc, page.index)
                else:
                    lines = page.lines
                tables = self._page_tables(pdf[page.index], page) if pdf else []
                table_count += len(tables)
                text = self._compose_page(lines, tables)
                if text:
                    blocks.append((page.index + 1, text))
        finally:
            if pdf is not None:
                pdf.close()
        return blocks, table_count

    def extract_chunks(
        self,
        doc: Document,
        max_chars: int = 6000,
        max_chunks: int = 60,
        start_page: int | None = None,
        end_page: int | None = None,
        start_segment: int | None = None,
        end_segment: int | None = None,
    ) -> dict:
        """Page/segment text, split into LLM-sized sections."""
        max_chars = max(2000, min(12000, int(max_chars)))
        cache_key = (
            doc.id,
            max_chars,
            start_page,
            end_page,
            start_segment,
            end_segment,
        )
        with self._lock:
            cached = self._extract_cache.get(cache_key)
            if cached is not None:
                return cached

        if doc.kind == "transcript":
            result = self._transcript_chunks(
                doc,
                max_chars,
                max_chunks,
                start_segment=start_segment,
                end_segment=end_segment,
            )
            with self._lock:
                self._extract_cache[cache_key] = result
            return result

        total_pages = len(doc.pages)
        first_page = max(1, min(total_pages, start_page or 1)) if total_pages else 0
        last_page = max(
            first_page,
            min(total_pages, end_page or total_pages),
        ) if total_pages else 0
        page_blocks, table_count = self.range_texts(doc, first_page, last_page)

        chunks: list[dict] = []
        current_parts: list[str] = []
        current_pages: list[int] = []
        current_len = 0

        def flush() -> None:
            nonlocal current_parts, current_pages, current_len
            if not current_parts:
                return
            start, end = current_pages[0], current_pages[-1]
            label = f"Page {start}" if start == end else f"Pages {start}\u2013{end}"
            chunks.append(
                {
                    "label": label,
                    "text": "\n\n".join(current_parts),
                    "pages": [start, end],
                }
            )
            current_parts, current_pages, current_len = [], [], 0

        for page_number, text in page_blocks:
            block = f"--- Page {page_number} ---\n{text}"
            if len(block) > max_chars:
                flush()
                for part in _split_text(block, max_chars):
                    chunks.append(
                        {
                            "label": f"Page {page_number}",
                            "text": part,
                            "pages": [page_number, page_number],
                        }
                    )
                continue
            if current_parts and current_len + len(block) + 2 > max_chars:
                flush()
            if not current_pages:
                current_pages = [page_number, page_number]
            else:
                current_pages[1] = page_number
            current_parts.append(block)
            current_len += len(block) + 2
        flush()

        truncated = len(chunks) > max_chunks
        if truncated:
            chunks = chunks[:max_chunks]
        result = {
            "id": doc.id,
            "filename": doc.filename,
            "kind": doc.kind,
            "pageCount": len(doc.pages),
            "selectedPageCount": max(0, last_page - first_page + 1) if page_blocks else 0,
            "startPage": first_page if page_blocks else None,
            "endPage": last_page if page_blocks else None,
            "chunks": chunks,
            "characters": sum(len(chunk["text"]) for chunk in chunks),
            "tableCount": table_count,
            "truncated": truncated,
        }
        with self._lock:
            self._extract_cache[cache_key] = result
        return result

    def _trim_page_images(self, doc: Document, keep: int = PAGE_IMAGE_CACHE) -> None:
        """Keep the page-image cache bounded so a book does not fill the disk."""
        try:
            images = sorted(
                doc.directory.glob("page-*.png"),
                key=lambda path: path.stat().st_mtime,
                reverse=True,
            )
        except OSError:
            return
        for stale in images[keep:]:
            try:
                stale.unlink()
            except OSError:
                continue

    def render_page(self, doc: Document, index: int) -> Path:
        if doc.kind == "transcript":
            raise ValueError("Transcripts do not have page images.")
        page = doc.pages[index]
        target = doc.directory / f"page-{index}.png"
        if target.exists():
            return target
        with self._page_lock(doc.id, index):
            if target.exists():
                return target
            if doc.kind == "image":
                return doc.directory / "page-0.png"
            if len(doc.pages) > LARGE_DOCUMENT_PAGES:
                self._trim_page_images(doc)
            with fitz.open(doc.source) as pdf:
                pdf_page = pdf[index]
                pix = pdf_page.get_pixmap(
                    matrix=fitz.Matrix(RENDER_SCALE, RENDER_SCALE), alpha=False
                )
                pix.save(str(target))
            # Keep the overlay aligned if the pixmap rounded differently.
            if pix.width != page.width or pix.height != page.height:
                sx = pix.width / page.width
                sy = pix.height / page.height
                for line in page.lines:
                    for key, factor in (("x0", sx), ("x1", sx), ("y0", sy), ("y1", sy)):
                        line[key] = round(line[key] * factor, 2)
                page.width, page.height = pix.width, pix.height
                self._save_meta(doc)
            return target

    def page_lines(self, doc: Document, index: int) -> tuple[list[dict], bool]:
        """Return lines, OCR-ing a scanned page the first time it is opened."""
        if doc.kind == "transcript":
            raise ValueError("Transcripts do not have page images.")
        page = doc.pages[index]
        if not page.needs_ocr:
            return page.lines, False
        with self._page_lock(doc.id, index):
            if page.needs_ocr:
                image_path = self.render_page(doc, index)
                lines = ocr_lines(image_path, page.width)
                page.lines = lines
                page.needs_ocr = False
                page.ocr_done = True
                self._save_meta(doc)
        return page.lines, True
