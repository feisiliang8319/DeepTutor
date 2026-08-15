"""record_attempt's transaction flow (P0-DESIGN.md §3), plus test matrix
items #11 (idempotent concurrent same-id submit), #15 (steps 5/6 failing
leaves the attempt committed + pending_recompute + an alert), and #16
(source='demo' never affects mastery).
"""

from __future__ import annotations

import sqlite3

import pytest

from deeptutor.education.application import record_attempt as record_attempt_module
from deeptutor.education.application.record_attempt import (
    NewAttemptInput,
    ValidationError,
    record_attempt,
)
from deeptutor.education.domain.evidence import StudentAttempt
from deeptutor.education.storage.repositories import (
    AssessmentItemRepository,
    AttemptRepository,
    KnowledgeGraphRepository,
)
from deeptutor.education.tests.fixtures import build_fixture_a_math


@pytest.fixture
def seeded_items(conn, course_version):
    bundle = build_fixture_a_math(course_version.id)
    KnowledgeGraphRepository(conn).import_nodes_and_edges(
        course_version_id=course_version.id, nodes=bundle.nodes, edges=bundle.edges
    )
    items = AssessmentItemRepository(conn).import_items(bundle.item_rows)
    return {item.id: item for item in items}


def _params(learner, item_id, response, **overrides) -> NewAttemptInput:
    base = dict(
        learner_id=learner.id,
        assessment_item_id=item_id,
        response=response,
        started_at="2026-01-01T00:00:00+00:00",
        submitted_at="2026-01-01T00:00:05+00:00",
        source="practice",
    )
    base.update(overrides)
    return NewAttemptInput(**base)


# ---- basic transaction flow -------------------------------------------------


def test_record_attempt_grades_choice_correctly(conn, learner, seeded_items):
    item = seeded_items["item-mult-basic-choice"]
    result = record_attempt(conn, _params(learner, item.id, "42"))
    assert result.attempt.is_correct is True
    assert result.pending_recompute is False
    assert result.mastery_snapshot is not None
    assert result.mastery_snapshot.status in ("new", "learning", "mastered")


def test_record_attempt_grades_numeric_with_tolerance(conn, learner, seeded_items):
    item = seeded_items["item-mult-multidigit-numeric"]  # expected "322"
    result = record_attempt(conn, _params(learner, item.id, "322.0000001"))
    assert result.attempt.is_correct is True


def test_record_attempt_rejects_unknown_learner(conn, seeded_items):
    item = next(iter(seeded_items.values()))
    bad_params = NewAttemptInput(
        learner_id="ghost-learner",
        assessment_item_id=item.id,
        response="x",
        started_at="2026-01-01T00:00:00+00:00",
        submitted_at="2026-01-01T00:00:01+00:00",
        source="practice",
    )
    with pytest.raises(ValidationError, match="learner"):
        record_attempt(conn, bad_params)
    assert conn.execute("SELECT COUNT(*) AS n FROM student_attempts").fetchone()["n"] == 0


def test_record_attempt_rejects_unknown_item(conn, learner):
    bad_params = _params(learner, "ghost-item", "x")
    with pytest.raises(ValidationError, match="assessment_item"):
        record_attempt(conn, bad_params)


def test_paper_ref_item_forced_to_human_reported_evidence_strength(conn, learner, course_version):
    bundle = build_fixture_a_math(course_version.id)
    KnowledgeGraphRepository(conn).import_nodes_and_edges(
        course_version_id=course_version.id, nodes=bundle.nodes[:1], edges=[]
    )
    node = bundle.nodes[0]
    row = {
        "id": "item-paper",
        "course_version_id": course_version.id,
        "knowledge_node_id": node.id,
        "item_type": "paper_ref",
        "prompt": None,
        "expected_answer": None,
        "rubric_json": None,
        "difficulty": 2,
        "content_scope": "REFERENCE_ONLY",
        "source_ref": "BA-4A|p.37|#12",
        "license_note": None,
        "attribution_text": None,
        "derived_from_item_id": None,
        "reviewer": None,
        "reviewed_at": None,
        "content_hash": "hash-paper",
        "status": "production",
    }
    [item] = AssessmentItemRepository(conn).import_items([row])
    from deeptutor.education.domain.evidence import EvidenceStrength

    # Even if a caller mistakenly asks for SYSTEM_GRADED, paper_ref forces
    # HUMAN_REPORTED — this is what keeps human-reported evidence from
    # silently outweighing real auto-graded evidence in rebuild_mastery.
    result = record_attempt(
        conn,
        _params(
            learner,
            item.id,
            "correct",
            evidence_strength=EvidenceStrength.SYSTEM_GRADED,
            manual_is_correct=True,
            manual_score=1.0,
        ),
    )
    assert result.attempt.evidence_strength is EvidenceStrength.HUMAN_REPORTED


