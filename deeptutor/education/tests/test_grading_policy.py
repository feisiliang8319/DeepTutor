"""Who settles an item: the string comparer, or a judge.

These tests exist because that question used to be answered three different
ways in three different modules, and the disagreement was invisible in
production. Two failure modes, mirror images of each other:

* a ``short`` item with a *prose* reference answer was served and then run
  through ``grade_answer``, which for anything longer than
  ``SHORT_FUZZY_MAX_CHARS`` can only return ``True`` on a byte-exact reply —
  45 of 91 servable Grade-4 short items were in this state on 2026-08-21,
  i.e. markable wrong and nothing else;
* a ``short`` item with a rubric but *no* reference answer could never be
  served at all, so 16 items sat in the database unreachable.

The invariant pinned here is a single one: **an item is auto-graded only
when a string comparison can actually settle it, and everything else needs
a judge** — with ``select_item``, ``record_attempt`` and the API agreeing on
that by construction, because they call the same predicate.
"""

from __future__ import annotations

import json
from pathlib import Path
import time

from fastapi.testclient import TestClient
import pytest

from deeptutor.education.api.app import create_app
from deeptutor.education.application import to_iso_timestamp
from deeptutor.education.application.grading_policy import (
    is_servable,
    needs_judgment,
)
from deeptutor.education.application.record_attempt import (
    NewAttemptInput,
    record_attempt,
)
from deeptutor.education.application.select_item import select_next_item
from deeptutor.education.domain.course import (
    AssessmentItem,
    ContentScope,
    Course,
    CourseVersion,
    CourseVersionStatus,
    ItemStatus,
    ItemType,
    KnowledgeNode,
)
from deeptutor.education.domain.learner import Enrollment, LearnerProfile
from deeptutor.education.storage import sqlite as edu_sqlite
from deeptutor.education.storage.repositories import (
    AssessmentItemRepository,
    CourseRepository,
    EnrollmentRepository,
    KnowledgeGraphRepository,
    LearnerRepository,
)
from deeptutor.education.tests.fixtures import content_hash
from deeptutor.learning.grading import SHORT_FUZZY_MAX_CHARS

CV = "cv-policy-1"
LEARNER = "learner-policy"
NODE = "node-POLICY"

# A real AP World History SAQ reference block is prose, not a key. Anything
# comfortably over the fuzzy ceiling stands in for it here.
PROSE_ANSWER = (
    "Muslim merchants and Sufi missionaries carried Islam along Indian Ocean "
    "trade routes, producing states such as the sultanate of Malacca."
)
KEY_ANSWER = "12"


def item(
    item_id: str,
    item_type: ItemType,
    expected_answer: str | None,
    *,
    rubric: dict[str, object] | None = None,
) -> AssessmentItem:
    return AssessmentItem(
        id=item_id,
        course_version_id=CV,
        knowledge_node_id=NODE,
        item_type=item_type,
        difficulty=3,
        content_scope=ContentScope.BUNDLED,
        content_hash=content_hash(item_id),
        status=ItemStatus.CANDIDATE,
        prompt="Explain ONE example.",
        expected_answer=expected_answer,
        rubric_json=None if rubric is None else json.dumps(rubric),
    )


# --------------------------------------------------------------------------
# the predicate itself
# --------------------------------------------------------------------------


def test_prose_reference_answer_on_a_short_item_needs_a_judge():
    """The regression this whole module exists for.

    ``grade_answer`` skips its fuzzy branch above the ceiling, so a prose
    reference answer makes every non-identical reply wrong. Serving that as
    "auto-graded" tells a child they are wrong when they are right.
    """
    assert len(PROSE_ANSWER) > SHORT_FUZZY_MAX_CHARS
    assert needs_judgment(item("i", ItemType.SHORT, PROSE_ANSWER)) is True


def test_short_key_answer_is_still_auto_graded():
    """Guard against over-correcting: the 46 items that *do* have exact-match
    keys must keep their deterministic, instant, offline verdict."""
    assert needs_judgment(item("i", ItemType.SHORT, KEY_ANSWER)) is False


