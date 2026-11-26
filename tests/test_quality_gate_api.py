"""API contract for the card quality gate (feature 001, US3)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import app.main as main_module
from app.config import Settings
from app.drafts import DraftStore
from app.library import Library
from app.main import create_app
from app.sent import SentStore
from app.store import Store

LEAKY = {
    "uid": "leak-1",
    "mode": "basic",
    "question": "Does metoprolol reduce mortality in heart failure?",
    "answer": "Yes, it does.",
    "tags": ["cardiology"],
}

CLEAN = {
    "uid": "clean-1",
    "mode": "basic",
    "question": "How does metoprolol differ from carvedilol in heart failure?",
    "answer": "Metoprolol blocks beta-1 only; carvedilol also blocks alpha-1.",
    "tags": ["cardiology"],
}

WARNING_ONLY = {
    "uid": "warn-1",
    "mode": "basic",
    "question": "Which drug classes are first line in hypertension?",
    "answer": "ACE inhibitors, ARBs, calcium channel blockers and thiazides.",
    "tags": [],
}


@pytest.fixture
def client(tmp_path):
    settings = Settings(api_key="sk-test-key", anki_url="http://127.0.0.1:9")
    app = create_app(
        store=Store(tmp_path / "documents"),
        settings=settings,
        library=Library(tmp_path / "library.json"),
        drafts=DraftStore(tmp_path / "drafts.json"),
        sent=SentStore(tmp_path / "sent.json"),
    )
    return TestClient(app, base_url="http://127.0.0.1")


def fake_push(*args, **kwargs):
    cards = args[2] if len(args) > 2 else kwargs["cards"]
    return {
        "deck": "Deck",
        "total": len(cards),
        "created": len(cards),
        "duplicates": 0,
        "noteIds": list(range(1, len(cards) + 1)),
    }


def test_push_refuses_a_blocking_card_and_writes_nothing(client, monkeypatch, tmp_path):
    called = {"pushed": False}

    def must_not_push(*args, **kwargs):
        called["pushed"] = True
        raise AssertionError("push must not reach Anki")

    monkeypatch.setattr(main_module.anki, "push_cards", must_not_push)
    source = str(tmp_path / "lecture.pdf")
    response = client.post(
        "/api/anki/push",
        json={"deck": "Deck", "cards": [LEAKY], "source_path": source, "filename": "lecture.pdf"},
    )
    assert response.status_code == 400, response.text
    detail = response.json()["detail"]
    assert detail["error"] == "blocked_cards"
    assert detail["message"] == "1 card has a blocking quality fault."
    assert detail["blocked"][0]["uid"] == "leak-1"
    assert detail["blocked"][0]["faults"][0]["code"] == "answer_leak"
    assert called["pushed"] is False
    assert client.get("/api/sent", params={"path": source}).json()["cards"] == []


def test_override_sends_the_same_batch(client, monkeypatch):
    monkeypatch.setattr(main_module.anki, "push_cards", fake_push)
    response = client.post(
        "/api/anki/push",
        json={"deck": "Deck", "cards": [LEAKY], "allow_blocked": True},
    )
    assert response.status_code == 200, response.text
    assert response.json()["created"] == 1


def test_preflight_applies_the_same_policy(client, monkeypatch):
    monkeypatch.setattr(main_module.anki, "preflight", lambda *a, **k: {})
    response = client.post("/api/anki/preflight", json={"deck": "Deck", "cards": [LEAKY]})
    assert response.status_code == 400
    assert response.json()["detail"]["error"] == "blocked_cards"

    allowed = client.post(
        "/api/anki/preflight",
        json={"deck": "Deck", "cards": [CLEAN], "allow_blocked": False},
    )
    assert allowed.status_code == 200, allowed.text


def test_warnings_do_not_block_a_push(client, monkeypatch):
    monkeypatch.setattr(main_module.anki, "push_cards", fake_push)
    response = client.post("/api/anki/push", json={"deck": "Deck", "cards": [WARNING_ONLY]})
    assert response.status_code == 200, response.text


def test_clean_cards_push(client, monkeypatch):
    monkeypatch.setattr(main_module.anki, "push_cards", fake_push)
    response = client.post("/api/anki/push", json={"deck": "Deck", "cards": [CLEAN]})
    assert response.status_code == 200, response.text


def test_count_reports_every_blocked_card(client, monkeypatch, tmp_path):
    monkeypatch.setattr(main_module.anki, "push_cards", fake_push)
    cards = [dict(LEAKY, uid=f"leak-{index}") for index in range(3)]
    response = client.post(
        "/api/anki/push",
        json={"deck": "Deck", "cards": cards, "source_path": str(tmp_path / "x.pdf")},
    )
    assert response.status_code == 400
    assert response.json()["detail"]["message"] == "3 cards have a blocking quality fault."
    assert len(response.json()["detail"]["blocked"]) == 3


def test_the_ledger_keeps_the_card_type(client, monkeypatch, tmp_path):
    monkeypatch.setattr(main_module.anki, "push_cards", fake_push)
    source = str(tmp_path / "lecture.pdf")
    typed = dict(CLEAN, type="compare")
    response = client.post(
        "/api/anki/push",
        json={
            "deck": "Deck",
            "cards": [typed],
            "source_path": source,
            "filename": "lecture.pdf",
        },
    )
    assert response.status_code == 200, response.text
    entry = response.json()["ledger"]["cards"][0]
    assert entry["type"] == "compare"
