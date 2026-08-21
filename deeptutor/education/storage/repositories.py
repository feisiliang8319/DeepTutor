"""Repositories covering P0's actual read/write paths.

Deliberately not a generic ORM: each method exists because
``application/record_attempt.py``, ``application/rebuild_mastery.py``,
``application/select_objective.py``, or the test matrix in
P0-DESIGN.md §6 needs exactly that operation. Every multi-row write that
must be all-or-nothing (imports) wraps itself in
``deeptutor.education.storage.sqlite.transaction``; single-row writes rely
on SQLite's own atomicity for the one statement.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
import json
import sqlite3

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
    Enrollment,
    LearnerProfile,
    MasterySnapshot,
    ReviewState,
)
from deeptutor.education.storage.sqlite import transaction

# CC-family licenses require attribution; anything else in license_note is
# left alone (P0-DESIGN.md §2.4 fail-closed rule #3, CEMC's CC BY-NC 4.0
# being the motivating case).
_CC_LICENSE_PREFIX = "CC BY"
# The one escape hatch out of the third-party provenance gate below: a row may
# skip licence+attribution only by declaring, in source_ref, that nobody else
# authored it.
_SELF_AUTHORED_PREFIX = "self-authored"


class ImportRejected(ValueError):
    """A batch import was rejected before (or, for a DB-level conflict,
    during, with a full rollback of) any row of this batch being written."""


class ExportDenied(PermissionError):
    """An item's ``content_scope`` forbids the requested export/publish
    operation (P0-DESIGN.md §2.4)."""


class NotFound(LookupError):
    """A referenced row (learner/course_version/node/item) does not exist."""


# ---------------------------------------------------------------------------
# learner_profiles
# ---------------------------------------------------------------------------


def _row_to_learner(row: sqlite3.Row) -> LearnerProfile:
    return LearnerProfile(
        id=row["id"],
        deep_tutor_user_id=row["deep_tutor_user_id"],
        display_name=row["display_name"],
        grade_band=row["grade_band"],
        locale=row["locale"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


class LearnerRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def create(self, profile: LearnerProfile) -> None:
        self._conn.execute(
            """
            INSERT INTO learner_profiles
                (id, deep_tutor_user_id, display_name, grade_band, locale, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                profile.id,
                profile.deep_tutor_user_id,
                profile.display_name,
                profile.grade_band,
                profile.locale,
                profile.created_at,
                profile.updated_at,
            ),
        )

    def get(self, learner_id: str) -> LearnerProfile | None:
        row = self._conn.execute(
            "SELECT * FROM learner_profiles WHERE id = ?", (learner_id,)
        ).fetchone()
        return _row_to_learner(row) if row is not None else None


# ---------------------------------------------------------------------------
# courses / course_versions
# ---------------------------------------------------------------------------


def _row_to_course(row: sqlite3.Row) -> Course:
    return Course(
        id=row["id"],
        subject_key=row["subject_key"],
        title=row["title"],
        created_at=row["created_at"],
        level=row["level"],
    )


def _row_to_course_version(row: sqlite3.Row) -> CourseVersion:
    return CourseVersion(
        id=row["id"],
        course_id=row["course_id"],
        version=row["version"],
        content_hash=row["content_hash"],
        status=CourseVersionStatus(row["status"]),
        created_at=row["created_at"],
    )


def _row_to_enrollment(row: sqlite3.Row) -> Enrollment:
    return Enrollment(
        learner_id=row["learner_id"],
        course_version_id=row["course_version_id"],
        status=row["status"],
        enrolled_at=row["enrolled_at"],
        updated_at=row["updated_at"],
    )


class EnrollmentRepository:
    """选课名册。学生 ↔ 课程版本的多对多关系，内容表一概不参与。"""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def enroll(self, enrollment: Enrollment) -> None:
        """幂等：重复选同一门课把它改回 active，而不是报错或插重复行。

        退选再选回来是正常操作，作答记录一直都在（enrollment 行不是它们的
        载体），所以复选不该丢任何东西。
        """
        self._conn.execute(
            """
            INSERT INTO enrollments
                (learner_id, course_version_id, status, enrolled_at, updated_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(learner_id, course_version_id) DO UPDATE SET
                status = excluded.status,
                updated_at = excluded.updated_at
            """,
            (
                enrollment.learner_id,
                enrollment.course_version_id,
                enrollment.status,
                enrollment.enrolled_at,
                enrollment.updated_at,
            ),
        )

    def set_status(self, learner_id: str, course_version_id: str, status: str, *, at: str) -> None:
        self._conn.execute(
            """
            UPDATE enrollments SET status = ?, updated_at = ?
            WHERE learner_id = ? AND course_version_id = ?
            """,
            (status, at, learner_id, course_version_id),
        )

    def list_for_learner(self, learner_id: str, *, active_only: bool = True) -> list[Enrollment]:
        query = "SELECT * FROM enrollments WHERE learner_id = ?"
        params: list[object] = [learner_id]
        if active_only:
            query += " AND status = 'active'"
        query += " ORDER BY enrolled_at ASC, course_version_id ASC"
        return [_row_to_enrollment(r) for r in self._conn.execute(query, params).fetchall()]

    def list_learners(self, course_version_id: str, *, active_only: bool = True) -> list[str]:
        query = "SELECT learner_id FROM enrollments WHERE course_version_id = ?"
        params: list[object] = [course_version_id]
        if active_only:
            query += " AND status = 'active'"
        query += " ORDER BY learner_id ASC"
        return [r["learner_id"] for r in self._conn.execute(query, params).fetchall()]

    def is_enrolled(self, learner_id: str, course_version_id: str) -> bool:
        row = self._conn.execute(
            "SELECT 1 FROM enrollments WHERE learner_id = ? AND course_version_id = ? "
            "AND status = 'active'",
            (learner_id, course_version_id),
        ).fetchone()
        return row is not None


class CourseRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def create_course(self, course: Course) -> None:
        if not (course.level or "").strip():
            # 数据库列可空（迁移 003 无法给已有行加 NOT NULL），所以由写入层
            # 把关。留空的课进不了目录查询——它会成为一门"存在但谁也拉不到"
            # 的课，且这个后果要等到有人按 (subject, level) 找不到它时才暴露。
            raise ImportRejected(
                f"course {course.id!r} 缺 level：课程目录按 (subject_key, level) 查询，"
                "留空的课无法被拉取。数学四年级写 'G4'，AP 高中线写 'AP-HS'。"
            )
        self._conn.execute(
            "INSERT INTO courses (id, subject_key, title, created_at, level) VALUES (?, ?, ?, ?, ?)",
            (course.id, course.subject_key, course.title, course.created_at, course.level),
        )

    def create_course_version(self, version: CourseVersion) -> None:
        self._conn.execute(
            """
            INSERT INTO course_versions (id, course_id, version, content_hash, status, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                version.id,
                version.course_id,
                version.version,
                version.content_hash,
                version.status.value,
                version.created_at,
            ),
        )

    def get_course(self, course_id: str) -> Course | None:
        row = self._conn.execute("SELECT * FROM courses WHERE id = ?", (course_id,)).fetchone()
        return _row_to_course(row) if row is not None else None

    def get_course_version(self, version_id: str) -> CourseVersion | None:
        row = self._conn.execute(
            "SELECT * FROM course_versions WHERE id = ?", (version_id,)
        ).fetchone()
        return _row_to_course_version(row) if row is not None else None

    def find_courses(self, *, subject_key: str, level: str | None = None) -> list[Course]:
        """课程目录查询：按学科（可再按等级）列出课程。

        这是"根据学科类别去拉取对应的年级或等级"的读路径。刻意不接
        ``learner_id``——内容拉取只由 (学科, 等级) 决定，学生是谁不参与；
        一旦这里出现按人过滤，课程目录就退化成了每人一份的绑定关系。
        """
        query = "SELECT * FROM courses WHERE subject_key = ?"
        params: list[object] = [subject_key]
        if level is not None:
            query += " AND level = ?"
            params.append(level)
        query += " ORDER BY level IS NULL, level ASC, id ASC"
        return [_row_to_course(row) for row in self._conn.execute(query, params).fetchall()]

    def find_active_version(self, *, subject_key: str, level: str) -> CourseVersion | None:
        """(学科, 等级) → 当前 active 的课程版本，找不到返回 None。

        一门课同时最多一个 active 版本是既有约定（course_versions.status），
        这里不替它兜底成"随便挑一个"：真出现两个 active 是数据错误，宁可让
        调用方拿到第一个后在别处炸出来，也不静默选一个看起来对的。
        """
        row = self._conn.execute(
            """
            SELECT cv.* FROM course_versions AS cv
            JOIN courses AS c ON c.id = cv.course_id
            WHERE c.subject_key = ? AND c.level = ? AND cv.status = 'active'
            ORDER BY cv.created_at DESC, cv.id ASC
            """,
            (subject_key, level),
        ).fetchone()
        return _row_to_course_version(row) if row is not None else None


# ---------------------------------------------------------------------------
# knowledge_nodes / knowledge_edges
# ---------------------------------------------------------------------------


def _row_to_node(row: sqlite3.Row) -> KnowledgeNode:
    return KnowledgeNode(
        id=row["id"],
        course_version_id=row["course_version_id"],
        code=row["code"],
        node_type=row["node_type"],
        title=row["title"],
        sort_order=row["sort_order"],
        standard_code=row["standard_code"],
    )


def _row_to_edge(row: sqlite3.Row) -> KnowledgeEdge:
    return KnowledgeEdge(
        course_version_id=row["course_version_id"],
        from_node_id=row["from_node_id"],
        to_node_id=row["to_node_id"],
        edge_type=EdgeType(row["edge_type"]),
    )


def _detect_cycle(node_ids: set[str], edges: Sequence[KnowledgeEdge]) -> list[str]:
    """Kahn's-algorithm topological sort over *all* edge types combined for
    one course_version. Returns the (sorted) node ids still involved in a
    cycle, or an empty list if the graph is a DAG.

    P0-DESIGN.md §2.3 requires cycle detection "in the import transaction,
    via topological sort" without scoping it to PREREQUISITE edges only, so
    this checks the combined graph — a cycle in any relation type on the
    same knowledge graph is equally suspicious for a P0 that only has two
    small hand-built fixtures.
    """
    adjacency: dict[str, set[str]] = {nid: set() for nid in node_ids}
    indegree: dict[str, int] = {nid: 0 for nid in node_ids}
    for edge in edges:
        if edge.to_node_id not in adjacency[edge.from_node_id]:
            adjacency[edge.from_node_id].add(edge.to_node_id)
            indegree[edge.to_node_id] += 1
    queue = [nid for nid, degree in indegree.items() if degree == 0]
    visited = 0
    work = dict(indegree)
    while queue:
        current = queue.pop()
        visited += 1
        for nxt in adjacency[current]:
            work[nxt] -= 1
            if work[nxt] == 0:
                queue.append(nxt)
    if visited == len(node_ids):
        return []
    return sorted(nid for nid, degree in work.items() if degree > 0)


def _reject_unknown_endpoints(edges: Sequence[KnowledgeEdge], known_ids: set[str]) -> None:
    """Every edge endpoint must resolve to a node the import can see.

    ``known_ids`` is the batch's own nodes for a fresh import, and the batch
    plus the stored nodes for an incremental one — the check itself does not
    change, only what counts as "known".
    """
    for edge in edges:
        if edge.from_node_id not in known_ids or edge.to_node_id not in known_ids:
            raise ImportRejected(
                f"edge references an unknown node outside this import batch: "
                f"{edge.from_node_id!r} -> {edge.to_node_id!r}"
            )


def _reject_dangling_stored_edges(
    stored_edges: Sequence[KnowledgeEdge], known_ids: set[str]
) -> None:
    """Refuse to extend a graph whose own stored edges do not resolve."""
    for edge in stored_edges:
        if edge.from_node_id not in known_ids or edge.to_node_id not in known_ids:
            raise ImportRejected(
                f"stored edge {edge.from_node_id!r} -> {edge.to_node_id!r} points outside "
                f"this course_version's nodes; the existing graph is inconsistent and "
                f"cannot be extended safely"
            )


def _reject_cycle(node_ids: set[str], edges: Sequence[KnowledgeEdge]) -> None:
    cyclic = _detect_cycle(node_ids, edges)
    if cyclic:
        raise ImportRejected(f"cycle detected in knowledge graph, involving nodes: {cyclic}")


class KnowledgeGraphRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def import_nodes_and_edges(
        self,
        *,
        course_version_id: str,
        nodes: Sequence[KnowledgeNode],
        edges: Sequence[KnowledgeEdge],
        allow_existing_nodes: bool = False,
    ) -> None:
        """All-or-nothing import of one course_version's knowledge graph.

        Validates self-edge / duplicate-in-batch / unknown-node / cycle
        *before* touching the database (all information needed is in the
        Python objects already), then writes everything inside one
        transaction so a DB-level conflict (e.g. re-importing a node code
        that collides with a pre-existing row) rolls back cleanly too.

        ``allow_existing_nodes`` switches on the *incremental* import mode.
        The default (False) is the original build-a-fresh-graph contract:
        every edge endpoint must be a node in this very batch. That is right
        when the batch *is* the whole graph, but it rejects every legitimate
        "new node depends on a node the DB already has" edge, which is what
        adding a topic to a live graph looks like — and rebuilding the DB
        instead is not an option once real attempt rows exist.

        Turning it on relaxes exactly one thing — an endpoint may resolve to
        a node already stored under this course_version — and *tightens*
        another: cycle detection then runs over the union of the stored edges
        and this batch's edges. It has to. A cycle can be formed by new edges
        closing a path through old ones (DB has A->B; batch adds B->C and
        C->A), and no per-batch check can see it. Missing that would put a
        cycle into the knowledge graph, which ``select_objective`` walks
        assuming a DAG.

        Deliberately not offered as a caller-supplied ``existing_node_ids``
        list: the set is read from the DB inside the same ``BEGIN IMMEDIATE``
        transaction that does the writing, so a caller cannot widen it by
        passing ids that are not really there, and nothing can slip in
        between the check and the insert.
        """
        node_ids = {node.id for node in nodes}
        for node in nodes:
            if node.course_version_id != course_version_id:
                raise ImportRejected(
                    f"node {node.id!r} belongs to course_version "
                    f"{node.course_version_id!r}, not the batch's {course_version_id!r}"
                )

        seen_edges: set[tuple[str, str, str]] = set()
        for edge in edges:
            if edge.course_version_id != course_version_id:
                raise ImportRejected(
                    f"edge {edge.from_node_id!r}->{edge.to_node_id!r} belongs to a "
                    f"different course_version than this batch"
                )
            # KnowledgeEdge.__post_init__ already rejects self-edges at
            # construction time; this is a defensive second check so the
            # repository's own error type/message is consistent for callers
            # that build edges some other way.
            if edge.from_node_id == edge.to_node_id:
                raise ImportRejected(f"self-edge rejected: node {edge.from_node_id!r}")
            key = (edge.from_node_id, edge.to_node_id, edge.edge_type.value)
            if key in seen_edges:
                raise ImportRejected(f"duplicate edge in import batch: {key}")
            seen_edges.add(key)

        if not allow_existing_nodes:
            _reject_unknown_endpoints(edges, node_ids)
            _reject_cycle(node_ids, edges)
            with transaction(self._conn):
                self._write_batch(nodes, edges)
            return

        with transaction(self._conn):
            known_ids = node_ids | {node.id for node in self.list_nodes(course_version_id)}
            stored_edges = self.list_all_edges(course_version_id)
            _reject_unknown_endpoints(edges, known_ids)
            # The stored edges are about to be fed to the cycle check, which
            # indexes nodes by id and would raise a bare KeyError on an edge
            # pointing outside this course_version's node set. That can only
            # happen if the graph is already inconsistent — knowledge_edges'
            # FK is on knowledge_nodes(id) alone and does not constrain the
            # node to share the edge's course_version — so say so instead of
            # crashing with a stack trace, and refuse the import either way.
            _reject_dangling_stored_edges(stored_edges, known_ids)
            _reject_cycle(known_ids, [*stored_edges, *edges])
            self._write_batch(nodes, edges)

    def _write_batch(
        self, nodes: Sequence[KnowledgeNode], edges: Sequence[KnowledgeEdge]
    ) -> None:
        """Insert one already-validated batch. Caller owns the transaction."""
        for node in nodes:
            try:
                self._conn.execute(
                    """
                    INSERT INTO knowledge_nodes
                        (id, course_version_id, code, node_type, title, sort_order,
                         standard_code)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        node.id,
                        node.course_version_id,
                        node.code,
                        node.node_type,
                        node.title,
                        node.sort_order,
                        node.standard_code,
                    ),
                )
            except sqlite3.IntegrityError as exc:
                raise ImportRejected(f"node {node.id!r} conflicts with existing data: {exc}") from exc
        for edge in edges:
            try:
                self._conn.execute(
                    """
                    INSERT INTO knowledge_edges
                        (course_version_id, from_node_id, to_node_id, edge_type)
                    VALUES (?, ?, ?, ?)
                    """,
                    (edge.course_version_id, edge.from_node_id, edge.to_node_id, edge.edge_type.value),
                )
            except sqlite3.IntegrityError as exc:
                raise ImportRejected(
                    f"edge {edge.from_node_id!r}->{edge.to_node_id!r} conflicts with "
                    f"existing data: {exc}"
                ) from exc

    def get_node(self, node_id: str) -> KnowledgeNode | None:
        row = self._conn.execute("SELECT * FROM knowledge_nodes WHERE id = ?", (node_id,)).fetchone()
        return _row_to_node(row) if row is not None else None

    def list_nodes(self, course_version_id: str) -> list[KnowledgeNode]:
        rows = self._conn.execute(
            "SELECT * FROM knowledge_nodes WHERE course_version_id = ? ORDER BY sort_order ASC",
            (course_version_id,),
        ).fetchall()
        return [_row_to_node(row) for row in rows]

    def list_prerequisite_edges(self, course_version_id: str) -> list[KnowledgeEdge]:
        rows = self._conn.execute(
            "SELECT * FROM knowledge_edges WHERE course_version_id = ? AND edge_type = ?",
            (course_version_id, EdgeType.PREREQUISITE.value),
        ).fetchall()
        return [_row_to_edge(row) for row in rows]

    def list_all_edges(self, course_version_id: str) -> list[KnowledgeEdge]:
        rows = self._conn.execute(
            "SELECT * FROM knowledge_edges WHERE course_version_id = ?",
            (course_version_id,),
        ).fetchall()
        return [_row_to_edge(row) for row in rows]


