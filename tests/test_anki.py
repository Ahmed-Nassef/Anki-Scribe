import pytest

from app import anki
from app.config import Settings


def test_note_building_basic_and_cloze():
    basic = anki._note_for(
        {
            "question": "Which receptor?",
            "answer": "<b>Beta-1</b>",
            "extra": "Metoprolol is cardioselective.",
        },
        "basic",
        ["cardiology"],
        "Cardiology",
        None,
    )
    assert basic["modelName"] == "Basic"
    assert basic["deckName"] == "Cardiology"
    assert basic["fields"]["Front"] == "Which receptor?"
    assert "<b>Beta-1</b>" in basic["fields"]["Back"]
    assert "<i>Metoprolol" in basic["fields"]["Back"]
    assert set(basic["fields"]) == {"Front", "Back"}

    cloze = anki._note_for(
        {"text": "The {{c1::mitral valve}} prevents backflow.", "extra": ""},
        "cloze",
        [],
        "Cardiology",
        None,
    )
    assert cloze["modelName"] == "Cloze"
    assert cloze["fields"]["Text"] == "The {{c1::mitral valve}} prevents backflow."


def test_note_building_with_our_model_carries_provenance():
    note = anki._note_for(
        {
            "question": "Which receptor?",
            "answer": "Beta-1",
            "extra": "",
            "evidence": "Metoprolol is cardioselective.",
            "sourceLabel": "lecture3.pdf",
            "sourcePage": "Page 4",
            "uid": "abc123",
        },
        "basic",
        [],
        "Cardiology",
        anki.MODEL_BASIC,
    )
    assert note["modelName"] == anki.MODEL_BASIC
    fields = note["fields"]
    assert fields["Source"] == "lecture3.pdf"
    assert fields["Page"] == "Page 4"
    assert fields["Quote"] == "Metoprolol is cardioselective."
    assert fields["QuestionId"] == "abc123"
    assert set(fields) == set(anki.BASIC_FIELDS)


def test_note_building_escapes_source_fields():
    note = anki._note_for(
        {
            "question": "Q",
            "answer": "A",
            "sourceLabel": '<script>x</script>',
            "evidence": "quoted <b>evidence</b> here",
        },
        "basic",
        [],
        "Deck",
        anki.MODEL_BASIC,
    )
    assert "<script>" not in note["fields"]["Source"]
    assert "&lt;script&gt;" in note["fields"]["Source"]
    assert "<b>evidence</b>" in note["fields"]["Quote"]


def test_note_building_rejects_empty_basic():
    with pytest.raises(anki.AnkiError):
        anki._note_for({"question": "", "answer": ""}, "basic", [], "Deck", None)


def test_push_cards(monkeypatch):
    calls = []

    def fake_invoke(settings, action, **params):
        calls.append((action, params))
        if action == "modelNames":
            return ["Basic", "Cloze"]
        if action == "addNotes":
            return [101, None, 102]
        return 1

    monkeypatch.setattr(anki, "_invoke", fake_invoke)
    result = anki.push_cards(
        Settings(api_key="sk-test", default_tags="anki-scribe"),
        "Cardiology",
        [
            {
                "mode": "basic",
                "question": "Q1",
                "answer": "A1",
                "extra": "",
                "tags": ["lecture-3"],
            },
            {"mode": "cloze", "text": "The {{c1::heart}} pumps blood.", "tags": []},
            {"mode": "basic", "question": "Q2", "answer": "A2", "tags": []},
        ],
        extra_tags="exam-1",
    )

    assert result["total"] == 3
    assert result["created"] == 2
    assert result["duplicates"] == 1
    assert result["noteIds"] == [101, None, 102]
    actions = [action for action, _ in calls]
    assert actions[0] == "modelNames"
    assert "createDeck" in actions
    assert "addNotes" in actions
    notes = dict(calls)["addNotes"]["notes"]
    assert len(notes) == 3
    assert notes[0]["deckName"] == "Cardiology"
    assert "exam-1" in notes[0]["tags"]
    assert "lecture-3" in notes[0]["tags"]
    assert "anki-scribe" in notes[0]["tags"]
    # A fresh collection gets our note type, created once per mode.
    assert notes[0]["modelName"] == anki.MODEL_BASIC
    assert notes[1]["modelName"] == anki.MODEL_CLOZE
    assert actions.count("createModel") == 2


def test_push_uses_stock_fields_when_creation_fails(monkeypatch):
    captured = {}

    def fake_invoke(settings, action, **params):
        if action == "modelNames":
            return ["Basic"]
        if action == "createModel":
            raise anki.AnkiError("blocked")
        if action == "addNotes":
            captured["notes"] = params["notes"]
            return [7]
        return 1

    monkeypatch.setattr(anki, "_invoke", fake_invoke)
    anki.push_cards(
        Settings(api_key="sk-test"),
        "Deck",
        [
            {
                "mode": "basic",
                "question": "Q",
                "answer": "A",
                "sourceLabel": "lecture.pdf",
                "sourcePage": "Page 2",
            }
        ],
    )
    note = captured["notes"][0]
    assert note["modelName"] == "Basic"
    assert "lecture.pdf" in note["fields"]["Back"]


