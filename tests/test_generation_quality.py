"""Generation carries types and faults, and the prompt states the rules (US1, US2, US4)."""

from __future__ import annotations

import json

import pytest

from app import llm
from app.config import Settings

EXCERPT = (
    "Metoprolol reduces mortality in heart failure with reduced ejection fraction "
    "by blocking beta-1 receptors on cardiac myocytes."
)


def settings() -> Settings:
    return Settings(api_key="sk-test-key")


def reply(cards: list[dict]) -> str:
    return json.dumps({"cards": cards})


MECHANISM = {
    "type": "mechanism",
    "question": "Why does metoprolol reduce mortality in HFrEF?",
    "answer": "By blocking beta-1 receptors on cardiac myocytes.",
    "extra": "",
    "tags": ["cardiology"],
    "evidence": "reduces mortality in heart failure with reduced ejection fraction",
}

LEGACY = {
    "question": "Which enzyme converts angiotensin I to angiotensin II?",
    "answer": "ACE.",
    "tags": ["cardiology"],
    "evidence": "blocking beta-1 receptors on cardiac myocytes",
}


def test_generation_keeps_the_type(monkeypatch):
    monkeypatch.setattr(llm, "_chat", lambda settings, messages: reply([MECHANISM]))
    result = llm.generate_cards(settings(), EXCERPT)
    assert result["cards"][0]["type"] == "mechanism"


def test_generation_attaches_faults(monkeypatch):
    monkeypatch.setattr(llm, "_chat", lambda settings, messages: reply([MECHANISM]))
    result = llm.generate_cards(settings(), EXCERPT)
    assert result["cards"][0]["faults"] == []


def test_a_leaking_card_carries_a_blocking_fault(monkeypatch):
    leaky = dict(
        MECHANISM,
        question="Does metoprolol reduce mortality in heart failure?",
        answer="Yes, it does.",
    )
    monkeypatch.setattr(llm, "_chat", lambda settings, messages: reply([leaky]))
    card = llm.generate_cards(settings(), EXCERPT)["cards"][0]
    assert card["faults"][0]["code"] == "answer_leak"
    assert card["faults"][0]["severity"] == "blocking"


def test_a_reply_without_a_type_is_a_definition(monkeypatch):
    monkeypatch.setattr(llm, "_chat", lambda settings, messages: reply([LEGACY]))
    card = llm.generate_cards(settings(), EXCERPT)["cards"][0]
    assert card["type"] == "definition"
    assert card["faults"] == []


def test_an_unknown_type_falls_back(monkeypatch):
    odd = dict(MECHANISM, type="essay question")
    monkeypatch.setattr(llm, "_chat", lambda settings, messages: reply([odd]))
    assert llm.generate_cards(settings(), EXCERPT)["cards"][0]["type"] == "definition"


def test_cloze_generation_carries_type_and_faults(monkeypatch):
    cloze_card = {
        "type": "definition",
        "text": "{{c1::Metoprolol}} is a beta-1 selective blocker.",
        "extra": "",
        "tags": ["cardiology"],
        "evidence": "blocking beta-1 receptors on cardiac myocytes",
    }
    monkeypatch.setattr(llm, "_chat", lambda settings, messages: reply([cloze_card]))
    card = llm.generate_cards(settings(), EXCERPT, mode="cloze")["cards"][0]
    assert card["type"] == "definition"
    assert card["faults"] == []


def test_regenerate_returns_type_and_faults(monkeypatch):
    monkeypatch.setattr(llm, "_chat", lambda settings, messages: reply([MECHANISM]))
    result = llm.regenerate_card(
        settings(),
        EXCERPT,
        question="What does metoprolol do?",
        answer="It does something.",
    )
    assert result["card"]["type"] == "mechanism"
    assert result["card"]["faults"] == []


CLOZE_CARD = {
    "type": "definition",
    "text": "{{c1::Metoprolol}} is a beta-1 selective blocker.",
    "extra": "",
    "tags": ["cardiology"],
    "evidence": "blocking beta-1 receptors on cardiac myocytes",
}


def captured_system(monkeypatch, mode: str) -> str:
    captured = {}
    payload = CLOZE_CARD if mode == "cloze" else MECHANISM

    def fake_chat(settings, messages):
        captured["system"] = messages[0]["content"]
        return reply([payload])

    monkeypatch.setattr(llm, "_chat", fake_chat)
    llm.generate_cards(settings(), EXCERPT, mode=mode)
    return captured["system"]


@pytest.mark.parametrize("phrase", [
    'exactly one "type"',
    "Never open a question with Explain",
    "The question must not contain its answer",
    "one card per item or a cloze card",
])
def test_basic_prompt_states_the_rules(monkeypatch, phrase):
    assert phrase in captured_system(monkeypatch, "basic")


@pytest.mark.parametrize("phrase", [
    "a single cloze deletion",
    "never more than three",
    'exactly one "type"',
])
def test_cloze_prompt_states_the_rules(monkeypatch, phrase):
    assert phrase in captured_system(monkeypatch, "cloze")


def test_basic_prompt_does_not_ask_for_three_deletions(monkeypatch):
    assert "1-3 cloze deletions" not in captured_system(monkeypatch, "cloze")
