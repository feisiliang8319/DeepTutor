"""Request-scoped teaching routing; account, tool and material scopes stay intact."""
from __future__ import annotations

from . import teaching_policy as policy_store
from .context import get_current_user_or_none
from .model_access import _model_by_id, _profile_by_id, admin_catalog, is_owner_bound


def build_teaching_provider(config, *, on_route=None):
    actor = get_current_user_or_none()
    if not actor or actor.role != "student" or config.binding != "openai_codex" or not policy_store.identity.active():
        return None
    # Only server-prepared teaching turns can use the administrator's service.
    policy = policy_store.current_turn_policy()
    if not policy.codex_service_enabled:
        return None
    catalog = admin_catalog()
    choice = next((item for item in (policy.teacher_model, policy.reasoning_model)
                   if item and _matches(catalog, item, config.model)), None)
    if choice is None:
        raise PermissionError("This model is not a configured teaching service")

    def authorize():
        access = policy_store.require_student_access()
        live, _ = policy_store.read()
        profile = _profile_by_id(admin_catalog(), "llm", choice.profile_id)
        if (choice not in access.models or not profile or not _model_by_id(profile, choice.model_id)
                or not policy_store.codex_service_model(profile, choice.model_id, live)):
            raise PermissionError("Teaching model access has been withdrawn")

    authorize()
    from deeptutor.services.codex_auth import get_codex_oauth_service
    from deeptutor.services.llm.provider_core.codex_failover import CodexFailoverProvider
    from deeptutor.services.llm.provider_core.openai_codex_provider import OpenAICodexProvider

    from .paths import local_admin_user, user_context

    # Resolve only the service handle as the operator. Never await or execute
    # tools under that scope: all subsequent work retains the student identity.
    with user_context(local_admin_user()):
        service = get_codex_oauth_service()
    primary = OpenAICodexProvider(default_model=config.model, oauth_service=service)
    fallback_choice = policy.fallback_model

    def fallback():
        from deeptutor.services.config.provider_runtime import resolve_llm_runtime_config
        from deeptutor.services.llm.provider_factory import get_runtime_provider
        from deeptutor.services.model_selection.runtime import llm_config_from_resolved

        access = policy_store.require_student_access()
        live, _ = policy_store.read()
        if (not fallback_choice or fallback_choice != live.fallback_model
                or fallback_choice not in access.models):
            raise PermissionError("No API fallback is authorized for this student")
        current = admin_catalog()
        profile = _profile_by_id(current, "llm", fallback_choice.profile_id)
        if (not profile or is_owner_bound(profile) or not profile.get("api_key")
                or not _model_by_id(profile, fallback_choice.model_id)):
            raise RuntimeError("The configured API fallback is unavailable")
        resolved = resolve_llm_runtime_config(catalog=current, llm_selection=fallback_choice.model_dump())
        selected = llm_config_from_resolved(resolved)
        return get_runtime_provider(selected), selected

    reported = False

    async def report(reason, model):
        nonlocal reported
        if reported:
            return
        reported = True
        with policy_store.identity.connect(write=True) as conn:
            policy_store.identity._event(conn, actor.id, "model_route", "fallback", {
                "primary": choice.model_dump(), "fallback": fallback_choice.model_dump(),
                "reason": reason, "selected_model": model,
            })
        if on_route:
            await on_route(reason, model)

    _, revision = policy_store.read()
    return CodexFailoverProvider(primary=primary, primary_config=config, fallback=fallback,
                                authorize=authorize, on_route=report,
                                cooldown_key=(choice.profile_id, choice.model_id, revision))


def _matches(catalog, choice, model):
    profile = _profile_by_id(catalog, "llm", choice.profile_id)
    selected = _model_by_id(profile, choice.model_id) if profile else None
    return bool(profile and profile.get("binding") == "openai_codex"
                and selected and selected.get("model") == model)
