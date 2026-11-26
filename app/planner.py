"""Turn an exam date, an amount to learn and daily time into a study schedule.

The schedule is a forward simulation of FSRS-6: each day the cards that are due
are reviewed, then the day's share of new cards is introduced. The plan does not
pretend to know your future ratings — it uses one expected rating for every
review (Good by default) and no intraday learning steps, because a day-level
plan only needs the interval FSRS would assign.
"""

from __future__ import annotations

import heapq
import math
from dataclasses import dataclass, replace
from datetime import date, timedelta

from .fsrs import FSRS, FSRSCard, Rating

MAX_CARDS = 10_000
MAX_DAYS = 730


@dataclass(frozen=True)
class PlanInput:
    start: date
    deadline: date
    cards: int
    minutes_per_day: int
    weekdays: tuple[int, ...] = (0, 1, 2, 3, 4, 5, 6)
    buffer_days: int = 2
    retention: float = 0.9
    rating: int = 3
    new_seconds: int = 60
    review_seconds: int = 15

    def validated(self) -> "PlanInput":
        if self.deadline <= self.start:
            raise ValueError("The exam date must be after the first study day.")
        if (self.deadline - self.start).days > MAX_DAYS:
            raise ValueError(f"Keep the plan within {MAX_DAYS} days.")
        if not 1 <= self.cards <= MAX_CARDS:
            raise ValueError(f"Cards must be between 1 and {MAX_CARDS}.")
        if not 5 <= self.minutes_per_day <= 1_440:
            raise ValueError("Daily minutes must be between 5 and 1440.")
        weekdays = tuple(sorted({int(day) for day in self.weekdays}))
        if not weekdays or any(day < 0 or day > 6 for day in weekdays):
            raise ValueError("Choose at least one study day.")
        if not 0 <= self.buffer_days <= 60:
            raise ValueError("The review buffer must be between 0 and 60 days.")
        if not 0.70 <= self.retention <= 0.99:
            raise ValueError("Desired retention must be between 70% and 99%.")
        if self.rating not in (2, 3, 4):
            raise ValueError("Expected recall must be Hard, Good or Easy.")
        if not 5 <= self.new_seconds <= 600:
            raise ValueError("Seconds per new card must be between 5 and 600.")
        if not 3 <= self.review_seconds <= 600:
            raise ValueError("Seconds per review must be between 3 and 600.")
        return replace(self, weekdays=weekdays)


def study_days(plan: PlanInput) -> list[date]:
    """Study days from start through the day before the exam."""
    last_day = plan.deadline - timedelta(days=1)
    if last_day < plan.start:
        return []
    days: list[date] = []
    day = plan.start
    while day <= last_day:
        if day.weekday() in plan.weekdays:
            days.append(day)
        day += timedelta(days=1)
    return days


@dataclass
class _Simulation:
    rows: list[dict]
    cards: int
    learned: int
    reviews: int
    total_minutes: float
    peak_minutes: float
    new_per_day_max: int
    reviewed_before_exam: int
    first_review: date | None
    last_new: date | None


def _simulate(plan: PlanInput) -> _Simulation:
    fsrs = FSRS(desired_retention=plan.retention)
    rating = Rating(plan.rating)
    days = study_days(plan)
    if not days:
        return _Simulation([], plan.cards, 0, 0, 0.0, 0.0, 0, 0, None, None)

    new_days = [
        day for day in days if (plan.deadline - day).days > plan.buffer_days
    ]
    new_days_set = set(new_days)
    base, extra = divmod(plan.cards, len(new_days)) if new_days else (0, 0)
    remaining_extra = extra

    due_heap: list[tuple[date, int, FSRSCard]] = []
    next_card_id = 0
    reviewed_ids: set[int] = set()
    learned = 0
    reviews = 0
    total_minutes = 0.0
    peak_minutes = 0.0
    new_per_day_max = 0
    first_review: date | None = None
    last_new: date | None = None
    rows: list[dict] = []

    for day in days:
        due = 0
        while due_heap and due_heap[0][0] <= day:
            _due, card_id, state = heapq.heappop(due_heap)
            state = fsrs.review(state, rating, day)
            due += 1
            reviewed_ids.add(card_id)
            heapq.heappush(due_heap, (state.due, card_id, state))
        reviews += due
        if due and first_review is None:
            first_review = day

        new_count = 0
        if day in new_days_set and learned < plan.cards:
            quota = base + (1 if remaining_extra > 0 else 0)
            if remaining_extra > 0:
                remaining_extra -= 1
            quota = min(quota, plan.cards - learned)
            for _ in range(quota):
                state = fsrs.review(None, rating, day)
                card_id = next_card_id
                next_card_id += 1
                heapq.heappush(due_heap, (state.due, card_id, state))
            new_count = quota
            learned += new_count
            if new_count:
                last_new = day
        new_per_day_max = max(new_per_day_max, new_count)

        minutes = (new_count * plan.new_seconds + due * plan.review_seconds) / 60
        total_minutes += minutes
        peak_minutes = max(peak_minutes, minutes)
        rows.append(
            {
                "date": day.isoformat(),
                "new": new_count,
                "reviews": due,
                "minutes": round(minutes, 1),
                "learned": learned,
                "over": minutes > plan.minutes_per_day + 1e-9,
                "examDay": False,
            }
        )

    reviewed_before_exam = len(reviewed_ids)
    return _Simulation(
        rows=rows,
        cards=plan.cards,
        learned=learned,
        reviews=reviews,
        total_minutes=total_minutes,
        peak_minutes=peak_minutes,
        new_per_day_max=new_per_day_max,
        reviewed_before_exam=reviewed_before_exam,
        first_review=first_review,
        last_new=last_new,
    )


