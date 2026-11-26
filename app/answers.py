"""Find card answers inside the pages they came from.

The PDF viewer can mask the answer text of every generated card, so a slide can
be read as a fill-in-the-blank page: the title, the table and the bullet list
stay visible, only the fact a card tests is hidden and clickable.

Nothing here is persisted. Masks are derived from the cards on every request, so
editing or deleting a card changes the study page on the next refresh.
"""

from __future__ import annotations

import html
import hashlib
import re
import statistics
import unicodedata
from dataclasses import dataclass, field
from typing import Callable, Iterable

import pymupdf

from .store import Document

MAX_CARDS = 2000
MAX_TERMS_PER_CARD = 6
MAX_MASKS = 5000
MAX_BOXES_PER_MASK = 4
MAX_PAGES = 1200
MAX_PAGE_SPAN = 120
MIN_FALLBACK_WORD = 5

CLOZE_RE = re.compile(r"\{\{c\d+::(.+?)\}\}", re.DOTALL)
_TAG_RE = re.compile(r"<[^>]+>")
_SPACE_RE = re.compile(r"\s+")
_BOLD_FLAG = 16

STOPWORDS = frozenset(
    """
    a an the and or but if then than that this these those is are was were be
    been being of to in on at by for from with without as it its their his her
    they them we you i not no yes can could may might will would should do does
    did done have has had more most less least other others such into over under
    about between among during before after above below up down out off again
    further once here there when where why how all any both each few many some
    own same so very just also only s t
    """.split()
)

_LEADING_YES_NO = re.compile(r"^(?:yes|no|true|false)\b[\s,;:.\-\u2013\u2014]*", re.I)
_LEADING_ARTICLE = re.compile(r"^(?:the|a|an)\s+", re.I)
_TRAILING_PUNCT = " \t\r\n.,;:!?\u2013\u2014-\u2026"
_NUMBER_RE = re.compile(
    r"(?:[$€£¥]\s?)?\d[\d,.]*\s?"
    r"(?:%|percent|percentage|million|billion|trillion|thousand|bn|m|k|"
    r"years?|months?|days?|weeks?|hours?)?",
    re.I,
)

_DATE_RE = re.compile(
    r"\b(?:19|20)\d{2}\b"
    r"|\b(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|"
    r"jul(?:y)?|aug(?:ust)?|sep(?:tember)?|oct(?:ober)?|nov(?:ember)?|"
    r"dec(?:ember)?)\b"
    r"|\b\d{1,2}[/-]\d{1,2}(?:[/-]\d{2,4})?\b",
    re.I,
)
_DOSE_RE = re.compile(
    r"\b\d+(?:\.\d+)?\s?(?:mg|mcg|µg|μg|g|kg|ml|l|iu|units?|mmol|meq|"
    r"mg/kg|µg/kg|ml/kg|%)(?![a-z0-9])",
    re.I,
)
_PROCEDURE_RE = re.compile(
    r"\b(?:procedure|technique|steps?|approach|maneuver|method|protocol|"
    r"how\s+to|first\s+step|next\s+step|insert|incision|suture|catheter|"
    r"administer|perform|workflow)\b",
    re.I,
)
_MECHANISM_RE = re.compile(
    r"\b(?:because|therefore|thus|leads?\s+to|results?\s+in|causes?|"
    r"due\s+to|so\s+that|mechanism|pathway)\b",
    re.I,
)
_COMPARE_RE = re.compile(
    r"\b(?:difference|differ|compared|comparison|versus|vs\.?|unlike|"
    r"whereas|distinguish)\b",
    re.I,
)
_APPLICATION_RE = re.compile(
    r"\b(?:patient|vignette|would\s+you|should\s+you|next\s+step|"
    r"management|first-line|treatment\s+of|prescribe)\b",
    re.I,
)
_DEFINITION_RE = re.compile(
    r"\b(?:is|are|refers?\s+to|means?|defined\s+as|describes?)\b", re.I
)

_CATEGORY_LABELS = {
    "date": "date",
    "dose": "dose",
    "number": "number",
    "procedure": "procedure",
    "definition": "definition",
    "mechanism": "mechanism",
    "compare": "comparison",
    "list": "list",
    "application": "application",
    "fact": "fact",
    "manual": "manual",
    "mixed": "mixed",
}


