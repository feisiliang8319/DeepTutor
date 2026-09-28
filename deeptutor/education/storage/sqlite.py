"""Connection management, migration application, and the append-only
trigger integrity self-check.

Two independent fail-closed checks live here, both from P0-DESIGN.md §2.5
("逃生舱的漏洞与补法"):

1. ``apply_migration`` — a *migration-time* assertion. If the SQL being
   applied does not leave all four append-only triggers in place, the whole
   migration (tables, indexes, everything it just created) is rolled back
   as one unit. A migration that silently drops enforcement is treated the
   same as a migration that fails outright.
2. ``open_database`` — a *startup-time* assertion. If a database that
   already has the ``student_attempts`` table is missing any of the four
   triggers (e.g. someone ran ``DROP TRIGGER`` by hand), the application
   refuses to open it at all. This deliberately does **not** try to
   self-heal by re-running the migration — silently recreating a trigger
   someone removed would hide exactly the tampering this check exists to
   catch.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
import sqlite3

MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"

# Single source of truth for "is the append-only guarantee intact". Keep in
# sync with the CREATE TRIGGER statements in
# storage/migrations/001_education_minimum.sql.
REQUIRED_TRIGGERS: frozenset[str] = frozenset(
    {
        "trg_attempts_no_update",
        "trg_attempts_no_delete",
        "trg_judgments_no_update",
        "trg_judgments_no_delete",
    }
)

# Presence of this table is how we distinguish "fresh database, safe to run
# the migration for the first time" from "existing database, integrity
# problems must fail closed rather than be silently repaired".
_SENTINEL_TABLE = "student_attempts"

# Ledger of migration files already applied to this database.
#
# Added 2026-08-15. Before this, ``open_database`` ran migrations *only* on a
# fresh database; an existing one was verified but never migrated. That was
# fine while 001 was the only file, but it meant any later migration would
# silently never reach a database that already had data — the schema on disk
# and the schema in the repo would drift apart with nothing reporting it.
# Now every migration file is recorded here as it is applied, and startup
# applies exactly the ones this database has not seen.
_MIGRATIONS_TABLE = "schema_migrations"

# Databases created before the ledger existed have 001 applied but no ledger
# row for it. Re-running 001 would be wrong (it is not idempotent for the
# append-only triggers) and skipping the whole mechanism would be worse, so
# such databases are back-filled with exactly this entry and then migrated
# forward normally.
_PRE_LEDGER_MIGRATION = "001_education_minimum.sql"


class SchemaIntegrityError(RuntimeError):
    """Raised when an existing database is missing required append-only
    triggers. The caller must not proceed — there is no automatic repair."""


class MigrationError(RuntimeError):
    """Raised when applying a migration file did not leave the schema in
    the required state; the migration's transaction has already been rolled
    back by the time this is raised."""


def connect_raw(db_path: Path) -> sqlite3.Connection:
    """Open a connection with the invariants every write path in this
    package relies on: manual transaction control (so callers can group
    multi-statement writes atomically, see ``transaction`` below),
    dict-like row access, and enforced foreign keys."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


@contextmanager
def transaction(conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    """Group statements into one atomic write. Requires ``isolation_level is
    None`` (see ``connect_raw``) so we own BEGIN/COMMIT/ROLLBACK explicitly
    instead of relying on sqlite3's implicit-transaction heuristics, which
    is what makes the migration/attempt failure-injection tests in this
    package's test suite possible to write deterministically."""
    # Repository batch imports may be composed into a whole-course import.
    # A savepoint keeps the outer transaction's ownership intact.
    nested = conn.in_transaction
    if nested:
        import uuid
        savepoint = "education_" + uuid.uuid4().hex
        conn.execute(f"SAVEPOINT {savepoint}")
    else:
        conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
    except BaseException:
        if nested:
            conn.execute(f"ROLLBACK TO {savepoint}")
            conn.execute(f"RELEASE {savepoint}")
        else:
            conn.execute("ROLLBACK")
        raise
    else:
        conn.execute(f"RELEASE {savepoint}" if nested else "COMMIT")


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (name,)
    ).fetchone()
    return row is not None


def check_trigger_integrity(conn: sqlite3.Connection) -> frozenset[str]:
    """Return the subset of ``REQUIRED_TRIGGERS`` that is currently
    *missing* from this connection's database. Empty result == healthy."""
    present = {
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'trigger'"
        ).fetchall()
    }
    required = REQUIRED_TRIGGERS
    if _table_exists(conn, "task_set_submissions"):
        required = required | {"task_set_submissions_no_update", "task_set_submissions_no_delete"}
    for table in ("exam_score_reviews", "promotion_events", "placement_events", "competition_foundation_choices", "exam_integrity_events", "content_reviews"):
        if _table_exists(conn, table):
            required = required | {table + "_no_update", table + "_no_delete"}
    return frozenset(required - present)


def _iter_statements(sql_text: str) -> Iterator[str]:
    """Split a ``.sql`` file into individual top-level statements.

    A naive split on ``;`` breaks trigger bodies (``BEGIN ... END;`` itself
    contains a ``;``). ``sqlite3.complete_statement`` is the same primitive
    the ``sqlite3`` CLI shell uses to decide when buffered input forms one
    full statement, and it correctly treats an entire
    ``CREATE TRIGGER ... BEGIN ... END;`` block as one statement.
    """
    buf: list[str] = []
    for line in sql_text.splitlines(keepends=True):
        stripped = line.strip()
        if not stripped or stripped.startswith("--"):
            continue
        buf.append(line)
        candidate = "".join(buf)
        if sqlite3.complete_statement(candidate):
            yield candidate.strip()
            buf = []
    remainder = "".join(buf).strip()
    if remainder:
        yield remainder


