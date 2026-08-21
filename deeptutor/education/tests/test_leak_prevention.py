"""Destructive-injection tests #8 and #9: ``expected_answer`` must never
reach a public payload, and must never reach a log line even when the
exception that triggered the log line was raised from code that had the
answer in scope (P0-DESIGN.md §2.4.2's "expected_answer 泄露闸门").
"""

from __future__ import annotations

import json
from dataclasses import replace
import logging

import pytest

from deeptutor.education.application import record_attempt as record_attempt_module
from deeptutor.education.application.record_attempt import NewAttemptInput, record_attempt
from deeptutor.education.storage.repositories import (
    AssessmentItemRepository,
    ImportRejected,
    KnowledgeGraphRepository,
)
from deeptutor.education.tests.fixtures import build_fixture_a_math, content_hash

_SECRET = "SECRET-ANSWER-DO-NOT-LEAK-7f3a9c"


def _seed_item_with_secret_answer(conn, course_version):
    bundle = build_fixture_a_math(course_version.id)
    KnowledgeGraphRepository(conn).import_nodes_and_edges(
        course_version_id=course_version.id, nodes=bundle.nodes[:1], edges=[]
    )
    node = bundle.nodes[0]
    row = {
        "id": "item-secret",
        "course_version_id": course_version.id,
        "knowledge_node_id": node.id,
        "item_type": "short",
        "prompt": "some question",
        "expected_answer": _SECRET,
        "rubric_json": '{"key": "also secret rubric text"}',
        "difficulty": 1,
        "content_scope": "BUNDLED",
        "source_ref": None,
        "license_note": None,
        "attribution_text": None,
        "derived_from_item_id": None,
        "reviewer": None,
        "reviewed_at": None,
        "content_hash": content_hash("item-secret"),
        "status": "production",
    }
    [item] = AssessmentItemRepository(conn).import_items([row])
    return item


# ---- test #8: public payload never contains expected_answer ---------------


def test_public_payload_excludes_expected_answer_and_rubric(conn, course_version):
    item = _seed_item_with_secret_answer(conn, course_version)
    payload = item.to_public_payload()

    assert "expected_answer" not in payload
    assert "rubric_json" not in payload

    serialized = json.dumps(payload)
    assert _SECRET not in serialized
    assert "also secret rubric text" not in serialized


def test_public_payload_includes_figure_spec_id(conn, course_version):
    """The inverse of the leak gate: a figure-dependent item is unanswerable
    if the figure never reaches the student, so ``figure_spec_id`` must be on
    the public side of the whitelist.

    Kept next to the leak tests deliberately — the two constraints pull in
    opposite directions and a future edit to ``_ITEM_PUBLIC_FIELDS`` should
    fail loudly if it satisfies only one of them.
    """
    item = _seed_item_with_secret_answer(conn, course_version)
    figured = replace(item, figure_spec_id="cemc-shape-sums")

    payload = figured.to_public_payload()
    assert payload["figure_spec_id"] == "cemc-shape-sums"
    # …and adding it must not have opened the answer path.
    assert "expected_answer" not in payload
    assert _SECRET not in json.dumps(payload)


def test_public_payload_of_every_field_type_never_leaks_across_a_batch(conn, course_version):
    """Grep-style check across a whole imported batch, mirroring how the
    task phrases test #8 ("公共 API 响应体 grep expected_answer")."""
    bundle = build_fixture_a_math(course_version.id)
    KnowledgeGraphRepository(conn).import_nodes_and_edges(
        course_version_id=course_version.id, nodes=bundle.nodes, edges=bundle.edges
    )
    items = AssessmentItemRepository(conn).import_items(bundle.item_rows)
    public_body = json.dumps([item.to_public_payload() for item in items])
    assert "expected_answer" not in public_body
    # A substring check against the raw answer value is unsound for short
    # numeric answers (e.g. "7") that legitimately also appear inside an
    # unrelated prompt's text — the field-name check above is the real
    # assertion; this only spot-checks a long, distinctive answer.
    distinctive = [item for item in items if item.expected_answer and len(item.expected_answer) >= 4]
    assert distinctive, "fixture must include at least one answer long enough for a meaningful substring check"
    for item in distinctive:
        assert item.expected_answer not in public_body


# ---- test #9: a grading-path exception must not leak the answer in logs --


def test_post_commit_failure_log_never_contains_expected_answer(conn, learner, course_version, caplog, monkeypatch):
    item = _seed_item_with_secret_answer(conn, course_version)

    def _boom(*args, **kwargs):
        # Simulate an exception raised from deep inside grading/mastery code
        # that (buggily) put the secret answer in its message — the point
        # of this test is that _safe_error_text must scrub it regardless.
        raise RuntimeError(f"grading exploded near answer {_SECRET!r}")

    monkeypatch.setattr(record_attempt_module, "rebuild_learner_node", _boom)

    params = NewAttemptInput(
        learner_id=learner.id,
        assessment_item_id=item.id,
        response="whatever",
        started_at="2026-01-01T00:00:00+00:00",
        submitted_at="2026-01-01T00:00:01+00:00",
        source="practice",
    )
    with caplog.at_level(logging.ERROR, logger="deeptutor.education.alerts"):
        result = record_attempt(conn, params)

    assert result.pending_recompute is True
    assert result.error is not None
    assert _SECRET not in result.error

    full_log_text = "\n".join(record.getMessage() for record in caplog.records)
    full_log_text += "\n".join(str(getattr(record, "error", "")) for record in caplog.records)
    assert _SECRET not in full_log_text


