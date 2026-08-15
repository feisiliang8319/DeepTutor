"""Course / knowledge-graph / assessment-item domain objects.

Field names and nullability mirror the DDL in
``storage/migrations/001_education_minimum.sql`` (which mirrors
P0-DESIGN.md §2.2-2.4) exactly, so a row from ``sqlite3.Row`` can be spread
straight into these constructors via ``**dict(row)``.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class CourseVersionStatus(str, Enum):
    DRAFT = "draft"
    ACTIVE = "active"
    ARCHIVED = "archived"


class ItemType(str, Enum):
    CHOICE = "choice"
    SHORT = "short"
    NUMERIC = "numeric"
    MULTI_STEP = "multi_step"
    VISUAL_MODEL = "visual_model"
    # Points at a physical page in a book the family already owns; no prompt
    # text is stored (see P0-DESIGN.md §2.4.1). Grading is human-reported.
    PAPER_REF = "paper_ref"


class ContentScope(str, Enum):
    """Rights-layer classification. See P0-DESIGN.md §2.4 for the full
    definition of each value — this is not a free-form tag, it drives
    fail-closed import/export gates in ``storage.repositories``."""

    BUNDLED = "BUNDLED"
    PRIVATE_INTERNAL = "PRIVATE_INTERNAL"
    REFERENCE_ONLY = "REFERENCE_ONLY"
    RESTRICTED = "RESTRICTED"


class ItemStatus(str, Enum):
    CANDIDATE = "candidate"
    PRODUCTION = "production"
    RETIRED = "retired"


class EdgeType(str, Enum):
    """P0 planner (``application.select_objective``) only consumes
    ``PREREQUISITE``. The other three exist so the US History fixture can
    prove the schema is not math-only; they are stored and schema-validated
    but never read by the planner (P0-DESIGN.md §2.3)."""

    PREREQUISITE = "PREREQUISITE"
    PRECEDES = "PRECEDES"
    CAUSES = "CAUSES"
    SUPPORTS = "SUPPORTS"


# Fields a public consumer (a UI, an export, a RAG index) may see. Anything
# not in this tuple — chiefly ``expected_answer`` and ``rubric_json`` — must
# never appear in a payload built for the student or leave via export
# (P0-DESIGN.md §2.4.2 "expected_answer 泄露闸门"; test matrix items 7-9).
_ITEM_PUBLIC_FIELDS: tuple[str, ...] = (
    "id",
    "course_version_id",
    "knowledge_node_id",
    "item_type",
    "prompt",
    "difficulty",
    "content_scope",
    "source_ref",
    "license_note",
    "attribution_text",
    "derived_from_item_id",
    "status",
    "figure_spec_id",
)


@dataclass(frozen=True, slots=True)
class Course:
    id: str
    subject_key: str
    title: str
    created_at: str


@dataclass(frozen=True, slots=True)
class CourseVersion:
    id: str
    course_id: str
    version: str
    content_hash: str
    status: CourseVersionStatus
    created_at: str


@dataclass(frozen=True, slots=True)
class KnowledgeNode:
    id: str
    course_version_id: str
    code: str
    node_type: str
    title: str
    sort_order: int
    # External curriculum-standard anchor (CCSS "4.OA.B.4", AP CED topic id, …).
    # None = this node is not anchored to any published standard, which is a
    # valid end state, not a TODO: self-authored nodes and nodes merged across
    # two standards have no single code. One standard maps to many nodes.
    standard_code: str | None = None


@dataclass(frozen=True, slots=True)
class KnowledgeEdge:
    course_version_id: str
    from_node_id: str
    to_node_id: str
    edge_type: EdgeType = EdgeType.PREREQUISITE

    def __post_init__(self) -> None:
        # The DB CHECK constraint enforces this too, but a domain object
        # should already be invalid before it ever reaches SQL — cheaper to
        # fail in Python during fixture/import construction than to round
        # trip to sqlite3.IntegrityError for a mistake this obvious.
        if self.from_node_id == self.to_node_id:
            raise ValueError(f"self-edge rejected: node {self.from_node_id!r} points to itself")


@dataclass(frozen=True, slots=True)
class AssessmentItem:
    id: str
    course_version_id: str
    knowledge_node_id: str
    item_type: ItemType
    difficulty: int
    content_scope: ContentScope
    content_hash: str
    status: ItemStatus
    prompt: str | None = None
    # Server-grading-path only. Never put this field's value in a payload
    # that reaches the student, an export, a log line, or a vector index.
    expected_answer: str | None = None
    rubric_json: str | None = None
    source_ref: str | None = None
    license_note: str | None = None
    attribution_text: str | None = None
    derived_from_item_id: str | None = None
    reviewer: str | None = None
    reviewed_at: str | None = None
    # Filename stem of a structured figure spec under seeds/figures/. Public
    # on purpose: the student cannot answer a figure-dependent item without
    # seeing the figure. It carries no answer — see the note in
    # seeds/figures/cemc-books-books-books.json for the one case where a
    # naive transcription would have leaked part (a)'s answer into the spec.
    figure_spec_id: str | None = None

    def to_public_payload(self) -> dict[str, object]:
        """Whitelist serialization for anything that isn't the grading path.

        Deliberately built by listing allowed fields rather than by
        stripping forbidden ones — a field added later to this dataclass
        defaults to *excluded* unless someone consciously adds it to
        ``_ITEM_PUBLIC_FIELDS``, not the other way around.
        """
        payload: dict[str, object] = {}
        for field_name in _ITEM_PUBLIC_FIELDS:
            value = getattr(self, field_name)
            if isinstance(value, Enum):
                value = value.value
            payload[field_name] = value
        return payload


__all__ = [
    "AssessmentItem",
    "ContentScope",
    "Course",
    "CourseVersion",
    "CourseVersionStatus",
    "EdgeType",
    "ItemStatus",
    "ItemType",
    "KnowledgeEdge",
    "KnowledgeNode",
]
