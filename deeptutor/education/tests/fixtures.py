"""The two P0-DESIGN.md §5 fixtures.

Fixture A (Grade 3-4 Mathematics): a real vertical slice — prerequisite
edges that matter, item types the planner and mastery rebuild both need to
exercise, including the "a Grade 4 node reaches back to two Grade 3 nodes"
shape the design calls out explicitly.

Fixture B (US History): exists to prove the schema is not math-specific.
Its PRECEDES/CAUSES/SUPPORTS edges are stored and schema-validated but
never read by ``select_objective`` (P0-DESIGN.md §2.3).

Both fixtures are entirely synthetic/public-domain-style content —
``content_scope='BUNDLED'`` throughout — so nothing here is a real
copyrighted question (P0-DESIGN.md §5: "fixture 只含合成数据").
"""

from __future__ import annotations

import json

from dataclasses import dataclass
import hashlib

from deeptutor.education.domain.course import EdgeType, KnowledgeEdge, KnowledgeNode


def content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class FixtureBundle:
    course_version_id: str
    nodes: list[KnowledgeNode]
    edges: list[KnowledgeEdge]
    # Raw rows, matching what AssessmentItemRepository.import_items expects
    # (the "loader boundary" shape — see storage/repositories.py).
    item_rows: list[dict[str, object]]


def build_fixture_a_math(course_version_id: str) -> FixtureBundle:
    def node(code: str, node_type: str, title: str, sort_order: int) -> KnowledgeNode:
        return KnowledgeNode(
            id=f"node-{code}",
            course_version_id=course_version_id,
            code=code,
            node_type=node_type,
            title=title,
            sort_order=sort_order,
        )

    nodes = [
        node("G3.MULT.BASIC", "concept", "Grade 3: single-digit multiplication facts", 1),
        node("G3.MULT.MULTIDIGIT", "procedure", "Grade 3: multi-digit multiplication", 2),
        node("G3.DIV.BASIC", "concept", "Grade 3: single-digit division facts", 3),
        node("G3.DIV.MULTIDIGIT", "procedure", "Grade 3: multi-digit division", 4),
        node("G3.FRAC.UNIT", "concept", "Grade 3: unit fractions", 5),
        node("G3.FRAC.COMPARE", "concept", "Grade 3: comparing fractions", 6),
        node("G4.MULT.AREA_MODEL", "strategy", "Grade 4: area model multiplication", 7),
        node("G4.DIV.LONG", "procedure", "Grade 4: long division", 8),
        # The design's explicit "a Grade 4 node reaches back to two Grade 3
        # nodes" case (P0-DESIGN.md §5): fraction equivalence needs BOTH
        # unit-fraction understanding and fraction comparison.
        node("G4.FRAC.EQUIV", "concept", "Grade 4: fraction equivalence", 9),
        node("G4.FRAC.ADD_SUB", "procedure", "Grade 4: adding/subtracting fractions", 10),
        node("G4.WORD_PROBLEMS", "skill", "Grade 4: multi-step multiplication/division word problems", 11),
    ]

    def edge(from_code: str, to_code: str) -> KnowledgeEdge:
        return KnowledgeEdge(
            course_version_id=course_version_id,
            from_node_id=f"node-{from_code}",
            to_node_id=f"node-{to_code}",
            edge_type=EdgeType.PREREQUISITE,
        )

    edges = [
        edge("G3.MULT.BASIC", "G3.MULT.MULTIDIGIT"),
        edge("G3.MULT.BASIC", "G3.DIV.BASIC"),
        edge("G3.DIV.BASIC", "G3.DIV.MULTIDIGIT"),
        edge("G3.MULT.MULTIDIGIT", "G3.DIV.MULTIDIGIT"),
        edge("G3.FRAC.UNIT", "G3.FRAC.COMPARE"),
        edge("G3.MULT.MULTIDIGIT", "G4.MULT.AREA_MODEL"),
        edge("G3.DIV.MULTIDIGIT", "G4.DIV.LONG"),
        edge("G3.FRAC.UNIT", "G4.FRAC.EQUIV"),
        edge("G3.FRAC.COMPARE", "G4.FRAC.EQUIV"),
        edge("G4.FRAC.EQUIV", "G4.FRAC.ADD_SUB"),
        edge("G4.MULT.AREA_MODEL", "G4.WORD_PROBLEMS"),
        edge("G4.DIV.LONG", "G4.WORD_PROBLEMS"),
    ]

    def item(
        item_id: str,
        node_code: str,
        item_type: str,
        prompt: str,
        expected_answer: str,
        difficulty: int,
    ) -> dict[str, object]:
        return {
            "id": item_id,
            "course_version_id": course_version_id,
            "knowledge_node_id": f"node-{node_code}",
            "item_type": item_type,
            "prompt": prompt,
            "expected_answer": expected_answer,
            "rubric_json": None,
            "difficulty": difficulty,
            "content_scope": "BUNDLED",
            "source_ref": None,
            "license_note": None,
            "attribution_text": None,
            "derived_from_item_id": None,
            "reviewer": None,
            "reviewed_at": None,
            "content_hash": content_hash(item_id + prompt),
            "status": "production",
            # choice 题必须带结构化选项（2026-08-21 起 import 闸门强制）：
            # 没有它前端只能把选项当散文渲染，孩子得手打字母。
            #
            # 这里的选项是**占位文本，不含正确答案**，两个理由：
            #   1. 本 fixture 的 choice 题沿用了"expected_answer = 选项正文"的
            #      老写法（如 "42"），与生产 MCQ 的"expected_answer = 选项字母"
            #      不同；把答案正文塞进某个选项会让 test_leak_prevention 的
            #      长答案子串检查命中 —— 那条检查是对的，不该为它让路。
            #   2. 这批 fixture 考的是判分/掌握度/FSRS 机制，不是 MCQ 语义。
            # 贴近生产形态的 MCQ（字母答案 + 散文选项）另见
            # test_leak_prevention.py::test_choices_ship_but_never_mark_the_right_one。
            **({"choices_json": json.dumps(
                [{"label": L, "text": f"Option {L}"} for L in "ABCD"], ensure_ascii=False)}
               if item_type == "choice" else {}),
        }

    item_rows = [
        item("item-mult-basic-choice", "G3.MULT.BASIC", "choice", "What is 6 x 7?", "42", 2),
        item("item-mult-basic-short", "G3.MULT.BASIC", "short", "What is 8 x 9?", "72", 2),
        item("item-mult-multidigit-numeric", "G3.MULT.MULTIDIGIT", "numeric", "What is 23 x 14?", "322", 3),
        item("item-div-basic-numeric", "G3.DIV.BASIC", "numeric", "What is 56 / 8?", "7", 2),
        item(
            "item-frac-unit-visual",
            "G3.FRAC.UNIT",
            "visual_model",
            "Shade 1/4 of the bar model and name the fraction shown.",
            "1/4",
            3,
        ),
        item(
            "item-frac-compare-visual",
            "G3.FRAC.COMPARE",
            "visual_model",
            "Which bar model shows the larger fraction, 2/3 or 3/5?",
            "2/3",
            4,
        ),
        item(
            "item-area-model-choice",
            "G4.MULT.AREA_MODEL",
            "choice",
            "Using the area model, 23 x 14 breaks into which four partial products?",
            "20x10, 20x4, 3x10, 3x4",
            4,
        ),
        item(
            "item-frac-equiv-short",
            "G4.FRAC.EQUIV",
            "short",
            "Write a fraction equivalent to 2/3 with denominator 9.",
            "6/9",
            4,
        ),
    ]

    return FixtureBundle(course_version_id=course_version_id, nodes=nodes, edges=edges, item_rows=item_rows)


