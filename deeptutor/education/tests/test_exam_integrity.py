"""Independent-exam lifecycle: interrupted answers cannot become mastery."""

from fastapi import HTTPException
import pytest

from deeptutor.education.application import assessment_engine as engine
from deeptutor.education.application import exam_integrity as integrity
from deeptutor.education.storage.repositories import AssessmentItemRepository
from deeptutor.education.storage.sqlite import check_trigger_integrity
from deeptutor.education.tests.test_formal_assessment import formal as _formal_fixture
from deeptutor.education.tests.test_web_loop import CV, LEARNER, web_db  # noqa: F401

formal = _formal_fixture

SESSION = "synthetic-page-session-1234567890123456"


def start(formal, kind="competition"):
    return engine.issue(formal[0], LEARNER, CV, kind, page_session=SESSION)


def post(formal, exam, session=SESSION):
    conn, client = formal
    payload = dict(
        learner_id=LEARNER,
        course_version_id=CV,
        set_id=exam["set_id"],
        answers=[
            {
                "item_id": i["id"],
                "response": AssessmentItemRepository(conn).get(i["id"]).expected_answer,
            }
            for i in exam["items"]
        ],
    )
    return client.post("/api/edu/set/submit", json=payload, headers={"X-Quiz-Session": session})


@pytest.mark.parametrize("reason", ["page_hidden", "page_left", "connection_lost"])
def test_leaving_is_durable_and_cannot_grade_or_promote(formal, reason):
    conn, _ = formal
    exam = start(formal)
    first = exam["items"][0]["id"]
    engine.save_draft(conn, exam["set_id"], {first: "saved response"}, 0, page_session=SESSION)
    assert integrity.inspect(conn, exam["set_id"], SESSION, reason=reason)["state"] == "invalidated"
    assert post(formal, exam).json()["assessment"]["status"] == "invalidated"
    assert engine.finalize(conn, exam["set_id"], parent_actor="parent")["passed"] is False
    assert (
        engine.save_draft(conn, exam["set_id"], {first: "replacement"}, 1, page_session=SESSION)[
            "assessment"
        ]["status"]
        == "invalidated"
    )
    assert "saved response" in conn.execute("SELECT answers_json FROM exam_drafts").fetchone()[0]
    assert conn.execute("SELECT COUNT(*) FROM student_attempts").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM promotion_events").fetchone()[0] == 0
    assert conn.execute("SELECT grade FROM subject_placements").fetchone()[0] == 4
    assert not check_trigger_integrity(conn)


def test_reload_new_session_cannot_resume_and_parent_retake_does_not_revalidate(formal):
    conn, _ = formal
    exam = start(formal)
    integrity.inspect(conn, exam["set_id"], "new-page-session-0000000000000000")
    with pytest.raises(HTTPException):
        start(formal)
    integrity.allow_retake(conn, exam["set_id"], "linked-parent")
    integrity.allow_retake(conn, exam["set_id"], "linked-parent")
    assert engine.public_exam(conn, exam["set_id"])["result"]["integrity"]["retake_authorized_at"]
    assert post(formal, exam).json()["assessment"]["passed"] is False
    second = start(formal)
    assert second["set_id"] != exam["set_id"]
    assert not {i["id"] for i in exam["items"]} & {i["id"] for i in second["items"]}
    assert (
        conn.execute(
            "SELECT COUNT(*) FROM exam_integrity_events WHERE kind='retake_authorized'"
        ).fetchone()[0]
        == 1
    )


def test_missing_session_direct_submit_is_invalidated(formal):
    conn, _ = formal
    exam = start(formal)
    result = post(formal, exam, session="").json()["assessment"]
    assert result["status"] == "invalidated" and not result["passed"]
    assert integrity.status(conn, exam["set_id"])["state"] == "invalidated"


