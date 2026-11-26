"""Subtitle (.srt/.vtt) and plain-transcript parsing."""

from __future__ import annotations

import html
import re
from pathlib import Path

MAX_TRANSCRIPT_BYTES = 8 * 1024 * 1024
MAX_SEGMENT_CHARS = 520

_HTML_TAG = re.compile(r"<[^>]+>")
_SUB_STYLE = re.compile(r"\{\\[^}]+\}")
_TIME = re.compile(r"(?:(\d{1,2}):)?(\d{1,2}):(\d{2})[.,](\d{1,3})")


def _parse_time(value: str) -> float | None:
    match = _TIME.search(value.strip())
    if not match:
        return None
    hours = int(match.group(1) or 0)
    minutes = int(match.group(2))
    seconds = int(match.group(3))
    millis = int(match.group(4).ljust(3, "0")[:3])
    if minutes > 59 or seconds > 59:
        return None
    return hours * 3600 + minutes * 60 + seconds + millis / 1000


def format_time(seconds: float | None) -> str:
    if seconds is None:
        return ""
    total = max(0, int(round(seconds)))
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def _clean_text(value: str) -> str:
    value = html.unescape(value)
    value = _HTML_TAG.sub(" ", value)
    value = _SUB_STYLE.sub("", value)
    value = value.replace("\u200b", "").replace("\ufeff", "")
    return re.sub(r"\s+", " ", value).strip()


def _cues(text: str) -> list[dict]:
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    cues: list[dict] = []
    index = 0
    while index < len(lines):
        line = lines[index].strip()
        if "-->" not in line:
            index += 1
            continue
        left, right = line.split("-->", 1)
        start = _parse_time(left)
        end = _parse_time(right)
        index += 1
        payload: list[str] = []
        while index < len(lines):
            current = lines[index].strip()
            if not current:
                index += 1
                break
            if "-->" in current:
                break
            payload.append(current)
            index += 1
        text_value = _clean_text(" ".join(payload))
        if start is None or end is None or not text_value:
            continue
        cues.append(
            {
                "start": start,
                "end": max(start, end),
                "text": text_value,
            }
        )
    return cues


def _merge(cues: list[dict]) -> list[dict]:
    merged: list[dict] = []
    for cue in cues:
        text = cue["text"]
        if merged:
            last = merged[-1]
            gap = cue["start"] - last["end"]
            if gap <= 1.5 and len(last["text"]) + len(text) + 1 <= MAX_SEGMENT_CHARS:
                if text == last["text"] or last["text"].endswith(text):
                    last["end"] = max(last["end"], cue["end"])
                    continue
                last["text"] = f"{last['text']} {text}".strip()
                last["end"] = max(last["end"], cue["end"])
                continue
        merged.append(dict(cue))
    return merged


def _plain_segments(text: str) -> list[dict]:
    blocks = [block.strip() for block in re.split(r"\n\s*\n", text) if block.strip()]
    if len(blocks) <= 1:
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        blocks = []
        current: list[str] = []
        length = 0
        for line in lines:
            if current and length + len(line) + 1 > MAX_SEGMENT_CHARS:
                blocks.append(" ".join(current))
                current, length = [], 0
            current.append(line)
            length += len(line) + 1
        if current:
            blocks.append(" ".join(current))

    segments: list[dict] = []
    for block in blocks:
        cleaned = _clean_text(block)
        if not cleaned:
            continue
        if len(cleaned) <= MAX_SEGMENT_CHARS * 2:
            segments.append({"start": None, "end": None, "text": cleaned})
            continue
        sentences = re.split(r"(?<=[.!?])\s+", cleaned)
        current: list[str] = []
        length = 0
        for sentence in sentences:
            if current and length + len(sentence) + 1 > MAX_SEGMENT_CHARS:
                segments.append(
                    {"start": None, "end": None, "text": " ".join(current)}
                )
                current, length = [], 0
            current.append(sentence)
            length += len(sentence) + 1
        if current:
            segments.append({"start": None, "end": None, "text": " ".join(current)})
    return segments


def parse_transcript(text: str) -> list[dict]:
    raw = text.replace("\r\n", "\n").replace("\r", "\n").strip()
    if not raw:
        return []
    cues = _merge(_cues(raw))
    items = cues if cues else _plain_segments(raw)
    if not items:
        return []

    for index, item in enumerate(items):
        item["index"] = index
        start = item.get("start")
        end = item.get("end")
        if start is not None and end is not None:
            item["start"] = round(float(start), 3)
            item["end"] = round(float(end), 3)
            item["startLabel"] = format_time(start)
            item["endLabel"] = format_time(end)
            item["label"] = f"{item['startLabel']}\u2013{item['endLabel']}"
        else:
            item["start"] = None
            item["end"] = None
            item["startLabel"] = ""
            item["endLabel"] = ""
            item["label"] = f"Segment {index + 1}"
        item["text"] = _clean_text(item.get("text", ""))
    return items


def read_transcript(path: Path) -> list[dict]:
    source = Path(path)
    try:
        if source.stat().st_size > MAX_TRANSCRIPT_BYTES:
            raise ValueError("That transcript is larger than 8 MB.")
        data = source.read_bytes()
    except OSError as exc:
        raise ValueError(f"Couldn't read that transcript: {exc}") from exc
    if not data:
        raise ValueError("That transcript is empty.")

    decoded = None
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        try:
            decoded = data.decode("utf-16")
        except UnicodeDecodeError:
            decoded = None
    if decoded is None:
        for encoding in ("utf-8-sig", "cp1252", "latin-1"):
            try:
                decoded = data.decode(encoding)
                break
            except UnicodeDecodeError:
                continue
    if decoded is None:
        raise ValueError("Couldn't decode that transcript.")
    segments = parse_transcript(decoded)
    if not segments:
        raise ValueError("No readable text was found in that transcript.")
    return segments