# ---- test #11: concurrent submit of the same attempt id -------------------


def test_duplicate_attempt_id_is_idempotent(conn, learner, course_version):
    bundle = build_fixture_a_math(course_version.id)
    KnowledgeGraphRepository(conn).import_nodes_and_edges(
        course_version_id=course_version.id, nodes=bundle.nodes[:1], edges=[]
    )
    items = AssessmentItemRepository(conn).import_items(
        [row for row in bundle.item_rows if row["knowledge_node_id"] == bundle.nodes[0].id]
    )
    item = items[0]
    now = "2026-01-01T00:00:00+00:00"
    attempt = StudentAttempt(
        id="same-id-twice",
        learner_id=learner.id,
        assessment_item_id=item.id,
        knowledge_node_id=item.knowledge_node_id,
        course_version_id=item.course_version_id,
        response="42",
        is_correct=True,
        score=1.0,
        started_at=now,
        submitted_at=now,
        grader_version="v1",
        source="practice",
        created_at=now,
    )
    repo = AttemptRepository(conn)
    first = repo.insert(attempt)
    second = repo.insert(attempt)  # simulates a retried network call re-sending the same id
    assert first is True
    assert second is False
    count = conn.execute(
        "SELECT COUNT(*) AS n FROM student_attempts WHERE id = 'same-id-twice'"
    ).fetchone()["n"]
    assert count == 1


def test_record_attempt_entry_point_is_idempotent_under_the_same_client_attempt_id(
    conn, learner, seeded_items
):
    """2026-08-14 audit finding (defect 1): AttemptRepository.insert's dedup
    was always correct in isolation, but record_attempt() generated a fresh
    uuid4() id on every call, so the dedup key could never repeat on this
    entry point and two "identical" submissions produced two attempts. This
    is the regression test for the fix: call record_attempt() — the actual
    production entry point, not the repository directly — 5 times with the
    same client_attempt_id and assert exactly one attempt exists.
    """
    item = seeded_items["item-mult-basic-choice"]
    params = _params(learner, item.id, "42", client_attempt_id="idem-key-abc")

    results = [record_attempt(conn, params) for _ in range(5)]

    assert AttemptRepository(conn).count_for_learner(learner.id) == 1
    ids = {r.attempt.id for r in results}
    assert ids == {"idem-key-abc"}
    # And it must not have duplicated the judgment/mastery side effects
    # either — see the second assertion in the sibling judgment test below.


def test_retrying_a_judged_attempt_does_not_duplicate_judgment_records(conn, learner, seeded_items):
    """The other half of defect 1: a retry must not re-run steps 4-6, or a
    multi_step/LLM-judged attempt would grow a new judgment_records row on
    every retry even though the attempt itself dedups correctly."""
    from deeptutor.education.application.record_attempt import JudgmentInput
    from deeptutor.education.domain.evidence import JudgeKind, Verdict
    from deeptutor.education.storage.repositories import JudgmentRepository

    item = seeded_items["item-frac-equiv-short"]
    params = _params(
        learner,
        item.id,
        "6/9",
        client_attempt_id="idem-key-judged",
        judgment=JudgmentInput(judge_kind=JudgeKind.LLM, judge_ref="test-model", verdict=Verdict.CORRECT),
    )

    for _ in range(3):
        record_attempt(conn, params)

    assert AttemptRepository(conn).count_for_learner(learner.id) == 1
    judgments = JudgmentRepository(conn).list_for_attempt("idem-key-judged")
    assert len(judgments) == 1


def test_without_client_attempt_id_no_idempotency_guarantee_is_made(conn, learner, seeded_items):
    """Documents the opt-in nature of the fix: omitting client_attempt_id
    keeps the pre-fix behavior (a fresh id per call) on purpose, because
    record_attempt() cannot infer a caller's retry semantics for it."""
    item = seeded_items["item-mult-basic-choice"]
    params = _params(learner, item.id, "42")  # no client_attempt_id
    record_attempt(conn, params)
    record_attempt(conn, params)
    assert AttemptRepository(conn).count_for_learner(learner.id) == 2


# ---- test #15: steps 5/6 failing leaves the attempt intact -----------------


def test_step5_mastery_recompute_failure_marks_pending_recompute(conn, learner, seeded_items, monkeypatch, caplog):
    import logging

    item = seeded_items["item-mult-basic-choice"]

    def _boom(*a, **kw):
        raise RuntimeError("simulated mastery recompute failure")

    monkeypatch.setattr(record_attempt_module, "rebuild_learner_node", _boom)

    with caplog.at_level(logging.ERROR, logger="deeptutor.education.alerts"):
        result = record_attempt(conn, _params(learner, item.id, "42"))

    assert result.pending_recompute is True
    # The attempt itself is durably committed regardless.
    stored = AttemptRepository(conn).get(result.attempt.id)
    assert stored is not None
    assert stored.id == result.attempt.id

    snapshot = conn.execute(
        "SELECT status FROM mastery_snapshots WHERE learner_id = ? AND knowledge_node_id = ?",
        (learner.id, item.knowledge_node_id),
    ).fetchone()
    assert snapshot["status"] == "pending_recompute"
    assert any("pending_recompute" in r.getMessage() for r in caplog.records)


