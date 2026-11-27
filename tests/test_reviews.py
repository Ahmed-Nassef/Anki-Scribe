"""Server-side study review scheduling and analytics."""

from __future__ import annotations

from app.reviews import ReviewStore


def test_grade_schedules_the_next_review(tmp_path):
    store = ReviewStore(tmp_path / "study.json")
    first = store.review({"uid": "card-1", "question": "Q"}, 3, 12)
    assert first["reps"] == 1
    assert first["interval"] == 1
    assert first["due"] > first["last"]
    second = store.review({"uid": "card-1", "question": "Q"}, 4, 8)
    assert second["reps"] == 2
    assert second["interval"] >= 4
    assert second["lapses"] == 0


def test_again_counts_a_lapse_and_returns_today(tmp_path):
    store = ReviewStore(tmp_path / "study.json")
    store.review({"uid": "card-2"}, 3, 5)
    record = store.review({"uid": "card-2"}, 1, 20)
    assert record["lapses"] == 1
    assert record["interval"] == 0
    assert record["due"] - record["last"] <= 10 * 60 + 1


def test_sessions_aggregate_and_persist(tmp_path):
    path = tmp_path / "study.json"
    store = ReviewStore(path)
    store.save_session(
        {"at": 100.0, "total": 4, "correct": 3, "seconds": 60, "streak": 2}
    )
    store.save_session(
        {"at": 200.0, "total": 2, "correct": 1, "seconds": 30, "streak": 1}
    )
    snapshot = store.snapshot()
    assert snapshot["stats"]["sessions"] == 2
    assert snapshot["stats"]["reviews"] == 6
    assert snapshot["stats"]["correct"] == 4
    assert snapshot["stats"]["retention"] == 0.667
    again = ReviewStore(path).snapshot()
    assert again["stats"]["reviews"] == 6
