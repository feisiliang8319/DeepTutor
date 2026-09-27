"""Transactional teaching identities. Activation is an explicit, offline migration.

This module uses only the standard library. It never reads secrets or silently
repairs a damaged store, and never falls back to legacy JSON after activation.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import sqlite3
from typing import Any, Iterator
from uuid import uuid4

MAX_STUDENTS_PER_PARENT = 5

SCHEMA = f"""
CREATE TABLE metadata (version INTEGER NOT NULL CHECK(version=1));
INSERT INTO metadata VALUES (1);
CREATE TABLE accounts (
 id TEXT PRIMARY KEY,
 username TEXT NOT NULL UNIQUE,
 hash TEXT NOT NULL CHECK(length(hash)>0),
 role TEXT NOT NULL CHECK(role IN ('admin','parent','student')),
 parent_id TEXT REFERENCES accounts(id) ON DELETE RESTRICT,
 created_at TEXT NOT NULL,
 disabled INTEGER NOT NULL DEFAULT 0 CHECK(disabled IN (0,1)),
 avatar TEXT NOT NULL DEFAULT '',
 CHECK((role='student' AND parent_id IS NOT NULL) OR
       (role!='student' AND parent_id IS NULL)),
 CHECK(parent_id IS NULL OR parent_id!=id),
 CHECK(role!='admin' OR disabled=0)
);
CREATE UNIQUE INDEX sole_admin ON accounts(role) WHERE role='admin';
CREATE INDEX children_by_parent ON accounts(parent_id);
CREATE TRIGGER family_capacity_insert BEFORE INSERT ON accounts
 WHEN NEW.role='student' AND (SELECT count(*) FROM accounts WHERE parent_id=NEW.parent_id)>={MAX_STUDENTS_PER_PARENT}
 BEGIN SELECT RAISE(ABORT, 'a parent may have at most five student accounts'); END;
CREATE TRIGGER family_capacity_update BEFORE UPDATE OF parent_id,role ON accounts
 WHEN NEW.role='student' AND (SELECT count(*) FROM accounts WHERE parent_id=NEW.parent_id AND id!=OLD.id)>={MAX_STUDENTS_PER_PARENT}
 BEGIN SELECT RAISE(ABORT, 'a parent may have at most five student accounts'); END;
CREATE TRIGGER valid_parent_insert BEFORE INSERT ON accounts
 WHEN NEW.role='student' AND NOT EXISTS (
 SELECT 1 FROM accounts WHERE id=NEW.parent_id AND role='parent' AND disabled=0)
 BEGIN SELECT RAISE(ABORT, 'student requires an active parent'); END;
CREATE TRIGGER valid_parent_update BEFORE UPDATE OF parent_id,role ON accounts
 WHEN NEW.role='student' AND NOT EXISTS (
 SELECT 1 FROM accounts WHERE id=NEW.parent_id AND role='parent' AND disabled=0)
 BEGIN SELECT RAISE(ABORT, 'student requires an active parent'); END;
CREATE TRIGGER retain_parent_role BEFORE UPDATE OF role ON accounts
 WHEN NEW.role!='parent' AND EXISTS (SELECT 1 FROM accounts WHERE parent_id=OLD.id)
 BEGIN SELECT RAISE(ABORT, 'parent has linked students'); END;
CREATE TRIGGER retain_admin BEFORE DELETE ON accounts WHEN OLD.role='admin'
 BEGIN SELECT RAISE(ABORT, 'the administrator cannot be removed'); END;
CREATE TRIGGER retain_admin_role BEFORE UPDATE OF role ON accounts
 WHEN OLD.role='admin' AND NEW.role!='admin'
 BEGIN SELECT RAISE(ABORT, 'the administrator role is fixed'); END;
