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
        return {"learner_id":learner[0],"states":states,"attempts":attempts,"source":"education"}
    finally:
        conn.close()
