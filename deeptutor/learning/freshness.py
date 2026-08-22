"""Is this learning progress a live record, or a stale copy of one?

Most ``LearningProgress`` documents are written by the tutor itself as the
learner works, so "when was this last touched" is the same question as "when
did the learner last do something" — nothing to warn about.

Projected ones are different. ``deeptutor.education`` owns its own database and
a launchd job copies a snapshot into the learning store every 10 minutes. If
that job stops, the snapshot simply stops changing: no error surfaces, and the
tutor keeps teaching from whatever mastery levels were true the last time the
copy ran. This module is the judgment that makes that visible — deliberately a
pure function so both consumers (the REST summary and the tutor's
``mastery_status`` tool) reach the same verdict instead of each inventing one.

The ``edu-`` prefix is what marks a document as projected; it is set by
``deeptutor.education.application.learning_progress_adapter`` when it names the
book, and nothing else writes that prefix.
"""

from __future__ import annotations

from dataclasses import dataclass
import time

# The projection job runs every 600s. Three missed cycles is the point where
# "the sync is a bit behind" stops being a plausible explanation. Warning at
# one missed cycle would fire constantly on normal scheduling jitter.
STALE_AFTER_SECONDS = 30 * 60

PROJECTED_BOOK_PREFIX = "edu-"


@dataclass(frozen=True, slots=True)
class Staleness:
    """A projected snapshot that has stopped being refreshed."""

    age_seconds: float
    threshold_seconds: int

    @property
    def age_minutes(self) -> int:
        return int(self.age_seconds // 60)

    def message(self) -> str:
        return (
            f"Mastery data for this course is a snapshot copied from the practice "
            f"system, and it was last refreshed {self.age_minutes} minutes ago "
            f"(expected every 10). Treat the levels below as possibly out of date: "
            f"say so if the learner's recent practice seems missing, and do not "
            f"claim they have not practised something."
        )


def is_projected(book_id: str) -> bool:
    """True for books copied in from the education service."""
    return book_id.startswith(PROJECTED_BOOK_PREFIX)


def projection_staleness(
    book_id: str,
    updated_at: float | None,
    *,
    now: float | None = None,
    threshold_seconds: int = STALE_AFTER_SECONDS,
) -> Staleness | None:
    """``Staleness`` when a projected snapshot has gone cold, else ``None``.

    Returns ``None`` for books the tutor writes itself: their timestamp means
    "when the learner last worked", and going quiet is normal there.

    A missing or non-numeric ``updated_at`` also returns ``None`` rather than
    guessing — an absent timestamp is not evidence of staleness, and reporting
    "0 minutes ago" would be worse than reporting nothing.
    """
    if not is_projected(book_id):
        return None
    if not isinstance(updated_at, (int, float)) or isinstance(updated_at, bool):
        return None
    age = (time.time() if now is None else now) - float(updated_at)
    if age <= threshold_seconds:
        return None
    return Staleness(age_seconds=age, threshold_seconds=threshold_seconds)
