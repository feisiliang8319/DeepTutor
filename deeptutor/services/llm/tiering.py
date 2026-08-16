"""Per-purpose LLM tiers: which model a *non-interactive* code path should use.

Why this exists
---------------
The catalog carries exactly one active LLM (``services.llm.active_profile_id`` /
``active_model_id``). Everything that does not receive an explicit per-request
``llm_selection`` falls back to it — including bulk ingestion work such as
describing every image in an uploaded document. Those calls are high-volume,
long-input, and need no reasoning ability, so paying a frontier-model rate for
them is waste; a local model does the job for free.

There is deliberately no attempt here to make *every* call site tier-aware. Two
existing mechanisms look like they would do this job and do not:

* ``set_scoped_llm_config`` (``services/llm/config.py``) is only consulted by
  ``get_llm_config()``. Call sites that reach ``resolve_llm_runtime_config()``
  directly never see it.
* ``get_llm_client()`` returns a process-wide singleton whose config is bound at
  first construction, so a scoped override set afterwards cannot reach it either.

So a tier is applied by handing the *seam that spends the tokens* its own client,
built from its own config. Three such seams exist, one per RAG pipeline.

Configuration
-------------
Optional, under ``services.llm`` in the model catalog::

    "tiers": {"ingestion": {"profile_id": "local-omlx", "model_id": "Qwen3-VL-8B-Instruct-4bit"}}

An unset or unresolvable tier falls back to the active model — i.e. exactly the
behaviour that existed before this module. That fallback is deliberately
*fail-open on cost*: an unconfigured install keeps working rather than refusing
to ingest. The guard against silently regressing to the expensive model is
``tier_is_configured()``, which callers can log/assert on.
"""

from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING, Any

from deeptutor.services.config.model_catalog import get_model_catalog_service
from deeptutor.services.config.provider_runtime import resolve_llm_runtime_config
from deeptutor.services.model_selection.runtime import llm_config_from_resolved

if TYPE_CHECKING:  # pragma: no cover - import cycle guard
    from .client import LLMClient
    from .config import LLMConfig

logger = logging.getLogger(__name__)

#: Bulk, non-interactive work performed while indexing documents.
INGESTION = "ingestion"

_TIER_CLIENTS: dict[tuple[str, str, str], "LLMClient"] = {}


def _tier_entry(tier: str) -> dict[str, Any]:
    """Return the raw ``tiers.<tier>`` mapping from the catalog, or ``{}``."""
    try:
        service = get_model_catalog_service()
        llm = service.load().get("services", {}).get("llm", {})
        entry = (llm.get("tiers") or {}).get(tier)
    except Exception:  # noqa: BLE001 - a broken catalog must not block ingestion
        logger.debug("Could not read LLM tier %r from catalog", tier, exc_info=True)
        return {}
    return entry if isinstance(entry, dict) else {}


def _tier_selection(tier: str) -> dict[str, str] | None:
    """Return a valid ``{profile_id, model_id}`` selection for *tier*, or ``None``.

    ``LLMSelection.from_payload`` rejects a half-filled selection by raising, so
    a tier configured with only one of the two IDs must be treated as unset here
    rather than passed down — otherwise a typo in the catalog turns into a hard
    ingestion failure instead of a fallback to the active model.
    """
    entry = _tier_entry(tier)
    profile_id = str(entry.get("profile_id") or "").strip()
    model_id = str(entry.get("model_id") or "").strip()
    if not profile_id or not model_id:
        if profile_id or model_id:
            logger.warning(
                "LLM tier %r is half-configured (profile_id=%r, model_id=%r); "
                "both are required. Falling back to the active model.",
                tier,
                profile_id,
                model_id,
            )
        return None
    return {"profile_id": profile_id, "model_id": model_id}


def tier_is_configured(tier: str) -> bool:
    """Whether *tier* names a profile/model, i.e. is not just the active model."""
    return _tier_selection(tier) is not None


def resolve_tier_config(tier: str) -> "LLMConfig":
    """Resolve the :class:`LLMConfig` for *tier*, falling back to the active model.

    The selection goes through ``resolve_llm_runtime_config(llm_selection=...)``
    — the same path the chat model picker uses — so a tier gets provider
    matching, endpoint defaults, and credential resolution for free instead of
    a second, divergent copy of that logic.

    A tier pointing at a profile/model that no longer exists raises inside that
    call. Ingestion must not die because someone renamed a profile, so the
    failure is logged and downgraded to the active model.
    """
    selection = _tier_selection(tier)
    if selection is not None:
        try:
            resolved = resolve_llm_runtime_config(llm_selection=selection)
        except ValueError:
            logger.warning(
                "LLM tier %r points at a profile/model that is not in the catalog "
                "(%s). Falling back to the active model.",
                tier,
                selection,
            )
        else:
            logger.debug("LLM tier %r resolved to %s", tier, resolved.model)
            return llm_config_from_resolved(resolved)

    return llm_config_from_resolved(resolve_llm_runtime_config())


def get_tier_llm_client(tier: str) -> "LLMClient":
    """Return a cached :class:`LLMClient` bound to *tier*'s config.

    ``LLMClient.__init__`` republishes ``OPENAI_API_KEY`` / ``OPENAI_BASE_URL``
    into the process environment for legacy SDK consumers. Those globals belong
    to the *interactive* model, so building a tier client would silently
    repoint them (e.g. at a local endpoint) for the rest of the process. The
    snapshot/restore below keeps that side effect from escaping this function;
    the tier client itself is unaffected because its provider receives the
    credentials explicitly through ``LLMConfig``.
    """
    from .client import LLMClient

    config = resolve_tier_config(tier)
    cache_key = (tier, str(config.model), str(config.base_url))
    cached = _TIER_CLIENTS.get(cache_key)
    if cached is not None:
        return cached

    sentinel = object()
    saved = {name: os.environ.get(name, sentinel) for name in ("OPENAI_API_KEY", "OPENAI_BASE_URL")}
    try:
        client = LLMClient(config)
    finally:
        for name, value in saved.items():
            if value is sentinel:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value  # type: ignore[arg-type]

    _TIER_CLIENTS[cache_key] = client
    return client


def reset_tier_clients() -> None:
    """Drop cached tier clients so the next call re-reads the catalog."""
    _TIER_CLIENTS.clear()


__all__ = [
    "INGESTION",
    "get_tier_llm_client",
    "reset_tier_clients",
    "resolve_tier_config",
    "tier_is_configured",
]