def card_category(card: dict) -> str:
    """The colour category for a card's hidden answer.

    The card's ``type`` comes from the generator's LLM, so this is a
    deterministic refinement of that classification: dates, doses and
    procedures are split out when the answer itself makes them unambiguous.
    """
    answer = str(card.get("answer") or card.get("text") or card.get("question") or "")
    question = str(card.get("question") or "")
    subject = f"{question} {answer}"
    if _DATE_RE.search(answer):
        return "date"
    if _DOSE_RE.search(answer):
        return "dose"
    if _PROCEDURE_RE.search(subject):
        return "procedure"
    kind = str(card.get("type") or "").strip().lower()
    mapped = {
        "number": "number",
        "enumeration": "list",
        "compare": "compare",
        "application": "application",
        "mechanism": "mechanism",
        "definition": "definition",
    }.get(kind)
    if mapped:
        return mapped
    if _MECHANISM_RE.search(subject):
        return "mechanism"
    if _COMPARE_RE.search(subject):
        return "compare"
    if _APPLICATION_RE.search(subject):
        return "application"
    if _DEFINITION_RE.search(answer):
        return "definition"
    if answer.count(",") >= 2 or re.search(r"\band\b.*\band\b", answer, re.I):
        return "list"
    return "fact"

SENTENCE_STARTERS = frozenset(
    """
    the this that these those there it its they them we you i a an no yes both
    in on at by for from with without as if when while after before because
    however therefore thus some many most each every all any one two three four
    five six seven eight nine ten
    """.split()
)


def _clean(value: object) -> str:
    text = html.unescape(str(value or ""))
    text = _TAG_RE.sub(" ", text)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = "".join(ch if ch >= " " or ch == "\n" else " " for ch in text)
    text = _SPACE_RE.sub(" ", text)
    return text.strip()


def _fold(text: str) -> str:
    text = unicodedata.normalize("NFKC", text or "")
    text = (
        text.replace("\u00ad", "")
        .replace("\ufb00", "ff")
        .replace("\ufb01", "fi")
        .replace("\ufb02", "fl")
        .replace("\ufb03", "ffi")
        .replace("\ufb04", "ffl")
        .replace("\u2018", "'")
        .replace("\u2019", "'")
        .replace("\u201c", '"')
        .replace("\u201d", '"')
    )
    out: list[str] = []
    for char in text:
        lowered = char.lower()
        if len(lowered) != 1:
            lowered = lowered[0] if lowered else ""
        if lowered and (lowered.isalnum() or lowered in "&+$€£¥%@#"):
            out.append(lowered)
        else:
            out.append(" ")
    return _SPACE_RE.sub(" ", "".join(out)).strip()


def _tokens(text: str) -> list[str]:
    folded = _fold(text)
    return [word for word in folded.split(" ") if word]


def _strip_term(value: str) -> str:
    text = _clean(value)
    text = _LEADING_YES_NO.sub("", text)
    text = _LEADING_ARTICLE.sub("", text)
    text = text.strip(_TRAILING_PUNCT)
    words = text.split()
    if len(words) > 14:
        text = " ".join(words[:14])
    return _clean(text)


def _dedupe_terms(terms: Iterable[str]) -> list[str]:
    cleaned: list[str] = []
    seen: set[str] = set()
    for term in terms:
        text = _strip_term(term)
        if len(text) < 2:
            continue
        key = _fold(text)
        if not key or key in seen:
            continue
        if key.isdigit() and len(key) < 2:
            continue
        seen.add(key)
        cleaned.append(text)

    # A single word that is part of a longer term ("Brazil" inside
    # "Brazil and Russia") is redundant; a shorter *phrase* is not, because it
    # is usually the precise answer clause while the long sentence is context.
    result: list[str] = []
    folded = [(_fold(term), term) for term in cleaned]
    for key, term in folded:
        single = len(key.split(" ")) == 1
        if single and any(
            key != other_key and key in other_key and not key.isdigit()
            for other_key, _ in folded
        ):
            continue
        result.append(term)
    return result[:MAX_TERMS_PER_CARD]


def cloze_terms(text: str) -> list[str]:
    return _dedupe_terms(match.group(1) for match in CLOZE_RE.finditer(_clean(text)))


_CAPITALISED_RE = re.compile(
    r"\b[A-Z][A-Za-z0-9&.'-]*"
    r"(?:\s+(?:(?:and|of|the|for|in|on|to|&)\s+)?[A-Z][A-Za-z0-9&.'-]*)*"
)


def _capitalised_terms(answer: str) -> list[str]:
    terms: list[str] = []
    for match in _CAPITALISED_RE.finditer(answer):
        phrase = match.group(0).strip()
        if not phrase:
            continue
        stripped = _strip_term(phrase)
        words = stripped.split(" ")
        sentence_start = match.start() == 0 or answer[: match.start()].rstrip().endswith(
            (".", "!", "?", ";", ":")
        )
        if len(words) >= 2:
            terms.append(stripped)
        elif len(words) == 1:
            word = words[0]
            # Acronyms are names even when they open a sentence ("PE is...").
            if word.isupper() and len(word) >= 2:
                terms.append(stripped)
            elif not sentence_start and len(word) >= 4 and word.lower() not in SENTENCE_STARTERS:
                terms.append(stripped)
    return terms


