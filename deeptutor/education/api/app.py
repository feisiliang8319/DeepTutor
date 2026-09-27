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

The outer household access control protects entry. Parent judgments additionally
require a verified identity mapped by server configuration to a parent profile;
choosing a profile in the browser never grants review permission.
"""

from __future__ import annotations

from datetime import datetime
import json
import hashlib
import os
import re
from pathlib import Path
import sqlite3
import time
from typing import Any
import uuid

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from pydantic import BaseModel, Field

from deeptutor.education.application import to_iso_timestamp
from deeptutor.education.application.grading_policy import needs_judgment, is_servable
from deeptutor.education.application.effective_grade import effective_correctness
from deeptutor.education.application.content_readiness import admitted, course_readiness
from deeptutor.education.application.learning_evidence import learning_evidence
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
from deeptutor.education.application.select_item import select_next_item
from deeptutor.education.application.select_objective import SelectedObjective
from deeptutor.education.domain.course import ItemStatus
from deeptutor.education.domain.evidence import Verdict
from deeptutor.education.storage import sqlite as edu_sqlite
from deeptutor.education.storage.repositories import (
    AssessmentItemRepository,
    JudgmentRepository,
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



class StudentCoursesRequest(BaseModel):
    course_versions: list[str] = Field(default_factory=list,max_length=100)


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


class RecoverSubmission(BaseModel):
    learner_id: str = Field(min_length=1)
    course_version_id: str = Field(min_length=1)
    set_id: str = Field(min_length=1)


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
    content_mode: str | None = None,
    parent_identity=None,
    account_access=None,
) -> FastAPI:
    """    ``judge`` enables open-response items. Without one they are not served
    at all: an unjudgeable question is worse than no question, because the
    attempt lands as permanently unresolved evidence.
    """
    content_mode = content_mode or os.environ.get("EDU_CONTENT_MODE", "production")
    if content_mode not in {"production", "trial"}:
        raise ValueError("EDU_CONTENT_MODE must be production or trial")
    if account_access is None:
        from deeptutor.education.api.account_identity import from_environment as account_from_environment
        account_access = account_from_environment()
    if parent_identity is None and account_access is None:
        from deeptutor.education.api.parent_identity import from_environment
        parent_identity = from_environment()
    app = FastAPI(title="DeepTutor Education Loop", docs_url=None, redoc_url=None)

    @app.middleware('http')
    async def account_boundary(request: Request, call_next):
        if account_access is not None:
            try:
                request.state.education_account = account_access.authenticate(request)
                from deeptutor.multi_user.teaching_identity import active as teaching_active
                if (request.method in {'GET', 'HEAD'} and request.url.path in {'/', '/practice'}
                        and (teaching_active() or request.state.education_account.role == 'admin')):
                    destination = {'admin':'/admin','parent':'/parent','student':'/quiz'}.get(request.state.education_account.role,'/home')
                    return RedirectResponse(destination, status_code=303,
                                            headers={'Cache-Control': 'private, no-store'})
                if request.method not in {'GET', 'HEAD', 'OPTIONS'}:
                    # Cookie authentication must not admit cross-site writes.
                    origin = request.headers.get('origin')
                    expected_origin = os.environ.get('EDU_PUBLIC_ORIGIN', str(request.base_url)).rstrip('/')
                    if ((not origin and not request.headers.get('authorization'))
                            or request.headers.get('sec-fetch-site') == 'cross-site'
                            or (origin and origin.rstrip('/') != expected_origin)):
                        raise HTTPException(403, '不接受跨站写入')
            except HTTPException as exc:
                if exc.status_code == 401 and request.url.path in {'/', '/practice'}:
                    return RedirectResponse('/login?next=%2Fpractice', status_code=303)
                return JSONResponse({'detail': exc.detail}, status_code=exc.status_code,
                                    headers={'Cache-Control': 'no-store'})
        response = await call_next(request)
        if account_access is not None:
            response.headers['Cache-Control'] = 'private, no-store'
        return response

    def connect() -> sqlite3.Connection:
        # One connection per request: SQLite objects are not safe to share
        # across threads, and the app is single-family scale.
        return edu_sqlite.open_database(db_path)

    def teaching_mode():
        from deeptutor.multi_user.teaching_identity import active
        return active()

    def account_profiles(conn, request, *, write=False):
        account = request.state.education_account
        if teaching_mode():
            from deeptutor.multi_user.teaching_identity import visible_students
            ids = visible_students(account.user_id, write=write)
            if not ids:
                return []
            marks = ','.join('?' for _ in ids)
            return [r['id'] for r in conn.execute(
                f'SELECT id FROM learner_profiles WHERE deep_tutor_user_id IN ({marks})', tuple(sorted(ids)))]
        return [r['id'] for r in conn.execute(
            'SELECT id FROM learner_profiles WHERE deep_tutor_user_id=?', (account.username,))]

    def require_learner(conn: sqlite3.Connection, learner_id: str, request: Request, *, write=False) -> str:
        if account_access is not None and teaching_mode():
            if write:
                from deeptutor.multi_user.teaching_grants import effective
                if "quiz" not in effective(request.state.education_account.user_id).features:
                    raise HTTPException(403, "Quiz access has not been enabled by your parent")
            if learner_id not in account_profiles(conn, request, write=write):
                raise HTTPException(403, '只能访问关联学生的学习记录；作答必须由学生本人提交')
        elif account_access is not None:
            profiles = account_profiles(conn, request)
            parent = any(p.startswith(PARENT_PREFIX) for p in profiles)
            if learner_id not in profiles and (write or not parent):
                raise HTTPException(403, '只能访问当前账号的学习记录')
            if write and parent:
                raise HTTPException(403, '家长账号不代替学生提交作答')
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

    def require_linked_parent(request: Request, student_id: str):
        from deeptutor.multi_user.identity import get_user_by_id
        if account_access is None or not teaching_mode():
            raise HTTPException(409,"Teaching account migration is required")
        actor=request.state.education_account
        target=get_user_by_id(student_id)
        if actor.role != "parent" or not target or target[1].get("parent_id") != actor.user_id:
            raise HTTPException(403,"Only the linked parent manages student courses")
        return target

    @app.get("/api/edu/students/{student_id}/courses")
    def student_courses(student_id: str, request: Request):
        require_linked_parent(request,student_id)
        from deeptutor.multi_user.teaching_grants import effective
        if "quiz" not in effective(request.state.education_account.user_id).features:
            raise HTTPException(403,"Quiz access has not been allocated to this parent")
        conn=connect()
        try:
            selected=[r[0] for r in conn.execute("SELECT e.course_version_id FROM enrollments e JOIN learner_profiles l ON l.id=e.learner_id WHERE l.deep_tutor_user_id=? AND e.status='active'",(student_id,))]
            courses=[dict(r) for r in conn.execute("SELECT cv.id AS course_version_id,c.title,c.subject_key,c.level FROM course_versions cv JOIN courses c ON c.id=cv.course_id WHERE cv.status='active' ORDER BY c.title,cv.version")]
            return {"courses":courses,"selected":selected}
        finally:
            conn.close()

    @app.put("/api/edu/students/{student_id}/courses")
    def set_student_courses(student_id: str, body: StudentCoursesRequest, request: Request):
        target=require_linked_parent(request,student_id)
        from deeptutor.multi_user.teaching_grants import effective
        if "quiz" not in effective(request.state.education_account.user_id).features:
            raise HTTPException(403,"Quiz access has not been allocated to this parent")
        conn=connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            available={r[0] for r in conn.execute("SELECT id FROM course_versions WHERE status='active'")}
            selected=set(body.course_versions)
            if not selected<=available:
                raise HTTPException(400,"Select a currently published course")
            row=conn.execute("SELECT id FROM learner_profiles WHERE deep_tutor_user_id=?",(student_id,)).fetchone()
            learner_id=row[0] if row else "learner-"+student_id
            now=to_iso_timestamp(time.time())
            if row is None:
                conn.execute("INSERT INTO learner_profiles(id,deep_tutor_user_id,display_name,locale,created_at,updated_at) VALUES(?,?,?,?,?,?)",(learner_id,student_id,target[0],"en",now,now))
            conn.execute("UPDATE enrollments SET status='withdrawn',updated_at=? WHERE learner_id=? AND status='active'",(now,learner_id))
            for version in sorted(selected):
                conn.execute("INSERT INTO enrollments VALUES(?,?,?,?,?) ON CONFLICT(learner_id,course_version_id) DO UPDATE SET status='active',updated_at=excluded.updated_at",(learner_id,version,"active",now,now))
            conn.commit()
            return {"learner_id":learner_id,"selected":sorted(selected)}
        finally:
            conn.close()

    @app.get("/api/edu/people")
    def people(request: Request) -> dict[str, Any]:
        """落地页用：谁在用这台设备。不是登录，是选身份。"""
        conn = connect()
        try:
            rows = conn.execute(
                "SELECT id, display_name, deep_tutor_user_id FROM learner_profiles ORDER BY id"
            ).fetchall()
            own = account_profiles(conn, request) if account_access is not None else []
            if account_access is not None and teaching_mode():
                rows = [r for r in rows if r['id'] in own]
            elif account_access is not None:
                if not own:
                    raise HTTPException(403, '当前账号尚未关联学习档案')
                if not any(p.startswith(PARENT_PREFIX) for p in own):
                    rows = [r for r in rows if r['id'] in own]
            return {
                'signed_in_profile_id': own[0] if own and (not teaching_mode() or request.state.education_account.role == 'student') else None,
                'account_role': request.state.education_account.role if account_access else None,
                'account_authenticated': account_access is not None,
                "people": [
                    {
                        "id": r["id"],
                        "display_name": r["display_name"],
                        **({"user_id":r["deep_tutor_user_id"]} if teaching_mode() else {}),
                        "role": "parent" if str(r["id"]).startswith(PARENT_PREFIX) else "learner",
                    }
                    for r in rows
                ]
            }
        finally:
            conn.close()

    @app.get("/api/edu/courses")
    def courses(learner_id: str, request: Request) -> dict[str, Any]:
        """这个人选了哪几门课。

        在此之前 enrollments 表在运行时**一个消费方都没有**（只有测试和建库脚本
        读它），前端把课程 id 写死成 `cv-ccss-g4-1.0.0`。结果是给谁选了课都不影响
        任何人看到什么 —— 第二门课上线后这一点才暴露出来。
        前端的课程切换器只能从这里取，不许再硬编码课程 id。
        """
        conn = connect()
        try:
            require_learner(conn, learner_id, request)
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

    def require_parent(request: Request, conn):
        if account_access is not None and teaching_mode():
            account = request.state.education_account
            if account.role not in {'parent', 'admin'}:
                raise HTTPException(403, '需要家长或管理员权限')
            return account.user_id
        if account_access is not None:
            parents = [p for p in account_profiles(conn, request) if p.startswith(PARENT_PREFIX)]
            if len(parents) != 1:
                raise HTTPException(403, '当前登录账号没有家长复核权限')
            return parents[0]
        if parent_identity is None:
            raise HTTPException(503, "家长复核身份尚未配置；切换使用者不授予裁定权限")
        reviewer = parent_identity(request)
        if not reviewer or not reviewer.startswith(PARENT_PREFIX):
            raise HTTPException(403, "需要经过验证的家长身份")
        require_learner(conn, reviewer, request)
        return reviewer

    def lesson_catalog():
        path = STATIC_DIR / "lessons" / "curriculum_index.json"
        return json.loads(path.read_text())["lessons"]

    def lesson_allowed(meta):
        if content_mode == "trial" and meta.get("status") == "candidate":
            return True
        return (meta.get("status") == "production" and bool(meta.get("reviewer"))
                and bool(meta.get("reviewed_at")) and meta.get("reviewed_sha256") == meta.get("sha256"))

    @app.get("/api/edu/lessons")
    def lessons(learner_id: str, course_version_id: str, request: Request):
        conn = connect()
        try:
            require_learner(conn, learner_id, request)
            require_enrollment(conn, learner_id, course_version_id)
            course = conn.execute("SELECT c.subject_key,c.level FROM courses c JOIN course_versions v ON v.course_id=c.id WHERE v.id=?", (course_version_id,)).fetchone()
            codes = {n.code for n in KnowledgeGraphRepository(conn).list_nodes(course_version_id)}
            entries = []
            for key, meta in lesson_catalog().items():
                if (lesson_allowed(meta) and meta["course"] == dict(course)
                        and codes.intersection(meta["node_codes"])):
                    entries.append({"id": key, "title": meta["unit_title"],
                                    "url": f"/api/edu/lessons/{key}", "status": meta["status"],
                                    "standards": meta["standards"]})
            return {"lessons": entries, "content_mode": content_mode}
        finally:
            conn.close()

    def verified_lesson(lesson_id: str):
        if not re.fullmatch(r"[a-zA-Z0-9_-]{1,100}", lesson_id):
            raise HTTPException(404, "lesson not found")
        meta = lesson_catalog().get(lesson_id)
        if meta is None or not lesson_allowed(meta):
            raise HTTPException(404, "lesson not available")
        path = STATIC_DIR / "lessons" / f"{lesson_id}.html"
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != meta["sha256"]:
            raise HTTPException(503, "lesson asset does not match its release")
        return meta, path

    @app.get("/api/edu/lessons/{lesson_id}/source")
    def lesson_source(lesson_id: str):
        from fastapi.responses import PlainTextResponse
        from .lesson_source import export_lesson_source

        meta, path = verified_lesson(lesson_id)
        return PlainTextResponse(
            export_lesson_source(lesson_id, meta, path.read_text(encoding="utf-8")),
            media_type="text/markdown",
            headers={"Content-Disposition": f'attachment; filename="deeptutor-trial-{lesson_id}.md"',
                     "X-Content-Type-Options": "nosniff", "Cache-Control": "private, no-store"},
        )

    @app.get("/api/edu/lessons/{lesson_id}")
    def lesson_document(lesson_id: str):
        _, path = verified_lesson(lesson_id)
        return FileResponse(path, media_type="text/html", headers={
            "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; img-src 'self' data:; base-uri 'none'; form-action 'none'; frame-ancestors 'self'",
            "X-Content-Type-Options": "nosniff",
        })

    @app.get("/api/edu/readiness")
    def readiness(learner_id: str, course_version_id: str, request: Request):
        conn = connect()
        try:
            require_learner(conn, learner_id, request)
            require_enrollment(conn, learner_id, course_version_id)
            return course_readiness(conn, course_version_id, content_mode=content_mode,
                                    judge_available=judge is not None)
        finally:
            conn.close()

    @app.get('/api/edu/topics')
    def topics(learner_id: str, course_version_id: str, request: Request):
        conn = connect()
        try:
            require_learner(conn, learner_id, request)
            require_enrollment(conn, learner_id, course_version_id)
            counts = {}
            for item in AssessmentItemRepository(conn).list_for_version(course_version_id):
                if admitted(item, content_mode) and is_servable(item, judge_available=judge is not None):
                    counts[item.knowledge_node_id] = counts.get(item.knowledge_node_id, 0) + 1
            current = conn.execute(
                'SELECT id FROM task_sets WHERE learner_id=? AND course_version_id=? '
                'AND submitted_at IS NULL AND skipped_at IS NULL', (learner_id, course_version_id),
            ).fetchone()
            pending = conn.execute(
                'SELECT 1 FROM task_sets t JOIN task_set_submissions s ON s.set_id=t.id '
                'WHERE t.learner_id=? AND t.course_version_id=? AND EXISTS ('
                'SELECT 1 FROM json_each(t.item_ids_json) i WHERE NOT EXISTS ('
                "SELECT 1 FROM student_attempts a WHERE a.id=t.id || ':' || i.value)) LIMIT 1",
                (learner_id, course_version_id),
            ).fetchone()
            return {'learning_mode': 'free', 'open_set_id': current['id'] if current else None,
                    'pending_submission': pending is not None,
                    'topics': [{'id': node.id, 'code': node.code, 'title': node.title,
                                'practice_items': counts.get(node.id, 0)}
                               for node in KnowledgeGraphRepository(conn).list_nodes(course_version_id)]}
        finally:
            conn.close()

    @app.post('/api/edu/set/skip')
    def skip_set(payload: RecoverSubmission, request: Request):
        conn = connect()
        try:
            require_learner(conn, payload.learner_id, request, write=True)
            require_enrollment(conn, payload.learner_id, payload.course_version_id)
            with edu_sqlite.transaction(conn):
                changed = conn.execute(
                    'UPDATE task_sets SET skipped_at=? WHERE id=? AND learner_id=? AND course_version_id=? '
                    'AND submitted_at IS NULL AND skipped_at IS NULL AND NOT EXISTS '
                    '(SELECT 1 FROM task_set_submissions WHERE set_id=task_sets.id)',
                    (to_iso_timestamp(time.time()), payload.set_id, payload.learner_id, payload.course_version_id),
                ).rowcount
                if changed != 1:
                    raise HTTPException(409, '已提交或已离开的练习不能再次跳过；已保存答案仍保留')
            return {'skipped': True, 'set_id': payload.set_id}
        finally:
            conn.close()

    @app.get("/api/edu/review-queue")
    def review_queue(course_version_id: str, request: Request) -> dict[str, Any]:
        """待大人看的作答：LLM 判不了或没把握的那些。

        家长视角的实际用途 —— 没有这个，``needs_review`` 只是数据库里一个
        没人消费的状态，孩子的开放题就永远停在 learning。
        """
        conn = connect()
        try:
            require_parent(request, conn)
            visible = account_profiles(conn, request) if teaching_mode() else None
            if visible == []:
                return {"pending": []}
            scope_sql = (" AND a.learner_id IN (" + ",".join("?" for _ in visible) + ")") if visible is not None else ""
            # "待复核" = 确定性判分给不出结果，且**最新一条**判定也没解决它。
            #
            # 判据不能只看 a.is_correct：student_attempts 是 append-only，人的
            # 裁定写的是 judgment_records，永远不会回填 is_correct。早先按
            # is_correct IS NULL 过滤时，裁定过的作答会一直挂在队列里（测试
            # test_parent_review_resolves_a_pending_attempt 抓到的就是这个）。
            # 取"每条 attempt 的最新判定"与 rebuild_mastery 的口径一致。
            rows = conn.execute(
                f"""
                WITH latest AS (
                    SELECT j.attempt_id, j.verdict, j.confidence, j.rationale
                    FROM judgment_records j
                    WHERE j.rowid = (SELECT j2.rowid FROM judgment_records j2
                        WHERE j2.attempt_id=j.attempt_id ORDER BY j2.created_at DESC, j2.rowid DESC LIMIT 1)
                )
                SELECT a.id AS attempt_id, a.learner_id, a.response, a.submitted_at,
                       i.prompt, n.title AS node_title,
                       latest.verdict, latest.confidence, latest.rationale
                FROM student_attempts a
                JOIN assessment_items i ON i.id = a.assessment_item_id
                JOIN knowledge_nodes n ON n.id = a.knowledge_node_id
                LEFT JOIN latest ON latest.attempt_id = a.id
                WHERE a.course_version_id = ? {scope_sql}
                  AND ((a.is_correct IS NULL AND latest.verdict IS NULL)
                       OR latest.verdict = 'needs_review' OR latest.confidence < 0.6)
                ORDER BY a.submitted_at DESC
                LIMIT 50
                """,
                (course_version_id, *(visible or [])),
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
    def review(payload: ReviewRequest, request: Request) -> dict[str, Any]:
        """人类裁定一条 needs_review 的作答，并立即重算掌握度。

        判定是**追加**不是修改：之前那条 AI 判定原样留在
        ``judgment_records`` 里，谁在什么时候推翻了它，事后查得到
        （P0-DESIGN.md §2.6）。
        """
        conn = connect()
        try:
            reviewer = require_parent(request, conn)
            if payload.reviewer != reviewer:
                raise HTTPException(
                    status_code=403, detail="只有家长账号可以裁定作答"
                )
            if teaching_mode():
                attempt = conn.execute('SELECT learner_id FROM student_attempts WHERE id=?', (payload.attempt_id,)).fetchone()
                if attempt is None or attempt['learner_id'] not in account_profiles(conn, request):
                    raise HTTPException(403, '无法复核未关联学生的作答')
            try:
                snapshot = append_human_judgment_and_recompute(
                    conn,
                    attempt_id=payload.attempt_id,
                    judge_ref=reviewer,
                    verdict=Verdict(payload.verdict),
                    # 人给的判定就是最终答案，不留置信度余地 —— 下游
                    # 的 low-confidence 封顶规则不该把它压回 learning。
                    confidence=1.0,
                    rationale=payload.note,
                )
            except ValueError as exc:
                raise HTTPException(status_code=404, detail=str(exc)) from exc
            delivery = {}
            if teaching_mode():
                from deeptutor.education.application.quiz_chat import handoff_review
                try:
                    delivery["chat_handoff"] = handoff_review(conn, payload.attempt_id)
                except (ValueError, RuntimeError, OSError, sqlite3.DatabaseError) as exc:
                    # The judgment already committed. Make the delivery failure
                    # visible, and retry delivery without another judgment.
                    delivery["chat_handoff_error"] = str(exc)
            return {
                **delivery,
                "attempt_id": payload.attempt_id,
                "verdict": payload.verdict,
                "mastery": {"score": snapshot.score, "status": snapshot.status},
            }
        finally:
            conn.close()

    @app.post("/api/edu/review/{attempt_id}/chat")
    def retry_review_chat(attempt_id: str, request: Request) -> dict[str, Any]:
        if not teaching_mode():
            raise HTTPException(409, "Teaching mode is required")
        conn = connect()
        try:
            require_parent(request, conn)
            attempt = conn.execute("SELECT learner_id FROM student_attempts WHERE id=?", (attempt_id,)).fetchone()
            if attempt is None or attempt["learner_id"] not in account_profiles(conn, request):
                raise HTTPException(403, "This attempt is not available to your account")
            from deeptutor.education.application.quiz_chat import handoff_review
            return {"chat_handoff": handoff_review(conn, attempt_id)}
        finally:
            conn.close()

    def _within_grace(claimed_at: str | None, now_iso: str, seconds: int = 60) -> bool:
        """认领时间距现在是否还在宽限期内（判断"另一路正在写"还是"它死了"）。"""
        if not claimed_at:
            return False
        try:
            return (datetime.fromisoformat(now_iso)
                    - datetime.fromisoformat(claimed_at)).total_seconds() < seconds
        except ValueError:
            # 时间戳解析不了就按"还在写"处理：宁可让孩子重试一次，
            # 也不要在看不清状态时去补写作答。
            return True

    def _stored_attempt_row(conn: sqlite3.Connection, learner_id: str,
                            item_id: str, submitted_at: str | None):
        """这一次提交里，这道题有没有已落库的作答（逐题现查，不吃入口那份快照）。"""
        if submitted_at is None:
            return None
        return conn.execute(
            "SELECT * FROM student_attempts WHERE learner_id = ? "
            "AND assessment_item_id = ? AND submitted_at = ?",
            (learner_id, item_id, submitted_at),
        ).fetchone()

    def _stored_judgment(conn: sqlite3.Connection, attempt_id: str):
        """取这条作答已落库的判定。

        第四轮质检席 A-6：回读分支里 judgment 恒为 None，于是任何被 LLM 判过的
        题一进回读，判分依据就从复盘里消失了。
        """
        return JudgmentRepository(conn).latest_for_attempt(attempt_id)

    class _ReplayedOutcome:
        """由已落库的作答重建的"评分结果"，形状与 record_attempt 的返回一致。

        重放路径**不跑判分、不写库**，所以这里只是把 DB 行包一层，让下面构造
        复盘的代码不必分叉。
        """

        def __init__(self, row, snapshot):
            self.attempt = _StoredAttempt(row)
            self.mastery_snapshot = snapshot
            self.pending_recompute = bool(
                snapshot is not None and snapshot.status == "pending_recompute")

    class _StoredAttempt:
        def __init__(self, row):
            self.id = row["id"]
            self.response = row["response"]
            self.is_correct = None if row["is_correct"] is None else bool(row["is_correct"])
            self.knowledge_node_id = row["knowledge_node_id"]

    @app.get("/api/edu/figures/{figure_id}")
    def practice_figure(figure_id: str):
        if not re.fullmatch(r"[a-zA-Z0-9_-]{1,100}", figure_id):
            raise HTTPException(status_code=404, detail="figure not found")
        path = STATIC_DIR / "figures" / f"{figure_id}.svg"
        if not path.is_file():
            raise HTTPException(status_code=404, detail="figure not found")
        return FileResponse(path, media_type="image/svg+xml", headers={
            "Content-Security-Policy": "default-src 'none'; sandbox",
            "X-Content-Type-Options": "nosniff",
        })

    def _public_item(item, node) -> dict[str, Any]:
        """出题面。答案、讲解、rubric 一律不在这里。

        `to_public_payload()` 是白名单式的（新字段默认**不**公开），这里再从
        中挑出题需要的几项。choices 解析成数组直接给前端 —— 前端拿字符串还得
        自己 JSON.parse，多一处出错的地方。
        """
        pub = item.to_public_payload()
        figure_id = pub["figure_spec_id"]
        if figure_id and (not re.fullmatch(r"[a-zA-Z0-9_-]{1,100}", figure_id)
                          or not (STATIC_DIR / "figures" / f"{figure_id}.svg").is_file()):
            raise HTTPException(status_code=503, detail="This item is missing its teaching figure")
        return {
            "id": pub["id"],
            "prompt": pub["prompt"],
            "item_type": pub["item_type"],
            "difficulty": pub["difficulty"],
            "attribution": pub["attribution_text"],
            "figure_spec_id": pub["figure_spec_id"],
            "figure_url": f"/api/edu/figures/{figure_id}" if figure_id else None,
            "choices": json.loads(pub["choices_json"]) if pub["choices_json"] else None,
            "node": {"code": node.code, "title": node.title,
                     "standard_code": node.standard_code},
        }

    @app.post("/api/edu/set")
    def task_set(learner_id: str, course_version_id: str, request: Request,
                 topic_id: str | None = None) -> dict[str, Any]:
        """发一组题；组由**服务端**发、服务端记。

        **是 POST 不是 GET**：这个端点会 INSERT 一行 task_sets。挂在 GET 上曾让
        两个人（第四轮质检席、以及我自己）在"只读复验"时意外写进生产库 ——
        HTTP 语义里 GET 应当是安全的，任何巡检/监控/重试都可能打它。

        题量是服务端配置（EDU_SET_SIZE，默认 5），**不是请求参数**：让客户端
        自选"这一组就一道题"，交上去立刻拿答案，等于逐题即时反馈 —— 那正是
        Sol 要求去掉的东西（2026-08-21 第二轮质检席 G-1）。

        同一门课保留一组未交练习以便恢复。学生可以随时放下该组，换主题或阅读
        讲义；放下练习不产生作答或掌握度证据。
        """
        conn = connect()
        try:
            require_learner(conn, learner_id, request, write=True)
            require_enrollment(conn, learner_id, course_version_id)
            nodes_by_id = {n.id: n for n in KnowledgeGraphRepository(conn).list_nodes(course_version_id)}
            if topic_id is not None and topic_id not in nodes_by_id:
                raise HTTPException(404, '所选主题不属于这门课程')

            unfinished = conn.execute(
                "SELECT t.id FROM task_sets t JOIN task_set_submissions s ON s.set_id=t.id "
                "WHERE t.learner_id=? AND t.course_version_id=? AND EXISTS ("
                "SELECT 1 FROM json_each(t.item_ids_json) i WHERE NOT EXISTS ("
                "SELECT 1 FROM student_attempts a WHERE a.id=t.id || ':' || i.value)) "
                "ORDER BY t.issued_at LIMIT 1", (learner_id, course_version_id),
            ).fetchone()
            # Recover saved grading when explicitly resuming. A delayed judge
            # must never prevent the learner from choosing another topic.
            if unfinished is not None and topic_id is None:
                return {"done": False, "set_id": unfinished["id"], "items": [],
                        "pending_submission": True,
                        "message": "Your saved answers are waiting for grading to finish."}

            open_set = conn.execute(
                """
                SELECT id, item_ids_json FROM task_sets
                WHERE learner_id = ? AND course_version_id = ? AND submitted_at IS NULL AND skipped_at IS NULL
                ORDER BY issued_at DESC LIMIT 1
                """,
                (learner_id, course_version_id),
            ).fetchone()
            if open_set is not None:
                items_repo = AssessmentItemRepository(conn)
                nodes = {n.id: n for n in
                         KnowledgeGraphRepository(conn).list_nodes(course_version_id)}
                wanted = json.loads(open_set["item_ids_json"])
                fetched = [items_repo.get(i) for i in wanted]
                if topic_id is not None and any(it and it.knowledge_node_id != topic_id for it in fetched):
                    raise HTTPException(409, {'message': '可以先放下未提交的练习，再选择其他主题',
                                              'open_set_id': open_set['id']})
                # 组里有题在发卷之后被下架/删掉了，就整组作废重发。
                # 第四轮质检席 A-新2：原先照发不误，孩子答完提交时才在
                # record_attempt 里炸出 "is retired and cannot be attempted"，
                # 而那时这一组已经被标记成已交 —— 永久卡死、复盘丢失。
                # 未作答的组删掉是安全的：没有任何作答记录引用它。
                if any(it is None or not admitted(it, content_mode) for it in fetched):
                    with conn:
                        conn.execute("DELETE FROM task_sets WHERE id = ?", (open_set["id"],))
                else:
                    return {"done": False, "set_id": open_set["id"],
                            "items": [_public_item(it, nodes.get(it.knowledge_node_id))
                                      for it in fetched],
                            "reissued": True, "skipped_empty_nodes": [], "content_mode": content_mode, "message": None}

            # Every topic is selectable, including one with unmet prerequisites
            # or existing practice evidence. Recommendations never lock access.
            objectives = [SelectedObjective(node, 'optional') for node in nodes_by_id.values()
                          if topic_id is None or node.id == topic_id]
            due_ids = [r["knowledge_node_id"] for r in conn.execute(
                "SELECT r.knowledge_node_id FROM review_states r JOIN knowledge_nodes n "
                "ON n.id=r.knowledge_node_id WHERE r.learner_id=? AND n.course_version_id=? "
                "AND julianday(r.due_at)<=julianday(?) ORDER BY r.due_at, n.sort_order, n.id",
                (learner_id, course_version_id, to_iso_timestamp(time.time())),
            )]
            if topic_id is None:
                objectives = [SelectedObjective(nodes_by_id[i], "review") for i in due_ids] + [
                    o for o in objectives if o.node.id not in due_ids]

            if not objectives:
                return {"done": True, "set_id": None, "items": [],
                        "state": "content_unavailable", "content_mode": content_mode,
                        "message": "当前课程尚未提供主题。"}

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
                        content_mode=content_mode,
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
                        "state": "content_unavailable", "content_mode": content_mode,
                        "message": "这个主题暂无可用练习；可以阅读讲义或选择其他主题。"}

            set_id = f"set-{uuid.uuid4().hex}"
            now = to_iso_timestamp(time.time())
            try:
                with conn:
                    conn.execute(
                        "INSERT INTO task_sets (id, learner_id, course_version_id, "
                        "item_ids_json, issued_at) VALUES (?, ?, ?, ?, ?)",
                        (set_id, learner_id, course_version_id,
                         json.dumps(chosen_ids), now),
                    )
            except sqlite3.IntegrityError:
                # 上面那句"有未交的组就重发"的检查在事务外，是 TOCTOU：并发的两个
                # 请求会各自查到"没有未交的组"，造出两个 set_id 相同题面的孪生卷子
                # ——先用 A 交垃圾骗答案、再用 B 照抄拿满分，绕过整个设计目标。
                # 唯一索引（migration 006）把它变成结构上不可能；撞上就说明另一个
                # 请求先建好了，回读那一组重发即可（fail-closed 地回到正确路径）。
                row = conn.execute(
                    "SELECT id, item_ids_json FROM task_sets WHERE learner_id = ? "
                    "AND course_version_id = ? AND submitted_at IS NULL AND skipped_at IS NULL",
                    (learner_id, course_version_id),
                ).fetchone()
                if row is None:
                    raise
                items_repo = AssessmentItemRepository(conn)
                nodes = {n.id: n for n in
                         KnowledgeGraphRepository(conn).list_nodes(course_version_id)}
                fetched = [items_repo.get(i) for i in json.loads(row["item_ids_json"])]
                if topic_id is not None and any(it and it.knowledge_node_id != topic_id for it in fetched):
                    raise HTTPException(409, {'message': '可以先放下未提交的练习，再选择其他主题',
                                              'open_set_id': row['id']})
                reissued = [_public_item(it, nodes.get(it.knowledge_node_id))
                            for it in fetched if it is not None]
                return {"done": False, "set_id": row["id"], "items": reissued,
                        "reissued": True, "skipped_empty_nodes": [], "content_mode": content_mode, "message": None}
            return {"done": False, "set_id": set_id, "items": picked,
                    "reissued": False, "skipped_empty_nodes": skipped, "content_mode": content_mode, "message": None}
        finally:
            conn.close()

    @app.post("/api/edu/set/recover")
    def recover_submission(payload: RecoverSubmission, request: Request) -> dict[str, Any]:
        conn = connect()
        try:
            require_learner(conn, payload.learner_id, request, write=True)
            row = conn.execute(
                "SELECT s.answers_json, t.course_version_id FROM task_set_submissions s "
                "JOIN task_sets t ON t.id=s.set_id WHERE t.id=? AND t.learner_id=?",
                (payload.set_id, payload.learner_id),
            ).fetchone()
            if row is None:
                raise HTTPException(status_code=404, detail="Saved submission not found")
            require_enrollment(conn, payload.learner_id, row["course_version_id"])
            answers = json.loads(row["answers_json"])
        finally:
            conn.close()
        return submit_set(SetSubmission(**payload.model_dump(), answers=answers), request)

    @app.post("/api/edu/set/submit")
    def submit_set(payload: SetSubmission, request: Request) -> dict[str, Any]:
        """整组提交，然后**才**给答案 + 讲解 + 关联知识点。

        这是全流程里唯一允许 `expected_answer` 出网线的出口，而且只在作答已经
        落库之后。rubric_json 仍然一步都不出去：它是阅卷口径，讲解另有 explanation
        列（migration 004）。
        """
        conn = connect()
        try:
            learner_id = require_learner(conn, payload.learner_id, request, write=True)
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
            if issued['skipped_at'] is not None:
                raise HTTPException(409, '这组练习已放下，请重新选择主题')
            require_enrollment(conn, learner_id, issued["course_version_id"])
            if issued["course_version_id"] != payload.course_version_id:
                raise HTTPException(status_code=400, detail="task set belongs to another course")
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

            # 落库之前先把整组过一遍：有一题不可作答（已下架/已删）就整组拒绝，
            # **在认领这一组之前**。否则会重演 A-新2：标记已交了，评分循环才炸。
            for _, item in resolved:
                if issued["submitted_at"] is None and not admitted(item, content_mode):
                    raise HTTPException(409, "题目已不符合当前内容准入条件，请重新领取题组")
                if item.status is ItemStatus.RETIRED:
                    raise HTTPException(
                        status_code=409,
                        detail=f"{item.id!r} 已下架，这一组作废；重新领一组即可")

            # ---- 已交过的组：只回读，绝不重新评分 ----
            # 第三轮质检席 CRITICAL-1：原先查 issued 时没过滤 submitted_at，
            # 那句 `UPDATE ... WHERE submitted_at IS NULL` 静默 no-op 之后代码照常
            # 往下评分。于是"先用错答案交一次骗出 correct_answer，再换一批
            # client_attempt_id 照抄正确答案交同一个 set_id"整条路畅通，
            # 而且比修前更隐蔽 —— 不必暴力枚举，一次就够。
            #
            # 不直接 409 拒掉，是因为提交成功但响应丢包时，孩子会永久看不到自己的
            # 复盘（作答已落库、卷子已标记已交）。所以：重放返回**同一份**复盘，
            # 由已落库的作答重建，一条新作答都不写、一次判分都不跑。
            # 「这一组归谁评」必须由一次原子的 compare-and-swap 决定，不能由函数
            # 顶部那次 SELECT 决定。
            # 第四轮质检席 A-新1：原先 already_submitted 在入口读一次就不再复核，
            # 于是并发提交时那句 UPDATE 虽然因 `WHERE submitted_at IS NULL` 静默
            # no-op，输掉竞态的一路仍然走"新作答"分支 —— 同一组被评分两遍，
            # 掌握度被推进两次，其中一路的作答永久落库却永不可能再被读出
            # （回读按 learner_id + submitted_at 精确匹配，时间戳对不上）。
            # 双击提交按钮就能触发，不需要恶意脚本。
            with edu_sqlite.transaction(conn):
                claimed = conn.execute(
                    "UPDATE task_sets SET submitted_at = ? WHERE id = ? "
                    "AND submitted_at IS NULL AND skipped_at IS NULL",
                    (now, payload.set_id),
                ).rowcount == 1
                if not claimed and conn.execute('SELECT skipped_at FROM task_sets WHERE id=?',
                                                (payload.set_id,)).fetchone()['skipped_at'] is not None:
                    raise HTTPException(409, '这组练习已放下，请重新选择主题')
                if claimed:
                    conn.execute(
                        "INSERT INTO task_set_submissions (set_id, answers_json, received_at) VALUES (?, ?, ?)",
                        (payload.set_id, json.dumps([a.model_dump() for a in payload.answers]), now),
                    )
            durable = conn.execute("SELECT answers_json FROM task_set_submissions WHERE set_id=?",
                                   (payload.set_id,)).fetchone()
            if durable is not None:
                # A retry can recover unfinished grading, but cannot replace
                # any original response after answers have been disclosed.
                resolved = [(SetAnswer(**a), items_repo.get(a["item_id"]))
                            for a in json.loads(durable["answers_json"])]
            issued = conn.execute(
                "SELECT * FROM task_sets WHERE id = ?", (payload.set_id,)
            ).fetchone()
            already_submitted = not claimed

            stored = {}
            if already_submitted:
                for row in conn.execute(
                    "SELECT * FROM student_attempts WHERE learner_id = ? AND submitted_at = ?",
                    (learner_id, issued["submitted_at"]),
                ):
                    stored[row["assessment_item_id"]] = row
                missing = [i for i in issued_ids if i not in stored]
                if missing:
                    # 认领成功的那一路还没写完（并发），或者它中途死了。
                    # 两种情况必须分开：前者稍后重试就好，后者不能让孩子永远卡住。
                    if _within_grace(issued["submitted_at"], now):
                        raise HTTPException(
                            status_code=409,
                            detail="这一组正在判分，请稍等几秒再试")
                    # 过了宽限期仍残缺 = 上一次提交没写完就断了。放行让它补齐
                    # 缺的那几题：已落库的题一律回读、不重判，所以补不出便宜可占。
                    already_submitted = False

            results = []
            for ans, item in resolved:
                judgment = None
                # `stored` 是函数入口读的一次快照。自愈分支（补齐上次没写完的题）
                # 拿它逐题判断"这题缺不缺"，两路并发就会都判定"缺"、都去写 ——
                # 这正是刚在组这一层用 CAS 修掉的那个反模式，在题这一层复刻了一遍
                # （第五轮质检席，3 路并发即触发；16 路时一道题落 5~6 条矛盾作答，
                #  review_states.lapses 被推到 11，FSRS 调度被污染）。
                # 真正关掉它的是**服务端派生的幂等键**（见下方 client_attempt_id）：
                # student_attempts.id 就是那个键，INSERT OR IGNORE 在主键上去重，
                # 并发下第二路直接被忽略并走 record_attempt 既有的重放分支。
                # 下面这句逐题现查**只是省一次判分调用**（已答过的题不必再喊 LLM），
                # 不是闸门 —— 把它去掉不会产生重复作答，破坏注入实测也确实不失败。
                # 别把它当成安全保证。
                row = stored.get(item.id) or _stored_attempt_row(
                    conn, learner_id, item.id, issued["submitted_at"])
                if row is not None:
                    # 这一题已经有落库的作答 —— 回读，绝不重判。
                    outcome = _ReplayedOutcome(row, MasterySnapshotRepository(conn).get(
                        learner_id, row["knowledge_node_id"]))
                    judgment = _stored_judgment(conn, row["id"])
                else:
                    # Judge exactly what the deterministic grader cannot
                    # settle — the same predicate select_item used to decide
                    # this item was servable in the first place. Keying off
                    # item_type instead (as this did until 2026-08-21) sent
                    # every `short` item to string comparison, including the
                    # ones whose reference answer is a paragraph.
                    if judge is not None and needs_judgment(item):
                        judgment = judge_open_response(
                            judge, item, ans.response, model_ref=judge_ref)
                    try:
                        outcome = record_attempt(
                            conn,
                            NewAttemptInput(
                                learner_id=learner_id,
                                assessment_item_id=item.id,
                                response=ans.response,
                                started_at=ans.started_at or now,
                                # 用这一组的提交时间，不是"此刻" —— 回读靠
                                # learner_id + submitted_at 认这一组的作答，补写的
                                # 题若打上新时间戳，下次就再也回读不到它。
                                submitted_at=issued["submitted_at"] or now,
                                source="web",
                                # 幂等键由**服务端**从 (组, 题) 派生，不用客户端传来的。
                                # student_attempts.id 就是这个键，AttemptRepository
                                # 用 INSERT OR IGNORE 在主键上做去重 —— 机制一直都在，
                                # 但只要客户端每次重试都换个新键，它就等于自己把去重
                                # 关掉了。第五轮质检席的并发攻击正是这么打的：3 路并发
                                # 各带不同 client_attempt_id，同一题落 2 条矛盾作答，
                                # FSRS 的 review_states.lapses 被推到 11。
                                # 派生之后：同一组同一题无论交多少次、几路并发，
                                # 落库的都是同一个主键，第一路写入、其余走重放分支。
                                client_attempt_id=f"{payload.set_id}:{item.id}",
                                judgment=judgment,
                            ),
                        )
                    except ValidationError as exc:
                        raise HTTPException(status_code=400, detail=str(exc)) from exc

                node = nodes.get(item.knowledge_node_id)
                results.append({
                    # 掌握度与复习状态在循环结束后统一回填 —— 见下方说明。
                    "_node_id": item.knowledge_node_id,
                    "item_id": item.id,
                    "prompt": item.prompt,
                    "figure_url": f"/api/edu/figures/{item.figure_spec_id}" if item.figure_spec_id else None,
                    # 回显落库的那条，不是这次 payload。
                    # 第三轮质检席 CRITICAL-3：复用同一个 client_attempt_id 配一段新
                    # 乱码，底层正确地保持首次作答不变（幂等），但响应把"新乱码 +
                    # 旧判分"拼在一起回吐，构成"乱打也算对"的展示层假象 —— 任何只信
                    # 这次响应、不回查库的下游（家长复盘页、截图取证）都会被骗。
                    "your_response": outcome.attempt.response,
                    "is_correct": effective_correctness(outcome.attempt.is_correct, judgment),
                    "raw_is_correct": outcome.attempt.is_correct,
                    "needs_judgment": effective_correctness(outcome.attempt.is_correct, judgment) is None,
                    # ↓ 全组已落库，到这一步才允许出现
                    "correct_answer": item.expected_answer,
                    "choices": json.loads(item.choices_json) if item.choices_json else None,
                    "explanation": item.explanation,
                    "explanation_source": item.explanation_source,
                    "knowledge_point": None if node is None else {
                        "code": node.code, "title": node.title,
                        "standard_code": node.standard_code,
                    },
                    # 判定理由（rationale）是写给大人的，且 rubric 绝不出网线，
                    # 所以这里只给 verdict 与置信度。
                    "judged": None if judgment is None else {
                        "verdict": judgment.verdict.value, "confidence": judgment.confidence,
                    },
                    "pending_recompute": outcome.pending_recompute,
                })

            # 一组里往往有好几道题落在同一个知识点上。若在循环内逐题读掌握度/
            # 复习状态，先落库的那几行读到的是**循环中途**的快照，同一份复盘里会
            # 出现同一个知识点的两个不同数值；重放时再读又都变成终态，看起来像
            # "重放把状态又推了一遍"（实际库里没变）。给孩子和家长看的应该是这一组
            # 交完之后的终态，所以统一放到循环之后取。
            for row in results:
                node_id = row.pop("_node_id")
                snapshot = MasterySnapshotRepository(conn).get(learner_id, node_id)
                review = ReviewStateRepository(conn).get(learner_id, node_id)
                row["mastery"] = None if snapshot is None else {
                    "score": snapshot.score, "status": snapshot.status,
                }
                row["learning_evidence"] = learning_evidence(conn, learner_id, node_id)
                row["review"] = None if review is None else {
                    "due_at": review.due_at, "reps": review.reps, "lapses": review.lapses,
                }

            chat_handoff = None
            if teaching_mode():
                from deeptutor.education.application.quiz_chat import handoff
                # A failure is observable; submitted answers remain durable and
                # recover/retry replays the same grades before retrying delivery.
                chat_handoff = handoff(conn, learner_id, payload.set_id, results)
            graded = [r for r in results if r["is_correct"] is not None]
            public_results = results if not teaching_mode() else [
                {key: row[key] for key in ("item_id", "prompt", "your_response", "is_correct", "needs_judgment", "correct_answer")}
                for row in results]
            return {
                "results": public_results,
                **({"chat_handoff": chat_handoff} if chat_handoff else {}),
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
    def progress(learner_id: str, course_version_id: str, request: Request) -> dict[str, Any]:
        conn = connect()
        try:
            require_learner(conn, learner_id, request)
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
                        "learning_evidence": learning_evidence(conn, learner_id, node_id),
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

    @app.get("/practice")
    def practice() -> FileResponse:
        """远程入口（2026-08-21 Sol 批准）。

        与 ``/`` 返回同一个页面，存在的唯一理由是 Cloudflare Tunnel 的 ingress
        按**路径**分流：``mytutors.cc/`` 归主应用（3782），这里再挂一个不与主应用
        冲突的路径，孩子在任何设备上只需记 mytutors.cc 一个网址。

        cloudflared 的 ingress 不改写路径，所以这个路由必须真实存在 —— 不能靠
        把 ``/practice`` 映射到 ``/``。页面自身是单文件、无外链资源，它发出的
        ``/api/edu/*`` 请求由同一份 ingress 的另一条规则送到本服务。
        """
        return FileResponse(STATIC_DIR / "index.html")

    return app
