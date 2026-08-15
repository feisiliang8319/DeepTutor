"""Destructive-injection test #4 (cyclic graph) and #17 (self-edge /
duplicate / unknown-node, all fail closed), plus fixture-import coverage
for test #18.
"""

from __future__ import annotations

import pytest

from deeptutor.education.domain.course import EdgeType, KnowledgeEdge, KnowledgeNode
from deeptutor.education.storage.repositories import ImportRejected, KnowledgeGraphRepository
from deeptutor.education.tests.fixtures import build_fixture_a_math, build_fixture_b_history


def _node(course_version_id: str, code: str, sort_order: int) -> KnowledgeNode:
    return KnowledgeNode(
        id=f"node-{code}",
        course_version_id=course_version_id,
        code=code,
        node_type="concept",
        title=code,
        sort_order=sort_order,
    )


def _edge(course_version_id: str, from_code: str, to_code: str) -> KnowledgeEdge:
    return KnowledgeEdge(
        course_version_id=course_version_id,
        from_node_id=f"node-{from_code}",
        to_node_id=f"node-{to_code}",
        edge_type=EdgeType.PREREQUISITE,
    )


# ---- test #4: cyclic prerequisite graph -> whole import rejected ----------


def test_cyclic_graph_is_rejected_and_nothing_is_written(conn, course_version):
    cv = course_version.id
    nodes = [_node(cv, "A", 1), _node(cv, "B", 2), _node(cv, "C", 3)]
    edges = [_edge(cv, "A", "B"), _edge(cv, "B", "C"), _edge(cv, "C", "A")]  # A->B->C->A

    with pytest.raises(ImportRejected, match="cycle"):
        KnowledgeGraphRepository(conn).import_nodes_and_edges(
            course_version_id=cv, nodes=nodes, edges=edges
        )

    node_count = conn.execute("SELECT COUNT(*) AS n FROM knowledge_nodes").fetchone()["n"]
    edge_count = conn.execute("SELECT COUNT(*) AS n FROM knowledge_edges").fetchone()["n"]
    assert node_count == 0
    assert edge_count == 0


def test_larger_cycle_through_an_otherwise_valid_dag_is_rejected(conn, course_version):
    cv = course_version.id
    nodes = [_node(cv, code, i) for i, code in enumerate(["A", "B", "C", "D", "E"], start=1)]
    edges = [
        _edge(cv, "A", "B"),
        _edge(cv, "A", "C"),
        _edge(cv, "B", "D"),
        _edge(cv, "C", "D"),
        _edge(cv, "D", "E"),
        _edge(cv, "E", "B"),  # closes a cycle B -> D -> E -> B
    ]
    with pytest.raises(ImportRejected, match="cycle"):
        KnowledgeGraphRepository(conn).import_nodes_and_edges(
            course_version_id=cv, nodes=nodes, edges=edges
        )


# ---- test #17: self-edge / duplicate / unknown node -----------------------


def test_self_edge_rejected_at_domain_construction():
    with pytest.raises(ValueError, match="self-edge"):
        KnowledgeEdge(course_version_id="cv-1", from_node_id="node-A", to_node_id="node-A")


def test_duplicate_edge_in_batch_rejected(conn, course_version):
    cv = course_version.id
    nodes = [_node(cv, "A", 1), _node(cv, "B", 2)]
    edges = [_edge(cv, "A", "B"), _edge(cv, "A", "B")]
    with pytest.raises(ImportRejected, match="duplicate"):
        KnowledgeGraphRepository(conn).import_nodes_and_edges(
            course_version_id=cv, nodes=nodes, edges=edges
        )


def test_duplicate_edge_against_existing_db_rows_rejected_via_primary_key(conn, course_version):
    cv = course_version.id
    nodes = [_node(cv, "A", 1), _node(cv, "B", 2)]
    edges = [_edge(cv, "A", "B")]
    repo = KnowledgeGraphRepository(conn)
    repo.import_nodes_and_edges(course_version_id=cv, nodes=nodes, edges=edges)

    # Re-importing the same nodes conflicts on knowledge_nodes' UNIQUE
    # (course_version_id, code) — the whole second batch must be rejected
    # and roll back, not partially apply.
    with pytest.raises(ImportRejected):
        repo.import_nodes_and_edges(course_version_id=cv, nodes=nodes, edges=edges)


def test_edge_referencing_unknown_node_rejected(conn, course_version):
    cv = course_version.id
    nodes = [_node(cv, "A", 1)]
    edges = [_edge(cv, "A", "GHOST")]
    with pytest.raises(ImportRejected, match="unknown"):
        KnowledgeGraphRepository(conn).import_nodes_and_edges(
            course_version_id=cv, nodes=nodes, edges=edges
        )
    assert conn.execute("SELECT COUNT(*) AS n FROM knowledge_nodes").fetchone()["n"] == 0


# ---- test #18 (import half): both fixtures import cleanly -----------------


