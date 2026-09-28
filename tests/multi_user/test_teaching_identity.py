"""Account migration, database invariants and current-authority regressions."""
from concurrent.futures import ThreadPoolExecutor
import sqlite3

import pytest

from deeptutor.multi_user import identity, teaching_identity as store


@pytest.fixture
def teaching(mu_isolated_root):
    users = {name: dict(id="u_" + name, hash="hash-" + name, role="user",
                       created_at="2026-09-27", disabled=False)
             for name in ("admin", "parent_a", "parent_b", "student_a", "student_b")}
    assignments = {name: {"role": "admin" if name == "admin" else
                         "parent" if name.startswith("parent") else "student"}
                   for name in users}
    assignments["student_a"]["parent_username"] = "parent_a"
    assignments["student_b"]["parent_username"] = "parent_b"
    identity.USERS_FILE.parent.mkdir(parents=True, exist_ok=True)
    identity.USERS_FILE.write_text("{}")
    return users, assignments


def activate(teaching):
    users, assignments = teaching
    store.migrate(users, assignments, apply=True)


def test_migration_dry_run_and_preserves_identity(teaching):
    users, assignments = teaching
    report = store.migrate(users, assignments)
    assert report["roles"] == {"admin": 1, "parent": 2, "student": 2}
    assert not store.active()
    assert not store.database_path().exists()
    activate(teaching)
    loaded = identity.load_users()
    assert loaded["student_a"]["id"] == "u_student_a"
    assert loaded["student_a"]["hash"] == "hash-student_a"
    assert loaded["student_a"]["parent_id"] == "u_parent_a"
    assert identity.USERS_FILE.read_text() == "{}"
    with pytest.raises(ValueError, match="overwrite"):
        activate(teaching)


@pytest.mark.parametrize("mutation", ["orphan", "two_admins", "no_admin", "missing", "disabled_parent", "duplicate_id"])
def test_migration_rejects_invalid_assignments_without_activation(teaching, mutation):
    users, assignments = teaching
    if mutation == "orphan": assignments["student_a"]["parent_username"] = "missing"
    if mutation == "two_admins": assignments["student_a"] = {"role": "admin"}
    if mutation == "no_admin": assignments["admin"] = {"role": "parent"}
    if mutation == "missing": assignments.pop("student_b")
    if mutation == "disabled_parent": users["parent_a"]["disabled"] = True
    if mutation == "duplicate_id": users["student_a"]["id"] = "u_admin"
    with pytest.raises(ValueError): store.migrate(users, assignments, apply=True)
    assert not store.active()


def test_store_prevents_second_admin_or_orphan_even_with_direct_sql(teaching):
    activate(teaching)
    with pytest.raises(ValueError):
        with store.connect(write=True) as conn:
            conn.execute("INSERT INTO accounts(id,username,hash,role,created_at) VALUES('other','other','hash','admin','now')")
    with pytest.raises(ValueError):
        store.create_user("orphan", "hash", "student")
    with pytest.raises(ValueError):
        store.create_user("wrong-parent", "hash", "student", "u_student_b")
    with pytest.raises(ValueError):
        store.update_user("admin", role="parent", parent_id=None)
    with pytest.raises(ValueError):
        store.update_user("admin", role="admin", parent_id=None, disabled=True)
    with pytest.raises(ValueError):
        store.update_user("parent_a", role="student", parent_id="u_parent_b")
    with pytest.raises(ValueError):
        with store.connect(write=True) as conn:
            conn.execute("DELETE FROM accounts WHERE id='u_parent_a'")


def test_family_scope_and_no_parent_submission(teaching):
    activate(teaching)
    assert store.visible_students("u_parent_a") == {"u_student_a"}
    assert store.visible_students("u_parent_b") == {"u_student_b"}
    assert store.visible_students("u_student_a") == {"u_student_a"}
    assert store.visible_students("u_admin") == {"u_student_a", "u_student_b"}
    assert store.visible_students("u_parent_a", write=True) == set()
    assert store.visible_students("u_admin", write=True) == set()
    assert store.visible_students("unknown") == set()
    store.update_user("student_a", role="student", parent_id="u_parent_b", actor_id="u_admin")
    assert store.visible_students("u_parent_a") == set()
    assert store.visible_students("u_parent_b") == {"u_student_a", "u_student_b"}


def test_duplicate_concurrent_create_never_replaces_password(teaching):
    activate(teaching)
    def create(_):
        try:
            store.create_user("new_parent", "original-hash", "parent")
            return True
        except ValueError:
            return False
    with ThreadPoolExecutor(max_workers=4) as pool:
        assert sum(pool.map(create, range(4))) == 1
    assert identity.load_users()["new_parent"]["hash"] == "original-hash"


def test_broken_store_does_not_fall_back_to_json(teaching):
    activate(teaching)
    store.database_path().write_bytes(b"damaged")
    with pytest.raises(sqlite3.DatabaseError): identity.load_users()


def test_missing_activated_database_does_not_resurrect_legacy(teaching):
    activate(teaching)
    store.database_path().rename(store.database_path().with_suffix(".held"))
    assert store.active()
    with pytest.raises(RuntimeError): identity.load_users()


