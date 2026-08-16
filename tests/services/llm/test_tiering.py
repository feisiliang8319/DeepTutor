"""Tests for per-purpose LLM tiers (``deeptutor.services.llm.tiering``).

The behaviour that matters is the fallback ladder: a tier that is unset,
half-written, or pointing at a profile that no longer exists must degrade to the
active model instead of raising, because these code paths run inside document
ingestion where a config typo would otherwise abort the whole job.
"""

import os

import pytest

from deeptutor.services.llm import tiering


def _catalog(tiers=None):
    llm = {
        "active_profile_id": "cloud",
        "active_model_id": "big",
        "profiles": [
            {
                "id": "cloud",
                "name": "Cloud",
                "binding": "openai",
                "base_url": "https://api.openai.com/v1",
                "api_key": "cloud-key",
                "api_version": "",
                "extra_headers": {},
                "models": [{"id": "big", "name": "Big", "model": "gpt-expensive"}],
            },
            {
                "id": "local",
                "name": "Local",
                "binding": "openai",
                "base_url": "http://127.0.0.1:8001/v1",
                "api_key": "local-key",
                "api_version": "",
                "extra_headers": {},
                "models": [{"id": "small", "name": "Small", "model": "qwen-cheap"}],
            },
        ],
    }
    if tiers is not None:
        llm["tiers"] = tiers
    return {"version": 1, "services": {"llm": llm}}


@pytest.fixture(autouse=True)
def _clean_tier_cache():
    tiering.reset_tier_clients()
    yield
    tiering.reset_tier_clients()


@pytest.fixture
def catalog_patch(monkeypatch):
    """Point both the tier reader and the resolver at one in-memory catalog."""

    def apply(catalog):
        class _Service:
            def load(self):
                return catalog

        monkeypatch.setattr(tiering, "get_model_catalog_service", lambda: _Service())

        real_resolve = tiering.resolve_llm_runtime_config

        def _resolve(*args, **kwargs):
            return real_resolve(catalog, **kwargs)

        monkeypatch.setattr(tiering, "resolve_llm_runtime_config", _resolve)

    return apply


def test_unset_tier_falls_back_to_active_model(catalog_patch):
    catalog_patch(_catalog())
    assert tiering.tier_is_configured(tiering.INGESTION) is False
    assert tiering.resolve_tier_config(tiering.INGESTION).model == "gpt-expensive"


def test_configured_tier_wins_over_active_model(catalog_patch):
    catalog_patch(_catalog({"ingestion": {"profile_id": "local", "model_id": "small"}}))
    assert tiering.tier_is_configured(tiering.INGESTION) is True
    config = tiering.resolve_tier_config(tiering.INGESTION)
    assert config.model == "qwen-cheap"
    assert config.base_url == "http://127.0.0.1:8001/v1"
    assert config.api_key == "local-key"


def test_tier_does_not_disturb_the_active_model(catalog_patch):
    """Resolving a tier must not mutate the catalog's active selection."""
    catalog = _catalog({"ingestion": {"profile_id": "local", "model_id": "small"}})
    catalog_patch(catalog)
    tiering.resolve_tier_config(tiering.INGESTION)
    assert catalog["services"]["llm"]["active_profile_id"] == "cloud"
    assert catalog["services"]["llm"]["active_model_id"] == "big"


@pytest.mark.parametrize(
    "tier_entry",
    [
        {"profile_id": "local"},  # model_id missing
        {"model_id": "small"},  # profile_id missing
        {},
        "not-a-mapping",
    ],
)
def test_half_written_tier_falls_back_instead_of_raising(catalog_patch, tier_entry):
    catalog_patch(_catalog({"ingestion": tier_entry}))
    assert tiering.tier_is_configured(tiering.INGESTION) is False
    assert tiering.resolve_tier_config(tiering.INGESTION).model == "gpt-expensive"


def test_tier_pointing_at_missing_profile_falls_back(catalog_patch, caplog):
    catalog_patch(_catalog({"ingestion": {"profile_id": "deleted", "model_id": "gone"}}))
    with caplog.at_level("WARNING"):
        config = tiering.resolve_tier_config(tiering.INGESTION)
    assert config.model == "gpt-expensive"
    assert "not in the catalog" in caplog.text


def test_unreadable_catalog_does_not_break_ingestion(monkeypatch):
    def _boom():
        raise RuntimeError("catalog on fire")

    monkeypatch.setattr(tiering, "get_model_catalog_service", _boom)
    assert tiering.tier_is_configured(tiering.INGESTION) is False


def test_tier_client_does_not_leak_openai_env_vars(catalog_patch, monkeypatch):
    """Building a local-endpoint tier client must not repoint global OPENAI_*.

    ``LLMClient.__init__`` republishes those vars for legacy SDK consumers; they
    describe the *interactive* model, so a tier client must leave them alone.
    """
    catalog_patch(_catalog({"ingestion": {"profile_id": "local", "model_id": "small"}}))
    monkeypatch.setenv("OPENAI_API_KEY", "interactive-key")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://api.openai.com/v1")

    client = tiering.get_tier_llm_client(tiering.INGESTION)

    assert client.config.model == "qwen-cheap"
    assert os.environ["OPENAI_API_KEY"] == "interactive-key"
    assert os.environ["OPENAI_BASE_URL"] == "https://api.openai.com/v1"


def test_tier_client_is_cached_per_resolved_model(catalog_patch):
    catalog_patch(_catalog({"ingestion": {"profile_id": "local", "model_id": "small"}}))
    assert tiering.get_tier_llm_client(tiering.INGESTION) is tiering.get_tier_llm_client(
        tiering.INGESTION
    )
    tiering.reset_tier_clients()
    assert tiering.get_tier_llm_client(tiering.INGESTION) is not None


def test_catalog_save_preserves_the_tiers_field(tmp_path):
    """A UI save must not silently drop the tier config.

    Settings → Models has no control for ``tiers``; the web app just round-trips
    whatever the catalog GET returned. If normalization ever grew a key
    allowlist, tier config would vanish the next time an admin touched an
    unrelated setting — and the only symptom would be a larger OpenAI bill.
    """
    from deeptutor.services.config.model_catalog import ModelCatalogService

    service = ModelCatalogService(tmp_path / "model_catalog.json")
    catalog = _catalog({"ingestion": {"profile_id": "local", "model_id": "small"}})
    service.save(catalog)

    reloaded = service.load()
    assert reloaded["services"]["llm"]["tiers"] == {
        "ingestion": {"profile_id": "local", "model_id": "small"}
    }

    # Same round trip an admin triggers by editing an unrelated field.
    reloaded["services"]["llm"]["active_model_id"] = "big"
    service.save(reloaded)
    assert service.load()["services"]["llm"]["tiers"]["ingestion"]["model_id"] == "small"
