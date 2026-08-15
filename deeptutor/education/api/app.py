"""Standalone FastAPI app for the education loop.

Deliberately **not** mounted into ``deeptutor.api.main``: the education
layer's whole premise is that it never edits an upstream file (upstream
ships a release roughly every two days). Its own app, its own port.

Hard rule enforced here and covered by tests: **no response body may
contain ``expected_answer`` or ``rubric_json``**. The upstream
``quiz_judge`` path was实证 leaking the reference answer into both the
server log and the child's browser (2026-08-13); this loop must not
recreate that. Grading happens server-side and only the verdict crosses
the wire.

Authentication is deliberately **not** here. The service is reachable only
via Cloudflare Access (three whitelisted family addresses) or from
localhost; anyone who gets this far is already the household. ``learner_id``
therefore says *which child is practising*, which is a choice, not a claim
to defend — a second credential in front of the first one would only add
something to leak, screenshot and revoke.
"""

from __future__ import annotations

from pathlib import Path
import sqlite3
import time
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from deeptutor.education.application import to_iso_timestamp
from deeptutor.education.application.llm_judge import (
    DEFAULT_MODEL,
    JudgeClient,
    judge_open_response,
)
from deeptutor.education.application.rebuild_mastery import (
    append_human_judgment_and_recompute,
)
from deeptutor.education.application.record_attempt import (
    NewAttemptInput,
    ValidationError,
    record_attempt,
)
from deeptutor.education.application.select_item import JUDGEABLE, select_next_item
from deeptutor.education.application.select_objective import list_available_objectives
from deeptutor.education.domain.evidence import Verdict
from deeptutor.education.storage import sqlite as edu_sqlite
from deeptutor.education.storage.repositories import (
    AssessmentItemRepository,
    KnowledgeGraphRepository,
    LearnerRepository,
    MasterySnapshotRepository,
    ReviewStateRepository,
)

STATIC_DIR = Path(__file__).resolve().parent / "static"

# 家长账号只读：进度看得到，作答写不进去。这不是安全边界（Access 之内都是
# 家里人），而是防止大人替孩子试答把记录写进她的掌握度 —— 那会让整套证据
# 失真，而 student_attempts 是 append-only，写错删不掉。
PARENT_PREFIX = "parent-"



class ReviewRequest(BaseModel):
    """大人对一条作答的裁定。

    ``reviewer`` 必须是 parent 账号：这是个写操作，写进去的是最终说了算的
    人类判定 —— 谁判的要留痕，且孩子不能自己给自己盖章。
    """

    reviewer: str = Field(min_length=1)
    attempt_id: str = Field(min_length=1)
    verdict: str = Field(pattern="^(correct|incorrect|partial)$")
    note: str | None = None


class AttemptRequest(BaseModel):
    learner_id: str = Field(min_length=1)
    course_version_id: str = Field(min_length=1)
    item_id: str = Field(min_length=1)
    response: str
    client_attempt_id: str = Field(min_length=1)
    started_at: str | None = None