CREATE TABLE teaching_grants (user_id TEXT PRIMARY KEY REFERENCES accounts(id), grant_json TEXT NOT NULL, updated_by TEXT NOT NULL);
CREATE TABLE material_scopes (owner_id TEXT NOT NULL REFERENCES accounts(id), name TEXT NOT NULL, students_json TEXT, shared INTEGER NOT NULL DEFAULT 0 CHECK(shared IN (0,1)), PRIMARY KEY(owner_id,name));
CREATE TABLE appearance (user_id TEXT PRIMARY KEY REFERENCES accounts(id), preferences TEXT NOT NULL);
CREATE TABLE teaching_policy (id INTEGER PRIMARY KEY CHECK(id=1), config TEXT NOT NULL, revision INTEGER NOT NULL);
CREATE TABLE learning_goals (student_id TEXT PRIMARY KEY REFERENCES accounts(id), goal TEXT NOT NULL, updated_at TEXT NOT NULL, actor_id TEXT NOT NULL);
CREATE TABLE identity_events (
 id INTEGER PRIMARY KEY, occurred_at TEXT NOT NULL, actor_id TEXT NOT NULL,
 subject_id TEXT NOT NULL, action TEXT NOT NULL, details TEXT NOT NULL
);
"""


def database_path() -> Path:
    from .identity import AUTH_DIR
    return AUTH_DIR / "teaching.sqlite3"


def active() -> bool:
    # A symlink/directory/broken file still signals activation and fails closed
    # when opened. Do not resurrect old credentials because a file is damaged.
    return os.path.lexists(database_path()) or database_path().with_suffix(".enabled").exists()


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


@contextmanager
def connect(*, write: bool = False) -> Iterator[sqlite3.Connection]:
    path = database_path()
    if path.is_symlink() or not path.is_file():
        raise RuntimeError("Teaching identity database is unavailable")
    conn = sqlite3.connect(path.as_uri() + "?mode=rw", uri=True, timeout=10)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA foreign_keys=ON")
        versions = [r[0] for r in conn.execute("SELECT version FROM metadata")]
        if versions != [1]:
            raise RuntimeError("Unsupported teaching identity schema")
        if write:
            conn.execute("BEGIN IMMEDIATE")
        if conn.execute("SELECT count(*) FROM accounts WHERE role='admin' AND disabled=0").fetchone()[0] != 1:
            raise RuntimeError("Teaching identity requires exactly one active administrator")
        yield conn
        if write:
            conn.commit()
    except sqlite3.IntegrityError as exc:
        conn.rollback()
        raise ValueError(str(exc)) from exc
    finally:
        conn.close()


def load_users() -> dict[str, dict[str, Any]]:
    with connect() as conn:
        result = {}
        for row in conn.execute("SELECT * FROM accounts ORDER BY created_at,id"):
            record = dict(row)
            username = record.pop("username")
            record["disabled"] = bool(record["disabled"])
            result[username] = record
        return result


def get_account(value: str, *, by_id: bool = False):
    column = "id" if by_id else "username"
    with connect() as conn:
        row = conn.execute(f"SELECT * FROM accounts WHERE {column}=?",(value,)).fetchone()
    if row is None:
        return None
    record=dict(row)
    username=record.pop("username")
    record["disabled"]=bool(record["disabled"])
    return username,record


def _event(conn, actor_id: str, subject_id: str, action: str, details: dict) -> None:
    conn.execute("INSERT INTO identity_events(occurred_at,actor_id,subject_id,action,details) VALUES(?,?,?,?,?)",
                 (now(), actor_id, subject_id, action, json.dumps(details, sort_keys=True)))


def create_user(username: str, hashed_password: str, role: str, parent_id: str | None = None,
                *, actor_id: str = "system") -> dict[str, Any]:
    if role not in {"parent", "student"}:
        raise ValueError("New teaching accounts must be parent or student")
    uid = "u_" + uuid4().hex
    with connect(write=True) as conn:
        conn.execute("INSERT INTO accounts(id,username,hash,role,parent_id,created_at) VALUES(?,?,?,?,?,?)",
                     (uid, username, hashed_password, role, parent_id, now()))
        _event(conn, actor_id, uid, "created", {"role": role, "parent_id": parent_id})
    return load_users()[username]


def update_user(username: str, *, role: str, parent_id: str | None,
                disabled: bool = False, actor_id: str = "system") -> bool:
    with connect(write=True) as conn:
        old = conn.execute("SELECT * FROM accounts WHERE username=?", (username,)).fetchone()
        if old is None:
            return False
        conn.execute("UPDATE accounts SET role=?,parent_id=?,disabled=? WHERE id=?",
                     (role, parent_id, int(disabled), old["id"]))
        _event(conn, actor_id, old["id"], "updated", {
            "before": {k: old[k] for k in ("role", "parent_id", "disabled")},
            "after": {"role": role, "parent_id": parent_id, "disabled": disabled}})
    return True


def set_avatar(username: str, avatar: str) -> bool:
    with connect(write=True) as conn:
        return conn.execute("UPDATE accounts SET avatar=? WHERE username=?", (avatar, username)).rowcount == 1


def visible_students(user_id: str, *, write: bool = False) -> set[str]:
    """Authoritative scope; parents/admin never submit a student's answer."""
    with connect() as conn:
        actor = conn.execute("SELECT * FROM accounts WHERE id=? AND disabled=0", (user_id,)).fetchone()
        if actor is None:
            return set()
        if actor["role"] == "student":
            return {user_id}
        if write:
            return set()
        if actor["role"] == "admin":
            return {r[0] for r in conn.execute("SELECT id FROM accounts WHERE role='student'")}
        return {r[0] for r in conn.execute("SELECT id FROM accounts WHERE parent_id=?", (user_id,))}


