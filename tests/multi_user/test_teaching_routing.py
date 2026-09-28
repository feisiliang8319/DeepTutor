import pytest

from deeptutor.multi_user import model_access, teaching_policy
from deeptutor.multi_user import teaching_identity as identities
from deeptutor.multi_user.context import get_current_user
from deeptutor.multi_user.teaching_grants import Access, save
from deeptutor.services.llm.config import LLMConfig


@pytest.fixture
def routing(mu_isolated_root, monkeypatch):
    users = {
        n: {"id": n, "hash": "synthetic-hash", "role": "user"}
        for n in ("admin", "parent", "other", "student", "foreign")
    }
    mapping = {
        n: {
            "role": "admin"
            if n == "admin"
            else "student"
            if n in ("student", "foreign")
            else "parent"
        }
        for n in users
    }
    mapping["student"]["parent_username"] = "parent"
    mapping["foreign"]["parent_username"] = "other"
    identities.migrate(users, mapping, apply=True)
    catalog = {
        "services": {
            "llm": {
                "profiles": [
                    {
                        "id": "codex",
                        "binding": "openai_codex",
                        "owner_bound": True,
                        "models": [
                            {"id": "main", "model": "codex-model"},
                            {"id": "unselected", "model": "other-model"},
                        ],
                    },
                    {
                        "id": "api",
                        "binding": "anthropic",
                        "api_key": "synthetic-key",
                        "models": [{"id": "backup", "model": "api-model"}],
                    },
                ]
            }
        }
    }
    monkeypatch.setattr(model_access, "admin_catalog", lambda: catalog)
    from deeptutor.multi_user import teaching_routing

    monkeypatch.setattr(teaching_routing, "admin_catalog", lambda: catalog)
    policy = teaching_policy.TeachingPolicy(
        teacher_model={"profile_id": "codex", "model_id": "main"},
        fallback_model={"profile_id": "api", "model_id": "backup"},
        codex_service_enabled=True,
    )
    teaching_policy.save(policy, 0, "admin")
    save(
        "admin",
        "parent",
        Access(models=[policy.teacher_model, policy.fallback_model], features=["chat"]),
    )
    return policy, catalog, teaching_routing


def test_subscription_requires_admin_opt_in_and_explicit_family_grant(routing, as_user):
    policy, catalog, _ = routing
    with as_user("student", role="student"):
        rows = model_access.redacted_model_access()["llm"]
        assert {r["model_id"] for r in rows} == {"main", "backup"}
        assert "synthetic-key" not in str(rows)
    with as_user("foreign", role="student"):
        assert model_access.redacted_model_access()["llm"] == []
    unselected = Access(
        models=[{"profile_id": "codex", "model_id": "unselected"}], features=["chat"]
    )
    with pytest.raises(Exception, match="shared resource"):
        save("admin", "other", unselected)
    policy.codex_service_enabled = False
    policy.teacher_model = policy.fallback_model
    teaching_policy.save(policy, 1, "admin")
    with as_user("student", role="student"):
        assert {r["model_id"] for r in model_access.redacted_model_access()["llm"]} == {"backup"}


def test_admin_service_resolution_does_not_elevate_student_tools_or_workspace(
    routing, as_user, monkeypatch
):
    policy, _, module = routing
    import deeptutor.services.codex_auth as codex_auth

    seen = []

    def service():
        seen.append(get_current_user().is_admin)
        return object()

    monkeypatch.setattr(codex_auth, "get_codex_oauth_service", service)
    with as_user("student", role="student"):
        token = teaching_policy._turn_policy.set(policy)
        try:
            provider = module.build_teaching_provider(
                LLMConfig(model="codex-model", binding="openai_codex", api_key="")
            )
            assert provider is not None and seen == [True]
            assert get_current_user().id == "student" and not get_current_user().is_admin
            save("admin", "parent", Access(features=["chat"]))
            with pytest.raises(PermissionError, match="withdrawn"):
                provider.authorize()
        finally:
            teaching_policy.reset_turn_policy(token)


