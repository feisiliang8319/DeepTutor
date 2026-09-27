"""Course availability is content evidence, never assumed learner mastery."""
from collections import defaultdict

from deeptutor.education.application.grading_policy import is_servable
from deeptutor.education.domain.course import ItemStatus
from deeptutor.education.storage.repositories import AssessmentItemRepository, KnowledgeGraphRepository


def admitted(item, content_mode: str) -> bool:
    if content_mode not in {"trial", "production"}:
        raise ValueError("content_mode must be trial or production")
    if item.status is ItemStatus.RETIRED:
        return False
    if content_mode == "trial":
        return True
    return (item.status is ItemStatus.PRODUCTION
            and bool(item.reviewer and item.reviewer.strip()) and bool(item.reviewed_at)
            and bool(item.explanation and item.explanation.strip()))


def course_readiness(conn, course_version_id, *, content_mode="production", judge_available=False):
    """Available optional practice; prerequisite edges never lock topics.

    Item coverage is separate from learning evidence. A content shortage does
    not mean that the learner must pass earlier exercises before reading.
    """
    graph = KnowledgeGraphRepository(conn)
    nodes = graph.list_nodes(course_version_id)
    items = defaultdict(list)
    for item in AssessmentItemRepository(conn).list_for_version(course_version_id):
        if admitted(item, content_mode) and is_servable(item, judge_available=judge_available):
            items[item.knowledge_node_id].append(item)
    available = {n.id for n in nodes if items[n.id]}
    return {"content_mode": content_mode, "learning_mode": "free",
            "prerequisites_enforced": False,
            "nodes": len(nodes), "practice_available_nodes": len(available),
            "gaps": [{"code": n.code, "title": n.title,
                      "role": n.node_type, "servable_items": 0,
                      "reason": "no_practice_items"}
                     for n in nodes if n.id not in available]}
