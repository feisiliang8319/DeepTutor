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

from deeptutor.education.domain.course import AssessmentItem, ItemStatus, ItemType
from deeptutor.education.storage.repositories import AssessmentItemRepository

# Item types the deterministic grader can actually score. Everything else
# needs a human/LLM judgment the web loop does not have yet, so serving it
# to a child would produce a question nobody can mark.
AUTO_GRADABLE = (ItemType.NUMERIC, ItemType.SHORT, ItemType.CHOICE)

# Open tasks a deterministic grader cannot mark. Servable only when a judge
# is wired in, otherwise a child would answer into a void: the attempt would
# be stored with is_correct=None and never resolve.
JUDGEABLE = (ItemType.MULTI_STEP, ItemType.VISUAL_MODEL)


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
) -> SelectedItem | None:
    """Least-attempted auto-gradable item on this node, ``None`` if none exist.

    Least-attempted first spreads practice over the whole pool before
    repeating anything; ``id`` breaks ties so the choice is stable.

    ``exclude`` skips items already picked for the current set — 组卷时同一张
    卷子上不该出现两道一模一样的题（2026-08-21 加，服务 /api/edu/set）。
    """
    servable = AUTO_GRADABLE + (JUDGEABLE if include_judgeable else ())
    items = [
        item
        for item in AssessmentItemRepository(conn).list_for_version(course_version_id)
        if item.knowledge_node_id == knowledge_node_id
        and item.status is not ItemStatus.RETIRED
        and item.item_type in servable
        # Auto-graded types need a reference answer; judged types do not
        # (their whole point is that there is no single right string).
        and (item.expected_answer is not None or item.item_type in JUDGEABLE)
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