def _number_terms(answer: str) -> list[str]:
    terms: list[str] = []
    for match in _NUMBER_RE.finditer(answer):
        value = match.group(0).strip()
        if not value or not re.search(r"\d", value):
            continue
        digits = re.sub(r"\D", "", value)
        unit = re.sub(r"[\d,.\s]", "", value).strip()
        if len(digits) >= 2 or unit:
            terms.append(value)
    return terms


def _trim_phrase(words: list[str], limit: int = 6) -> str:
    """A short, specific phrase: no leading/trailing filler, at most 6 words."""
    values = list(words)
    while values and values[0].lower() in STOPWORDS:
        values.pop(0)
    while values and values[-1].lower() in STOPWORDS:
        values.pop()
    return " ".join(values[:limit]).strip()


def answer_terms(answer: str, quote: str = "") -> list[str]:
    """The few phrases in ``answer`` that are worth hiding on the page.

    A whole answer is often a paragraph. Hiding the paragraph destroys the
    slide the student is trying to read, so basic cards hide the *specific*
    fact instead: the names, the numbers, the short clause. A long shared
    sentence is only used when nothing more precise exists.
    """
    text = _clean(answer)
    if not text:
        return []

    quote_words = _tokens(quote)
    answer_words = _tokens(text)
    candidates: list[str] = []

    # A short answer is already the fact ("A financial institution").
    short = ""
    if 1 <= len(answer_words) <= 6:
        short = _trim_phrase(answer_words)

    # Names, numbers and other discriminating tokens come first: they are the
    # words that make the fact specific, and they survive even when the card
    # paraphrased the sentence.
    candidates.extend(_capitalised_terms(text))
    candidates.extend(_number_terms(text))
    specific = bool(candidates)
    if short:
        candidates.insert(0, short)

    if answer_words and quote_words:
        import difflib

        matcher = difflib.SequenceMatcher(None, answer_words, quote_words, autojunk=False)
        blocks = [block for block in matcher.get_matching_blocks() if block.size >= 2]
        blocks.sort(key=lambda block: block.size, reverse=True)
        for block in blocks[:2]:
            phrase_words = answer_words[block.a : block.a + block.size]
            if len(phrase_words) <= 4:
                candidates.append(_trim_phrase(phrase_words))
            elif not specific and len(phrase_words) <= 10:
                # Nothing more precise was found; a whole short clause is still
                # a better blank than the complete paragraph.
                candidates.append(_trim_phrase(phrase_words, limit=10))

    # Deliberately no "random distinctive words" fallback for a basic card: a
    # lone adjective is not the answer, and hiding it makes the slide harder to
    # read without testing anything. Such a card is left for manual hiding.

    terms = [
        term
        for term in _dedupe_terms(candidates)
        if any(word not in STOPWORDS for word in _fold(term).split(" "))
    ]
    multi = [term for term in terms if len(_fold(term).split(" ")) >= 2]
    single = [
        term
        for term in terms
        if term not in multi and _fold(term) not in STOPWORDS
    ]
    return (multi + single)[:4]


def card_terms(card: dict) -> list[str]:
    mode = str(card.get("mode") or "basic")
    if mode == "figure":
        return []
    source = card.get("source") if isinstance(card.get("source"), dict) else {}
    quote = str(source.get("quote") or source.get("evidence") or card.get("evidence") or "")
    if mode == "cloze":
        text = str(card.get("text") or card.get("question") or "")
        terms = cloze_terms(text)
        if terms:
            return terms
    answer = str(card.get("answer") or "")
    return answer_terms(answer, quote)


@dataclass
class _Line:
    text: str
    x0: float
    y0: float
    x1: float
    y1: float
    size: float
    bold: bool = False
    heading: bool = False
    decorative: bool = False


@dataclass
class _PageText:
    page: int
    text: str = ""
    boxes: list[tuple[float, float, float, float] | None] = field(default_factory=list)
    lines: list[int] = field(default_factory=list)
    line_info: list[_Line] = field(default_factory=list)

    def add_char(self, char: str, box: tuple[float, float, float, float] | None, line: int) -> None:
        self.text += char
        self.boxes.append(box)
        self.lines.append(line)

    def add_space(self) -> None:
        if self.text and not self.text.endswith(" "):
            self.text += " "
            self.boxes.append(None)
            self.lines.append(-1)


def _is_heading(line: _Line, body_size: float) -> bool:
    text = line.text.strip()
    if not text:
        return True
    if line.decorative:
        return True
    letters = [char for char in text if char.isalpha()]
    upper = bool(letters) and all(char.isupper() for char in letters)
    if len(text) > 120:
        return False
    if line.size >= body_size * 1.15:
        return True
    if (
        line.bold
        and line.size >= body_size * 1.05
        and len(text) <= 90
        and not text.endswith((".", ":", ";", "?", "!", ","))
    ):
        return True
    if upper and 2 <= len(text) <= 70 and line.size >= body_size * 0.98:
        return True
    return False