def test_foreign_family_is_rejected_before_loading_operator_credentials(
    routing, as_user, monkeypatch
):
    policy, _, module = routing
    import deeptutor.services.codex_auth as codex_auth

    called = []
    monkeypatch.setattr(codex_auth, "get_codex_oauth_service", lambda: called.append(True))
    with as_user("foreign", role="student"):
        token = teaching_policy._turn_policy.set(policy)
        try:
            with pytest.raises(RuntimeError, match="Chat access"):
                module.build_teaching_provider(
                    LLMConfig(model="codex-model", binding="openai_codex", api_key="")
                )
        finally:
            teaching_policy.reset_turn_policy(token)
    assert not called


def test_ungranted_api_fallback_is_not_called(routing, as_user, monkeypatch):
    policy, _, module = routing
    import deeptutor.services.codex_auth as codex_auth

    monkeypatch.setattr(codex_auth, "get_codex_oauth_service", lambda: object())
    save("parent", "student", Access(models=[policy.teacher_model], features=["chat"]))
    with as_user("student", role="student"):
        token = teaching_policy._turn_policy.set(policy)
        try:
            provider = module.build_teaching_provider(
                LLMConfig(model="codex-model", binding="openai_codex", api_key="")
            )
            with pytest.raises(PermissionError, match="fallback"):
                provider.fallback()
        finally:
            teaching_policy.reset_turn_policy(token)


def test_removed_model_ids_are_not_selected_and_ocr_is_not_implicit_fallback(routing):
    policy, catalog, _ = routing
    access = Access(
        models=[
            policy.teacher_model,
            policy.fallback_model,
            {"profile_id": "local", "model_id": "ocr"},
        ]
    )
    catalog["services"]["llm"]["profiles"][0]["models"] = []
    assert teaching_policy.choose_model(policy, access, catalog=catalog) == policy.fallback_model
    catalog["services"]["llm"]["profiles"][1]["models"] = []
    with pytest.raises(RuntimeError, match="No teaching model"):
        teaching_policy.choose_model(policy, access, catalog=catalog)


def test_catalog_lists_actual_route_and_keeps_ocr_out_of_teaching(routing):
    policy, catalog, _ = routing
    catalog["services"]["llm"]["profiles"].append(
        {
            "id": "local",
            "binding": "openai",
            "models": [
                {"id": "ocr", "model": "OvisOCR2-4bit"},
                {"id": "ocr2", "model": "DeepSeek-OCR-2-8bit"},
                {"id": "qwen", "model": "Qwen3-VL-8B-Instruct-4bit"},
            ],
        }
    )
    choices, route = teaching_policy.teaching_model_options(catalog, policy)
    assert {m["model_id"] for m in choices} == {"main", "unselected", "backup", "qwen"}
    assert [(m["model_id"], m["route_roles"]) for m in route] == [
        ("main", ["primary"]),
        ("backup", ["fallback"]),
    ]
    assert "synthetic-key" not in str((choices, route))
    with pytest.raises(Exception, match="shared resource"):
        save("admin", "parent", Access(models=[{"profile_id": "local", "model_id": "ocr"}]))
    policy.teacher_model = teaching_policy.ModelChoice(profile_id="local", model_id="ocr")
    with pytest.raises(ValueError, match="OCR"):
        teaching_policy.save(policy, 1, "admin")


def test_local_model_placeholder_key_does_not_make_it_an_api_fallback(routing):
    policy,catalog,_=routing
    catalog['services']['llm']['profiles'].append({'id':'local','binding':'openai',
        'base_url':'http://127.0.0.1:8000/v1','api_key':'placeholder',
        'models':[{'id':'qwen','model':'Qwen3-VL'}]})
    choices,_=teaching_policy.teaching_model_options(catalog,policy)
    assert not next(m for m in choices if m['model_id']=='qwen')['api_key_model']
    policy.fallback_model=teaching_policy.ModelChoice(profile_id='local',model_id='qwen')
    with pytest.raises(ValueError,match='API-key'):
        teaching_policy.save(policy,1,'admin')


def test_catalog_endpoint_limits_parent_to_granted_route(routing, as_user):
    from deeptutor.api.routers.teaching import resource_catalog
    from deeptutor.services.auth import TokenPayload

    with as_user("parent", role="parent"):
        result = resource_catalog(TokenPayload(username="parent", role="parent", user_id="parent"))
    assert {m["model_id"] for m in result["models"]} == {"main", "backup"}
    assert result["teaching_models"] == []
    with as_user("other", role="parent"):
        assert (
            resource_catalog(TokenPayload(username="other", role="parent", user_id="other"))[
                "models"
            ]
            == []
        )
