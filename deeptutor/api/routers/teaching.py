"""Small teaching administration surface; all ownership is resolved server-side."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from deeptutor.api.routers.auth import require_auth, require_admin
from deeptutor.services.auth import TokenPayload
from deeptutor.multi_user import teaching_identity as identities, teaching_policy
from deeptutor.multi_user.identity import list_user_info, get_user_by_id

router = APIRouter()


def require_teaching(payload: TokenPayload = Depends(require_auth)) -> TokenPayload:
    if not identities.active():
        raise HTTPException(409, "Teaching identity migration is required")
    return payload


class PolicyUpdate(BaseModel):
    policy: teaching_policy.TeachingPolicy
    revision: int = Field(ge=0)


class GoalUpdate(BaseModel):
    goal: str = Field(max_length=4000)


from pydantic import SecretStr, field_validator


class PasswordChange(BaseModel):
    new_password: SecretStr
    current_password: SecretStr | None = None

    @field_validator("new_password")
    @classmethod
    def valid_password(cls, value):
        text = value.get_secret_value()
        if len(text) < 8 or len(text.encode("utf-8")) > 72:
            raise ValueError("Password must be at least 8 characters and at most 72 UTF-8 bytes")
        return value


@router.put("/accounts/{user_id}/password")
def change_account_password(user_id: str, body: PasswordChange, actor: TokenPayload = Depends(require_teaching)):
    from deeptutor.multi_user.teaching_passwords import change_password
    try:
        change_password(actor.user_id, user_id, body.new_password.get_secret_value(),
                        current_password=body.current_password.get_secret_value() if body.current_password else None)
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"ok": True, "sign_in_required": actor.user_id == user_id}


@router.post("/accounts/{user_id}/initialize-password")
def initialize_account_password(user_id: str, actor: TokenPayload = Depends(require_teaching)):
    from deeptutor.multi_user.teaching_passwords import change_password
    try:
        change_password(actor.user_id, user_id, "12345678", initialize=True)
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    return {"ok": True, "password_change_required": True}


@router.get("/policy")
def get_policy(_: TokenPayload = Depends(require_admin)):
    if not identities.active():
        raise HTTPException(409, "Teaching identity migration is required")
    policy, revision = teaching_policy.read()
    return {"policy":policy.model_dump(), "revision":revision,
            "ownership":{"policy":"administrator", "learning_goals":"linked parent", "student_overrides":False},
            "configured":policy.teacher_model is not None}


@router.put("/policy")
def put_policy(body: PolicyUpdate, actor: TokenPayload = Depends(require_admin)):
    if not identities.active():
        raise HTTPException(409, "Teaching identity migration is required")
    try:
        revision = teaching_policy.save(body.policy, body.revision, actor.user_id)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return {"revision":revision, "policy":body.policy.model_dump()}


@router.get("/students")
def students(actor: TokenPayload = Depends(require_teaching)):
    allowed = identities.visible_students(actor.user_id)
    with identities.connect() as conn:
        goals = {row[0]: row[1] for row in conn.execute("SELECT student_id,goal FROM learning_goals") if row[0] in allowed}
    return {"students":[{**user,"goal":goals.get(user["id"], "")} for user in list_user_info() if user["id"] in allowed],
            "capacity": {"limit": identities.MAX_STUDENTS_PER_PARENT, "used":len(allowed)} if actor.role == "parent" else None}


@router.put("/students/{student_id}/goal")
def set_goal(student_id: str, body: GoalUpdate, actor: TokenPayload = Depends(require_teaching)):
    if actor.role != "parent" or student_id not in identities.visible_students(actor.user_id):
        raise HTTPException(403, "Only the linked parent may set this learning goal")
    with identities.connect(write=True) as conn:
        conn.execute("INSERT INTO learning_goals VALUES(?,?,?,?) ON CONFLICT(student_id) DO UPDATE SET goal=excluded.goal,updated_at=excluded.updated_at,actor_id=excluded.actor_id",
                     (student_id,body.goal,identities.now(),actor.user_id))
        identities._event(conn, actor.user_id, student_id, "goal_updated", {})
    return {"student_id":student_id,"goal":body.goal}


@router.get("/material-policy")
def material_policy(actor: TokenPayload = Depends(require_teaching)):
    if actor.role not in {"parent", "admin"}:
        raise HTTPException(403, "Materials are managed by a parent or administrator")
    return {"engine":teaching_policy.material_index_provider(),"visibility":"family","retrieval":"automatic"}


from typing import Literal


class Appearance(BaseModel):
    scene: Literal["grove", "tide", "apricot"] = "grove"
    nickname: str = Field(default="", max_length=24)
    text_size: Literal["comfortable", "large"] = "comfortable"
    motion: bool = True
    companion: bool = True
    language: Literal["en", "zh", "zh-Hant"] = "en"


@router.get("/appearance")
def get_appearance(actor: TokenPayload = Depends(require_teaching)):
    with identities.connect() as conn:
        row = conn.execute("SELECT preferences FROM appearance WHERE user_id=?", (actor.user_id,)).fetchone()
    return Appearance.model_validate_json(row[0]) if row else Appearance()


@router.put("/appearance")
def put_appearance(body: Appearance, actor: TokenPayload = Depends(require_teaching)):
    with identities.connect(write=True) as conn:
        conn.execute("INSERT INTO appearance VALUES(?,?) ON CONFLICT(user_id) DO UPDATE SET preferences=excluded.preferences",
                     (actor.user_id, body.model_dump_json()))
    return body


class AppearanceLanguage(BaseModel):
    language: Literal["en", "zh", "zh-Hant"]


@router.patch("/appearance")
def set_appearance_language(body: AppearanceLanguage, actor: TokenPayload = Depends(require_teaching)):
    # Update only the language, preserving appearance saved by another tab.
    with identities.connect(write=True) as conn:
        row = conn.execute("SELECT preferences FROM appearance WHERE user_id=?", (actor.user_id,)).fetchone()
        current = Appearance.model_validate_json(row[0]) if row else Appearance()
        saved = current.model_copy(update={"language": body.language})
        conn.execute("INSERT INTO appearance VALUES(?,?) ON CONFLICT(user_id) DO UPDATE SET preferences=excluded.preferences",
                     (actor.user_id, saved.model_dump_json()))
    return saved


class MaterialScope(BaseModel):
    students: list[str] | None = None
    shared: bool = False


@router.get("/materials")
def materials(_: TokenPayload = Depends(require_teaching)):
    from deeptutor.multi_user.teaching_materials import catalog
    return {"materials":catalog()}


@router.put("/materials/{owner_id}/{name}/scope")
def material_scope(owner_id: str, name: str, body: MaterialScope, _: TokenPayload = Depends(require_teaching)):
    from deeptutor.multi_user.teaching_materials import set_scope
    set_scope(owner_id,name,body.students,body.shared,update_students="students" in body.model_fields_set)
    return {"ok":True}


from deeptutor.multi_user.teaching_grants import Access, effective, save as save_access


@router.get("/access/{user_id}")
def get_access(user_id: str, actor: TokenPayload = Depends(require_teaching)):
    target=get_user_by_id(user_id)
    if not target or not (actor.role == "admin" or actor.user_id == user_id or
                          actor.role == "parent" and target[1].get("parent_id") == actor.user_id):
        raise HTTPException(403,"Account access is private")
    return effective(user_id)


@router.put("/access/{user_id}")
def put_access(user_id: str, body: Access, actor: TokenPayload = Depends(require_teaching)):
    return save_access(actor.user_id,user_id,body)


@router.get("/catalog")
def resource_catalog(actor: TokenPayload = Depends(require_teaching)):
    if actor.role not in {"admin","parent"}:
        raise HTTPException(403,"Resource allocation belongs to parents and the administrator")
    from deeptutor.multi_user.model_access import admin_catalog
    from deeptutor.multi_user.knowledge_access import admin_kb_manager
    ceiling=effective(actor.user_id)
    allowed={(m.profile_id,m.model_id) for m in ceiling.models}
    choices, route = teaching_policy.teaching_model_options(admin_catalog(), teaching_policy.read()[0])
    teaching_models = choices if actor.role == "admin" else []
    models = [m for m in route if actor.role == "admin" or (m["profile_id"],m["model_id"]) in allowed]
    knowledge=[{"id":"admin:kb:"+name,"label":name} for name in admin_kb_manager().list_knowledge_bases()
               if actor.role == "admin" or "admin:kb:"+name in ceiling.knowledge_bases]
    with identities.connect() as conn:
        for row in conn.execute("SELECT owner_id,name FROM material_scopes WHERE shared=1"):
            ref=f"family:{row[0]}:kb:{row[1]}"
            if actor.role == "admin" or ref in ceiling.knowledge_bases:
                knowledge.append({"id":ref,"label":row[1]})
    return {"models":models,"teaching_models":teaching_models,"knowledge_bases":knowledge,"features":["chat","quiz","research","homework"] if actor.role == "admin" else ceiling.features}


@router.get("/students/{student_id}/evidence")
def student_evidence(student_id: str, actor: TokenPayload = Depends(require_teaching)):
    if student_id not in identities.visible_students(actor.user_id):
        raise HTTPException(403,"Learning evidence is private to the linked family")
    from deeptutor.multi_user import teaching_evidence
    try:
        return teaching_evidence.read(student_id,include_private=actor.role in {"parent","admin"})
    except (RuntimeError, OSError) as exc:
        raise HTTPException(503,str(exc)) from exc


# Admin-only connection setup. Does not submit main/family/student material.
from deeptutor.api.routers import material_intelligence
router.include_router(material_intelligence.router, prefix="/intelligence")
