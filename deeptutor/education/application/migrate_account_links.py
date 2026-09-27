"""Explicit legacy username -> stable account ID migration; dry-run by default."""
from __future__ import annotations


def migrate_account_links(conn, users: dict, *, apply: bool = False) -> dict:
    by_id = {record["id"]: record for record in users.values()}
    changes = []
    for row in conn.execute("SELECT id,deep_tutor_user_id FROM learner_profiles"):
        owner = row["deep_tutor_user_id"]
        record = by_id.get(owner) or users.get(owner)
        if record is None:
            raise ValueError("Unmapped learning profile: " + row["id"])
        # Historical parent/admin profiles remain intact as evidence but are
        # never student resources in the teaching authorization resolver.
        if owner != record["id"]:
            changes.append((row["id"], record["id"]))
    if apply:
        from deeptutor.education.storage.sqlite import transaction
        with transaction(conn):
            for profile_id, user_id in changes:
                conn.execute("UPDATE learner_profiles SET deep_tutor_user_id=? WHERE id=?", (user_id, profile_id))
    return {"changed_profiles": len(changes), "applied": apply}
