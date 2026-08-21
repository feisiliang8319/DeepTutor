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
from deeptutor.education.application.record_attempt import NewAttemptInput, record_attempt
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


def _issue(client: TestClient, learner: str = LEARNER, cv: str = CV):
    return client.post("/api/edu/set", params={"learner_id": learner, "course_version_id": cv})


def _next(client: TestClient) -> dict:
    """发一组，把第一题包成旧 /api/edu/next 的形状。

    旧端点已删（它能不交卷就问出答案，见 G-1）。helper 保留同名，是为了让那些
    真正想断言"规划器先给哪个节点""同一节点先出哪道题"的用例不必改写 —— 它们
    考的是选题逻辑，不是端点形状。
    """
    r = _issue(client)
    assert r.status_code == 200, r.text
    d = r.json()
    if not d.get("items"):
        return {"done": d.get("done", False), "item": None, "node": None,
                "message": d.get("message"),
                "skipped_empty_nodes": d.get("skipped_empty_nodes", [])}
    first = d["items"][0]
    return {"done": False, "node": first["node"], "item": first,
            "set_id": d["set_id"], "items": d["items"],
            "skipped_empty_nodes": d.get("skipped_empty_nodes", [])}


def _attempt(client: TestClient, item_id: str, response: str, key: str):
    """把当前这一组整组交上去，目标题用给定答案，其余留空。

    整组交是硬要求：服务端只在"交的恰好等于发出去的那一组"时才判分并给答案。
    """
    r = _issue(client)
    assert r.status_code == 200, r.text
    d = r.json()
    ids = [i["id"] for i in d["items"]]
    if item_id not in ids:          # 目标题不在本组（跨课注入等用例）
        ids = ids + [item_id]
    resp = client.post("/api/edu/set/submit", json={
        "learner_id": LEARNER, "course_version_id": CV, "set_id": d["set_id"],
        "answers": [{"item_id": i, "response": response if i == item_id else ""} for i in ids],
    })
    if resp.status_code != 200:
        return resp
    row = next(r for r in resp.json()["results"] if r["item_id"] == item_id)
    return _Merged(resp, row)


class _Merged:
    """让旧断言 `_attempt(...).json()["is_correct"]` 继续读得通：
    对外表现成一个只含目标题那一行的响应。"""

    def __init__(self, resp, row):
        self._resp, self._row = resp, row
        self.status_code = resp.status_code
        self.text = resp.text

    def json(self):
        return self._row


# ---- the leak invariant ---------------------------------------------------


def test_task_set_never_ships_the_answer_or_rubric(client: TestClient):
    """出题面的字段是白名单挑出来的：新加一个字段默认**不**公开。

    （原 test_next_task_never_ships_the_answer_or_rubric。/api/edu/next 已于
    2026-08-21 删除 —— 它配合 /api/edu/attempt 构成"不交卷就能问出答案"的
    判分预言机，见 G-1。这条断言迁到 /api/edu/set 上继续守同一件事。）
    """
    r = _issue(client)
    body = r.text
    assert "expected_answer" not in body
    assert "rubric" not in body
    assert "explanation" not in body, "讲解必须等整组提交之后"
    assert SECRET_RUBRIC not in body
    first = r.json()["items"][0]
    assert first["prompt"] == "What is 40 + 2?"
    assert set(first) == {
        "id", "prompt", "item_type", "difficulty", "attribution",
        "figure_spec_id", "choices", "node",
    }


def test_submit_response_ships_the_answer_but_never_the_rubric(client: TestClient):
    """交卷之后**可以**给答案（这正是需求），但 rubric 仍然一步都不出去。"""
    item_id = _next(client)["item"]["id"]
    r = _attempt(client, item_id, "999", "k1")
    assert r.status_code == 200, r.text
    assert "expected_answer" not in r.text, "字段名不该出现；答案走 correct_answer"
    assert SECRET_RUBRIC not in r.text
    assert r.json()["is_correct"] is False
    assert r.json()["correct_answer"] == SECRET_ANSWER


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
    """同一节点上先出没做过的题。

    成组之后这条更明显：一组里就该把该节点没做过的题铺开，而不是重复同一道。
    """
    ids = [i["id"] for i in _issue(client).json()["items"]]
    assert len(ids) == len(set(ids))
    assert {"item-A-1", "item-A-2"} <= set(ids), "同节点两道题都没做过，应该都出现"