def _mark_headings(lines: list[_Line]) -> None:
    sizes: list[float] = []
    for line in lines:
        if len(line.text) < 2:
            continue
        sizes.extend([line.size] * max(1, min(len(line.text), 200)))
    body = statistics.median(sizes) if sizes else 0.0
    if body <= 0:
        body = 10.0
    for line in lines:
        stripped = line.text.strip()
        line.decorative = bool(
            re.fullmatch(r"[\d\s.\-\u2013\u2014/]+", stripped or "")
            or re.fullmatch(r"page\s+\d+", stripped or "", re.I)
        )
        line.heading = _is_heading(line, body)


def _looks_like_contents(index: _PageText) -> bool:
    """A table of contents is navigation, not answer material.

    Cards are sometimes generated from a ``Content`` slide. Masking those
    entries hides the chapter list the student needs to keep their bearings,
    so the page is left readable and the search moves to the next candidate.
    """
    lines = [line.text.strip() for line in index.line_info if line.text.strip()]
    if not lines:
        return False
    for line in lines[:3]:
        head = _fold(line)
        if re.match(r"^(content|contents|table of contents|agenda|outline|index)\b", head):
            return True
    return False


def _page_from_pdf(pdf_page: "pymupdf.Page", page_number: int) -> _PageText:
    result = _PageText(page=page_number)
    raw = pdf_page.get_text(
        "rawdict",
        flags=pymupdf.TEXTFLAGS_DICT & ~pymupdf.TEXT_PRESERVE_IMAGES,
    )
    rotation = int(getattr(pdf_page, "rotation", 0) or 0) % 360
    rect = pdf_page.rect
    width = max(1.0, float(rect.width))
    height = max(1.0, float(rect.height))

    def box_of(bbox) -> tuple[float, float, float, float]:
        box = pymupdf.Rect(bbox)
        if rotation:
            box = box * pdf_page.rotation_matrix
        return (box.x0 / width, box.y0 / height, box.x1 / width, box.y1 / height)

    line_boxes: list[_Line] = []
    for block in raw.get("blocks", []):
        if block.get("type") != 0:
            continue
        for line in block.get("lines", []):
            spans = line.get("spans", [])
            chars: list[tuple[str, tuple[float, float, float, float], float, bool]] = []
            sizes: list[float] = []
            bold = 0
            for span in spans:
                size = float(span.get("size") or 10.0)
                is_bold = bool(int(span.get("flags") or 0) & _BOLD_FLAG)
                for char in span.get("chars", []):
                    value = str(char.get("c") or "")
                    bbox = char.get("bbox")
                    if not value or not bbox:
                        continue
                    chars.append((value, box_of(bbox), size, is_bold))
                    sizes.append(size)
                    bold += 1 if is_bold else 0
            if not chars:
                continue
            text = "".join(item[0] for item in chars)
            if not text.strip():
                continue
            x0 = min(item[1][0] for item in chars)
            y0 = min(item[1][1] for item in chars)
            x1 = max(item[1][2] for item in chars)
            y1 = max(item[1][3] for item in chars)
            line_index = len(line_boxes)
            line_boxes.append(
                _Line(
                    text=text,
                    x0=x0,
                    y0=y0,
                    x1=x1,
                    y1=y1,
                    size=max(sizes) if sizes else 10.0,
                    bold=bold * 2 >= len(chars),
                )
            )
            last_char_box = None
            last_char_size = 0.0
            for value, bbox, size, _is_bold in chars:
                folded_value = _fold(value)
                if not folded_value:
                    # A real space glyph, punctuation, or a soft hyphen: all
                    # of them separate words for matching purposes.
                    result.add_space()
                    continue
                # A PDF text layer often has no space glyphs: the gap between
                # two words is geometric. Without this, "Banks are universal"
                # becomes one word and no card answer can ever match it.
                if result.text and not result.text.endswith(" "):
                    previous = last_char_box
                    if previous is not None:
                        gap = bbox[0] - previous[2]
                        if gap > max(0.8, min(size, last_char_size) * 0.18):
                            result.add_space()
                for folded in folded_value:
                    if folded.isspace():
                        result.add_space()
                    else:
                        result.add_char(folded, bbox, line_index)
                last_char_box = bbox
                last_char_size = size
            result.add_space()
            last_char_box = None

    _mark_headings(line_boxes)
    result.line_info = line_boxes
    return result


