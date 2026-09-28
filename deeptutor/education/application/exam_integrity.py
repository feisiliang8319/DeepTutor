"""Server-owned independent-exam lifecycle. Browser signals are not proctoring.

Missing page sessions and lost presence fail closed. Raw answers stay in the
original draft; an invalidated exam never writes mastery/grade evidence.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time

from fastapi import HTTPException

from deeptutor.education.application import to_iso_timestamp
from deeptutor.education.storage.sqlite import transaction

PRESENCE_SECONDS = 60
REASONS = {"page_hidden", "page_left", "page_reloaded", "connection_lost"}


def _hash(session):
    return hashlib.sha256((session or "").encode()).hexdigest()


def start(conn, set_id, page_session):
    if page_session is None:
        return  # Historical/internal non-web exams retain their original policy.
    now = time.time()
    conn.execute(
        "INSERT INTO exam_integrity(set_id,session_hash,state,started_at,last_seen) VALUES(?,?,?,?,?)",
        (set_id, _hash(page_session), "active", now, now),
    )
    conn.execute(
        "INSERT INTO exam_integrity_events(set_id,kind,actor_id,created_at) VALUES(?,?,?,?)",
        (set_id, "started", "student_page", now),
    )


def status(conn, set_id):
    row = conn.execute("SELECT * FROM exam_integrity WHERE set_id=?", (set_id,)).fetchone()
    if not row:
        return None
    return {key: row[key] for key in ("state", "reason", "ended_at", "retake_authorized_at")}


def invalid_result(conn, set_id):
    state = status(conn, set_id)
    if state and state["state"] == "invalidated":
        return {
            "status": "invalidated",
            "passed": False,
            "qualified": False,
            "promotion": None,
            "integrity": state,
        }
    return None


def report(conn, set_id):
    return {"assessment": invalid_result(conn, set_id), "results": []}


def inspect(conn, set_id, page_session, *, reason=None, heartbeat=False):
    """Commit terminal state before callers reject a request. Safe inside a
    transaction if the caller RETURNS the invalid report rather than raising.
    A terminal exam is immutable: delayed unloads cannot revoke a submission.
    """
    with transaction(conn):
        row = conn.execute(
            "SELECT i.*,f.deadline FROM exam_integrity i JOIN formal_exams f ON f.set_id=i.set_id WHERE i.set_id=?",
            (set_id,),
        ).fetchone()
        if not row or row["state"] != "active":
            return status(conn, set_id)
        now = time.time()
        failure = None
        if row["last_seen"] + PRESENCE_SECONDS < min(now, row["deadline"]):
            failure = "connection_lost"
        elif now < row["deadline"]:
            if not hmac.compare_digest(row["session_hash"], _hash(page_session)):
                failure = "page_reloaded"
            elif reason in REASONS:
                failure = reason
        if failure:
            conn.execute(
                "UPDATE exam_integrity SET state='invalidated',reason=?,ended_at=? WHERE set_id=? AND state='active'",
                (failure, now, set_id),
            )
            conn.execute(
                "INSERT INTO exam_integrity_events(set_id,kind,actor_id,created_at) VALUES(?,?,?,?)",
                (
                    set_id,
                    failure,
                    "student_page" if failure != "connection_lost" else "presence_timeout",
                    now,
                ),
            )
            # This is a terminal attempt without academic marks. Do not forge
            # a zero score or feed untrusted interrupted answers into mastery.
            conn.execute(
                "UPDATE task_sets SET submitted_at=COALESCE(submitted_at,?) WHERE id=?",
                (to_iso_timestamp(now), set_id),
            )
            conn.execute(
                "UPDATE formal_exams SET result_json=?,result_revision=result_revision+1 WHERE set_id=?",
                (json.dumps(invalid_result(conn, set_id)), set_id),
            )
        elif heartbeat and now < row["deadline"]:
            conn.execute("UPDATE exam_integrity SET last_seen=? WHERE set_id=?", (now, set_id))
        return status(conn, set_id)


def seal(conn, set_id):
    """Called in the same transaction that durably accepts all answers."""
    now = time.time()
    if conn.execute(
        "UPDATE exam_integrity SET state='sealed',ended_at=? WHERE set_id=? AND state='active'",
        (now, set_id),
    ).rowcount:
        conn.execute(
            "INSERT INTO exam_integrity_events(set_id,kind,actor_id,created_at) VALUES(?,?,?,?)",
            (set_id, "submitted", "student_page", now),
        )


def require_retake_permission(conn, learner):
    if conn.execute(
        "SELECT 1 FROM exam_integrity i JOIN formal_exams f ON f.set_id=i.set_id WHERE f.learner_id=? AND i.state='invalidated' AND i.retake_authorized_at IS NULL",
        (learner,),
    ).fetchone():
        raise HTTPException(409, "上次测试已失效，请家长确认后再开始新测试。")


def allow_retake(conn, set_id, actor):
    with transaction(conn):
        row = status(conn, set_id)
        if not row or row["state"] != "invalidated":
            raise HTTPException(409, "只有已失效的测试可以安排重测。")
        if row["retake_authorized_at"] is None:
            now = time.time()
            conn.execute(
                "UPDATE exam_integrity SET retake_authorized_by=?,retake_authorized_at=? WHERE set_id=?",
                (actor, now, set_id),
            )
            conn.execute(
                "INSERT INTO exam_integrity_events(set_id,kind,actor_id,created_at) VALUES(?,?,?,?)",
                (set_id, "retake_authorized", actor, now),
            )
    return invalid_result(conn, set_id)


def active_for_user(conn, user_id):
    """Do not expire a lease by unlocking assistance before the exam ends.
    Presence reconciliation belongs to the exam API and persists its outcome.
    """
    return conn.execute(
        "SELECT f.set_id FROM formal_exams f JOIN learner_profiles l ON l.id=f.learner_id JOIN task_sets t ON t.id=f.set_id WHERE l.deep_tutor_user_id=? AND t.submitted_at IS NULL AND t.skipped_at IS NULL LIMIT 1",
        (user_id,),
    ).fetchone()


def guard_education_request(conn, user_id, path, method):
    active = active_for_user(conn, user_id)
    if not active:
        return
    set_id = active["set_id"]
    allowed = {
        ("GET", "/api/edu/people"),
        ("GET", "/api/edu/assessments/catalog"),
        ("GET", "/api/edu/assessments/active"),
        ("POST", "/api/edu/assessments"),
        ("POST", "/api/edu/set/submit"),
        ("POST", "/api/edu/set/recover"),
        ("GET", f"/api/edu/assessments/{set_id}"),
        ("PUT", f"/api/edu/assessments/{set_id}/draft"),
        ("POST", f"/api/edu/assessments/{set_id}/presence"),
    }
    if (method, path) in allowed:
        return
    if method == "POST" and path.endswith("/foundation-choice"):
        snapshot = json.loads(
            conn.execute(
                "SELECT snapshot_json FROM formal_exams WHERE set_id=?", (set_id,)
            ).fetchone()[0]
        )
        if path == f"/api/edu/assessments/{snapshot.get('competition_set_id')}/foundation-choice":
            return
    if method == "GET" and path.startswith("/api/edu/figures/"):
        snapshot = json.loads(
            conn.execute(
                "SELECT snapshot_json FROM formal_exams WHERE set_id=?", (set_id,)
            ).fetchone()[0]
        )
        if path.removeprefix("/api/edu/figures/") in {
            i["public"].get("figure_spec_id") for i in snapshot["items"]
        }:
            return
    raise HTTPException(423, "独立测试进行中，暂时不能使用 Chat、资料或其他测试记录。")


def guard_submission_target(conn, user_id, set_id):
    active = active_for_user(conn, user_id)
    if active and active["set_id"] != set_id:
        raise HTTPException(423, "独立测试进行中，不能查看其他测试的答案。")
