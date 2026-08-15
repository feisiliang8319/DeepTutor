"""Test matrix items #13, #13b, #13d (P0-DESIGN.md §6):

#13  mastery_snapshots can be deleted entirely and rebuilt from
     student_attempts + judgment_records, matching under the corrected
     invariant ("same evidence set -> same result", not "same as some past
     online value" — see rebuild_mastery.py's module docstring).
#13b appending a judge_kind='human' judgment auto-recomputes the snapshot
     and moves evidence_watermark forward, without waiting for a scheduled
     rebuild.
#13d paper_ref (human_reported) evidence mixed with system_graded evidence
     is distinguished correctly — human-reported alone cannot carry
     'mastered'.
"""

from __future__ import annotations

import time

import pytest

from deeptutor.education.application import to_iso_timestamp
from deeptutor.education.application.rebuild_mastery import (
    append_human_judgment_and_recompute,
    rebuild_all,
    rebuild_learner_node,
)
from deeptutor.education.domain.evidence import (
    EvidenceStrength,
    JudgeKind,
    JudgmentRecord,
    StudentAttempt,
    Verdict,
)
from deeptutor.education.storage.repositories import (
    AssessmentItemRepository,
    AttemptRepository,
    JudgmentRepository,
    KnowledgeGraphRepository,
    MasterySnapshotRepository,
)
from deeptutor.education.tests.fixtures import build_fixture_a_math


@pytest.fixture
def one_item(conn, course_version):
    bundle = build_fixture_a_math(course_version.id)
    KnowledgeGraphRepository(conn).import_nodes_and_edges(
        course_version_id=course_version.id, nodes=bundle.nodes[:1], edges=[]
    )
    node = bundle.nodes[0]
    rows = [row for row in bundle.item_rows if row["knowledge_node_id"] == node.id]
    [item] = AssessmentItemRepository(conn).import_items(rows[:1])
    return node, item


def _insert_attempt(
    conn,
    learner,
    node,
    item,
    *,
    attempt_id,
    is_correct,
    submitted_at,
    evidence_strength=EvidenceStrength.SYSTEM_GRADED,
    source="practice",
) -> StudentAttempt:
    attempt = StudentAttempt(
        id=attempt_id,
        learner_id=learner.id,
        assessment_item_id=item.id,
        knowledge_node_id=node.id,
        course_version_id=item.course_version_id,
        response="x",
        is_correct=is_correct,
        score=1.0 if is_correct else 0.0,
        started_at=submitted_at,
        submitted_at=submitted_at,
        grader_version="v1",
        source=source,
        evidence_strength=evidence_strength,
        created_at=submitted_at,
    )
    AttemptRepository(conn).insert(attempt)
    return attempt


# ---- test #13: rebuild from scratch matches, under the same evidence set --


def test_rebuild_all_matches_incremental_computation_under_same_evidence(conn, learner, one_item):
    node, item = one_item
    for i in range(5):
        _insert_attempt(
            conn,
            learner,
            node,
            item,
            attempt_id=f"a{i}",
            is_correct=True,
            submitted_at=f"2026-01-01T00:0{i}:00+00:00",
        )
    before = rebuild_learner_node(conn, learner.id, node.id)

    deleted = MasterySnapshotRepository(conn).delete_all()
    assert deleted >= 1

    report = rebuild_all(conn)
    assert report.pairs_rebuilt == 1

    after = MasterySnapshotRepository(conn).get(learner.id, node.id)
    assert after is not None
    assert after.score == before.score
    assert after.status == before.status
    assert after.evidence_watermark == before.evidence_watermark


def test_rebuild_is_deterministic_across_repeated_calls(conn, learner, one_item):
    node, item = one_item
    for i, correct in enumerate([True, False, True, True]):
        _insert_attempt(
            conn, learner, node, item, attempt_id=f"b{i}", is_correct=correct,
            submitted_at=f"2026-01-01T00:0{i}:00+00:00",
        )
    first = rebuild_learner_node(conn, learner.id, node.id)
    second = rebuild_learner_node(conn, learner.id, node.id)
    third = rebuild_learner_node(conn, learner.id, node.id)
    assert first.score == second.score == third.score
    assert first.status == second.status == third.status


