from types import SimpleNamespace

import pytest

from deeptutor.services.llm.provider_core.base import LLMResponse
from deeptutor.services.llm.provider_core.codex_failover import (
    CodexFailoverProvider,
    FailureCooldown,
    TeachingModelError,
)


class FakeProvider:
    def __init__(self, result, chunks=()):
        self.result, self.chunks, self.calls = result, chunks, []

    async def chat(self, **kwargs):
        self.calls.append(kwargs)
        if isinstance(self.result, BaseException):
            raise self.result
        return self.result

    async def chat_stream(self, **kwargs):
        for chunk in self.chunks:
            await kwargs["on_content_delta"](chunk)
        return await self.chat(**kwargs)


def test_completed_codex_tools_convert_to_paired_claude_ids_without_replaying():
    import copy
    import re

    from deeptutor.services.llm.provider_core.anthropic_provider import AnthropicProvider

    messages = [
        {"role":"assistant","tool_calls":[
            {"id":"call_1|fc_1","function":{"name":"rag","arguments":"{}"}},
            {"id":"call_1_fc_1","function":{"name":"reason","arguments":"{}"}},
        ]},
        {"role":"tool","tool_call_id":"call_1|fc_1","content":"Saved retrieval evidence"},
        {"role":"tool","tool_call_id":"call_1_fc_1","content":"Saved reasoning result"},
    ]
    original=copy.deepcopy(messages)
    provider=object.__new__(AnthropicProvider)
    _, converted=provider._convert_messages(messages)
    calls=converted[0]['content']
    results=converted[1]['content']
    assert calls[0]['id']==results[0]['tool_use_id']
    assert calls[1]['id']==results[1]['tool_use_id']=='call_1_fc_1'
    assert calls[0]['id']!=calls[1]['id']
    assert re.fullmatch(r'[a-zA-Z0-9_-]{1,128}',calls[0]['id'])
    assert messages==original and results[0]['content']=='Saved retrieval evidence'


def route(primary, backup=None, authorize=lambda: None, cooldowns=None):
    backup = backup or FakeProvider(LLMResponse("Backup answer"))
    def config(model, effort):
        return SimpleNamespace(model=model, reasoning_effort=effort)
    wrapper = CodexFailoverProvider(
        primary=primary,
        primary_config=config("codex-primary", "high"),
        fallback=lambda: (backup, config("api-backup", None)),
        authorize=authorize,
        cooldown_key=("configured-model", 1),
        cooldowns=cooldowns or FailureCooldown(),
    )
    return wrapper, backup


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [404, 429])
async def test_one_fallback_keeps_context_tools_and_uses_backup_configuration(status):
    primary = FakeProvider(
        LLMResponse("private upstream error", finish_reason="error", error_status=status)
    )
    wrapper, backup = route(primary)
    messages = [
        {"role": "user", "content": "Explain fractions"},
        {"role": "tool", "tool_call_id": "already-ran", "content": "Retrieved evidence"},
    ]
    tools = [{"type": "function", "function": {"name": "rag"}}]
    result = await wrapper.chat(messages, tools=tools, model="ignored", reasoning_effort="high")
    assert result.content == "Backup answer"
    assert len(primary.calls) == len(backup.calls) == 1
    assert backup.calls[0]["messages"] == messages and backup.calls[0]["tools"] == tools
    assert backup.calls[0]["model"] == "api-backup"
    assert backup.calls[0]["reasoning_effort"] is None
    await wrapper.chat(messages)
    assert len(primary.calls) == 1 and len(backup.calls) == 2


@pytest.mark.asyncio
async def test_success_does_not_invoke_api_even_when_answer_contains_404():
    wrapper, backup = route(FakeProvider(LLMResponse("The number is 404, not a quota error")))
    result = await wrapper.chat([{"role": "user", "content": "404"}])
    assert "404" in result.content and not backup.calls


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [400, 401, 403, 500])
async def test_other_errors_are_not_automatically_paid_retries(status):
    wrapper, backup = route(
        FakeProvider(LLMResponse("secret", finish_reason="error", error_status=status))
    )
    with pytest.raises(TeachingModelError, match="unavailable"):
        await wrapper.chat([])
    assert not backup.calls


@pytest.mark.asyncio
async def test_structured_stream_quota_code_switches_without_text_guessing():
    wrapper, backup = route(
        FakeProvider(LLMResponse("", finish_reason="error", error_code="usage_limit_reached"))
    )
    await wrapper.chat([])
    assert len(backup.calls) == 1


@pytest.mark.asyncio
async def test_partial_output_is_not_replayed_and_next_request_uses_fallback():
    wrapper, backup = route(
        FakeProvider(LLMResponse("error", finish_reason="error", error_status=429), ["first part"])
    )
    chunks = []

    async def emit(text):
        chunks.append(text)

    with pytest.raises(TeachingModelError, match="interrupted"):
        await wrapper.chat_stream([], on_content_delta=emit)
    assert chunks == ["first part"] and not backup.calls
    await wrapper.chat([])
    assert len(backup.calls) == 1


@pytest.mark.asyncio
async def test_revocation_after_primary_failure_prevents_fallback():
    checks = 0

    def authorize():
        nonlocal checks
        checks += 1
        if checks > 1:
            raise PermissionError("revoked")

    wrapper, backup = route(
        FakeProvider(LLMResponse("", finish_reason="error", error_status=404)), authorize=authorize
    )
    with pytest.raises(PermissionError):
        await wrapper.chat([])
    assert not backup.calls


@pytest.mark.asyncio
async def test_failed_backup_is_error_not_successful_teaching_text():
    backup = FakeProvider(LLMResponse("private key error", finish_reason="error"))
    wrapper, _ = route(
        FakeProvider(LLMResponse("", finish_reason="error", error_status=429)), backup
    )
    with pytest.raises(TeachingModelError) as failure:
        await wrapper.chat([])
    assert "private" not in str(failure.value) and len(backup.calls) == 1


@pytest.mark.asyncio
async def test_cooldown_skips_unavailable_primary_then_retries_after_reset_time():
    now = [0]
    cooldowns = FailureCooldown(lambda: now[0])
    primary = FakeProvider(LLMResponse("", finish_reason="error", error_status=429, retry_after=60))
    first, _ = route(primary, cooldowns=cooldowns)
    await first.chat([])
    second, _ = route(primary, cooldowns=cooldowns)
    await second.chat([])
    assert len(primary.calls) == 1
    now[0] = 61
    third, _ = route(primary, cooldowns=cooldowns)
    await third.chat([])
    assert len(primary.calls) == 2
