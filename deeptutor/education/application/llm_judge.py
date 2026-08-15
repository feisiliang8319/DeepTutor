"""LLM judging for open-response items, as *evidence* rather than as a
scoring function.

Why this module exists: 20 of the Illustrative Mathematics items are open
tasks ("draw every rectangle with this area", "write one statement using
the word factor"). No deterministic grader can mark those, so without a
judge they can be answered but never counted, and the nodes they cover stay
unmeasurable.

Three constraints shape the whole design:

* **The verdict is stored, not recomputed.** ``record_attempt`` takes a
  pre-computed ``JudgmentInput`` and writes a ``judgment_records`` row
  carrying model id, prompt version and rubric version. Mastery rebuilds
  read that row; they never re-run a model. A future model change therefore
  cannot silently rewrite a child's history (P0-DESIGN.md §2.6).
* **Uncertainty routes to a human, not to a guess.** A malformed reply, an
  unreachable model, or a low-confidence verdict must never become
  "correct". They become ``NEEDS_REVIEW`` or no judgment at all, which
  ``rebuild_mastery`` already caps below ``mastered``.
* **The rubric and the reference answer stay server-side.** They go into
  the model prompt and nowhere near a response body — the upstream
  ``quiz_judge`` leak (2026-08-13) is the cautionary case.

The client is a plain OpenAI-compatible HTTP call so the education package
keeps its "no upstream provider imports" property; by default it points at
the local oMLX server, so a child's work does not leave the machine.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import logging
import re
from typing import Any, Protocol

import httpx

from deeptutor.education.application.record_attempt import JudgmentInput
from deeptutor.education.domain.course import AssessmentItem
from deeptutor.education.domain.evidence import JudgeKind, Verdict

logger = logging.getLogger("deeptutor.education.alerts")

PROMPT_VERSION = "edu-judge-v1"
DEFAULT_BASE_URL = "http://127.0.0.1:8001/v1"
DEFAULT_MODEL = "Qwen3-VL-8B-Instruct-4bit"

# Below this the verdict is not trusted on its own. Kept equal to
# rebuild_mastery.LOW_CONFIDENCE_FLOOR on purpose: one number, one meaning.
CONFIDENCE_FLOOR = 0.6

_SYSTEM = (
    "You mark a 9-year-old's maths work. You are given the task, the marking "
    "focus, and the child's answer. Reply with ONE JSON object and nothing "
    "else:\n"
    '{"verdict": "correct"|"partial"|"incorrect"|"needs_review", '
    '"confidence": 0.0-1.0, "rationale": "one short sentence"}\n'
    "Use needs_review when the answer cannot be judged from text alone (it "
    "refers to a drawing, a poster, or work done on paper), or when you are "
    "unsure. Never guess a verdict to seem decisive. Judge the mathematics, "
    "not spelling or handwriting."
)


class JudgeClient(Protocol):
    """Anything that can turn a prompt into a raw model reply.

    A Protocol rather than a concrete class so tests can inject canned
    replies — including malformed ones, which is the case that matters.
    """

    def complete(self, system: str, user: str) -> str: ...


@dataclass(frozen=True, slots=True)
class LocalOpenAIJudge:
    """OpenAI-compatible chat completion against a local server."""

    base_url: str = DEFAULT_BASE_URL
    model: str = DEFAULT_MODEL
    timeout_s: float = 60.0

    def complete(self, system: str, user: str) -> str:
        response = httpx.post(
            f"{self.base_url}/chat/completions",
            json={
                "model": self.model,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                # Deterministic-ish: the same work should not flip verdict
                # between two submissions of the same answer.
                "temperature": 0.0,
                "max_tokens": 300,
            },
            timeout=self.timeout_s,
        )
        response.raise_for_status()
        return str(response.json()["choices"][0]["message"]["content"])


def rubric_version(item: AssessmentItem) -> str:
    """A content hash, so a rubric edit is visible in stored judgments
    instead of being retroactively invisible."""
    return hashlib.sha256((item.rubric_json or "").encode("utf-8")).hexdigest()[:16]


def build_prompt(item: AssessmentItem, response: str) -> str:
    focus = ""
    if item.rubric_json:
        try:
            focus = str(json.loads(item.rubric_json).get("focus") or "")
        except (json.JSONDecodeError, AttributeError):
            focus = ""
    parts = [f"TASK:\n{item.prompt or '(no prompt stored)'}"]
    if focus:
        parts.append(f"MARKING FOCUS:\n{focus}")
    if item.expected_answer:
        parts.append(f"REFERENCE ANSWER (never reveal):\n{item.expected_answer}")
    parts.append(f"CHILD'S ANSWER:\n{response}")
    return "\n\n".join(parts)


def _extract_json(raw: str) -> dict[str, Any] | None:
    """Models wrap JSON in prose or fences often enough that refusing to
    parse those would mean discarding usable verdicts; anything past the
    first balanced object is still rejected."""
    match = re.search(r"\{.*?\}", raw, re.DOTALL)
    if match is None:
        return None
    try:
        parsed = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def parse_verdict(raw: str, *, model_ref: str, rubric_ver: str) -> JudgmentInput:
    """Turn a raw reply into a judgment. Anything unparseable becomes
    ``NEEDS_REVIEW`` with zero confidence — never a silent pass or fail."""
    parsed = _extract_json(raw)
    if parsed is None:
        return JudgmentInput(
            judge_kind=JudgeKind.LLM, judge_ref=model_ref, verdict=Verdict.NEEDS_REVIEW,
            confidence=0.0, rationale="judge reply was not parseable JSON",
            prompt_version=PROMPT_VERSION, rubric_version=rubric_ver,
        )
    try:
        verdict = Verdict(str(parsed.get("verdict", "")).strip().lower())
    except ValueError:
        verdict = Verdict.NEEDS_REVIEW

    raw_confidence = parsed.get("confidence")
    try:
        confidence = min(1.0, max(0.0, float(raw_confidence)))
    except (TypeError, ValueError):
        # A verdict with no usable confidence is a verdict nobody can weigh.
        verdict, confidence = Verdict.NEEDS_REVIEW, 0.0

    if verdict is not Verdict.NEEDS_REVIEW and confidence < CONFIDENCE_FLOOR:
        # Keep the model's opinion in the rationale, but do not let a
        # hesitant call carry a node toward mastered.
        return JudgmentInput(
            judge_kind=JudgeKind.LLM, judge_ref=model_ref, verdict=Verdict.NEEDS_REVIEW,
            confidence=confidence,
            rationale=f"low confidence ({confidence:.2f}) on '{verdict.value}': "
                      f"{str(parsed.get('rationale', ''))[:160]}",
            prompt_version=PROMPT_VERSION, rubric_version=rubric_ver,
        )

    return JudgmentInput(
        judge_kind=JudgeKind.LLM, judge_ref=model_ref, verdict=verdict,
        confidence=confidence, rationale=str(parsed.get("rationale", ""))[:400],
        prompt_version=PROMPT_VERSION, rubric_version=rubric_ver,
    )


def judge_open_response(
    client: JudgeClient, item: AssessmentItem, response: str, *, model_ref: str
) -> JudgmentInput:
    """Judge one open answer. Never raises: a transport failure is itself a
    ``NEEDS_REVIEW`` verdict, because the child's attempt must still be
    recorded and somebody has to look at it."""
    rubric_ver = rubric_version(item)
    try:
        raw = client.complete(_SYSTEM, build_prompt(item, response))
    except Exception as exc:  # noqa: BLE001 - transport/model failures are data here
        logger.warning(
            "llm_judge: judge call failed; routing to human review",
            extra={"item_id": item.id, "error_type": type(exc).__name__},
        )
        return JudgmentInput(
            judge_kind=JudgeKind.LLM, judge_ref=model_ref, verdict=Verdict.NEEDS_REVIEW,
            confidence=0.0, rationale=f"judge unavailable ({type(exc).__name__})",
            prompt_version=PROMPT_VERSION, rubric_version=rubric_ver,
        )
    return parse_verdict(raw, model_ref=model_ref, rubric_ver=rubric_ver)


__all__ = [
    "CONFIDENCE_FLOOR",
    "DEFAULT_MODEL",
    "JudgeClient",
    "LocalOpenAIJudge",
    "PROMPT_VERSION",
    "build_prompt",
    "judge_open_response",
    "parse_verdict",
    "rubric_version",
]