def test_resubmitting_the_same_set_does_not_double_count(client: TestClient):
    """重放一次提交不该把复习次数记两遍。

    2026-08-21 改写：原用例叫 test_same_client_attempt_id_is_idempotent，靠
    `_attempt(..., "same-key")` 连调两次来表达"重放"。幂等键改由服务端从
    (组, 题) 派生之后，那个写法已经**不再是重放** —— helper 每次都会领一张新
    卷子，两次提交是两次货真价实的作答。改为直接把同一张卷子交两遍。
    """
    issued = _issue(client).json()
    body = _submit_all(client, issued, SECRET_ANSWER).json()
    assert body["summary"]["answered"] == len(issued["items"])
    # 判据是"重放前后不变"，不是"等于 1"：一组里同一个知识点上有几道题，
    # 首次提交本来就会把该节点的复习次数推进几次。
    before = {r["item_id"]: (r["review"] or {}).get("reps") for r in body["results"]}

    again = _submit_all(client, issued, SECRET_ANSWER).json()
    after = {r["item_id"]: (r["review"] or {}).get("reps") for r in again["results"]}
    assert after == before, f"重放把复习次数又推了一遍：{before} -> {after}"


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

    body = TestClient(create_app(db_path)).post(
        "/api/edu/set", params={"learner_id": LEARNER, "course_version_id": CV}
    ).json()
    assert [i["node"]["code"] for i in body["items"]] == ["HAS"], \
        "should walk past the empty node, not dead-end on it"
    assert body["items"][0]["id"] == "item-has-1"
    assert body["skipped_empty_nodes"] == ["EMPTY"], "the content gap must be reported, not hidden"


def test_unknown_learner_is_404_not_an_empty_task(web_db: Path):
    r = TestClient(create_app(web_db)).get(
        "/api/edu/next", params={"learner_id": "nobody", "course_version_id": CV}
    )
    assert r.status_code == 404


def test_item_outside_the_issued_set_is_rejected(client: TestClient):
    """交一道没发给你的题 —— 无论它存不存在，都在成员校验这一步就被挡下。

    这条比原来的"未知题 400"更靠前也更重要：能往组里塞题，就能拿到没发给自己
    的题的答案。（原 test_unknown_item_is_400。）
    """
    r = _attempt(client, "item-does-not-exist", "1", "k-bad")
    assert r.status_code == 400
    assert "必须整组一起交" in r.json()["detail"]
    assert "item-does-not-exist" in r.json()["detail"]


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
    r = client.post("/api/edu/set/submit", json={
        "learner_id": "parent-x", "course_version_id": CV, "set_id": "set-whatever",
        "answers": [{"item_id": "item-A-1", "response": "42"}]})
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


def _seed_pending_attempt(db_path: Path, response: str, key: str) -> None:
    """直接经应用层写一条待复核作答。

    不走 HTTP：开放题没接 judge 时不会被出题，因而进不了发出去的那一组。
    这三条用例要的是"队列里有一条待复核"，作答从哪来无关紧要。
    """
    conn = edu_sqlite.open_database(db_path)
    now = to_iso_timestamp(time.time())
    try:
        record_attempt(conn, NewAttemptInput(
            learner_id=LEARNER, assessment_item_id="item-open", response=response,
            started_at=now, submitted_at=now, source="web", client_attempt_id=key))
        conn.commit()
    finally:
        conn.close()


def test_review_queue_surfaces_unresolved_attempts(judge_free_db: Path):
    """needs_review 不该是个没人消费的状态：家长视角靠这个队列看到它。"""
    _seed_pending_attempt(judge_free_db, "I drew it on paper", "q1")
    client = TestClient(create_app(judge_free_db))
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
    _seed_pending_attempt(judge_free_db, "I drew all four rectangles", "r1")
    client = TestClient(create_app(judge_free_db))
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
    _seed_pending_attempt(judge_free_db, "trust me", "r2")
    client = TestClient(create_app(judge_free_db))
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
    issued = _issue(client).json()                  # 退选前正常领到一组
    conn = edu_sqlite.open_database(web_db)
    EnrollmentRepository(conn).set_status(
        LEARNER, CV, "withdrawn", at=to_iso_timestamp(time.time()))
    conn.commit(); conn.close()

    assert client.post("/api/edu/set", params={
        "learner_id": LEARNER, "course_version_id": CV}).status_code == 403
    assert client.get("/api/edu/progress", params={
        "learner_id": LEARNER, "course_version_id": CV}).status_code == 403
    # 最要紧的一条：退选后不能再往这门课写作答，否则掌握度证据会长在已退的课上。
    # 拿着退选**之前**领到的那张卷子交，也必须被挡下 —— 领卷时有权限不代表交卷时还有。
    assert client.post("/api/edu/set/submit", json={
        "learner_id": LEARNER, "course_version_id": CV, "set_id": issued["set_id"],
        "answers": [{"item_id": i["id"], "response": SECRET_ANSWER}
                    for i in issued["items"]]}).status_code == 403


