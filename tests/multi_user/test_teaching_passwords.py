import json

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from deeptutor.multi_user import teaching_identity as store
from deeptutor.services import auth


@pytest.fixture
def passwords(mu_isolated_root, monkeypatch):
    from deeptutor.api.routers import auth as auth_api
    from deeptutor.api.routers import teaching

    hashed = auth.hash_password("Original-1234")
    users = {
        n: {"id": n, "hash": hashed, "role": "user"} for n in ("admin", "parent", "other", "child")
    }
    mapping = {
        n: {"role": "admin" if n == "admin" else "student" if n == "child" else "parent"}
        for n in users
    }
    mapping["child"]["parent_username"] = "parent"
    store.migrate(users, mapping, apply=True)
    monkeypatch.setattr(auth, "AUTH_SECRET", "synthetic-password-session-key")
    monkeypatch.setattr(auth, "AUTH_ENABLED", True)
    monkeypatch.setattr(auth, "POCKETBASE_ENABLED", False)
    monkeypatch.setattr(auth_api, "AUTH_ENABLED", True)
    monkeypatch.setattr(auth_api, "POCKETBASE_ENABLED", False)
    app = FastAPI()
    app.include_router(teaching.router, prefix="/api/v1/teaching")
    app.include_router(auth_api.router, prefix="/api/v1/auth")
    headers = {
        n: {"Authorization": "Bearer " + auth.create_token(n, mapping[n]["role"], n)} for n in users
    }
    return TestClient(app), headers


def test_admin_reset_revokes_old_sessions_and_preserves_student_credentials(passwords):
    client, headers = passwords
    child_hash = store.get_account("child")[1]["hash"]
    response = client.put(
        "/api/v1/teaching/accounts/parent/password",
        headers=headers["admin"],
        json={"new_password": "Changed-1234"},
    )
    assert response.status_code == 200
    assert auth.decode_token(headers["parent"]["Authorization"][7:]) is None
    assert auth.authenticate("parent", "Original-1234") is None
    assert auth.authenticate("parent", "Changed-1234") is not None
    assert store.get_account("child")[1]["hash"] == child_hash
    assert auth.decode_token(headers["child"]["Authorization"][7:]) is not None
    assert "Changed-1234" not in response.text
    with store.connect() as conn:
        audit = json.dumps([dict(r) for r in conn.execute("SELECT * FROM identity_events")])
    assert "Changed-1234" not in audit and "Original-1234" not in audit


def test_parent_change_requires_current_password_and_revokes_own_session(passwords):
    client, headers = passwords
    url = "/api/v1/teaching/accounts/parent/password"
    for current in (None, "wrong"):
        body = {"new_password": "Changed-1234", "current_password": current}
        assert client.put(url, headers=headers["parent"], json=body).status_code == 400
    assert auth.authenticate("parent", "Original-1234") is not None
    assert (
        client.put(
            url,
            headers=headers["parent"],
            json={"new_password": "Changed-1234", "current_password": "Original-1234"},
        ).status_code
        == 200
    )
    assert client.get("/api/v1/teaching/students", headers=headers["parent"]).status_code == 401
    token = auth.create_token("parent", "parent", "parent")
    assert auth.decode_token(token) is not None


@pytest.mark.parametrize(
    "actor,target",
    [("parent", "other"), ("child", "parent"), ("admin", "child"), ("parent", "admin")],
)
def test_password_management_respects_role_and_family_boundary(passwords, actor, target):
    client, headers = passwords
    response = client.put(
        "/api/v1/teaching/accounts/" + target + "/password",
        headers=headers[actor],
        json={"new_password": "Changed-1234"},
    )
    assert response.status_code == 403
    assert auth.authenticate(target, "Original-1234") is not None


@pytest.mark.parametrize("value", ["short", "界" * 25])
def test_password_length_is_validated_server_side(passwords, value):
    client, headers = passwords
    assert (
        client.put(
            "/api/v1/teaching/accounts/parent/password",
            headers=headers["admin"],
            json={"new_password": value},
        ).status_code
        == 422
    )


def test_initialization_requires_change_before_accessing_family_data(passwords):
    client, headers = passwords
    url = "/api/v1/teaching/accounts/parent/initialize-password"
    assert client.post(url, headers=headers["parent"]).status_code == 403
    assert client.post(url, headers=headers["admin"]).status_code == 200
    assert auth.decode_token(headers["parent"]["Authorization"][7:]) is None
    assert auth.authenticate("parent", "12345678") is not None
    restricted = {"Authorization": "Bearer " + auth.create_token("parent", "parent", "parent")}
    status = client.get("/api/v1/auth/status", headers=restricted)
    assert status.status_code == 200 and status.json()["password_change_required"]
    assert client.get("/api/v1/teaching/students", headers=restricted).status_code == 403
    assert client.get("/api/v1/teaching/materials", headers=restricted).status_code == 403
    assert client.get("/api/v1/auth/profile", headers=restricted).status_code == 200
    change = "/api/v1/teaching/accounts/parent/password"
    assert (
        client.put(
            change,
            headers=restricted,
            json={"current_password": "12345678", "new_password": "12345678"},
        ).status_code
        == 400
    )
    assert (
        client.put(
            change,
            headers=restricted,
            json={"current_password": "12345678", "new_password": "Private-New-5678"},
        ).status_code
        == 200
    )
    assert auth.decode_token(restricted["Authorization"][7:]) is None
    fresh = {"Authorization": "Bearer " + auth.create_token("parent", "parent", "parent")}
    assert not client.get("/api/v1/auth/status", headers=fresh).json()["password_change_required"]
    assert client.get("/api/v1/teaching/students", headers=fresh).status_code == 200
    assert auth.authenticate("parent", "12345678") is None


def test_legacy_session_survives_rollout_but_not_password_reset(passwords):
    from jose import jwt

    client, headers = passwords
    legacy = jwt.encode(
        {"sub": "parent", "uid": "parent", "role": "parent"}, auth.AUTH_SECRET, algorithm="HS256"
    )
    assert auth.decode_token(legacy) is not None
    assert (
        client.post(
            "/api/v1/teaching/accounts/parent/initialize-password", headers=headers["admin"]
        ).status_code
        == 200
    )
    assert auth.decode_token(legacy) is None


def test_initialized_parent_cannot_bypass_change_through_education_service(passwords):
    from types import SimpleNamespace

    from fastapi import HTTPException

    from deeptutor.education.api.account_identity import NativeAccountAccess

    client, headers = passwords
    client.post('/api/v1/teaching/accounts/parent/initialize-password', headers=headers['admin'])
    token = auth.create_token('parent','parent','parent')
    access = NativeAccountAccess(decode=auth.decode_token, lookup=auth.get_user_info)
    request = SimpleNamespace(headers={'authorization':'Bearer '+token}, cookies={})
    with pytest.raises(HTTPException) as failure:
        access.authenticate(request)
    assert failure.value.status_code == 403