def create_app(
    db_path: Path,
    *,
    judge: JudgeClient | None = None,
    judge_ref: str = DEFAULT_MODEL,
) -> FastAPI:
    """    ``judge`` enables open-response items. Without one they are not served
    at all: an unjudgeable question is worse than no question, because the
    attempt lands as permanently unresolved evidence.
    """
    app = FastAPI(title="DeepTutor Education Loop", docs_url=None, redoc_url=None)

    def connect() -> sqlite3.Connection:
        # One connection per request: SQLite objects are not safe to share
        # across threads, and the app is single-family scale.
        return edu_sqlite.open_database(db_path)

    def require_learner(conn: sqlite3.Connection, learner_id: str) -> str:
        if LearnerRepository(conn).get(learner_id) is None:
            raise HTTPException(status_code=404, detail=f"unknown learner {learner_id!r}")
        return learner_id

    @app.get("/api/edu/people")
    def people() -> dict[str, Any]:
        """落地页用：谁在用这台设备。不是登录，是选身份。"""
        conn = connect()
        try:
            rows = conn.execute(
                "SELECT id, display_name FROM learner_profiles ORDER BY id"
            ).fetchall()
            return {
                "people": [
                    {
                        "id": r["id"],
                        "display_name": r["display_name"],
                        "role": "parent" if str(r["id"]).startswith(PARENT_PREFIX) else "learner",
                    }
                    for r in rows
                ]
            }
        finally:
            conn.close()

    @app.get("/api/edu/review-queue")
    def review_queue(course_version_id: str) -> dict[str, Any]:
        """待大人看的作答：LLM 判不了或没把握的那些。

        家长视角的实际用途 —— 没有这个，``needs_review`` 只是数据库里一个
        没人消费的状态，孩子的开放题就永远停在 learning。
        """
        conn = connect()
        try:
            # "待复核" = 确定性判分给不出结果，且**最新一条**判定也没解决它。
            #
            # 判据不能只看 a.is_correct：student_attempts 是 append-only，人的
            # 裁定写的是 judgment_records，永远不会回填 is_correct。早先按
            # is_correct IS NULL 过滤时，裁定过的作答会一直挂在队列里（测试
            # test_parent_review_resolves_a_pending_attempt 抓到的就是这个）。
            # 取"每条 attempt 的最新判定"与 rebuild_mastery 的口径一致。
            rows = conn.execute(
                """
                WITH latest AS (
                    SELECT j.attempt_id, j.verdict, j.confidence, j.rationale
                    FROM judgment_records j
                    JOIN (
                        SELECT attempt_id, MAX(created_at) AS created_at
                        FROM judgment_records GROUP BY attempt_id
                    ) m ON m.attempt_id = j.attempt_id AND m.created_at = j.created_at
                )
                SELECT a.id AS attempt_id, a.learner_id, a.response, a.submitted_at,
                       i.prompt, n.title AS node_title,
                       latest.verdict, latest.confidence, latest.rationale
                FROM student_attempts a
                JOIN assessment_items i ON i.id = a.assessment_item_id
                JOIN knowledge_nodes n ON n.id = a.knowledge_node_id
                LEFT JOIN latest ON latest.attempt_id = a.id
                WHERE a.course_version_id = ?
                  AND a.is_correct IS NULL
                  AND (latest.verdict IS NULL OR latest.verdict = 'needs_review')
                ORDER BY a.submitted_at DESC
                LIMIT 50
                """,
                (course_version_id,),
            ).fetchall()
            return {
                "pending": [
                    {
                        "attempt_id": r["attempt_id"],
                        "learner_id": r["learner_id"],
                        "node": r["node_title"],
                        "prompt": r["prompt"],
                        "answer": r["response"],
                        "submitted_at": r["submitted_at"],
                        "judge": None
                        if r["verdict"] is None
                        else {"verdict": r["verdict"], "confidence": r["confidence"],
                              "rationale": r["rationale"]},
                    }
                    for r in rows
                ]
            }
        finally:
            conn.close()

    @app.post("/api/edu/review")
    def review(payload: ReviewRequest) -> dict[str, Any]:
        """人类裁定一条 needs_review 的作答，并立即重算掌握度。

        判定是**追加**不是修改：之前那条 AI 判定原样留在
        ``judgment_records`` 里，谁在什么时候推翻了它，事后查得到
        （P0-DESIGN.md §2.6）。
        """
        conn = connect()
        try:
            require_learner(conn, payload.reviewer)
            if not payload.reviewer.startswith(PARENT_PREFIX):
                raise HTTPException(
                    status_code=403, detail="只有家长账号可以裁定作答"
                )
            try:
                snapshot = append_human_judgment_and_recompute(
                    conn,
                    attempt_id=payload.attempt_id,
                    judge_ref=payload.reviewer,
                    verdict=Verdict(payload.verdict),
                    # 人给的判定就是最终答案，不留置信度余地 —— 下游
                    # 的 low-confidence 封顶规则不该把它压回 learning。
                    confidence=1.0,
                    rationale=payload.note,
                )
            except ValueError as exc:
                raise HTTPException(status_code=404, detail=str(exc)) from exc
            return {
                "attempt_id": payload.attempt_id,
                "verdict": payload.verdict,
                "mastery": {"score": snapshot.score, "status": snapshot.status},
            }
        finally:
            conn.close()

    @app.get("/api/edu/next")
    def next_task(learner_id: str, course_version_id: str) -> dict[str, Any]:
        conn = connect()
        try:
            require_learner(conn, learner_id)
            objectives = list_available_objectives(conn, learner_id, course_version_id)
            if not objectives:
                return {"done": True, "message": "every node is mastered"}

            # Walk past nodes whose item bank is still empty instead of
            # dead-ending on them: the planner's head node is frequently a
            # prerequisite anchor we imported for graph structure and never
            # wrote questions for, and a child hitting that sees a blank
            # screen. Skipped nodes are reported, not hidden — an empty bank
            # is a content gap somebody has to fix.
            skipped: list[str] = []
            objective = None
            selected = None
            for candidate in objectives:
                found = select_next_item(
                    conn, learner_id, course_version_id, candidate.node.id,
                    include_judgeable=judge is not None,
                )
                if found is not None:
                    objective, selected = candidate, found
                    break
                skipped.append(candidate.node.code)

            if objective is None or selected is None:
                head = objectives[0]
                return {
                    "done": False,
                    "node": {"id": head.node.id, "code": head.node.code, "title": head.node.title,
                             "standard_code": head.node.standard_code, "status": head.status},
                    "item": None,
                    "skipped_empty_nodes": skipped,
                    "message": "no auto-gradable item on any unblocked node yet",
                }

            node = {
                "id": objective.node.id,
                "code": objective.node.code,
                "title": objective.node.title,
                "standard_code": objective.node.standard_code,
                "status": objective.status,
            }
            return {
                "done": False,
                "node": node,
                "item": {
                    "id": selected.item.id,
                    "prompt": selected.item.prompt,
                    "item_type": selected.item.item_type.value,
                    "difficulty": selected.item.difficulty,
                    "attribution": selected.item.attribution_text,
                    # expected_answer / rubric_json intentionally absent.
                },
                "pool": {"attempts_on_this_item": selected.attempts_so_far,
                         "gradable_items_on_node": selected.total_gradable},
                "skipped_empty_nodes": skipped,
            }
        finally:
            conn.close()

    @app.post("/api/edu/attempt")
    def submit_attempt(payload: AttemptRequest) -> dict[str, Any]:
        conn = connect()
        try:
            learner_id = require_learner(conn, payload.learner_id)
            if learner_id.startswith(PARENT_PREFIX):
                raise HTTPException(
                    status_code=403,
                    detail="家长账号只读：替孩子作答会污染她的掌握度证据",
                )
            now = to_iso_timestamp(time.time())

            # Open tasks are judged before the attempt is written, so the
            # verdict lands in the same transaction as its evidence. The
            # judge never sees the network: it is called server-side and
            # only its verdict is returned to the browser.
            judgment = None
            item = AssessmentItemRepository(conn).get(payload.item_id)
            if judge is not None and item is not None and item.item_type in JUDGEABLE:
                judgment = judge_open_response(
                    judge, item, payload.response, model_ref=judge_ref
                )

            try:
                result = record_attempt(
                    conn,
                    NewAttemptInput(
                        learner_id=learner_id,
                        assessment_item_id=payload.item_id,
                        response=payload.response,
                        started_at=payload.started_at or now,
                        submitted_at=now,
                        source="web",
                        client_attempt_id=payload.client_attempt_id,
                        judgment=judgment,
                    ),
                )
            except ValidationError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc

            snapshot = result.mastery_snapshot
            review = ReviewStateRepository(conn).get(
                learner_id, result.attempt.knowledge_node_id
            )
            return {
                "is_correct": result.attempt.is_correct,
                "needs_judgment": result.attempt.is_correct is None,
                # The verdict may be shown; the rationale is written for an
                # adult reviewer and the rubric never leaves the server.
                "judged": None
                if judgment is None
                else {"verdict": judgment.verdict.value, "confidence": judgment.confidence},
                "mastery": None
                if snapshot is None
                else {"score": snapshot.score, "status": snapshot.status},
                "review": None
                if review is None
                else {"due_at": review.due_at, "reps": review.reps, "lapses": review.lapses},
                "pending_recompute": result.pending_recompute,
            }
        finally:
            conn.close()

    @app.get("/api/edu/progress")
    def progress(learner_id: str, course_version_id: str) -> dict[str, Any]:
        conn = connect()
        try:
            require_learner(conn, learner_id)
            nodes = {n.id: n for n in KnowledgeGraphRepository(conn).list_nodes(course_version_id)}
            snapshots = {
                s.knowledge_node_id: s
                for s in MasterySnapshotRepository(conn).list_for_learner(learner_id)
            }
            rows = []
            for node_id, node in nodes.items():
                snap = snapshots.get(node_id)
                rows.append(
                    {
                        "code": node.code,
                        "title": node.title,
                        "standard_code": node.standard_code,
                        "status": snap.status if snap else "new",
                        "score": round(snap.score, 3) if snap else None,
                    }
                )
            counts: dict[str, int] = {}
            for row in rows:
                counts[row["status"]] = counts.get(row["status"], 0) + 1
            return {"counts": counts, "nodes": rows}
        finally:
            conn.close()

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    return app