def test_attempt_checks_the_items_course_not_the_payload_field(client: TestClient, web_db: Path):
    """防"校验剧场"：payload.course_version_id 不参与落库，照它校验等于没校验。

    record_attempt 从 item 反查 course_version_id，所以这里必须按 item 实际所属
    课程判。构造：learner 退掉了 item 所在的课，却在 payload 里报一门他确实选了
    的课 —— 若校验打在 payload 上，这一条会被放行。
    """
    issued = _issue(client).json()
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

    r = client.post("/api/edu/set/submit", json={
        "learner_id": LEARNER, "course_version_id": "cv-other",   # 谎报一门他选了的课
        "set_id": issued["set_id"],
        "answers": [{"item_id": i["id"], "response": SECRET_ANSWER} for i in issued["items"]]})
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
    body = client.post("/api/edu/set", params={
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
    issued = _issue(client).json()
    body = client.post("/api/edu/set/submit", json={
        "learner_id": LEARNER, "course_version_id": CV, "set_id": issued["set_id"],
        "answers": [{"item_id": i["id"],
                     "response": "A" if i["id"] == "item-A-choice" else ""} for i in issued["items"]],
    }).json()
    assert any(i["id"] == "item-A-choice" for i in issued["items"])

    row = next(r for r in body["results"] if r["item_id"] == "item-A-choice")
    assert row["is_correct"] is False
    assert row["your_response"] == "A"
    assert row["correct_answer"] == "B", "整组交完之后，答案才给"
    assert row["explanation"] == "40 加 2 就是 42。"
    assert row["explanation_source"] == "authored", "讲解必须带出处，家长才知道能不能信"
    assert row["knowledge_point"] == {
        "code": "A", "title": "Node A", "standard_code": "4.OA.B.4"}
    assert body["summary"]["answered"] == len(issued["items"])
    assert body["summary"]["correct"] == 0
    # rubric 仍然一步都不出去 —— 讲解走 explanation 列，不是把 rubric 放行
    assert SECRET_RUBRIC not in json.dumps(body, ensure_ascii=False)


def test_set_submit_records_every_answer_as_a_real_attempt(client: TestClient, web_db: Path):
    _seed_explained_choice(web_db)
    issued = _issue(client).json()
    picked = issued["items"]
    client.post("/api/edu/set/submit", json={
        "learner_id": LEARNER, "course_version_id": CV, "set_id": issued["set_id"],
        "answers": [{"item_id": i["id"], "response": SECRET_ANSWER} for i in picked],
    })
    conn = edu_sqlite.open_database(web_db)
    stored = {r["assessment_item_id"] for r in conn.execute(
        "SELECT assessment_item_id FROM student_attempts WHERE learner_id = ?", (LEARNER,))}
    conn.close()
    assert stored == {i["id"] for i in picked}, "复盘页好看不算数，作答必须真落库"


def test_set_has_no_duplicate_items(client: TestClient, web_db: Path):
    _seed_explained_choice(web_db)
    ids = [i["id"] for i in _issue(client).json()["items"]]
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

    issued = _issue(client).json()
    answers = [{"item_id": i["id"], "response": SECRET_ANSWER} for i in issued["items"]]
    answers.append({"item_id": "item-X", "response": "2"})
    r = client.post("/api/edu/set/submit", json={
        "learner_id": LEARNER, "course_version_id": CV,
        "set_id": issued["set_id"], "answers": answers})
    # 成员校验先于一切落库：多塞一道别的课的题，整组拒绝
    assert r.status_code == 400
    assert "多出" in r.json()["detail"]
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
        "learner_id": "parent-s", "course_version_id": CV, "set_id": "set-whatever",
        "answers": [{"item_id": "item-A-1", "response": "42"}]})
    assert r.status_code == 403


