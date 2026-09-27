"""Server-owned handoff of completed Quiz evidence into the student's Chat."""
from __future__ import annotations
import json


def handoff(conn, learner_id: str, set_id: str, results: list[dict], *, event_id: str | None = None) -> dict:
    from deeptutor.multi_user.identity import get_user_by_id
    from deeptutor.multi_user.paths import scope_for_user, get_path_service_for_scope
    from deeptutor.services.session.sqlite_store import SQLiteSessionStore

    row = conn.execute("SELECT deep_tutor_user_id FROM learner_profiles WHERE id=?", (learner_id,)).fetchone()
    record = get_user_by_id(row[0]) if row else None
    if not record or record[1]["role"] != "student" or record[1].get("disabled"):
        raise ValueError("Quiz learner must map to an active student account")
    uid = record[1]["id"]
    # Explicit student scope: the education service's background/default scope
    # must never choose the administrator's conversation database.
    path = get_path_service_for_scope(scope_for_user(uid, is_admin=False)).get_chat_history_db()
    from deeptutor.multi_user import teaching_identity
    with teaching_identity.connect() as identity_conn:
        appearance=identity_conn.execute("SELECT preferences FROM appearance WHERE user_id=?",(uid,)).fetchone()
    language=(json.loads(appearance[0]).get("language") if appearance else None) or "en"
    labels={
        "en":("Quiz explanations and corrections","Your questions, original answers and grading evidence are saved here. We can work through anything you would like to understand.","Question","Your original answer","Result","Reference answer","Knowledge point","Explanation source","Awaiting review","Correct","Needs correction","There is no approved explanation for this question yet. We can work through it using the question and grading evidence."),
        "zh":("Quiz 讲解与订正","题目、原始作答和批改结果已自动带到这里，可以接着讨论不理解的地方。","题目","你的原始作答","批改结果","参考答案","知识点","讲解来源","等待复核","正确","需要订正","此题暂无已核准的讲解。我们可以根据题目和批改结果逐步分析。"),
        "zh-Hant":("Quiz 講解與訂正","題目、原始作答和批改結果已自動帶到這裡，可以接著討論不理解的地方。","題目","你的原始作答","批改結果","參考答案","知識點","講解來源","等待複核","正確","需要訂正","此題暫無已核准的講解。我們可以根據題目和批改結果逐步分析。"),
    }[language if language in {"en","zh","zh-Hant"} else "en"]
    heading = ({"en":"Grading review update","zh":"批改复核更新","zh-Hant":"批改複核更新"}.get(language,"Grading review update") if event_id else labels[0])
    lines = ["## "+heading, "", labels[1]]
    for index, result in enumerate(results, 1):
        verdict = labels[8] if result["is_correct"] is None else labels[9] if result["is_correct"] else labels[10]
        lines.extend(["", f"### {labels[2]} {index}", "", result["prompt"], "",
                      f"**{labels[3]}:** " + str(result["your_response"]), "",
                      f"**{labels[4]}:** " + verdict, "", f"**{labels[5]}:** " + str(result["correct_answer"])])
        knowledge = result.get("knowledge_point") or {}
        if knowledge.get("title"):
            lines.extend(["", f"**{labels[6]}:** " + knowledge["title"]])
        lines.extend(["", result.get("explanation") or labels[11]])
        if result.get("explanation_source"):
            lines.extend(["", f"**{labels[7]}:** " + str(result["explanation_source"])])
    evidence = {"set_id": set_id, "learner_id": learner_id, "results": results}
    store = SQLiteSessionStore(db_path=path, migrate_legacy=False)
    session_id = store.receive_quiz_explanation(set_id, "\n".join(lines), evidence, title=labels[0],event_id=event_id)
    return {"session_id": session_id, "href": "/home/" + session_id}


def handoff_review(conn, attempt_id: str) -> dict | None:
    """Append a reviewed verdict without replacing the student's prior record."""
    from deeptutor.education.storage.repositories import JudgmentRepository
    from deeptutor.education.application.effective_grade import effective_correctness
    row = conn.execute("""SELECT a.*,i.prompt,i.expected_answer,i.explanation,i.explanation_source,
        n.title AS node_title,n.code AS node_code FROM student_attempts a
        JOIN assessment_items i ON i.id=a.assessment_item_id
        JOIN knowledge_nodes n ON n.id=a.knowledge_node_id WHERE a.id=?""", (attempt_id,)).fetchone()
    if row is None:
        raise ValueError("Original attempt not found")
    # Web attempt IDs bind the server-issued set and item. A legacy standalone
    # attempt gets its own review conversation rather than a guessed set.
    suffix = ":" + row["assessment_item_id"]
    candidate = attempt_id[:-len(suffix)] if attempt_id.endswith(suffix) else ""
    issued = conn.execute("SELECT id FROM task_sets WHERE id=? AND learner_id=?", (candidate,row["learner_id"])).fetchone()
    source_id = issued[0] if issued else "attempt:" + attempt_id
    judgment = JudgmentRepository(conn).latest_for_attempt(attempt_id)
    if judgment is None:
        return None
    result = {"item_id":row["assessment_item_id"],"prompt":row["prompt"],"your_response":row["response"],
              "is_correct":effective_correctness(row["is_correct"],judgment),"correct_answer":row["expected_answer"],
              "explanation":row["explanation"],"explanation_source":row["explanation_source"],
              "knowledge_point":{"title":row["node_title"],"code":row["node_code"]},
              "judged":{"id":judgment.id,"verdict":judgment.verdict.value,"confidence":judgment.confidence}}
    return handoff(conn,row["learner_id"],source_id,[result],event_id=judgment.id)