def build_fixture_b_history(course_version_id: str) -> FixtureBundle:
    def node(code: str, node_type: str, title: str, sort_order: int) -> KnowledgeNode:
        return KnowledgeNode(
            id=f"node-{code}",
            course_version_id=course_version_id,
            code=code,
            node_type=node_type,
            title=title,
            sort_order=sort_order,
        )

    nodes = [
        node("US.EVENT.DECLARATION", "event", "The Declaration of Independence (1776)", 1),
        node("US.FACT.YEAR_1776", "fact", "The Declaration was adopted in 1776", 2),
        node("US.SOURCE.DECLARATION_TEXT", "source", "Primary source: the Declaration's text", 3),
        node("US.EVENT.TREATY_OF_PARIS", "event", "The Treaty of Paris (1783)", 4),
        node("US.SKILL.PRIMARY_SOURCE_ANALYSIS", "skill", "Analyzing a primary source document", 5),
        node("US.ARGUMENT.CAUSES_OF_REVOLUTION", "argument", "Argument: causes of the Revolution", 6),
    ]

    def edge(from_code: str, to_code: str, edge_type: EdgeType) -> KnowledgeEdge:
        return KnowledgeEdge(
            course_version_id=course_version_id,
            from_node_id=f"node-{from_code}",
            to_node_id=f"node-{to_code}",
            edge_type=edge_type,
        )

    edges = [
        edge("US.FACT.YEAR_1776", "US.EVENT.DECLARATION", EdgeType.SUPPORTS),
        edge("US.SOURCE.DECLARATION_TEXT", "US.EVENT.DECLARATION", EdgeType.SUPPORTS),
        edge("US.EVENT.DECLARATION", "US.EVENT.TREATY_OF_PARIS", EdgeType.PRECEDES),
        edge("US.ARGUMENT.CAUSES_OF_REVOLUTION", "US.EVENT.DECLARATION", EdgeType.CAUSES),
        edge("US.SKILL.PRIMARY_SOURCE_ANALYSIS", "US.SOURCE.DECLARATION_TEXT", EdgeType.SUPPORTS),
        edge("US.SOURCE.DECLARATION_TEXT", "US.EVENT.TREATY_OF_PARIS", EdgeType.PRECEDES),
    ]

    prompt = (
        "According to the Declaration of Independence, governments derive "
        "their just powers from what?"
    )
    item_rows = [
        {
            "id": "item-us-primary-source-short",
            "course_version_id": course_version_id,
            "knowledge_node_id": "node-US.SOURCE.DECLARATION_TEXT",
            "item_type": "short",
            "prompt": prompt,
            "expected_answer": "the consent of the governed",
            "rubric_json": None,
            "difficulty": 3,
            "content_scope": "BUNDLED",
            "source_ref": None,
            "license_note": None,
            "attribution_text": None,
            "derived_from_item_id": None,
            "reviewer": None,
            "reviewed_at": None,
            "content_hash": content_hash("item-us-primary-source-short" + prompt),
            "status": "production",
        }
    ]

    return FixtureBundle(course_version_id=course_version_id, nodes=nodes, edges=edges, item_rows=item_rows)


__all__ = ["FixtureBundle", "build_fixture_a_math", "build_fixture_b_history", "content_hash"]
