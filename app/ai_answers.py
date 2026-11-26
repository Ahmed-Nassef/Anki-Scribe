"""LLM-assisted answer detection for the PDF study view.

The local matcher in :mod:`app.answers` usually finds the answer from the card's
own cloze deletion or answer phrasing. When it cannot, the model is asked for a
verbatim quote from the page; this module maps those quotes back to character
boxes. The model never supplies coordinates, so it cannot hide arbitrary text.
"""

from __future__ import annotations

import hashlib
import json
from typing import Callable

import pymupdf

from . import answers, llm
from .config import Settings
from .store import Document

MAX_AI_CARDS = 80
MAX_AI_CARDS_PER_CALL = 8
MAX_QUOTES_PER_CARD = 3


def _page_texts(doc: Document, pages: set[int], page_lines) -> dict[int, str]:
    texts: dict[int, str] = {}
    pdf = None
    try:
        pdf = pymupdf.open(doc.source)
    except Exception:
        pdf = None
    try:
        for page in sorted(pages):
            text = ""
            if pdf is not None and page < pdf.page_count:
                try:
                    text = pdf[page].get_text("text")
                except Exception:
                    text = ""
            if not text and page_lines is not None:
                try:
                    lines, _ocr = page_lines(page)
                    text = "\n".join(str(line.get("text") or "") for line in lines)
                except Exception:
                    text = ""
            texts[page] = text
    finally:
        if pdf is not None:
            try:
                pdf.close()
            except Exception:
                pass
    return texts


def _choose_page(card: dict, pages: list[int], texts: dict[int, str]) -> int | None:
    if not pages:
        return None
    source = card.get("source") if isinstance(card.get("source"), dict) else {}
    quote = str(source.get("quote") or source.get("evidence") or card.get("evidence") or "")
    quote_words = answers._tokens(quote)
    if len(quote_words) < 2:
        return pages[0] if texts.get(pages[0]) else None
    best: tuple[float, int] | None = None
    for page in pages:
        page_words = answers._tokens(texts.get(page, ""))
        score = answers._quote_score(quote_words, page_words)
        if best is None or score > best[0]:
            best = (score, page)
    if best is None:
        return None
    return best[1]


def _mask_payload(masks: list[answers._Mask]) -> dict:
    masks = answers._merge_masks(masks)
    masks.sort(
        key=lambda mask: (
            mask.page,
            min(box["y"] for box in mask.boxes),
            min(box["x"] for box in mask.boxes),
        )
    )
    output: list[dict] = []
    for mask in masks:
        seed = json.dumps(
            [mask.page, mask.text, mask.boxes, sorted(mask.uids)],
            ensure_ascii=False,
            sort_keys=True,
        )
        output.append(
            {
                "id": "ai-" + hashlib.sha1(seed.encode("utf-8")).hexdigest()[:16],
                "page": mask.page,
                "kind": "ai",
                "category": mask.category,
                "text": mask.text[:160],
                "boxes": mask.boxes,
                "uids": sorted(mask.uids)[:8],
            }
        )
    return {"masks": output}


def build_ai_masks(
    doc: Document,
    cards: list[dict],
    settings: Settings,
    page_lines: Callable[[int], list[dict]] | None = None,
) -> dict:
    stats = {
        "cards": 0,
        "calls": 0,
        "pages": 0,
        "quotes": 0,
        "masks": 0,
        "skipped": 0,
    }
    if not cards or not settings.api_key:
        return {"masks": [], "stats": stats}

    prepared: list[dict] = []
    seen: set[str] = set()
    for raw in cards[:MAX_AI_CARDS]:
        if not isinstance(raw, dict):
            continue
        uid = str(raw.get("uid") or raw.get("id") or "")
        pages = answers._range_pages(raw, len(doc.pages))
        if not uid or uid in seen or not pages:
            continue
        seen.add(uid)
        prepared.append(raw)
    stats["cards"] = len(prepared)
    if not prepared:
        return {"masks": [], "stats": stats}

    needed: set[int] = set()
    for card in prepared:
        needed.update(answers._range_pages(card, len(doc.pages)))
    if not needed:
        return {"masks": [], "stats": stats}
    texts = _page_texts(doc, needed, page_lines)
    grouped: dict[int, list[dict]] = {}
    for card in prepared:
        pages = answers._range_pages(card, len(doc.pages))
        chosen = _choose_page(card, pages, texts)
        if chosen is None:
            stats["skipped"] += 1
            continue
        grouped.setdefault(chosen, []).append(card)

    pdf = None
    try:
        pdf = pymupdf.open(doc.source)
    except Exception:
        pdf = None
    indexes: dict[int, answers._PageText] = {}

    def index_for(page: int) -> answers._PageText | None:
        if page in indexes:
            return indexes[page]
        try:
            if pdf is not None and page < pdf.page_count:
                index = answers._page_from_pdf(pdf[page], page)
                if index.text.strip():
                    indexes[page] = index
                    return index
        except Exception:
            pass
        if page_lines is not None:
            try:
                lines, _ocr = page_lines(page)
                index = answers._page_from_lines(doc.pages[page], lines)
                indexes[page] = index
                return index
            except Exception:
                pass
        indexes[page] = answers._PageText(page=page)
        return indexes[page]

    masks: list[answers._Mask] = []
    try:
        for page in sorted(grouped):
            cards_on_page = grouped[page]
            index = index_for(page)
            if index is None or not index.text.strip():
                stats["skipped"] += len(cards_on_page)
                continue
            for start in range(0, len(cards_on_page), MAX_AI_CARDS_PER_CALL):
                batch = cards_on_page[start : start + MAX_AI_CARDS_PER_CALL]
                payload = []
                for card in batch:
                    source = card.get("source") if isinstance(card.get("source"), dict) else {}
                    payload.append(
                        {
                            "question": str(card.get("question") or ""),
                            "answer": str(card.get("answer") or ""),
                            "evidence": str(
                                source.get("quote")
                                or source.get("evidence")
                                or card.get("evidence")
                                or ""
                            ),
                        }
                    )
                try:
                    located = llm.locate_answer_spans(
                        settings,
                        f"Page {page + 1}",
                        texts.get(page, ""),
                        payload,
                    )
                    stats["calls"] += 1
                except llm.LLMError:
                    raise
                except Exception:
                    stats["skipped"] += len(batch)
                    continue
                for entry in located:
                    card = batch[entry["card"] - 1]
                    uid = str(card.get("uid") or card.get("id") or "")
                    source = card.get("source") if isinstance(card.get("source"), dict) else {}
                    quote = str(
                        source.get("quote")
                        or source.get("evidence")
                        or card.get("evidence")
                        or ""
                    )
                    near = answers._near_range(index, quote)
                    for text in entry.get("quotes", [])[:MAX_QUOTES_PER_CARD]:
                        matches = answers._phrase_matches(index, text)
                        boxes = answers._best_match(matches, near)
                        if not boxes:
                            stats["skipped"] += 1
                            continue
                        masks.append(
                            answers._Mask(
                                page=page,
                                boxes=boxes,
                                text=text,
                                kind="ai",
                                category=answers.card_category(card),
                                uids={uid} if uid else set(),
                            )
                        )
                        stats["quotes"] += 1
            stats["pages"] += 1
    finally:
        if pdf is not None:
            try:
                pdf.close()
            except Exception:
                pass

    result = _mask_payload(masks)
    stats["masks"] = len(result["masks"])
    return {"masks": result["masks"], "stats": stats}


__all__ = ["build_ai_masks"]
