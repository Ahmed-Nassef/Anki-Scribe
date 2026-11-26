"""Learning-objective detection.

Courses hand students an explicit target. If a deck can say "4 of 7 objectives
covered", coverage stops being a page count and becomes the thing the exam is
built from.

Detection is deliberately conservative: a heading line, then the items under
it. Anything less certain is skipped, because a wrong checklist is worse than
no checklist.
"""

from __future__ import annotations

import re

from .store import Document

_HEADING = re.compile(
    r"^(?:lecture|lesson|session|course|workshop|seminar|topic|chapter|class)?"
    r"\s*(?:learning\s+|course\s+|lecture\s+)?objectives?\b"
    r"|^by the end of (?:this|the)\b",
    re.IGNORECASE,
)
_BULLET = re.compile(r"^\s*(?:[\u2022\u00b7\u25aa\u25cf\u2023\u2043\u2013\u2014*\-]|\d+[.)]|\(?[a-z][.)])\s*")
_SENTENCE_START = re.compile(r"^(?:the|a|an|this|that|these|those|it|there|we|you|in|on|for)\b", re.I)

MIN_ITEM_CHARS = 15
MAX_ITEM_CHARS = 300
MIN_ITEMS = 3
MAX_ITEMS = 12


def _clean_item(text: str) -> str:
    value = _BULLET.sub("", text or "").strip()
    value = re.sub(r"\s+", " ", value)
    return value.strip(" .;:\u2013\u2014-")


def _looks_like_heading(text: str) -> bool:
    return bool(_HEADING.match((text or "").strip()))


def _looks_like_item(text: str) -> bool:
    value = (text or "").strip()
    if len(value) < MIN_ITEM_CHARS or len(value) > MAX_ITEM_CHARS:
        return False
    # A wrapped line from the paragraph above usually starts mid-sentence.
    if not _BULLET.match(value) and _SENTENCE_START.match(value) and value.endswith(","):
        return False
    return True


def _collect(lines: list[str], start: int) -> list[str]:
    """Items after a heading, stopping at the next heading or at prose.

    Once the block has shown a bullet, a line without one is no longer part of
    it — that is how a trailing paragraph stays out of the checklist.
    """
    items: list[str] = []
    saw_bullet = False
    for text in lines[start:]:
        if _looks_like_heading(text):
            break
        if _BULLET.match(text or ""):
            cleaned = _clean_item(text)
            if len(cleaned) >= MIN_ITEM_CHARS:
                items.append(cleaned)
                saw_bullet = True
            if len(items) >= MAX_ITEMS:
                break
            continue
        if saw_bullet:
            break
        if not _looks_like_item(text):
            if items:
                break
            continue
        items.append(_clean_item(text))
        if len(items) >= MAX_ITEMS:
            break
    return items


def _unit_lines(doc: Document, unit: int) -> list[str]:
    if doc.kind == "transcript":
        if unit >= len(doc.segments):
            return []
        return [doc.segments[unit].get("text", "")]
    if unit >= len(doc.pages):
        return []
    return [line.get("text", "") for line in doc.pages[unit].lines]


def _units(doc: Document) -> list[int]:
    return list(range(len(doc.segments) if doc.kind == "transcript" else len(doc.pages)))


def _label(doc: Document, unit: int) -> str:
    if doc.kind == "transcript":
        segment = doc.segments[unit]
        return segment.get("label") or f"Segment {unit + 1}"
    return f"Page {unit + 1}"


def detect(doc: Document) -> list[dict]:
    """Return ``[{text, unit, label}]`` for the first objectives block found."""
    units = _units(doc)
    for unit in units:
        lines = _unit_lines(doc, unit)
        for index, line in enumerate(lines):
            if not _looks_like_heading(line):
                continue
            items = _collect(lines, index + 1)
            # A block can run past its page or segment: keep reading forward
            # until there are enough items, the next heading, or the end.
            next_unit = unit + 1
            while len(items) < MIN_ITEMS and next_unit < len(units):
                more = _collect(_unit_lines(doc, next_unit), 0)
                if not more:
                    break
                items.extend(more)
                next_unit += 1
            if len(items) >= MIN_ITEMS:
                return [
                    {"text": text, "unit": unit, "label": _label(doc, unit)}
                    for text in items[:MAX_ITEMS]
                ]
    return []
