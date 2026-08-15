"""Learner / mastery / review-state domain objects.

See P0-DESIGN.md §2.1, §2.7, §2.8. ``MasterySnapshot`` and ``ReviewState``
are both *derived* rows — nothing here computes them, ``application`` does.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class LearnerProfile:
    id: str
    deep_tutor_user_id: str
    display_name: str
    locale: str
    created_at: str
    updated_at: str
    # Context only — never a planner input. Foundation Track routing must be
    # evidence-triggered, not grade-label-triggered (P0-DESIGN.md §2.1).
    grade_band: str | None = None


# Status values reuse deeptutor.learning.policy's existing three-way
# vocabulary ("mastered" | "learning" | "new") plus one P0 addition,
# "pending_recompute", used to flag a snapshot that is known-stale because
# step 5/6 of record_attempt failed after the attempt itself was already
# committed (P0-DESIGN.md §3 failure handling). There is no separate table
# for this state — reusing the status column keeps the append-only vs.
# derived-and-rebuildable table split exactly as designed.
MASTERY_STATUSES: frozenset[str] = frozenset({"new", "learning", "mastered", "pending_recompute"})


@dataclass(frozen=True, slots=True)
class MasterySnapshot:
    learner_id: str
    knowledge_node_id: str
    score: float
    status: str
    policy_version: str
    updated_at: str
    confidence: float | None = None
    last_attempt_id: str | None = None
    # The newest judgment_record.created_at this snapshot's computation
    # consulted (NULL if the node has no qualitative evidence at all). Makes
    # "which evidence batch is this snapshot based on" auditable — see
    # P0-DESIGN.md §2.6 rebuild-invariant correction.
    evidence_watermark: str | None = None


@dataclass(frozen=True, slots=True)
class ReviewState:
    """FSRS-ish spaced-repetition state. Explicitly NOT covered by the
    "rebuild == exact reconstruction" contract that applies to
    ``MasterySnapshot`` — it is time-relative state, see P0-DESIGN.md §2.8.
    """

    learner_id: str
    knowledge_node_id: str
    stability: float
    difficulty: float
    due_at: str
    fsrs_params_ver: str
    last_review_at: str | None = None
    reps: int = 0
    lapses: int = 0
    # FSRS card phase + step index; see the migration comment on the columns.
    fsrs_state: int = 1
    fsrs_step: int | None = None



@dataclass(frozen=True, slots=True)
class Enrollment:
    """一个学习者选了某个课程版本。

    这是学生与内容之间**唯一**的关联点。内容表（knowledge_nodes /
    assessment_items / knowledge_edges）一概不认识学习者；加一个学生就是往
    这里加一行，不动内容结构。

    关联到 course_version_id 而非 course_id：学生的历史进度属于他当时学的那
    一版教材，换版后旧版仍要能查。是否自动跟随最新版是产品决策，不由外键代答。
    """

    learner_id: str
    course_version_id: str
    status: str
    enrolled_at: str
    updated_at: str


__all__ = [
    "MASTERY_STATUSES",
    "Enrollment",
    "LearnerProfile",
    "MasterySnapshot",
    "ReviewState",
]