def _page_from_lines(page: "object", lines: list[dict]) -> _PageText:
    result = _PageText(page=int(getattr(page, "index", 0)))
    page_width = float(getattr(page, "width", 1) or 1)
    page_height = float(getattr(page, "height", 1) or 1)
    line_boxes: list[_Line] = []
    for raw in lines:
        text = str(raw.get("text") or "")
        if not text:
            continue
        try:
            x0 = float(raw.get("x0") or 0) / page_width
            y0 = float(raw.get("y0") or 0) / page_height
            x1 = float(raw.get("x1") or 0) / page_width
            y1 = float(raw.get("y1") or 0) / page_height
        except (TypeError, ValueError):
            continue
        if x1 <= x0 or y1 <= y0:
            continue
        size = max(1.0, (y1 - y0) * page_height)
        line_index = len(line_boxes)
        line_boxes.append(_Line(text=text, x0=x0, y0=y0, x1=x1, y1=y1, size=size))
        result.add_space()
        width = max(1e-9, x1 - x0)
        step = width / max(1, len(text))
        for position, value in enumerate(text):
            box = (x0 + position * step, y0, x0 + (position + 1) * step, y1)
            folded_value = _fold(value)
            if not folded_value:
                result.add_space()
                continue
            for folded in folded_value:
                if folded.isspace():
                    result.add_space()
                else:
                    result.add_char(folded, box, line_index)
        result.add_space()
    _mark_headings(line_boxes)
    result.line_info = line_boxes
    return result


@dataclass
class _Mask:
    page: int
    boxes: list[dict]
    text: str
    kind: str = "answer"
    category: str = "fact"
    uids: set[str] = field(default_factory=set)


def _box_overlap(first: dict, second: dict) -> float:
    left = max(first["x"], second["x"])
    top = max(first["y"], second["y"])
    right = min(first["x"] + first["w"], second["x"] + second["w"])
    bottom = min(first["y"] + first["h"], second["y"] + second["h"])
    if right <= left or bottom <= top:
        return 0.0
    intersection = (right - left) * (bottom - top)
    smaller = min(first["w"] * first["h"], second["w"] * second["h"])
    return intersection / max(1e-9, smaller)


def _merge_masks(masks: list[_Mask]) -> list[_Mask]:
    """Group masks that cover the same words into one clickable answer.

    A basic card often contributes both a clause and the names inside it. Left
    separate, clicking the name would reveal it while the surrounding clause
    stayed blank, which reads as a bug. One group per region is also far less
    DOM when a page carries twenty cards.
    """
    groups: list[_Mask] = []
    for mask in masks:
        merged = False
        for group in groups:
            if group.page != mask.page:
                continue
            if any(
                _box_overlap(existing, new) >= 0.5
                for existing in group.boxes
                for new in mask.boxes
            ):
                group.boxes = _merge_boxes([group.boxes, mask.boxes], limit=12)
                group.uids |= mask.uids
                if group.category != mask.category:
                    group.category = "mixed"
                if len(mask.text) > len(group.text):
                    group.text = mask.text
                merged = True
                break
        if not merged:
            groups.append(mask)
    return groups


def _line_boxes_for_range(index: _PageText, start: int, end: int) -> list[dict]:
    groups: dict[int, list[tuple[float, float, float, float]]] = {}
    for position in range(max(0, start), min(len(index.text), end)):
        box = index.boxes[position]
        line = index.lines[position]
        if box is None or line < 0 or line >= len(index.line_info):
            continue
        info = index.line_info[line]
        if info.heading or info.decorative:
            continue
        groups.setdefault(line, []).append(box)
    boxes: list[dict] = []
    for line in sorted(groups):
        coords = groups[line]
        x0 = min(item[0] for item in coords)
        y0 = min(item[1] for item in coords)
        x1 = max(item[2] for item in coords)
        y1 = max(item[3] for item in coords)
        if x1 - x0 < 0.001 or y1 - y0 < 0.001:
            continue
        pad_x = 0.0018
        pad_y = 0.002
        left = max(0.0, x0 - pad_x)
        top = max(0.0, y0 - pad_y)
        right = min(1.0, x1 + pad_x)
        bottom = min(1.0, y1 + pad_y)
        boxes.append(
            {
                "x": round(left, 4),
                "y": round(top, 4),
                "w": round(right - left, 4),
                "h": round(bottom - top, 4),
            }
        )
        if len(boxes) >= MAX_BOXES_PER_MASK:
            break
    return boxes


def _pattern(folded: str) -> str:
    return r"(?<!\w)" + re.escape(folded).replace(r"\ ", r"\s+") + r"(?!\w)"


