"""Compute (and persist) mastery_snapshots purely from student_attempts +
judgment_records.

**The rebuild invariant, as corrected in P0-DESIGN.md §2.6** — this is the
one thing every function in this module must uphold:

    rebuild(t) == recompute from the full evidence set known at time t.

Not "reproduce whatever the online value was at some past moment" — a human
judgment (§2.6's worked example: T2 an LLM says correct, T5 a parent's
review says incorrect) is allowed to change the *result* of a rebuild
without that being a bug. What must stay true is determinism given a fixed
evidence set: run this module twice over the same rows and get the same
score both times.

P0 mastery policy (documented here because nothing in P0-DESIGN.md's DDL
encodes it — the design only fixes the *evidence rules* in §2.5/§2.6, not
the exact status arithmetic):

* Evidence with ``evidence_strength`` in {HINTED, IMITATED} counts as
  "touched" but never enters the correctness average — a hinted or
  imitated success is not proof of independent mastery.
* Evidence with a judgment whose verdict is ``NEEDS_REVIEW`` counts as
  "touched" but is excluded from the average and caps the node's status
  below ``mastered`` until it is resolved.
* A judgment overrides its attempt's raw ``is_correct`` (a later verdict —
  e.g. an LLM grading a Feynman explanation — has the final say);
  ``PARTIAL`` is treated conservatively as not-correct.
* A node can only reach ``mastered`` if the recency-weighted score clears
  ``MASTERY_GATE`` *and* at least one ``SYSTEM_GRADED`` attempt is among
  the evidence — human-reported (e.g. paper_ref) correctness alone cannot
  carry a mastered verdict (P0-DESIGN.md §2.5).
* The most recent judgment on the node having low confidence also caps the
  status below ``mastered``, regardless of the score.
"""

from __future__ import annotations

from dataclasses import dataclass
import sqlite3
import time
import uuid

from deeptutor.education.application import to_iso_timestamp
from deeptutor.education.domain.evidence import EvidenceStrength, JudgeKind, JudgmentRecord, Verdict
from deeptutor.education.domain.learner import MasterySnapshot
from deeptutor.education.storage.repositories import (
    AttemptRepository,
    JudgmentRepository,
    MasterySnapshotRepository,
)
from deeptutor.education.storage.sqlite import transaction
from deeptutor.learning.mastery import compute_mastery

POLICY_VERSION = "edu-p0-v1"

# Mirrors deeptutor.learning.policy.QUANTITATIVE_GATE's default (0.9). Not
# imported from there: coupling this package to deeptutor/learning is a
# later, separate adapter phase (see the package's top-level docstring), so
# the number is restated here rather than pulled in as a live dependency.
MASTERY_GATE = 0.9

# A judgment below this confidence cannot, by itself, carry a node to
# "mastered" — it routes to human review instead (P0-DESIGN.md §2.6).
LOW_CONFIDENCE_FLOOR = 0.6


def _effective_correctness(is_correct: bool | None, judgment: JudgmentRecord | None) -> bool | None:
    """What one attempt actually contributes to the correctness tally,
    after a judgment (if any) has the final say. ``None`` means "not usable
    evidence yet" (ungraded, or awaiting review)."""
    if judgment is None:
        return is_correct
    if judgment.verdict is Verdict.NEEDS_REVIEW:
        return None
    return judgment.verdict is Verdict.CORRECT


@dataclass(frozen=True, slots=True)
class NodeMasteryComputation:
    score: float
    status: str
    confidence: float | None
    evidence_watermark: str | None
    last_attempt_id: str | None


def compute_node_mastery(
    conn: sqlite3.Connection, learner_id: str, knowledge_node_id: str
) -> NodeMasteryComputation:
    """Pure read + compute — does not write anything. ``rebuild_learner_node``
    below is the write path; kept separate so tests can assert on the
    computation without needing to also assert on persistence.
    """
    attempts = AttemptRepository(conn).list_for_node(learner_id, knowledge_node_id)
    if not attempts:
        return NodeMasteryComputation(
            score=0.0, status="new", confidence=None, evidence_watermark=None, last_attempt_id=None
        )

    all_judgments = JudgmentRepository(conn).list_for_attempts([a.id for a in attempts])
    # list_for_attempts is chronological ascending; later entries for the
    # same attempt_id overwrite earlier ones in this dict, so the dict ends
    # up holding each attempt's *latest* judgment.
    latest_by_attempt: dict[str, JudgmentRecord] = {}
    for judgment in all_judgments:
        latest_by_attempt[judgment.attempt_id] = judgment

    counted: list[bool] = []
    has_strong_evidence = False
    touched = False
    needs_review_pending = False
    considered_judgment_timestamps: list[str] = []

    for attempt in attempts:
        judgment = latest_by_attempt.get(attempt.id)
        if judgment is not None:
            considered_judgment_timestamps.append(judgment.created_at)

        if attempt.evidence_strength in (EvidenceStrength.HINTED, EvidenceStrength.IMITATED):
            touched = True
            continue

        if judgment is not None and judgment.verdict is Verdict.NEEDS_REVIEW:
            touched = True
            needs_review_pending = True
            continue

        effective = _effective_correctness(attempt.is_correct, judgment)
        if effective is None:
            touched = True
            continue

        touched = True
        counted.append(effective)
        if attempt.evidence_strength is EvidenceStrength.SYSTEM_GRADED:
            has_strong_evidence = True

    latest_judgment_overall = max(all_judgments, key=lambda j: j.created_at, default=None)
    low_confidence_pending = (
        latest_judgment_overall is not None
        and latest_judgment_overall.confidence is not None
        and latest_judgment_overall.confidence < LOW_CONFIDENCE_FLOOR
    )

    score = compute_mastery(counted) if counted else 0.0

    if not touched:
        status = "new"
    elif needs_review_pending or low_confidence_pending:
        status = "learning"
    elif score >= MASTERY_GATE and has_strong_evidence:
        status = "mastered"
    else:
        status = "learning"

    evidence_watermark = max(considered_judgment_timestamps) if considered_judgment_timestamps else None
    confidence = latest_judgment_overall.confidence if latest_judgment_overall is not None else None

    return NodeMasteryComputation(
        score=score,
        status=status,
        confidence=confidence,
        evidence_watermark=evidence_watermark,
        last_attempt_id=attempts[-1].id,
    )