def test_current_role_and_disable_override_old_jwt(teaching, monkeypatch):
    from deeptutor.services import auth
    activate(teaching)
    monkeypatch.setattr(auth, "POCKETBASE_ENABLED", False)
    monkeypatch.setattr(auth, "AUTH_SECRET", "synthetic-test-secret")
    token = auth.create_token("student_a", "admin", "u_student_a")
    assert auth.decode_token(token).role == "student"
    mismatched = auth.create_token("student_a", "student", "u_student_b")
    assert auth.decode_token(mismatched) is None
    store.update_user("student_a", role="student", parent_id="u_parent_a", disabled=True)
    assert auth.decode_token(token) is None


from deeptutor.education.tests.test_web_loop import web_db, CV, LEARNER


@pytest.fixture
def family_client(teaching, web_db, monkeypatch):
    from fastapi.testclient import TestClient
    from deeptutor.education.api.app import create_app
    from deeptutor.education.api.account_identity import NativeAccountAccess
    from deeptutor.education.storage import sqlite as edu
    from deeptutor.services import auth
    activate(teaching)
    monkeypatch.setattr(auth, "AUTH_SECRET", "synthetic-family-key")
    monkeypatch.setattr(auth, "AUTH_ENABLED", True)
    monkeypatch.setattr(auth, "POCKETBASE_ENABLED", False)
    conn = edu.open_database(web_db)
    conn.execute("UPDATE learner_profiles SET deep_tutor_user_id='u_student_a' WHERE id=?", (LEARNER,))
    conn.close()
    client = TestClient(create_app(web_db, content_mode="trial", account_access=NativeAccountAccess()))
    def headers(name):
        return {"Authorization": "Bearer " + auth.create_token(name, "admin", "u_" + name)}
    return client, headers


def test_education_people_and_progress_are_family_scoped(family_client):
    client, headers = family_client
    for name in ("student_a", "parent_a", "admin"):
        assert [p["id"] for p in client.get("/api/edu/people", headers=headers(name)).json()["people"]] == [LEARNER]
        assert client.get("/api/edu/progress", params={"learner_id":LEARNER,"course_version_id":CV}, headers=headers(name)).status_code == 200
    for name in ("student_b", "parent_b"):
        assert client.get("/api/edu/people", headers=headers(name)).json()["people"] == []
        assert client.get("/api/edu/progress", params={"learner_id":LEARNER,"course_version_id":CV}, headers=headers(name)).status_code == 403


def test_parent_cannot_submit_and_other_family_cannot_review(family_client):
    client, headers = family_client
    for name in ("parent_a", "parent_b", "admin", "student_b"):
        assert client.post("/api/edu/set", params={"learner_id":LEARNER,"course_version_id":CV}, headers=headers(name)).status_code == 403
    response = client.post("/api/edu/review", json={"reviewer":"u_parent_b", "attempt_id":"not-owned", "verdict":"correct"}, headers=headers("parent_b"))
    assert response.status_code == 403
    assert client.get("/api/edu/review-queue", params={"course_version_id":CV}, headers=headers("parent_b")).json()["pending"] == []


def test_retired_endpoints_and_admin_settings_are_not_student_apis(teaching):
    from fastapi import HTTPException
    from deeptutor.multi_user.teaching_access import authorize
    activate(teaching)
    for path in ("/api/v1/settings/models", "/api/v1/memory", "/api/v1/knowledge", "/api/v1/quiz/judge", "/api/v1/sessions/x/quiz-results"):
        with pytest.raises(HTTPException): authorize(path, "POST", "student")
    for role in ("admin", "parent", "student"):
        with pytest.raises(HTTPException): authorize("/api/v1/imports", "POST", role)
    authorize("/api/v1/ws", "WS", "student")
    authorize("/api/v1/knowledge/create", "POST", "parent")



def test_five_student_limit_survives_concurrent_creation(teaching):
    activate(teaching)
    def create(i):
        try:
            store.create_user("child_"+str(i),"hash","student","u_parent_a")
            return True
        except ValueError:
            return False
    with ThreadPoolExecutor(max_workers=8) as pool:
        assert sum(pool.map(create,range(8))) == 4
    assert len(store.visible_students("u_parent_a")) == 5
    with pytest.raises(ValueError, match="five"):
        store.update_user("student_b",role="student",parent_id="u_parent_a")


def test_delegated_access_intersection_and_immediate_revocation(teaching):
    from deeptutor.multi_user.teaching_grants import Access,effective,save
    from fastapi import HTTPException
    activate(teaching)
    parent=Access(models=[{"profile_id":"p","model_id":"teacher"}],knowledge_bases=["admin:kb:math"],features=["chat","quiz"])
    with store.connect(write=True) as conn:
        conn.execute("INSERT INTO teaching_grants VALUES(?,?,?)",("u_parent_a",parent.model_dump_json(),"u_admin"))
    assert effective("u_student_a")==parent
    assert effective("u_student_b")==Access()
    with pytest.raises(HTTPException):
        save("u_parent_a","u_student_b",Access())
    with pytest.raises(HTTPException):
        save("u_admin","u_student_a",parent)
    with pytest.raises(HTTPException):
        save("u_parent_a","u_student_a",Access(features=["research"]))
    save("u_parent_a","u_student_a",Access(models=parent.models,features=["chat"]))
    assert effective("u_student_a").features==["chat"]
    with store.connect(write=True) as conn:
        conn.execute("UPDATE teaching_grants SET grant_json=? WHERE user_id=?",(Access().model_dump_json(),"u_parent_a"))
    assert effective("u_student_a")==Access()


