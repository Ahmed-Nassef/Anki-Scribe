"""Split a document into one file per chapter, ready to feed a model.

The app already generates cards one chapter at a time; this writes the same
split to disk so a book can also be handed to any LLM outside Anki Scribe.
Each chapter becomes a numbered Markdown file with a short front matter (book,
chapter, title, page range) and the chapters themselves are listed in a
``manifest.json`` beside them, which is what a script reads to know the order,
the sizes and where every file came from.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

from .config import data_dir
from .store import Document, Store

DEFAULT_DIR = "splits"
MAX_NAME = 70

_ILLEGAL = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_SPACES = re.compile(r"\s+")


def slug(value: str, limit: int = MAX_NAME) -> str:
    """A filename-safe piece of a chapter or book title.

    Long titles are cut at a word boundary: a folder called
    "... (Brianna Wie" reads like an error.
    """
    text = _ILLEGAL.sub(" ", str(value or ""))
    text = _SPACES.sub(" ", text).strip(" .")
    if len(text) > limit:
        text = text[:limit]
        boundary = text.rfind(" ")
        if boundary >= limit // 2:
            text = text[:boundary]
        text = text.strip(" .")
    return text or "untitled"


def _unique(name: str, used: set[str]) -> str:
    stem, dot, suffix = name.rpartition(".")
    if not dot:
        stem, suffix = name, ""
    candidate = name
    counter = 2
    while candidate.casefold() in used:
        candidate = f"{stem} ({counter}).{suffix}" if suffix else f"{stem} ({counter})"
        counter += 1
    used.add(candidate.casefold())
    return candidate


def _range_label(chapter: dict) -> str:
    start = chapter.get("startPage")
    end = chapter.get("endPage")
    if start is not None:
        return f"{start}" if start == end else f"{start}-{end}"
    start = chapter.get("startSegment")
    end = chapter.get("endSegment")
    if start is not None:
        return f"segments {start}" if start == end else f"segments {start}-{end}"
    return ""


def _front_matter(book: str, chapter: dict, number: int) -> str:
    title = str(chapter.get("title") or f"Chapter {number}")
    lines = ["---"]
    lines.append(f"book: {json.dumps(book, ensure_ascii=False)}")
    lines.append(f"chapter: {number}")
    lines.append(f"title: {json.dumps(title, ensure_ascii=False)}")
    path = [str(part) for part in (chapter.get("path") or []) if part]
    if path:
        lines.append(f"path: {json.dumps(path, ensure_ascii=False)}")
    if chapter.get("startPage") is not None:
        lines.append(f"pages: {json.dumps(_range_label(chapter), ensure_ascii=False)}")
    elif chapter.get("startSegment") is not None:
        lines.append(f"segments: {json.dumps(_range_label(chapter), ensure_ascii=False)}")
    lines.append("---")
    return "\n".join(lines)


def _chapter_body(store: Store, doc: Document, chapter: dict) -> str:
    if doc.kind == "transcript":
        start = int(chapter.get("startSegment") or 1)
        end = int(chapter.get("endSegment") or len(doc.segments))
        parts: list[str] = []
        for index in range(start - 1, min(end, len(doc.segments))):
            segment = doc.segments[index]
            label = (
                segment.get("startLabel")
                or segment.get("label")
                or f"Segment {index + 1}"
            )
            text = str(segment.get("text", "")).strip()
            if text:
                parts.append(f"--- {label} ---\n{text}")
        return "\n\n".join(parts)

    start = int(chapter.get("startPage") or 1)
    end = int(chapter.get("endPage") or len(doc.pages))
    blocks, _ = store.range_texts(doc, start, end)
    return "\n\n".join(f"--- Page {page} ---\n{text}" for page, text in blocks)


def output_folder(doc: Document, raw: str | Path | None = None) -> Path:
    """The folder the chapter files go to, created when missing."""
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        folder = data_dir() / DEFAULT_DIR / slug(Path(doc.filename).stem or "book")
    else:
        folder = Path(str(raw)).expanduser()
        if not folder.is_absolute():
            raise ValueError(
                "Choose a full folder path, for example C:\\Users\\you\\Books\\Heart."
            )
    try:
        folder.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise ValueError(f"Couldn't write to {folder}: {exc}") from exc
    if not folder.is_dir():
        raise ValueError(f"{folder} is not a folder.")
    return folder


def _previous_files(folder: Path) -> list[str]:
    """Chapter files a previous split wrote here; nothing else is touched."""
    try:
        raw = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    chapters = raw.get("chapters") if isinstance(raw, dict) else None
    return [
        str(entry["file"])
        for entry in chapters or []
        if isinstance(entry, dict) and entry.get("file")
    ]


def _has_range(chapter: dict) -> bool:
    return chapter.get("startPage") is not None or chapter.get("startSegment") is not None


def split_document(
    store: Store,
    doc: Document,
    plan: dict,
    output_dir: str | Path | None = None,
) -> dict:
    """Write one Markdown file per chapter plus a manifest, and report them."""
    chapters = [
        chapter
        for chapter in (plan.get("chapters") or [])
        if isinstance(chapter, dict) and _has_range(chapter)
    ]
    if not chapters:
        raise ValueError("This file has no chapters to split.")

    folder = output_folder(doc, output_dir)
    previous = _previous_files(folder)
    book = str(plan.get("sourceTitle") or Path(doc.filename).stem or doc.filename)
    width = max(2, len(str(len(chapters))))
    used: set[str] = set()
    entries: list[dict] = []
    total = 0

    for number, chapter in enumerate(chapters, start=1):
        title = str(chapter.get("title") or f"Chapter {number}")
        body = _chapter_body(store, doc, chapter)
        name = _unique(f"{number:0{width}d} - {slug(title)}.md", used)
        header = [f"# {title}"]
        label = _range_label(chapter)
        subtitle = f"*{book}*" + (f" \u00b7 {label}" if label else "")
        header.append(subtitle)
        content = (
            _front_matter(book, chapter, number)
            + "\n\n"
            + "\n\n".join(header)
            + "\n\n"
            + (body or "_(No extractable text in this chapter.)_")
            + "\n"
        )
        try:
            (folder / name).write_text(content, encoding="utf-8")
        except OSError as exc:
            raise ValueError(f"Couldn't write {name} to {folder}: {exc}") from exc

        total += len(body)
        entries.append(
            {
                "index": number,
                "file": name,
                "title": title,
                "path": [str(part) for part in (chapter.get("path") or []) if part],
                "startPage": chapter.get("startPage"),
                "endPage": chapter.get("endPage"),
                "startSegment": chapter.get("startSegment"),
                "endSegment": chapter.get("endSegment"),
                "characters": len(body),
                "estimatedSections": chapter.get("estimatedSections"),
            }
        )

    manifest = {
        "source": doc.filename,
        "sourceKind": doc.kind,
        "sourceFormat": doc.format or doc.kind,
        "sourceTitle": book,
        "strategy": plan.get("strategy"),
        "unit": plan.get("unit"),
        "generatedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "chapterCount": len(entries),
        "characters": total,
        "chapters": entries,
    }
    manifest_path = folder / "manifest.json"
    try:
        temporary = manifest_path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        temporary.replace(manifest_path)
    except OSError as exc:
        raise ValueError(f"Couldn't write the chapter manifest: {exc}") from exc

    # A re-split with fewer chapters used to leave the old files behind, so the
    # folder described more of the book than the manifest did.
    stale = [name for name in previous if name.casefold() not in used]
    for name in stale:
        try:
            (folder / name).unlink()
        except OSError:
            continue

    return {
        "folder": str(folder),
        "manifest": str(manifest_path),
        "sourceTitle": book,
        "strategy": plan.get("strategy"),
        "unit": plan.get("unit"),
        "chapterCount": len(entries),
        "characters": total,
        "files": [entry["file"] for entry in entries],
        "plan": plan,
    }