# ---- 判分预言机：不交卷就不许拿到答案 ------------------------------------
#
# 2026-08-21 第二轮质检席 G-1（CRITICAL）：旧的 /api/edu/next + /api/edu/attempt
# 还活着，直接 POST 就能对同一道选择题连猜 A/B/C/D 逐次拿 is_correct，四次以内
# 必中，而且每次猜测都写进 append-only 的掌握度证据表。当时的 commit message
# 自己写了"旧路径与这条要求冲突"，代码却没动 —— 这是最危险的一种言行不一。


@pytest.mark.parametrize("method,path", [
    ("get", "/api/edu/next"),
    ("post", "/api/edu/attempt"),
])
def test_the_old_per_question_endpoints_are_gone(client: TestClient, method, path):
    """旧路由必须**物理下线**，不是"前端不再调用它"就算数。

    可达性与使用习惯是两条完全不同的边界：前端不调它，任何 HTTP 客户端仍能调。
    """
    r = getattr(client, method)(path, **({"json": {}} if method == "post" else {}))
    assert r.status_code == 404, f"{path} 仍然可达"


def test_partial_submission_gets_no_answers(client: TestClient, web_db: Path):
    """少交几题就想拿答案 = 逐题即时反馈，必须整组拒绝且一条都不落库。"""
    issued = _issue(client).json()
    assert len(issued["items"]) >= 2, "这条用例需要一组至少两题"
    r = client.post("/api/edu/set/submit", json={
        "learner_id": LEARNER, "course_version_id": CV, "set_id": issued["set_id"],
        "answers": [{"item_id": issued["items"][0]["id"], "response": SECRET_ANSWER}]})
    assert r.status_code == 400
    assert "必须整组一起交" in r.json()["detail"]
    assert "correct_answer" not in r.text
    conn = edu_sqlite.open_database(web_db)
    n = conn.execute("SELECT COUNT(*) c FROM student_attempts").fetchone()["c"]
    conn.close()
    assert n == 0, "被拒的提交不该留下任何作答痕迹"


def test_cannot_submit_someone_elses_set(client: TestClient, web_db: Path):
    conn = edu_sqlite.open_database(web_db)
    now = to_iso_timestamp(time.time())
    LearnerRepository(conn).create(LearnerProfile(
        id="learner-other", deep_tutor_user_id="dtu-o", display_name="Other",
        locale="en-US", created_at=now, updated_at=now))
    EnrollmentRepository(conn).enroll(Enrollment("learner-other", CV, "active", now, now))
    conn.commit(); conn.close()

    mine = _issue(client).json()
    r = client.post("/api/edu/set/submit", json={
        "learner_id": "learner-other", "course_version_id": CV, "set_id": mine["set_id"],
        "answers": [{"item_id": i["id"], "response": "x"} for i in mine["items"]]})
    assert r.status_code == 404, "别人的卷子不能拿来交，否则等于拿别人的题问答案"


def test_an_open_set_is_reissued_not_rerolled(client: TestClient):
    """没交就刷新，应该拿回同一组；否则"这组做完再讲"变成"挑到会做的为止"。"""
    first = _issue(client).json()
    again = _issue(client).json()
    assert again["set_id"] == first["set_id"]
    assert again["reissued"] is True
    assert [i["id"] for i in again["items"]] == [i["id"] for i in first["items"]]


def test_a_new_set_is_issued_after_the_previous_one_is_submitted(client: TestClient):
    first = _issue(client).json()
    client.post("/api/edu/set/submit", json={
        "learner_id": LEARNER, "course_version_id": CV, "set_id": first["set_id"],
        "answers": [{"item_id": i["id"], "response": SECRET_ANSWER} for i in first["items"]]})
    second = _issue(client).json()
    assert second["set_id"] != first["set_id"]


def test_size_is_server_side_not_a_query_parameter(web_db: Path):
    """题量不能由客户端说了算。

    能自选"这一组就一道题"，交上去立刻拿答案 —— 那就是逐题即时反馈换了个入口，
    正是 Sol 要求去掉的东西。所以 size 是 create_app 的参数（生产由 EDU_SET_SIZE
    环境变量注入），请求里带 size 一律无效。
    """
    small = TestClient(create_app(web_db, set_size=1))
    body = small.post("/api/edu/set", params={
        "learner_id": LEARNER, "course_version_id": CV}).json()
    assert len(body["items"]) == 1, "题量由服务端配置决定"

    # 同一组还没交，带上 size=10 也只能拿回原组
    ignored = small.post("/api/edu/set", params={
        "learner_id": LEARNER, "course_version_id": CV, "size": 10}).json()
    assert len(ignored["items"]) == 1, "size 参数必须被忽略"
    assert ignored["set_id"] == body["set_id"]