def test_account_management_follows_parent_layer(teaching,monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from deeptutor.api.routers import auth as routes
    from deeptutor.services import auth
    activate(teaching)
    monkeypatch.setattr(auth,"AUTH_SECRET","synthetic-api-secret")
    monkeypatch.setattr(auth,"AUTH_ENABLED",True)
    monkeypatch.setattr(auth,"POCKETBASE_ENABLED",False)
    monkeypatch.setattr(routes,"AUTH_ENABLED",True)
    monkeypatch.setattr(routes,"POCKETBASE_ENABLED",False)
    app=FastAPI();app.include_router(routes.router,prefix="/api/v1/auth")
    client=TestClient(app)
    def headers(name):return {"Authorization":"Bearer "+auth.create_token(name,"admin","u_"+name)}
    payload={"username":"new_child","password":"synthetic-password","role":"student","parent_id":"u_parent_b"}
    assert client.post("/api/v1/auth/users",json=payload,headers=headers("admin")).status_code==403
    created=client.post("/api/v1/auth/users",json=payload,headers=headers("parent_a"))
    assert created.status_code==201
    assert identity.get_user("new_child")["parent_id"]=="u_parent_a"
    update={"role":"student","parent_id":"u_parent_a","disabled":True}
    for actor in ("admin","parent_b","student_a"):
        assert client.put("/api/v1/auth/users/new_child/teaching",json=update,headers=headers(actor)).status_code==403
    assert client.put("/api/v1/auth/users/new_child/teaching",json=update,headers=headers("parent_a")).status_code==200
    for i in range(3):
        response=client.post("/api/v1/auth/users",json={**payload,"username":f"api_child_{i}"},headers=headers("parent_a"))
        assert response.status_code==201
    response=client.post("/api/v1/auth/users",json={**payload,"username":"api_sixth"},headers=headers("parent_a"))
    assert response.status_code==409
    assert "five" in response.json()["detail"]
    assert identity.get_user("api_sixth") is None


def test_disabled_students_still_use_capacity(teaching):
    activate(teaching)
    store.update_user("student_a",role="student",parent_id="u_parent_a",disabled=True)
    for i in range(4): store.create_user(f"more_{i}","hash","student","u_parent_a")
    with pytest.raises(ValueError,match="five"):
        store.create_user("sixth","hash","student","u_parent_a")
    # The unrelated family has its own independent allowance.
    store.create_user("other_family","hash","student","u_parent_b")
    store.update_user("student_a",role="student",parent_id="u_parent_a",disabled=False)
    assert len(store.visible_students("u_parent_a")) == 5


def test_migration_rejects_six_students_before_activation(teaching):
    users,assignments=teaching
    for i in range(5):
        name=f"extra_{i}"
        users[name]={"id":"u_"+name,"hash":"hash","role":"user"}
        assignments[name]={"role":"student","parent_username":"parent_a"}
    with pytest.raises(ValueError,match="five"):
        store.migrate(users,assignments,apply=True)
    assert not store.active()


def test_chat_strategy_is_server_owned_and_pinned(teaching,as_user,monkeypatch):
    from types import SimpleNamespace
    from deeptutor.multi_user import teaching_policy as policy,knowledge_access
    from deeptutor.multi_user.teaching_grants import Access
    activate(teaching)
    settings=policy.TeachingPolicy(teacher_model={"profile_id":"p","model_id":"teacher"},reasoning_model={"profile_id":"p","model_id":"reasoner"},instructions="Original teaching strategy")
    access=Access(models=[settings.teacher_model],features=["chat"])
    with store.connect(write=True) as conn:
        conn.execute("INSERT INTO teaching_policy VALUES(1,?,1)",(settings.model_dump_json(),))
        conn.execute("INSERT INTO teaching_grants VALUES(?,?,?)",("u_parent_a",access.model_dump_json(),"u_admin"))
    from deeptutor.multi_user import model_access
    monkeypatch.setattr(model_access,"admin_catalog",lambda: {"services":{"llm":{"profiles":[{"id":"p","binding":"openai","models":[{'id': 'teacher', 'model': 'teacher'}, {'id': 'reasoner', 'model': 'reasoner'}]}]}}})
    monkeypatch.setattr(knowledge_access,"list_visible_knowledge_bases",lambda: [{"id":"allowed","available":True}])
    with as_user("u_student_a",role="student"):
        payload=policy.prepare_turn({"content":"Explain fractions", "capability":"deep_question", "tools":["exec"], "knowledge_bases":["foreign"], "config":{"persona":"override"}})
        assert payload["capability"]=="chat" and payload["tools"]==["reason"]
        assert payload["knowledge_bases"]==["allowed"] and payload["config"]=={}
        assert policy.choose_model(settings,access,reasoning=True)==settings.teacher_model
        with pytest.raises(RuntimeError,match="Homework"):
            policy.prepare_turn({"attachments":[{"name":"homework"}]})
        context=SimpleNamespace(enabled_tools=payload["tools"],metadata={},memory_context="unverified legacy memory")
        with store.connect(write=True) as conn:
            conn.execute("UPDATE teaching_policy SET config=?,revision=2",(policy.TeachingPolicy(instructions="New strategy").model_dump_json(),))
        token = policy.apply_context(context,payload)
        assert policy.current_turn_policy().instructions == "Original teaching strategy"
        policy.reset_turn_policy(token)
        assert "Original teaching strategy" in context.persona_context
        assert context.metadata["teaching_policy_revision"]==1
        assert "exec" not in context.allowed_builtin_tools and "web_search" not in context.allowed_builtin_tools
        assert context.memory_context==""
        with store.connect(write=True) as conn:
            conn.execute("UPDATE teaching_grants SET grant_json=? WHERE user_id=?",(Access().model_dump_json(),"u_parent_a"))
        with pytest.raises(RuntimeError,match="Chat access"):
            policy.require_student_access()


def test_family_material_visibility_cannot_cross_parent_ceiling(teaching,as_user,monkeypatch):
    from types import SimpleNamespace
    from deeptutor.multi_user import teaching_materials as materials,knowledge_access
    from deeptutor.multi_user.teaching_grants import Access
    from fastapi import HTTPException
    activate(teaching)
    monkeypatch.setattr(knowledge_access,"_manager_for",lambda _: SimpleNamespace(list_knowledge_bases=lambda:["notes"]))
    ref="family:u_parent_a:kb:notes"
    with as_user("u_parent_a",role="parent"):
        materials.set_scope("u_parent_a","notes",["u_student_a"],False)
        with pytest.raises(HTTPException): materials.set_scope("u_parent_a","notes",None,True)
        with pytest.raises(HTTPException): materials.set_scope("u_parent_a","notes",["u_student_b"],False)
    with as_user("u_student_a",role="student"):
        assert materials.resolve(ref).read_only
        with pytest.raises(HTTPException): materials.resolve(ref,require_write=True)
    with as_user("u_student_b",role="student"):
        with pytest.raises(HTTPException): materials.resolve(ref)
    with as_user("u_admin",role="admin"):
        with pytest.raises(HTTPException,match=""):
            materials.set_scope("u_parent_a","notes",[],True)
        materials.set_scope("u_parent_a","notes",None,True,update_students=False)
    with as_user("u_student_b",role="student"):
        with pytest.raises(HTTPException): materials.resolve(ref)
    with store.connect(write=True) as conn:
        conn.execute("INSERT INTO teaching_grants VALUES(?,?,?)",("u_parent_b",Access(knowledge_bases=[ref]).model_dump_json(),"u_admin"))
    with as_user("u_student_b",role="student"):
        assert materials.resolve(ref).read_only
    with store.connect(write=True) as conn:
        conn.execute("UPDATE teaching_grants SET grant_json=? WHERE user_id=?",(Access().model_dump_json(),"u_parent_b"))
    with as_user("u_student_b",role="student"):
        with pytest.raises(HTTPException): materials.resolve(ref)


def test_quiz_explanation_receipt_is_atomic_and_idempotent(tmp_path):
    from deeptutor.services.session.sqlite_store import SQLiteSessionStore
    path=tmp_path/"student-chat.db"
    session=SQLiteSessionStore(db_path=path,migrate_legacy=False)
    def receive(_):return session.receive_quiz_explanation("quiz-1","Saved teaching explanation",{"set_id":"quiz-1","response":"original"})
    with ThreadPoolExecutor(max_workers=6) as pool:
        sessions=list(pool.map(receive,range(6)))
    assert len(set(sessions))==1
    with sqlite3.connect(path) as conn:
        assert conn.execute("SELECT count(*) FROM sessions").fetchone()[0]==1
        assert conn.execute("SELECT count(*) FROM messages").fetchone()[0]==1
        assert 'original' in conn.execute("SELECT metadata_json FROM messages").fetchone()[0]
    other=SQLiteSessionStore(db_path=tmp_path/"other-student.db",migrate_legacy=False)
    assert other.receive_quiz_explanation("quiz-1","Different student",{})==sessions[0]
    with sqlite3.connect(path) as conn:
        assert conn.execute("SELECT content FROM messages").fetchone()[0]=="Saved teaching explanation"


def test_account_language_is_authoritative_and_traditional_is_preserved(teaching,as_user,monkeypatch):
    from deeptutor.multi_user import teaching_policy as policy,knowledge_access
    from deeptutor.multi_user.teaching_grants import Access
    from deeptutor.services.prompt.language import language_directive
    activate(teaching)
    settings=policy.TeachingPolicy(teacher_model={"profile_id":"p","model_id":"m"})
    with store.connect(write=True) as conn:
        conn.execute("INSERT INTO teaching_policy VALUES(1,?,1)",(settings.model_dump_json(),))
        conn.execute("INSERT INTO teaching_grants VALUES(?,?,?)",("u_parent_a",Access(models=[settings.teacher_model],features=["chat"]).model_dump_json(),"u_admin"))
        conn.execute("INSERT INTO appearance VALUES(?,?)",("u_student_a",'{"language":"zh-Hant"}'))
    from deeptutor.multi_user import model_access
    monkeypatch.setattr(model_access,"admin_catalog",lambda: {"services":{"llm":{"profiles":[{"id":"p","binding":"openai","models":[{'id': 'm', 'model': 'm'}]}]}}})
    monkeypatch.setattr(knowledge_access,"list_visible_knowledge_bases",lambda:[])
    with as_user("u_student_a",role="student"):
        assert policy.prepare_turn({"language":"fr","content":"Explain"})["language"]=="zh-Hant"
    assert "繁體中文" in language_directive("zh-Hant")


def test_quiz_handoff_uses_student_scope_and_saved_language(teaching,web_db):
    from deeptutor.education.storage import sqlite as edu_sqlite
    from deeptutor.education.application.quiz_chat import handoff
    from deeptutor.multi_user.paths import get_path_service_for_scope,scope_for_user
    activate(teaching)
    with store.connect(write=True) as conn:
        conn.execute("INSERT INTO appearance VALUES(?,?)",("u_student_a",'{"language":"zh-Hant"}'))
    conn=edu_sqlite.open_database(web_db)
    conn.execute("UPDATE learner_profiles SET deep_tutor_user_id=? WHERE id=?",("u_student_a",LEARNER));conn.commit()
    result={"prompt":"40 + 2?","your_response":"41","is_correct":False,"correct_answer":"42"}
    receipt=handoff(conn,LEARNER,"quiz-language",[result]);conn.close()
    path=get_path_service_for_scope(scope_for_user("u_student_a",is_admin=False)).get_chat_history_db()
    with sqlite3.connect(path) as chat:
        message=chat.execute("SELECT content FROM messages WHERE session_id=?",(receipt["session_id"],)).fetchone()[0]
        assert "講解與訂正" in message and "原始作答" in message and "41" in message
        assert "**參考答案:** 42" in message
    assert not get_path_service_for_scope(scope_for_user("u_student_b",is_admin=False)).get_chat_history_db().exists()


def test_only_linked_parent_allocates_courses_and_creates_learning_profile(family_client):
    from deeptutor.multi_user.teaching_grants import Access
    client,headers=family_client
    with store.connect(write=True) as conn:
        conn.execute("INSERT INTO teaching_grants VALUES(?,?,?)",("u_parent_b",Access(features=["quiz"]).model_dump_json(),"u_admin"))
    path="/api/edu/students/u_student_b/courses"
    for actor in ("admin","parent_a","student_b"):
        assert client.put(path,headers=headers(actor),json={"course_versions":[CV]}).status_code==403
    assert client.put(path,headers=headers("parent_b"),json={"course_versions":["unknown"]}).status_code==400
    saved=client.put(path,headers=headers("parent_b"),json={"course_versions":[CV]})
    assert saved.status_code==200
    learner=saved.json()["learner_id"]
    assert learner=="learner-u_student_b"
    assert client.get("/api/edu/courses",headers=headers("student_b"),params={"learner_id":learner}).json()["courses"][0]["course_version_id"]==CV
    assert client.put(path,headers=headers("parent_b"),json={"course_versions":[]}).status_code==200
    assert client.get("/api/edu/courses",headers=headers("student_b"),params={"learner_id":learner}).json()["courses"]==[]
    # Enrollment withdrawal keeps the learner identity and all previous work.
    assert client.get("/api/edu/people",headers=headers("student_b")).json()["people"][0]["id"]==learner


def test_old_student_owned_libraries_cannot_bypass_family_scope(teaching,as_user,monkeypatch):
    from types import SimpleNamespace
    from fastapi import HTTPException
    from deeptutor.multi_user import knowledge_access as knowledge,teaching_materials
    activate(teaching)
    fake=SimpleNamespace(list_knowledge_bases=lambda:["old-private"])
    monkeypatch.setattr(knowledge,"current_kb_manager",lambda:fake)
    monkeypatch.setattr(knowledge,"admin_kb_manager",lambda:SimpleNamespace(list_knowledge_bases=lambda:[]))
    monkeypatch.setattr(teaching_materials,"catalog",lambda:[])
    with as_user("u_student_a",role="student"):
        assert knowledge.list_visible_knowledge_bases()==[]
        for name in ("old-private","user:kb:old-private","admin:kb:old-private"):
            with pytest.raises(HTTPException): knowledge.resolve_for_rag(name)


def test_language_patch_preserves_saved_appearance(teaching):
    from deeptutor.api.routers.teaching import AppearanceLanguage, set_appearance_language
    from deeptutor.services.auth import TokenPayload
    import json
    activate(teaching)
    with store.connect(write=True) as conn:
        conn.execute("INSERT INTO appearance VALUES(?,?)", ("u_student_a", json.dumps({"scene":"tide","nickname":"小树","text_size":"large","motion":False,"language":"zh"})))
    actor = TokenPayload(username="student_a", role="student", user_id="u_student_a")
    saved = set_appearance_language(AppearanceLanguage(language="zh-Hant"), actor)
    assert saved.language == "zh-Hant"
    assert saved.scene == "tide" and saved.nickname == "小树"
    assert saved.text_size == "large" and saved.motion is False
    with store.connect() as conn:
        stored = json.loads(conn.execute("SELECT preferences FROM appearance WHERE user_id=?", (actor.user_id,)).fetchone()[0])
    assert stored == saved.model_dump()


def test_model_route_falls_back_only_within_family_grant():
    from deeptutor.multi_user.teaching_policy import TeachingPolicy, choose_model
    from deeptutor.multi_user.teaching_grants import Access
    policy = TeachingPolicy(teacher_model={"profile_id":"main","model_id":"teacher"})
    access = Access(models=[{"profile_id":"assigned","model_id":"alternate"}])
    assert choose_model(policy, access) == access.models[0]
    assert choose_model(policy, access, reasoning=True) == access.models[0]
    with pytest.raises(RuntimeError, match="No teaching model"):
        choose_model(policy, Access())


def test_review_appends_chat_and_recovers_delivery_without_regrading(family_client, web_db, monkeypatch):
    import json
    from deeptutor.multi_user.teaching_grants import Access
    from deeptutor.multi_user import teaching_evidence
    from deeptutor.multi_user.paths import get_path_service_for_scope, scope_for_user
    from deeptutor.education.application import quiz_chat
    client, headers = family_client
    with store.connect(write=True) as conn:
        conn.execute("INSERT INTO teaching_grants VALUES(?,?,?)", ("u_parent_a",Access(features=["quiz","chat"]).model_dump_json(),"u_admin"))
    issued = client.post("/api/edu/set", params={"learner_id":LEARNER,"course_version_id":CV}, headers=headers("student_a")).json()
    submission = {"learner_id":LEARNER,"course_version_id":CV,"set_id":issued["set_id"],
                  "answers":[{"item_id":item["id"],"response":"43"} for item in issued["items"]]}
    submitted = client.post("/api/edu/set/submit", json=submission, headers=headers("student_a"))
    assert submitted.status_code == 200, submitted.text
    session_id = submitted.json()["chat_handoff"]["session_id"]
    attempt_id = issued["set_id"] + ":" + issued["items"][0]["id"]
    body = {"reviewer":"u_parent_a","attempt_id":attempt_id,"verdict":"correct","note":"private rubric quote"}
    reviewed = client.post("/api/edu/review", json=body, headers=headers("parent_a"))
    assert reviewed.status_code == 200, reviewed.text
    assert reviewed.json()["chat_handoff"]["session_id"] == session_id
    path = get_path_service_for_scope(scope_for_user("u_student_a",is_admin=False)).get_chat_history_db()
    with sqlite3.connect(path) as chat:
        messages = chat.execute("SELECT content,metadata_json FROM messages WHERE session_id=? ORDER BY id", (session_id,)).fetchall()
    assert len(messages) == 2
    assert "Grading review update" in messages[1][0] and "**Result:** Correct" in messages[1][0]
    assert "private rubric quote" not in json.dumps(messages)
    assert "**Result:** Needs correction" in messages[0][0]
    retry = f"/api/edu/review/{attempt_id}/chat"
    assert client.post(retry,headers=headers("parent_b")).status_code == 403
    assert client.post(retry,headers=headers("student_a")).status_code == 403
    assert client.post(retry,headers=headers("parent_a")).status_code == 200
    with sqlite3.connect(path) as chat:
        assert chat.execute("SELECT count(*) FROM messages").fetchone()[0] == 2
    monkeypatch.setenv("TEACHING_EDUCATION_DB", str(web_db))
    public = teaching_evidence.read("u_student_a")
    private = teaching_evidence.read("u_student_a",include_private=True)
    assert "private rubric quote" not in json.dumps(public)
    assert "private rubric quote" in json.dumps(private)
    assert next(a for a in public["attempts"] if a["id"]==attempt_id)["effective_is_correct"] is True
    real = quiz_chat.handoff_review
    def fail(*args): raise OSError("synthetic delivery failure")
    monkeypatch.setattr(quiz_chat,"handoff_review",fail)
    failed = client.post("/api/edu/review",json={**body,"verdict":"incorrect"},headers=headers("parent_a"))
    assert failed.status_code == 200 and "synthetic delivery failure" in failed.json()["chat_handoff_error"]
    monkeypatch.setattr(quiz_chat,"handoff_review",real)
    assert client.post(retry,headers=headers("parent_a")).status_code == 200
    with sqlite3.connect(web_db) as conn:
        assert conn.execute("SELECT count(*) FROM judgment_records WHERE attempt_id=?",(attempt_id,)).fetchone()[0] == 2
        assert conn.execute("SELECT response,is_correct FROM student_attempts WHERE id=?",(attempt_id,)).fetchone() == ("43",0)
    with sqlite3.connect(path) as chat:
        assert chat.execute("SELECT count(*) FROM messages").fetchone()[0] == 3


def test_formal_assessment_routes_preserve_delegation(family_client,web_db):
    from deeptutor.education.application import assessment_engine as engine
    from deeptutor.education.storage.sqlite import open_database
    from deeptutor.multi_user.teaching_grants import Access
    client,headers=family_client
    with store.connect(write=True) as conn:
        conn.execute("INSERT INTO teaching_grants VALUES(?,?,?)",('u_parent_a',Access(features=['quiz','chat']).model_dump_json(),'u_admin'))
    blueprint={'curriculum_key':'test','grade':4,'units':['node-A','node-B'],'competition_domain':'mathematics'}
    route='/api/edu/assessment-admin/courses/'+CV
    for name in ('parent_a','student_a','parent_b'):
        assert client.put(route,json=blueprint,headers=headers(name)).status_code==403
    assert client.put(route,json=blueprint,headers=headers('admin')).status_code==200
    plan={'course_version_id':CV,'grade':4,'school_grade':3,'entry_level':'extension','revision':0}
    planroute='/api/edu/students/u_student_a/learning-plan'
    for name in ('admin','student_a','parent_b'):
        assert client.put(planroute,json=plan,headers=headers(name)).status_code==403
    assert client.put(planroute,json=plan,headers=headers('parent_a')).status_code==200
    assert client.put(planroute,json=plan,headers=headers('parent_a')).status_code==409
    catalog='/api/edu/assessments/catalog?learner_id='+LEARNER
    assert client.get(catalog,headers=headers('student_b')).status_code==403
    assert client.get(catalog,headers=headers('student_a')).json()['courses'][0]['learning_grade']==4
    request={'learner_id':LEARNER,'course_version_id':CV,'kind':'competition'}
    for name in ('admin','parent_a','parent_b','student_b'):
        assert client.post('/api/edu/assessments',json=request,headers=headers(name)).status_code==403
    # There are no reviewed competition items: trial mode cannot silently fill.
    assert client.post('/api/edu/assessments',json=request,headers=headers('student_a')).status_code==409
    with store.connect(write=True) as conn:
        conn.execute('UPDATE teaching_grants SET grant_json=? WHERE user_id=?',(Access(features=['chat']).model_dump_json(),'u_parent_a'))
    assert client.get(catalog,headers=headers('student_a')).status_code==403


def test_voice_uses_current_chat_grant_and_supported_language(teaching,as_user,monkeypatch):
    from deeptutor.api.routers.voice import _teaching_voice_access,voice_status
    from deeptutor.multi_user.teaching_grants import Access
    from deeptutor.multi_user import model_access
    from fastapi import HTTPException
    activate(teaching)
    catalog={'services':{}}
    monkeypatch.setattr(model_access,'admin_catalog',lambda:catalog)
    with store.connect(write=True) as conn:
        conn.execute('INSERT INTO teaching_grants VALUES(?,?,?)',('u_parent_a',Access(features=['chat']).model_dump_json(),'u_admin'))
    with as_user('u_student_a',role='student'):
        assert _teaching_voice_access('zh-Hant')==(catalog,'zh')
        with pytest.raises(HTTPException):_teaching_voice_access('fr')
        assert voice_status()['configured'] is False
    with as_user('u_parent_a',role='parent'):
        with pytest.raises(HTTPException):_teaching_voice_access('en')
    with store.connect(write=True) as conn:
        conn.execute('UPDATE teaching_grants SET grant_json=? WHERE user_id=?',(Access().model_dump_json(),'u_parent_a'))
    with as_user('u_student_a',role='student'):
        with pytest.raises(HTTPException):_teaching_voice_access('en')


def test_previous_practice_is_recoverable_in_new_quiz(family_client):
    from deeptutor.multi_user.teaching_grants import Access
    client,headers=family_client
    with store.connect(write=True) as conn:
        conn.execute('INSERT INTO teaching_grants VALUES(?,?,?)',('u_parent_a',Access(features=['quiz','chat']).model_dump_json(),'u_admin'))
    issued=client.post('/api/edu/set',params={'learner_id':LEARNER,'course_version_id':CV},headers=headers('student_a')).json()
    active=client.get('/api/edu/assessments/active',params={'learner_id':LEARNER},headers=headers('student_a')).json()
    assert active['exam'] is None and active['legacy_task']['set_id']==issued['set_id']
    response=client.post('/api/edu/set/submit',json={'set_id':issued['set_id'],'learner_id':LEARNER,'course_version_id':CV,'answers':[{'item_id':i['id'],'response':'42'} for i in issued['items']]},headers=headers('student_a'))
    assert response.status_code==200,response.text
    assert response.json()['chat_handoff']['session_id']
    assert client.get('/api/edu/assessments/active',params={'learner_id':LEARNER},headers=headers('student_a')).json()=={'exam':None,'legacy_task':None}


from deeptutor.education.tests.test_formal_assessment import formal


def test_competition_followup_and_numeric_review_are_family_scoped(family_client,formal,web_db,monkeypatch):
    monkeypatch.setenv("TEACHING_EDUCATION_DB",str(web_db))
    from deeptutor.education.application import assessment_engine as engine
    from deeptutor.education.storage.repositories import AssessmentItemRepository
    from deeptutor.multi_user.teaching_grants import Access
    client,headers=family_client;conn,_=formal
    with store.connect(write=True) as users:
        users.execute('INSERT INTO teaching_grants VALUES(?,?,?)',('u_parent_a',Access(features=['quiz','chat']).model_dump_json(),'u_admin'))
    paper=engine.issue(conn,LEARNER,CV,'competition')
    answers=[{'item_id':i['id'],'response':AssessmentItemRepository(conn).get(i['id']).expected_answer if n<14 else '-999'} for n,i in enumerate(paper['items'])]
    response=client.post('/api/edu/set/submit',json={'learner_id':LEARNER,'course_version_id':CV,'set_id':paper['set_id'],'answers':answers},headers=headers('student_a'))
    assert response.status_code==200,response.text
    assert response.json()['assessment']['promotion']['to_grade']==5
    route='/api/edu/assessments/'+paper['set_id']+'/foundation-choice'
    for name in ('admin','parent_a','parent_b','student_b'):
        assert client.post(route,json={'choice':'yes'},headers=headers(name)).status_code==403
    active=client.get('/api/edu/assessments/active',params={'learner_id':LEARNER},headers=headers('student_a')).json()
    assert active['exam']['set_id']==paper['set_id'] and active['exam']['submitted']
    started=client.post(route,json={'choice':'yes'},headers=headers('student_a'))
    assert started.status_code==200,started.text
    foundation=started.json()['exam'];assert foundation['kind']=='foundation'
    assert client.post(route,json={'choice':'yes'},headers=headers('student_a')).json()['exam']['set_id']==foundation['set_id']
    review='/api/edu/assessments/'+paper['set_id']+'/review'
    payload={'item_id':paper['items'][-1]['id'],'points':2.5,'note':'Checked the original working and awarded partial credit.'}
    for name in ('admin','student_a','parent_b','student_b'):
        assert client.get(review,headers=headers(name)).status_code==403
        assert client.post(review,json=payload,headers=headers(name)).status_code==403
    result=client.post(review,json=payload,headers=headers('parent_a'))
    assert result.status_code==200,result.text
    assert result.json()['assessment']['percent']==72.5
    attempt=conn.execute('SELECT response,is_correct FROM student_attempts WHERE id=?',(paper['set_id']+':'+paper['items'][-1]['id'],)).fetchone()
    assert tuple(attempt)==('-999',0)
    assert conn.execute('SELECT COUNT(*) FROM promotion_events').fetchone()[0]==1
    school='/api/edu/students/u_student_a/school-grade'
    assert client.put(school,json={'grade':6},headers=headers('admin')).status_code==403
    assert client.put(school,json={'grade':6},headers=headers('parent_a')).status_code==200
    plan=client.get('/api/edu/students/u_student_a/learning-plan',headers=headers('parent_a')).json()
    assert plan['school_grade']==6 and plan['courses'][0]['learning_grade']==5
    competition=next(e for e in plan['exams'] if e['kind']=='competition')
    assert competition['result']['foundation_followup']['status']=='in_progress'
    # A low foundation score goes to Chat and teaching evidence without undoing advancement.
    response=client.post('/api/edu/set/submit',json={'learner_id':LEARNER,'course_version_id':CV,'set_id':foundation['set_id'],'answers':[{'item_id':i['id'],'response':'-999'} for i in foundation['items']]},headers=headers('student_a'))
    assert response.status_code==200,response.text
    from deeptutor.multi_user import teaching_evidence
    evidence=teaching_evidence.read('u_student_a')
    diagnostic=next(e for e in evidence['assessments'] if e['kind']=='foundation')
    assert diagnostic['diagnostic_only'] and diagnostic['percent']==0
    competition=next(e for e in evidence['assessments'] if e['kind']=='competition')
    assert competition['promotion']['to_grade']==5 and competition['foundation_followup']['status']=='completed'
    from deeptutor.multi_user.paths import scope_for_user,get_path_service_for_scope
    import sqlite3
    chat_path=get_path_service_for_scope(scope_for_user('u_student_a',is_admin=False)).get_chat_history_db()
    with sqlite3.connect(chat_path) as chat:
        content=chat.execute('SELECT content FROM messages WHERE session_id=?',(response.json()['chat_handoff']['session_id'],)).fetchone()[0]
    assert 'Foundation check' in content and 'Focus for follow-up learning' in content and 'Node A' in content
    with store.connect(write=True) as users:
        users.execute('UPDATE teaching_grants SET grant_json=? WHERE user_id=?',(Access(features=['chat']).model_dump_json(),'u_parent_a'))
    assert client.post(route,json={'choice':'yes'},headers=headers('student_a')).status_code==403
