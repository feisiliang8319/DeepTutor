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
    # 选项进白名单，讲解**不进**：选项是答题必需（不给就没法作答），讲解按 Sol
    # 2026-08-21 的要求只能在全部提交之后出现，所以它走 review 专用出口，
    # 不搭这班车。见 api/app.py 的 /api/edu/set/submit。
    "choices_json",
)


@dataclass(frozen=True, slots=True)
class Course:
    id: str
    subject_key: str
    title: str
    created_at: str
    # 年级/等级，与 subject_key 一起构成课程目录的查询键（'G4' / 'AP-HS'）。
    # 不从 title 里解析：title 是给人看的展示串，改一次文案就会让查询失灵。
    level: str | None = None


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
    # 选择题的选项，JSON 数组：[{"label": "A", "text": "…"}, …]。
    # 此前选项是拼进 prompt 散文的，前端只能拿到一坨文本，渲染不出单选按钮，
    # 孩子只好手打字母。**结构里绝不标哪个是对的** —— 那等于把 expected_answer
    # 换个字段名送到浏览器；import 时有闸门强制（repositories._validate_item_row）。
    choices_json: str | None = None
    # 讲解：给孩子看的"为什么是这个答案"。与 rubric_json 分开存，因为 rubric
    # 是阅卷口径且有"永不出服务端"的硬不变量；讲解本来就是要给人看的，只是
    # 要等全部提交之后。explanation_source 记权威性：publisher_official 是
    # 出版社原文，authored 是自撰，derived 是从推导答案倒推的（最不可信）。
    explanation: str | None = None
    explanation_source: str | None = None

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
