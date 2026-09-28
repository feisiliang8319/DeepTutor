"""Explicit Codex -> authorized API routing, without replaying the agent turn.

This wrapper owns no credentials. Its caller supplies providers and checks live
authorization before each request. Generic Codex callers keep their existing
behavior; only a configured teaching route installs this wrapper.
"""
from __future__ import annotations

from collections import OrderedDict
from collections.abc import Callable
import time

from .base import LLMProvider


class TeachingModelError(RuntimeError):
    """A safe failure, never an answer that the tutor may treat as evidence."""


class FailureCooldown:
    """Bounded process-local backoff; configuration revisions use distinct keys."""

    def __init__(self, clock: Callable[[], float] = time.monotonic):
        self.clock = clock
        self.entries = OrderedDict()

    def active(self, key):
        deadline = self.entries.get(key, 0)
        if deadline > self.clock():
            return True
        self.entries.pop(key, None)
        return False

    def record(self, key, retry_after=None):
        delay = 300.0 if retry_after is None else min(86400.0, max(1.0, retry_after))
        self.entries[key] = self.clock() + delay
        self.entries.move_to_end(key)
        while len(self.entries) > 256:
            self.entries.popitem(last=False)


COOLDOWNS = FailureCooldown()
FALLBACK_CODES = frozenset({"usage_limit_reached", "insufficient_quota", "rate_limit_exceeded", "model_not_found"})


def should_fallback(result):
    return result.finish_reason == "error" and (
        result.error_status in {404, 429} or result.error_code in FALLBACK_CODES
    )


class CodexFailoverProvider(LLMProvider):
    """One model request may fail over once, before any text reaches the learner."""

    def __init__(self, *, primary, primary_config, fallback, authorize,
                 cooldown_key, on_route=None, cooldowns=COOLDOWNS):
        super().__init__()
        self.primary = primary
        self.primary_config = primary_config
        self.fallback = fallback
        self.authorize = authorize
        self.cooldown_key = cooldown_key
        self.cooldowns = cooldowns
        self.on_route = on_route
        self.fallback_used = False
        self.selected_model = primary_config.model

    def get_default_model(self):
        return self.primary_config.model

    async def chat(self, messages, **kwargs):
        return await self._call(messages, streaming=False, **kwargs)

    async def chat_stream(self, messages, **kwargs):
        return await self._call(messages, streaming=True, **kwargs)

    async def _call(self, messages, *, streaming, **kwargs):
        self.authorize()
        if self.fallback_used or self.cooldowns.active(self.cooldown_key):
            return await self._fallback(messages, streaming, kwargs, "cooldown")
        emitted = False
        original_content = kwargs.get("on_content_delta")
        original_reasoning = kwargs.get("on_reasoning_delta")

        async def content(text):
            nonlocal emitted
            if text and original_content:
                emitted = True
                await original_content(text)

        async def reasoning(text):
            nonlocal emitted
            if text and original_reasoning:
                emitted = True
                await original_reasoning(text)

        options = dict(kwargs)
        options.update(model=self.primary_config.model,
                       reasoning_effort=self.primary_config.reasoning_effort)
        if streaming:
            options.update(on_content_delta=content, on_reasoning_delta=reasoning)
        call = self.primary.chat_stream if streaming else self.primary.chat
        # Provider exceptions are not classified by message text: a prompt or
        # network error containing "404" must never trigger another paid call.
        result = await call(messages=messages, **options)
        self.authorize()
        if should_fallback(result):
            self.cooldowns.record(self.cooldown_key, result.retry_after)
            if emitted:
                # The next request will use the backup. Replaying this one
                # would append two incompatible answers to the same bubble.
                raise TeachingModelError("The teaching connection was interrupted. Please retry your message.")
            return await self._fallback(messages, streaming, kwargs,
                                        "http_" + str(result.error_status) if result.error_status else result.error_code)
        if result.finish_reason == "error":
            raise TeachingModelError("The teaching model is unavailable. Please contact your administrator.")
        return result

    async def _fallback(self, messages, streaming, kwargs, reason):
        self.authorize()
        # Resolve the current fallback key/model and recheck its own grant.
        provider, config = self.fallback()
        self.selected_model = config.model
        self.fallback_used = True
        if self.on_route:
            await self.on_route(reason, config.model)
        options = dict(kwargs)
        options.update(model=config.model, reasoning_effort=config.reasoning_effort)
        call = provider.chat_stream if streaming else provider.chat
        result = await call(messages=messages, **options)
        self.authorize()
        if result.finish_reason == "error":
            raise TeachingModelError("The backup teaching model is unavailable. Please try again later.")
        return result