def test_heartbeat_loss_before_deadline_cannot_be_recovered(formal, monkeypatch):
    conn, _ = formal
    exam = start(formal)
    last = conn.execute("SELECT last_seen FROM exam_integrity").fetchone()[0]
    monkeypatch.setattr(integrity.time, "time", lambda: last + 61)
    assert (
        integrity.inspect(conn, exam["set_id"], SESSION, heartbeat=True)["reason"]
        == "connection_lost"
    )
    assert post(formal, exam).json()["assessment"]["status"] == "invalidated"


def test_deadline_uses_only_received_draft_even_if_tab_closes_after_time(formal, monkeypatch):
    conn, _ = formal
    exam = start(formal)
    item = exam["items"][0]["id"]
    answer = AssessmentItemRepository(conn).get(item).expected_answer
    engine.save_draft(conn, exam["set_id"], {item: answer}, 0, page_session=SESSION)
    conn.execute(
        "UPDATE exam_integrity SET last_seen=? WHERE set_id=?",
        (exam["deadline"] - 1, exam["set_id"]),
    )
    monkeypatch.setattr(integrity.time, "time", lambda: exam["deadline"] + 1)
    integrity.inspect(conn, exam["set_id"], SESSION, reason="page_left")
    result = post(formal, exam).json()["assessment"]
    assert result["status"] == "final" and result["percent"] == 5
    assert integrity.status(conn, exam["set_id"])["state"] == "sealed"


def test_submitted_exam_ignores_late_unload_and_duplicate_requests(formal):
    conn, _ = formal
    exam = start(formal)
    first = post(formal, exam).json()["assessment"]
    assert first["passed"] and first["promotion"]["to_grade"] == 5
    assert integrity.inspect(conn, exam["set_id"], SESSION, reason="page_left")["state"] == "sealed"
    assert (
        post(formal, exam, session="different").json()["assessment"]["promotion"]["to_grade"] == 5
    )
    assert conn.execute("SELECT COUNT(*) FROM promotion_events").fetchone()[0] == 1


def test_resource_gate_blocks_same_student_but_not_sibling_and_no_old_answers(formal):
    conn, _ = formal
    exam = start(formal)
    for path in (
        "/api/edu/lessons/number-structure",
        "/api/edu/topics",
        "/api/edu/assessments/other",
        "/api/edu/figures/unrelated",
    ):
        with pytest.raises(HTTPException) as e:
            integrity.guard_education_request(conn, "dtu-web", path, "GET")
        assert e.value.status_code == 423
        integrity.guard_education_request(conn, "unrelated", path, "GET")
    integrity.guard_education_request(
        conn, "dtu-web", f"/api/edu/assessments/{exam['set_id']}/presence", "POST"
    )
    with pytest.raises(HTTPException):
        integrity.guard_submission_target(conn, "dtu-web", "another-set")
    integrity.inspect(conn, exam["set_id"], SESSION, reason="page_hidden")
    integrity.guard_education_request(conn, "dtu-web", "/api/edu/lessons/number-structure", "GET")


def test_http_chat_and_attachment_gate_during_exam(formal, monkeypatch):
    from deeptutor.multi_user import teaching_evidence, teaching_identity

    conn, _ = formal
    start(formal)
    path = conn.execute("PRAGMA database_list").fetchone()["file"]
    monkeypatch.setenv("TEACHING_EDUCATION_DB", path)
    monkeypatch.setattr(teaching_identity, "active", lambda: True)
    for path in ("/api/v1/sessions", "/api/attachments/old-image", "/api/v1/voice/stt"):
        with pytest.raises(HTTPException) as e:
            teaching_evidence.enforce_exam_access("dtu-web", "student", path)
        assert e.value.status_code == 423
    teaching_evidence.enforce_exam_access("dtu-web", "student", "/api/v1/auth/status")
    teaching_evidence.enforce_exam_access("parent", "parent", "/api/v1/teaching/students")


