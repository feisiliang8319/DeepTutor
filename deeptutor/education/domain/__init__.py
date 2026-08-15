"""Pure domain data classes for the Education Data Layer — no IO here.

Every class in this sub-package is a frozen ``dataclass`` that mirrors one
row of one table (see ``storage/migrations/001_education_minimum.sql``).
Keeping them IO-free means the same objects can be built in tests, in
fixtures, and from SQLite rows without dragging a database connection
through call signatures that don't need one.
"""

from __future__ import annotations

from deeptutor.education.domain.course import (
    AssessmentItem,
    ContentScope,
    Course,
    CourseVersion,
    CourseVersionStatus,
    EdgeType,
    ItemStatus,
    ItemType,
    KnowledgeEdge,
    KnowledgeNode,
)
from deeptutor.education.domain.evidence import (
    EvidenceStrength,
    JudgeKind,
    JudgmentRecord,
    Provenance,
    StudentAttempt,
    Verdict,
)
from deeptutor.education.domain.learner import (
    LearnerProfile,
    MasterySnapshot,
    ReviewState,
)

__all__ = [
    "AssessmentItem",
    "ContentScope",
    "Course",
    "CourseVersion",
    "CourseVersionStatus",
    "EdgeType",
    "EvidenceStrength",
    "ItemStatus",
    "ItemType",
    "JudgeKind",
    "JudgmentRecord",
    "KnowledgeEdge",
    "KnowledgeNode",
    "LearnerProfile",
    "MasterySnapshot",
    "Provenance",
    "ReviewState",
    "StudentAttempt",
    "Verdict",
]