# ---------------------------------------------------------------------------
# assessment_items
# ---------------------------------------------------------------------------


def _row_to_item(row: sqlite3.Row) -> AssessmentItem:
    return AssessmentItem(
        id=row["id"],
        course_version_id=row["course_version_id"],
        knowledge_node_id=row["knowledge_node_id"],
        item_type=ItemType(row["item_type"]),
        prompt=row["prompt"],
        expected_answer=row["expected_answer"],
        rubric_json=row["rubric_json"],
        difficulty=row["difficulty"],
        content_scope=ContentScope(row["content_scope"]),
        source_ref=row["source_ref"],
        license_note=row["license_note"],
        attribution_text=row["attribution_text"],
        derived_from_item_id=row["derived_from_item_id"],
        reviewer=row["reviewer"],
        reviewed_at=row["reviewed_at"],
        content_hash=row["content_hash"],
        status=ItemStatus(row["status"]),
        figure_spec_id=row["figure_spec_id"],
        choices_json=row["choices_json"],
        explanation=row["explanation"],
        explanation_source=row["explanation_source"],
    )


_EXPLANATION_SOURCES = {"publisher_official", "authored", "derived"}

# 选项对象里出现这些键，一律拒收：它们就是 expected_answer 换个名字送到浏览器。
# 选择题的选项必须**送到孩子面前**才能作答，所以 choices_json 在
# ``_ITEM_PUBLIC_FIELDS`` 白名单里；正因为它必然出网线，"哪个是对的"绝不能
# 藏在里面。这是本次新增字段带来的新泄漏面，靠 import 闸门堵死而非靠自觉。
_FORBIDDEN_CHOICE_KEYS = {
    "is_correct", "correct", "answer", "expected", "expected_answer",
    "score", "points", "rubric", "explanation", "why", "rationale", "solution",
}