@pytest.fixture
def protected_api(formal, monkeypatch):
    from types import SimpleNamespace

    from fastapi.testclient import TestClient

    from deeptutor.education.api.account_identity import AccountIdentity
    from deeptutor.education.api.app import create_app
    from deeptutor.multi_user import identity, teaching_grants, teaching_identity

    conn, _ = formal

    class Access:
        def authenticate(self, request):
            name = request.headers.get("authorization", "").removeprefix("Bearer ")
            if name not in {"student", "parent", "outsider"}:
                raise HTTPException(401, "login")
            return AccountIdentity(
                name,
                "dtu-web" if name == "student" else name,
                "student" if name == "student" else "parent",
            )

    monkeypatch.setattr(teaching_identity, "active", lambda: True)
    monkeypatch.setattr(
        identity,
        "get_user_by_id",
        lambda user: (
            ("student", {"id": "dtu-web", "parent_id": "parent"}) if user == "dtu-web" else None
        ),
    )
    monkeypatch.setattr(
        teaching_identity,
        "visible_students",
        lambda user_id, **kw: {"dtu-web"} if user_id in {"dtu-web", "parent"} else set(),
    )
    monkeypatch.setattr(
        teaching_grants, "effective", lambda _: SimpleNamespace(features={"quiz", "chat"})
    )
    db = conn.execute("PRAGMA database_list").fetchone()["file"]
    from pathlib import Path

    return TestClient(create_app(Path(db), content_mode="trial", account_access=Access()))


def test_protected_web_api_requires_rules_and_ownership(formal, protected_api):
    conn, _ = formal
    h = {"Authorization": "Bearer student", "X-Quiz-Session": SESSION}
    body = {
        "learner_id": LEARNER,
        "course_version_id": CV,
        "kind": "daily",
        "page_session": SESSION,
    }
    assert protected_api.post("/api/edu/assessments", json=body, headers=h).status_code == 422
    body["rules_accepted"] = True
    response = protected_api.post("/api/edu/assessments", json=body, headers=h)
    assert response.status_code == 200, response.text
    paper = response.json()
    sid = paper["set_id"]
    assert paper["integrity"]["state"] == "active"
    presence = f"/api/edu/assessments/{sid}/presence"
    assert (
        protected_api.post(
            presence,
            json={"page_session": SESSION, "reason": "page_left"},
            headers={"Authorization": "Bearer outsider"},
        ).status_code
        == 403
    )
    assert integrity.status(conn, sid)["state"] == "active"
    assert protected_api.get("/api/edu/lessons/number-structure", headers=h).status_code == 423
    refreshed = protected_api.get(
        "/api/edu/assessments/active",
        params={"learner_id": LEARNER},
        headers={
            "Authorization": "Bearer student",
            "X-Quiz-Session": "a-new-page-session-00000000000000",
        },
    )
    assert refreshed.status_code == 200, refreshed.text
    assert refreshed.json()["exam"]["result"]["status"] == "invalidated"
    endpoint = f"/api/edu/assessments/{sid}/allow-retake"
    assert protected_api.post(endpoint, headers=h).status_code == 403
    assert (
        protected_api.post(endpoint, headers={"Authorization": "Bearer outsider"}).status_code
        == 403
    )
    assert (
        protected_api.post(endpoint, headers={"Authorization": "Bearer parent"}).status_code == 200
    )
    assert integrity.invalid_result(conn, sid)["passed"] is False


def test_lost_presence_report_is_caught_by_reload_and_cookie_origin_gate(formal, protected_api):
    conn, _ = formal
    paper = start(formal)
    response = protected_api.post(
        f"/api/edu/assessments/{paper['set_id']}/presence",
        json={"page_session": SESSION, "reason": "page_hidden"},
        headers={"Authorization": "Bearer student", "Origin": "https://other.invalid"},
    )
    assert (
        response.status_code == 403 and integrity.status(conn, paper["set_id"])["state"] == "active"
    )
    response = protected_api.get(
        f"/api/edu/assessments/{paper['set_id']}", headers={"Authorization": "Bearer student"}
    )
    assert response.status_code == 200 and response.json()["integrity"]["state"] == "invalidated"