def _phrase_matches(index: _PageText, phrase: str) -> list[tuple[int, int, list[dict]]]:
    folded = _fold(phrase)
    if len(folded) < 2:
        return []
    matches: list[tuple[int, int, list[dict]]] = []
    for match in re.finditer(_pattern(folded), index.text):
        boxes = _line_boxes_for_range(index, match.start(), match.end())
        if boxes:
            matches.append((match.start(), match.end(), boxes))
    return matches


def _near_range(index: _PageText, quote: str) -> tuple[int, int] | None:
    folded = _fold(quote)
    if len(folded) < 2:
        return None
    match = re.search(_pattern(folded), index.text)
    if match:
        return (match.start(), match.end())
    # The quote may be truncated or lightly paraphrased; its first six words
    # are still enough to anchor the answer to the right paragraph.
    words = folded.split(" ")
    if len(words) >= 4:
        anchor = " ".join(words[:6])
        match = re.search(_pattern(anchor), index.text)
        if match:
            return (match.start(), match.end())
    return None


def _best_match(
    matches: list[tuple[int, int, list[dict]]],
    near: tuple[int, int] | None,
) -> list[dict]:
    if not matches:
        return []

    def rank(item: tuple[int, int, list[dict]]) -> tuple:
        start, end, boxes = item
        if near is not None:
            distance = 0 if start <= near[1] and end >= near[0] else min(
                abs(start - near[0]), abs(start - near[1]), abs(end - near[0]), abs(end - near[1])
            )
        else:
            distance = 0
        # Near the quote first, then the widest match (a phrase spanning a
        # wrapped line is a better answer than a one-word fragment).
        return (distance, -len(boxes), start)

    return sorted(matches, key=rank)[0][2]


def _clean_boxes(boxes: list[dict], limit: int = MAX_BOXES_PER_MASK) -> list[dict]:
    """Collapse boxes that cover the same words into their union."""
    cleaned: list[dict] = []
    for box in sorted(boxes, key=lambda item: (item["y"], item["x"])):
        for existing in cleaned:
            overlap = _box_overlap(existing, box)
            same_row = (
                min(existing["y"] + existing["h"], box["y"] + box["h"])
                - max(existing["y"], box["y"])
                > 0.5 * min(existing["h"], box["h"])
            )
            if overlap >= 0.35 or (same_row and overlap > 0):
                left = min(existing["x"], box["x"])
                top = min(existing["y"], box["y"])
                right = max(existing["x"] + existing["w"], box["x"] + box["w"])
                bottom = max(existing["y"] + existing["h"], box["y"] + box["h"])
                existing.update(
                    {
                        "x": round(left, 4),
                        "y": round(top, 4),
                        "w": round(right - left, 4),
                        "h": round(bottom - top, 4),
                    }
                )
                break
        else:
            cleaned.append(dict(box))
    return cleaned[:limit]


def _merge_boxes(groups: list[list[dict]], limit: int = MAX_BOXES_PER_MASK) -> list[dict]:
    seen: set[tuple] = set()
    merged: list[dict] = []
    for group in groups:
        for box in group:
            key = (
                round(box["x"], 3),
                round(box["y"], 3),
                round(box["w"], 3),
                round(box["h"], 3),
            )
            if key in seen:
                continue
            seen.add(key)
            merged.append(box)
    merged.sort(key=lambda box: (box["y"], box["x"]))
    return _clean_boxes(merged, limit=limit)


def find_term(
    index: _PageText,
    term: str,
    near: tuple[int, int] | None = None,
) -> list[dict]:
    folded = _fold(term)
    if len(folded) < 2:
        return []
    matches = _phrase_matches(index, folded)
    if matches:
        return _best_match(matches, near)

    words = [word for word in folded.split(" ") if word]
    for length in range(min(len(words), 6), 1, -1):
        for start in range(0, len(words) - length + 1):
            candidate = " ".join(words[start : start + length])
            matches = _phrase_matches(index, candidate)
            if matches:
                return _best_match(matches, near)

    # No phrase survived. Hide a few distinctive words from the answer instead
    # of one arbitrary fragment; the student still gets a useful blank.
    groups: list[list[dict]] = []
    for word in sorted(set(words), key=len, reverse=True):
        if len(word) < MIN_FALLBACK_WORD or word in STOPWORDS:
            continue
        matches = _phrase_matches(index, word)
        if matches:
            groups.append(_best_match(matches, near))
        if len(groups) >= 3:
            break
    return _merge_boxes(groups)