def _validate_choices(item_id: str, item_type: ItemType, raw: object) -> str | None:
    if raw is None:
        if item_type is ItemType.CHOICE:
            raise ImportRejected(
                f"item {item_id!r}: choice 题必须带 choices_json —— 否则前端只能"
                "把选项当散文渲染，孩子仍得手打字母"
            )
        return None
    if item_type is not ItemType.CHOICE:
        raise ImportRejected(f"item {item_id!r}: 非 choice 题不得带 choices_json")

    text = raw if isinstance(raw, str) else json.dumps(raw, ensure_ascii=False)
    try:
        parsed = json.loads(text)
    except (TypeError, ValueError) as exc:
        raise ImportRejected(f"item {item_id!r}: choices_json 不是合法 JSON: {exc}") from exc
    if not isinstance(parsed, list) or len(parsed) < 2:
        raise ImportRejected(f"item {item_id!r}: choices_json 必须是至少 2 项的数组")

    labels = []
    for entry in parsed:
        if not isinstance(entry, dict):
            raise ImportRejected(f"item {item_id!r}: 选项必须是对象 {{label, text}}")
        leaked = sorted(_FORBIDDEN_CHOICE_KEYS & {str(k).lower() for k in entry})
        if leaked:
            raise ImportRejected(
                f"item {item_id!r}: 选项里带了 {leaked} —— 选项必然要送到孩子的浏览器，"
                "任何指向正确答案的字段都等于泄题"
            )
        label, choice_text = entry.get("label"), entry.get("text")
        if not isinstance(label, str) or not label.strip():
            raise ImportRejected(f"item {item_id!r}: 选项缺 label")
        if not isinstance(choice_text, str) or not choice_text.strip():
            raise ImportRejected(f"item {item_id!r}: 选项 {label!r} 缺 text")
        labels.append(label.strip())
    if len(set(labels)) != len(labels):
        raise ImportRejected(f"item {item_id!r}: 选项 label 重复: {labels}")
    return json.dumps(parsed, ensure_ascii=False)


