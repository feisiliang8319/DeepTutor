"""Education Data Layer (P0) — an independent, append-only-evidence store for
learner mastery that lives entirely under ``deeptutor/education/``.

This is deliberately **not** wired into ``deeptutor/learning`` (the existing
Mastery Path engine) yet. P0 builds the data layer and proves it end-to-end
in isolation; the adapter that lets the chat-loop tutor read/write through it
is a separate, later phase (see ``docs/P0-DESIGN.md`` §9 and this package's
test suite for what is/is not covered).

Sub-packages:
    domain        — pure dataclasses, no IO (course.py / evidence.py / learner.py)
    storage       — SQLite connection management, migrations, repositories
    application   — the three P0 use cases: record_attempt / rebuild_mastery /
                     select_objective
    tests         — pytest suite, including the destructive-injection matrix
                     required by P0-DESIGN.md §6
"""

from __future__ import annotations

__all__: list[str] = []