def rebuild_learner_node(
    conn: sqlite3.Connection, learner_id: str, knowledge_node_id: str
) -> MasterySnapshot:
    """Recompute one learner+node snapshot and persist it.

    Writes via a single ``INSERT ... ON CONFLICT`` statement, so this is
    safe to call standalone (it autocommits under this package's
    autocommit-mode connections — see ``storage.sqlite.connect_raw``) or
    from inside a caller's own ``transaction()`` block, where it simply
    joins that transaction instead of starting a nested one.
    """
    computed = compute_node_mastery(conn, learner_id, knowledge_node_id)
    snapshot = MasterySnapshot(
        learner_id=learner_id,
        knowledge_node_id=knowledge_node_id,
        score=computed.score,
        status=computed.status,
        confidence=computed.confidence,
        policy_version=POLICY_VERSION,
        last_attempt_id=computed.last_attempt_id,
        evidence_watermark=computed.evidence_watermark,
        updated_at=to_iso_timestamp(time.time()),
    )
    MasterySnapshotRepository(conn).upsert(snapshot)
    return snapshot


@dataclass(frozen=True, slots=True)
class RebuildReport:
    pairs_rebuilt: int
    snapshots: list[MasterySnapshot]


def rebuild_all(conn: sqlite3.Connection) -> RebuildReport:
    """Delete-and-reconstruct entry point. Exercises the P0-DESIGN.md §6
    test #13 invariant: ``mastery_snapshots`` can be truncated entirely and
    rebuilt from ``student_attempts`` + ``judgment_records`` alone. Runs as
    one transaction — either every pair's snapshot is refreshed or none is.
    """
    pairs = AttemptRepository(conn).list_all_learner_node_pairs()
    snapshots: list[MasterySnapshot] = []
    with transaction(conn):
        for learner_id, knowledge_node_id in pairs:
            snapshots.append(rebuild_learner_node(conn, learner_id, knowledge_node_id))
    return RebuildReport(pairs_rebuilt=len(pairs), snapshots=snapshots)


def append_human_judgment_and_recompute(
    conn: sqlite3.Connection,
    *,
    attempt_id: str,
    judge_ref: str,
    verdict: Verdict,
    confidence: float | None = None,
    rationale: str | None = None,
    rubric_version: str | None = None,
    prompt_version: str | None = None,
    judgment_id: str | None = None,
) -> MasterySnapshot:
    """Append a ``judge_kind='human'`` correction and immediately recompute
    the affected snapshot — P0-DESIGN.md §2.6's requirement that a human
    override not wait for the next scheduled rebuild (test #13b). The
    judgment itself is never edited or replaced, only appended; the earlier
    verdict this supersedes is still there for anyone auditing the trail.
    """
    attempt = AttemptRepository(conn).get(attempt_id)
    if attempt is None:
        raise ValueError(f"unknown attempt_id {attempt_id!r}")

    record = JudgmentRecord(
        id=judgment_id or str(uuid.uuid4()),
        attempt_id=attempt_id,
        judge_kind=JudgeKind.HUMAN,
        judge_ref=judge_ref,
        prompt_version=prompt_version,
        rubric_version=rubric_version,
        verdict=verdict,
        confidence=confidence,
        rationale=rationale,
        created_at=to_iso_timestamp(time.time()),
    )
    with transaction(conn):
        JudgmentRepository(conn).insert(record)
        snapshot = rebuild_learner_node(conn, attempt.learner_id, attempt.knowledge_node_id)
    return snapshot


__all__ = [
    "LOW_CONFIDENCE_FLOOR",
    "MASTERY_GATE",
    "POLICY_VERSION",
    "NodeMasteryComputation",
    "RebuildReport",
    "append_human_judgment_and_recompute",
    "compute_node_mastery",
    "rebuild_all",
    "rebuild_learner_node",
]
