"""Plan or append corrections; preserve raw attempts and existing judgments.

Application is an explicit maintenance operation on a backed-up database,
never an automatic startup migration. Returned counts contain no responses.
"""
from __future__ import annotations

import time
import uuid

from deeptutor.education.application import to_iso_timestamp
from deeptutor.education.application.record_attempt import _grade, rebuild_review_state
from deeptutor.education.application.rebuild_mastery import rebuild_learner_node
from deeptutor.education.domain.evidence import JudgeKind, JudgmentRecord, Verdict
from deeptutor.education.storage.repositories import (
    AssessmentItemRepository, AttemptRepository, JudgmentRepository,
)
from deeptutor.education.storage.sqlite import transaction

REPAIR_VERSION = "edu-exact-math-v2"
INVALID_ITEMS = frozenset({
    "synth-g4-nbt-a1-place_ten_times-017",
    "synth-g4-nbt-a1-place_ten_times-019",
})


def _plan(conn):
    corrections = []
    items = AssessmentItemRepository(conn)
    judgments = JudgmentRepository(conn)
    for row in conn.execute("SELECT id, assessment_item_id, response, is_correct FROM student_attempts"):
        # Human/LLM adjudications remain authoritative. This repair does not
        # silently replace an existing decision with a new deterministic one.
        if judgments.latest_for_attempt(row["id"]) is not None:
            continue
        item = items.get(row["assessment_item_id"])
        if item is None:
            raise ValueError("attempt references missing content")
        if item.id in INVALID_ITEMS:
            corrections.append((row["id"], Verdict.NEEDS_REVIEW))
            continue
        correct, _ = _grade(item, row["response"])
        if correct is not None and row["is_correct"] is not None and correct != bool(row["is_correct"]):
            corrections.append((row["id"], Verdict.CORRECT if correct else Verdict.INCORRECT))
    return corrections


def repair_deterministic_evidence(conn, *, apply: bool = False) -> dict:
    """Dry-run by default; apply appends verdicts and rebuilds derived state."""
    def summary(plan, rebuilt=0):
        return {"mode": "apply" if apply else "dry-run", "corrections": len(plan),
                "invalid_item_reviews": sum(v is Verdict.NEEDS_REVIEW for _, v in plan),
                "derived_pairs_rebuilt": rebuilt, "repair_version": REPAIR_VERSION}

    if not apply:
        return summary(_plan(conn))
    with transaction(conn):
        plan = _plan(conn)
        for attempt_id, verdict in plan:
            JudgmentRepository(conn).insert(JudgmentRecord(
                id=str(uuid.uuid5(uuid.NAMESPACE_URL, REPAIR_VERSION + ":" + attempt_id)),
                attempt_id=attempt_id, judge_kind=JudgeKind.DETERMINISTIC,
                judge_ref=REPAIR_VERSION, verdict=verdict,
                confidence=1.0 if verdict is not Verdict.NEEDS_REVIEW else None,
                rationale="Audited invalid question; review required" if verdict is Verdict.NEEDS_REVIEW
                    else "Deterministic regrade after the mathematical comparison correction",
                created_at=to_iso_timestamp(time.time()),
            ))
        pairs = AttemptRepository(conn).list_all_learner_node_pairs()
        for learner_id, node_id in pairs:
            rebuild_learner_node(conn, learner_id, node_id)
            rebuild_review_state(conn, learner_id, node_id)
    return summary(plan, len(pairs))
