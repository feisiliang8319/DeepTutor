"""Destructive-injection tests #8 and #9: ``expected_answer`` must never
reach a public payload, and must never reach a log line even when the
exception that triggered the log line was raised from code that had the
answer in scope (P0-DESIGN.md §2.4.2's "expected_answer 泄露闸门").
"""

from __future__ import annotations

import json
from dataclasses import replace
import logging

from deeptutor.education.application import record_attempt as record_attempt_module
from deeptutor.education.application.record_attempt import NewAttemptInput, record_attempt
from deeptutor.education.storage.repositories import (
    AssessmentItemRepository,
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
