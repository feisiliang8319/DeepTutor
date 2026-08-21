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

import os
from pathlib import Path
import sqlite3
import time
import json
from typing import Any
import uuid

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
    EnrollmentRepository,
    KnowledgeGraphRepository,
    LearnerRepository,
    MasterySnapshotRepository,
    ReviewStateRepository,
)

STATIC_DIR = Path(__file__).resolve().parent / "static"

# 一组几道题。**服务端配置，不是请求参数** —— 见 /api/edu/set 的说明。
DEFAULT_SET_SIZE = int(os.environ.get("EDU_SET_SIZE", "5"))

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


class SetAnswer(BaseModel):
    item_id: str = Field(min_length=1)
    response: str
    client_attempt_id: str = Field(min_length=1)
    started_at: str | None = None


class SetSubmission(BaseModel):
    """一整组题的作答。

    Sol 2026-08-21：出题时不给答案，答案要等**全部**提交之后才出现，并且要
    讲清楚为什么以及关联哪个知识点。所以判分结果不再逐题即时回吐 ——
    整组交上来才一次性给复盘。
    """

    learner_id: str = Field(min_length=1)
    course_version_id: str = Field(min_length=1)
    # 服务端发卷时给的 id。没有它就无法判断"是不是把发出去的那一组都交了"，
    # 而那正是"答案要等全部提交之后"这条要求的唯一着力点。
    set_id: str = Field(min_length=1)
    answers: list[SetAnswer] = Field(min_length=1)


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
    set_size: int = DEFAULT_SET_SIZE,
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

    def require_enrollment(
        conn: sqlite3.Connection, learner_id: str, course_version_id: str
    ) -> None:
        """选课是**访问边界**，不只是"前端该显示哪几门课"。

        2026-08-21 质检席 F-1：/next、/attempt、/progress 此前只校验 learner 存在。
        把一个 learner 的选课置 withdrawn 之后，他照样能取到该课的题、照样能把作答
        写进去 —— 掌握度证据继续长在一门已经退掉的课上，而课程列表里已经看不见它。
        当时 commit message 写的"enrollments 首次真正通电"只在 UI 层成立。
        """
        if not EnrollmentRepository(conn).is_enrolled(learner_id, course_version_id):
            raise HTTPException(
                status_code=403,
                detail=f"{learner_id!r} 未选修 {course_version_id!r}",
            )

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

    @app.get("/api/edu/courses")
    def courses(learner_id: str) -> dict[str, Any]:
        """这个人选了哪几门课。

        在此之前 enrollments 表在运行时**一个消费方都没有**（只有测试和建库脚本
        读它），前端把课程 id 写死成 `cv-ccss-g4-1.0.0`。结果是给谁选了课都不影响
        任何人看到什么 —— 第二门课上线后这一点才暴露出来。
        前端的课程切换器只能从这里取，不许再硬编码课程 id。
        """
        conn = connect()
        try:
            require_learner(conn, learner_id)
            rows = conn.execute(
                """
                SELECT cv.id AS course_version_id, c.title, c.subject_key, c.level
                FROM enrollments e
                JOIN course_versions cv ON cv.id = e.course_version_id
                JOIN courses c ON c.id = cv.course_id
                WHERE e.learner_id = ? AND e.status = 'active' AND cv.status = 'active'
                ORDER BY e.enrolled_at, cv.id
                """,
                (learner_id,),
            ).fetchall()
            return {"courses": [dict(r) for r in rows]}
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

    def _public_item(item, node) -> dict[str, Any]:
        """出题面。答案、讲解、rubric 一律不在这里。

        `to_public_payload()` 是白名单式的（新字段默认**不**公开），这里再从
        中挑出题需要的几项。choices 解析成数组直接给前端 —— 前端拿字符串还得
        自己 JSON.parse，多一处出错的地方。
        """
        pub = item.to_public_payload()
        return {
            "id": pub["id"],
            "prompt": pub["prompt"],
            "item_type": pub["item_type"],
            "difficulty": pub["difficulty"],
            "attribution": pub["attribution_text"],
            "figure_spec_id": pub["figure_spec_id"],
            "choices": json.loads(pub["choices_json"]) if pub["choices_json"] else None,
            "node": {"code": node.code, "title": node.title,
                     "standard_code": node.standard_code},
        }

    @app.get("/api/edu/set")
    def task_set(learner_id: str, course_version_id: str) -> dict[str, Any]:
        """发一组题；组由**服务端**发、服务端记。

        题量是服务端配置（EDU_SET_SIZE，默认 5），**不是请求参数**：让客户端
        自选"这一组就一道题"，交上去立刻拿答案，等于逐题即时反馈 —— 那正是
        Sol 要求去掉的东西（2026-08-21 第二轮质检席 G-1）。

        同一门课有未交的组时，把原组原样发回去，不另抽一组：否则刷新页面就能
        换一批题，"这组做完再讲"变成"挑到会做的为止"。
        """
        conn = connect()
        try:
            require_learner(conn, learner_id)
            require_enrollment(conn, learner_id, course_version_id)

            open_set = conn.execute(
                """
                SELECT id, item_ids_json FROM task_sets
                WHERE learner_id = ? AND course_version_id = ? AND submitted_at IS NULL
                ORDER BY issued_at DESC LIMIT 1
                """,
                (learner_id, course_version_id),
            ).fetchone()
            if open_set is not None:
                items_repo = AssessmentItemRepository(conn)
                nodes = {n.id: n for n in
                         KnowledgeGraphRepository(conn).list_nodes(course_version_id)}
                reissued = []
                for item_id in json.loads(open_set["item_ids_json"]):
                    item = items_repo.get(item_id)
                    if item is not None:
                        reissued.append(_public_item(item, nodes.get(item.knowledge_node_id)))
                if reissued:
                    return {"done": False, "set_id": open_set["id"], "items": reissued,
                            "reissued": True, "skipped_empty_nodes": [], "message": None}

            objectives = list_available_objectives(conn, learner_id, course_version_id)
            if not objectives:
                return {"done": True, "set_id": None, "items": [],
                        "message": "every node is mastered"}

            picked: list[dict[str, Any]] = []
            chosen_ids: list[str] = []
            skipped: list[str] = []
            # 轮转着取：先给每个待学节点各出一题，不够再回头补第二轮。
            # 一口气把一个节点抽干会让整组题挤在同一个知识点上。
            progressed = True
            while len(picked) < set_size and progressed:
                progressed = False
                for candidate in objectives:
                    if len(picked) >= set_size:
                        break
                    found = select_next_item(
                        conn, learner_id, course_version_id, candidate.node.id,
                        include_judgeable=judge is not None, exclude=set(chosen_ids),
                    )
                    if found is None:
                        if not chosen_ids and candidate.node.code not in skipped:
                            # 只在第一轮记"这个节点一道题都没有"；第二轮取不到
                            # 通常只是本组已经把它抽完了，不是内容缺口。
                            skipped.append(candidate.node.code)
                        continue
                    chosen_ids.append(found.item.id)
                    picked.append(_public_item(found.item, candidate.node))
                    progressed = True

            if not picked:
                return {"done": False, "set_id": None, "items": [],
                        "skipped_empty_nodes": skipped,
                        "message": "no auto-gradable item on any unblocked node yet"}

            set_id = f"set-{uuid.uuid4().hex}"
            now = to_iso_timestamp(time.time())
            with conn:
                conn.execute(
                    "INSERT INTO task_sets (id, learner_id, course_version_id, "
                    "item_ids_json, issued_at) VALUES (?, ?, ?, ?, ?)",
                    (set_id, learner_id, course_version_id,
                     json.dumps(chosen_ids), now),
                )
            return {"done": False, "set_id": set_id, "items": picked,
                    "reissued": False, "skipped_empty_nodes": skipped, "message": None}
        finally:
            conn.close()

    @app.post("/api/edu/set/submit")
    def submit_set(payload: SetSubmission) -> dict[str, Any]:
        """整组提交，然后**才**给答案 + 讲解 + 关联知识点。

        这是全流程里唯一允许 `expected_answer` 出网线的出口，而且只在作答已经
        落库之后。rubric_json 仍然一步都不出去：它是阅卷口径，讲解另有 explanation
        列（migration 004）。
        """
        conn = connect()
        try:
            learner_id = require_learner(conn, payload.learner_id)
            if learner_id.startswith(PARENT_PREFIX):
                raise HTTPException(
                    status_code=403,
                    detail="家长账号只读：替孩子作答会污染她的掌握度证据",
                )
            seen = [a.item_id for a in payload.answers]
            if len(set(seen)) != len(seen):
                raise HTTPException(status_code=400, detail="同一题在一组里提交了多次")

            # ---- 交的必须**恰好**是发出去的那一组 ----
            # 少交一题就想拿答案 = 逐题即时反馈；多交一题 = 拿到没发给你的题的
            # 答案。两者都直接推翻"答案必须在所有答题提交后再给出"。
            issued = conn.execute(
                "SELECT * FROM task_sets WHERE id = ? AND learner_id = ?",
                (payload.set_id, learner_id),
            ).fetchone()
            if issued is None:
                raise HTTPException(
                    status_code=404,
                    detail=f"没有发给 {learner_id!r} 的这一组题：{payload.set_id!r}",
                )
            issued_ids = list(json.loads(issued["item_ids_json"]))
            if set(seen) != set(issued_ids):
                missing = sorted(set(issued_ids) - set(seen))
                extra = sorted(set(seen) - set(issued_ids))
                raise HTTPException(
                    status_code=400,
                    detail=f"必须整组一起交：缺 {missing}，多出 {extra}",
                )

            items_repo = AssessmentItemRepository(conn)
            nodes = {
                n.id: n
                for n in KnowledgeGraphRepository(conn).list_nodes(payload.course_version_id)
            }
            now = to_iso_timestamp(time.time())

            # 先校验整组，再落库任何一条：一组题里混进一道别的课的题，应该整组
            # 拒绝，而不是先写进去几条再报错。
            resolved = []
            for ans in payload.answers:
                item = items_repo.get(ans.item_id)
                if item is None:
                    raise HTTPException(status_code=404, detail=f"unknown item {ans.item_id!r}")
                require_enrollment(conn, learner_id, item.course_version_id)
                resolved.append((ans, item))

            with conn:
                conn.execute(
                    "UPDATE task_sets SET submitted_at = ? WHERE id = ? AND submitted_at IS NULL",
                    (now, payload.set_id),
                )

            results = []
            for ans, item in resolved:
                judgment = None
                if judge is not None and item.item_type in JUDGEABLE:
                    judgment = judge_open_response(judge, item, ans.response, model_ref=judge_ref)
                try:
                    outcome = record_attempt(
                        conn,
                        NewAttemptInput(
                            learner_id=learner_id,
                            assessment_item_id=item.id,
                            response=ans.response,
                            started_at=ans.started_at or now,
                            submitted_at=now,
                            source="web",
                            client_attempt_id=ans.client_attempt_id,
                            judgment=judgment,
                        ),
                    )
                except ValidationError as exc:
                    raise HTTPException(status_code=400, detail=str(exc)) from exc

                node = nodes.get(item.knowledge_node_id)
                snapshot = outcome.mastery_snapshot
                review = ReviewStateRepository(conn).get(
                    learner_id, outcome.attempt.knowledge_node_id
                )
                results.append({
                    "item_id": item.id,
                    "prompt": item.prompt,
                    "your_response": ans.response,
                    "is_correct": outcome.attempt.is_correct,
                    "needs_judgment": outcome.attempt.is_correct is None,
                    # ↓ 全组已落库，到这一步才允许出现
                    "correct_answer": item.expected_answer,
                    "choices": json.loads(item.choices_json) if item.choices_json else None,
                    "explanation": item.explanation,
                    "explanation_source": item.explanation_source,
                    "knowledge_point": None if node is None else {
                        "code": node.code, "title": node.title,
                        "standard_code": node.standard_code,
                    },
                    "mastery": None if snapshot is None else {
                        "score": snapshot.score, "status": snapshot.status,
                    },
                    # 判定理由（rationale）是写给大人的，且 rubric 绝不出网线，
                    # 所以这里只给 verdict 与置信度。
                    "judged": None if judgment is None else {
                        "verdict": judgment.verdict.value, "confidence": judgment.confidence,
                    },
                    "review": None if review is None else {
                        "due_at": review.due_at, "reps": review.reps, "lapses": review.lapses,
                    },
                    "pending_recompute": outcome.pending_recompute,
                })

            graded = [r for r in results if r["is_correct"] is not None]
            return {
                "results": results,
                "summary": {
                    "answered": len(results),
                    "auto_graded": len(graded),
                    "correct": sum(1 for r in graded if r["is_correct"]),
                    "awaiting_review": sum(1 for r in results if r["needs_judgment"]),
                },
            }
        finally:
            conn.close()

    @app.get("/api/edu/progress")
    def progress(learner_id: str, course_version_id: str) -> dict[str, Any]:
        conn = connect()
        try:
            require_learner(conn, learner_id)
            require_enrollment(conn, learner_id, course_version_id)
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