@pytest.mark.parametrize("blank", [None, "", "   ", "\n"])
def test_missing_reference_answer_needs_a_judge(blank):
    """Empty string counts as missing. A blank column after a CSV import is
    not "a reference answer that happens to be empty" — read that way,
    ``grade_answer`` marks every reply wrong."""
    assert needs_judgment(item("i", ItemType.SHORT, blank)) is True


def test_length_ceiling_does_not_leak_into_numeric_or_choice():
    """Only ``short`` straddles the line. A float parse and a label compare
    do not care how long the stored answer is, and pushing these to a judge
    would be a pointless, slower, less reliable verdict."""
    assert needs_judgment(item("n", ItemType.NUMERIC, "3.14159265358979323846264338")) is False
    assert needs_judgment(item("c", ItemType.CHOICE, "B")) is False


def test_open_and_paper_types_always_need_a_judgment():
    assert needs_judgment(item("m", ItemType.MULTI_STEP, None)) is True
    assert needs_judgment(item("v", ItemType.VISUAL_MODEL, PROSE_ANSWER)) is True
    assert needs_judgment(item("p", ItemType.PAPER_REF, None)) is True


def test_paper_ref_is_never_servable_even_with_a_judge():
    """Its outcome is phoned in by a parent; no judge has anything to read."""
    assert is_servable(item("p", ItemType.PAPER_REF, None), judge_available=True) is False


def test_servability_turns_on_the_judge_for_exactly_the_judged_items():
    prose = item("i", ItemType.SHORT, PROSE_ANSWER)
    key = item("k", ItemType.SHORT, KEY_ANSWER)
    assert is_servable(prose, judge_available=False) is False
    assert is_servable(prose, judge_available=True) is True
    # The auto-gradable one is servable either way — a judge being present
    # must not change how it gets marked.
    assert is_servable(key, judge_available=False) is True
    assert is_servable(key, judge_available=True) is True


# --------------------------------------------------------------------------
# the three call sites actually agreeing
# --------------------------------------------------------------------------


@pytest.fixture
def policy_db(tmp_path: Path) -> Path:
    db_path = tmp_path / "policy.db"
    conn = edu_sqlite.open_database(db_path)
    now = to_iso_timestamp(time.time())
    CourseRepository(conn).create_course(
        Course(id="c-p", subject_key="history", title="P", created_at=now, level="AP-HS")
    )
    CourseRepository(conn).create_course_version(
        CourseVersion(id=CV, course_id="c-p", version="1.0.0", content_hash="0" * 64,
                      status=CourseVersionStatus.ACTIVE, created_at=now)
    )
    LearnerRepository(conn).create(
        LearnerProfile(id=LEARNER, deep_tutor_user_id="dtu-p", display_name="Kid",
                       locale="en-US", created_at=now, updated_at=now)
    )
    KnowledgeGraphRepository(conn).import_nodes_and_edges(
        course_version_id=CV,
        nodes=[KnowledgeNode(id=NODE, course_version_id=CV, code="POLICY",
                             node_type="concept", title="Policy node", sort_order=1)],
        edges=[],
    )

    def row(item_id: str, item_type: str, expected: str | None, rubric: dict | None):
        return {
            "id": item_id, "course_version_id": CV, "knowledge_node_id": NODE,
            "item_type": item_type,
            "prompt": "Explain ONE example of Islamic influence in South Asia.",
            "expected_answer": expected,
            "rubric_json": None if rubric is None else json.dumps(rubric),
            "difficulty": 3, "content_scope": "BUNDLED",
            "source_ref": "self-authored (test)", "license_note": None,
            "attribution_text": None, "derived_from_item_id": None, "reviewer": None,
            "reviewed_at": None, "content_hash": content_hash(item_id),
            "status": "candidate",
        }

    AssessmentItemRepository(conn).import_items([
        row("saq-no-answer", "short", None, {"scoring": "must explain one mechanism"}),
        row("saq-prose-answer", "short", PROSE_ANSWER, None),
    ])
    EnrollmentRepository(conn).enroll(Enrollment(LEARNER, CV, "active", now, now))
    conn.commit()
    conn.close()
    return db_path


