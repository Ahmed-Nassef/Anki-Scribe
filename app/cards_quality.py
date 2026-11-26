"""Card quality: what kind of knowledge a card tests, and what is wrong with it.

Pure functions only — no I/O, no model calls, no clock. Shared by the generation
path (:mod:`app.llm`) and the push guard (:mod:`app.main`), so a rule cannot
disagree with itself (constitution VIII).

The rules are deliberately high-precision. A false fault costs the student
attention on every review; a missed fault is caught later by triage. When in
doubt, a rule stays a warning.
"""

from __future__ import annotations

import html
import re
from typing import Any, Iterable

# -- vocabulary ----------------------------------------------------------

TYPES: tuple[str, ...] = (
    "definition",
    "mechanism",
    "compare",
    "application",
    "enumeration",
    "number",
)
DEFAULT_TYPE = "definition"

BLOCKING = "blocking"
WARNING = "warning"
INFO = "info"
_SEVERITY_RANK = {BLOCKING: 0, WARNING: 1, INFO: 2}

# -- policy --------------------------------------------------------------
# One place for every threshold. Tests import these; nothing else may
# hard-code a number.

MAX_CLOZE_DELETIONS = 3
MAX_DELETION_WORDS = 8
MIN_QUESTION_WORDS = 5
RESTATEMENT_RATIO = 0.8
MIN_QUESTION_CONTENT_TOKENS = 3
INTERFERENCE_JACCARD = 0.8
MAX_INTERFERENCE_BUCKET = 40
MAX_INTERFERENCE_COMPARISONS = 20_000
MAX_BLOCKED_REPORTED = 50

_FAULTS: dict[str, tuple[str, str]] = {
    "empty_side": ("a required side is empty", BLOCKING),
    "open_ended": ("it asks for an essay, not a recallable fact", BLOCKING),
    "answer_leak": ("the answer is already in the question", BLOCKING),
    "cloze_overloaded": ("too many deletions, or one deletion too long", BLOCKING),
    "list_answer": ("the answer is a list, not one fact", WARNING),
    "vague_question": ("the question does not stand alone", WARNING),
    "bare_number": ("the answer is a bare number with no unit", WARNING),
    "untagged": ("no tags", WARNING),
    "interference_pair": ("nearly the same front as another card here", WARNING),
}

# -- text helpers --------------------------------------------------------

_STOPWORDS = frozenset(
    """
    a an the and or nor but if then than that this these those of to in on at by
    for with from into onto over under about above below between among during
    before after per via as is are was were be been being am do does did done
    doing has have had having it its their there here they them he she his her
    him we our us you your yours i me my mine who whom whose what which when
    where why how not no only also more most less least very can could may
    might must shall should will would just both each few many much other some
    such own same so too don doesn isn wasn weren won wouldn shouldn couldn
    """.split()
)

_TAG_RE = re.compile(r"<[^>]+>")
_CLOZE_RE = re.compile(r"\{\{c(\d+)::(.*?)(?:::.*?)?\}\}", re.DOTALL)
_WORD_RE = re.compile(r"[0-9a-z]+(?:'[0-9a-z]+)?")
_SPACE_RE = re.compile(r"\s+")

_OPEN_ENDED_RE = re.compile(
    r"^(?:explain|describe|discuss|list|outline|summari[sz]e|compare and contrast)\b",
    re.IGNORECASE,
)
_WHICH_OF_THE_FOLLOWING = "which of the following"
_YES_NO_RE = re.compile(r"^(?:yes|no|true|false)\b", re.IGNORECASE)
_LIST_JOINER_RE = re.compile(r"\b(?:such as|including|e\.g\.)\b", re.IGNORECASE)
_BARE_NUMBER_RE = re.compile(r"^[+-]?\d[\d,. ]*$")
_VAGUE_TAIL_RE = re.compile(
    r"\b(?:this|these|those|the text|the excerpt|the document|the passage)\s*\?*$",
    re.IGNORECASE,
)


def clean(value: Any) -> str:
    """Plain text for a card side: tags stripped, entities folded, one spacing."""
    text = "" if value is None else str(value)
    text = _TAG_RE.sub(" ", text)
    text = html.unescape(text)
    return _SPACE_RE.sub(" ", text).strip()


def words(text: str) -> list[str]:
    return _WORD_RE.findall(text.casefold())


def content_tokens(text: str) -> set[str]:
    """Words that carry meaning: at least three characters, not a stop word."""
    return {word for word in words(text) if len(word) >= 3 and word not in _STOPWORDS}


def cloze_deletions(text: str) -> list[str]:
    return [match.group(2) for match in _CLOZE_RE.finditer(text)]


