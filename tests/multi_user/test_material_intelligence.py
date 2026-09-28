"""Jev setup boundaries: admin credentials, synthetic-only outbound data, safe failures."""
import json
from copy import deepcopy

import httpx
import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from deeptutor.api.routers import auth, material_intelligence as routes
from deeptutor.multi_user.context import set_current_user
from deeptutor.services import material_intelligence as service
from deeptutor.services.auth import TokenPayload
from deeptutor.services.config.model_catalog import redact_catalog_secrets, restore_catalog_secrets

KEY = "synthetic-unit-test-key"


def response_payload():
    answer = {"type": "choice", "choice": "mathematics", "confidence": 0.96,
              "probabilities": {"mathematics": 0.99, "other": 0.01}}
    return {"model": service.MODEL, "answers": {lang: deepcopy(answer) for lang in service.FIXTURE}}


@pytest.fixture
def transport(monkeypatch):
    original = httpx.AsyncClient
    calls = []
    def install(handler):
        def receive(request):
            calls.append(request)
            return handler(request)
        def client(**kwargs):
            assert kwargs["follow_redirects"] is False and kwargs["trust_env"] is False
            return original(transport=httpx.MockTransport(receive), **kwargs)
        monkeypatch.setattr(service.httpx, "AsyncClient", client)
        return calls
    return install


def test_key_roundtrip_keeps_other_services_and_never_returns_secret(as_user):
    with as_user("admin", role="admin"):
        store = service._store()
        before = deepcopy(store.load()["services"])
        state = service.save_key(KEY)
        assert state["key_configured"] and not state["material_processing_enabled"]
        assert KEY not in json.dumps(state)
        catalog = store.load()
        assert {k: v for k, v in catalog["services"].items() if k != service.SERVICE} == before
        assert KEY not in json.dumps(redact_catalog_secrets(catalog))
        restored = restore_catalog_secrets(redact_catalog_secrets(catalog), catalog)
        assert service._profile(store.save(restored))["api_key"] == KEY
        assert service.save_key(None)["key_configured"]
        assert service.save_key("")["key_configured"] is False


@pytest.mark.parametrize("role", ["parent", "student"])
def test_direct_service_denies_non_admin(as_user, role):
    with as_user(role, role=role), pytest.raises(HTTPException) as exc:
        service.save_key(KEY)
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_missing_key_never_calls_provider(as_user, transport):
    calls = transport(lambda _: pytest.fail("No key must mean no outbound request"))
    with as_user("admin", role="admin"), pytest.raises(service.IntelligenceError, match="not_configured"):
        await service.connection_test()
    assert not calls


@pytest.mark.asyncio
async def test_only_fixed_bilingual_fixture_is_sent(as_user, transport):
    calls = transport(lambda _: httpx.Response(200, json=response_payload()))
    with as_user("admin", role="admin"):
        service.save_key(KEY)
        result = await service.connection_test()
        assert result["status"] == "connected"
        assert service.settings()["last_test_status"] == "connected"
        assert service.settings()["material_processing_enabled"] is False
    assert len(calls) == 1
    request = calls[0]
    assert str(request.url) == service.ENDPOINT
    assert request.headers["authorization"] == "Bearer " + KEY
    body = json.loads(request.content)
    assert set(body) == {"model", "state", "questions"}
    assert body["state"] == service.FIXTURE
    assert set(body["questions"]) == {"english", "chinese"}
    assert KEY not in request.content.decode()


@pytest.mark.parametrize("status,code", [(401, "invalid_key"), (403, "invalid_key"), (429, "rate_limited"),
    (529, "rate_limited"), (500, "provider_unavailable"), (302, "provider_unavailable")])
@pytest.mark.asyncio
async def test_provider_failures_are_safe_and_persisted(as_user, transport, status, code):
    calls = transport(lambda _: httpx.Response(status, text=KEY, headers={"location": "https://example.invalid/"}))
    with as_user("admin", role="admin"):
        service.save_key(KEY)
        with pytest.raises(service.IntelligenceError) as exc:
            await service.connection_test()
        assert str(exc.value) == code and KEY not in str(exc.value)
        assert service.settings()["last_test_status"] == code
    assert len(calls) == 1


