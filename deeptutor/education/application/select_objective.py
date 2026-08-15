"""select_objective — deterministic prerequisite planner.

P0 scope only (P0-DESIGN.md §2.3): consumes ``PREREQUISITE`` edges
exclusively. ``PRECEDES``/``CAUSES``/``SUPPORTS`` (the US History fixture's
edge types) are stored and schema-validated but never read here — proving
the node/edge schema is not math-specific is the fixture's whole job, not
feeding the planner.

Edge convention: an edge ``(course_version_id, from_node_id, to_node_id,
edge_type=PREREQUISITE)`` means *from_node_id must be mastered before
to_node_id* — ``from`` is the prerequisite, ``to`` is the dependent.
"""

from __future__ import annotations

from dataclasses import dataclass
import sqlite3

from deeptutor.education.domain.course import KnowledgeNode
from deeptutor.education.storage.repositories import (
    KnowledgeGraphRepository,
    MasterySnapshotRepository,
)


@dataclass(frozen=True, slots=True)
class SelectedObjective:
    node: KnowledgeNode
    # The learner's current status for this node ("new" or "learning") —
    # advisory context for the caller's pedagogy, not part of the decision
    # itself (the decision is "first unblocked, not-yet-mastered node in
    # sort_order").
    status: str


def list_available_objectives(
    conn: sqlite3.Connection, learner_id: str, course_version_id: str
) -> list[SelectedObjective]:
    """Every not-yet-mastered node whose prerequisites are all mastered, in
    ``sort_order``. ``select_next_objective`` is the first element of this.

    Exists because a caller may need to look past the head: the web loop
    only serves nodes that actually have an auto-gradable item, so it walks
    this list rather than dead-ending on the first node whose item bank is
    still empty. Keeping that walk out here means "what is unblocked" has
    exactly one implementation.

    Deterministic: a pure function of stored knowledge_nodes /
    knowledge_edges (course content — immutable once a version is active,
    P0-DESIGN.md §2.2) and the learner's current mastery_snapshots. Same
    inputs always produce the same output; no randomness, no wall-clock
    dependence.

    Cycle-freedom is an import-time guarantee (``KnowledgeGraphRepository
    .import_nodes_and_edges`` rejects any cycle before it reaches the
    database — see storage/repositories.py), so this function does not
    re-check for cycles; it assumes a DAG.
    """
    graph = KnowledgeGraphRepository(conn)
    nodes = graph.list_nodes(course_version_id)  # already sorted by sort_order
    if not nodes:
        return []
    edges = graph.list_prerequisite_edges(course_version_id)

    node_ids = {node.id for node in nodes}
    prerequisites_of: dict[str, set[str]] = {node_id: set() for node_id in node_ids}
    for edge in edges:
        if edge.to_node_id in prerequisites_of:
            prerequisites_of[edge.to_node_id].add(edge.from_node_id)

    mastery_by_node = {
        snapshot.knowledge_node_id: snapshot.status
        for snapshot in MasterySnapshotRepository(conn).list_for_learner(learner_id)
    }

    available: list[SelectedObjective] = []
    for node in nodes:
        status = mastery_by_node.get(node.id, "new")
        if status == "mastered":
            continue
        prereq_ids = prerequisites_of.get(node.id, set())
        if all(mastery_by_node.get(prereq_id) == "mastered" for prereq_id in prereq_ids):
            available.append(
                SelectedObjective(node=node, status=status if status in ("new", "learning") else "new")
            )
    return available


def select_next_objective(
    conn: sqlite3.Connection, learner_id: str, course_version_id: str
) -> SelectedObjective | None:
    """The next node the learner should work on, or ``None`` when every
    node in this course_version is mastered.

    Deterministic: a pure function of stored knowledge_nodes /
    knowledge_edges (course content — immutable once a version is active,
    P0-DESIGN.md §2.2) and the learner's current mastery_snapshots. Same
    inputs always produce the same output; no randomness, no wall-clock
    dependence.

    An empty result means everything is mastered: for a valid DAG with a
    non-empty not-yet-mastered set there is always at least one unblocked
    node (a DAG's induced subgraph over any non-empty node set has a node
    with no incoming edge from within that set), and cycle-freedom is
    guaranteed at import time by ``KnowledgeGraphRepository
    .import_nodes_and_edges``.
    """
    available = list_available_objectives(conn, learner_id, course_version_id)
    return available[0] if available else None


__all__ = ["SelectedObjective", "list_available_objectives", "select_next_objective"]