def _validate_item_row(row: Mapping[str, object]) -> AssessmentItem:
    """Parse+validate one raw import row into an ``AssessmentItem``,
    applying every P0-DESIGN.md §2.4 fail-closed rule. Raises
    ``ImportRejected`` on the first violation; never returns a partially
    valid object.
    """
    item_id = str(row.get("id") or "")
    raw_scope = row.get("content_scope")
    if raw_scope is None or str(raw_scope).strip() == "":
        raise ImportRejected(f"item {item_id!r} is missing content_scope")
    try:
        content_scope = ContentScope(raw_scope)
    except ValueError as exc:
        raise ImportRejected(f"item {item_id!r} has an unknown content_scope {raw_scope!r}") from exc

    if content_scope is ContentScope.RESTRICTED:
        raise ImportRejected(f"item {item_id!r}: RESTRICTED content_scope cannot be imported")

    license_note = row.get("license_note")
    attribution_text = row.get("attribution_text")
    has_attribution = isinstance(attribution_text, str) and bool(attribution_text.strip())
    is_cc_licensed = isinstance(license_note, str) and license_note.upper().startswith(_CC_LICENSE_PREFIX)
    if content_scope is ContentScope.BUNDLED and is_cc_licensed:
        if not has_attribution:
            raise ImportRejected(
                f"item {item_id!r}: BUNDLED with a CC license ({license_note!r}) requires "
                "attribution_text; missing attribution loses the license's protection"
            )

    item_type = ItemType(row["item_type"])
    prompt = row.get("prompt")
    expected_answer = row.get("expected_answer")
    if item_type is ItemType.PAPER_REF:
        if content_scope is not ContentScope.REFERENCE_ONLY:
            raise ImportRejected(
                f"item {item_id!r}: paper_ref items must use content_scope=REFERENCE_ONLY"
            )
        if prompt or expected_answer:
            raise ImportRejected(
                f"item {item_id!r}: paper_ref items must not store prompt/expected_answer text "
                "(P0-DESIGN.md §2.4.1 — the physical book is the only copy of the question)"
            )

    # Third-party provenance gate. The CC check above only fires when the row
    # *says* "CC ..." — so mislabelling the licence (or leaving it blank) used
    # to walk third-party content straight past attribution. Fail closed on
    # provenance instead of on the licence string: any BUNDLED row that names
    # an external source must carry both a licence and an attribution, and the
    # only way out is to declare the item self-authored explicitly.
    # Runs after the paper_ref rules so those keep reporting their own, more
    # specific reason (a paper_ref row is REFERENCE_ONLY and never lands here).
    if content_scope is ContentScope.BUNDLED:
        source_ref = row.get("source_ref")
        names_a_source = isinstance(source_ref, str) and bool(source_ref.strip())
        is_self_authored = names_a_source and source_ref.strip().lower().startswith(
            _SELF_AUTHORED_PREFIX
        )
        if names_a_source and not is_self_authored:
            has_licence = isinstance(license_note, str) and bool(license_note.strip())
            if not (has_licence and has_attribution):
                raise ImportRejected(
                    f"item {item_id!r}: BUNDLED item cites a third-party source_ref "
                    f"({source_ref!r}) but is missing "
                    f"{'license_note' if not has_licence else 'attribution_text'}; "
                    f"declare it self-authored (source_ref starting with "
                    f"{_SELF_AUTHORED_PREFIX!r}) if it has no external provenance"
                )

    choices_json = _validate_choices(item_id, item_type, row.get("choices_json"))

    explanation_source = row.get("explanation_source")
    if explanation_source is not None and explanation_source not in _EXPLANATION_SOURCES:
        raise ImportRejected(
            f"item {item_id!r}: explanation_source={explanation_source!r} 不在 "
            f"{sorted(_EXPLANATION_SOURCES)} 内"
        )
    if row.get("explanation") and explanation_source is None:
        raise ImportRejected(
            f"item {item_id!r}: 有讲解就必须写 explanation_source —— "
            "「这段讲解权威不权威」直接决定家长该不该信它，不许留空"
        )

    return AssessmentItem(
        id=item_id,
        course_version_id=str(row["course_version_id"]),
        knowledge_node_id=str(row["knowledge_node_id"]),
        item_type=item_type,
        prompt=prompt,
        expected_answer=expected_answer,
        rubric_json=row.get("rubric_json"),
        difficulty=int(row["difficulty"]),
        content_scope=content_scope,
        source_ref=row.get("source_ref"),
        license_note=license_note,
        attribution_text=attribution_text,
        derived_from_item_id=row.get("derived_from_item_id"),
        reviewer=row.get("reviewer"),
        reviewed_at=row.get("reviewed_at"),
        content_hash=str(row["content_hash"]),
        status=ItemStatus(row.get("status", "candidate")),
        figure_spec_id=row.get("figure_spec_id"),
        choices_json=choices_json,
        explanation=row.get("explanation"),
        explanation_source=explanation_source,
    )


class AssessmentItemRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def import_items(self, rows: Sequence[Mapping[str, object]]) -> list[AssessmentItem]:
        """Validate every row in the batch, then write all-or-nothing.

        This is the "loader" half of P0-DESIGN.md §2.4's two-layer
        fail-closed rule (the other half, export, is ``export_items``
        below). A single bad row rejects the whole batch — nothing from a
        rejected batch is ever partially imported.
        """
        items = [_validate_item_row(row) for row in rows]
        with transaction(self._conn):
            for item in items:
                self._insert(item)
        return items

    def _insert(self, item: AssessmentItem) -> None:
        try:
            self._conn.execute(
                """
                INSERT INTO assessment_items (
                    id, course_version_id, knowledge_node_id, item_type, prompt,
                    expected_answer, rubric_json, difficulty, content_scope, source_ref,
                    license_note, attribution_text, derived_from_item_id, reviewer,
                    reviewed_at, content_hash, status, figure_spec_id,
                    choices_json, explanation, explanation_source
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    item.id,
                    item.course_version_id,
                    item.knowledge_node_id,
                    item.item_type.value,
                    item.prompt,
                    item.expected_answer,
                    item.rubric_json,
                    item.difficulty,
                    item.content_scope.value,
                    item.source_ref,
                    item.license_note,
                    item.attribution_text,
                    item.derived_from_item_id,
                    item.reviewer,
                    item.reviewed_at,
                    item.content_hash,
                    item.status.value,
                    item.figure_spec_id,
                    item.choices_json,
                    item.explanation,
                    item.explanation_source,
                ),
            )
        except sqlite3.IntegrityError as exc:
            raise ImportRejected(f"item {item.id!r} conflicts with existing data: {exc}") from exc

    def get(self, item_id: str) -> AssessmentItem | None:
        row = self._conn.execute("SELECT * FROM assessment_items WHERE id = ?", (item_id,)).fetchone()
        return _row_to_item(row) if row is not None else None

    def list_for_version(self, course_version_id: str) -> list[AssessmentItem]:
        rows = self._conn.execute(
            "SELECT * FROM assessment_items WHERE course_version_id = ?",
            (course_version_id,),
        ).fetchall()
        return [_row_to_item(row) for row in rows]

    def export_items(self, item_ids: Iterable[str]) -> list[AssessmentItem]:
        """Fail-closed export gate: only ``BUNDLED`` items may leave the
        family's own database (P0-DESIGN.md §2.4 — everything else is
        either purchased-content, a book-index pointer, or unvetted).
        Checks every requested item before returning any of them.
        """
        items: list[AssessmentItem] = []
        for item_id in item_ids:
            item = self.get(item_id)
            if item is None:
                raise NotFound(f"assessment_item {item_id!r} does not exist")
            if item.content_scope is not ContentScope.BUNDLED:
                raise ExportDenied(
                    f"item {item.id!r} has content_scope={item.content_scope.value}, "
                    "which may not be exported"
                )
            items.append(item)
        return items


# ---------------------------------------------------------------------------
# student_attempts
# ---------------------------------------------------------------------------


def _row_to_attempt(row: sqlite3.Row) -> StudentAttempt:
    is_correct = row["is_correct"]
    return StudentAttempt(
        id=row["id"],
        learner_id=row["learner_id"],
        assessment_item_id=row["assessment_item_id"],
        knowledge_node_id=row["knowledge_node_id"],
        course_version_id=row["course_version_id"],
        response=row["response"],
        is_correct=None if is_correct is None else bool(is_correct),
        score=row["score"],
        started_at=row["started_at"],
        submitted_at=row["submitted_at"],
        duration_ms=row["duration_ms"],
        hint_count=row["hint_count"],
        retry_index=row["retry_index"],
        grader_version=row["grader_version"],
        source=row["source"],
        provenance=Provenance(row["provenance"]),
        evidence_strength=EvidenceStrength(row["evidence_strength"]),
        created_at=row["created_at"],
    )


class AttemptRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def insert(self, attempt: StudentAttempt) -> bool:
        """Insert one attempt. Uses ``INSERT OR IGNORE`` keyed on the
        primary key only, so a caller that (re)submits the exact same
        ``attempt.id`` — e.g. a retried network call after the server's
        response was lost — is idempotent instead of raising: the row is
        written at most once (P0-DESIGN.md §6 test #11). Returns whether
        this call is the one that actually wrote the row.
        """
        cur = self._conn.execute(
            """
            INSERT OR IGNORE INTO student_attempts (
                id, learner_id, assessment_item_id, knowledge_node_id, course_version_id,
                response, is_correct, score, started_at, submitted_at, duration_ms,
                hint_count, retry_index, grader_version, source, provenance,
                evidence_strength, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                attempt.id,
                attempt.learner_id,
                attempt.assessment_item_id,
                attempt.knowledge_node_id,
                attempt.course_version_id,
                attempt.response,
                None if attempt.is_correct is None else int(attempt.is_correct),
                attempt.score,
                attempt.started_at,
                attempt.submitted_at,
                attempt.duration_ms,
                attempt.hint_count,
                attempt.retry_index,
                attempt.grader_version,
                attempt.source,
                attempt.provenance.value,
                attempt.evidence_strength.value,
                attempt.created_at,
            ),
        )
        return cur.rowcount > 0

    def get(self, attempt_id: str) -> StudentAttempt | None:
        row = self._conn.execute(
            "SELECT * FROM student_attempts WHERE id = ?", (attempt_id,)
        ).fetchone()
        return _row_to_attempt(row) if row is not None else None

    def list_for_node(
        self, learner_id: str, knowledge_node_id: str, *, include_demo: bool = False
    ) -> list[StudentAttempt]:
        """Chronological (``submitted_at`` then insertion order) attempts
        for one learner+node. ``source='demo'`` rows are excluded by
        default — they must never influence mastery (P0-DESIGN.md §2.5).
        """
        query = (
            "SELECT * FROM student_attempts WHERE learner_id = ? AND knowledge_node_id = ?"
        )
        params: list[object] = [learner_id, knowledge_node_id]
        if not include_demo:
            query += " AND source != 'demo'"
        query += " ORDER BY submitted_at ASC, rowid ASC"
        rows = self._conn.execute(query, params).fetchall()
        return [_row_to_attempt(row) for row in rows]

    def count_for_learner(self, learner_id: str) -> int:
        row = self._conn.execute(
            "SELECT COUNT(*) AS n FROM student_attempts WHERE learner_id = ?", (learner_id,)
        ).fetchone()
        return int(row["n"])

    def list_all_node_ids_with_attempts(
        self, learner_id: str, *, course_version_id: str | None = None
    ) -> list[tuple[str, str]]:
        """Distinct (learner_id, knowledge_node_id) pairs that have at
        least one non-demo attempt — the work list for a full rebuild.

        ``course_version_id`` 收口到单门课。多学科同库后（2026-08-15 起数学
        与 AP 世界史并存），不带它就会把另一门课的节点也拖进重算范围。
        """
        query = (
            "SELECT DISTINCT learner_id, knowledge_node_id FROM student_attempts "
            "WHERE learner_id = ? AND source != 'demo'"
        )
        params: list[object] = [learner_id]
        if course_version_id is not None:
            query += " AND course_version_id = ?"
            params.append(course_version_id)
        rows = self._conn.execute(query, params).fetchall()
        return [(row["learner_id"], row["knowledge_node_id"]) for row in rows]

    def list_all_learner_node_pairs(
        self, *, course_version_id: str | None = None
    ) -> list[tuple[str, str]]:
        query = (
            "SELECT DISTINCT learner_id, knowledge_node_id FROM student_attempts "
            "WHERE source != 'demo'"
        )
        params: list[object] = []
        if course_version_id is not None:
            query += " AND course_version_id = ?"
            params.append(course_version_id)
        rows = self._conn.execute(query, params).fetchall()
        return [(row["learner_id"], row["knowledge_node_id"]) for row in rows]


