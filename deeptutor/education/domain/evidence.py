"""Evidence domain objects: ``student_attempts`` (raw fact) and
``judgment_records`` (append-only verdicts over an attempt).

See P0-DESIGN.md §2.5-2.6. The append-only guarantee itself is enforced by
SQLite triggers (``storage.sqlite``), not by anything in this module — these
are just data shapes.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Provenance(str, Enum):
    NATIVE = "native"
    # Imported from the pre-existing DeepTutor per-book JSON progress files.
    # Not implemented in P0 (see package docstring) — the enum value exists
    # now so the column's CHECK constraint and any future importer agree on
    # spelling from day one.
    MIGRATED_PARTIAL = "migrated_partial"


class EvidenceStrength(str, Enum):
    """How much an attempt's correctness should count toward mastery.

    Only ``SYSTEM_GRADED`` and ``HUMAN_REPORTED`` attempts are averaged into
    a mastery score at all; ``HINTED``/``IMITATED`` count as "touched" but
    never as "correct" evidence (P0-DESIGN.md §2.5). A node can only reach
    ``mastered`` status if at least one ``SYSTEM_GRADED`` attempt backs it —
    see ``application.rebuild_mastery`` for where that rule is applied.
    """

    SYSTEM_GRADED = "system_graded"
    HUMAN_REPORTED = "human_reported"
    HINTED = "hinted"
    IMITATED = "imitated"


class JudgeKind(str, Enum):
    DETERMINISTIC = "deterministic"
    LLM = "llm"
    HUMAN = "human"


class Verdict(str, Enum):
    CORRECT = "correct"
    INCORRECT = "incorrect"
    PARTIAL = "partial"
    NEEDS_REVIEW = "needs_review"


@dataclass(frozen=True, slots=True)
class StudentAttempt:
    id: str
    learner_id: str
    assessment_item_id: str
    knowledge_node_id: str
    course_version_id: str
    response: str
    started_at: str
    submitted_at: str
    grader_version: str
    source: str
    created_at: str
    is_correct: bool | None = None
    score: float | None = None
    duration_ms: int | None = None
    hint_count: int = 0
    retry_index: int = 0
    provenance: Provenance = Provenance.NATIVE
    evidence_strength: EvidenceStrength = EvidenceStrength.SYSTEM_GRADED


@dataclass(frozen=True, slots=True)
class JudgmentRecord:
    id: str
    attempt_id: str
    judge_kind: JudgeKind
    judge_ref: str
    verdict: Verdict
    created_at: str
    prompt_version: str | None = None
    rubric_version: str | None = None
    confidence: float | None = None
    rationale: str | None = None


__all__ = [
    "EvidenceStrength",
    "JudgeKind",
    "JudgmentRecord",
    "Provenance",
    "StudentAttempt",
    "Verdict",
]