def quote_boxes(
    index: _PageText,
    quote: str,
    near: tuple[int, int] | None = None,
) -> list[dict]:
    """Fallback for a basic card whose answer is phrased too differently.

    The evidence quote is verbatim source text; hiding the clause it points at
    is still a useful blank, and the surrounding title, table and bullets stay.
    """
    folded = _fold(quote)
    if len(folded) < 2:
        return []
    matches = _phrase_matches(index, folded)
    if not matches:
        words = folded.split(" ")
        # Drop a trailing fragment that may have been cut by the chunker.
        for length in range(min(len(words), 20), 3, -1):
            candidate = " ".join(words[:length])
            matches = _phrase_matches(index, candidate)
            if matches:
                break
    if not matches:
        return []
    boxes = _best_match(matches, near)
    if not boxes:
        return []
    # A quote can be a whole paragraph. Keep the blank to the width of a
    # sentence so a table or a bullet list underneath is not swallowed.
    if sum(box["w"] for box in boxes) > 0.9 or len(boxes) > 2:
        boxes = boxes[:2]
    return boxes


def _page_words(texts: dict[int, str]) -> dict[int, list[str]]:
    return {page: _tokens(text) for page, text in texts.items()}


def _quote_score(quote_words: list[str], page_words: list[str]) -> float:
    if not quote_words or not page_words:
        return 0.0
    import difflib

    matcher = difflib.SequenceMatcher(None, quote_words, page_words, autojunk=False)
    matched = sum(block.size for block in matcher.get_matching_blocks())
    return matched / max(1, len(quote_words))


def _candidate_pages(
    card: dict,
    range_pages: list[int],
    page_texts: dict[int, str],
    page_words: dict[int, list[str]],
) -> list[int]:
    if not range_pages:
        return []
    source = card.get("source") if isinstance(card.get("source"), dict) else {}
    quote = str(source.get("quote") or source.get("evidence") or card.get("evidence") or "")
    quote_words = _tokens(quote)
    if len(quote_words) < 2 or len(range_pages) == 1:
        return range_pages[:MAX_PAGES]

    scored: list[tuple[float, int]] = []
    for page in range_pages:
        score = _quote_score(quote_words, page_words.get(page, []))
        if score:
            scored.append((score, page))
    if not scored:
        return range_pages[:MAX_PAGES]
    scored.sort(reverse=True)
    best = scored[0][0]
    # Keep pages close to the best match; a generic quote should not drag every
    # page of a chapter into the search. Rank by score, not by page number, so
    # the page the quote actually came from is tried first.
    pages = [page for score, page in scored if score >= max(0.45, best - 0.18)]
    if scored[0][1] not in pages:
        pages.insert(0, scored[0][1])
    return pages[:MAX_PAGES]


def _range_pages(card: dict, page_count: int) -> list[int]:
    source = card.get("source") if isinstance(card.get("source"), dict) else {}
    pages = source.get("pages")
    if not isinstance(pages, list) or not pages:
        return []
    try:
        start = int(pages[0])
        end = int(pages[1]) if len(pages) > 1 else start
    except (TypeError, ValueError):
        return []
    start, end = sorted((start, end))
    start = max(0, min(start, page_count - 1))
    end = max(0, min(end, page_count - 1))
    return list(range(start, end + 1))