def unwrap_cloze(text: str) -> str:
    return _CLOZE_RE.sub(r"\2", text)


def card_type(card: dict) -> str:
    """The card's type, normalised; unknown or missing values read as definition."""
    value = card.get("type")
    if isinstance(value, str):
        candidate = value.strip().casefold()
        if candidate in TYPES:
            return candidate
    return DEFAULT_TYPE


def _mode(card: dict) -> str:
    return str(card.get("mode") or "basic").strip().casefold()


def _has_picture(card: dict) -> bool:
    figure = card.get("figure")
    if isinstance(figure, dict) and figure.get("masked"):
        return True
    image = card.get("image")
    return isinstance(image, dict) and bool(image.get("name"))


# -- faults --------------------------------------------------------------


def _fault(code: str, detail: str = "") -> dict:
    label, severity = _FAULTS[code]
    return {"code": code, "label": label, "severity": severity, "detail": detail}


def sort_faults(faults: Iterable[dict]) -> list[dict]:
    """Deterministic: blocking first, then code, then detail."""
    return sorted(
        faults,
        key=lambda fault: (
            _SEVERITY_RANK.get(str(fault.get("severity")), 9),
            str(fault.get("code", "")),
            str(fault.get("detail", "")),
        ),
    )


# -- per-card rules ------------------------------------------------------


def _empty_side_faults(card: dict, question: str, answer: str, text: str) -> list[dict]:
    if _mode(card) == "cloze":
        return [_fault("empty_side", "text")] if not text else []
    faults: list[dict] = []
    if not question:
        faults.append(_fault("empty_side", "question"))
    if not answer and not _has_picture(card):
        faults.append(_fault("empty_side", "answer"))
    return faults


def _open_ended_faults(question: str) -> list[dict]:
    if not question:
        return []
    if _OPEN_ENDED_RE.match(question) or _WHICH_OF_THE_FOLLOWING in question.casefold():
        return [_fault("open_ended", "")]
    return []


def _answer_leak_faults(question: str, answer: str) -> list[dict]:
    """Three precise ways an answer can already be in its question.

    A definition card ("What is preload?" -> "Preload is ...") is *not* a leak:
    naming the term is what a definition question is for. So the restatement
    rule needs a question with real content, and containment needs an answer of
    at least two content words.
    """
    if not question or not answer:
        return []
    if _YES_NO_RE.match(answer):
        return [_fault("answer_leak", "yes/no answer")]

    question_tokens = content_tokens(question)
    answer_tokens = content_tokens(answer)
    if not question_tokens or not answer_tokens:
        return []

    if len(answer_tokens) >= 2 and answer_tokens <= question_tokens:
        return [_fault("answer_leak", "every answer word is in the question")]

    if len(question_tokens) >= MIN_QUESTION_CONTENT_TOKENS:
        shared = len(question_tokens & answer_tokens)
        if shared / len(question_tokens) >= RESTATEMENT_RATIO:
            return [_fault("answer_leak", "the answer restates the question")]
    return []


def _cloze_faults(text: str) -> list[dict]:
    deletions = cloze_deletions(text)
    if not deletions:
        return []
    if len(deletions) > MAX_CLOZE_DELETIONS:
        return [_fault("cloze_overloaded", f"{len(deletions)} deletions")]
    longest = max(len(words(deletion)) for deletion in deletions)
    if longest > MAX_DELETION_WORDS:
        return [_fault("cloze_overloaded", f"{longest}-word deletion")]
    return []


def _list_answer_faults(answer: str) -> list[dict]:
    if len(content_tokens(answer)) < 4:
        return []
    separators = answer.count(",") + answer.count(";")
    if separators < 2:
        return []
    if re.search(r"\band\b", answer, re.IGNORECASE) or _LIST_JOINER_RE.search(answer):
        return [_fault("list_answer", f"{separators + 1} items")]
    return []


def _vague_question_faults(question: str) -> list[dict]:
    if not question:
        return []
    if len(words(question)) < MIN_QUESTION_WORDS:
        return [_fault("vague_question", "too short")]
    if _VAGUE_TAIL_RE.search(question):
        return [_fault("vague_question", "points at the text")]
    return []


def _bare_number_faults(answer: str) -> list[dict]:
    if not answer or not _BARE_NUMBER_RE.match(answer):
        return []
    return [_fault("bare_number", answer[:20])]


