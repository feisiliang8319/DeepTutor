"""Test matrix item #14: review_states replay differences are recorded but
never asserted equal (P0-DESIGN.md §2.8 excludes this table from the
rebuild-exactness contract that applies to mastery_snapshots).
"""

from __future__ import annotations

from deeptutor.education.application.record_attempt import (
    NewAttemptInput,
    record_attempt,
    replay_review_state,
)
from deeptutor.education.storage.repositories import (
    AssessmentItemRepository,
    KnowledgeGraphRepository,
)
from deeptutor.education.tests.fixtures import build_fixture_a_math


def test_replay_runs_and_returns_a_comparison_without_requiring_equality(conn, learner, course_version):
    bundle = build_fixture_a_math(course_version.id)
    KnowledgeGraphRepository(conn).import_nodes_and_edges(
        course_version_id=course_version.id, nodes=bundle.nodes[:1], edges=[]
    )
    node = bundle.nodes[0]
    rows = [row for row in bundle.item_rows if row["knowledge_node_id"] == node.id]
    [item] = AssessmentItemRepository(conn).import_items(rows[:1])

    for i, response in enumerate(["42", "wrong", "42"]):
        record_attempt(
            conn,
            NewAttemptInput(
                learner_id=learner.id,
                assessment_item_id=item.id,
                response=response,
                started_at=f"2026-01-01T00:0{i}:00+00:00",
                submitted_at=f"2026-01-01T00:0{i}:05+00:00",
                source="practice",
            ),
        )

    report = replay_review_state(conn, learner.id, node.id)

    # The function must produce both sides of the comparison and a boolean
    # verdict — the test intentionally does NOT assert `report.matches`,
    # because a mismatch would not be a bug (§2.8).
    assert report.online is not None
    assert report.replayed is not None
    assert isinstance(report.matches, bool)
    assert report.online.reps == report.replayed.reps
    assert report.online.lapses == report.replayed.lapses
    assert "not asserted" in report.note or "explicitly excluded" in report.note


def test_replay_with_no_attempts_reports_no_online_or_replayed_state(conn, learner, course_version):
    bundle = build_fixture_a_math(course_version.id)
    KnowledgeGraphRepository(conn).import_nodes_and_edges(
        course_version_id=course_version.id, nodes=bundle.nodes[:1], edges=[]
    )
    node = bundle.nodes[0]
    report = replay_review_state(conn, learner.id, node.id)
    assert report.online is None
    assert report.replayed is None
    assert report.matches is False