def _applied_migrations(conn: sqlite3.Connection) -> set[str]:
    """Filenames this database has already had applied. Empty set if the
    ledger table does not exist yet (i.e. a fresh database)."""
    if not _table_exists(conn, _MIGRATIONS_TABLE):
        return set()
    rows = conn.execute(f"SELECT filename FROM {_MIGRATIONS_TABLE}").fetchall()
    return {r[0] for r in rows}


def apply_migration(conn: sqlite3.Connection, sql_path: Path) -> None:
    """Apply one migration file as a single atomic unit, then assert the
    append-only triggers are all present before committing.

    On any failure — a bad SQL statement, or a script that runs clean but
    leaves a trigger missing — the entire transaction is rolled back, so a
    half-applied migration never leaves partially-protected tables on disk
    (P0-DESIGN.md §6 test 13c, "migration 中途丢触发器 → 断言整体回滚").

    Re-applying a file that this database has already had applied is a no-op
    (the ledger is consulted first). That contract used to rest on every
    migration script being self-idempotent — workable while 001 was all
    ``CREATE TABLE IF NOT EXISTS``, but impossible for ``ALTER TABLE ADD
    COLUMN``, which SQLite offers no ``IF NOT EXISTS`` form for. Anchoring it
    to the ledger instead means a migration author no longer has to hand-roll
    idempotence in SQL, and cannot get it subtly wrong.
    """
    if sql_path.name in _applied_migrations(conn):
        return
    sql_text = sql_path.read_text(encoding="utf-8")
    statements = list(_iter_statements(sql_text))
    # SQLite requires FK enforcement to be suspended BEFORE a table rebuild
    # transaction. Only this reviewed migration needs the exception. Integrity
    # is checked before commit and enforcement is restored on every exit.
    rebuild = sql_path.name == "010_competition_foundation.sql"
    if rebuild:
        if conn.in_transaction:
            raise MigrationError("table rebuild cannot run inside an existing transaction")
        conn.execute("PRAGMA foreign_keys = OFF")
    try:
        conn.execute("BEGIN IMMEDIATE")
        for statement in statements:
            conn.execute(statement)
        # Ledger row goes in the SAME transaction as the DDL: if the script
        # fails halfway we roll back both, so "recorded as applied" can never
        # outlive a migration that did not actually land.
        conn.execute(
            f"CREATE TABLE IF NOT EXISTS {_MIGRATIONS_TABLE} ("
            "  filename   TEXT PRIMARY KEY,"
            "  applied_at TEXT NOT NULL DEFAULT (datetime('now'))"
            ")"
        )
        conn.execute(
            f"INSERT OR IGNORE INTO {_MIGRATIONS_TABLE} (filename) VALUES (?)",
            (sql_path.name,),
        )
        if rebuild and conn.execute("PRAGMA foreign_key_check").fetchone():
            raise MigrationError("table rebuild left invalid foreign-key references")
        missing = check_trigger_integrity(conn)
        if missing:
            raise MigrationError(
                f"migration {sql_path.name} left required triggers missing: "
                f"{sorted(missing)}"
            )
        conn.execute("COMMIT")
    except BaseException:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        raise
    finally:
        if rebuild:
            conn.execute("PRAGMA foreign_keys = ON")


def open_database(db_path: Path, *, migrations_dir: Path | None = None) -> sqlite3.Connection:
    """Application startup entrypoint: connect, migrate-if-fresh, and
    fail-closed if an existing database's append-only guarantees have been
    tampered with.

    Fresh database (no ``student_attempts`` table yet): run the full
    migration, then verify. Existing database: verify only — a missing
    trigger here means "someone bypassed the schema", and the correct
    response is to refuse to start, not to quietly recreate it.
    """
    conn = connect_raw(db_path)
    migrations = migrations_dir or MIGRATIONS_DIR
    try:
        fresh = not _table_exists(conn, _SENTINEL_TABLE)
        if not fresh and not _table_exists(conn, _MIGRATIONS_TABLE):
            # Pre-ledger database: it demonstrably has 001 (the sentinel table
            # comes from there), so record that and let anything newer run.
            conn.execute(
                f"CREATE TABLE IF NOT EXISTS {_MIGRATIONS_TABLE} ("
                "  filename   TEXT PRIMARY KEY,"
                "  applied_at TEXT NOT NULL DEFAULT (datetime('now'))"
                ")"
            )
            conn.execute(
                f"INSERT OR IGNORE INTO {_MIGRATIONS_TABLE} (filename) VALUES (?)",
                (_PRE_LEDGER_MIGRATION,),
            )
            conn.commit()
        applied = _applied_migrations(conn)
        for migration_file in sorted(migrations.glob("*.sql")):
            if migration_file.name in applied:
                continue
            apply_migration(conn, migration_file)
        missing = check_trigger_integrity(conn)
        if missing:
            raise SchemaIntegrityError(
                f"refusing to start: database {db_path} is missing required "
                f"append-only triggers {sorted(missing)}. This looks like the "
                "schema was modified outside the migration path (e.g. a "
                "manual DROP TRIGGER). Restore the triggers before retrying; "
                "this check will not recreate them automatically."
            )
    except BaseException:
        conn.close()
        raise
    return conn


__all__ = [
    "MIGRATIONS_DIR",
    "REQUIRED_TRIGGERS",
    "MigrationError",
    "SchemaIntegrityError",
    "apply_migration",
    "check_trigger_integrity",
    "connect_raw",
    "open_database",
    "transaction",
]
