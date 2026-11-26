import pytest

from app.drafts import DraftStore


def test_draft_store_persists_across_instances(tmp_path):
    path = tmp_path / "drafts.json"
    source = tmp_path / "Lecture.pdf"
    cards = [{"uid": "one", "question": "Q", "answer": "A"}]

    store = DraftStore(path)
    store.put(str(source), "Lecture.pdf", cards)

    reopened = DraftStore(path)
    draft = reopened.get(str(source))
    assert draft["filename"] == "Lecture.pdf"
    assert draft["cards"] == cards


def test_draft_store_returns_empty_for_unknown_source(tmp_path):
    store = DraftStore(tmp_path / "drafts.json")
    draft = store.get(str(tmp_path / "missing.pdf"))
    assert draft["cards"] == []
    assert draft["filename"] == ""


def test_draft_store_delete(tmp_path):
    store = DraftStore(tmp_path / "drafts.json")
    source = str(tmp_path / "lecture.pdf")
    store.put(source, "lecture.pdf", [{"uid": "one"}])
    store.delete(source)
    assert store.get(source)["cards"] == []


def test_draft_store_rejects_too_many_cards(tmp_path):
    store = DraftStore(tmp_path / "drafts.json")
    with pytest.raises(ValueError):
        store.put(str(tmp_path / "lecture.pdf"), "lecture.pdf", [{}] * 2001)


def test_counts_reports_cards_per_source(tmp_path):
    store = DraftStore(tmp_path / "drafts.json")
    first = str(tmp_path / "a.pdf")
    second = str(tmp_path / "b.pdf")
    store.put(first, "a.pdf", [{"uid": "1"}, {"uid": "2"}])
    store.put(second, "b.pdf", [{"uid": "3"}])

    counts = store.counts()
    assert sum(counts.values()) == 3
    assert sorted(counts.values()) == [1, 2]
