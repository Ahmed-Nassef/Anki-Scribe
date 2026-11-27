import json

import pymupdf
import pytest
from fastapi.testclient import TestClient

import app.main as main_module
from app.config import Settings
from app.drafts import DraftStore
from app.library import UNSORTED_ID, Library
from app.main import create_app
from app.masks import MaskStore
from app.sent import SentStore
from app.store import Store


def pdf_bytes(text="Beta blockers reduce heart rate by blocking beta-1 receptors."):
    pdf = pymupdf.open()
    page = pdf.new_page(width=600, height=800)
    page.insert_text((60, 100), text, fontsize=13)
    data = pdf.tobytes()
    pdf.close()
    return data


@pytest.fixture
def client(tmp_path):
    settings = Settings(api_key="sk-test-key", anki_url="http://127.0.0.1:9")
    store = Store(tmp_path / "documents")
    library = Library(tmp_path / "library.json")
    drafts = DraftStore(tmp_path / "drafts.json")
    sent = SentStore(tmp_path / "sent.json")
    app = create_app(
        store=store,
        settings=settings,
        library=library,
        drafts=drafts,
        sent=sent,
        mask_store=MaskStore(tmp_path / "masks.json"),
    )
    # The app only accepts loopback Host headers; match that in the client.
    return TestClient(app, base_url="http://127.0.0.1")


