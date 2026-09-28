"""Read teaching memory from its evidence store, never from casual chat claims."""
from __future__ import annotations
import os
import sqlite3
from pathlib import Path


def read(user_id: str, *, include_private: bool = False) -> dict:
    configured=os.environ.get("TEACHING_EDUCATION_DB","")
    if not configured:
        raise RuntimeError("The teaching evidence database has not been configured")
    path=Path(configured).expanduser().resolve()
    if not path.is_file():
        raise RuntimeError("The teaching evidence database is unavailable")
    conn=sqlite3.connect(path.as_uri()+"?mode=ro",uri=True,timeout=5)
    conn.row_factory=sqlite3.Row
    try:
        learner=conn.execute("SELECT id FROM learner_profiles WHERE deep_tutor_user_id=?",(user_id,)).fetchone()
        if learner is None:
            return {"learner_id":None,"states":[],"attempts":[],"source":"education"}
        states=[dict(r) for r in conn.execute("""SELECT m.*,n.title,n.code,r.due_at FROM mastery_snapshots m
          JOIN knowledge_nodes n ON n.id=m.knowledge_node_id
          LEFT JOIN review_states r ON r.learner_id=m.learner_id AND r.knowledge_node_id=m.knowledge_node_id
          WHERE m.learner_id=? ORDER BY m.updated_at DESC LIMIT 100""",(learner[0],))]
        attempts=[dict(r) for r in conn.execute("""SELECT a.id,a.assessment_item_id,a.knowledge_node_id,a.response,a.is_correct,
          a.submitted_at,a.grader_version,a.evidence_strength,i.prompt FROM student_attempts a
          JOIN assessment_items i ON i.id=a.assessment_item_id WHERE a.learner_id=? ORDER BY a.submitted_at DESC,a.id DESC LIMIT 30""",(learner[0],))]
        from deeptutor.education.storage.repositories import JudgmentRepository
        from deeptutor.education.application.effective_grade import effective_correctness
        judgments = JudgmentRepository(conn)
        for attempt in attempts:
            # Grader notes may quote private rubrics. Only adult review surfaces
            # receive them; student Chat gets the verdict and immutable answer.
            fields = "id,judge_kind,verdict,confidence,created_at" + (",rationale" if include_private else "")
            attempt["judgments"] = [dict(r) for r in conn.execute(
                f"SELECT {fields} FROM judgment_records WHERE attempt_id=? ORDER BY created_at,rowid", (attempt["id"],))]
            attempt["effective_is_correct"] = effective_correctness(attempt["is_correct"], judgments.latest_for_attempt(attempt["id"]))
        placements=[]
        if conn.execute("SELECT 1 FROM sqlite_master WHERE name='subject_placements'").fetchone():
            placements=[dict(r) for r in conn.execute("SELECT subject_key,curriculum_key,grade,entry_level FROM subject_placements WHERE learner_id=?",(learner[0],))]
        assessments=[]
        if conn.execute("SELECT 1 FROM sqlite_master WHERE name='competition_foundation_choices'").fetchone():
            from deeptutor.education.application.assessment_engine import exam_result
            for exam in conn.execute("SELECT * FROM formal_exams WHERE learner_id=? AND result_json IS NOT NULL ORDER BY deadline DESC LIMIT 10",(learner[0],)):
                result=exam_result(conn,exam)
                assessments.append({'set_id':exam['set_id'],'subject_key':exam['subject_key'],'grade':exam['grade'],'kind':exam['kind'],**{k:result[k] for k in ('status','percent','passed','core','promotion','foundation_followup','diagnostic_only') if k in result}})
        return {"assessments":assessments,"learner_id":learner[0],"states":states,"attempts":attempts,"placements":placements,"placement_note":"Learning grade and initial placement are teaching context, not mastery evidence. Competition advancement does not establish foundational mastery; a skipped foundation check remains unverified.","source":"education"}
    finally:
        conn.close()


class ActiveAssessmentError(RuntimeError):
    pass


def assert_no_active_assessment(user_id: str) -> None:
    """Do not provide Chat assistance while a formal independent exam is open."""
    configured=os.environ.get("TEACHING_EDUCATION_DB", "")
    if not configured:
        return
    path=Path(configured).expanduser().resolve()
    if not path.is_file():
        raise RuntimeError("The teaching assessment database is unavailable")
    conn=sqlite3.connect(path.as_uri()+"?mode=ro",uri=True,timeout=5)
    try:
        if not conn.execute("SELECT 1 FROM sqlite_master WHERE name='formal_exams'").fetchone():
            return
        exam=conn.execute("SELECT 1 FROM formal_exams f JOIN learner_profiles l ON l.id=f.learner_id JOIN task_sets t ON t.id=f.set_id WHERE l.deep_tutor_user_id=? AND t.submitted_at IS NULL AND t.skipped_at IS NULL LIMIT 1",(user_id,)).fetchone()
        if exam:
            raise ActiveAssessmentError("Please submit your current Quiz before returning to Chat. 请先提交当前测试，再回到 Chat 学习与订正。")
    finally:
        conn.close()


def enforce_exam_access(user_id: str, role: str, path: str) -> None:
    """HTTP resources are guarded as well as the existing per-turn Chat gate."""
    from fastapi import HTTPException
    from .teaching_identity import active
    if role != 'student' or not active():
        return
    if path in {'/api/v1/auth/status','/api/v1/auth/logout','/api/v1/capabilities','/api/v1/settings/ui','/api/v1/teaching/appearance'} or path.startswith('/api/v1/auth/profile'):
        return
    try:
        assert_no_active_assessment(user_id)
    except ActiveAssessmentError as exc:
        raise HTTPException(423, '独立测试进行中，暂时不能使用 Chat、资料或其他测试记录。') from exc