def evaluate_card(card: dict) -> list[dict]:
    """Every per-card fault, in deterministic order. Batch rules are not here."""
    mode = _mode(card)
    question = clean(card.get("question", ""))
    answer = clean(card.get("answer", ""))
    text = clean(card.get("text", ""))

    faults: list[dict] = []
    faults.extend(_empty_side_faults(card, question, answer, text))

    if mode == "cloze":
        faults.extend(_cloze_faults(text))
    else:
        faults.extend(_open_ended_faults(question))
        faults.extend(_answer_leak_faults(question, answer))
        faults.extend(_list_answer_faults(answer))
        faults.extend(_vague_question_faults(question))
        faults.extend(_bare_number_faults(answer))

    tags = card.get("tags")
    if not isinstance(tags, list) or not [tag for tag in tags if str(tag).strip()]:
        faults.append(_fault("untagged", ""))

    return sort_faults(faults)


# -- batch rules ---------------------------------------------------------


def _front_text(card: dict) -> str:
    if _mode(card) == "cloze":
        return unwrap_cloze(clean(card.get("text", "")))
    return clean(card.get("question", ""))


def _jaccard(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return 0.0
    shared = len(left & right)
    return shared / (len(left) + len(right) - shared)


def _interference(cards: list[dict]) -> list[list[dict]]:
    """Flag pairs of cards with near-identical fronts.

    Bucketed like the browser's risk ranking: each card is indexed under its two
    rarest tokens, so a near-duplicate (which differs in one word) almost always
    still shares one. Buckets that are too generic and a hard comparison budget
    keep a 2,000-card batch cheap.
    """
    found: list[list[dict]] = [[] for _ in cards]
    tokens = [content_tokens(_front_text(card)) for card in cards]

    frequency: dict[str, int] = {}
    for item in tokens:
        for token in item:
            frequency[token] = frequency.get(token, 0) + 1

    buckets: dict[str, list[int]] = {}
    for index, item in enumerate(tokens):
        ranked = sorted(item, key=lambda token: (frequency.get(token, 0), token))
        for token in ranked[:2]:
            buckets.setdefault(token, []).append(index)

    compared: set[tuple[int, int]] = set()
    comparisons = 0
    for indexes in buckets.values():
        if len(indexes) < 2 or len(indexes) > MAX_INTERFERENCE_BUCKET:
            continue
        for left_at in range(len(indexes)):
            for right_at in range(left_at + 1, len(indexes)):
                if comparisons >= MAX_INTERFERENCE_COMPARISONS:
                    return found
                left, right = indexes[left_at], indexes[right_at]
                if left == right:
                    continue
                pair = (left, right) if left < right else (right, left)
                if pair in compared:
                    continue
                compared.add(pair)
                comparisons += 1
                if _jaccard(tokens[left], tokens[right]) < INTERFERENCE_JACCARD:
                    continue
                found[left].append(
                    _fault("interference_pair", _front_text(cards[right])[:60])
                )
                found[right].append(
                    _fault("interference_pair", _front_text(cards[left])[:60])
                )
    return found


def evaluate_batch(cards: list[dict]) -> list[list[dict]]:
    """Per-card faults plus interference, aligned with the input list."""
    batch_faults = _interference(cards)
    result: list[list[dict]] = []
    for card, extra in zip(cards, batch_faults):
        result.append(sort_faults(evaluate_card(card) + extra))
    return result


def annotate_cards(cards: list[dict]) -> list[dict]:
    """Return copies of the cards carrying their normalised ``type`` and ``faults``."""
    annotated: list[dict] = []
    for card, faults in zip(cards, evaluate_batch(cards)):
        entry = dict(card)
        entry["type"] = card_type(card)
        entry["faults"] = faults
        annotated.append(entry)
    return annotated


# -- reporting -----------------------------------------------------------


def blocking_faults(faults: Iterable[dict]) -> list[dict]:
    return [fault for fault in faults if fault.get("severity") == BLOCKING]


def blocked_cards(cards: list[dict]) -> dict:
    """The cards a push must refuse, with enough context for the student.

    Returns ``{"count": n, "cards": [...]}``: the true count, and a report capped
    at :data:`MAX_BLOCKED_REPORTED` so one bad run cannot produce a huge response.
    """
    report: list[dict] = []
    count = 0
    for card, faults in zip(cards, evaluate_batch(cards)):
        severe = blocking_faults(faults)
        if not severe:
            continue
        count += 1
        if len(report) >= MAX_BLOCKED_REPORTED:
            continue
        report.append(
            {
                "uid": str(card.get("uid") or ""),
                "question": _front_text(card)[:160],
                "faults": severe,
            }
        )
    return {"count": count, "cards": report}


def type_counts(cards: list[dict]) -> dict[str, int]:
    """How many cards of each type, omitting types that do not occur."""
    counts: dict[str, int] = {}
    for card in cards:
        key = card_type(card)
        counts[key] = counts.get(key, 0) + 1
    return counts