@pytest.mark.parametrize("mutation", ["model", "missing", "confidence", "probabilities", "inconclusive", "large", "malformed", "choice_type", "huge_number"])
@pytest.mark.asyncio
async def test_untrusted_responses_cannot_pass(as_user, transport, mutation):
    body = response_payload()
    if mutation == "choice_type": body["answers"]["english"]["choice"] = {}
    if mutation == "huge_number": body["answers"]["chinese"]["confidence"] = 10 ** 400
    if mutation == "model": body["model"] = "unknown"
    if mutation == "missing": body["answers"].pop("chinese")
    if mutation == "confidence": body["answers"]["chinese"]["confidence"] = True
    if mutation == "probabilities": body["answers"]["english"]["probabilities"]["other"] = .5
    if mutation == "inconclusive": body["answers"]["english"].update(choice="other", probabilities={"mathematics": 0, "other": 1})
    reply = httpx.Response(200, json=body)
    if mutation == "large": reply = httpx.Response(200, text="x" * 64001)
    if mutation == "malformed": reply = httpx.Response(200, text="not-json")
    transport(lambda _: reply)
    with as_user("admin", role="admin"):
        service.save_key(KEY)
        with pytest.raises(service.IntelligenceError): await service.connection_test()
        assert service.settings()["last_test_status"] != "connected"


@pytest.mark.asyncio
async def test_timeout_and_changed_credential_do_not_certify_success(as_user, transport, monkeypatch):
    def timeout(request): raise httpx.ReadTimeout("sensitive-provider-text", request=request)
    transport(timeout)
    with as_user("admin", role="admin"):
        service.save_key(KEY)
        with pytest.raises(service.IntelligenceError, match="timeout"): await service.connection_test()
        async def rotate(_): service.save_key("synthetic-replacement")
        monkeypatch.setattr(service, "_probe", rotate)
        with pytest.raises(service.IntelligenceError, match="configuration_changed"): await service.connection_test()
        assert service.settings()["last_test_status"] is None


@pytest.fixture
def api(make_user, monkeypatch):
    monkeypatch.setattr(auth, "AUTH_ENABLED", True)
    monkeypatch.setattr(auth, "_validate_teaching_auth", lambda: None)
    app = FastAPI()
    app.include_router(routes.router, prefix="/intelligence")
    def client(role):
        async def authenticated():
            if role == "anonymous": raise HTTPException(401)
            set_current_user(make_user(role, role=role))
            return TokenPayload(username=role, role=role, user_id=role)
        app.dependency_overrides[auth.require_auth] = authenticated
        return TestClient(app)
    return client


@pytest.mark.parametrize("role,expected", [("parent",403),("student",403),("anonymous",401)])
def test_http_role_boundaries(api, role, expected):
    client = api(role)
    assert client.get("/intelligence/settings").status_code == expected
    assert client.put("/intelligence/settings", json={"api_key": KEY}).status_code == expected
    assert client.post("/intelligence/test", json={}).status_code == expected


def test_admin_api_validation_redacts_invalid_input_and_rejects_arbitrary_state(api, transport):
    calls = transport(lambda _: pytest.fail("Invalid requests must not make calls"))
    client = api("admin")
    assert client.get("/intelligence/settings").status_code == 200
    response = client.put("/intelligence/settings", json={"api_key": KEY})
    assert response.status_code == 200 and KEY not in response.text
    response = client.put("/intelligence/settings", json={"api_key": KEY * 500})
    assert response.status_code == 422 and KEY not in response.text
    response = client.put("/intelligence/settings", json={"api_key": {"secret": KEY}})
    assert response.status_code == 422 and KEY not in response.text
    response = client.post("/intelligence/test", json={"state": {"text": "private content"}})
    assert response.status_code == 422 and "private content" not in response.text
    assert not calls
