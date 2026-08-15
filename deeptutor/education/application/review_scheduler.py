"""Spaced-repetition scheduling, backed by py-fsrs (FSRS-6).

Replaces the ``p0-internal-v1`` placeholder that multiplied stability by a
hand-picked factor. The placeholder was never a memory model — it had no
notion of how long ago the last review was, so a card answered correctly
after five minutes and one answered correctly after five weeks moved
identically.

Two deliberate configuration choices, both about replayability:

* ``enable_fuzzing=False`` — FSRS by default jitters each interval by a few
  percent so that cards introduced together do not forever come due
  together. That jitter is random, and this package's whole posture is that
  derived state must be reconstructible from ``student_attempts`` alone
  (P0-DESIGN.md §2.8). Determinism wins; a single learner does not have
  enough cards for clumping to matter.
* Scheduling is driven by the **attempt's** ``submitted_at``, never by
  ``time.time()`` at write time. Replaying the same attempts therefore
  reproduces the same schedule instead of drifting with the wall clock.

Rating mapping is intentionally binary: an auto-graded answer carries no
signal that separates "Hard" from "Good" from "Easy". Inventing that
gradation from response time or hint count would be a pedagogical claim the
data does not support, so correct → ``Good`` and incorrect → ``Again``.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from fsrs import Card, Rating, Scheduler, State

if TYPE_CHECKING:
    from deeptutor.education.domain.learner import ReviewState as ReviewStateLike

# Bump when the parameter set or the mapping below changes: rows carry this
# string so a future reader can tell which model produced their schedule.
FSRS_PARAMS_VER = "fsrs-6.3.2-default-nofuzz"

_SCHEDULER = Scheduler(enable_fuzzing=False)


@dataclass(frozen=True, slots=True)
class ReviewMath:
    """Everything ``review_states`` needs, as a pure value.

    ``state``/``step`` are FSRS's own card phase (learning → review →
    relearning) and position within the learning steps. They are persisted
    because they are *not* derivable from stability/difficulty alone —
    dropping them would silently restart every resumed card in the learning
    phase.
    """

    stability: float
    difficulty: float
    reps: int
    lapses: int
    state: int
    step: int | None
    due_at: str
    last_review_at: str | None


def _parse(iso: str) -> datetime:
    dt = datetime.fromisoformat(iso)
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _to_card(math: ReviewMath | None) -> Card:
    if math is None:
        return Card()
    return Card(
        state=State(math.state),
        step=math.step,
        stability=math.stability,
        difficulty=math.difficulty,
        due=_parse(math.due_at),
        last_review=_parse(math.last_review_at) if math.last_review_at else None,
    )


def math_from_state(state: "ReviewStateLike | None") -> ReviewMath | None:
    """Lift a stored ``review_states`` row back into scheduler input.

    Lives here rather than in ``record_attempt`` so that resuming a card is
    part of the scheduler's own contract — the ``state``/``step`` round-trip
    is exactly the part that silently breaks if a caller reconstructs this
    by hand.
    """
    if state is None:
        return None
    return ReviewMath(
        stability=state.stability,
        difficulty=state.difficulty,
        reps=state.reps,
        lapses=state.lapses,
        state=state.fsrs_state,
        step=state.fsrs_step,
        due_at=state.due_at,
        last_review_at=state.last_review_at,
    )


def step_review(math: ReviewMath | None, *, is_correct: bool, reviewed_at: str) -> ReviewMath:
    """Advance one review. ``reviewed_at`` is the attempt's ``submitted_at``."""
    review_dt = _parse(reviewed_at)
    card, _log = _SCHEDULER.review_card(
        _to_card(math), Rating.Good if is_correct else Rating.Again, review_datetime=review_dt
    )
    previous_reps = math.reps if math else 0
    previous_lapses = math.lapses if math else 0
    return ReviewMath(
        stability=float(card.stability),
        difficulty=float(card.difficulty),
        # reps counts successful reviews and lapses counts failures — FSRS-6
        # tracks neither on the card, and they are what a parent actually
        # reads ("got it 4 times, forgot it twice").
        reps=previous_reps + (1 if is_correct else 0),
        lapses=previous_lapses + (0 if is_correct else 1),
        state=int(card.state.value),
        step=card.step,
        due_at=card.due.isoformat(),
        last_review_at=card.last_review.isoformat() if card.last_review else None,
    )


__all__ = ["FSRS_PARAMS_VER", "ReviewMath", "math_from_state", "step_review"]
