"""Tests for the day-by-day FSRS study plan."""

from __future__ import annotations

from dataclasses import replace
from datetime import date

import pytest

from app.planner import PlanInput, build_plan, study_days


def plan(**overrides) -> dict:
    base = PlanInput(
        start=date(2026, 11, 23),  # Monday
        deadline=date(2026, 12, 7),  # Monday, two weeks later
        cards=200,
        minutes_per_day=60,
        buffer_days=2,
    )
    return build_plan(replace(base, **overrides))


def test_feasible_plan_learns_every_card():
    result = plan()
    assert result["feasible"] is True
    assert result["reason"] == "ok"
    assert result["summary"]["learned"] == 200
    assert sum(day["new"] for day in result["days"]) == 200
    assert all(day["minutes"] <= 60 for day in result["days"])


def test_plan_stops_before_the_exam_day():
    result = plan()
    assert result["days"]
    assert all(day["date"] < "2026-12-07" for day in result["days"])
    assert result["days"][-1]["date"] == "2026-12-06"


def test_study_days_respect_the_weekday_selection():
    result = plan(weekdays=(0, 1, 2, 3, 4))  # weekdays only
    assert result["days"]
    for row in result["days"]:
        assert date.fromisoformat(row["date"]).weekday() < 5


def test_no_study_days_before_the_exam_is_an_error():
    with pytest.raises(ValueError, match="no study day"):
        plan(
            start=date(2026, 12, 5),  # Saturday
            deadline=date(2026, 12, 6),  # Sunday
            weekdays=(0, 1, 2, 3, 4),
        )


def test_time_shortage_is_reported_with_a_suggested_card_count():
    result = plan(cards=500, minutes_per_day=30, deadline=date(2026, 11, 30))
    assert result["feasible"] is False
    assert result["reason"] == "time"
    summary = result["summary"]
    assert summary["minimumMinutes"] > 30
    assert 0 < summary["suggestedCards"] < 500
    assert summary["peakMinutes"] > 30
    assert any("heaviest day" in warning for warning in result["warnings"])


def test_the_suggested_card_count_actually_fits():
    too_much = plan(cards=500, minutes_per_day=30, deadline=date(2026, 11, 30))
    suggested = too_much["summary"]["suggestedCards"]
    fits = plan(cards=suggested, minutes_per_day=30, deadline=date(2026, 11, 30))
    assert fits["feasible"] is True


def test_a_long_review_buffer_can_leave_no_day_for_new_cards():
    result = plan(cards=100, deadline=date(2026, 11, 27), buffer_days=4)
    assert result["feasible"] is False
    assert result["reason"] == "buffer"
    assert result["summary"]["learned"] == 0
    assert any("no day for new cards" in warning for warning in result["warnings"])


def test_reviews_are_scheduled_before_the_exam():
    result = plan(cards=20, deadline=date(2026, 12, 7))
    assert result["summary"]["reviews"] > 0
    assert result["summary"]["firstReview"] is not None
    assert result["summary"]["firstReview"] < "2026-12-07"
    assert result["summary"]["reviewedBeforeExam"] > 0


def test_short_buffer_warns_about_the_first_review():
    result = plan(cards=100, buffer_days=0)
    assert any("buffer" in warning.lower() for warning in result["warnings"])


def test_higher_retention_needs_more_time():
    low = plan(cards=200, retention=0.8)
    high = plan(cards=200, retention=0.95)
    assert high["summary"]["totalMinutes"] >= low["summary"]["totalMinutes"]


def test_plan_is_deterministic():
    assert plan()["days"] == plan()["days"]


def test_validation_rejects_invalid_inputs():
    with pytest.raises(ValueError):
        plan(cards=0)
    with pytest.raises(ValueError):
        plan(deadline=date(2026, 11, 23))
    with pytest.raises(ValueError):
        plan(weekdays=())
    with pytest.raises(ValueError):
        plan(weekdays=(7,))
    with pytest.raises(ValueError):
        plan(minutes_per_day=1)
    with pytest.raises(ValueError):
        plan(retention=0.5)
    with pytest.raises(ValueError):
        plan(rating=1)


def test_study_days_helper_excludes_the_exam():
    days = study_days(
        PlanInput(
            start=date(2026, 11, 23),
            deadline=date(2026, 11, 27),
            cards=1,
            minutes_per_day=60,
        )
    )
    assert days == [
        date(2026, 11, 23),
        date(2026, 11, 24),
        date(2026, 11, 25),
        date(2026, 11, 26),
    ]
