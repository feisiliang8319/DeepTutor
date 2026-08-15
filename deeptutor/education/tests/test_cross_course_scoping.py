"""多学科同库后，按学习者全局扫的查询不能把另一门课的行带进来。

2026-08-15 起数学（G4）与 AP 世界史在同一个 education.db 里。三处查询原本
没有课程条件：人工复核队列、两处掌握度重算的工作清单。它们都是"按人扫"，
在单课程时代看不出问题，第二门课一进来就跨课。

收口方向是 **course_version**，不是 learner——内容侧的隔离由课程决定，学生
是谁不参与。
"""

from __future__ import annotations

import time

import pytest

from deeptutor.education.application import to_iso_timestamp
from deeptutor.education.domain.course import (
    Course,
    CourseVersion,
    CourseVersionStatus,
    KnowledgeNode,
)
from deeptutor.education.domain.evidence import JudgeKind, JudgmentRecord, StudentAttempt, Verdict
from deeptutor.education.storage.repositories import (
    AssessmentItemRepository,
    AttemptRepository,
    CourseRepository,
    JudgmentRepository,
    KnowledgeGraphRepository,
)

from .conftest import content_hash


def _now() -> str:
    return to_iso_timestamp(time.time())


def _build_course(conn, *, subject: str, level: str, tag: str):
    """一门课：course + active version + 一个节点 + 一道题。"""
    now = _now()
    repo = CourseRepository(conn)
    repo.create_course(
        Course(id=f"c-{tag}", subject_key=subject, title=tag, created_at=now, level=level)
    )
    version = CourseVersion(
        id=f"cv-{tag}",
        course_id=f"c-{tag}",
        version="1.0.0",
        content_hash=content_hash(tag),
        status=CourseVersionStatus.ACTIVE,
        created_at=now,
    )
    repo.create_course_version(version)

    node = KnowledgeNode(
        id=f"node-{tag}-1",
        course_version_id=version.id,
        code=f"{tag.upper()}.1",
        node_type="concept",
        title=f"{tag} node",
        sort_order=1,
    )
    KnowledgeGraphRepository(conn).import_nodes_and_edges(
        course_version_id=version.id, nodes=[node], edges=[]
    )
    [item] = AssessmentItemRepository(conn).import_items(
        [
            {
                "id": f"item-{tag}-1",
                "course_version_id": version.id,
                "knowledge_node_id": node.id,
                "item_type": "short",
                "prompt": f"{tag} prompt",
                "expected_answer": "x",
                "rubric_json": None,
                "difficulty": 2,
                "content_scope": "BUNDLED",
                "source_ref": None,
                "license_note": None,
                "attribution_text": None,
                "derived_from_item_id": None,
                "reviewer": None,
                "reviewed_at": None,
                "content_hash": content_hash(f"item-{tag}-1"),
                "status": "production",
            }
        ]
    )
    return version, node, item


def _attempt_with_pending_judgment(conn, learner, version, node, item, *, tag: str) -> str:
    now = _now()
    attempt_id = f"att-{tag}"
    AttemptRepository(conn).insert(
        StudentAttempt(
            id=attempt_id,
            learner_id=learner.id,
            assessment_item_id=item.id,
            knowledge_node_id=node.id,
            course_version_id=version.id,
            response="something",
            is_correct=None,
            score=None,
            started_at=now,
            submitted_at=now,
            grader_version="v1",
            source="practice",
            created_at=now,
        )
    )
    JudgmentRepository(conn).insert(
        JudgmentRecord(
            id=f"judg-{tag}",
            attempt_id=attempt_id,
            judge_kind=JudgeKind.LLM,
            judge_ref="test",
            verdict=Verdict.NEEDS_REVIEW,
            created_at=now,
            confidence=0.1,
            rationale="unsure",
        )
    )
    return attempt_id


@pytest.fixture
def two_courses(conn, learner):
    """同一个学生，两门课，各有一条待复核的作答。"""
    math = _build_course(conn, subject="mathematics", level="G4", tag="math")
    hist = _build_course(conn, subject="world_history", level="AP-HS", tag="hist")
    math_attempt = _attempt_with_pending_judgment(conn, learner, *math, tag="math")
    hist_attempt = _attempt_with_pending_judgment(conn, learner, *hist, tag="hist")
    return {
        "math": (math[0], math[1], math_attempt),
        "hist": (hist[0], hist[1], hist_attempt),
    }


def test_review_queue_scopes_to_one_course(conn, two_courses) -> None:
    """复核队列是给人分派的工作清单，跨学科混在一起就没法用。"""
    repo = JudgmentRepository(conn)
    math_cv, _, math_attempt = two_courses["math"]
    hist_cv, _, hist_attempt = two_courses["hist"]

    assert {j.attempt_id for j in repo.list_needs_review()} == {math_attempt, hist_attempt}
    assert [j.attempt_id for j in repo.list_needs_review(course_version_id=math_cv.id)] == [
        math_attempt
    ]
    assert [j.attempt_id for j in repo.list_needs_review(course_version_id=hist_cv.id)] == [
        hist_attempt
    ]


def test_rebuild_worklists_scope_to_one_course(conn, learner, two_courses) -> None:
    """重算掌握度的工作清单不该把另一门课的节点拖进来。"""
    repo = AttemptRepository(conn)
    math_cv, math_node, _ = two_courses["math"]
    hist_cv, hist_node, _ = two_courses["hist"]

    assert {n for _, n in repo.list_all_learner_node_pairs()} == {math_node.id, hist_node.id}
    assert repo.list_all_learner_node_pairs(course_version_id=math_cv.id) == [
        (learner.id, math_node.id)
    ]
    assert repo.list_all_node_ids_with_attempts(learner.id, course_version_id=hist_cv.id) == [
        (learner.id, hist_node.id)
    ]


def test_scoping_is_by_course_not_by_learner(conn, learner, two_courses) -> None:
    """第二个学生选同一门课，课程范围内的结果里必须两个人都在。

    如果哪天有人"顺手"把这些查询按 learner 收口，这条会失败——那正是把内容
    隔离绑回人的那一步。
    """
    from deeptutor.education.domain.learner import LearnerProfile
    from deeptutor.education.storage.repositories import LearnerRepository

    now = _now()
    second = LearnerProfile(
        id="learner-2",
        deep_tutor_user_id="dtu-2",
        display_name="Second",
        locale="en-US",
        created_at=now,
        updated_at=now,
    )
    LearnerRepository(conn).create(second)

    math_cv, math_node, _ = two_courses["math"]
    item = AssessmentItemRepository(conn).list_for_version(math_cv.id)[0]
    AttemptRepository(conn).insert(
        StudentAttempt(
            id="att-math-2",
            learner_id=second.id,
            assessment_item_id=item.id,
            knowledge_node_id=math_node.id,
            course_version_id=math_cv.id,
            response="y",
            is_correct=True,
            score=1.0,
            started_at=now,
            submitted_at=now,
            grader_version="v1",
            source="practice",
            created_at=now,
        )
    )

    pairs = AttemptRepository(conn).list_all_learner_node_pairs(course_version_id=math_cv.id)
    assert sorted(pairs) == sorted([(learner.id, math_node.id), (second.id, math_node.id)])
