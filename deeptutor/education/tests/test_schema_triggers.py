"""Destructive-injection tests #1-3, #10, #12, and the two "13c" tests
(P0-DESIGN.md §6): append-only enforcement, migration idempotency, startup
fail-closed on a tampered schema, migration-time rollback on a broken
script, and (test #12) that no path — including a redo-style reset of
derived state — can alter or delete a committed attempt.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sqlite3
import time

import pytest

from deeptutor.education.application import to_iso_timestamp
from deeptutor.education.domain.evidence import JudgeKind, JudgmentRecord, StudentAttempt, Verdict
from deeptutor.education.storage import sqlite as edu_sqlite
from deeptutor.education.storage.repositories import (
    AssessmentItemRepository,
    AttemptRepository,
    JudgmentRepository,
    KnowledgeGraphRepository,
    MasterySnapshotRepository,
)
from deeptutor.education.tests.fixtures import build_fixture_a_math


def _seed_one_attempt(conn: sqlite3.Connection, learner, course_version) -> StudentAttempt:
    bundle = build_fixture_a_math(course_version.id)
    KnowledgeGraphRepository(conn).import_nodes_and_edges(
        course_version_id=course_version.id, nodes=bundle.nodes, edges=bundle.edges
    )
    items = AssessmentItemRepository(conn).import_items(bundle.item_rows)
    item = items[0]
    now = to_iso_timestamp(time.time())
    attempt = StudentAttempt(
        id="attempt-1",
        learner_id=learner.id,
        assessment_item_id=item.id,
        knowledge_node_id=item.knowledge_node_id,
        course_version_id=item.course_version_id,
        response="42",
        is_correct=True,
        score=1.0,
        started_at=now,
        submitted_at=now,
        grader_version="test-v1",
        source="practice",
        created_at=now,
    )
    AttemptRepository(conn).insert(attempt)
    return attempt


# ---- test #1: direct UPDATE student_attempts -------------------------------


def test_direct_update_student_attempts_is_aborted(conn, learner, course_version):
    _seed_one_attempt(conn, learner, course_version)
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        conn.execute("UPDATE student_attempts SET is_correct = 0 WHERE id = 'attempt-1'")
    # And the row is unchanged.
    row = conn.execute("SELECT is_correct FROM student_attempts WHERE id = 'attempt-1'").fetchone()
    assert row["is_correct"] == 1


# ---- test #2: direct DELETE student_attempts -------------------------------


def test_direct_delete_student_attempts_is_aborted(conn, learner, course_version):
    _seed_one_attempt(conn, learner, course_version)
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        conn.execute("DELETE FROM student_attempts WHERE id = 'attempt-1'")
    count = conn.execute("SELECT COUNT(*) AS n FROM student_attempts").fetchone()["n"]
    assert count == 1


# ---- test #3: direct UPDATE judgment_records -------------------------------


def test_direct_update_judgment_records_is_aborted(conn, learner, course_version):
    attempt = _seed_one_attempt(conn, learner, course_version)
    judgment = JudgmentRecord(
        id="judgment-1",
        attempt_id=attempt.id,
        judge_kind=JudgeKind.LLM,
        judge_ref="test-model",
        verdict=Verdict.CORRECT,
        created_at=to_iso_timestamp(time.time()),
    )
    JudgmentRepository(conn).insert(judgment)
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        conn.execute("UPDATE judgment_records SET verdict = 'incorrect' WHERE id = 'judgment-1'")
    row = conn.execute("SELECT verdict FROM judgment_records WHERE id = 'judgment-1'").fetchone()
    assert row["verdict"] == "correct"


def test_direct_delete_judgment_records_is_aborted(conn, learner, course_version):
    """Not one of the task's numbered 9, but explicitly required by the
    hard constraints ("student_attempts 与 judgment_records 的 BEFORE UPDATE
    / BEFORE DELETE 触发器") — judgment_records must be no-delete too, or it
    is not actually append-only."""
    attempt = _seed_one_attempt(conn, learner, course_version)
    judgment = JudgmentRecord(
        id="judgment-2",
        attempt_id=attempt.id,
        judge_kind=JudgeKind.HUMAN,
        judge_ref="parent",
        verdict=Verdict.CORRECT,
        created_at=to_iso_timestamp(time.time()),
    )
    JudgmentRepository(conn).insert(judgment)
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        conn.execute("DELETE FROM judgment_records WHERE id = 'judgment-2'")


# ---- test #10: migration idempotency ---------------------------------------


def test_migration_first_run_creates_full_schema(db_path: Path):
    connection = edu_sqlite.open_database(db_path)
    try:
        tables = {
            row["name"]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
        expected = {
            "learner_profiles",
            "courses",
            "course_versions",
            "knowledge_nodes",
            "knowledge_edges",
            "assessment_items",
            "student_attempts",
            "judgment_records",
            "mastery_snapshots",
            "review_states",
        }
        assert expected <= tables
        assert edu_sqlite.check_trigger_integrity(connection) == frozenset()
    finally:
        connection.close()


def test_migration_rerun_is_a_noop(db_path: Path):
    conn1 = edu_sqlite.open_database(db_path)
    conn1.close()
    # Re-running the migration file directly (not just re-opening) must not
    # error and must not duplicate/alter anything.
    conn2 = edu_sqlite.connect_raw(db_path)
    try:
        for migration_file in sorted(edu_sqlite.MIGRATIONS_DIR.glob("*.sql")):
            edu_sqlite.apply_migration(conn2, migration_file)
        assert edu_sqlite.check_trigger_integrity(conn2) == frozenset()
    finally:
        conn2.close()


# ---- "13c" part 1: manual DROP TRIGGER -> startup refuses -----------------


def test_startup_refuses_when_a_trigger_is_missing(db_path: Path):
    conn1 = edu_sqlite.open_database(db_path)
    conn1.close()

    raw = sqlite3.connect(str(db_path))
    raw.execute("DROP TRIGGER trg_judgments_no_update")
    raw.commit()
    raw.close()

    with pytest.raises(edu_sqlite.SchemaIntegrityError, match="trg_judgments_no_update"):
        edu_sqlite.open_database(db_path)


def test_startup_refuses_and_does_not_silently_heal(db_path: Path):
    """The refusal must not be a disguised auto-repair: after the refusal,
    the trigger must still be missing (open_database did not quietly
    recreate it before raising)."""
    conn1 = edu_sqlite.open_database(db_path)
    conn1.close()
    raw = sqlite3.connect(str(db_path))
    raw.execute("DROP TRIGGER trg_attempts_no_delete")
    raw.commit()
    raw.close()

    with pytest.raises(edu_sqlite.SchemaIntegrityError):
        edu_sqlite.open_database(db_path)

    check = sqlite3.connect(str(db_path))
    try:
        present = {
            row[0] for row in check.execute("SELECT name FROM sqlite_master WHERE type='trigger'").fetchall()
        }
        assert "trg_attempts_no_delete" not in present
    finally:
        check.close()


# ---- "13c" part 2: migration mid-way loses a trigger -> full rollback -----


def test_migration_rolls_back_entirely_if_a_trigger_ends_up_missing(tmp_path: Path):
    broken_sql = """
    CREATE TABLE IF NOT EXISTS learner_profiles (id TEXT PRIMARY KEY);
    CREATE TABLE IF NOT EXISTS student_attempts (id TEXT PRIMARY KEY);
    CREATE TABLE IF NOT EXISTS judgment_records (id TEXT PRIMARY KEY);
    CREATE TRIGGER IF NOT EXISTS trg_attempts_no_update
    BEFORE UPDATE ON student_attempts
    BEGIN SELECT RAISE(ABORT, 'student_attempts is append-only'); END;
    -- deliberately missing the other three required triggers
    """
    sql_path = tmp_path / "broken_001.sql"
    sql_path.write_text(broken_sql)
    db_path = tmp_path / "broken.db"

    connection = edu_sqlite.connect_raw(db_path)
    try:
        with pytest.raises(edu_sqlite.MigrationError):
            edu_sqlite.apply_migration(connection, sql_path)
        tables = connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        ).fetchall()
        assert tables == [], "a failed migration must leave zero tables behind, not a partial schema"
    finally:
        connection.close()


# ---- test #12: redo semantics must not alter/delete student_attempts -----


def _hash_attempts_table(conn: sqlite3.Connection) -> str:
    """A content hash over the full student_attempts table, order-independent
    at the row level (sorted by id) but sensitive to every column value —
    good enough to detect "same row count, different content" as well as
    "different row count"."""
    rows = conn.execute("SELECT * FROM student_attempts ORDER BY id").fetchall()
    canonical = json.dumps([dict(row) for row in rows], sort_keys=True, default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def test_redo_style_reset_of_derived_state_leaves_attempts_byte_identical(conn, learner, course_version):
    """2026-08-14 audit finding (defect 3): test matrix item #12 ("redo 后
    attempt 数量与 hash 不变") was previously skipped on the theory that it
    needs a deeptutor/learning adapter. It doesn't — the claim under test is
    "no path can alter/delete a committed attempt", which is testable
    entirely within this package by simulating redo's derived-state-reset
    semantics (deeptutor/api/routers/mastery_path.py's redo_progress()
    clears quiz_attempts/error_records/repetition_states — the P0 analogues
    of mastery_snapshots/review_states, never student_attempts) and
    asserting attempts survive unchanged, in both count and content hash.
    """
    bundle = build_fixture_a_math(course_version.id)
    KnowledgeGraphRepository(conn).import_nodes_and_edges(
        course_version_id=course_version.id, nodes=bundle.nodes, edges=bundle.edges
    )
    items = AssessmentItemRepository(conn).import_items(bundle.item_rows)

    for i, item in enumerate(items):
        now = to_iso_timestamp(time.time())
        AttemptRepository(conn).insert(
            StudentAttempt(
                id=f"redo-attempt-{i}",
                learner_id=learner.id,
                assessment_item_id=item.id,
                knowledge_node_id=item.knowledge_node_id,
                course_version_id=item.course_version_id,
                response="some response",
                is_correct=bool(i % 2),
                score=1.0 if i % 2 else 0.0,
                started_at=now,
                submitted_at=now,
                grader_version="v1",
                source="practice",
                created_at=now,
            )
        )

    before_count = AttemptRepository(conn).count_for_learner(learner.id)
    before_hash = _hash_attempts_table(conn)
    assert before_count == len(items)

    # Simulate redo: reset every piece of *derived* state this package owns.
    # review_states has no append-only trigger — clearing it is legitimate
    # (P0-DESIGN.md §2.8 explicitly excludes it from the rebuild-exactness
    # contract that applies to attempts).
    MasterySnapshotRepository(conn).delete_all()
    conn.execute("DELETE FROM review_states")

    after_count = AttemptRepository(conn).count_for_learner(learner.id)
    after_hash = _hash_attempts_table(conn)

    assert after_count == before_count
    assert after_hash == before_hash, "student_attempts must be byte-identical across a redo-style reset"

    # And the append-only guarantee is still live afterward — a redo-style
    # reset must not itself be (or degrade into) a path that can mutate
    # attempts.
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        conn.execute("UPDATE student_attempts SET is_correct = 0")
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        conn.execute("DELETE FROM student_attempts")
