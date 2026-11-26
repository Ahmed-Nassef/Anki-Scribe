"""Chapter/section planning for large PDFs and transcripts."""

from __future__ import annotations

import math
import re
from pathlib import Path

import pymupdf as fitz

from .store import Document

_HEADING = re.compile(
    r"^(?:chapter|lecture|part|unit|section|module|topic|week)\s+"
    r"(?:[0-9]+|[ivxlcdm]+|one|two|three|four|five|six|seven|eight|nine|ten|"
    r"eleven|twelve|thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|"
    r"nineteen|twenty)\b[\s:.\-\u2013\u2014]*(.*)$",
    re.IGNORECASE,
)
_MARKDOWN = re.compile(r"^#{1,4}\s+(.+)$")
# "CHAPTER 12" on its own line: the title is usually the line below it.
_BARE_HEADING = re.compile(
    r"^(?:chapter|lecture|part|unit|section|module|topic|week)\s+"
    r"(?:[0-9]+|[ivxlcdm]+|one|two|three|four|five|six|seven|eight|nine|ten|"
    r"eleven|twelve|thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|"
    r"nineteen|twenty)$",
    re.IGNORECASE,
)
_SKIP_TITLES = re.compile(
    r"^(?:contents|table of contents|cover|title page|index|references|bibliography)\b",
    re.IGNORECASE,
)


def source_title(doc: Document) -> str:
    stem = Path(doc.filename).stem or "Untitled"
    title = re.sub(r"[_-]+", " ", stem)
    title = re.sub(r"\s+", " ", title).strip()
    return title or "Untitled"


def _clean_title(value: str) -> str:
    text = re.sub(r"<[^>]+>", " ", str(value or ""))
    text = re.sub(r"\s+", " ", text).strip(" .:-\u2013\u2014")
    return text[:100]


def _skip_title(value: str) -> bool:
    return bool(_SKIP_TITLES.match(value.strip()))


def _page_chars(doc: Document, start: int, end: int) -> int:
    return sum(
        len(line.get("text", ""))
        for page in doc.pages[start - 1 : end]
        for line in page.lines
    )


def _segment_chars(doc: Document, start: int, end: int) -> int:
    return sum(len(segment.get("text", "")) for segment in doc.segments[start - 1 : end])


def _sections(titles: list[str], total_chars: int, page_count: int) -> int:
    if total_chars <= 0:
        return 1
    return max(1, math.ceil(total_chars / 3500))


def _node_path(nodes: list[dict], node: dict) -> list[str]:
    titles: list[str] = []
    current = node
    while current is not None:
        titles.append(current["title"])
        parent = current.get("parent")
        current = nodes[parent] if parent is not None else None
    titles.reverse()
    cleaned: list[str] = []
    for title in titles:
        if title and (not cleaned or cleaned[-1] != title):
            cleaned.append(title)
    return cleaned[-3:]


_CHAPTER_NAMED = re.compile(
    r"^(?:chapter|part|unit|section|module|book|volume|lesson|lecture|appendix)\b",
    re.IGNORECASE,
)


def _pick_candidates(nodes: list[dict]) -> list[dict]:
    """Choose the contents level that reads as "chapters".

    A textbook's outline nests parts over chapters over sections; a syllabus
    nests modules over lectures over topics. Splitting on parts is too coarse
    (a part can be 150 pages) and splitting on sections is too fine. The level
    whose titles announce themselves wins outright; failing that, the deepest
    level that still leaves a manageable number of units.
    """
    levels: dict[int, list[dict]] = {}
    for node in nodes:
        levels.setdefault(node["level"], []).append(node)
    ordered = sorted(levels)
    for level in reversed(ordered):
        entries = levels[level]
        named = [node for node in entries if _CHAPTER_NAMED.match(node["title"])]
        if len(named) >= 2 and len(entries) <= 80:
            return entries
    for level in reversed(ordered):
        entries = levels[level]
        if 2 <= len(entries) <= 40:
            return entries
    top = levels[ordered[0]]
    return top if len(top) >= 2 else [node for node in nodes if not node["children"]]


