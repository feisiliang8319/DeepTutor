"""LLM judging of open-response items.

The load-bearing property is not "the judge is accurate" — no test can pin
that for a model. It is that **every way the judge can fail lands on
NEEDS_REVIEW rather than on a verdict**: unparseable output, a missing
confidence, a hesitant call, a dead server. A wrong "correct" would quietly
push a node toward mastered on evidence nobody checked.
"""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path
import time

from fastapi.testclient import TestClient
import pytest

from deeptutor.education.api.app import create_app
from deeptutor.education.application import to_iso_timestamp
from deeptutor.education.application.llm_judge import (
    CONFIDENCE_FLOOR,
    PROMPT_VERSION,
    build_prompt,
    judge_open_response,
    parse_verdict,
    rubric_version,
)
from deeptutor.education.domain.course import (
    Course,
    CourseVersion,
    CourseVersionStatus,
    KnowledgeNode,
)
from deeptutor.education.domain.evidence import JudgeKind, Verdict
from deeptutor.education.domain.learner import LearnerProfile
from deeptutor.education.storage import sqlite as edu_sqlite
from deeptutor.education.storage.repositories import (
    AssessmentItemRepository,
    CourseRepository,
    JudgmentRepository,
    KnowledgeGraphRepository,
    LearnerRepository,
    MasterySnapshotRepository,
)
from deeptutor.education.tests.fixtures import content_hash

CV = "cv-judge-1"
LEARNER = "learner-judge"
NODE = "node-OPEN"
ITEM = "item-open-task"
SECRET_RUBRIC_FOCUS = "must-list-every-factor-pair"


class StubJudge:
    """Returns whatever the test wants, including nonsense."""

    def __init__(self, reply: str | Exception) -> None:
        self.reply = reply
        self.seen: list[str] = []

    def complete(self, system: str, user: str) -> str:
        self.seen.append(user)
        if isinstance(self.reply, Exception):
            raise self.reply
        return self.reply


@pytest.fixture
def judge_db(tmp_path: Path) -> Path:
    db_path = tmp_path / "judge.db"
    conn = edu_sqlite.open_database(db_path)
    now = to_iso_timestamp(time.time())
    CourseRepository(conn).create_course(
        Course(id="c-j", subject_key="mathematics", title="J", created_at=now, level="G4")
    )
    CourseRepository(conn).create_course_version(
        CourseVersion(id=CV, course_id="c-j", version="1.0.0", content_hash="0" * 64,
                      status=CourseVersionStatus.ACTIVE, created_at=now)
    )
    LearnerRepository(conn).create(
        LearnerProfile(id=LEARNER, deep_tutor_user_id="dtu-j", display_name="Kid",
                       locale="en-US", created_at=now, updated_at=now)
    )
    KnowledgeGraphRepository(conn).import_nodes_and_edges(
        course_version_id=CV,
        nodes=[KnowledgeNode(id=NODE, course_version_id=CV, code="OPEN", node_type="concept",
                             title="Open task node", sort_order=1, standard_code="4.OA.B.4")],
        edges=[],
    )
    AssessmentItemRepository(conn).import_items(
        [{
            "id": ITEM, "course_version_id": CV, "knowledge_node_id": NODE,
            "item_type": "multi_step",
            "prompt": "Draw every rectangle with an area of 24 and list the side lengths.",
            "expected_answer": None,
            "rubric_json": json.dumps({"focus": SECRET_RUBRIC_FOCUS}),
            "difficulty": 3, "content_scope": "BUNDLED",
            "source_ref": "self-authored (test)", "license_note": None,
            "attribution_text": None, "derived_from_item_id": None, "reviewer": None,
            "reviewed_at": None, "content_hash": content_hash(ITEM), "status": "candidate",
        }]
    )
    conn.close()
    return db_path


def client_with(db: Path, judge) -> TestClient:
    return TestClient(create_app(db, judge=judge, judge_ref="stub-model"))


def submit(client: TestClient, answer: str, key: str = "k1"):
    return client.post(
        "/api/edu/attempt",
        json={"learner_id": LEARNER, "course_version_id": CV, "item_id": ITEM,
              "response": answer, "client_attempt_id": key},
    )


# ---- every failure mode lands on NEEDS_REVIEW -----------------------------


@pytest.mark.parametrize(
    "reply,why",
    [
        ("not json at all", "unparseable"),
        ('{"verdict": "brilliant", "confidence": 0.9}', "verdict outside the enum"),
        ('{"verdict": "correct"}', "no confidence at all"),
        ('{"verdict": "correct", "confidence": "very"}', "non-numeric confidence"),
        ("", "empty reply"),
    ],
)
def test_unusable_replies_become_needs_review(reply: str, why: str):
    judgment = parse_verdict(reply, model_ref="m", rubric_ver="r")
    assert judgment.verdict is Verdict.NEEDS_REVIEW, why
    assert judgment.judge_kind is JudgeKind.LLM


