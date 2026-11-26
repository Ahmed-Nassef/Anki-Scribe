import json

from app.sent import MAX_SENT_PER_SOURCE, SentStore


def test_append_and_read_round_trip(tmp_path):
    store = SentStore(tmp_path / "sent.json")
    source = str(tmp_path / "lecture.pdf")

    store.append(
        source,
        "lecture.pdf",
        [
            {"id": "a", "noteId": 1, "question": "Q1", "source": {"pages": [1, 1]}},
            {"id": "b", "noteId": 2, "question": "Q2"},
        ],
    )

    record = store.get(source)
    assert len(record["cards"]) == 2
    assert record["filename"] == "lecture.pdf"
    assert record["updatedAt"] > 0
    assert store.count(source) == 2


def test_append_replaces_a_card_with_the_same_id(tmp_path):
    store = SentStore(tmp_path / "sent.json")
    source = str(tmp_path / "lecture.pdf")

    store.append(source, "lecture.pdf", [{"id": "a", "question": "old"}])
    store.append(source, "lecture.pdf", [{"id": "a", "question": "new"}])

    cards = store.get(source)["cards"]
    assert len(cards) == 1
    assert cards[0]["question"] == "new"


def test_ledger_persists_across_instances(tmp_path):
    path = tmp_path / "sent.json"
    source = str(tmp_path / "lecture.pdf")
    SentStore(path).append(source, "lecture.pdf", [{"id": "a", "question": "Q"}])

    reopened = SentStore(path)
    assert reopened.count(source) == 1
    assert reopened.get(source)["cards"][0]["question"] == "Q"


def test_same_file_different_case_is_one_source(tmp_path):
    store = SentStore(tmp_path / "sent.json")
    upper = str(tmp_path / "LECTURE.PDF")
    lower = str(tmp_path / "lecture.pdf")

    store.append(upper, "LECTURE.PDF", [{"id": "a"}])
    store.append(lower, "lecture.pdf", [{"id": "b"}])

    assert store.count(upper) == 2


def test_cards_are_capped_per_source(tmp_path):
    store = SentStore(tmp_path / "sent.json")
    source = str(tmp_path / "big.pdf")
    cards = [{"id": f"c{index}"} for index in range(MAX_SENT_PER_SOURCE + 5)]
    store.append(source, "big.pdf", cards)

    stored = store.get(source)["cards"]
    assert len(stored) == MAX_SENT_PER_SOURCE
    # The newest survive; the oldest are trimmed.
    assert stored[-1]["id"] == f"c{MAX_SENT_PER_SOURCE + 4}"


def test_delete_clears_one_source_only(tmp_path):
    store = SentStore(tmp_path / "sent.json")
    first = str(tmp_path / "a.pdf")
    second = str(tmp_path / "b.pdf")
    store.append(first, "a.pdf", [{"id": "a"}])
    store.append(second, "b.pdf", [{"id": "b"}])

    store.delete(first)

    assert store.count(first) == 0
    assert store.count(second) == 1


def test_corrupt_file_is_treated_as_empty(tmp_path):
    path = tmp_path / "sent.json"
    path.write_text("{not json", encoding="utf-8")
    store = SentStore(path)
    assert store.get(str(tmp_path / "x.pdf"))["cards"] == []


def test_non_dict_file_is_ignored(tmp_path):
    path = tmp_path / "sent.json"
    path.write_text(json.dumps([1, 2, 3]), encoding="utf-8")
    assert SentStore(path).sources() == []


def test_sources_lists_one_row_per_file(tmp_path):
    store = SentStore(tmp_path / "sent.json")
    store.append(str(tmp_path / "a.pdf"), "a.pdf", [{"id": "1"}, {"id": "2"}])
    rows = store.sources()
    assert len(rows) == 1
    assert rows[0]["count"] == 2
