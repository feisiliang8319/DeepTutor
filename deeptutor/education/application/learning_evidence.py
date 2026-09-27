"""Describe observed practice separately from unmeasured retention/transfer.

The 48-hour interval is an initial product rule, not a validated measurement
of lasting mastery. This read model never writes or invents learner evidence.
"""
from datetime import datetime

from deeptutor.education.application.effective_grade import effective_correctness
from deeptutor.education.domain.evidence import EvidenceStrength, JudgeKind
from deeptutor.education.storage.repositories import AttemptRepository, JudgmentRepository

DELAY_HOURS = 48


def learning_evidence(conn, learner_id, node_id):
    attempts = AttemptRepository(conn).list_for_node(learner_id, node_id)
    judgments = JudgmentRepository(conn).list_for_attempts([a.id for a in attempts])
    latest_judgments = {j.attempt_id: j for j in judgments}
    latest = {}
    first_correct = {}
    pending = 0
    model_judged = 0
    for attempt in attempts:
        judgment = latest_judgments.get(attempt.id)
        if judgment and judgment.judge_kind is JudgeKind.LLM:
            model_judged += 1
        if attempt.evidence_strength in (EvidenceStrength.HINTED, EvidenceStrength.IMITATED):
            continue
        correct = effective_correctness(attempt.is_correct, judgment)
        if correct is None:
            pending += 1
        latest[attempt.assessment_item_id] = (correct, attempt.submitted_at)
        if correct:
            first_correct.setdefault(attempt.assessment_item_id, attempt.submitted_at)

    distinct_correct = sum(correct is True for correct, _ in latest.values())
    delayed = 0
    for item_id, (correct, submitted_at) in latest.items():
        if correct is not True:
            continue
        start = datetime.fromisoformat(first_correct[item_id].replace("Z", "+00:00"))
        end = datetime.fromisoformat(submitted_at.replace("Z", "+00:00"))
        if (end - start).total_seconds() >= DELAY_HOURS * 3600:
            delayed += 1
    return {
        "distinct_correct_items": distinct_correct,
        "independent_practice": "observed" if distinct_correct >= 3 and not pending else "insufficient",
        "pending_review": pending,
        "delayed_correct_items": delayed,
        "delayed_review": "observed" if delayed else "not_yet_observed",
        "delay_hours": DELAY_HOURS,
        "transfer": "not_assessed",
        "model_judged_attempts": model_judged,
        "model_calibration": "not_established" if model_judged else "not_applicable",
    }