def build_masks(
    doc: Document,
    cards: list[dict],
    page_lines: Callable[[int], list[dict]] | None = None,
) -> dict:
    page_count = len(doc.pages)
    stats = {
        "cards": 0,
        "maskedCards": 0,
        "terms": 0,
        "masks": 0,
        "pages": 0,
        "truncated": False,
    }
    if not page_count or not cards:
        return {"masks": [], "stats": stats}

    prepared: list[dict] = []
    for raw in cards[:MAX_CARDS]:
        if not isinstance(raw, dict):
            continue
        if not card_terms(raw):
            continue
        prepared.append(raw)
    stats["cards"] = len(prepared)
    if not prepared:
        return {"masks": [], "stats": stats}

    needed: set[int] = set()
    ranges: dict[int, list[int]] = {}
    for position, card in enumerate(prepared):
        pages = _range_pages(card, page_count)
        if not pages:
            continue
        ranges[position] = pages
        needed.update(pages)
    if not needed:
        return {"masks": [], "stats": stats}
    allowed_pages = set(needed)
    if len(allowed_pages) > MAX_PAGES:
        stats["truncated"] = True
        allowed_pages = set(sorted(allowed_pages)[:MAX_PAGES])

    page_texts: dict[int, str] = {}
    pdf = None
    try:
        pdf = pymupdf.open(doc.source)
    except Exception:
        pdf = None

    try:
        for page_index in sorted(allowed_pages):
            text = ""
            if pdf is not None and page_index < pdf.page_count:
                try:
                    text = pdf[page_index].get_text("text")
                except Exception:
                    text = ""
            if not text and page_lines is not None:
                try:
                    lines, _ocr = page_lines(page_index)
                    text = "\n".join(str(line.get("text") or "") for line in lines)
                except Exception:
                    text = ""
            page_texts[page_index] = text
    except Exception:
        page_texts = {page: "" for page in allowed_pages}

    page_words = _page_words(page_texts)
    indexes: dict[int, _PageText] = {}

    def index_for(page_index: int) -> _PageText | None:
        if page_index in indexes:
            return indexes[page_index]
        try:
            if pdf is not None and page_index < pdf.page_count:
                index = _page_from_pdf(pdf[page_index], page_index)
                if index.text.strip():
                    indexes[page_index] = index
                    return index
        except Exception:
            pass
        if page_lines is not None:
            try:
                lines, _ocr = page_lines(page_index)
                index = _page_from_lines(doc.pages[page_index], lines)
                indexes[page_index] = index
                return index
            except Exception:
                pass
        indexes[page_index] = _PageText(page=page_index)
        return indexes[page_index]

    masks: list[_Mask] = []
    seen_boxes: dict[tuple, _Mask] = {}
    masked_cards = 0
    for position, card in enumerate(prepared):
        terms = card_terms(card)
        if not terms:
            continue
        uid = str(card.get("uid") or card.get("id") or "")
        category = card_category(card)
        pages = ranges.get(position, [])
        if not pages:
            continue
        pages = [page for page in pages if page in allowed_pages]
        if not pages:
            continue
        if len(pages) > MAX_PAGE_SPAN:
            pages = pages[:MAX_PAGE_SPAN]
        candidates = _candidate_pages(card, pages, page_texts, page_words)
        source = card.get("source") if isinstance(card.get("source"), dict) else {}
        quote = str(source.get("quote") or source.get("evidence") or card.get("evidence") or "")
        found_any = False
        for page_index in candidates[:4]:
            index = index_for(page_index)
            if index is None or not index.text.strip():
                continue
            if _looks_like_contents(index):
                continue
            near = _near_range(index, quote)
            page_masks: list[_Mask] = []
            kind = "cloze" if str(card.get("mode") or "") == "cloze" else "answer"
            for term in terms[:MAX_TERMS_PER_CARD]:
                boxes = find_term(index, term, near)
                if not boxes:
                    continue
                page_masks.append(
                    _Mask(
                        page=page_index,
                        boxes=boxes,
                        text=term,
                        kind=kind,
                        category=category,
                        uids={uid} if uid else set(),
                    )
                )
                if len(page_masks) >= 4:
                    break
            if not page_masks and kind == "answer" and quote:
                # Only a short quote is a useful blank. A long paragraph is
                # left visible; the student can select it by hand if wanted.
                if 2 <= len(_tokens(quote)) <= 10:
                    boxes = quote_boxes(index, quote, near)
                    if boxes:
                        page_masks.append(
                            _Mask(
                                page=page_index,
                                boxes=boxes,
                                text=quote[:160],
                                kind="quote",
                                category=category,
                                uids={uid} if uid else set(),
                            )
                        )
            if page_masks:
                found_any = True
                for mask in page_masks:
                    signature = (
                        mask.page,
                        tuple(
                            (
                                round(box["x"], 3),
                                round(box["y"], 3),
                                round(box["w"], 3),
                                round(box["h"], 3),
                            )
                            for box in mask.boxes
                        ),
                    )
                    if signature in seen_boxes:
                        existing = seen_boxes[signature]
                        existing.uids |= mask.uids
                        if existing.category != mask.category:
                            existing.category = "mixed"
                        continue
                    seen_boxes[signature] = mask
                    masks.append(mask)
                break
        if found_any:
            masked_cards += 1
        if len(masks) >= MAX_MASKS:
            stats["truncated"] = True
            break

    if pdf is not None:
        try:
            pdf.close()
        except Exception:
            pass

    masks = _merge_masks(masks)
    masks.sort(key=lambda mask: (mask.page, min(box["y"] for box in mask.boxes), min(box["x"] for box in mask.boxes)))
    output: list[dict] = []
    for mask in masks:
        seed = "|".join(
            [
                str(mask.page),
                mask.text,
                ",".join(
                    f"{box['x']:.4f}:{box['y']:.4f}:{box['w']:.4f}:{box['h']:.4f}"
                    for box in mask.boxes
                ),
            ]
        )
        output.append(
            {
                "id": "card-" + hashlib.sha1(seed.encode("utf-8")).hexdigest()[:16],
                "page": mask.page,
                "kind": mask.kind,
                "category": mask.category,
                "text": mask.text[:160],
                "boxes": mask.boxes,
                "uids": sorted(mask.uids)[:8],
            }
        )
    stats["maskedCards"] = masked_cards
    stats["masks"] = len(output)
    stats["terms"] = sum(len(mask["boxes"]) for mask in output)
    stats["pages"] = len({mask["page"] for mask in output})
    return {"masks": output, "stats": stats}


__all__ = [
    "answer_terms",
    "build_masks",
    "card_category",
    "card_terms",
    "cloze_terms",
    "find_term",
]