def test_rebuild_result_legitimately_changes_when_evidence_set_changes(conn, learner, one_item):
    """This is the design's explicit correction (§2.6): a *new* piece of
    evidence changing the result is expected behavior, not a violation of
    the rebuild invariant. Only "same evidence -> same result" is
    guaranteed."""
    node, item = one_item
    _insert_attempt(
        conn, learner, node, item, attempt_id="c0", is_correct=True, submitted_at="2026-01-01T00:00:00+00:00"
    )
    before = rebuild_learner_node(conn, learner.id, node.id)
    _insert_attempt(
        conn, learner, node, item, attempt_id="c1", is_correct=False, submitted_at="2026-01-01T00:01:00+00:00"
    )
    after = rebuild_learner_node(conn, learner.id, node.id)
    assert after.score != before.score


# ---- test #13b: human judgment auto-recomputes + watermark moves forward --


def test_human_judgment_triggers_automatic_recompute(conn, learner, one_item):
    node, item = one_item
    attempt = _insert_attempt(
        conn, learner, node, item, attempt_id="d0", is_correct=True, submitted_at="2026-01-01T00:00:00+00:00"
    )
    # An LLM judged it correct at T2.
    JudgmentRepository(conn).insert(
        JudgmentRecord(
            id="j-llm",
            attempt_id=attempt.id,
            judge_kind=JudgeKind.LLM,
            judge_ref="test-model",
            verdict=Verdict.CORRECT,
            confidence=0.9,
            created_at="2026-01-01T00:02:00+00:00",
        )
    )
    snapshot_t2 = rebuild_learner_node(conn, learner.id, node.id)
    assert snapshot_t2.evidence_watermark == "2026-01-01T00:02:00+00:00"

    # T5: a parent's review reverses the verdict — appended, not edited.
    snapshot_t5 = append_human_judgment_and_recompute(
        conn,
        attempt_id=attempt.id,
        judge_ref="parent",
        verdict=Verdict.INCORRECT,
        confidence=1.0,
        rationale="checked by hand, the LLM was wrong",
    )

    assert snapshot_t5.evidence_watermark is not None
    assert snapshot_t5.evidence_watermark > snapshot_t2.evidence_watermark
    # Both judgments are still there — nothing was edited or deleted.
    all_judgments = JudgmentRepository(conn).list_for_attempt(attempt.id)
    assert len(all_judgments) == 2
    assert {j.verdict for j in all_judgments} == {Verdict.CORRECT, Verdict.INCORRECT}
    # The human verdict (the most recent) now determines the outcome.
    assert snapshot_t5.score < snapshot_t2.score


def test_needs_review_judgment_prevents_mastered_status(conn, learner, one_item):
    node, item = one_item
    for i in range(5):
        attempt = _insert_attempt(
            conn, learner, node, item, attempt_id=f"e{i}", is_correct=True,
            submitted_at=f"2026-01-01T00:0{i}:00+00:00",
        )
    JudgmentRepository(conn).insert(
        JudgmentRecord(
            id="j-needs-review",
            attempt_id=attempt.id,
            judge_kind=JudgeKind.LLM,
            judge_ref="test-model",
            verdict=Verdict.NEEDS_REVIEW,
            confidence=0.3,
            created_at="2026-01-01T00:06:00+00:00",
        )
    )
    snapshot = rebuild_learner_node(conn, learner.id, node.id)
    assert snapshot.status != "mastered"


# ---- defect 2 (2026-08-14 audit): needs_review must have a read path ------