def test_low_confidence_verdict_is_downgraded_not_trusted():
    judgment = parse_verdict(
        json.dumps({"verdict": "correct", "confidence": CONFIDENCE_FLOOR - 0.05,
                    "rationale": "maybe"}),
        model_ref="m", rubric_ver="r",
    )
    assert judgment.verdict is Verdict.NEEDS_REVIEW
    assert "low confidence" in (judgment.rationale or "")


def test_confident_verdict_passes_through():
    judgment = parse_verdict(
        json.dumps({"verdict": "correct", "confidence": 0.92, "rationale": "all six pairs"}),
        model_ref="m", rubric_ver="r",
    )
    assert judgment.verdict is Verdict.CORRECT
    assert judgment.confidence == 0.92
    assert judgment.prompt_version == PROMPT_VERSION


def test_dead_judge_is_a_verdict_not_an_exception(judge_db: Path):
    conn = edu_sqlite.open_database(judge_db)
    try:
        item = AssessmentItemRepository(conn).get(ITEM)
    finally:
        conn.close()
    judgment = judge_open_response(
        StubJudge(ConnectionError("no server")), item, "my answer", model_ref="m"
    )
    assert judgment.verdict is Verdict.NEEDS_REVIEW
    assert "unavailable" in (judgment.rationale or "")


def test_json_wrapped_in_prose_is_still_read():
    judgment = parse_verdict(
        'Sure! Here is my marking:\n```json\n{"verdict": "partial", "confidence": 0.8}\n```',
        model_ref="m", rubric_ver="r",
    )
    assert judgment.verdict is Verdict.PARTIAL


# ---- prompt contents and versioning --------------------------------------


def test_prompt_carries_the_rubric_but_the_response_does_not(judge_db: Path):
    stub = StubJudge(json.dumps({"verdict": "correct", "confidence": 0.9, "rationale": "ok"}))
    client = client_with(judge_db, stub)
    r = submit(client, "2x12, 3x8, 4x6, 1x24")
    assert r.status_code == 200, r.text
    # The rubric reaches the model...
    assert SECRET_RUBRIC_FOCUS in stub.seen[0]
    # ...and nothing else.
    assert SECRET_RUBRIC_FOCUS not in r.text
    assert "rubric" not in r.text


def test_rubric_edit_changes_the_recorded_rubric_version(judge_db: Path):
    conn = edu_sqlite.open_database(judge_db)
    try:
        item = AssessmentItemRepository(conn).get(ITEM)
    finally:
        conn.close()
    before = rubric_version(item)
    edited = dataclasses.replace(item, rubric_json=json.dumps({"focus": "something else"}))
    assert rubric_version(edited) != before, "a rubric change must be visible in stored judgments"
    # And an item with no rubric still gets a stable, non-empty version.
    assert rubric_version(dataclasses.replace(item, rubric_json=None))


# ---- end to end through the API ------------------------------------------


def test_confident_correct_records_a_judgment_row_and_moves_mastery(judge_db: Path):
    client = client_with(
        judge_db, StubJudge(json.dumps({"verdict": "correct", "confidence": 0.95,
                                        "rationale": "found all pairs"}))
    )
    body = submit(client, "1x24, 2x12, 3x8, 4x6").json()
    assert body["judged"] == {"verdict": "correct", "confidence": 0.95}

    conn = edu_sqlite.open_database(judge_db)
    try:
        attempt_id = conn.execute("SELECT id FROM student_attempts").fetchone()["id"]
        records = JudgmentRepository(conn).list_for_attempt(attempt_id)
        assert len(records) == 1
        assert records[0].judge_kind is JudgeKind.LLM
        assert records[0].judge_ref == "stub-model"
        assert records[0].prompt_version == PROMPT_VERSION
        assert records[0].rubric_version  # a hash, not empty
        snapshot = MasterySnapshotRepository(conn).get(LEARNER, NODE)
        assert snapshot is not None and snapshot.score > 0
    finally:
        conn.close()


def test_needs_review_does_not_reach_mastered(judge_db: Path):
    client = client_with(judge_db, StubJudge("garbage"))
    for i in range(4):
        submit(client, "some drawing I did on paper", key=f"k{i}")
    conn = edu_sqlite.open_database(judge_db)
    try:
        snapshot = MasterySnapshotRepository(conn).get(LEARNER, NODE)
        assert snapshot is not None
        assert snapshot.status != "mastered", "unreviewed work must not become mastery"
    finally:
        conn.close()


def test_open_items_are_not_served_without_a_judge(judge_db: Path):
    """Without a judge the only open item must not be offered: answering it
    would store evidence that can never resolve."""
    no_judge = TestClient(create_app(judge_db))
    body = no_judge.get(
        "/api/edu/next", params={"learner_id": LEARNER, "course_version_id": CV}
    ).json()
    assert body["item"] is None
    assert body["skipped_empty_nodes"] == ["OPEN"]

    with_judge = client_with(judge_db, StubJudge('{"verdict":"partial","confidence":0.7}'))
    served = with_judge.get(
        "/api/edu/next", params={"learner_id": LEARNER, "course_version_id": CV}
    ).json()
    assert served["item"]["id"] == ITEM