def test_step6_review_state_failure_marks_pending_recompute(conn, learner, seeded_items, monkeypatch):
    item = seeded_items["item-mult-basic-choice"]

    def _boom(*a, **kw):
        raise RuntimeError("simulated review-state update failure")

    monkeypatch.setattr(record_attempt_module, "_update_review_state", _boom)

    result = record_attempt(conn, _params(learner, item.id, "42"))
    assert result.pending_recompute is True
    stored = AttemptRepository(conn).get(result.attempt.id)
    assert stored is not None


def test_pending_recompute_is_healed_by_rebuild(conn, learner, seeded_items, monkeypatch):
    """The 'idempotent recompute command' the design requires: calling
    rebuild_learner_node after a pending_recompute failure clears it."""
    from deeptutor.education.application.rebuild_mastery import rebuild_learner_node

    item = seeded_items["item-mult-basic-choice"]

    def _boom(*a, **kw):
        raise RuntimeError("simulated failure")

    monkeypatch.setattr(record_attempt_module, "rebuild_learner_node", _boom)
    result = record_attempt(conn, _params(learner, item.id, "42"))
    assert result.pending_recompute is True

    healed = rebuild_learner_node(conn, learner.id, item.knowledge_node_id)
    assert healed.status != "pending_recompute"


# ---- defect 2 (2026-08-14 audit): pending_recompute must have a read path -


def test_pending_recompute_is_listable_and_disappears_once_healed(conn, learner, seeded_items, monkeypatch):
    """Before this fix, pending_recompute was a write-only status: it was
    set on failure but no repository method could ever list it back out, so
    nothing — human or automated — could discover the backlog and process
    it. This asserts the full cycle: fails -> listable -> healed -> gone."""
    from deeptutor.education.application.rebuild_mastery import rebuild_learner_node
    from deeptutor.education.storage.repositories import MasterySnapshotRepository

    item = seeded_items["item-mult-basic-choice"]

    def _boom(*a, **kw):
        raise RuntimeError("simulated failure")

    monkeypatch.setattr(record_attempt_module, "rebuild_learner_node", _boom)
    record_attempt(conn, _params(learner, item.id, "42"))

    snapshots_repo = MasterySnapshotRepository(conn)
    backlog = snapshots_repo.list_pending_recompute()
    assert len(backlog) == 1
    assert backlog[0].learner_id == learner.id
    assert backlog[0].knowledge_node_id == item.knowledge_node_id

    # Filtering by learner_id works too, and excludes other learners.
    scoped = snapshots_repo.list_pending_recompute(learner_id=learner.id)
    assert len(scoped) == 1
    assert snapshots_repo.list_pending_recompute(learner_id="some-other-learner") == []

    rebuild_learner_node(conn, learner.id, item.knowledge_node_id)
    assert snapshots_repo.list_pending_recompute() == []


# ---- test #16: source='demo' never affects mastery -------------------------


def test_demo_source_attempt_excluded_from_mastery(conn, learner, seeded_items):
    item = seeded_items["item-mult-basic-choice"]
    result = record_attempt(conn, _params(learner, item.id, "42", source="demo"))
    assert result.attempt.source == "demo"
    # rebuild sees zero non-demo attempts for this node -> status stays "new"
    assert result.mastery_snapshot is not None
    assert result.mastery_snapshot.status == "new"
    assert result.mastery_snapshot.score == 0.0


def test_demo_attempts_are_excluded_even_when_mixed_with_real_ones(conn, learner, seeded_items):
    item = seeded_items["item-mult-basic-choice"]
    record_attempt(conn, _params(learner, item.id, "wrong-answer", source="demo"))
    result = record_attempt(conn, _params(learner, item.id, "42", source="practice"))
    attempts = AttemptRepository(conn).list_for_node(learner.id, item.knowledge_node_id)
    assert len(attempts) == 1  # the demo attempt is excluded by list_for_node's default
    assert attempts[0].source == "practice"
    assert result.mastery_snapshot is not None


# ---- 20 fixture answers: attempt count matches submission count -----------


def test_twenty_consecutive_fixture_answers_produce_twenty_attempts(conn, learner, seeded_items):
    item_ids = list(seeded_items.keys())
    for i in range(20):
        item = seeded_items[item_ids[i % len(item_ids)]]
        record_attempt(conn, _params(learner, item.id, "irrelevant-response", submitted_at=f"2026-01-01T00:{i:02d}:00+00:00"))
    assert AttemptRepository(conn).count_for_learner(learner.id) == 20
