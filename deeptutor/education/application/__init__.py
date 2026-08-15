"""P0's three use cases.

    record_attempt     — the one-answer transaction (P0-DESIGN.md §3)
    rebuild_mastery     — compute/recompute mastery_snapshots from
                           student_attempts + judgment_records
    select_objective    — deterministic prerequisite planner

``to_iso_timestamp`` is the one thing both ``record_attempt`` and
``rebuild_mastery`` need and neither owns — a shared, tiny, pure helper
lives here rather than in either of them or in a new top-level module (P0's
directory layout is fixed to domain/storage/application/tests; this stays
inside the already-planned ``application`` package instead of adding one).
"""

from __future__ import annotations

import datetime as _dt


def to_iso_timestamp(unix_seconds: float) -> str:
    """UTC ISO-8601 string for a ``time.time()``-style unix timestamp. All
    timestamp columns in this package's schema are TEXT, and every writer
    in ``application`` goes through this one function so they sort and
    compare consistently."""
    return _dt.datetime.fromtimestamp(unix_seconds, tz=_dt.timezone.utc).isoformat()


__all__ = ["to_iso_timestamp"]