# ---- 选项必须出网线，但绝不能标出哪个是对的 -----------------------------
#
# 2026-08-21 新增 choices_json 时开的新泄漏面：选择题的选项**必然**要送到孩子
# 的浏览器（不给就没法作答），所以它在 `_ITEM_PUBLIC_FIELDS` 白名单里。正因为
# 必然出网线，任何"哪个是对的"的痕迹藏在里面都等于把 expected_answer 换个字段名
# 发出去。import 闸门 fail-closed，这里做回归。


_MCQ_CHOICES = [
    {"label": "A", "text": "Foreigners were not welcome in Chinese trading cities."},
    {"label": "B", "text": "Hangzhou was accessible by the Grand Canal for internal trade."},
    {"label": "C", "text": "Chinese governments limited the number of markets."},
    {"label": "D", "text": "Most traders were Europeans on the Silk Roads."},
]


def _mcq_row(course_version_id: str, **overrides) -> dict:
    row = {
        "id": "item-mcq-1",
        "course_version_id": course_version_id,
        "knowledge_node_id": "node-G3.MULT.BASIC",
        "item_type": "choice",
        # 生产形态：答案是**字母**，选项是散文（apwh-u1-t11-mcq1 即如此）
        "prompt": "Based on the passage, which statement is most accurate?",
        "expected_answer": "B",
        "rubric_json": None,
        "difficulty": 3,
        "content_scope": "BUNDLED",
        "source_ref": "self-authored (test)",
        "license_note": None,
        "attribution_text": None,
        "derived_from_item_id": None,
        "reviewer": None,
        "reviewed_at": None,
        "content_hash": content_hash("item-mcq-1"),
        "status": "candidate",
        "choices_json": json.dumps(_MCQ_CHOICES, ensure_ascii=False),
    }
    row.update(overrides)
    return row


def _seed_mcq_node(conn, course_version):
    bundle = build_fixture_a_math(course_version.id)
    KnowledgeGraphRepository(conn).import_nodes_and_edges(
        course_version_id=course_version.id, nodes=bundle.nodes, edges=bundle.edges
    )


def test_choices_ship_but_never_mark_the_right_one(conn, course_version):
    _seed_mcq_node(conn, course_version)
    item = AssessmentItemRepository(conn).import_items([_mcq_row(course_version.id)])[0]
    payload = item.to_public_payload()

    assert json.loads(payload["choices_json"]) == _MCQ_CHOICES, "选项必须送到孩子面前"
    body = json.dumps(payload, ensure_ascii=False)
    assert "expected_answer" not in body
    assert "explanation" not in body, "讲解只能在全部提交之后出现，不能搭出题这班车"
    for marker in ("is_correct", "correct", "rationale", "solution"):
        assert marker not in body


@pytest.mark.parametrize(
    "bad_choices,why",
    [
        # 原报的三种（黑名单时代就拦得住的）
        ([{"label": "A", "text": "x", "is_correct": True}, {"label": "B", "text": "y"}], "布尔标记"),
        ([{"label": "A", "text": "x", "score": 1}, {"label": "B", "text": "y"}], "分值"),
        ([{"label": "A", "text": "x", "explanation": "因为…"}, {"label": "B", "text": "y"}], "讲解"),
        # ↓ 2026-08-21 第二轮质检席 E 项实测能绕过黑名单的同义变体，
        #   改白名单后应全部拒收。字段级黑名单必须假设"换个名字"攻击面。
        ([{"label": "A", "text": "x", "answerKey": "A"}, {"label": "B", "text": "y"}], "驼峰 answerKey"),
        ([{"label": "A", "text": "x", "isCorrect": True}, {"label": "B", "text": "y"}], "驼峰 isCorrect"),
        ([{"label": "A", "text": "x", "CorrectAnswer": "A"}, {"label": "B", "text": "y"}], "首字母大写"),
        ([{"label": "A", "text": "x", "is correct": True}, {"label": "B", "text": "y"}], "带空格"),
        ([{"label": "A", "text": "x", "正确": True}, {"label": "B", "text": "y"}], "中文键"),
        # 答案编进 label 也拦掉
        ([{"label": "A (correct)", "text": "x"}, {"label": "B", "text": "y"}], "答案编进 label"),
        ([{"label": "A", "text": "x"}], "只有一个选项"),
        ([{"label": "A", "text": "x"}, {"label": "A", "text": "y"}], "label 重复"),
        ("not json at all", "不是合法 JSON"),
    ],
)
def test_choice_rows_that_hint_at_the_answer_are_rejected(conn, course_version, bad_choices, why):
    _seed_mcq_node(conn, course_version)
    payload = bad_choices if isinstance(bad_choices, str) else json.dumps(bad_choices)
    with pytest.raises(ImportRejected):
        AssessmentItemRepository(conn).import_items(
            [_mcq_row(course_version.id, choices_json=payload)]
        )


def test_choice_item_without_structured_choices_is_rejected(conn, course_version):
    """没有结构化选项的 choice 题就是"孩子只能手打字母"那个缺陷本身。"""
    _seed_mcq_node(conn, course_version)
    with pytest.raises(ImportRejected):
        AssessmentItemRepository(conn).import_items(
            [_mcq_row(course_version.id, choices_json=None)]
        )


def test_explanation_without_a_source_is_rejected(conn, course_version):
    """讲解必须带出处：权威不权威直接决定家长该不该信它。"""
    _seed_mcq_node(conn, course_version)
    with pytest.raises(ImportRejected):
        AssessmentItemRepository(conn).import_items(
            [_mcq_row(course_version.id, explanation="因为运河通内陆。")]
        )