def _toc_plan(doc: Document) -> dict | None:
    try:
        with fitz.open(doc.source) as pdf:
            raw = pdf.get_toc(simple=True)
    except Exception:
        return None
    if not raw:
        return None

    nodes: list[dict] = []
    stack: list[dict] = []
    seen: set[tuple[str, int]] = set()
    for level, raw_title, page in raw:
        title = _clean_title(raw_title)
        try:
            level = int(level)
            page = int(page)
        except (TypeError, ValueError):
            continue
        if not title or page < 1 or page > len(doc.pages):
            continue
        key = (title.casefold(), page)
        if key in seen:
            continue
        seen.add(key)
        while stack and stack[-1]["level"] >= level:
            stack.pop()
        parent = stack[-1]["index"] if stack else None
        node = {
            "index": len(nodes),
            "level": level,
            "title": title,
            "page": page,
            "parent": parent,
            "children": [],
        }
        if parent is not None:
            nodes[parent]["children"].append(node["index"])
        nodes.append(node)
        stack.append(node)

    if not nodes:
        return None
    leaves = [node for node in nodes if not node["children"]]
    if len(leaves) < 2:
        return None
    candidates = _pick_candidates(nodes)
    if len(candidates) < 2:
        return None
    strategy = "toc"

    candidates = sorted(candidates, key=lambda node: node["page"])
    chapters: list[dict] = []
    for index, node in enumerate(candidates):
        start = node["page"]
        next_page = (
            candidates[index + 1]["page"]
            if index + 1 < len(candidates)
            else len(doc.pages) + 1
        )
        end = min(len(doc.pages), max(start, next_page - 1))
        chars = _page_chars(doc, start, end)
        path = _node_path(nodes, node)
        if not path or _skip_title(path[-1]):
            continue
        chapters.append(
            {
                "id": str(len(chapters)),
                "title": path[-1],
                "path": path,
                "startPage": start,
                "endPage": end,
                "startSegment": None,
                "endSegment": None,
                "characters": chars,
                "estimatedSections": _sections(path[-1], chars, len(doc.pages)),
            }
        )
    if not chapters:
        return None
    return {
        "kind": doc.kind,
        "unit": "pages",
        "strategy": strategy,
        "chapters": chapters,
    }


def _heading_title(text: str) -> str:
    value = _clean_title(text)
    if len(value) < 3 or len(value) > 100:
        return ""
    match = _MARKDOWN.match(text.strip())
    if match:
        return _clean_title(match.group(1))
    match = _HEADING.match(value)
    if match:
        return value
    if value.isupper() and 2 <= len(value.split()) <= 10 and len(value) >= 5:
        return value.title()
    return ""


def _full_heading(lines: list[str], index: int, title: str) -> str:
    """A bare "CHAPTER 12" takes its title from the line below it.

    Books habitually print the number and the name on two lines. Without this
    every chapter would be called "Chapter 12" and every deck under it would
    share one indistinguishable name.
    """
    if not _BARE_HEADING.match(title):
        return title
    for value in lines[index + 1 : index + 5]:
        extra = _clean_title(value)
        if not extra or extra.isdigit():
            continue
        if len(extra) > 80 or extra.endswith((".", ",", ";", ":")):
            return title
        return f"{title}: {extra}"
    return title


