"""FSRS-6 reference checks.

The expected values were produced by py-fsrs 6.x with the same default
parameters and no intraday learning steps, so they pin the math rather than a
hand-written approximation.
"""

from __future__ import annotations

from datetime import date

import pytest

from app.fsrs import DEFAULT_PARAMETERS, FSRS, Rating


def test_default_parameter_count():
    assert len(DEFAULT_PARAMETERS) == 21


def test_new_card_ratings_match_reference():
    scheduler = FSRS()
    start = date(2026, 1, 1)
    expected = {
        Rating.AGAIN: (0.212, 6.4133, date(2026, 1, 2)),
        Rating.HARD: (1.2931, 5.112171, date(2026, 1, 2)),
        Rating.GOOD: (2.3065, 2.118104, date(2026, 1, 3)),
        Rating.EASY: (8.2956, 1.0, date(2026, 1, 9)),
    }
    for rating, (stability, difficulty, due) in expected.items():
        card = scheduler.review(None, rating, start)
        assert card.stability == pytest.approx(stability, abs=1e-6)
        assert card.difficulty == pytest.approx(difficulty, abs=1e-6)
        assert card.due == due
        assert card.reps == 1


def test_second_good_review_matches_reference():
    scheduler = FSRS()
    card = scheduler.review(None, Rating.GOOD, date(2026, 1, 1))
    card = scheduler.review(card, Rating.GOOD, date(2026, 1, 3))
    assert card.stability == pytest.approx(10.964332, abs=1e-6)
    assert card.difficulty == pytest.approx(2.111214, abs=1e-6)
    assert card.due == date(2026, 1, 14)
    assert card.reps == 2


def test_lapse_matches_reference():
    scheduler = FSRS()
    card = scheduler.review(None, Rating.GOOD, date(2026, 1, 1))
    card = scheduler.review(card, Rating.AGAIN, date(2026, 1, 3))
    assert card.stability == pytest.approx(0.60758, abs=1e-5)
    assert card.difficulty == pytest.approx(7.394503, abs=1e-6)
    assert card.due == date(2026, 1, 4)


def test_retrievability_at_due_date_matches_reference():
    scheduler = FSRS()
    card = scheduler.review(None, Rating.GOOD, date(2026, 1, 1))
    assert scheduler.retrievability(card, date(2026, 1, 3)) == pytest.approx(
        0.909493, abs=1e-6
    )


def test_first_intervals_match_reference():
    scheduler = FSRS()
    assert scheduler.first_interval(Rating.AGAIN) == 1
    assert scheduler.first_interval(Rating.HARD) == 1
    assert scheduler.first_interval(Rating.GOOD) == 2
    assert scheduler.first_interval(Rating.EASY) == 8


def test_higher_retention_shortens_intervals():
    low = FSRS(desired_retention=0.8)
    high = FSRS(desired_retention=0.95)
    assert high.first_interval(Rating.GOOD) < low.first_interval(Rating.GOOD)


def test_invalid_parameters_and_retention_are_rejected():
    with pytest.raises(ValueError):
        FSRS(parameters=(1.0,))
    with pytest.raises(ValueError):
        FSRS(desired_retention=0.5)
    with pytest.raises(ValueError):
        FSRS(maximum_interval=0)
