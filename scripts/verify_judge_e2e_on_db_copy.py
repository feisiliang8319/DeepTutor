"""End-to-end check of the grading-policy fix against the real content.

Runs the real FastAPI app, with the real local oMLX judge, over a **copy**
of the production education database — the children's attempts must not get
a synthetic row in them, and ``student_attempts`` is append-only so a
mistake here could not be deleted afterwards.

What it proves that the unit tests cannot: that the six AP World History
SAQs, whose rubrics and prompts are real copyrighted content rather than
fixtures, are now (a) picked by the selector and (b) resolved by the judge
into a stored verdict rather than left unresolved.

Usage: ``.venv/bin/python scripts/verify_judge_e2e_on_db_copy.py [learner]``
"""

from __future__ import annotations

from pathlib import Path
import shutil
import sqlite3
import sys
import tempfile

from fastapi.testclient import TestClient

from deeptutor.education.api.app import create_app
from deeptutor.education.application.llm_judge import LocalOpenAIJudge

SOURCE_DB = Path("/Users/gwp_group/Projects/deeptutor-education/data/education.db")
COURSE = "cv-hist-apworld-1.0.0"
MODEL = "Qwen3-VL-8B-Instruct-4bit"

# Deliberately substantive but not copied from any rubric: the point is to
# see the judge distinguish it from the nonsense answer below.
GOOD = (
    "Muslim merchants and Sufi missionaries carried Islam along Indian Ocean "
    "trade routes into South and Southeast Asia, and rulers who converted, as "
    "in the Delhi Sultanate and Malacca, used Islamic law and patronage to "
    "legitimise their states."
)
NONSENSE = "The Mongols conquered Japan in 1850 and made everyone convert."


def main(learner: str) -> int:
    tmp_dir = Path(tempfile.mkdtemp(prefix="edu-e2e-"))
    db = tmp_dir / "education.db"
    shutil.copy2(SOURCE_DB, db)
    print(f"copy under test: {db}\n(source untouched: {SOURCE_DB})\n")

    client = TestClient(create_app(db, judge=LocalOpenAIJudge(), judge_ref=MODEL))

    # The selector picks the *least-attempted* item on each node, breaking
    # ties on id. Every AP node carries both an MCQ and an SAQ, and "mcq"
    # sorts before "saq", so a first-ever set is all MCQs even now that the
    # SAQs are servable — they surface on the next pass. That is the
    # intended spread-before-repeat behaviour, but it means "unlocked" and
    # "will show up today" are different claims, so this walks the rounds
    # rather than asserting round one contains an SAQ.
    ids: list[str] = []
    saqs: list[str] = []
    for round_no in range(1, 5):
        issued = client.post(
            "/api/edu/set", params={"learner_id": learner, "course_version_id": COURSE}
        ).json()
        if "items" not in issued:
            print(f"could not draw a set: {issued}")
            return 1
        ids = [i["id"] for i in issued["items"]]
        saqs = [i for i in ids if "saq" in i]
        print(f"round {round_no}: {len(ids)} items, {len(saqs)} SAQ -> {ids}")
        if saqs:
            break
        # Burn this round with placeholder answers so the next draw moves on.
        client.post("/api/edu/set/submit", json={
            "learner_id": learner, "course_version_id": COURSE,
            "set_id": issued["set_id"],
            "answers": [{"item_id": i, "response": "A"} for i in ids],
        })
    if not saqs:
        print("FAIL: no SAQ surfaced in four rounds — the six items are unreachable")
        return 1

    answers = []
    for item_id in ids:
        if item_id == saqs[0]:
            answers.append({"item_id": item_id, "response": GOOD})
        elif item_id in saqs:
            answers.append({"item_id": item_id, "response": NONSENSE})
        else:
            answers.append({"item_id": item_id, "response": "A"})

    body = client.post("/api/edu/set/submit", json={
        "learner_id": learner, "course_version_id": COURSE,
        "set_id": issued["set_id"], "answers": answers,
    }).json()

    print("\nper-item outcome:")
    ok = True
    for row in body["results"]:
        judged = row["judged"]
        kind = "SAQ" if row["item_id"] in saqs else "MCQ"
        print(f"  [{kind}] {row['item_id']}")
        print(f"        is_correct={row['is_correct']} needs_judgment={row['needs_judgment']} "
              f"judged={judged}")
        if kind == "SAQ" and judged is None:
            print("        FAIL: served but never judged — this is the void the fix closes")
            ok = False

    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    stored = conn.execute(
        """
        SELECT j.verdict, j.confidence, j.prompt_version, j.judge_kind, a.assessment_item_id
        FROM judgment_records j JOIN student_attempts a ON a.id = j.attempt_id
        WHERE a.assessment_item_id LIKE '%saq%'
        """
    ).fetchall()
    print(f"\njudgment_records rows written for SAQs: {len(stored)}")
    for r in stored:
        print(f"  {r['assessment_item_id']}: {r['verdict']} conf={r['confidence']} "
              f"prompt={r['prompt_version']} kind={r['judge_kind']}")
    if not stored:
        print("FAIL: verdicts were not persisted — mastery rebuild would see nothing")
        ok = False
    conn.close()

    # The leak gate still holds on the new path.
    raw = client.post("/api/edu/set", params={
        "learner_id": learner, "course_version_id": COURSE}).text
    for forbidden in ("expected_answer", "rubric_json", "MARKING FOCUS"):
        if forbidden in raw:
            print(f"FAIL: {forbidden!r} crossed the wire")
            ok = False
    print("\nleak gate: no expected_answer / rubric_json / marking focus in the item payload")

    print(f"\ntemp copy left at {tmp_dir} for inspection; delete when done")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "rayn"))