def test_fixture_a_math_imports_cleanly(conn, course_version):
    bundle = build_fixture_a_math(course_version.id)
    KnowledgeGraphRepository(conn).import_nodes_and_edges(
        course_version_id=course_version.id, nodes=bundle.nodes, edges=bundle.edges
    )
    assert len(bundle.nodes) == 11
    assert 12 <= len(bundle.edges) <= 16
    stored_nodes = KnowledgeGraphRepository(conn).list_nodes(course_version.id)
    assert len(stored_nodes) == len(bundle.nodes)
    # sort_order is respected end to end.
    assert [n.code for n in stored_nodes] == [n.code for n in sorted(bundle.nodes, key=lambda n: n.sort_order)]


def test_fixture_a_has_the_two_grade3_prerequisite_shape(conn, course_version):
    """The design's explicit requirement: a Grade 4 node reaching back to
    two Grade 3 nodes."""
    bundle = build_fixture_a_math(course_version.id)
    KnowledgeGraphRepository(conn).import_nodes_and_edges(
        course_version_id=course_version.id, nodes=bundle.nodes, edges=bundle.edges
    )
    prereq_edges = KnowledgeGraphRepository(conn).list_prerequisite_edges(course_version.id)
    to_frac_equiv = [e for e in prereq_edges if e.to_node_id == "node-G4.FRAC.EQUIV"]
    assert {e.from_node_id for e in to_frac_equiv} == {"node-G3.FRAC.UNIT", "node-G3.FRAC.COMPARE"}


def test_fixture_b_history_imports_cleanly_with_non_prerequisite_edges(conn):
    import time

    from deeptutor.education.application import to_iso_timestamp
    from deeptutor.education.domain.course import Course, CourseVersion, CourseVersionStatus
    from deeptutor.education.storage.repositories import CourseRepository
    from deeptutor.education.tests.fixtures import content_hash

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
    assert len(bundle.nodes) == 6
    assert 6 <= len(bundle.edges) <= 8
    KnowledgeGraphRepository(conn).import_nodes_and_edges(
        course_version_id=version.id, nodes=bundle.nodes, edges=bundle.edges
    )
    # None of Fixture B's edges are PREREQUISITE — proving the schema
    # accepts and stores non-prerequisite relations without the planner
    # ever seeing them (P0-DESIGN.md §2.3).
    assert KnowledgeGraphRepository(conn).list_prerequisite_edges(version.id) == []
    all_edges = KnowledgeGraphRepository(conn).list_all_edges(version.id)
    assert len(all_edges) == len(bundle.edges)
    edge_types = {e.edge_type for e in all_edges}
    assert edge_types <= {EdgeType.PRECEDES, EdgeType.CAUSES, EdgeType.SUPPORTS}


# ---- standard_code: external curriculum anchor ---------------------------


def _anchored_node(
    course_version_id: str, code: str, sort_order: int, standard_code: str | None
) -> KnowledgeNode:
    return KnowledgeNode(
        id=f"node-{code}",
        course_version_id=course_version_id,
        code=code,
        node_type="concept",
        title=code,
        sort_order=sort_order,
        standard_code=standard_code,
    )


def test_standard_code_round_trips_and_defaults_to_none(conn, course_version):
    cv = course_version.id
    nodes = [
        _anchored_node(cv, "FACTOR_PAIRS", 1, "4.OA.B.4"),
        _node(cv, "SELF_AUTHORED", 2),  # standard_code omitted entirely
    ]
    KnowledgeGraphRepository(conn).import_nodes_and_edges(
        course_version_id=cv, nodes=nodes, edges=[]
    )
    stored = {n.code: n for n in KnowledgeGraphRepository(conn).list_nodes(cv)}
    assert stored["FACTOR_PAIRS"].standard_code == "4.OA.B.4"
    # NULL is a valid end state for an un-anchored node, not a placeholder.
    assert stored["SELF_AUTHORED"].standard_code is None


def test_one_standard_maps_to_many_nodes(conn, course_version):
    """4.OA.B.4 is a single published standard covering three independently
    diagnosable skills — the column must not behave like a unique key."""
    cv = course_version.id
    nodes = [
        _anchored_node(cv, "B4.FACTOR_PAIRS", 1, "4.OA.B.4"),
        _anchored_node(cv, "B4.MULTIPLE_TEST", 2, "4.OA.B.4"),
        _anchored_node(cv, "B4.PRIME_COMPOSITE", 3, "4.OA.B.4"),
        _anchored_node(cv, "C5.GENERATE_PATTERN", 4, "4.OA.C.5"),
    ]
    KnowledgeGraphRepository(conn).import_nodes_and_edges(
        course_version_id=cv, nodes=nodes, edges=[]
    )
    stored = KnowledgeGraphRepository(conn).list_nodes(cv)
    covering = [n.code for n in stored if n.standard_code == "4.OA.B.4"]
    assert covering == ["B4.FACTOR_PAIRS", "B4.MULTIPLE_TEST", "B4.PRIME_COMPOSITE"]
