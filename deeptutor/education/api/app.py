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

from datetime import datetime
import json
import os
from pathlib import Path
import sqlite3
import time
from typing import Any
import uuid

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from deeptutor.education.application import to_iso_timestamp
from deeptutor.education.application.grading_policy import needs_judgment
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
from deeptutor.education.application.select_objective import list_available_objectives
from deeptutor.education.domain.course import ItemStatus
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
        row = conn.execute(
            "SELECT verdict, confidence FROM judgment_records WHERE attempt_id = ? "
            "ORDER BY created_at DESC LIMIT 1",
            (attempt_id,),
        ).fetchone()
        return None if row is None else _StoredJudgment(row)

    class _StoredJudgment:
        def __init__(self, row):
            self.verdict = _EnumLike(row["verdict"])
            self.confidence = row["confidence"]

    class _EnumLike:
        def __init__(self, value):
            self.value = value

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

    @app.post("/api/edu/set")
    def task_set(learner_id: str, course_version_id: str) -> dict[str, Any]:
        """发一组题；组由**服务端**发、服务端记。

        **是 POST 不是 GET**：这个端点会 INSERT 一行 task_sets。挂在 GET 上曾让
        两个人（第四轮质检席、以及我自己）在"只读复验"时意外写进生产库 ——
        HTTP 语义里 GET 应当是安全的，任何巡检/监控/重试都可能打它。

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
                wanted = json.loads(open_set["item_ids_json"])
                fetched = [items_repo.get(i) for i in wanted]
                # 组里有题在发卷之后被下架/删掉了，就整组作废重发。
                # 第四轮质检席 A-新2：原先照发不误，孩子答完提交时才在
                # record_attempt 里炸出 "is retired and cannot be attempted"，
                # 而那时这一组已经被标记成已交 —— 永久卡死、复盘丢失。
                # 未作答的组删掉是安全的：没有任何作答记录引用它。
                if any(it is None or it.status is ItemStatus.RETIRED for it in fetched):
                    with conn:
                        conn.execute("DELETE FROM task_sets WHERE id = ?", (open_set["id"],))
                else:
                    return {"done": False, "set_id": open_set["id"],
                            "items": [_public_item(it, nodes.get(it.knowledge_node_id))
                                      for it in fetched],
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
                    "AND course_version_id = ? AND submitted_at IS NULL",
                    (learner_id, course_version_id),
                ).fetchone()
                if row is None:
                    raise
                items_repo = AssessmentItemRepository(conn)
                nodes = {n.id: n for n in
                         KnowledgeGraphRepository(conn).list_nodes(course_version_id)}
                reissued = [_public_item(it, nodes.get(it.knowledge_node_id))
                            for it in (items_repo.get(i)
                                       for i in json.loads(row["item_ids_json"]))
                            if it is not None]
                return {"done": False, "set_id": row["id"], "items": reissued,
                        "reissued": True, "skipped_empty_nodes": [], "message": None}
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

            # 落库之前先把整组过一遍：有一题不可作答（已下架/已删）就整组拒绝，
            # **在认领这一组之前**。否则会重演 A-新2：标记已交了，评分循环才炸。
            for _, item in resolved:
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
            with conn:
                claimed = conn.execute(
                    "UPDATE task_sets SET submitted_at = ? WHERE id = ? "
                    "AND submitted_at IS NULL",
                    (now, payload.set_id),
                ).rowcount == 1
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
                    # 回显落库的那条，不是这次 payload。
                    # 第三轮质检席 CRITICAL-3：复用同一个 client_attempt_id 配一段新
                    # 乱码，底层正确地保持首次作答不变（幂等），但响应把"新乱码 +
                    # 旧判分"拼在一起回吐，构成"乱打也算对"的展示层假象 —— 任何只信
                    # 这次响应、不回查库的下游（家长复盘页、截图取证）都会被骗。
                    "your_response": outcome.attempt.response,
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
                row["review"] = None if review is None else {
                    "due_at": review.due_at, "reps": review.reps, "lapses": review.lapses,
                }

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