def test_push_raises_when_no_usable_note_type(monkeypatch):
    def fake_invoke(settings, action, **params):
        if action == "modelNames":
            return []
        raise anki.AnkiError("blocked")

    monkeypatch.setattr(anki, "_invoke", fake_invoke)
    with pytest.raises(anki.AnkiError, match="no 'Basic' note type"):
        anki.push_cards(
            Settings(api_key="sk-test"),
            "Deck",
            [{"mode": "basic", "question": "Q", "answer": "A"}],
        )


def test_preflight_reports_duplicates_without_writing(monkeypatch):
    calls = []

    def fake_invoke(settings, action, **params):
        calls.append(action)
        if action == "modelNames":
            return ["Basic", "Cloze", anki.MODEL_BASIC]
        if action == "canAddNotes":
            return [True, False, True]
        raise AssertionError(f"unexpected action {action}")

    monkeypatch.setattr(anki, "_invoke", fake_invoke)
    result = anki.preflight(
        Settings(api_key="sk-test"),
        "Deck",
        [
            {"mode": "basic", "question": "Q1", "answer": "A1"},
            {"mode": "basic", "question": "Q2", "answer": "A2"},
            {"mode": "basic", "question": "Q3", "answer": "A3"},
        ],
    )
    assert result["total"] == 3
    assert result["addable"] == 2
    assert result["duplicates"] == 1
    assert result["results"] == [True, False, True]
    assert "addNotes" not in calls


def test_preflight_rejects_bad_answer(monkeypatch):
    def fake_invoke(settings, action, **params):
        if action == "modelNames":
            return ["Basic", anki.MODEL_BASIC]
        return {"unexpected": True}

    monkeypatch.setattr(anki, "_invoke", fake_invoke)
    with pytest.raises(anki.AnkiError):
        anki.preflight(
            Settings(api_key="sk-test"),
            "Deck",
            [{"mode": "basic", "question": "Q", "answer": "A"}],
        )


def test_status_handles_connection_failure(monkeypatch):
    def fail(settings, action, **params):
        raise anki.AnkiError("nope")

    monkeypatch.setattr(anki, "_invoke", fail)
    status = anki.status(Settings())
    assert status["connected"] is False
    assert "nope" in status["message"]


def test_push_requires_deck(monkeypatch):
    monkeypatch.setattr(anki, "_invoke", lambda *args, **kwargs: ["Basic"])
    with pytest.raises(anki.AnkiError):
        anki.push_cards(Settings(), "", [{"mode": "basic", "question": "Q", "answer": "A"}])


def test_create_and_rename_deck(monkeypatch):
    calls = []

    def fake_invoke(settings, action, **params):
        calls.append((action, params))
        if action == "deckNames":
            return ["Cardiology", "Cardiology::Lecture 3"]
        return 1

    monkeypatch.setattr(anki, "_invoke", fake_invoke)

    assert anki.create_deck(Settings(), "Cardiology::Lecture 3") == "Cardiology::Lecture 3"
    assert calls[-1] == ("createDeck", {"deck": "Cardiology::Lecture 3"})

    assert anki.rename_deck(Settings(), "Cardiology", "Cardio") == "Cardio"
    assert calls[-1] == (
        "renameDeck",
        {"oldName": "Cardiology", "newName": "Cardio"},
    )

    assert anki.deck_names(Settings()) == ["Cardiology", "Cardiology::Lecture 3"]


def test_create_deck_rejects_empty_name(monkeypatch):
    monkeypatch.setattr(anki, "_invoke", lambda *args, **kwargs: 1)
    with pytest.raises(anki.AnkiError):
        anki.create_deck(Settings(), "   ")


def test_read_review_history_joins_notes_and_cards(monkeypatch):
    def fake(settings, action, **params):
        if action == "notesInfo":
            return [
                {
                    "noteId": 10,
                    "modelName": "Anki Scribe Basic",
                    "cards": [100],
                    "fields": {
                        "Front": {"value": "What is <b>PE</b>?"},
                        "Back": {"value": "Private equity"},
                    },
                },
                {
                    "noteId": 11,
                    "modelName": "Anki Scribe Basic",
                    "cards": [101],
                    "fields": {
                        "Front": {"value": "Hard card"},
                        "Back": {"value": "Answer"},
                    },
                },
            ]
        if action == "cardsInfo":
            return [
                {
                    "cardId": 100,
                    "deckName": "Anki Scribe",
                    "reps": 8,
                    "lapses": 2,
                    "type": 2,
                    "interval": 12,
                    "due": 123,
                },
                {
                    "cardId": 101,
                    "deckName": "Anki Scribe",
                    "reps": 9,
                    "lapses": 4,
                    "type": 2,
                    "interval": 2,
                    "due": 124,
                },
            ]
        raise AssertionError(action)

    monkeypatch.setattr(anki, "_invoke", fake)
    result = anki.read_review_history(Settings(api_key="sk-test"), [10, 11])
    assert result["totals"] == {
        "notes": 2,
        "cards": 2,
        "learned": 2,
        "new": 0,
        "lapsed": 2,
        "leeches": 1,
    }
    assert result["leeches"][0]["noteId"] == 11
    assert result["leeches"][0]["front"] == "Hard card"
    assert result["leeches"][0]["lapses"] == 4