def test_selector_withholds_judged_items_until_a_judge_exists(policy_db):
    conn = edu_sqlite.open_database(policy_db)
    try:
        assert select_next_item(conn, LEARNER, CV, NODE, include_judgeable=False) is None
        with_judge = select_next_item(conn, LEARNER, CV, NODE, include_judgeable=True)
        assert with_judge is not None
        # Both items are reachable, not just the one missing an answer —
        # the prose-answer item is the half that used to be served *and*
        # mismarked rather than withheld.
        assert with_judge.total_gradable == 2
    finally:
        conn.close()


@pytest.mark.parametrize("item_id", ["saq-no-answer", "saq-prose-answer"])
def test_record_attempt_leaves_judged_items_unresolved_rather_than_wrong(policy_db, item_id):
    """The load-bearing half of the fix.

    A substantively correct answer to a prose-referenced item must come back
    ``is_correct is None`` ("nobody has settled this yet"), never ``False``.
    Before 2026-08-21 the second case returned ``False`` here, and that
    ``False`` fed straight into the mastery rebuild.
    """
    conn = edu_sqlite.open_database(policy_db)
    try:
        now = to_iso_timestamp(time.time())
        result = record_attempt(conn, NewAttemptInput(
            learner_id=LEARNER,
            assessment_item_id=item_id,
            response="Sufi missionaries spread Islam along Indian Ocean trade routes.",
            started_at=now, submitted_at=now, source="test",
            client_attempt_id=f"policy:{item_id}",
        ))
        assert result.attempt.is_correct is None
        assert result.attempt.score is None
    finally:
        conn.close()


def test_api_sends_prose_referenced_short_items_to_the_judge(policy_db):
    """The wiring, end to end.

    ``api.app`` used to decide "call the judge?" from ``item_type`` alone,
    which meant every ``short`` item went to string comparison however its
    reference answer was written. Pinning it here because the two halves can
    drift apart silently: the selector can serve an item the submit handler
    then refuses to judge, and the only symptom is an attempt that never
    resolves.
    """
    seen: list[str] = []

    class StubJudge:
        def complete(self, system: str, user: str) -> str:
            seen.append(user)
            return '{"verdict": "correct", "confidence": 0.9, "rationale": "ok"}'

    client = TestClient(create_app(policy_db, judge=StubJudge(), judge_ref="stub"))
    issued = client.post(
        "/api/edu/set", params={"learner_id": LEARNER, "course_version_id": CV}
    ).json()
    ids = [i["id"] for i in issued["items"]]
    assert "saq-prose-answer" in ids, "prose-referenced item must be servable with a judge"

    body = client.post("/api/edu/set/submit", json={
        "learner_id": LEARNER, "course_version_id": CV, "set_id": issued["set_id"],
        "answers": [{"item_id": i, "response": "Sufi missionaries along trade routes."}
                    for i in ids],
    }).json()

    row = next(r for r in body["results"] if r["item_id"] == "saq-prose-answer")
    assert row["judged"] is not None, "no judgment attached — the handler string-matched it"
    assert row["judged"]["verdict"] == "correct"
    assert len(seen) == len(ids), "every servable item in this set needed a judge"
    # And the rubric/reference answer still do not cross the wire.
    assert "rubric_json" not in json.dumps(body)


def test_auto_gradable_item_is_still_marked_without_a_judge(policy_db):
    """The other direction: nothing here made deterministic grading lazier."""
    conn = edu_sqlite.open_database(policy_db)
    try:
        now = to_iso_timestamp(time.time())
        AssessmentItemRepository(conn).import_items([{
            "id": "num-1", "course_version_id": CV, "knowledge_node_id": NODE,
            "item_type": "numeric", "prompt": "6 x 2 = ?", "expected_answer": "12",
            "rubric_json": None, "difficulty": 1, "content_scope": "BUNDLED",
            "source_ref": "self-authored (test)", "license_note": None,
            "attribution_text": None, "derived_from_item_id": None, "reviewer": None,
            "reviewed_at": None, "content_hash": content_hash("num-1"),
            "status": "candidate",
        }])
        conn.commit()
        result = record_attempt(conn, NewAttemptInput(
            learner_id=LEARNER, assessment_item_id="num-1", response="12",
            started_at=now, submitted_at=now, source="test",
            client_attempt_id="policy:num-1",
        ))
        assert result.attempt.is_correct is True
    finally:
        conn.close()
