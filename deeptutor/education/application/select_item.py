"""Pick the next assessment item to put in front of a learner.

Split from ``select_objective`` on purpose: that module answers "which
knowledge node next", which is a function of the graph and mastery only.
This one answers "which question for that node", which additionally
depends on what the learner has already seen — a different input set and a
different reason to change.

Deterministic like its sibling: same database state always yields the same
item (ties break on ``id``), so a reload never reshuffles the question in
front of a child mid-thought.
"""

from __future__ import annotations

from collections.abc import Container
from dataclasses import dataclass
import sqlite3

from deeptutor.education.application.grading_policy import is_servable
from deeptutor.education.application.content_readiness import admitted
from deeptutor.education.domain.course import AssessmentItem, ItemStatus
from deeptutor.education.storage.repositories import AssessmentItemRepository


@dataclass(frozen=True, slots=True)
class SelectedItem:
    item: AssessmentItem
    attempts_so_far: int
    total_gradable: int


def select_next_item(
    conn: sqlite3.Connection,
    learner_id: str,
    course_version_id: str,
    knowledge_node_id: str,
    *,
    include_judgeable: bool = False,
    exclude: Container[str] = (),
    content_mode: str = "production",
) -> SelectedItem | None:
    """Least-attempted servable item on this node, ``None`` if none exist.

    ``include_judgeable`` means "a judge is wired in". With one, items that
    no string comparison can settle (open tasks, and ``short`` items whose
    reference answer is prose rather than a key) become servable too.

    Least-attempted first spreads practice over the whole pool before
    repeating anything; ``id`` breaks ties so the choice is stable.

    ``exclude`` skips items already picked for the current set — 组卷时同一张
    卷子上不该出现两道一模一样的题（2026-08-21 加，服务 /api/edu/set）。
    """
    items = [
        item
        for item in AssessmentItemRepository(conn).list_for_version(course_version_id)
        if item.knowledge_node_id == knowledge_node_id
        and admitted(item, content_mode)
        # Servability is one question with one answer, and it lives in
        # grading_policy — "can anything mark this?" — not a type whitelist
        # plus a null check that disagreed with how grading actually works.
        and is_servable(item, judge_available=include_judgeable)
        and item.id not in exclude
    ]
    if not items:
        return None

    counts = {
        row["assessment_item_id"]: row["n"]
        for row in conn.execute(
            """
            SELECT assessment_item_id, COUNT(*) AS n
            FROM student_attempts
            WHERE learner_id = ? AND knowledge_node_id = ?
            GROUP BY assessment_item_id
            """,
            (learner_id, knowledge_node_id),
        ).fetchall()
    }
    chosen = min(items, key=lambda i: (counts.get(i.id, 0), i.id))
    return SelectedItem(
        item=chosen,
        attempts_so_far=counts.get(chosen.id, 0),
        total_gradable=len(items),
    )
