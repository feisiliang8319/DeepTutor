"""Authorized family resource catalog. Filter ownership before retrieval."""
import json
from fastapi import HTTPException
from . import teaching_identity as identities
from .identity import get_user_by_id, load_users
from .context import get_current_user
from .models import KnowledgeResource
from .paths import scope_for_user, get_path_service_for_scope

PREFIX = "family:"


def _base(owner_id):
    return get_path_service_for_scope(scope_for_user(owner_id, is_admin=False)).get_knowledge_bases_root()


def _visible(owner_id, name, actor, scopes):
    if actor.is_admin or actor.id == owner_id:
        return True
    row = scopes.get((owner_id, name))
    if row and row["shared"]:
        from .teaching_grants import effective
        if f"family:{owner_id}:kb:{name}" in effective(actor.id).knowledge_bases:
            return True
    record = get_user_by_id(actor.id)
    if not record or record[1].get("parent_id") != owner_id:
        return False
    return not row or row["students_json"] is None or actor.id in json.loads(row["students_json"])


def catalog():
    from .knowledge_access import _manager_for
    actor = get_current_user()
    with identities.connect() as conn:
        scopes = {(row["owner_id"],row["name"]):dict(row) for row in conn.execute("SELECT * FROM material_scopes")}
    result=[]
    for username, record in load_users().items():
        if record["role"] != "parent":
            continue
        owner_id=record["id"]
        current = get_user_by_id(actor.id)
        owns_family = actor.id == owner_id or (current and current[1].get("parent_id") == owner_id)
        shared_names = {name for (owner,name),scope in scopes.items() if owner == owner_id and scope["shared"]}
        if not actor.is_admin and not owns_family and not shared_names:
            continue
        for name in _manager_for(str(_base(owner_id).resolve())).list_knowledge_bases():
            if _visible(owner_id,name,actor,scopes):
                result.append({"id":f"family:{owner_id}:kb:{name}","name":name,"source":"family",
                    "owner_id":owner_id,"owner_name":username if actor.is_admin or actor.id == owner_id else "","read_only":actor.id!=owner_id,"available":True,
                    "provenance_label":"Family material", "shared":bool(scopes.get((owner_id,name),{}).get("shared")),
                    **({"students":json.loads(scopes[(owner_id,name)]["students_json"]) if scopes.get((owner_id,name),{}).get("students_json") is not None else None} if actor.id == owner_id else {})})
    return result


def resolve(reference: str, *, require_write=False):
    actor=get_current_user()
    for item in catalog():
        if item["id"] != reference:
            continue
        if require_write and actor.id != item["owner_id"]:
            raise HTTPException(403,"Family source files can only be changed by their owner")
        return KnowledgeResource(id=reference,name=item["name"],base_dir=_base(item["owner_id"]),
            source="family",assigned=True,read_only=actor.id!=item["owner_id"],metadata={"owner_id":item["owner_id"]})
    raise HTTPException(403,"This family material is not visible to your account")


def set_scope(owner_id: str, name: str, students: list[str] | None, shared: bool, *, update_students: bool = True):
    actor=get_current_user()
    if not actor.is_admin and actor.id != owner_id:
        raise HTTPException(403,"Only the material owner or administrator may change visibility")
    with identities.connect(write=True) as conn:
        old=conn.execute("SELECT shared,students_json FROM material_scopes WHERE owner_id=? AND name=?",(owner_id,name)).fetchone()
        previous_students = json.loads(old[1]) if old and old[1] is not None else None
        if actor.is_admin and update_students and students != previous_students:
            raise HTTPException(403,"Only the linked parent selects students for family materials")
        if not update_students:
            students = previous_students
        if not actor.is_admin and shared != bool(old[0] if old else False):
            raise HTTPException(403,"Only the administrator may promote a family resource to the shared catalog")
        valid={row[0] for row in conn.execute("SELECT id FROM accounts WHERE parent_id=?",(owner_id,))}
        if students is not None and not set(students)<=valid:
            raise HTTPException(400,"Selected students must belong to the material owner's family")
        # Resolve existence under the owner's path, never a client-supplied path.
        from .knowledge_access import _manager_for
        if name not in _manager_for(str(_base(owner_id).resolve())).list_knowledge_bases():
            raise HTTPException(404,"Family resource not found")
        conn.execute("INSERT INTO material_scopes VALUES(?,?,?,?) ON CONFLICT(owner_id,name) DO UPDATE SET students_json=excluded.students_json,shared=excluded.shared",
                     (owner_id,name,None if students is None else json.dumps(students),int(shared)))
        identities._event(conn,actor.id,owner_id,"material_visibility",{"name":name,"students":students,"shared":shared})
