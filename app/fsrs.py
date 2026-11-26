"""FSRS-6 scheduling math for the study plan.

This is a compact, day-granularity implementation of the Free Spaced
Repetition Scheduler used by Anki, adapted from the MIT-licensed
`py-fsrs <https://github.com/open-spaced-repetition/py-fsrs>`_ reference
implementation (default parameters and formulas). It is not a replacement for
Anki's scheduler: the planner only needs the interval a card would get, not
sub-day learning steps, fuzzing or a review log.

The plan is honest about what it simulates: every new card is reviewed once on
the day it is introduced and then on each FSRS due date, using one expected
rating. A review that falls on a day off is taken on the next study day.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, timedelta
from enum import IntEnum

# FSRS-6 defaults, exactly as shipped by py-fsrs 6.x.
DEFAULT_PARAMETERS = (
    0.212,
    1.2931,
    2.3065,
    8.2956,
    6.4133,
    0.8334,
    3.0194,
    0.001,
    1.8722,
    0.1666,
    0.796,
    1.4835,
    0.0614,
    0.2629,
    1.6483,
    0.6014,
    1.8729,
    0.5425,
    0.0912,
    0.0658,
    0.1542,
)

MIN_STABILITY = 0.001
MIN_DIFFICULTY = 1.0
MAX_DIFFICULTY = 10.0
DEFAULT_MAX_INTERVAL = 36_500


class Rating(IntEnum):
    AGAIN = 1
    HARD = 2
    GOOD = 3
    EASY = 4


@dataclass
class FSRSCard:
    """One card's FSRS memory state at day granularity."""

    stability: float
    difficulty: float
    due: date
    last_review: date
    reps: int = 1


class FSRS:
    def __init__(
        self,
        parameters: tuple[float, ...] = DEFAULT_PARAMETERS,
        desired_retention: float = 0.9,
        maximum_interval: int = DEFAULT_MAX_INTERVAL,
    ) -> None:
        if len(parameters) != len(DEFAULT_PARAMETERS):
            raise ValueError("FSRS needs exactly 21 parameters.")
        if not 0.70 <= desired_retention <= 0.99:
            raise ValueError("Desired retention must be between 0.70 and 0.99.")
        if maximum_interval < 1:
            raise ValueError("Maximum interval must be at least one day.")
        self.parameters = tuple(float(value) for value in parameters)
        self.desired_retention = float(desired_retention)
        self.maximum_interval = int(maximum_interval)
        self._decay = -self.parameters[20]
        self._factor = 0.9 ** (1 / self._decay) - 1

    # -- public API -----------------------------------------------------

    def first_interval(self, rating: Rating = Rating.GOOD) -> int:
        """Days until the first review of a new card at this rating."""
        return self._next_interval(self._initial_stability(rating))

    def review(self, card: FSRSCard | None, rating: Rating, day: date) -> FSRSCard:
        """Return the card state after a review on ``day``."""
        if card is None:
            stability = self._initial_stability(rating)
            difficulty = self._initial_difficulty(rating)
            reps = 1
        else:
            retrievability = self.retrievability(card, day)
            stability = self._next_stability(
                difficulty=card.difficulty,
                stability=card.stability,
                retrievability=retrievability,
                rating=rating,
            )
            difficulty = self._next_difficulty(card.difficulty, rating)
            reps = card.reps + 1
        interval = self._next_interval(stability)
        return FSRSCard(
            stability=round(stability, 6),
            difficulty=round(difficulty, 6),
            due=day + timedelta(days=interval),
            last_review=day,
            reps=reps,
        )

    def retrievability(self, card: FSRSCard, day: date) -> float:
        """Probability the card is recalled on ``day`` (FSRS power curve)."""
        elapsed = max(0, (day - card.last_review).days)
        return (1 + self._factor * elapsed / card.stability) ** self._decay

    def interval_for_stability(self, stability: float) -> int:
        return self._next_interval(stability)

    # -- formulas -------------------------------------------------------

    def _initial_stability(self, rating: Rating) -> float:
        return max(MIN_STABILITY, self.parameters[rating - 1])

    def _initial_difficulty(self, rating: Rating, *, clamp: bool = True) -> float:
        value = (
            self.parameters[4]
            - math.exp(self.parameters[5] * (rating - 1))
            + 1
        )
        return _clamp(value, MIN_DIFFICULTY, MAX_DIFFICULTY) if clamp else value

    def _next_interval(self, stability: float) -> int:
        interval = (stability / self._factor) * (
            (self.desired_retention ** (1 / self._decay)) - 1
        )
        interval = round(interval)
        return max(1, min(interval, self.maximum_interval))

    def _next_difficulty(self, difficulty: float, rating: Rating) -> float:
        delta = -(self.parameters[6] * (rating - 3))
        damped = (10.0 - difficulty) * delta / 9.0
        mean_reverted = (
            self.parameters[7] * self._initial_difficulty(Rating.EASY, clamp=False)
            + (1 - self.parameters[7]) * (difficulty + damped)
        )
        return _clamp(mean_reverted, MIN_DIFFICULTY, MAX_DIFFICULTY)

    def _next_stability(
        self,
        *,
        difficulty: float,
        stability: float,
        retrievability: float,
        rating: Rating,
    ) -> float:
        if rating == Rating.AGAIN:
            value = min(
                self.parameters[11]
                * (difficulty ** -self.parameters[12])
                * ((stability + 1) ** self.parameters[13] - 1)
                * math.exp((1 - retrievability) * self.parameters[14]),
                stability / math.exp(self.parameters[17] * self.parameters[18]),
            )
        else:
            hard_penalty = self.parameters[15] if rating == Rating.HARD else 1.0
            easy_bonus = self.parameters[16] if rating == Rating.EASY else 1.0
            value = stability * (
                1
                + math.exp(self.parameters[8])
                * (11 - difficulty)
                * (stability ** -self.parameters[9])
                * (math.exp((1 - retrievability) * self.parameters[10]) - 1)
                * hard_penalty
                * easy_bonus
            )
        return max(MIN_STABILITY, value)


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


__all__ = ["DEFAULT_PARAMETERS", "FSRS", "FSRSCard", "Rating"]
