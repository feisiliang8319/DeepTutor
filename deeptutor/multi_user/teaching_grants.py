"""Delegated access: administrator -> parent -> student, evaluated on every use."""
from __future__ import annotations
import json
from typing import Literal
from pydantic import BaseModel, Field
from fastapi import HTTPException
from . import teaching_identity as identities
from .teaching_policy import ModelChoice
from .identity import get_user_by_id


class Access(BaseModel):
    models: list[ModelChoice] = Field(default_factory=list)
    knowledge_bases: list[str] = Field(default_factory=list)
    features: list[Literal["chat", "quiz", "research", "homework"]] = Field(default_factory=list)


def _load(conn, user_id):
    row=conn.execute("SELECT grant_json FROM teaching_grants WHERE user_id=?",(user_id,)).fetchone()
    return Access.model_validate_json(row[0]) if row else None


def effective(user_id: str) -> Access:
    with identities.connect() as conn:
        account=conn.execute("SELECT * FROM accounts WHERE id=? AND disabled=0",(user_id,)).fetchone()
        if account is None:
            return Access()
        own=_load(conn,user_id)
        if account["role"] == "parent":
            return own or Access()
        if account["role"] != "student":
            return Access()
        parent=conn.execute("SELECT * FROM accounts WHERE id=? AND role='parent' AND disabled=0",(account["parent_id"],)).fetchone()
        if parent is None:
            return Access()
        ceiling=_load(conn,parent["id"]) or Access()
        if own is None:
            return ceiling
        allowed={(m.profile_id,m.model_id) for m in ceiling.models}
        return Access(models=[m for m in own.models if (m.profile_id,m.model_id) in allowed],
                      knowledge_bases=[kb for kb in own.knowledge_bases if kb in ceiling.knowledge_bases],
                      features=[f for f in own.features if f in ceiling.features])


def save(actor_id: str, subject_id: str, grant: Access) -> Access:
    actor=get_user_by_id(actor_id);subject=get_user_by_id(subject_id)
    if not actor or not subject or actor[1].get("disabled"):
        raise HTTPException(403,"Account unavailable")
    a=actor[1];s=subject[1]
    if a["role"] == "admin":
        if s["role"] != "parent":
            raise HTTPException(403,"Administrators allocate access to parents, never directly to students")
        from .model_access import admin_catalog,_profile_by_id,_model_by_id,is_owner_bound
        catalog=admin_catalog()
        for model in grant.models:
            profile=_profile_by_id(catalog,"llm",model.profile_id)
            if not profile or is_owner_bound(profile) or not _model_by_id(profile,model.model_id):
                raise HTTPException(400,"Model is not an available shared resource")
        from .knowledge_access import admin_kb_manager
        names=set(admin_kb_manager().list_knowledge_bases())
        with identities.connect() as conn:
            shared={f"family:{r[0]}:kb:{r[1]}" for r in conn.execute("SELECT owner_id,name FROM material_scopes WHERE shared=1")}
        valid={"admin:kb:"+name for name in names}|shared
        if not set(grant.knowledge_bases)<=valid:
            raise HTTPException(400,"Knowledge resource is not in the main catalog")
    elif a["role"] == "parent" and s["role"] == "student" and s["parent_id"] == a["id"]:
        ceiling=effective(actor_id)
        allowed={(m.profile_id,m.model_id) for m in ceiling.models}
        if (any((m.profile_id,m.model_id) not in allowed for m in grant.models)
                or not set(grant.knowledge_bases)<=set(ceiling.knowledge_bases)
                or not set(grant.features)<=set(ceiling.features)):
            raise HTTPException(403,"A parent cannot allocate more access than they were granted")
    else:
        raise HTTPException(403,"Only the linked parent manages a student's access")
    with identities.connect(write=True) as conn:
        conn.execute("INSERT INTO teaching_grants VALUES(?,?,?) ON CONFLICT(user_id) DO UPDATE SET grant_json=excluded.grant_json,updated_by=excluded.updated_by",
                     (subject_id,grant.model_dump_json(),actor_id))
        identities._event(conn,actor_id,subject_id,"access_updated",grant.model_dump())
    return effective(subject_id)


def legacy_view(user_id: str) -> dict:
    access=effective(user_id)
    profiles={}
    for model in access.models:
        profiles.setdefault(model.profile_id,[]).append(model.model_id)
    tools=["reason"] if "chat" in access.features else []
    if "research" in access.features: tools.extend(["web_search","paper_search"])
    return {"version":2,"user_id":user_id,"models":{"llm":[{"profile_id":p,"model_ids":m} for p,m in profiles.items()]},
            "knowledge_bases":[{"resource_id":ref} for ref in access.knowledge_bases],"enabled_tools":tools,
            "skills":[],"partners":[],"mcp_tools":[],"cli_apps":[],"exec_enabled":False}