def test_drafts_round_trip(client, tmp_path):
    source = str(tmp_path / "lecture.pdf")
    cards = [
        {
            "uid": "card-1",
            "mode": "basic",
            "selected": True,
            "question": "What do beta blockers do?",
            "answer": "Slow heart rate.",
            "tags": ["cardiology"],
            "source": {"label": "Page 1", "pages": [0, 0]},
        }
    ]
    saved = client.post(
        "/api/drafts",
        json={"path": source, "filename": "lecture.pdf", "cards": cards},
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["cards"] == cards

    loaded = client.get("/api/drafts", params={"path": source})
    assert loaded.status_code == 200, loaded.text
    assert loaded.json()["cards"] == cards
    assert loaded.json()["filename"] == "lecture.pdf"


def test_drafts_accept_a_whole_file_batch(client, tmp_path):
    """A run big enough to break the old keepalive request must still save."""
    source = str(tmp_path / "big.pdf")
    cards = [
        {
            "uid": f"card-{index}",
            "mode": "basic",
            "selected": True,
            "question": "Which receptor does metoprolol block selectively in the heart?",
            "answer": "Beta-1, which is why it spares the airway.",
            "tags": ["cardiology"],
            "evidence": "Metoprolol is cardioselective, so it causes less bronchospasm.",
            "source": {
                "kind": "chunk",
                "label": "Pages 4-5",
                "pages": [3, 4],
                "quote": "q" * 260,
                "chapterPath": ["Beta blockers"],
                "deckPath": ["Cardiology Lecture 3", "Beta blockers"],
            },
        }
        for index in range(150)
    ]
    payload_bytes = len(json.dumps({"path": source, "filename": "big.pdf", "cards": cards}))
    assert payload_bytes > 65_536  # the size that used to be undeliverable

    saved = client.post(
        "/api/drafts",
        json={"path": source, "filename": "big.pdf", "cards": cards},
    )
    assert saved.status_code == 200, saved.text
    assert len(client.get("/api/drafts", params={"path": source}).json()["cards"]) == 150


def test_ai_balance_endpoint(client, monkeypatch):
    monkeypatch.setattr(
        main_module.llm,
        "get_balance",
        lambda settings: {
            "isAvailable": True,
            "balances": [
                {
                    "currency": "USD",
                    "total": "12.34",
                    "granted": "2.00",
                    "toppedUp": "10.34",
                }
            ],
        },
    )
    response = client.get("/api/ai/balance")
    assert response.status_code == 200, response.text
    assert response.json()["balances"][0]["total"] == "12.34"


def test_health_and_index(client):
    payload = client.get("/api/health").json()
    assert payload["app"] == "anki-scribe"
    response = client.get("/")
    assert response.status_code == 200
    assert "Anki Scribe" in response.text


def test_health_names_the_data_folder(client):
    """A second launch uses this to tell our instance from a stray one."""
    from app.config import data_fingerprint

    assert client.get("/api/health").json()["data"] == data_fingerprint()


def test_push_accepts_long_chapter_deck_path(client, monkeypatch):
    deck = "medicine::lecture::" + ("x" * 120)
    captured = {}

    def fake_push(settings, deck, cards, extra_tags="", media=None):
        captured["deck"] = deck
        return {
            "deck": deck,
            "total": len(cards),
            "created": len(cards),
            "duplicates": 0,
        }

    monkeypatch.setattr(main_module.anki, "push_cards", fake_push)
    response = client.post(
        "/api/anki/push",
        json={
            "deck": deck,
            "cards": [{"question": "Question", "answer": "Answer"}],
        },
    )
    assert response.status_code == 200, response.text
    assert captured["deck"] == deck


def test_document_coverage_endpoint(client):
    uploaded = client.post(
        "/api/documents",
        files={"file": ("lecture.pdf", pdf_bytes(), "application/pdf")},
    )
    doc_id = uploaded.json()["id"]
    response = client.get(f"/api/documents/{doc_id}/coverage")
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["contentPages"] == 1
    assert data["textPages"] == 1
    assert data["pages"][0]["chars"] > 0


def test_document_chapters_and_range_extract(client):
    pdf = pymupdf.open()
    for index in range(4):
        page = pdf.new_page(width=600, height=800)
        page.insert_text((60, 60), f"Chapter {index // 2 + 1}", fontsize=20)
        page.insert_text((60, 120), f"Content page {index + 1}", fontsize=12)
    pdf.set_toc([[1, "Chapter One", 1], [1, "Chapter Two", 3]])
    data = pdf.tobytes()
    pdf.close()

    uploaded = client.post(
        "/api/documents",
        files={"file": ("book.pdf", data, "application/pdf")},
    )
    doc_id = uploaded.json()["id"]
    plan = client.get(f"/api/documents/{doc_id}/chapters")
    assert plan.status_code == 200, plan.text
    assert plan.json()["strategy"] == "toc"
    assert plan.json()["chapterCount"] == 2

    extract = client.get(
        f"/api/documents/{doc_id}/extract", params={"start_page": 3, "end_page": 4}
    )
    assert extract.status_code == 200, extract.text
    assert extract.json()["selectedPageCount"] == 2
    assert all(chunk["pages"][0] >= 3 for chunk in extract.json()["chunks"])


def test_upload_pdf_and_read_lines(client):
    response = client.post(
        "/api/documents",
        files={"file": ("lecture.pdf", pdf_bytes(), "application/pdf")},
    )
    assert response.status_code == 200, response.text
    doc = response.json()
    assert doc["pageCount"] == 1
    assert doc["kind"] == "pdf"

    lines = client.get(f"/api/documents/{doc['id']}/pages/0/lines").json()
    assert any("Beta blockers" in line["text"] for line in lines["lines"])
    assert lines["ocr"] is False

    image = client.get(f"/api/documents/{doc['id']}/pages/0/image")
    assert image.status_code == 200
    assert image.headers["content-type"] == "image/png"


def test_extract_endpoint(client):
    upload = client.post(
        "/api/documents",
        files={"file": ("lecture.pdf", pdf_bytes(), "application/pdf")},
    )
    doc = upload.json()
    response = client.get(f"/api/documents/{doc['id']}/extract")
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["pageCount"] == 1
    assert len(payload["chunks"]) == 1
    assert "Beta blockers" in payload["chunks"][0]["text"]
    assert payload["chunks"][0]["label"] == "Page 1"


def test_upload_rejects_unsupported_type(client):
    response = client.post(
        "/api/documents",
        files={"file": ("notes.txt", b"hello", "text/plain")},
    )
    assert response.status_code == 415


def test_generate_endpoint(client, monkeypatch):
    def fake_generate(
        settings, text, mode, count, filename, page, whole_file=False, strict=False, style="balanced"
    ):
        return {
            "cards": [
                {"question": "Q?", "answer": "<b>A</b>", "extra": "", "tags": ["x"]}
            ],
            "mode": mode,
            "model": settings.model,
        }

    monkeypatch.setattr(main_module.llm, "generate_cards", fake_generate)
    response = client.post(
        "/api/generate",
        json={"text": "x" * 60, "mode": "basic", "count": 3, "filename": "a.pdf"},
    )
    assert response.status_code == 200
    assert response.json()["cards"][0]["answer"] == "<b>A</b>"


def test_push_endpoint(client, monkeypatch):
    def fake_push(settings, deck, cards, extra_tags="", media=None):
        return {"deck": deck, "total": len(cards), "created": len(cards), "duplicates": 0}

    monkeypatch.setattr(main_module.anki, "push_cards", fake_push)
    payload = {
        "deck": "Cardiology",
        "tags": "lecture-3",
        "cards": [
            {"mode": "basic", "question": "Q", "answer": "A", "tags": ["x"]},
        ],
    }
    response = client.post("/api/anki/push", json=payload)
    assert response.status_code == 200
    assert response.json()["created"] == 1


def test_create_subdeck_endpoint(client, monkeypatch):
    captured = {}

    def fake_create(settings, name):
        captured["name"] = name
        return name

    monkeypatch.setattr(main_module.anki, "create_deck", fake_create)
    monkeypatch.setattr(
        main_module.anki,
        "deck_names",
        lambda settings: ["Cardiology", "Cardiology::Lecture 3"],
    )

    response = client.post(
        "/api/anki/decks",
        json={"parent": "Cardiology", "name": "Lecture 3"},
    )
    assert response.status_code == 200, response.text
    assert captured["name"] == "Cardiology::Lecture 3"
    assert response.json()["name"] == "Cardiology::Lecture 3"
    assert "Cardiology::Lecture 3" in response.json()["decks"]


def test_rename_deck_endpoint(client, monkeypatch):
    captured = {}

    def fake_rename(settings, old, new):
        captured["old"] = old
        captured["new"] = new
        return new

    monkeypatch.setattr(main_module.anki, "rename_deck", fake_rename)
    monkeypatch.setattr(main_module.anki, "deck_names", lambda settings: ["Cardio"])

    response = client.post(
        "/api/anki/decks/rename",
        json={"old": "Cardiology", "new": "Cardio"},
    )
    assert response.status_code == 200, response.text
    assert captured == {"old": "Cardiology", "new": "Cardio"}
    assert response.json()["name"] == "Cardio"


def test_create_subdeck_rejects_blank_path(client, monkeypatch):
    monkeypatch.setattr(main_module.anki, "create_deck", lambda *args: "x")
    response = client.post("/api/anki/decks", json={"parent": "", "name": "   "})
    assert response.status_code == 400


def test_settings_never_return_key(client):
    response = client.get("/api/settings")
    assert response.json()["has_key"] is True
    assert "api_key" not in response.json()

    updated = client.put(
        "/api/settings",
        json={"default_deck": "Neurology", "api_key": "sk-new-key-123456"},
    )
    assert updated.status_code == 200
    assert updated.json()["default_deck"] == "Neurology"
    assert updated.json()["key_hint"] == "3456"
    assert "sk-new-key-123456" not in updated.text


def test_anki_status_when_offline(client):
    response = client.get("/api/anki/status")
    assert response.status_code == 200
    assert response.json()["connected"] is False


def test_document_list(client):
    client.post(
        "/api/documents",
        files={"file": ("lecture.pdf", pdf_bytes(), "application/pdf")},
    )
    listing = client.get("/api/documents").json()["documents"]
    assert len(listing) == 1
    assert listing[0]["filename"] == "lecture.pdf"


def test_library_import_and_open(client, tmp_path):
    source = tmp_path / "library-lecture.pdf"
    source.write_bytes(pdf_bytes())

    imported = client.post("/api/library/import", json={"paths": [str(source)]})
    assert imported.status_code == 200, imported.text
    payload = imported.json()
    assert len(payload["added"]) == 1
    file_id = payload["added"][0]["id"]
    assert payload["library"]["files"][0]["path"] == str(source)

    opened = client.post(f"/api/library/files/{file_id}/open")
    assert opened.status_code == 200, opened.text
    doc = opened.json()
    assert doc["pageCount"] == 1
    assert doc["libraryFileId"] == file_id
    assert source.exists()

    snapshot = client.get("/api/library").json()
    assert snapshot["lastOpenedFileId"] == file_id


def test_library_transcript_import_open_coverage_and_extract(client, tmp_path):
    source = tmp_path / "lecture.srt"
    source.write_text(
        "1\n00:00:01,000 --> 00:00:03,000\nBeta blockers reduce heart rate.\n\n"
        "2\n00:00:10,000 --> 00:00:12,000\nMetoprolol is cardioselective.\n",
        encoding="utf-8",
    )
    imported = client.post("/api/library/import", json={"paths": [str(source)]})
    assert imported.status_code == 200, imported.text
    file_id = imported.json()["added"][0]["id"]

    opened = client.post(f"/api/library/files/{file_id}/open")
    assert opened.status_code == 200, opened.text
    doc = opened.json()
    assert doc["kind"] == "transcript"
    assert doc["segmentCount"] == 2
    assert doc["segments"][0]["text"] == "Beta blockers reduce heart rate."

    extract = client.get(f"/api/documents/{doc['id']}/extract")
    assert extract.status_code == 200, extract.text
    assert extract.json()["chunks"][0]["segments"] == [1, 2]

    coverage = client.get(f"/api/documents/{doc['id']}/coverage")
    assert coverage.status_code == 200, coverage.text
    assert coverage.json()["kind"] == "transcript"
    assert coverage.json()["unit"] == "segments"
    assert coverage.json()["contentPages"] == 2
    assert source.exists()


def test_library_pick_uses_native_picker(client, tmp_path, monkeypatch):
    source = tmp_path / "picked.pdf"
    source.write_bytes(pdf_bytes())
    monkeypatch.setattr(main_module.picker, "pick_files", lambda: [str(source)])

    response = client.post("/api/library/pick", json={"group_id": UNSORTED_ID})
    assert response.status_code == 200, response.text
    payload = response.json()
    assert len(payload["added"]) == 1
    assert payload["added"][0]["name"] == "picked.pdf"


def test_library_groups_and_move(client, tmp_path):
    source = tmp_path / "grouped.pdf"
    source.write_bytes(pdf_bytes())
    file_id = client.post(
        "/api/library/import", json={"paths": [str(source)]}
    ).json()["added"][0]["id"]

    created = client.post("/api/library/groups", json={"name": "Cardiology"})
    assert created.status_code == 200, created.text
    group = next(
        item for item in created.json()["groups"] if item["name"] == "Cardiology"
    )

    moved = client.patch(
        f"/api/library/files/{file_id}", json={"group_id": group["id"]}
    )
    assert moved.status_code == 200
    assert moved.json()["files"][0]["groupId"] == group["id"]

    renamed = client.patch(
        f"/api/library/groups/{group['id']}", json={"name": "Cardio"}
    )
    assert renamed.status_code == 200
    assert any(item["name"] == "Cardio" for item in renamed.json()["groups"])

    deleted = client.delete(f"/api/library/groups/{group['id']}")
    assert deleted.status_code == 200
    assert deleted.json()["files"][0]["groupId"] == UNSORTED_ID


def test_library_missing_file_cannot_open(client, tmp_path):
    source = tmp_path / "gone.pdf"
    source.write_bytes(pdf_bytes())
    file_id = client.post(
        "/api/library/import", json={"paths": [str(source)]}
    ).json()["added"][0]["id"]
    source.unlink()

    response = client.post(f"/api/library/files/{file_id}/open")
    assert response.status_code == 400
    assert "missing" in response.json()["detail"].lower()

    snapshot = client.get("/api/library").json()
    assert snapshot["files"][0]["exists"] is False


def test_library_remove_only_removes_reference(client, tmp_path):
    source = tmp_path / "keep.pdf"
    source.write_bytes(pdf_bytes())
    file_id = client.post(
        "/api/library/import", json={"paths": [str(source)]}
    ).json()["added"][0]["id"]

    response = client.delete(f"/api/library/files/{file_id}")
    assert response.status_code == 200
    assert response.json()["files"] == []


# -- sent ledger ---------------------------------------------------------


def test_push_writes_sent_ledger(client, monkeypatch, tmp_path):
    source = str(tmp_path / "lecture3.pdf")

    def fake_push(settings, deck, cards, extra_tags="", media=None):
        return {
            "deck": deck,
            "total": len(cards),
            "created": len(cards),
            "duplicates": 0,
            "noteIds": [1000 + index for index in range(len(cards))],
        }

    monkeypatch.setattr(main_module.anki, "push_cards", fake_push)
    response = client.post(
        "/api/anki/push",
        json={
            "deck": "Anki Scribe::Lecture 3",
            "source_path": source,
            "filename": "lecture3.pdf",
            "cards": [
                {
                    "mode": "basic",
                    "question": "Which receptor do beta blockers block?",
                    "answer": "Beta-1",
                    "uid": "card-1",
                    "evidence": "Beta blockers reduce heart rate",
                    "sourcePage": "Page 4",
                    "source": {
                        "kind": "selection",
                        "pages": [3, 3],
                        "ignored": "should be dropped",
                    },
                },
                {
                    "mode": "basic",
                    "question": "What does metoprolol treat?",
                    "answer": "Hypertension",
                    "uid": "card-2",
                },
            ],
        },
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["ledger"]["saved"] is True
    assert payload["ledger"]["path"] == source
    assert len(payload["ledger"]["cards"]) == 2

    stored = client.get("/api/sent", params={"path": source}).json()
    assert len(stored["cards"]) == 2
    first = stored["cards"][0]
    assert first["noteId"] == 1000
    assert first["id"] == "card-1"
    assert first["deck"] == "Anki Scribe::Lecture 3"
    assert first["source"]["pages"] == [3, 3]
    assert "ignored" not in first["source"]
    assert first["fingerprint"]


def test_push_without_source_path_keeps_result_and_skips_ledger(client, monkeypatch):
    def fake_push(settings, deck, cards, extra_tags="", media=None):
        return {
            "deck": deck,
            "total": 1,
            "created": 1,
            "duplicates": 0,
            "noteIds": [5],
        }

    monkeypatch.setattr(main_module.anki, "push_cards", fake_push)
    response = client.post(
        "/api/anki/push",
        json={"deck": "Deck", "cards": [{"question": "Q", "answer": "A", "uid": "x"}]},
    )
    assert response.status_code == 200
    assert response.json()["ledger"]["saved"] is False
    assert response.json()["created"] == 1


def test_sent_ledger_survives_clear_and_delete(client, tmp_path):
    source = str(tmp_path / "keep.pdf")
    assert client.get("/api/sent", params={"path": source}).json()["cards"] == []

    cleared = client.delete("/api/sent", params={"path": source})
    assert cleared.status_code == 200
    assert cleared.json()["cleared"] is True


def test_preflight_endpoint_proxies_anki(client, monkeypatch):
    captured = {}

    def fake_preflight(settings, deck, cards, extra_tags=""):
        captured["deck"] = deck
        captured["count"] = len(cards)
        return {
            "total": len(cards),
            "addable": 1,
            "duplicates": len(cards) - 1,
            "results": [True] + [False] * (len(cards) - 1),
            "models": ["Anki Scribe Basic"],
        }

    monkeypatch.setattr(main_module.anki, "preflight", fake_preflight)
    response = client.post(
        "/api/anki/preflight",
        json={
            "deck": "Deck",
            "cards": [
                {"question": "Q1", "answer": "A1"},
                {"question": "Q2", "answer": "A2"},
            ],
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["addable"] == 1
    assert captured == {"deck": "Deck", "count": 2}


def test_preflight_surfaces_anki_errors(client, monkeypatch):
    from app.anki import AnkiError

    def fail(settings, deck, cards, extra_tags=""):
        raise AnkiError("Couldn't reach Anki")

    monkeypatch.setattr(main_module.anki, "preflight", fail)
    response = client.post(
        "/api/anki/preflight",
        json={"deck": "Deck", "cards": [{"question": "Q", "answer": "A"}]},
    )
    assert response.status_code == 502
    assert "reach Anki" in response.json()["detail"]


def test_library_snapshot_counts_drafts_and_sent(client, monkeypatch, tmp_path):
    source = tmp_path / "lecture.pdf"
    source.write_bytes(pdf_bytes())
    client.post("/api/library/import", json={"paths": [str(source)]})
    client.post(
        "/api/drafts",
        json={
            "path": str(source),
            "filename": "lecture.pdf",
            "cards": [{"uid": "d1", "question": "Q", "answer": "A"}],
        },
    )

    def fake_push(settings, deck, cards, extra_tags="", media=None):
        return {
            "deck": deck,
            "total": len(cards),
            "created": len(cards),
            "duplicates": 0,
            "noteIds": [900 + index for index in range(len(cards))],
        }

    monkeypatch.setattr(main_module.anki, "push_cards", fake_push)
    client.post(
        "/api/anki/push",
        json={
            "deck": "Deck",
            "source_path": str(source),
            "filename": "lecture.pdf",
            "cards": [
                {"question": "Q1", "answer": "A1", "uid": "s1"},
                {"question": "Q2", "answer": "A2", "uid": "s2"},
            ],
        },
    )

    files = client.get("/api/library").json()["files"]
    assert len(files) == 1
    assert files[0]["draftCount"] == 1
    assert files[0]["sentCount"] == 2


def test_library_counts_are_zero_for_a_fresh_file(client, tmp_path):
    source = tmp_path / "fresh.pdf"
    source.write_bytes(pdf_bytes())
    client.post("/api/library/import", json={"paths": [str(source)]})
    file = client.get("/api/library").json()["files"][0]
    assert file["draftCount"] == 0
    assert file["sentCount"] == 0


# -- regenerate one card -------------------------------------------------


def test_generate_one_proxies_to_the_rewriter(client, monkeypatch):
    captured = {}

    def fake_regenerate(settings, text, **kwargs):
        captured["text"] = text
        captured["kwargs"] = kwargs
        return {
            "card": {"question": "Sharper?", "answer": "Yes", "verified": True},
            "mode": "basic",
            "nudge": kwargs.get("nudge"),
            "model": settings.model,
        }

    monkeypatch.setattr(main_module.llm, "regenerate_card", fake_regenerate)
    response = client.post(
        "/api/generate/one",
        json={
            "text": "Metoprolol is cardioselective, so it causes less bronchospasm.",
            "question": "What does metoprolol do?",
            "answer": "Beta blocker",
            "nudge": "clinical",
            "style": "trap",
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["nudge"] == "clinical"
    assert captured["kwargs"]["nudge"] == "clinical"
    assert captured["kwargs"]["style"] == "trap"
    assert captured["kwargs"]["question"] == "What does metoprolol do?"


def test_generate_one_maps_llm_errors(client, monkeypatch):
    def fail(settings, text, **kwargs):
        raise main_module.llm.LLMError("This card has no saved quote to rewrite from.", 400)

    monkeypatch.setattr(main_module.llm, "regenerate_card", fail)
    response = client.post("/api/generate/one", json={"text": "x" * 40})
    assert response.status_code == 400
    assert "no saved quote" in response.json()["detail"]


# -- objectives ----------------------------------------------------------


def objectives_pdf() -> bytes:
    pdf = pymupdf.open()
    page = pdf.new_page(width=595, height=842)
    lines = [
        "Cardiology Lecture 3",
        "Learning objectives",
        "- Describe the phases of the cardiac cycle in order",
        "- Explain the Frank-Starling relationship and its limits",
        "- Differentiate restrictive from constrictive pericarditis",
    ]
    y = 80
    for line in lines:
        page.insert_text((60, y), line, fontsize=11)
        y += 20
    data = pdf.tobytes()
    pdf.close()
    return data


def test_objectives_endpoint_detects_a_block(client):
    uploaded = client.post(
        "/api/documents",
        files={"file": ("objectives.pdf", objectives_pdf(), "application/pdf")},
    )
    doc_id = uploaded.json()["id"]

    response = client.get(f"/api/documents/{doc_id}/objectives")
    assert response.status_code == 200, response.text
    items = response.json()["objectives"]
    assert len(items) == 3
    assert items[0]["text"] == "Describe the phases of the cardiac cycle in order"
    assert items[0]["label"] == "Page 1"
    assert items[0]["unit"] == 0


def test_objectives_endpoint_returns_empty_for_plain_pages(client):
    uploaded = client.post(
        "/api/documents",
        files={"file": ("plain.pdf", pdf_bytes(), "application/pdf")},
    )
    doc_id = uploaded.json()["id"]
    assert client.get(f"/api/documents/{doc_id}/objectives").json()["objectives"] == []


def test_objectives_endpoint_404s_for_unknown_document(client):
    assert client.get("/api/documents/missing/objectives").status_code == 404


# -- hidden answers on the PDF page ---------------------------------------


def test_answer_masks_endpoint_returns_page_boxes(client):
    pdf = pymupdf.open()
    page = pdf.new_page(width=600, height=800)
    page.insert_text((60, 60), "The Formats", fontsize=24)
    page.insert_text((60, 120), "The Banking Directive regulates banks.", fontsize=13)
    data = pdf.tobytes()
    pdf.close()
    uploaded = client.post(
        "/api/documents",
        files={"file": ("lecture.pdf", data, "application/pdf")},
    )
    doc_id = uploaded.json()["id"]
    payload = {
        "cards": [
            {
                "uid": "c1",
                "mode": "cloze",
                "text": "The {{c1::Banking Directive}} regulates banks.",
                "type": "definition",
                "source": {
                    "pages": [0, 0],
                    "quote": "The Banking Directive regulates banks.",
                },
            }
        ]
    }
    response = client.post(f"/api/documents/{doc_id}/answer-masks", json=payload)
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["stats"]["cards"] == 1
    assert result["stats"]["maskedCards"] == 1
    assert result["masks"][0]["page"] == 0
    assert result["masks"][0]["text"] == "Banking Directive"
    assert result["masks"][0]["category"] == "definition"
    assert result["masks"][0]["uids"] == ["c1"]
    assert result["masks"][0]["boxes"][0]["w"] > 0

    # The second call comes from the in-memory cache and is identical.
    cached = client.post(f"/api/documents/{doc_id}/answer-masks", json=payload)
    assert cached.status_code == 200
    assert cached.json() == result


def test_answer_masks_unknown_document_is_a_404(client):
    response = client.post(
        "/api/documents/nope/answer-masks",
        json={"cards": []},
    )
    assert response.status_code == 404


def test_manual_masks_round_trip(client, tmp_path):
    path = str(tmp_path / "lecture.pdf")
    mask = {
        "id": "manual-1",
        "text": "2%",
        "boxes": [{"page": 3, "x": 0.5, "y": 0.7, "w": 0.05, "h": 0.02}],
    }
    saved = client.post("/api/masks", json={"path": path, "masks": [mask]})
    assert saved.status_code == 200, saved.text
    assert saved.json()["masks"][0]["id"] == "manual-1"
    assert saved.json()["masks"][0]["boxes"][0]["page"] == 3

    loaded = client.get("/api/masks", params={"path": path})
    assert loaded.status_code == 200, loaded.text
    assert loaded.json()["masks"] == saved.json()["masks"]

    cleared = client.delete("/api/masks", params={"path": path})
    assert cleared.status_code == 200, cleared.text
    assert client.get("/api/masks", params={"path": path}).json()["masks"] == []


def test_manual_mask_with_no_boxes_is_rejected(client, tmp_path):
    response = client.post(
        "/api/masks",
        json={
            "path": str(tmp_path / "lecture.pdf"),
            "masks": [{"id": "bad", "text": "x", "boxes": []}],
        },
    )
    assert response.status_code == 400


# -- study plan -----------------------------------------------------------


def test_plan_endpoint_returns_a_day_by_day_schedule(client):
    response = client.post(
        "/api/plan",
        json={
            "start": "2026-11-23",
            "deadline": "2026-12-07",
            "cards": 120,
            "minutes": 60,
            "weekdays": [0, 1, 2, 3, 4, 5, 6],
            "buffer_days": 2,
            "retention": 0.9,
            "rating": 3,
        },
    )
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["feasible"] is True
    assert data["summary"]["cards"] == 120
    assert data["summary"]["learned"] == 120
    assert data["days"]
    assert data["days"][-1]["date"] < "2026-12-07"
    assert all(row["minutes"] <= 60 for row in data["days"])


def test_plan_endpoint_reports_an_impossible_plan(client):
    response = client.post(
        "/api/plan",
        json={
            "start": "2026-11-23",
            "deadline": "2026-11-30",
            "cards": 500,
            "minutes": 30,
            "buffer_days": 2,
        },
    )
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["feasible"] is False
    assert data["summary"]["suggestedCards"] < 500


def test_plan_endpoint_rejects_bad_input(client):
    response = client.post(
        "/api/plan",
        json={
            "start": "2026-11-23",
            "deadline": "2026-11-23",
            "cards": 20,
            "minutes": 60,
        },
    )
    assert response.status_code == 400


def test_ai_answer_masks_endpoint(client, monkeypatch):
    import app.ai_answers as ai_answers

    pdf = pymupdf.open()
    page = pdf.new_page(width=600, height=800)
    page.insert_text((60, 120), "The dose is 5 mg twice a day.", fontsize=13)
    data = pdf.tobytes()
    pdf.close()
    uploaded = client.post(
        "/api/documents",
        files={"file": ("dose.pdf", data, "application/pdf")},
    )
    doc_id = uploaded.json()["id"]

    monkeypatch.setattr(
        ai_answers.llm,
        "locate_answer_spans",
        lambda *args, **kwargs: [{"card": 1, "quotes": ["5 mg twice a day"]}],
    )
    response = client.post(
        f"/api/documents/{doc_id}/ai-answer-masks",
        json={
            "cards": [
                {
                    "uid": "dose",
                    "mode": "basic",
                    "type": "number",
                    "question": "What is the dose?",
                    "answer": "5 mg twice a day",
                    "source": {
                        "pages": [0, 0],
                        "quote": "The dose is 5 mg twice a day.",
                    },
                }
            ]
        },
    )
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["masks"]
    assert result["masks"][0]["category"] == "dose"
    assert result["masks"][0]["uids"] == ["dose"]


def test_ocr_status_endpoint_for_a_text_pdf(client):
    uploaded = client.post(
        "/api/documents",
        files={"file": ("text.pdf", pdf_bytes(), "application/pdf")},
    )
    doc_id = uploaded.json()["id"]
    status = client.get(f"/api/documents/{doc_id}/ocr").json()
    assert status["pending"] == 0
    assert status["total"] == 0
    assert status["running"] is False
    started = client.post(f"/api/documents/{doc_id}/ocr").json()
    assert started["pending"] == 0
    assert client.post(f"/api/documents/{doc_id}/ocr/cancel").status_code == 200


def test_uploading_a_scanned_pdf_starts_background_ocr(client, monkeypatch):
    import time

    import app.store as store_module

    def fake(image_path, width):
        return [
            {
                "text": "Scanned text.",
                "x0": 20.0,
                "y0": 30.0,
                "x1": 200.0,
                "y1": 50.0,
            }
        ]

    monkeypatch.setattr(store_module, "ocr_lines", fake)
    pdf = pymupdf.open()
    pdf.new_page(width=600, height=800)
    data = pdf.tobytes()
    pdf.close()
    uploaded = client.post(
        "/api/documents",
        files={"file": ("scan.pdf", data, "application/pdf")},
    )
    doc_id = uploaded.json()["id"]
    deadline = time.time() + 5
    status = client.get(f"/api/documents/{doc_id}/ocr").json()
    while status["running"] and time.time() < deadline:
        time.sleep(0.02)
        status = client.get(f"/api/documents/{doc_id}/ocr").json()
    assert status["pending"] == 0
    assert status["done"] == 1
    lines = client.get(f"/api/documents/{doc_id}/pages/0/lines").json()
    assert lines["lines"][0]["text"] == "Scanned text."
    assert lines["ocr"] is True


def test_static_js_is_revalidated(client):
    response = client.get("/static/js/ocr.js")
    assert response.status_code == 200
    assert "no-cache" in response.headers.get("cache-control", "")


def test_plan_sources_counts_selected_files(client, tmp_path):
    source = tmp_path / "planned.pdf"
    source.write_bytes(pdf_bytes())
    library = client.app.state.library
    file, _ = library.add_file(str(source))
    drafts = client.app.state.drafts
    drafts.put(
        file.path,
        file.name,
        [
            {"uid": "a", "mode": "basic", "question": "q", "answer": "a"},
            {
                "uid": "b",
                "mode": "cloze",
                "text": "{{c1::one}} and {{c2::two}}",
            },
            {"uid": "c", "mode": "figure"},
        ],
    )
    client.app.state.sent.append(
        file.path,
        file.name,
        [{"id": "s1", "mode": "basic", "question": "q", "answer": "a"}],
    )
    client.app.state.masks.put(
        file.path,
        [
            {
                "id": "m1",
                "text": "hidden",
                "boxes": [{"page": 0, "x": 0.1, "y": 0.1, "w": 0.2, "h": 0.05}],
            }
        ],
    )
    response = client.post("/api/plan/sources", json={"file_ids": [file.id]})
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["total"] == {
        "basic": 2,
        "cloze": 2,
        "figure": 1,
        "manual": 1,
        "total": 6,
    }
    assert result["files"][0]["name"] == "planned.pdf"


def test_batch_jobs_listing_and_empty_create(client):
    listing = client.get("/api/batch-jobs")
    assert listing.status_code == 200
    assert listing.json()["jobs"] == []
    empty = client.post("/api/batch-jobs", json={"file_ids": []})
    assert empty.status_code == 400


def test_study_review_and_session_endpoints(client):
    reviewed = client.post(
        "/api/study/review",
        json={"uid": "study-card", "question": "What?", "rating": 3, "seconds": 9},
    )
    assert reviewed.status_code == 200, reviewed.text
    assert reviewed.json()["review"]["interval"] == 1
    snapshot = client.get("/api/study").json()
    assert "study-card" in snapshot["reviews"]
    assert snapshot["stats"]["reviews"] == 0

    saved = client.post(
        "/api/study/session",
        json={"total": 2, "correct": 2, "seconds": 40, "streak": 2},
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["stats"]["retention"] == 1.0