def migration_records(users: dict, assignments: dict) -> list[dict]:
    if not users or set(users) != set(assignments):
        raise ValueError("Every source account requires exactly one explicit role assignment")
    result = []
    ids = set()
    for username, old in users.items():
        if not isinstance(old, dict) or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", str(old.get("id", ""))):
            raise ValueError("Source accounts require stable safe IDs")
        if old["id"] in ids:
            raise ValueError("Duplicate source account ID")
        ids.add(old["id"])
        spec = assignments[username]
        role = spec.get("role")
        parent = spec.get("parent_username")
        if role not in {"admin", "parent", "student"}:
            raise ValueError("Assign admin, parent, or student explicitly")
        if role == "student":
            if parent not in users or assignments[parent].get("role") != "parent" or users[parent].get("disabled"):
                raise ValueError("Every student requires an active mapped parent")
        elif parent is not None:
            raise ValueError("Only students may have a parent")
        if not old.get("hash"):
            raise ValueError("Source account has no password hash")
        result.append(dict(id=old["id"], username=username, hash=old["hash"], role=role,
                           parent_id=users[parent]["id"] if parent else None,
                           created_at=old.get("created_at") or now(), disabled=int(bool(old.get("disabled"))),
                           avatar=old.get("avatar") or ""))
    admins = [r for r in result if r["role"] == "admin"]
    if len(admins) != 1 or admins[0]["disabled"]:
        raise ValueError("Exactly one active administrator is required")
    for parent in (r for r in result if r["role"] == "parent"):
        if sum(r["parent_id"] == parent["id"] for r in result) > MAX_STUDENTS_PER_PARENT:
            raise ValueError("A parent may have at most five student accounts")
    return sorted(result, key=lambda r: r["role"] == "student")


def migrate(users: dict, assignments: dict, *, apply: bool = False, target: Path | None = None) -> dict:
    records = migration_records(users, assignments)
    destination = target or database_path()
    if os.path.lexists(destination):
        raise ValueError("Teaching identity already exists; refusing overwrite")
    report = {"accounts": len(records), "roles": {role: sum(r["role"] == role for r in records)
              for role in ("admin", "parent", "student")}, "applied": False}
    if not apply:
        return report
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(destination.name + ".prepared-" + uuid4().hex)
    fd = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    os.close(fd)
    conn = sqlite3.connect(temporary)
    try:
        conn.execute("PRAGMA foreign_keys=ON")
        conn.executescript(SCHEMA)
        with conn:
            conn.executemany("INSERT INTO accounts(id,username,hash,role,parent_id,created_at,disabled,avatar) "
                             "VALUES(:id,:username,:hash,:role,:parent_id,:created_at,:disabled,:avatar)", records)
            _event(conn, "migration", "all", "migrated", report)
        if conn.execute("PRAGMA integrity_check").fetchone()[0] != "ok" or conn.execute("PRAGMA foreign_key_check").fetchall():
            raise RuntimeError("Prepared identity database failed integrity checks")
    finally:
        conn.close()
    with temporary.open("rb") as stream:
        os.fsync(stream.fileno())
    # Atomic create, unlike replace(): a concurrent activation cannot overwrite.
    os.link(temporary, destination)
    destination.with_suffix(".enabled").write_text("1\n", encoding="utf-8")
    report["applied"] = True
    # This is a hard link used for atomic activation, NOT a backup snapshot.
    report["activation_staging_link"] = str(temporary)
    return report


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Explicit teaching identity migration (dry-run by default)")
    parser.add_argument("--users", required=True, type=Path)
    parser.add_argument("--assignments", required=True, type=Path)
    parser.add_argument("--target", type=Path)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    result = migrate(json.loads(args.users.read_text()), json.loads(args.assignments.read_text()),
                     apply=args.apply, target=args.target)
    print(json.dumps(result, ensure_ascii=False, indent=2))
