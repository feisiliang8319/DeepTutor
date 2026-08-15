"""The py-fsrs swap (2026-08-14): what the placeholder could not do.

The old ``p0-internal-v1`` math multiplied stability by a constant factor
and never looked at the clock, so "answered correctly five minutes later"
and "answered correctly five weeks later" produced identical schedules —
which is the one thing a spaced-repetition algorithm exists to distinguish.
These tests pin the behaviours that only a real memory model has, plus the
two configuration choices (no fuzzing, attempt-time driven) that keep the
schedule reproducible.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from deeptutor.education.application.record_attempt import (
    NewAttemptInput,
    record_attempt,
    replay_review_state,
)
from deeptutor.education.application.review_scheduler import (
    FSRS_PARAMS_VER,
    math_from_state,
    step_review,
)
from deeptutor.education.storage.repositories import (
    AssessmentItemRepository,
    KnowledgeGraphRepository,
    ReviewStateRepository,
)
from deeptutor.education.tests.fixtures import build_fixture_a_math, content_hash

BASE = datetime(2026, 8, 14, 9, 0, tzinfo=timezone.utc)


def iso(offset_days: float = 0.0) -> str:
    return (BASE + timedelta(days=offset_days)).isoformat()


@pytest.fixture
def item_id(conn, course_version) -> str:
    bundle = build_fixture_a_math(course_version.id)
    KnowledgeGraphRepository(conn).import_nodes_and_edges(
        course_version_id=course_version.id, nodes=bundle.nodes[:1], edges=[]
    )
    AssessmentItemRepository(conn).import_items(
        [{
            "id": "item-fsrs", "course_version_id": course_version.id,
            "knowledge_node_id": bundle.nodes[0].id, "item_type": "numeric",
            "prompt": "6 x 7 = ?", "expected_answer": "42", "rubric_json": None,
            "difficulty": 2, "content_scope": "BUNDLED",
            "source_ref": "self-authored (test)", "license_note": None,
            "attribution_text": None, "derived_from_item_id": None, "reviewer": None,
            "reviewed_at": None, "content_hash": content_hash("item-fsrs"),
            "status": "production",
        }]
    )
    return "item-fsrs"


def answer(conn, learner, item_id: str, response: str, at: str, key: str):
    return record_attempt(
        conn,
        NewAttemptInput(
            learner_id=learner.id, assessment_item_id=item_id, response=response,
            started_at=at, submitted_at=at, source="test", client_attempt_id=key,
        ),
    )


# ---- what the placeholder structurally could not do -----------------------


def test_elapsed_time_changes_the_resulting_stability():
    """The core of the swap: same rating, different gap, different memory
    state. Under the old math these two were bit-identical."""
    first = step_review(None, is_correct=True, reviewed_at=iso(0))
    soon = step_review(first, is_correct=True, reviewed_at=iso(0.01))  # ~15 min later
    later = step_review(first, is_correct=True, reviewed_at=iso(30))  # a month later
    assert soon.stability != later.stability
    # Recalling something after a month is stronger evidence of durable
    # memory than recalling it 15 minutes after seeing it.
    assert later.stability > soon.stability


def test_a_lapse_shortens_the_next_interval():
    good = step_review(None, is_correct=True, reviewed_at=iso(0))
    good2 = step_review(good, is_correct=True, reviewed_at=iso(5))
    lapsed = step_review(good2, is_correct=False, reviewed_at=iso(10))
    gap_after_success = datetime.fromisoformat(good2.due_at) - datetime.fromisoformat(iso(5))
    gap_after_lapse = datetime.fromisoformat(lapsed.due_at) - datetime.fromisoformat(iso(10))
    assert gap_after_lapse < gap_after_success
    assert lapsed.lapses == 1 and lapsed.reps == 2


# FSRS only fuzzes intervals above a few days, so a determinism check has
# to drive the card out of the learning steps and into a long Review-phase
# interval first — otherwise it passes with fuzzing switched *on* and proves
# nothing. Measured: this schedule reaches a ~4-month interval, where three
# fuzzed runs land on three different dates.
_LONG_SCHEDULE = [0, 0.01, 1, 4, 12, 30]


def _run_schedule(days: list[float]):
    math = None
    for day in days:
        math = step_review(math, is_correct=True, reviewed_at=iso(day))
    return math


def test_scheduling_is_deterministic_fuzzing_off():
    """Two identical replays must land on the same second — the rebuild
    contract depends on it, and FSRS fuzzes intervals by default."""
    a = _run_schedule(_LONG_SCHEDULE)
    b = _run_schedule(_LONG_SCHEDULE)
    assert (a.stability, a.difficulty, a.due_at) == (b.stability, b.difficulty, b.due_at)
    # Guard the guard: if this interval ever shrinks back under the fuzz
    # threshold the assertion above becomes vacuous, so pin that it really
    # is a long Review-phase interval.
    from datetime import datetime as _dt

    interval_days = (_dt.fromisoformat(a.due_at) - _dt.fromisoformat(iso(30))).days
    assert a.state == 2, "card must be in the Review phase, not still in learning steps"
    assert interval_days > 30, f"interval {interval_days}d is below FSRS's fuzz range"


def test_params_version_names_the_real_algorithm(conn, learner, course_version, item_id):
    answer(conn, learner, item_id, "42", iso(0), "k1")
    state = ReviewStateRepository(conn).get(learner.id, "node-G3.MULT.BASIC")
    assert state.fsrs_params_ver == FSRS_PARAMS_VER
    assert state.fsrs_params_ver.startswith("fsrs-"), "must not still claim the placeholder"


# ---- persistence of the FSRS card phase ----------------------------------


def test_card_phase_survives_a_reload(conn, learner, course_version, item_id):
    """``state``/``step`` are not derivable from stability+difficulty; if
    they are not persisted, every resumed card silently restarts in the
    learning phase and the schedule collapses to minutes."""
    answer(conn, learner, item_id, "42", iso(0), "k1")
    answer(conn, learner, item_id, "42", iso(1), "k2")
    stored = ReviewStateRepository(conn).get(learner.id, "node-G3.MULT.BASIC")
    assert stored.fsrs_state in (1, 2, 3)
    # Continuing from the *stored* card must not reset progress.
    continued = step_review(math_from_state(stored), is_correct=True, reviewed_at=iso(30))
    assert continued.reps == stored.reps + 1
    assert continued.stability > stored.stability


# ---- replay now reproduces, not just resembles ---------------------------


def test_replay_reproduces_the_online_schedule(conn, learner, course_version, item_id):
    answer(conn, learner, item_id, "42", iso(0), "k1")
    answer(conn, learner, item_id, "wrong", iso(2), "k2")
    answer(conn, learner, item_id, "42", iso(9), "k3")

    report = replay_review_state(conn, learner.id, "node-G3.MULT.BASIC")
    assert report.online is not None and report.replayed is not None
    assert report.matches, (
        "with fuzzing off and both paths keyed off submitted_at, replay must "
        f"land exactly on the stored schedule: {report.online} vs {report.replayed}"
    )
    assert report.online.due_at == report.replayed.due_at


def test_unresolved_attempt_does_not_move_the_schedule(conn, learner, course_version):
    """An attempt nobody has graded yet is not evidence of recall."""
    bundle = build_fixture_a_math(course_version.id)
    KnowledgeGraphRepository(conn).import_nodes_and_edges(
        course_version_id=course_version.id, nodes=bundle.nodes[:1], edges=[]
    )
    AssessmentItemRepository(conn).import_items(
        [{
            "id": "item-open", "course_version_id": course_version.id,
            "knowledge_node_id": bundle.nodes[0].id, "item_type": "multi_step",
            "prompt": "Explain your reasoning.", "expected_answer": None,
            "rubric_json": None, "difficulty": 3, "content_scope": "BUNDLED",
            "source_ref": "self-authored (test)", "license_note": None,
            "attribution_text": None, "derived_from_item_id": None, "reviewer": None,
            "reviewed_at": None, "content_hash": content_hash("item-open"),
            "status": "production",
        }]
    )
    answer(conn, learner, "item-open", "because...", iso(0), "k-open")
    assert ReviewStateRepository(conn).get(learner.id, bundle.nodes[0].id) is None