# ---------------------------------------------------------------------------
# judgment_records
# ---------------------------------------------------------------------------


def _row_to_judgment(row: sqlite3.Row) -> JudgmentRecord:
    return JudgmentRecord(
        id=row["id"],
        attempt_id=row["attempt_id"],
        judge_kind=JudgeKind(row["judge_kind"]),
        judge_ref=row["judge_ref"],
        prompt_version=row["prompt_version"],
        rubric_version=row["rubric_version"],
        verdict=Verdict(row["verdict"]),
        confidence=row["confidence"],
        rationale=row["rationale"],
        created_at=row["created_at"],
    )


class JudgmentRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def insert(self, judgment: JudgmentRecord) -> None:
        self._conn.execute(
            """
            INSERT INTO judgment_records (
                id, attempt_id, judge_kind, judge_ref, prompt_version, rubric_version,
                verdict, confidence, rationale, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                judgment.id,
                judgment.attempt_id,
                judgment.judge_kind.value,
                judgment.judge_ref,
                judgment.prompt_version,
                judgment.rubric_version,
                judgment.verdict.value,
                judgment.confidence,
                judgment.rationale,
                judgment.created_at,
            ),
        )

    def list_for_attempt(self, attempt_id: str) -> list[JudgmentRecord]:
        rows = self._conn.execute(
            "SELECT * FROM judgment_records WHERE attempt_id = ? ORDER BY created_at ASC, rowid ASC",
            (attempt_id,),
        ).fetchall()
        return [_row_to_judgment(row) for row in rows]

    def latest_for_attempt(self, attempt_id: str) -> JudgmentRecord | None:
        row = self._conn.execute(
            """
            SELECT * FROM judgment_records WHERE attempt_id = ?
            ORDER BY created_at DESC, rowid DESC LIMIT 1
            """,
            (attempt_id,),
        ).fetchone()
        return _row_to_judgment(row) if row is not None else None

    def list_for_attempts(self, attempt_ids: Sequence[str]) -> list[JudgmentRecord]:
        if not attempt_ids:
            return []
        placeholders = ",".join("?" for _ in attempt_ids)
        rows = self._conn.execute(
            f"SELECT * FROM judgment_records WHERE attempt_id IN ({placeholders}) "  # nosec B608
            "ORDER BY created_at ASC, rowid ASC",
            tuple(attempt_ids),
        ).fetchall()
        return [_row_to_judgment(row) for row in rows]

    def list_needs_review(
        self, *, confidence_floor: float | None = None, course_version_id: str | None = None
    ) -> list[JudgmentRecord]:
        """The human-review queue P0-DESIGN.md §2.6 requires ("进人工复核
        队列"): every attempt whose *most recent* judgment is unresolved —
        an explicit ``verdict='needs_review'``, or (when ``confidence_floor``
        is given) confidence below that floor.

        Only the latest judgment per attempt is considered. Judgments are
        append-only (an old ``needs_review`` is never edited), so this
        recomputes "currently unresolved" from the full history each call
        rather than reading a mutable flag: once a newer judgment settles
        an attempt (e.g. a human verdict appended after the review), that
        attempt stops appearing here even though its old needs_review row
        is still in the table (2026-08-14 audit finding: this method did
        not previously exist — needs_review was written but never queryable).

        ``course_version_id`` 收口到单门课：复核队列是给人看的工作清单，
        多学科同库后（2026-08-15）不收口就会把数学和文科的待复核混成一锅，
        复核者拿到的队列跨学科、无法分派。收口在**取行时**而不是取完再滤，
        否则"最近一条判定"会被另一门课的行影响（同一 attempt 不跨课，但
        全表扫描的成本和语义都没必要背着别的课）。
        """
        query = "SELECT j.* FROM judgment_records AS j"
        params: list[object] = []
        if course_version_id is not None:
            query += (
                " JOIN student_attempts AS a ON a.id = j.attempt_id"
                " WHERE a.course_version_id = ?"
            )
            params.append(course_version_id)
        query += " ORDER BY j.created_at ASC, j.rowid ASC"
        rows = self._conn.execute(query, params).fetchall()
        latest_by_attempt: dict[str, JudgmentRecord] = {}
        for row in rows:
            judgment = _row_to_judgment(row)
            # Ascending order means the last write for a given attempt_id
            # is the most recent judgment — same pattern as
            # rebuild_mastery.compute_node_mastery's latest-judgment lookup.
            latest_by_attempt[judgment.attempt_id] = judgment

        unresolved = [
            judgment
            for judgment in latest_by_attempt.values()
            if judgment.verdict is Verdict.NEEDS_REVIEW
            or (
                confidence_floor is not None
                and judgment.confidence is not None
                and judgment.confidence < confidence_floor
            )
        ]
        unresolved.sort(key=lambda judgment: judgment.created_at)
        return unresolved


# ---------------------------------------------------------------------------
# mastery_snapshots
# ---------------------------------------------------------------------------


def _row_to_snapshot(row: sqlite3.Row) -> MasterySnapshot:
    return MasterySnapshot(
        learner_id=row["learner_id"],
        knowledge_node_id=row["knowledge_node_id"],
        score=row["score"],
        status=row["status"],
        confidence=row["confidence"],
        policy_version=row["policy_version"],
        last_attempt_id=row["last_attempt_id"],
        evidence_watermark=row["evidence_watermark"],
        updated_at=row["updated_at"],
    )


class MasterySnapshotRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def upsert(self, snapshot: MasterySnapshot) -> None:
        self._conn.execute(
            """
            INSERT INTO mastery_snapshots (
                learner_id, knowledge_node_id, score, status, confidence,
                policy_version, last_attempt_id, evidence_watermark, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (learner_id, knowledge_node_id) DO UPDATE SET
                score = excluded.score,
                status = excluded.status,
                confidence = excluded.confidence,
                policy_version = excluded.policy_version,
                last_attempt_id = excluded.last_attempt_id,
                evidence_watermark = excluded.evidence_watermark,
                updated_at = excluded.updated_at
            """,
            (
                snapshot.learner_id,
                snapshot.knowledge_node_id,
                snapshot.score,
                snapshot.status,
                snapshot.confidence,
                snapshot.policy_version,
                snapshot.last_attempt_id,
                snapshot.evidence_watermark,
                snapshot.updated_at,
            ),
        )

    def get(self, learner_id: str, knowledge_node_id: str) -> MasterySnapshot | None:
        row = self._conn.execute(
            "SELECT * FROM mastery_snapshots WHERE learner_id = ? AND knowledge_node_id = ?",
            (learner_id, knowledge_node_id),
        ).fetchone()
        return _row_to_snapshot(row) if row is not None else None

    def list_for_learner(self, learner_id: str) -> list[MasterySnapshot]:
        rows = self._conn.execute(
            "SELECT * FROM mastery_snapshots WHERE learner_id = ?", (learner_id,)
        ).fetchall()
        return [_row_to_snapshot(row) for row in rows]

    def delete_all(self) -> int:
        """Used by the rebuild-invariant test: the whole table can be
        dropped and reconstructed from student_attempts + judgment_records
        alone (P0-DESIGN.md §2.7)."""
        cur = self._conn.execute("DELETE FROM mastery_snapshots")
        return cur.rowcount

    def list_pending_recompute(self, *, learner_id: str | None = None) -> list[MasterySnapshot]:
        """The backlog for ``application.rebuild_mastery.rebuild_learner_node``
        (the idempotent healer): every learner+node snapshot
        ``record_attempt`` flagged ``pending_recompute`` after a step 4-6
        failure (P0-DESIGN.md §3 requires this state to have "主动告警" —
        an active alert — not just a status nobody ever reads back out;
        2026-08-14 audit finding: this method did not previously exist, so
        the status was write-only)."""
        if learner_id is None:
            rows = self._conn.execute(
                "SELECT * FROM mastery_snapshots WHERE status = 'pending_recompute'"
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM mastery_snapshots WHERE status = 'pending_recompute' AND learner_id = ?",
                (learner_id,),
            ).fetchall()
        return [_row_to_snapshot(row) for row in rows]


# ---------------------------------------------------------------------------
# review_states
# ---------------------------------------------------------------------------


def _row_to_review_state(row: sqlite3.Row) -> ReviewState:
    return ReviewState(
        learner_id=row["learner_id"],
        knowledge_node_id=row["knowledge_node_id"],
        stability=row["stability"],
        difficulty=row["difficulty"],
        due_at=row["due_at"],
        last_review_at=row["last_review_at"],
        reps=row["reps"],
        lapses=row["lapses"],
        fsrs_state=row["fsrs_state"],
        fsrs_step=row["fsrs_step"],
        fsrs_params_ver=row["fsrs_params_ver"],
    )


class ReviewStateRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def upsert(self, state: ReviewState) -> None:
        self._conn.execute(
            """
            INSERT INTO review_states (
                learner_id, knowledge_node_id, stability, difficulty, due_at,
                last_review_at, reps, lapses, fsrs_state, fsrs_step, fsrs_params_ver
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (learner_id, knowledge_node_id) DO UPDATE SET
                stability = excluded.stability,
                difficulty = excluded.difficulty,
                due_at = excluded.due_at,
                last_review_at = excluded.last_review_at,
                reps = excluded.reps,
                lapses = excluded.lapses,
                fsrs_state = excluded.fsrs_state,
                fsrs_step = excluded.fsrs_step,
                fsrs_params_ver = excluded.fsrs_params_ver
            """,
            (
                state.learner_id,
                state.knowledge_node_id,
                state.stability,
                state.difficulty,
                state.due_at,
                state.last_review_at,
                state.reps,
                state.lapses,
                state.fsrs_state,
                state.fsrs_step,
                state.fsrs_params_ver,
            ),
        )

    def get(self, learner_id: str, knowledge_node_id: str) -> ReviewState | None:
        row = self._conn.execute(
            "SELECT * FROM review_states WHERE learner_id = ? AND knowledge_node_id = ?",
            (learner_id, knowledge_node_id),
        ).fetchone()
        return _row_to_review_state(row) if row is not None else None


__all__ = [
    "AssessmentItemRepository",
    "AttemptRepository",
    "CourseRepository",
    "ExportDenied",
    "ImportRejected",
    "JudgmentRepository",
    "KnowledgeGraphRepository",
    "LearnerRepository",
    "MasterySnapshotRepository",
    "NotFound",
    "ReviewStateRepository",
]
