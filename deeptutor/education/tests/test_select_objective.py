"""select_objective — the deterministic prerequisite planner."""

from __future__ import annotations

import time

from deeptutor.education.application import to_iso_timestamp
from deeptutor.education.application.select_objective import select_next_objective
from deeptutor.education.domain.course import Course, CourseVersion, CourseVersionStatus
from deeptutor.education.domain.learner import MasterySnapshot
from deeptutor.education.storage.repositories import (
    CourseRepository,
    KnowledgeGraphRepository,
    MasterySnapshotRepository,
)
from deeptutor.education.tests.fixtures import (
    build_fixture_a_math,
    build_fixture_b_history,
    content_hash,
)


def _mark_mastered(conn, learner_id, node_id):
    MasterySnapshotRepository(conn).upsert(
        MasterySnapshot(
            learner_id=learner_id,
            knowledge_node_id=node_id,
            score=1.0,
            status="mastered",
            policy_version="test",
            updated_at=to_iso_timestamp(time.time()),
        )
    )


def test_empty_course_version_returns_none(conn, learner, course_version):
    result = select_next_objective(conn, learner.id, course_version.id)
    assert result is None


def test_first_objective_is_the_lowest_sort_order_unblocked_node(conn, learner, course_version):
    bundle = build_fixture_a_math(course_version.id)
    KnowledgeGraphRepository(conn).import_nodes_and_edges(
        course_version_id=course_version.id, nodes=bundle.nodes, edges=bundle.edges
    )
    result = select_next_objective(conn, learner.id, course_version.id)
    assert result is not None
    assert result.node.code == "G3.MULT.BASIC"
    assert result.status == "new"


def test_two_grade3_prerequisites_both_required_before_unlocking(conn, learner, course_version):
    bundle = build_fixture_a_math(course_version.id)
    KnowledgeGraphRepository(conn).import_nodes_and_edges(
        course_version_id=course_version.id, nodes=bundle.nodes, edges=bundle.edges
    )
    # Master everything except the two Grade-3 fraction prerequisites, plus
    # master only one of the two.
    for code in [
        "G3.MULT.BASIC",
        "G3.MULT.MULTIDIGIT",
        "G3.DIV.BASIC",
        "G3.DIV.MULTIDIGIT",
        "G4.MULT.AREA_MODEL",
        "G4.DIV.LONG",
        "G3.FRAC.UNIT",
    ]:
        _mark_mastered(conn, learner.id, f"node-{code}")

    result = select_next_objective(conn, learner.id, course_version.id)
    assert result is not None
    # G4.FRAC.EQUIV must stay blocked: G3.FRAC.COMPARE isn't mastered yet,
    # and G3.FRAC.COMPARE itself isn't blocked (its only prereq, FRAC.UNIT,
    # is mastered) so it should be selected next.
    assert result.node.code == "G3.FRAC.COMPARE"

    _mark_mastered(conn, learner.id, "node-G3.FRAC.COMPARE")
    result2 = select_next_objective(conn, learner.id, course_version.id)
    assert result2 is not None
    assert result2.node.code == "G4.FRAC.EQUIV"


def test_all_mastered_returns_none(conn, learner, course_version):
    bundle = build_fixture_a_math(course_version.id)
    KnowledgeGraphRepository(conn).import_nodes_and_edges(
        course_version_id=course_version.id, nodes=bundle.nodes, edges=bundle.edges
    )
    for node in bundle.nodes:
        _mark_mastered(conn, learner.id, node.id)
    assert select_next_objective(conn, learner.id, course_version.id) is None


def test_selection_is_deterministic_across_repeated_calls(conn, learner, course_version):
    bundle = build_fixture_a_math(course_version.id)
    KnowledgeGraphRepository(conn).import_nodes_and_edges(
        course_version_id=course_version.id, nodes=bundle.nodes, edges=bundle.edges
    )
    first = select_next_objective(conn, learner.id, course_version.id)
    second = select_next_objective(conn, learner.id, course_version.id)
    assert first is not None and second is not None
    assert first.node.id == second.node.id


def test_planner_ignores_non_prerequisite_edges_fixture_b(conn, learner):
    now = to_iso_timestamp(time.time())
    course = Course(id="course-history", subject_key="social_studies", title="Test History", created_at=now)
    version = CourseVersion(
        id="cv-history-1",
        course_id=course.id,
        version="1.0.0",
        content_hash=content_hash("history-v1"),
        status=CourseVersionStatus.ACTIVE,
        created_at=now,
    )
    repo = CourseRepository(conn)
    repo.create_course(course)
    repo.create_course_version(version)

    bundle = build_fixture_b_history(version.id)
    KnowledgeGraphRepository(conn).import_nodes_and_edges(
        course_version_id=version.id, nodes=bundle.nodes, edges=bundle.edges
    )
    # None of Fixture B's edges are PREREQUISITE, so every node is
    # "unblocked" from the planner's point of view — it must fall back to
    # plain sort_order, the first node being whichever has sort_order=1,
    # regardless of the SUPPORTS/PRECEDES/CAUSES edges pointing at or from it.
    result = select_next_objective(conn, learner.id, version.id)
    assert result is not None
    assert result.node.code == "US.EVENT.DECLARATION"
