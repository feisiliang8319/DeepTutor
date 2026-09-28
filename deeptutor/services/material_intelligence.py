"""Admin-only Jev connection setup; no document or student-data submission.

The only outbound request contains a fixed bilingual synthetic fixture. Real
material classification is deliberately not wired to this connection pilot.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json

import httpx
from fastapi import HTTPException

from deeptutor.multi_user.context import get_current_user
from deeptutor.multi_user.paths import get_admin_path_service
from deeptutor.services.config.model_catalog import ModelCatalogService

ENDPOINT = "https://api.typesafe.ai/v1/systemone"
MODEL = "jev-1.13.0"
SERVICE = "judgment"
FIXTURE = {"english": "A triangle has three sides.", "chinese": "三角形有三条边。"}


class IntelligenceError(Exception):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def _store():
    if not get_current_user().is_admin:
        raise HTTPException(403, "Administrator access required")
    return ModelCatalogService.get_instance(get_admin_path_service().get_settings_file("model_catalog"))


def _profile(catalog):
    service = catalog.get("services", {}).get(SERVICE, {})
    return next((p for p in service.get("profiles", []) if p.get("id") == "typesafe-jev"), {})


def settings():
    profile = _profile(_store().load())
    return {"key_configured": bool(profile.get("api_key")), "model": MODEL,
            "material_processing_enabled": False, "last_test_at": profile.get("last_test_at"),
            "last_test_status": profile.get("last_test_status")}


def save_key(api_key: str | None):
    if api_key is None:
        return settings()
    key = api_key.strip()
    if key == "***" or len(key) > 4096 or any(not 33 <= ord(c) <= 126 for c in key):
        raise IntelligenceError("invalid_key")
    def update(catalog):
        catalog.setdefault("services", {})[SERVICE] = {
            "active_profile_id": "typesafe-jev", "active_model_id": "jev-stable", "profiles": [{
                "id": "typesafe-jev", "name": "TypeSafe Jev", "binding": "typesafe", "api_key": key,
                "base_url": "https://api.typesafe.ai/v1", "models": [{"id": "jev-stable", "name": "Jev", "model": MODEL}],
            }],
        }
    _store().update(update)
    return settings()


def _validate_answer(answer):
    if not isinstance(answer, dict) or answer.get("type") != "choice" or not isinstance(answer.get("choice"), str) or answer.get("choice") not in {"mathematics", "other"}:
        raise IntelligenceError("invalid_response")
    confidence, probabilities = answer.get("confidence"), answer.get("probabilities")
    if (isinstance(confidence, bool) or not isinstance(confidence, (int, float))
            or not 0 <= confidence <= 1
            or not isinstance(probabilities, dict) or set(probabilities) != {"mathematics", "other"}):
        raise IntelligenceError("invalid_response")
    if any(isinstance(p, bool) or not isinstance(p, (int, float)) or not 0 <= p <= 1 for p in probabilities.values()):
        raise IntelligenceError("invalid_response")
    if abs(sum(probabilities.values()) - 1) > 0.02 or probabilities[answer["choice"]] < max(probabilities.values()):
        raise IntelligenceError("invalid_response")
    if answer["choice"] != "mathematics":
        raise IntelligenceError("test_inconclusive")


async def _probe(key):
    questions = {language: {"type": "choice", "instructions": f"Classify the school subject of state.{language}.",
                 "criteria": {"mathematics": "Mathematics or geometry", "other": "Another school subject"}}
                 for language in FIXTURE}
    # Fixed origin, no redirects or environment proxies. The request has no
    # user-controlled text, host settings, account details or private files.
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(20, connect=5), follow_redirects=False, trust_env=False) as client:
            async with client.stream("POST", ENDPOINT, headers={"Authorization": f"Bearer {key}"},
                                     json={"model": MODEL, "state": FIXTURE, "questions": questions}) as response:
                if response.status_code != 200:
                    code = "invalid_key" if response.status_code in {401, 403} else "rate_limited" if response.status_code in {429, 529} else "provider_unavailable"
                    raise IntelligenceError(code)
                body = bytearray()
                async for chunk in response.aiter_bytes():
                    body.extend(chunk)
                    if len(body) > 64000:
                        raise IntelligenceError("invalid_response")
        payload = json.loads(body)
    except httpx.TimeoutException:
        raise IntelligenceError("timeout") from None
    except httpx.HTTPError:
        raise IntelligenceError("provider_unavailable") from None
    except (ValueError, UnicodeError):
        raise IntelligenceError("invalid_response") from None
    if not isinstance(payload, dict) or not isinstance(payload.get("answers"), dict) or payload.get("model") != MODEL:
        raise IntelligenceError("invalid_response")
    for language in FIXTURE:
        _validate_answer(payload["answers"].get(language))


async def connection_test():
    store = _store()
    key = str(_profile(store.load()).get("api_key") or "")
    if not key:
        raise IntelligenceError("not_configured")
    timestamp = datetime.now(timezone.utc).isoformat()
    error = None
    try:
        await _probe(key)
    except IntelligenceError as exc:
        error = exc
    def record(catalog):
        profile = _profile(catalog)
        # A result from an old credential cannot certify a newly saved key.
        if profile.get("api_key") != key:
            raise IntelligenceError("configuration_changed")
        profile.update(last_test_at=timestamp, last_test_status=error.code if error else "connected")
    store.update(record)
    if error:
        raise error
    return {"status": "connected", "model": MODEL, "checked_at": timestamp}