def test_default_set_has_more_than_one_question(client: TestClient):
    """默认题量 > 1 —— 一组一题等于逐题即时反馈。"""
    assert len(_issue(client).json()["items"]) > 1


# ---- 状态机边界：已终结的资源要真的终结，并发下不能造出孪生资源 ----------
#
# 2026-08-21 第三轮质检席三条 CRITICAL 的回归。它们的共同点：功能测试全绿时
# 完全不可见 —— 只有对「资源生命周期状态转换」做重放与并发注入才会暴露。
# 上一轮测试有精确对应的覆盖缺口：全文件对"重复交/已交"零命中、无并发用例、
# 复用 client_attempt_id 时两次传的是**相同** response（于是回显错配测不出来）。


def _submit_all(client: TestClient, issued: dict, response: str):
    return client.post("/api/edu/set/submit", json={
        "learner_id": LEARNER, "course_version_id": CV, "set_id": issued["set_id"],
        "answers": [{"item_id": i["id"], "response": response} for i in issued["items"]]})


def test_resubmitting_a_submitted_set_never_regrades(client: TestClient, web_db: Path):
    """CRITICAL-1：先交垃圾骗出答案，再换一批 key 照抄正确答案交同一组。

    重放必须原样返回**第一次**那份复盘：不写新作答、不重新判分。
    """
    issued = _issue(client).json()
    first = _submit_all(client, issued, "definitely-wrong").json()
    assert first["summary"]["correct"] == 0
    answers = {r["item_id"]: r["correct_answer"] for r in first["results"]}

    conn = edu_sqlite.open_database(web_db)
    n_before = conn.execute("SELECT COUNT(*) c FROM student_attempts").fetchone()["c"]
    conn.close()

    cheat = client.post("/api/edu/set/submit", json={
        "learner_id": LEARNER, "course_version_id": CV, "set_id": issued["set_id"],
        "answers": [{"item_id": i, "response": a or ""}
                    for i, a in answers.items()]})
    assert cheat.status_code == 200
    assert cheat.json()["summary"]["correct"] == 0, "抄了答案重交也不该改判"
    for row in cheat.json()["results"]:
        assert row["your_response"] == "definitely-wrong", "回显必须是落库的那条"

    conn = edu_sqlite.open_database(web_db)
    n_after = conn.execute("SELECT COUNT(*) c FROM student_attempts").fetchone()["c"]
    conn.close()
    assert n_after == n_before, "重放不该再写一条作答"


