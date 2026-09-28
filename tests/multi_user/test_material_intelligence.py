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
        assert state["key_configured"] and state["material_processing_enabled"]
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
        assert service.settings()["material_processing_enabled"] is True
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


@pytest.fixture
def main_material(as_user, monkeypatch):
    from types import SimpleNamespace
    from deeptutor.services import material_reviews as reviews
    from deeptutor.multi_user.paths import get_admin_path_service
    with as_user("admin", role="admin"):
        root = get_admin_path_service().get_knowledge_bases_root()
        raw = root / "synthetic-math" / "raw"
        raw.mkdir(parents=True)
        source = raw / "triangles.md"
        source.write_text("Grade 4 mathematics: a triangle has three sides. 三角形有三条边。")
        manager = SimpleNamespace(config={"knowledge_bases":{"synthetic-math": {}}}, list_knowledge_bases=lambda: ["synthetic-math"])
        monkeypatch.setattr(reviews, "admin_kb_manager", lambda: manager)
    return reviews, source


def review_response(reviews):
    choices = {"subject":"mathematics", "level":"primary_upper", "quality":"readable"}
    return {"model":service.MODEL,"answers":{name:{"type":"choice","choice":choices[name],"confidence":.91,
        "probabilities":{option:1 if option==choices[name] else 0 for option in options}}
        for name,options in reviews.OPTIONS.items()}}


@pytest.mark.asyncio
async def test_versioned_preview_requires_explicit_approval_and_sends_only_excerpt(as_user,main_material,transport):
    reviews, source = main_material
    calls=transport(lambda _:httpx.Response(200,json=review_response(reviews)))
    with as_user("admin",role="admin"):
        service.save_key(KEY)
        item=reviews.prepare("synthetic-math",source.name)
        assert not calls and item["status"]=="preview"
        with pytest.raises(service.IntelligenceError,match="export_confirmation_required"):
            await reviews.analyze(item["id"],False)
        assert not calls
        result=await reviews.analyze(item["id"],True)
        assert result["status"]=="completed" and result["authorized_at"]
        assert result["result"]["subject"]["choice"]=="mathematics"
        assert reviews.review(item["id"])["result"]==result["result"]
        assert (await reviews.analyze(item["id"],True))["status"]=="completed"
    assert len(calls)==1
    body=json.loads(calls[0].content)
    assert body["state"]=={"excerpt":source.read_text()}
    assert source.name not in calls[0].content.decode() and KEY not in calls[0].content.decode()


@pytest.mark.parametrize("mutation",["changed","expired","family","traversal","symlink","personal"])
@pytest.mark.asyncio
async def test_unapproved_or_changed_material_never_leaves_server(as_user,main_material,transport,mutation):
    reviews,source=main_material
    calls=transport(lambda _:pytest.fail("Forbidden material must not leave server"))
    with as_user("admin",role="admin"):
        service.save_key(KEY)
        item=reviews.prepare("synthetic-math",source.name)
        with pytest.raises(service.IntelligenceError):
            if mutation=="family": reviews.prepare("family:parent:kb:materials",source.name)
            elif mutation=="traversal": reviews.prepare("synthetic-math","../triangles.md")
            elif mutation=="symlink":
                link=source.parent/"link.md";link.symlink_to(source)
                reviews.prepare("synthetic-math",link.name)
            elif mutation=="personal":
                source.write_text("Student personal contact child@example.com")
                reviews.prepare("synthetic-math",source.name)
            else:
                if mutation=="changed":source.write_text("Changed material")
                else:
                    with reviews._db() as conn:conn.execute("UPDATE reviews SET created_at=0 WHERE id=?",(item["id"],))
                await reviews.analyze(item["id"],True)
    assert not calls


@pytest.mark.asyncio
async def test_failed_analysis_is_persisted_and_unknown_is_marked_for_review(as_user,main_material,transport):
    reviews,source=main_material
    calls=transport(lambda _:httpx.Response(429,text="provider private data "+KEY))
    with as_user("admin",role="admin"):
        service.save_key(KEY)
        item=reviews.prepare("synthetic-math",source.name)
        with pytest.raises(service.IntelligenceError,match="rate_limited"): await reviews.analyze(item["id"],True)
        assert reviews.review(item["id"])["status"]=="failed"
        with pytest.raises(service.IntelligenceError):await reviews.analyze(item["id"],True)
        assert len(calls)==1


def test_cached_ocr_stays_local_until_preview_is_approved(as_user,main_material,transport):
    from deeptutor.multi_user.paths import get_admin_path_service
    reviews,source=main_material
    calls=transport(lambda _:pytest.fail("Preview cannot call an external parser"))
    with as_user("admin",role="admin"):
        scan=source.with_suffix(".pdf");scan.write_bytes(b"%PDF-synthetic-scan")
        digest=reviews._hash(scan.read_bytes())[:16]
        cache=get_admin_path_service().get_parse_cache_root()/digest[:2]/digest/"synthetic-ocr"
        cache.mkdir(parents=True)
        (cache/"manifest.json").write_text(json.dumps({"source_hash":digest}))
        (cache/"scan.md").write_text("Synthetic grade 4 mathematics from OCR.")
        item=reviews.prepare("synthetic-math",scan.name)
        assert item["excerpt"]=="Synthetic grade 4 mathematics from OCR."
    assert not calls


@pytest.mark.parametrize("role",["parent","student","anonymous"])
def test_all_material_review_routes_are_admin_only(api,main_material,role):
    client=api(role);expected=401 if role=="anonymous" else 403
    for path in ["/libraries","/documents?kb=synthetic-math","/reviews","/reviews/unknown"]:
        assert client.get("/intelligence"+path).status_code==expected
    assert client.post("/intelligence/preview",json={"kb":"synthetic-math","filename":"triangles.md"}).status_code==expected
    assert client.post("/intelligence/reviews/unknown/analyze",json={"confirmed_nonpersonal_export":True}).status_code==expected


@pytest.mark.asyncio
async def test_uncertain_judgment_and_interrupted_run_are_not_success(as_user,main_material,transport):
    reviews,source=main_material
    payload=review_response(reviews)
    payload["answers"]["level"].update(choice="unknown",confidence=.1,probabilities={k:1/len(reviews.OPTIONS["level"]) for k in reviews.OPTIONS["level"]})
    transport(lambda _:httpx.Response(200,json=payload))
    with as_user("admin",role="admin"):
        service.save_key(KEY)
        item=reviews.prepare("synthetic-math",source.name)
        result=await reviews.analyze(item["id"],True)
        assert result["result"]["level"]["needs_review"] is True
        pending=reviews.prepare("synthetic-math",source.name)
        with reviews._db() as conn:
            conn.execute("UPDATE reviews SET status='running',authorized_at='2000-01-01T00:00:00+00:00' WHERE id=?",(pending["id"],))
        recovered=reviews.review(pending["id"])
        assert recovered["status"]=="failed" and recovered["error_code"]=="interrupted"