def test_needs_review_is_listable_and_disappears_once_resolved(conn, learner, one_item):
    """P0-DESIGN.md §2.6 requires needs_review judgments to enter a human
    review queue. Before this fix, JudgmentRepository had no method that
    could ever surface a needs_review verdict — it was write-only. This
    asserts the full cycle: appears -> listable -> resolved by a newer
    judgment -> gone (even though the old needs_review row is still in the
    append-only table, untouched)."""
    node, item = one_item
    attempt = _insert_attempt(
        conn, learner, node, item, attempt_id="queue-0", is_correct=True,
        submitted_at="2026-01-01T00:00:00+00:00",
    )
    JudgmentRepository(conn).insert(
        JudgmentRecord(
            id="j-queue-needs-review",
            attempt_id=attempt.id,
            judge_kind=JudgeKind.LLM,
            judge_ref="test-model",
            verdict=Verdict.NEEDS_REVIEW,
            confidence=0.3,
            created_at="2026-01-01T00:01:00+00:00",
        )
    )

    queue = JudgmentRepository(conn).list_needs_review()
    assert len(queue) == 1
    assert queue[0].attempt_id == attempt.id
    assert queue[0].verdict is Verdict.NEEDS_REVIEW

    # A newer judgment resolves it — appended, not editing the old row.
    JudgmentRepository(conn).insert(
        JudgmentRecord(
            id="j-queue-resolved",
            attempt_id=attempt.id,
            judge_kind=JudgeKind.HUMAN,
            judge_ref="parent",
            verdict=Verdict.CORRECT,
            created_at="2026-01-01T00:02:00+00:00",
        )
    )
    assert JudgmentRepository(conn).list_needs_review() == []
    # The old needs_review row is still there, unmodified — it's just no
    # longer the *latest* judgment for this attempt, so the queue reflects
    # current truth rather than history.
    all_judgments = JudgmentRepository(conn).list_for_attempt(attempt.id)
    assert len(all_judgments) == 2


def test_needs_review_confidence_floor_surfaces_low_confidence_judgments_too(conn, learner, one_item):
    node, item = one_item
    attempt = _insert_attempt(
        conn, learner, node, item, attempt_id="queue-1", is_correct=True,
        submitted_at="2026-01-01T00:00:00+00:00",
    )
    JudgmentRepository(conn).insert(
        JudgmentRecord(
            id="j-low-confidence",
            attempt_id=attempt.id,
            judge_kind=JudgeKind.LLM,
            judge_ref="test-model",
            verdict=Verdict.CORRECT,  # not needs_review, but confidence is low
            confidence=0.2,
            created_at="2026-01-01T00:01:00+00:00",
        )
    )
    assert JudgmentRepository(conn).list_needs_review() == []  # no floor given -> not surfaced
    surfaced = JudgmentRepository(conn).list_needs_review(confidence_floor=0.6)
    assert len(surfaced) == 1
    assert surfaced[0].attempt_id == attempt.id


# ---- test #13d: paper_ref (human_reported) mixed with system_graded -------


def test_human_reported_alone_cannot_reach_mastered(conn, learner, one_item):
    node, item = one_item
    for i in range(5):
        _insert_attempt(
            conn,
            learner,
            node,
            item,
            attempt_id=f"f{i}",
            is_correct=True,
            submitted_at=f"2026-01-01T00:0{i}:00+00:00",
            evidence_strength=EvidenceStrength.HUMAN_REPORTED,
        )
    snapshot = rebuild_learner_node(conn, learner.id, node.id)
    assert snapshot.score >= 0.9  # the score itself is high...
    assert snapshot.status != "mastered"  # ...but status is capped without system_graded backing


def test_one_system_graded_attempt_unlocks_mastered_when_score_clears_gate(conn, learner, one_item):
    node, item = one_item
    for i in range(4):
        _insert_attempt(
            conn,
            learner,
            node,
            item,
            attempt_id=f"g{i}",
            is_correct=True,
            submitted_at=f"2026-01-01T00:0{i}:00+00:00",
            evidence_strength=EvidenceStrength.HUMAN_REPORTED,
        )
    _insert_attempt(
        conn,
        learner,
        node,
        item,
        attempt_id="g-strong",
        is_correct=True,
        submitted_at="2026-01-01T00:05:00+00:00",
        evidence_strength=EvidenceStrength.SYSTEM_GRADED,
    )
    snapshot = rebuild_learner_node(conn, learner.id, node.id)
    assert snapshot.status == "mastered"


def test_hinted_and_imitated_evidence_counts_as_touched_not_correct(conn, learner, one_item):
    node, item = one_item
    _insert_attempt(
        conn,
        learner,
        node,
        item,
        attempt_id="h0",
        is_correct=True,
        submitted_at="2026-01-01T00:00:00+00:00",
        evidence_strength=EvidenceStrength.HINTED,
    )
    snapshot = rebuild_learner_node(conn, learner.id, node.id)
    assert snapshot.status == "learning"  # touched, but not counted as correctness evidence
    assert snapshot.score == 0.0