def _heading_plan(doc: Document) -> dict | None:
    if doc.kind == "transcript":
        starts: list[tuple[int, str]] = []
        for segment in doc.segments:
            title = _heading_title(segment.get("text", ""))
            if title:
                starts.append((int(segment["index"]) + 1, title))
        if len(starts) < 2:
            return None
        chapters = []
        for index, (start, title) in enumerate(starts):
            end = (
                starts[index + 1][0] - 1
                if index + 1 < len(starts)
                else len(doc.segments)
            )
            chars = _segment_chars(doc, start, end)
            chapters.append(
                {
                    "id": str(index),
                    "title": title,
                    "path": [title],
                    "startPage": None,
                    "endPage": None,
                    "startSegment": start,
                    "endSegment": end,
                    "characters": chars,
                    "estimatedSections": _sections(title, chars, len(doc.segments)),
                }
            )
        return {
            "kind": "transcript",
            "unit": "segments",
            "strategy": "headings",
            "chapters": chapters,
        }

    if doc.kind != "pdf":
        return None

    raw_starts: list[tuple[int, str]] = []
    for page in doc.pages:
        texts = [line.get("text", "") for line in page.lines[:15]]
        for index, text in enumerate(texts):
            title = _heading_title(text)
            if title:
                raw_starts.append((page.index + 1, _full_heading(texts, index, title)))
                break
    if len(raw_starts) < 2:
        return None

    counts: dict[str, int] = {}
    for _, title in raw_starts:
        counts[title.casefold()] = counts.get(title.casefold(), 0) + 1
    starts = [
        (page, title)
        for page, title in raw_starts
        if counts[title.casefold()] <= max(2, len(doc.pages) // 3)
    ]
    if len(starts) < 2:
        return None

    chapters: list[dict] = []
    for index, (start, title) in enumerate(starts):
        next_page = starts[index + 1][0] if index + 1 < len(starts) else len(doc.pages) + 1
        end = min(len(doc.pages), max(start, next_page - 1))
        chars = _page_chars(doc, start, end)
        chapters.append(
            {
                "id": str(index),
                "title": title,
                "path": [title],
                "startPage": start,
                "endPage": end,
                "startSegment": None,
                "endSegment": None,
                "characters": chars,
                "estimatedSections": _sections(title, chars, len(doc.pages)),
            }
        )
    return {
        "kind": "pdf",
        "unit": "pages",
        "strategy": "headings",
        "chapters": chapters,
    }


def _fallback_plan(doc: Document) -> dict:
    if doc.kind == "transcript":
        total = len(doc.segments)
        parts = min(12, max(1, math.ceil(total / 50)))
        size = max(1, math.ceil(total / parts))
        chapters = []
        for index in range(0, total, size):
            start = index + 1
            end = min(total, index + size)
            chars = _segment_chars(doc, start, end)
            chapters.append(
                {
                    "id": str(len(chapters)),
                    "title": f"Part {len(chapters) + 1}" if parts > 1 else "Full transcript",
                    "path": [f"Part {len(chapters) + 1}"] if parts > 1 else [],
                    "startPage": None,
                    "endPage": None,
                    "startSegment": start,
                    "endSegment": end,
                    "characters": chars,
                    "estimatedSections": _sections("", chars, total),
                }
            )
        return {
            "kind": "transcript",
            "unit": "segments",
            "strategy": "fallback",
            "chapters": chapters,
        }

    total = len(doc.pages)
    parts = min(12, max(1, math.ceil(total / 12)))
    size = max(1, math.ceil(total / parts))
    chapters = []
    for index in range(0, total, size):
        start = index + 1
        end = min(total, index + size)
        chars = _page_chars(doc, start, end)
        chapters.append(
            {
                "id": str(len(chapters)),
                "title": f"Part {len(chapters) + 1}" if parts > 1 else "Full file",
                "path": [f"Part {len(chapters) + 1}"] if parts > 1 else [],
                "startPage": start,
                "endPage": end,
                "startSegment": None,
                "endSegment": None,
                "characters": chars,
                "estimatedSections": _sections("", chars, total),
            }
        )
    return {
        "kind": "pdf" if doc.kind == "pdf" else doc.kind,
        "unit": "pages",
        "strategy": "fallback",
        "chapters": chapters,
    }


def build_plan(doc: Document) -> dict:
    plan = _toc_plan(doc) or _heading_plan(doc) or _fallback_plan(doc)
    chapters = plan["chapters"]
    plan["sourceTitle"] = source_title(doc)
    plan["pageCount"] = len(doc.pages)
    plan["segmentCount"] = len(doc.segments)
    plan["estimatedSections"] = sum(c["estimatedSections"] for c in chapters) or 1
    plan["chapterCount"] = len(chapters)
    return plan


def outline(doc: Document, max_chars: int = 18000) -> str:
    lines: list[str] = []
    if doc.kind == "transcript":
        segments = doc.segments
        stride = max(1, math.ceil(len(segments) / 220))
        for segment in segments[::stride]:
            label = segment.get("startLabel") or segment.get("label") or f"Segment {segment['index'] + 1}"
            text = re.sub(r"\s+", " ", segment.get("text", ""))[:100]
            lines.append(f"[{label}] {text}")
    else:
        for page in doc.pages:
            texts = [line.get("text", "") for line in page.lines if line.get("text")]
            snippet = " ".join(texts[:2])[:120]
            if snippet:
                lines.append(f"[Page {page.index + 1}] {snippet}")
    text = "\n".join(lines)
    if len(text) > max_chars:
        stride = max(1, math.ceil(len(lines) / 300))
        text = "\n".join(lines[::stride])[:max_chars]
    return text


def plan_from_proposals(
    doc: Document,
    proposals: list[dict],
    fallback: dict,
) -> dict | None:
    total = len(doc.pages) if doc.kind == "pdf" else len(doc.segments)
    if not proposals or total <= 0:
        return None
    cleaned: list[tuple[int, int, str, str]] = []
    for item in proposals:
        if not isinstance(item, dict):
            continue
        try:
            start = int(item.get("start"))
            end = int(item.get("end"))
        except (TypeError, ValueError):
            continue
        title = _clean_title(item.get("title", ""))
        subtitle = _clean_title(item.get("subtitle", ""))
        if not title or _skip_title(title):
            continue
        start = max(1, min(total, start))
        end = max(start, min(total, end))
        cleaned.append((start, end, title, subtitle))
    if not cleaned:
        return None
    cleaned.sort(key=lambda item: item[0])

    # The model can omit the opening pages or leave gaps between ranges.
    # Normalize to non-overlapping consecutive ranges so every unit is planned.
    normalized: list[tuple[int, int, str, str]] = []
    next_unit = 1
    for start, end, title, subtitle in cleaned:
        if normalized:
            previous = normalized[-1]
            if start > next_unit:
                normalized[-1] = (previous[0], start - 1, previous[2], previous[3])
                next_unit = start
            start = max(start, next_unit)
        else:
            start = 1
        if end < start:
            continue
        normalized.append((start, end, title, subtitle))
        next_unit = end + 1
    if not normalized:
        return None
    if normalized[-1][1] < total:
        last = normalized[-1]
        normalized[-1] = (last[0], total, last[2], last[3])

    chapters: list[dict] = []
    for start, end, title, subtitle in normalized:
        if doc.kind == "pdf":
            chars = _page_chars(doc, start, end)
            entry = {
                "id": str(len(chapters)),
                "title": title,
                "path": [title] + ([subtitle] if subtitle and subtitle != title else []),
                "startPage": start,
                "endPage": end,
                "startSegment": None,
                "endSegment": None,
            }
        else:
            chars = _segment_chars(doc, start, end)
            entry = {
                "id": str(len(chapters)),
                "title": title,
                "path": [title] + ([subtitle] if subtitle and subtitle != title else []),
                "startPage": None,
                "endPage": None,
                "startSegment": start,
                "endSegment": end,
            }
        entry["characters"] = chars
        entry["estimatedSections"] = _sections(title, chars, total)
        chapters.append(entry)
    if not chapters:
        return None
    result = dict(fallback)
    result["strategy"] = "llm"
    result["chapters"] = chapters
    result["chapterCount"] = len(chapters)
    result["estimatedSections"] = sum(c["estimatedSections"] for c in chapters) or 1
    return result
