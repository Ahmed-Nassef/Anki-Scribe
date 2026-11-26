"""Tests for LLM-assisted answer locations, without network calls."""

from __future__ import annotations

from types import SimpleNamespace

import pymupdf
import pytest

from app import ai_answers, llm
from app.config import Settings


def make_pdf(tmp_path, text="The dose is 5 mg twice a day."):
    pdf = pymupdf.open()
    page = pdf.new_page(width=600, height=800)
    page.insert_text((60, 120), text, fontsize=13)
    path = tmp_path / "page.pdf"
    path.write_bytes(pdf.tobytes())
    pdf.close()
    return path


def card(**extra):
    base = {
        "uid": "dose-card",
        "mode": "basic",
        "type": "number",
        "question": "What is the dose?",
        "answer": "5 mg twice a day",
        "source": {"pages": [0, 0], "quote": "The dose is 5 mg twice a day."},
    }
    base.update(extra)
    return base


def test_ai_masks_map_exact_quotes_with_category(tmp_path, monkeypatch):
    path = make_pdf(tmp_path)
    doc = SimpleNamespace(pages=[None], source=str(path))

    def fake(settings, page_label, page_text, cards, **kwargs):
        assert page_label == "Page 1"
        assert cards
        return [{"card": 1, "quotes": ["5 mg twice a day"]}]

    monkeypatch.setattr(ai_answers.llm, "locate_answer_spans", fake)
    result = ai_answers.build_ai_masks(
        doc,
        [card()],
        Settings(api_key="sk-test"),
    )
    assert result["stats"]["calls"] == 1
    assert result["stats"]["cards"] == 1
    assert len(result["masks"]) == 1
    mask = result["masks"][0]
    assert mask["page"] == 0
    assert mask["category"] == "dose"
    assert mask["uids"] == ["dose-card"]
    assert mask["boxes"]


def test_ai_quotes_that_are_not_verbatim_are_skipped(tmp_path, monkeypatch):
    path = make_pdf(tmp_path)
    doc = SimpleNamespace(pages=[None], source=str(path))
    monkeypatch.setattr(
        ai_answers.llm,
        "locate_answer_spans",
        lambda *args, **kwargs: [
            {"card": 1, "quotes": ["a paraphrase that is not on the page"]}
        ],
    )
    result = ai_answers.build_ai_masks(
        doc,
        [card()],
        Settings(api_key="sk-test"),
    )
    assert result["masks"] == []
    assert result["stats"]["skipped"] >= 1


def test_ai_masks_need_an_api_key(tmp_path):
    path = make_pdf(tmp_path)
    doc = SimpleNamespace(pages=[None], source=str(path))
    result = ai_answers.build_ai_masks(doc, [card()], Settings(api_key=""))
    assert result["masks"] == []


def test_locate_answer_spans_parses_and_filters(monkeypatch):
    content = (
        '{"answers":[{"card":1,"quotes":["5 mg twice a day","5 mg twice a day",'
        '"too much text that is absolutely not on this page at all"]},'
        '{"card":99,"quotes":["nope"]}]}'
    )
    monkeypatch.setattr(llm, "_chat", lambda settings, messages: content)
    result = llm.locate_answer_spans(
        Settings(api_key="sk-test"),
        "Page 1",
        "The dose is 5 mg twice a day.",
        [{"question": "dose?", "answer": "5 mg", "evidence": "5 mg twice a day"}],
    )
    assert result == [{"card": 1, "quotes": ["5 mg twice a day", "too much text that is absolutely not on this page at all"]}]


def test_locate_answer_spans_requires_a_key():
    with pytest.raises(llm.LLMError):
        llm.locate_answer_spans(Settings(api_key=""), "Page 1", "text", [card()])