def _max_cards_that_fit(plan: PlanInput) -> int:
    low, high = 0, plan.cards
    while low < high:
        middle = (low + high + 1) // 2
        simulation = _simulate(replace(plan, cards=middle))
        if (
            simulation.learned == middle
            and simulation.peak_minutes <= plan.minutes_per_day + 1e-9
        ):
            low = middle
        else:
            high = middle - 1
    return low


def build_plan(plan: PlanInput) -> dict:
    """Return a day-by-day plan plus the numbers that explain it."""
    plan = plan.validated()
    fsrs = FSRS(desired_retention=plan.retention)
    rating = Rating(plan.rating)
    days = study_days(plan)
    if not days:
        raise ValueError(
            "There is no study day left: the exam must be at least one day after today."
        )

    simulation = _simulate(plan)
    first_interval = fsrs.first_interval(rating)
    feasible = (
        simulation.learned == plan.cards
        and simulation.peak_minutes <= plan.minutes_per_day + 1e-9
    )
    reason = "ok"
    minimum_minutes = math.ceil(simulation.peak_minutes)
    suggested_cards = plan.cards
    if simulation.learned < plan.cards:
        reason = "buffer"
        suggested_cards = 0
    elif not feasible:
        reason = "time"
        suggested_cards = _max_cards_that_fit(plan)

    warnings: list[str] = []
    if reason == "buffer":
        warnings.append(
            "Your review buffer leaves no day for new cards. "
            "Shorten the buffer or move the exam date."
        )
    if reason == "time":
        warnings.append(
            f"Your heaviest day needs about {minimum_minutes} minutes; "
            f"with {plan.minutes_per_day} minutes you can learn about "
            f"{suggested_cards} cards by this date."
        )
    if simulation.reviewed_before_exam < simulation.learned:
        missing = simulation.learned - simulation.reviewed_before_exam
        warnings.append(
            f"{missing} card{'' if missing == 1 else 's'} will not get a second "
            "review before the exam. Learn them earlier or keep a longer buffer."
        )
    if plan.buffer_days < first_interval:
        warnings.append(
            f"With {rating.name.lower()} recall the first review is "
            f"{first_interval} days after learning; your {plan.buffer_days}-day "
            "buffer may not leave room for it."
        )

    return {
        "feasible": feasible,
        "reason": reason,
        "summary": {
            "start": plan.start.isoformat(),
            "deadline": plan.deadline.isoformat(),
            "studyDays": len(days),
            "newCardDays": sum(
                1 for day in days if (plan.deadline - day).days > plan.buffer_days
            ),
            "cards": plan.cards,
            "learned": simulation.learned,
            "reviews": simulation.reviews,
            "newPerDayMax": simulation.new_per_day_max,
            "totalMinutes": round(simulation.total_minutes),
            "peakMinutes": round(simulation.peak_minutes, 1),
            "averageMinutes": round(
                simulation.total_minutes / max(1, len(days)), 1
            ),
            "minimumMinutes": minimum_minutes,
            "suggestedCards": suggested_cards,
            "retention": plan.retention,
            "rating": plan.rating,
            "firstInterval": first_interval,
            "firstReview": (
                simulation.first_review.isoformat() if simulation.first_review else None
            ),
            "lastNew": simulation.last_new.isoformat() if simulation.last_new else None,
            "reviewedBeforeExam": simulation.reviewed_before_exam,
            "bufferDays": plan.buffer_days,
            "minutesPerDay": plan.minutes_per_day,
        },
        "days": simulation.rows,
        "warnings": warnings,
    }


__all__ = ["MAX_CARDS", "PlanInput", "build_plan", "study_days"]
