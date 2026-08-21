"""The standalone education web loop: next → attempt → progress.

The leak tests carry the weight here. Upstream's ``quiz_judge`` was shown
(2026-08-13) to put the reference answer into both the server log and the
child's browser; this loop is the replacement path, so "the answer never
crosses the wire" is a tested invariant, not a convention.
"""

from __future__ import annotations

import json
from pathlib import Path
import time

from fastapi.testclient import TestClient
import pytest

from deeptutor.education.api.app import create_app
from deeptutor.education.application import to_iso_timestamp
from deeptutor.education.domain.course import (
    Course,
    CourseVersion,
    CourseVersionStatus,
    KnowledgeEdge,
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

CV = "cv-web-1"
LEARNER = "learner-web-1"
SECRET_ANSWER = "42"
SECRET_RUBRIC = "the-rubric-must-not-leak"


@pytest.fixture
def web_db(tmp_path: Path) -> Path:
    db_path = tmp_path / "education.db"
    conn = edu_sqlite.open_database(db_path)
    now = to_iso_timestamp(time.time())
    CourseRepository(conn).create_course(
        Course(id="c-web", subject_key="mathematics", title="Web", created_at=now, level="G4")
    )
    CourseRepository(conn).create_course_version(
        CourseVersion(
            id=CV, course_id="c-web", version="1.0.0", content_hash="0" * 64,
            status=CourseVersionStatus.ACTIVE, created_at=now,
        )
    )
    LearnerRepository(conn).create(
        LearnerProfile(
            id=LEARNER, deep_tutor_user_id="dtu-web", display_name="Kid",
            locale="en-US", created_at=now, updated_at=now,
        )
    )
    nodes = [
        KnowledgeNode(id="node-A", course_version_id=CV, code="A", node_type="concept",
                      title="Node A", sort_order=1, standard_code="4.OA.B.4"),
        KnowledgeNode(id="node-B", course_version_id=CV, code="B", node_type="procedure",
                      title="Node B", sort_order=2, standard_code="4.OA.B.4"),
    ]
    KnowledgeGraphRepository(conn).import_nodes_and_edges(
        course_version_id=CV, nodes=nodes,
        edges=[KnowledgeEdge(course_version_id=CV, from_node_id="node-A", to_node_id="node-B")],
    )
    AssessmentItemRepository(conn).import_items(
        [
            {
                "id": "item-A-1", "course_version_id": CV, "knowledge_node_id": "node-A",
                "item_type": "numeric", "prompt": "What is 40 + 2?",
                "expected_answer": SECRET_ANSWER,
                "rubric_json": json.dumps({"note": SECRET_RUBRIC}),
                "difficulty": 1, "content_scope": "BUNDLED", "source_ref": "self-authored (test)",
                "license_note": None, "attribution_text": None, "derived_from_item_id": None,
                "reviewer": None, "reviewed_at": None,
                "content_hash": content_hash("item-A-1"), "status": "candidate",
            },
            {
                "id": "item-A-2", "course_version_id": CV, "knowledge_node_id": "node-A",
                "item_type": "numeric", "prompt": "What is 41 + 1?",
                "expected_answer": SECRET_ANSWER, "rubric_json": None,
                "difficulty": 1, "content_scope": "BUNDLED", "source_ref": "self-authored (test)",
                "license_note": None, "attribution_text": None, "derived_from_item_id": None,
                "reviewer": None, "reviewed_at": None,
                "content_hash": content_hash("item-A-2"), "status": "candidate",
            },
        ]
    )
    # 选课不是装饰：/next、/attempt、/progress 都以它为访问边界（2026-08-21 起）。
    # 这些 fixture 原先一条选课都没有却能取题作答，正是那个缺口的化石。
    EnrollmentRepository(conn).enroll(Enrollment(LEARNER, CV, "active", now, now))
    conn.commit()
    conn.close()
    return db_path


@pytest.fixture
def client(web_db: Path) -> TestClient:
    return TestClient(create_app(web_db))


def _next(client: TestClient) -> dict:
    r = client.get("/api/edu/next", params={"learner_id": LEARNER, "course_version_id": CV})
    assert r.status_code == 200, r.text
    return r.json()


def _attempt(client: TestClient, item_id: str, response: str, key: str):
    return client.post(
        "/api/edu/attempt",
        json={"learner_id": LEARNER, "course_version_id": CV, "item_id": item_id,
              "response": response, "client_attempt_id": key},
    )


# ---- the leak invariant ---------------------------------------------------


def test_next_task_never_ships_the_answer_or_rubric(client: TestClient):
    r = client.get("/api/edu/next", params={"learner_id": LEARNER, "course_version_id": CV})
    body = r.text
    assert "expected_answer" not in body
    assert "rubric" not in body
    # The answer string itself must not appear anywhere in the payload —
    # not under another key, not inside the prompt echo.
    assert SECRET_RUBRIC not in body
    payload = r.json()
    assert payload["item"]["prompt"] == "What is 40 + 2?"
    assert set(payload["item"]) == {"id", "prompt", "item_type", "difficulty", "attribution"}


def test_attempt_response_never_ships_the_answer_or_rubric(client: TestClient):
    item_id = _next(client)["item"]["id"]
    r = _attempt(client, item_id, "999", "k1")
    assert r.status_code == 200, r.text
    assert "expected_answer" not in r.text
    assert SECRET_RUBRIC not in r.text
    assert r.json()["is_correct"] is False


# ---- the loop actually turns ---------------------------------------------


def test_correct_answer_moves_mastery_and_review(client: TestClient):
    item_id = _next(client)["item"]["id"]
    body = _attempt(client, item_id, SECRET_ANSWER, "k-correct").json()
    assert body["is_correct"] is True
    assert body["mastery"]["score"] > 0
    assert body["review"]["reps"] == 1


def test_planner_serves_the_unblocked_node_first(client: TestClient):
    """Node B is gated behind Node A, so the loop must not open on B."""
    assert _next(client)["node"]["code"] == "A"


def test_least_attempted_item_is_served_next(client: TestClient):
    first = _next(client)["item"]["id"]
    _attempt(client, first, "1", "k-a")
    second = _next(client)["item"]["id"]
    assert second != first, "second visit should serve the untouched item"


def test_same_client_attempt_id_is_idempotent(client: TestClient):
    item_id = _next(client)["item"]["id"]
    _attempt(client, item_id, SECRET_ANSWER, "same-key")
    body = _attempt(client, item_id, SECRET_ANSWER, "same-key").json()
    assert body["review"]["reps"] == 1, "a replayed submission must not double-count"


# ---- fail closed ----------------------------------------------------------


def test_empty_item_bank_node_is_skipped_and_reported(tmp_path: Path):
    """The planner's head node is often a prerequisite anchor with no
    questions written yet. The loop must walk past it — and say that it
    did, because an empty bank is a content gap, not a normal state."""
    db_path = tmp_path / "skip.db"
    conn = edu_sqlite.open_database(db_path)
    now = to_iso_timestamp(time.time())
    CourseRepository(conn).create_course(
        Course(id="c-skip", subject_key="mathematics", title="Skip", created_at=now, level="G4")
    )
    CourseRepository(conn).create_course_version(
        CourseVersion(id=CV, course_id="c-skip", version="1.0.0", content_hash="0" * 64,
                      status=CourseVersionStatus.ACTIVE, created_at=now)
    )
    LearnerRepository(conn).create(
        LearnerProfile(id=LEARNER, deep_tutor_user_id="d", display_name="K",
                       locale="en-US", created_at=now, updated_at=now)
    )
    EnrollmentRepository(conn).enroll(Enrollment(LEARNER, CV, "active", now, now))
    KnowledgeGraphRepository(conn).import_nodes_and_edges(
        course_version_id=CV,
        nodes=[
            # Sorted first, deliberately question-less.
            KnowledgeNode(id="node-EMPTY", course_version_id=CV, code="EMPTY",
                          node_type="concept", title="Anchor with no items",
                          sort_order=1, standard_code="3.OA.A.1"),
            KnowledgeNode(id="node-HAS", course_version_id=CV, code="HAS",
                          node_type="numeric", title="Has an item",
                          sort_order=2, standard_code="4.OA.B.4"),
        ],
        edges=[],
    )
    AssessmentItemRepository(conn).import_items(
        [{
            "id": "item-has-1", "course_version_id": CV, "knowledge_node_id": "node-HAS",
            "item_type": "numeric", "prompt": "2 + 2 = ?", "expected_answer": "4",
            "rubric_json": None, "difficulty": 1, "content_scope": "BUNDLED",
            "source_ref": "self-authored (test)", "license_note": None,
            "attribution_text": None, "derived_from_item_id": None, "reviewer": None,
            "reviewed_at": None, "content_hash": content_hash("item-has-1"),
            "status": "candidate",
        }]
    )
    conn.close()

    body = TestClient(create_app(db_path)).get(
        "/api/edu/next", params={"learner_id": LEARNER, "course_version_id": CV}
    ).json()
    assert body["node"]["code"] == "HAS", "should walk past the empty node, not dead-end on it"
    assert body["item"]["id"] == "item-has-1"
    assert body["skipped_empty_nodes"] == ["EMPTY"], "the content gap must be reported, not hidden"


def test_unknown_learner_is_404_not_an_empty_task(web_db: Path):
    r = TestClient(create_app(web_db)).get(
        "/api/edu/next", params={"learner_id": "nobody", "course_version_id": CV}
    )
    assert r.status_code == 404


def test_unknown_item_is_400(client: TestClient):
    r = _attempt(client, "item-does-not-exist", "1", "k-bad")
    assert r.status_code == 400
    assert "unknown assessment_item_id" in r.json()["detail"]


def test_parent_account_cannot_answer(web_db: Path):
    """大人替孩子试答会把记录写进她的掌握度，而 attempts 是 append-only —— 
    写错了删不掉，所以这条必须在写入前拦住。"""
    conn = edu_sqlite.open_database(web_db)
    now = to_iso_timestamp(time.time())
    LearnerRepository(conn).create(
        LearnerProfile(id="parent-x", deep_tutor_user_id="dtu-parent", display_name="家长",
                       locale="en-US", created_at=now, updated_at=now)
    )
    conn.close()
    client = TestClient(create_app(web_db))
    r = client.post("/api/edu/attempt", json={
        "learner_id": "parent-x", "course_version_id": CV, "item_id": "item-A-1",
        "response": "42", "client_attempt_id": "p1"})
    assert r.status_code == 403
    conn = edu_sqlite.open_database(web_db)
    try:
        assert conn.execute("SELECT COUNT(*) c FROM student_attempts").fetchone()["c"] == 0
    finally:
        conn.close()


def test_people_endpoint_labels_roles(web_db: Path):
    conn = edu_sqlite.open_database(web_db)
    now = to_iso_timestamp(time.time())
    LearnerRepository(conn).create(
        LearnerProfile(id="parent-y", deep_tutor_user_id="dtu-p2", display_name="家长",
                       locale="en-US", created_at=now, updated_at=now)
    )
    conn.close()
    body = TestClient(create_app(web_db)).get("/api/edu/people").json()
    roles = {p["id"]: p["role"] for p in body["people"]}
    assert roles["parent-y"] == "parent"
    assert roles[LEARNER] == "learner"


def test_review_queue_surfaces_unresolved_attempts(judge_free_db: Path):
    """needs_review 不该是个没人消费的状态：家长视角靠这个队列看到它。"""
    client = TestClient(create_app(judge_free_db))
    client.post("/api/edu/attempt", json={
        "learner_id": LEARNER, "course_version_id": CV, "item_id": "item-open",
        "response": "I drew it on paper", "client_attempt_id": "q1"})
    body = client.get("/api/edu/review-queue", params={"course_version_id": CV}).json()
    assert len(body["pending"]) == 1
    assert body["pending"][0]["answer"] == "I drew it on paper"
    assert body["pending"][0]["judge"] is None  # 没接 judge 时如实说没有判定


@pytest.fixture
def judge_free_db(web_db: Path) -> Path:
    """一道无法自动判分的开放题，用来制造 needs_review。"""
    conn = edu_sqlite.open_database(web_db)
    AssessmentItemRepository(conn).import_items([{
        "id": "item-open", "course_version_id": CV, "knowledge_node_id": "node-A",
        "item_type": "multi_step", "prompt": "Explain your reasoning.",
        "expected_answer": None, "rubric_json": None, "difficulty": 2,
        "content_scope": "BUNDLED", "source_ref": "self-authored (test)",
        "license_note": None, "attribution_text": None, "derived_from_item_id": None,
        "reviewer": None, "reviewed_at": None, "content_hash": content_hash("item-open"),
        "status": "candidate"}])
    conn.close()
    return web_db


def test_parent_review_resolves_a_pending_attempt(judge_free_db: Path):
    """家长裁定后，那条作答不再挂在待复核队列里，掌握度立刻重算 ——
    没有这一步，needs_review 就是个没人能消费的死状态。"""
    conn = edu_sqlite.open_database(judge_free_db)
    now = to_iso_timestamp(time.time())
    LearnerRepository(conn).create(
        LearnerProfile(id="parent-r", deep_tutor_user_id="dtu-pr", display_name="家长",
                       locale="en-US", created_at=now, updated_at=now)
    )
    conn.close()
    client = TestClient(create_app(judge_free_db))
    client.post("/api/edu/attempt", json={
        "learner_id": LEARNER, "course_version_id": CV, "item_id": "item-open",
        "response": "I drew all four rectangles", "client_attempt_id": "r1"})
    pending = client.get("/api/edu/review-queue", params={"course_version_id": CV}).json()["pending"]
    assert len(pending) == 1

    r = client.post("/api/edu/review", json={
        "reviewer": "parent-r", "attempt_id": pending[0]["attempt_id"],
        "verdict": "correct", "note": "看了她的本子，四个矩形都画了"})
    assert r.status_code == 200, r.text
    assert r.json()["mastery"]["score"] > 0

    after = client.get("/api/edu/review-queue", params={"course_version_id": CV}).json()["pending"]
    assert after == [], "裁定过的作答不该还挂在队列里"

    conn = edu_sqlite.open_database(judge_free_db)
    try:
        kinds = [row["judge_kind"] for row in
                 conn.execute("SELECT judge_kind FROM judgment_records").fetchall()]
        assert "human" in kinds
    finally:
        conn.close()


def test_child_cannot_review_their_own_work(judge_free_db: Path):
    client = TestClient(create_app(judge_free_db))
    client.post("/api/edu/attempt", json={
        "learner_id": LEARNER, "course_version_id": CV, "item_id": "item-open",
        "response": "trust me", "client_attempt_id": "r2"})
    pending = client.get("/api/edu/review-queue", params={"course_version_id": CV}).json()["pending"]
    r = client.post("/api/edu/review", json={
        "reviewer": LEARNER, "attempt_id": pending[0]["attempt_id"], "verdict": "correct"})
    assert r.status_code == 403


def test_review_of_unknown_attempt_is_404(judge_free_db: Path):
    conn = edu_sqlite.open_database(judge_free_db)
    now = to_iso_timestamp(time.time())
    LearnerRepository(conn).create(
        LearnerProfile(id="parent-z", deep_tutor_user_id="dtu-pz", display_name="家长",
                       locale="en-US", created_at=now, updated_at=now)
    )
    conn.close()
    r = TestClient(create_app(judge_free_db)).post("/api/edu/review", json={
        "reviewer": "parent-z", "attempt_id": "no-such-attempt", "verdict": "correct"})
    assert r.status_code == 404


def test_progress_reports_status_per_node(client: TestClient):
    item_id = _next(client)["item"]["id"]
    _attempt(client, item_id, SECRET_ANSWER, "k-p")
    body = client.get(
        "/api/edu/progress", params={"learner_id": LEARNER, "course_version_id": CV}
    ).json()
    assert {row["code"] for row in body["nodes"]} == {"A", "B"}
    by_code = {row["code"]: row for row in body["nodes"]}
    assert by_code["A"]["status"] in ("learning", "mastered")
    assert by_code["B"]["status"] == "new"
    assert "expected_answer" not in json.dumps(body)


# ---- 课程目录：前端唯一的课程来源 -----------------------------------------
#
# 这三个测试补的是一个曾经真实存在的缺口：enrollments 表在运行时**没有任何
# 消费方**，前端把 `cv-ccss-g4-1.0.0` 写死。给谁选了课都不影响任何人看到什么，
# 直到第二门课上线才暴露（2026-08-21）。


def test_courses_lists_only_active_enrollments(client: TestClient, web_db: Path):
    conn = edu_sqlite.open_database(web_db)
    now = to_iso_timestamp(time.time())
    CourseRepository(conn).create_course(
        Course(id="c-hist", subject_key="history", title="History", created_at=now, level="AP-HS")
    )
    CourseRepository(conn).create_course_version(
        CourseVersion(id="cv-hist-1", course_id="c-hist", version="1.0.0", content_hash="1" * 64,
                      status=CourseVersionStatus.ACTIVE, created_at=now)
    )
    repo = EnrollmentRepository(conn)
    earlier = to_iso_timestamp(time.time() - 86400)
    repo.enroll(Enrollment(LEARNER, CV, "active", earlier, earlier))
    repo.enroll(Enrollment(LEARNER, "cv-hist-1", "active", now, now))
    conn.commit()
    titles = [c["title"] for c in client.get(
        "/api/edu/courses", params={"learner_id": LEARNER}).json()["courses"]]
    # "cv-hist-1" < "cv-web-1"：若排序退回按 course_version_id，这里会翻成 History 在前。
    # 同一时刻选的多门课才按 id 决胜负 —— 那种情况下本就没有数据能说谁是默认课。
    assert titles == ["Web", "History"], "应按选课时间排序：新课不该把默认课挤掉"

    repo.set_status(LEARNER, "cv-hist-1", "withdrawn", at=now)
    conn.commit()
    conn.close()
    titles = [c["title"] for c in client.get(
        "/api/edu/courses", params={"learner_id": LEARNER}).json()["courses"]]
    assert titles == ["Web"], "退选的课不该继续出现在课表里"


def test_courses_is_empty_without_enrollment(client: TestClient, web_db: Path):
    conn = edu_sqlite.open_database(web_db)
    now = to_iso_timestamp(time.time())
    LearnerRepository(conn).create(LearnerProfile(
        id="learner-unenrolled", deep_tutor_user_id="dtu-un", display_name="No Courses",
        locale="en-US", created_at=now, updated_at=now))
    conn.commit(); conn.close()
    assert client.get(
        "/api/edu/courses", params={"learner_id": "learner-unenrolled"}).json()["courses"] == []


# ---- 选课是访问边界，不只是课程列表（质检席 F-1）--------------------------


def test_withdrawn_learner_cannot_fetch_or_answer(client: TestClient, web_db: Path):
    item_id = _next(client)["item"]["id"]          # 退选前正常
    conn = edu_sqlite.open_database(web_db)
    EnrollmentRepository(conn).set_status(
        LEARNER, CV, "withdrawn", at=to_iso_timestamp(time.time()))
    conn.commit(); conn.close()

    assert client.get("/api/edu/next", params={
        "learner_id": LEARNER, "course_version_id": CV}).status_code == 403
    assert client.get("/api/edu/progress", params={
        "learner_id": LEARNER, "course_version_id": CV}).status_code == 403
    # 最要紧的一条：退选后不能再往这门课写作答，否则掌握度证据会长在已退的课上
    assert _attempt(client, item_id, SECRET_ANSWER, "k-withdrawn").status_code == 403


def test_attempt_checks_the_items_course_not_the_payload_field(client: TestClient, web_db: Path):
    """防"校验剧场"：payload.course_version_id 不参与落库，照它校验等于没校验。

    record_attempt 从 item 反查 course_version_id，所以这里必须按 item 实际所属
    课程判。构造：learner 退掉了 item 所在的课，却在 payload 里报一门他确实选了
    的课 —— 若校验打在 payload 上，这一条会被放行。
    """
    item_id = _next(client)["item"]["id"]
    conn = edu_sqlite.open_database(web_db)
    now = to_iso_timestamp(time.time())
    CourseRepository(conn).create_course(
        Course(id="c-other", subject_key="history", title="Other", created_at=now, level="AP-HS"))
    CourseRepository(conn).create_course_version(
        CourseVersion(id="cv-other", course_id="c-other", version="1.0.0", content_hash="2" * 64,
                      status=CourseVersionStatus.ACTIVE, created_at=now))
    repo = EnrollmentRepository(conn)
    repo.enroll(Enrollment(LEARNER, "cv-other", "active", now, now))
    repo.set_status(LEARNER, CV, "withdrawn", at=now)
    conn.commit(); conn.close()

    r = client.post("/api/edu/attempt", json={
        "learner_id": LEARNER, "course_version_id": "cv-other",   # 谎报一门他选了的课
        "item_id": item_id, "response": SECRET_ANSWER, "client_attempt_id": "k-theater"})
    assert r.status_code == 403, "按 payload 校验＝校验剧场；必须按 item 实际所属课程判"


def test_courses_unknown_learner_is_404(client: TestClient):
    assert client.get("/api/edu/courses", params={"learner_id": "nobody"}).status_code == 404


# ---- 成组出题：答案与讲解只在整组提交之后出现 ----------------------------
#
# Sol 2026-08-21：「出题后不能附答案！答案必须在所有答题提交后再给出，给出的
# 答案必须解释答案的原因与关联的知识点。」
# 旧路径 /api/edu/next + /api/edu/attempt 是"答一题→立刻告知对错→1.4 秒后
# 下一题"，孩子在整组做完之前就知道每题对错，与上面这条冲突。


def _seed_explained_choice(web_db: Path) -> None:
    conn = edu_sqlite.open_database(web_db)
    AssessmentItemRepository(conn).import_items([{
        "id": "item-A-choice", "course_version_id": CV, "knowledge_node_id": "node-A",
        "item_type": "choice", "prompt": "Which one is 40 + 2?",
        "expected_answer": "B", "rubric_json": json.dumps({"note": SECRET_RUBRIC}),
        "difficulty": 1, "content_scope": "BUNDLED", "source_ref": "self-authored (test)",
        "license_note": None, "attribution_text": None, "derived_from_item_id": None,
        "reviewer": None, "reviewed_at": None,
        "content_hash": content_hash("item-A-choice"), "status": "candidate",
        # 选项用英文数词而非阿拉伯数字：MCQ 的正确选项正文天然**就是**答案，
        # 若写成 "42" 会与本文件其他题的 SECRET_ANSWER 撞串，让泄漏断言产生
        # 无意义的假阳性。真正的保证是"不出现 expected_answer/correct_answer
        # 这些字段"，不是"答案的字面值不许出现在任何地方"。
        "choices_json": json.dumps([{"label": "A", "text": "forty-one"},
                                    {"label": "B", "text": "forty-two"}]),
        "explanation": "40 加 2 就是 42。", "explanation_source": "authored",
    }])
    conn.close()


def test_task_set_ships_choices_but_no_answer_or_explanation(client: TestClient, web_db: Path):
    _seed_explained_choice(web_db)
    body = client.get("/api/edu/set", params={
        "learner_id": LEARNER, "course_version_id": CV, "size": 3}).json()

    assert 1 <= len(body["items"]) <= 3
    choice = next(i for i in body["items"] if i["id"] == "item-A-choice")
    assert [c["label"] for c in choice["choices"]] == ["A", "B"], "选项必须结构化，否则渲染不出单选按钮"
    assert choice["node"]["code"] == "A", "出题时就带上知识点，复盘页不用再查一次"

    raw = json.dumps(body, ensure_ascii=False)
    assert "expected_answer" not in raw
    assert "correct_answer" not in raw
    assert "explanation" not in raw, "讲解必须等到整组提交之后"
    assert SECRET_RUBRIC not in raw


def test_set_submit_returns_answer_explanation_and_knowledge_point(client: TestClient, web_db: Path):
    _seed_explained_choice(web_db)
    body = client.post("/api/edu/set/submit", json={
        "learner_id": LEARNER, "course_version_id": CV,
        "answers": [{"item_id": "item-A-choice", "response": "A",
                     "client_attempt_id": "set-1:item-A-choice"}],
    }).json()

    row = body["results"][0]
    assert row["is_correct"] is False
    assert row["your_response"] == "A"
    assert row["correct_answer"] == "B", "整组交完之后，答案才给"
    assert row["explanation"] == "40 加 2 就是 42。"
    assert row["explanation_source"] == "authored", "讲解必须带出处，家长才知道能不能信"
    assert row["knowledge_point"] == {
        "code": "A", "title": "Node A", "standard_code": "4.OA.B.4"}
    assert body["summary"] == {
        "answered": 1, "auto_graded": 1, "correct": 0, "awaiting_review": 0}
    # rubric 仍然一步都不出去 —— 讲解走 explanation 列，不是把 rubric 放行
    assert SECRET_RUBRIC not in json.dumps(body, ensure_ascii=False)


def test_set_submit_records_every_answer_as_a_real_attempt(client: TestClient, web_db: Path):
    _seed_explained_choice(web_db)
    picked = client.get("/api/edu/set", params={
        "learner_id": LEARNER, "course_version_id": CV, "size": 3}).json()["items"]
    client.post("/api/edu/set/submit", json={
        "learner_id": LEARNER, "course_version_id": CV,
        "answers": [{"item_id": i["id"], "response": SECRET_ANSWER,
                     "client_attempt_id": f"set-2:{i['id']}"} for i in picked],
    })
    conn = edu_sqlite.open_database(web_db)
    stored = {r["assessment_item_id"] for r in conn.execute(
        "SELECT assessment_item_id FROM student_attempts WHERE learner_id = ?", (LEARNER,))}
    conn.close()
    assert stored == {i["id"] for i in picked}, "复盘页好看不算数，作答必须真落库"


def test_set_has_no_duplicate_items(client: TestClient, web_db: Path):
    _seed_explained_choice(web_db)
    ids = [i["id"] for i in client.get("/api/edu/set", params={
        "learner_id": LEARNER, "course_version_id": CV, "size": 10}).json()["items"]]
    assert len(ids) == len(set(ids)), "同一张卷子上不该出现两道一模一样的题"


def test_set_submit_rejects_an_item_from_another_course(client: TestClient, web_db: Path):
    """一组里混进别的课的题：整组拒绝，不能先写进去几条再报错。"""
    conn = edu_sqlite.open_database(web_db)
    now = to_iso_timestamp(time.time())
    CourseRepository(conn).create_course(
        Course(id="c-x", subject_key="history", title="X", created_at=now, level="AP-HS"))
    CourseRepository(conn).create_course_version(
        CourseVersion(id="cv-x", course_id="c-x", version="1.0.0", content_hash="3" * 64,
                      status=CourseVersionStatus.ACTIVE, created_at=now))
    KnowledgeGraphRepository(conn).import_nodes_and_edges(
        course_version_id="cv-x",
        nodes=[KnowledgeNode(id="node-X", course_version_id="cv-x", code="X",
                             node_type="concept", title="X", sort_order=1,
                             standard_code="9.X.1")], edges=[])
    AssessmentItemRepository(conn).import_items([{
        "id": "item-X", "course_version_id": "cv-x", "knowledge_node_id": "node-X",
        "item_type": "numeric", "prompt": "1+1?", "expected_answer": "2",
        "rubric_json": None, "difficulty": 1, "content_scope": "BUNDLED",
        "source_ref": "self-authored (test)", "license_note": None, "attribution_text": None,
        "derived_from_item_id": None, "reviewer": None, "reviewed_at": None,
        "content_hash": content_hash("item-X"), "status": "candidate"}])
    conn.close()

    good = _next(client)["item"]["id"]
    r = client.post("/api/edu/set/submit", json={
        "learner_id": LEARNER, "course_version_id": CV,
        "answers": [
            {"item_id": good, "response": SECRET_ANSWER, "client_attempt_id": "mix-1"},
            {"item_id": "item-X", "response": "2", "client_attempt_id": "mix-2"},
        ]})
    assert r.status_code == 403
    conn = edu_sqlite.open_database(web_db)
    n = conn.execute("SELECT COUNT(*) c FROM student_attempts").fetchone()["c"]
    conn.close()
    assert n == 0, "整组校验必须在落库之前，否则前半组已经写进去了"


def test_parent_cannot_submit_a_set(client: TestClient, web_db: Path):
    conn = edu_sqlite.open_database(web_db)
    now = to_iso_timestamp(time.time())
    LearnerRepository(conn).create(LearnerProfile(
        id="parent-s", deep_tutor_user_id="dtu-ps", display_name="家长",
        locale="en-US", created_at=now, updated_at=now))
    EnrollmentRepository(conn).enroll(Enrollment("parent-s", CV, "active", now, now))
    conn.commit(); conn.close()
    r = client.post("/api/edu/set/submit", json={
        "learner_id": "parent-s", "course_version_id": CV,
        "answers": [{"item_id": "item-A-1", "response": "42", "client_attempt_id": "p-1"}]})
    assert r.status_code == 403
