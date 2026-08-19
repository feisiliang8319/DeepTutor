"""Provider-error classifiers used by retry and graceful-degradation paths."""

from __future__ import annotations


def error_text(exc: Exception) -> str:
    """Return the best available lowercase provider error body."""
    response = getattr(exc, "response", None)
    body = (
        getattr(exc, "body", None)
        or getattr(exc, "doc", None)
        or getattr(response, "text", None)
        or getattr(exc, "message", None)
        or str(exc)
    )
    return str(body).lower()


def is_stream_options_unsupported(exc: Exception) -> bool:
    """Whether a provider rejected OpenAI's ``stream_options`` parameter."""
    text = error_text(exc)
    return any(
        marker in text
        for marker in (
            "stream_options",
            "stream options",
            "unknown parameter",
            "unrecognized request argument",
            "unsupported parameter",
            "extra inputs are not permitted",
            "unexpected keyword",
        )
    )


#: Phrases that only appear when a provider genuinely rejects the tool/function
#: schema itself. A bare "tool" substring is deliberately NOT here: any error
#: whose body echoes the request (which carries ``tools``) would match it, and
#: so would an over-long-context error that counts "messages and tools" tokens
#: — both would be silently downgraded to a tool-less retry, hiding the real
#: cause. Add whole phrases, never single words.
_TOOL_SCHEMA_MARKERS: tuple[str, ...] = (
    "invalid schema for function",
    "invalid schema for tool",
    "function_declaration",
    "function declaration",
    "function_declarations",
    "tool_choice",
    "parameters.properties",
    "tools with reasoning_effort",
    "tools are not supported",
    "tools is not supported",
    "tools not supported",
    "does not support tools",
    "tool use is not supported",
    "tool calling is not supported",
    "function calling is not supported",
    "function call is not supported",
    "does not support function calling",
)

#: Providers that answer an unsupported-tooling request with a bare 404 (Gemini
#: does this). Kept, but only counted when the body also mentions tools or
#: functions — otherwise a mistyped model name reads as "tools unsupported" and
#: gets retried without tools, failing again for the real reason nobody sees.
_NOT_FOUND_MARKERS: tuple[str, ...] = ("404_not_found", "404 not_found")
_TOOL_HINTS: tuple[str, ...] = ("tool", "function")


def is_tool_schema_unsupported(exc: Exception) -> bool:
    """Whether a provider rejected native tool/function-calling schemas."""
    text = error_text(exc)
    if any(marker in text for marker in _TOOL_SCHEMA_MARKERS):
        return True
    return any(marker in text for marker in _NOT_FOUND_MARKERS) and any(
        hint in text for hint in _TOOL_HINTS
    )


def is_image_input_unsupported(exc: Exception) -> bool:
    """Whether a provider or model rejected multimodal message content."""
    text = error_text(exc)
    return any(
        marker in text
        for marker in (
            "image",
            "vision",
            "multimodal",
            "image_url",
            "content type",
            "must be a string",
            "expected a string",
            "expected string",
            "invalid type for 'messages",
        )
    )


__all__ = [
    "error_text",
    "is_image_input_unsupported",
    "is_stream_options_unsupported",
    "is_tool_schema_unsupported",
]