def test_only_one_open_set_per_course_even_under_concurrency(client: TestClient, web_db: Path):
    """CRITICAL-2：并发发卷曾造出两个 set_id、题面相同的孪生卷子。

    孪生卷子让"同一组不许重复交"那条补丁失效 —— 两张卷子各交一次都合法，
    先用 A 骗答案、再用 B 照抄。所以唯一性必须由数据库强制（migration 006），
    应用层的先查后写只能收窄窗口，收窄不等于关闭。
    """
    import threading
    results: list[dict] = []
    lock = threading.Lock()

    def grab():
        c = TestClient(create_app(web_db))
        r = c.post("/api/edu/set", params={"learner_id": LEARNER, "course_version_id": CV})
        with lock:
            results.append(r.json())

    threads = [threading.Thread(target=grab) for _ in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len({r["set_id"] for r in results}) == 1, \
        f"并发下发出了多张卷子: {sorted({r['set_id'] for r in results})}"
    conn = edu_sqlite.open_database(web_db)
    open_rows = conn.execute(
        "SELECT COUNT(*) c FROM task_sets WHERE submitted_at IS NULL").fetchone()["c"]
    conn.close()
    assert open_rows == 1


def test_replay_echoes_the_stored_answer_not_the_new_payload(client: TestClient):
    """重放同一组、换一段新乱码，回显必须是**落库的那条**。

    （原名 test_replayed_client_attempt_id_echoes_what_was_stored。幂等键已于
    2026-08-21 改由服务端从 (set_id, item_id) 派生，`client_attempt_id` 字段
    也已从请求体移除，名字里再提它会误导后来的读者。不变量本身没变。）

    第四轮质检席 CRITICAL-3：底层幂等地保留了首次作答（正确），但响应把
    "新乱码 + 旧判分"拼在一起回吐，构成"乱打也算对"的展示层假象。
    """
    issued = _issue(client).json()
    _submit_all(client, issued, SECRET_ANSWER)
    replay = client.post("/api/edu/set/submit", json={
        "learner_id": LEARNER, "course_version_id": CV, "set_id": issued["set_id"],
        "answers": [{"item_id": i["id"], "response": "garbage-!!!"} for i in issued["items"]]})
    assert replay.status_code == 200
    for row in replay.json()["results"]:
        assert row["your_response"] != "garbage-!!!"
        assert row["your_response"] == SECRET_ANSWER


# ---- 第四轮质检席：交卷这一步自己的竞态，以及"交到一半失败"的僵尸态 --------


def test_concurrent_submit_of_one_set_grades_once(client: TestClient, web_db: Path):
    """A-新1：并发提交同一组曾被评分两遍。

    根因是 `already_submitted` 在函数入口读一次就不再复核 —— 那句
    `UPDATE ... WHERE submitted_at IS NULL` 虽然对输掉竞态的一路静默 no-op，
    它仍然照走"新作答"分支。**双击提交按钮就能触发，不需要恶意脚本。**
    """
    import threading
    issued = _issue(client).json()
    ids = [i["id"] for i in issued["items"]]
    codes: list[int] = []
    lock = threading.Lock()

    def go(tag: str):
        c = TestClient(create_app(web_db))
        r = c.post("/api/edu/set/submit", json={
            "learner_id": LEARNER, "course_version_id": CV, "set_id": issued["set_id"],
            "answers": [{"item_id": i, "response": tag} for i in ids]})
        with lock:
            codes.append(r.status_code)

    threads = [threading.Thread(target=go, args=(t,)) for t in ("AAAA", "BBBB")]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    conn = edu_sqlite.open_database(web_db)
    n = conn.execute("SELECT COUNT(*) c FROM student_attempts").fetchone()["c"]
    responses = {r["response"] for r in conn.execute("SELECT response FROM student_attempts")}
    conn.close()
    assert n == len(ids), f"同一组被评分了不止一次：{n} 条作答，期望 {len(ids)}"
    assert len(responses) == 1, f"两路作答都落了库：{responses}"
    assert sorted(codes) == [200, 409] or codes == [200, 200], codes


def test_retired_item_voids_the_open_set_instead_of_reissuing_it(
        client: TestClient, web_db: Path):
    """A-新2 前半：组里有题被下架，重发时必须整组作废，而不是照发。

    照发的后果不是"少一道题"，而是孩子答完提交时才在判分层炸掉，
    而那时这一组已被标记已交 —— 永久卡死、那次复盘丢失。
    """
    issued = _issue(client).json()
    victim = issued["items"][0]["id"]
    conn = edu_sqlite.open_database(web_db)
    conn.execute("UPDATE assessment_items SET status = 'retired' WHERE id = ?", (victim,))
    conn.commit(); conn.close()

    again = _issue(client).json()
    assert again["set_id"] != issued["set_id"], "含下架题的组必须作废重发"
    assert victim not in [i["id"] for i in again["items"]]


def test_retired_item_at_submit_time_does_not_burn_the_set(client: TestClient, web_db: Path):
    """A-新2 后半：即使下架发生在领卷之后、提交之前，也必须在**认领这一组之前**
    就拒绝，让孩子还能重来。"""
    issued = _issue(client).json()
    ids = [i["id"] for i in issued["items"]]
    conn = edu_sqlite.open_database(web_db)
    conn.execute("UPDATE assessment_items SET status = 'retired' WHERE id = ?", (ids[1],))
    conn.commit(); conn.close()

    r = client.post("/api/edu/set/submit", json={
        "learner_id": LEARNER, "course_version_id": CV, "set_id": issued["set_id"],
        "answers": [{"item_id": i, "response": SECRET_ANSWER} for i in ids]})
    assert r.status_code == 409

    conn = edu_sqlite.open_database(web_db)
    row = conn.execute("SELECT submitted_at FROM task_sets WHERE id = ?",
                       (issued["set_id"],)).fetchone()
    n = conn.execute("SELECT COUNT(*) c FROM student_attempts").fetchone()["c"]
    conn.close()
    assert row["submitted_at"] is None, "被拒的提交不该把这一组标记成已交"
    assert n == 0, "被拒的提交不该留下半组作答"

    fresh = _issue(client).json()          # 还能继续用
    assert fresh["set_id"] != issued["set_id"]


def test_issuing_a_set_is_a_post_not_a_get(client: TestClient):
    """发卷会 INSERT 一行；挂在 GET 上曾让两个人在"只读复验"时写进生产库。"""
    assert client.get("/api/edu/set", params={
        "learner_id": LEARNER, "course_version_id": CV}).status_code == 405


# ---- 自愈分支（补齐上次没写完的题）本身的并发 ---------------------------
#
# 2026-08-21 第五轮质检席（CRITICAL）：为修"僵尸组"引入的自愈分支，在**题**这一层
# 原样复刻了刚在**组**这一层用 CAS 修掉的反模式 —— `stored` 快照只在函数入口读
# 一次，循环内逐题拿它判断"缺不缺"，两路并发都判"缺"、都去写。
# 实测 3 路即触发（两个标签页 / 一次网络自动重试撞上原生提交就够），
# 16 路时一道题落 5~6 条矛盾作答，review_states.lapses 被推到 11。


def _force_partial_submission(web_db: Path, set_id: str, keep: int) -> None:
    """把一组做成"已标记已交、但只写了前 keep 题"，且时间戳退到宽限期之外。"""
    conn = edu_sqlite.open_database(web_db)
    row = conn.execute("SELECT item_ids_json FROM task_sets WHERE id = ?", (set_id,)).fetchone()
    ids = json.loads(row["item_ids_json"])
    long_ago = to_iso_timestamp(time.time() - 3600)
    for item_id in ids[:keep]:
        record_attempt(conn, NewAttemptInput(
            learner_id=LEARNER, assessment_item_id=item_id, response="partial",
            started_at=long_ago, submitted_at=long_ago, source="web",
            client_attempt_id=f"{set_id}:{item_id}"))
    conn.execute("UPDATE task_sets SET submitted_at = ? WHERE id = ?", (long_ago, set_id))
    conn.commit(); conn.close()


def test_self_heal_writes_each_missing_item_exactly_once_under_concurrency(
        client: TestClient, web_db: Path):
    import threading
    issued = _issue(client).json()
    ids = [i["id"] for i in issued["items"]]
    _force_partial_submission(web_db, issued["set_id"], keep=1)

    barrier = threading.Barrier(8)

    def go(tag: str):
        c = TestClient(create_app(web_db))
        barrier.wait()
        c.post("/api/edu/set/submit", json={
            "learner_id": LEARNER, "course_version_id": CV, "set_id": issued["set_id"],
            "answers": [{"item_id": i, "response": f"race-{tag}"} for i in ids]})

    threads = [threading.Thread(target=go, args=(str(i),)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    conn = edu_sqlite.open_database(web_db)
    rows = list(conn.execute(
        "SELECT assessment_item_id, COUNT(*) c FROM student_attempts "
        "WHERE learner_id = ? GROUP BY 1", (LEARNER,)))
    lapses = [r["lapses"] for r in conn.execute(
        "SELECT lapses FROM review_states WHERE learner_id = ?", (LEARNER,))]
    conn.close()
    dupes = {r["assessment_item_id"]: r["c"] for r in rows if r["c"] > 1}
    assert not dupes, f"同一题落了多条作答：{dupes}"
    assert len(rows) == len(ids), f"补齐后应恰好每题一条：{rows}"
    assert all(n <= len(ids) for n in lapses), f"FSRS 状态被重复写入推高了：{lapses}"


def test_within_grace_period_a_partial_set_asks_you_to_wait(client: TestClient, web_db: Path):
    """宽限期内残缺 = 另一路正在写，让它重试，别去补写。"""
    issued = _issue(client).json()
    ids = [i["id"] for i in issued["items"]]
    conn = edu_sqlite.open_database(web_db)
    now = to_iso_timestamp(time.time())
    record_attempt(conn, NewAttemptInput(
        learner_id=LEARNER, assessment_item_id=ids[0], response="x",
        started_at=now, submitted_at=now, source="web",
        client_attempt_id=f"{issued['set_id']}:{ids[0]}"))
    conn.execute("UPDATE task_sets SET submitted_at = ? WHERE id = ?", (now, issued["set_id"]))
    conn.commit(); conn.close()

    r = client.post("/api/edu/set/submit", json={
        "learner_id": LEARNER, "course_version_id": CV, "set_id": issued["set_id"],
        "answers": [{"item_id": i, "response": "y"} for i in ids]})
    assert r.status_code == 409
    assert "稍等" in r.json()["detail"]

    conn = edu_sqlite.open_database(web_db)
    n = conn.execute("SELECT COUNT(*) c FROM student_attempts").fetchone()["c"]
    conn.close()
    assert n == 1, "宽限期内不该补写任何作答"


def test_self_heal_never_regrades_the_items_already_stored(client: TestClient, web_db: Path):
    """补齐缺的题时，已落库的那几题必须原样回读 —— 否则"先探再补"就成了新预言机。"""
    issued = _issue(client).json()
    ids = [i["id"] for i in issued["items"]]
    _force_partial_submission(web_db, issued["set_id"], keep=2)

    body = client.post("/api/edu/set/submit", json={
        "learner_id": LEARNER, "course_version_id": CV, "set_id": issued["set_id"],
        "answers": [{"item_id": i, "response": SECRET_ANSWER} for i in ids]}).json()
    by_id = {r["item_id"]: r for r in body["results"]}
    for i in ids[:2]:
        assert by_id[i]["your_response"] == "partial", "已落库的题不该被这次答案覆盖"
        assert by_id[i]["is_correct"] is False
    for i in ids[2:]:
        assert by_id[i]["your_response"] == SECRET_ANSWER


def test_attempt_ids_are_derived_by_the_server_from_set_and_item(
        client: TestClient, web_db: Path):
    """去重键必须由服务端派生，不能由客户端自选。

    `student_attempts.id` 就是幂等键，`AttemptRepository.insert` 用
    `INSERT OR IGNORE` 在主键上做去重 —— 机制一直都在，但只要客户端每次重试
    都换个新键，它就等于自己把去重关掉了（第五轮质检席的并发攻击正是这么打的）。

    这条断言是**确定性**的：它不依赖能不能在测试里复现出真并发，直接检查
    落库的主键形状。上一版只写了并发用例，而 TestClient 下的多线程实际被
    SQLite 串行化，把"幂等键换回客户端可控"注进去也照样绿 —— 那样的用例
    保护不了这条不变量。
    """
    issued = _issue(client).json()
    _submit_all(client, issued, SECRET_ANSWER)
    conn = edu_sqlite.open_database(web_db)
    ids = {r["id"] for r in conn.execute(
        "SELECT id FROM student_attempts WHERE learner_id = ?", (LEARNER,))}
    conn.close()
    assert ids == {f"{issued['set_id']}:{i['id']}" for i in issued["items"]}


def test_one_review_state_per_node_is_reported_consistently(client: TestClient):
    """同一知识点上的几道题，复盘里报的复习次数必须一致。

    循环内逐题读会读到**中途快照**：先落库的那几行拿到的是还没数完的值，
    同一份复盘里同一个知识点出现两个数。终态统一在循环结束后取。
    """
    issued = _issue(client).json()
    body = _submit_all(client, issued, SECRET_ANSWER).json()
    per_node: dict[str, set] = {}
    for row, item in zip(body["results"], issued["items"]):
        code = item["node"]["code"]
        per_node.setdefault(code, set()).add(
            None if row["review"] is None else row["review"]["reps"])
    for code, values in per_node.items():
        assert len(values) == 1, f"知识点 {code} 在同一份复盘里报了 {values}"


def test_a_smuggled_client_attempt_id_is_ignored(client: TestClient, web_db: Path):
    """请求体里夹带 client_attempt_id 必须无效。

    该字段已从 `SetAnswer` 移除，pydantic 默认把多余字段静默丢掉 —— 行为是对的，
    但"对"是默认配置给的，没有任何测试钉住它。哪天有人给模型加上
    `model_config = ConfigDict(extra="allow")`，或顺手把字段加回来，客户端就又能
    自选去重键了（第五轮质检席那条 CRITICAL 的入口）。这条负面测试就是那颗钉子。
    """
    issued = _issue(client).json()
    r = client.post("/api/edu/set/submit", json={
        "learner_id": LEARNER, "course_version_id": CV, "set_id": issued["set_id"],
        "answers": [{"item_id": i["id"], "response": SECRET_ANSWER,
                     "client_attempt_id": f"smuggled-{i['id']}"} for i in issued["items"]]})
    assert r.status_code == 200

    conn = edu_sqlite.open_database(web_db)
    ids = {row["id"] for row in conn.execute(
        "SELECT id FROM student_attempts WHERE learner_id = ?", (LEARNER,))}
    conn.close()
    assert ids == {f"{issued['set_id']}:{i['id']}" for i in issued["items"]}
    assert not any(i.startswith("smuggled-") for i in ids), "夹带的键不该成为落库主键"
