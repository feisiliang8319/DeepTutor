"""Parent self-service and administrator recovery without exposing passwords."""
from __future__ import annotations

import hashlib
import hmac
import json

from . import teaching_identity as identities


def password_tag(hashed_password: str, secret: str) -> str:
    # A JWT must never contain the bcrypt hash or a usable password verifier.
    return hmac.new(secret.encode(), hashed_password.encode(), hashlib.sha256).hexdigest()


def token_matches(record, payload, secret):
    tag = payload.get("pwdv")
    if isinstance(tag, str):
        return hmac.compare_digest(tag, password_tag(record["hash"], secret))
    # Existing sessions survive rollout, but not a later password reset.
    with identities.connect() as conn:
        changed = conn.execute(
            "SELECT 1 FROM identity_events WHERE subject_id=? AND action='password_changed' LIMIT 1",
            (record["id"],),
        ).fetchone()
    return changed is None


def must_change_password(user_id):
    with identities.connect() as conn:
        row = conn.execute(
            "SELECT details FROM identity_events WHERE subject_id=? AND action='password_changed' ORDER BY id DESC LIMIT 1",
            (user_id,),
        ).fetchone()
    return bool(row and json.loads(row[0]).get("method") == "admin_initialize")


def enforce_password_change(payload, path, method):
    if not payload.password_change_required:
        return
    allowed = {
        ("/api/v1/auth/profile", "GET"),
        ("/api/v1/teaching/appearance", "GET"),
        ("/api/v1/teaching/appearance", "PATCH"),
        (f"/api/v1/teaching/accounts/{payload.user_id}/password", "PUT"),
        ("/api/v1/auth/logout", "POST"),
    }
    if (path, method) not in allowed:
        from fastapi import HTTPException
        raise HTTPException(403, "Change your initial password before continuing")


def change_password(actor_id, subject_id, new_password, *, current_password=None, initialize=False):
    from deeptutor.services.auth import hash_password, verify_password

    if not 8 <= len(new_password) or len(new_password.encode("utf-8")) > 72:
        raise ValueError("Password must be at least 8 characters and at most 72 UTF-8 bytes")
    with identities.connect(write=True) as conn:
        actor = conn.execute("SELECT * FROM accounts WHERE id=? AND disabled=0", (actor_id,)).fetchone()
        subject = conn.execute("SELECT * FROM accounts WHERE id=?", (subject_id,)).fetchone()
        if not actor or not subject or subject["role"] != "parent":
            raise PermissionError("Only parent account passwords can be managed here")
        own = actor_id == subject_id and actor["role"] == "parent"
        if initialize and actor["role"] != "admin":
            raise PermissionError("Only the administrator may initialize a parent's password")
        if not own and actor["role"] != "admin":
            raise PermissionError("Only the administrator may reset a parent's password")
        if own and (not current_password or not verify_password(current_password, subject["hash"])):
            raise ValueError("The current password is incorrect")
        if own and verify_password(new_password, subject["hash"]):
            raise ValueError("The new password must differ from the current password")
        hashed = hash_password(new_password)
        conn.execute("UPDATE accounts SET hash=? WHERE id=?", (hashed, subject_id))
        identities._event(conn, actor_id, subject_id, "password_changed", {
            "method": "admin_initialize" if initialize else "self" if own else "admin_reset"
        })
