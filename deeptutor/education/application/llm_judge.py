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
import uuid

import httpx

from deeptutor.education.application.record_attempt import JudgmentInput
from deeptutor.education.domain.course import AssessmentItem
from deeptutor.education.domain.evidence import JudgeKind, Verdict

logger = logging.getLogger("deeptutor.education.alerts")

# v2 (2026-08-21): the v1 prompt hard-coded "a 9-year-old's maths work" and
# "judge the mathematics", which was true when only Illustrative Mathematics
# open tasks reached a judge. It stopped being true the moment AP World
# History short answers did, and the contamination was visible in the
# output: asked to mark "i dont know" on an Islamic-expansion SAQ, the model
# reasoned that "the child did not provide a mathematical answer". Bumped
# rather than edited in place because ``judgment_records.prompt_version``
# stores it — a silent prompt change would make old verdicts unreadable.
PROMPT_VERSION = "edu-judge-v2"
DEFAULT_BASE_URL = "http://127.0.0.1:8001/v1"
DEFAULT_MODEL = "Qwen3-VL-8B-Instruct-4bit"

# Below this the verdict is not trusted on its own. Kept equal to
# rebuild_mastery.LOW_CONFIDENCE_FLOOR on purpose: one number, one meaning.
CONFIDENCE_FLOOR = 0.6

# Subject-neutral on purpose. What the answer should contain, and how
# strictly to read it, comes from MARKING FOCUS — which is per-item data
# (see ``_marking_focus``) rather than something baked into this string.
# That is also what lets one judge serve a Grade-4 card sort and an AP SAQ
# without either one being marked to the other's bar.
_SYSTEM = (
    "You mark a student's schoolwork. You are given the task, the marking "
    "focus, and the student's answer. Reply with ONE JSON object and nothing "
    "else:\n"
    '{"verdict": "correct"|"partial"|"incorrect"|"needs_review", '
    '"confidence": 0.0-1.0, "rationale": "one short sentence"}\n'
    "Use needs_review when the answer cannot be judged from text alone (it "
    "refers to a drawing, a poster, a card sort, or work done on paper), or "
    "when you are unsure. Never guess a verdict to seem decisive. Judge the "
    "substance against the marking focus — not spelling, handwriting or "
    "style. Follow the marking focus where it states how many points the "
    "task is worth or what a scoring answer must do."
)

# No "never reveal the rubric" sentence here on purpose — not for safety
# reasons but for length: every sentence added to this prompt pushes more
# requests over the server-side cache threshold documented on
# ``_CACHE_BUST_PREFIX``. Asking a model not to leak was never the guarantee
# anyway. The guarantee is that ``api.app`` returns only ``verdict`` and
# ``confidence`` to the browser and drops the rationale entirely — a gate in
# code, on the way out, which holds whatever the model decides to write.

# Rubric keys that carry marking guidance, in the order they should be shown
# to the judge. The rubrics in this database were written by three different
# processes and share no single key: 132 generated items use
# ``answer_derivation``, 20 Illustrative Mathematics open tasks use
# ``focus``, 6 AP World History SAQs use ``scoring``/``ap_format``, and the
# publisher-sourced items use ``official_solution``. v1 read ``focus`` and
# only ``focus``, so **the AP rubrics were silently absent from the prompt** —
# the judge was marking those SAQs off the question text alone.
_RUBRIC_GUIDANCE_KEYS: tuple[str, ...] = (
    "focus",
    "scoring",
    "official_solution",
    "answer_derivation",
    "answer_display",
    "numeric_grading_note",
    "figure_dependency",
    "partial_coverage",
    "ap_format",
)


def _reply_text(body: Any) -> str:
    """The assistant text out of an OpenAI-shaped response body.

    Written defensively because the local oMLX server does not always
    produce the documented shape: observed 2026-08-21, one call in a short
    run came back with a ``message`` object carrying **no ``content`` key at
    all**. A bare ``body["choices"][0]["message"]["content"]`` turns that
    into a ``KeyError``, which ``judge_open_response`` then reports as
    "judge unavailable (KeyError)" — a transport diagnosis for what is
    really a reply-shape problem. Qwen3 builds are also known to route the
    answer into a separate thinking field and leave ``content`` empty, so
    those are checked before giving up.

    Returns ``""`` rather than raising when nothing usable is present:
    ``parse_verdict`` already turns empty text into NEEDS_REVIEW, which is
    the correct outcome and a more legible one than an exception.
    """
    try:
        message = body["choices"][0]["message"]
    except (KeyError, IndexError, TypeError):
        return ""
    if not isinstance(message, dict):
        return ""
    for key in ("content", "reasoning_content", "thinking"):
        value = message.get(key)
        if isinstance(value, str) and value.strip():
            return value
    return ""


class JudgeClient(Protocol):
    """Anything that can turn a prompt into a raw model reply.

    A Protocol rather than a concrete class so tests can inject canned
    replies — including malformed ones, which is the case that matters.
    """

    def complete(self, system: str, user: str) -> str: ...


# A unique string prepended to every system message, purely to keep the
# local server's prompt cache from matching. Working around this bug,
# reproduced against oMLX on 2026-08-21:
#
#   prompt tokens | cached | completion tokens
#   ------------- | ------ | -----------------
#            310  |      0 |  37   <- fine
#            365  |    256 |   0   <- empty reply, finish_reason "stop"
#
# Once a request's prompt is long enough for the server to cache a 256-token
# prefix, **every later request sharing that prefix comes back with zero
# output tokens**. Not a refusal and not a truncation: a successful HTTP 200
# whose message carries no content. Five identical calls: the first answers,
# the next four are empty.
#
# It ruins exactly the items this judge exists for, because prompt length is
# driven by the task text plus the rubric — a passage-based AP short-answer
# question is over the line before the child has written a word. Downstream
# it is invisible in the worst way: an empty reply is unparseable, so
# ``parse_verdict`` files a correct-by-construction NEEDS_REVIEW, and the
# symptom reads as "the judge is unsure" rather than "the judge never ran".
# Measured cost of the workaround: none beyond losing prefix-cache reuse
# (5/5 answered with it, 1/5 without).
#
# ``prompt_cache: false`` / ``cache_prompt: false`` / ``use_prompt_cache:
# false`` were all tried and all ignored by this server. Delete this once
# oMLX is fixed or replaced — check by removing the prefix and running
# ``scripts/probe_apwh_saq_judge_calibration.py``, which exercises the long
# prompts that trigger it.
_CACHE_BUST_PREFIX = "[judge-request {nonce}]\n"


@dataclass(frozen=True, slots=True)
class LocalOpenAIJudge:
    """OpenAI-compatible chat completion against a local server."""

    base_url: str = DEFAULT_BASE_URL
    model: str = DEFAULT_MODEL
    timeout_s: float = 60.0
    # One retry, because the cache-bust prefix makes an empty reply rare but
    # not impossible, and the difference between a real verdict and a
    # NEEDS_REVIEW nobody asked for is worth two seconds.
    empty_reply_retries: int = 1

    def complete(self, system: str, user: str) -> str:
        for attempt in range(self.empty_reply_retries + 1):
            nonce = uuid.uuid4().hex[:12]
            response = httpx.post(
                f"{self.base_url}/chat/completions",
                json={
                    "model": self.model,
                    "messages": [
                        {"role": "system",
                         "content": _CACHE_BUST_PREFIX.format(nonce=nonce) + system},
                        {"role": "user", "content": user},
                    ],
                    # Deterministic-ish: the same work should not flip verdict
                    # between two submissions of the same answer. (The nonce
                    # above perturbs the prompt, but a stored judgment is
                    # never recomputed — ``api.app`` replays it — so this only
                    # has to hold within a single call.)
                    "temperature": 0.0,
                    "max_tokens": 300,
                },
                timeout=self.timeout_s,
            )
            response.raise_for_status()
            text = _reply_text(response.json())
            if text:
                return text
            if attempt < self.empty_reply_retries:
                logger.warning(
                    "llm_judge: empty completion, retrying with a fresh nonce",
                    extra={"attempt": attempt},
                )
        return ""


def rubric_version(item: AssessmentItem) -> str:
    """A content hash, so a rubric edit is visible in stored judgments
    instead of being retroactively invisible."""
    return hashlib.sha256((item.rubric_json or "").encode("utf-8")).hexdigest()[:16]


def _marking_focus(item: AssessmentItem) -> str:
    """Whatever marking guidance this item's rubric carries, as one block.

    Reads a known set of keys rather than one, because the rubrics were
    authored by several different processes (see ``_RUBRIC_GUIDANCE_KEYS``).
    Bookkeeping keys (``generator``, ``authored_by``,
    ``source_answer_available``, ``node_rationale``) are left out: they say
    where the item came from, not how to mark it, and every token of them
    dilutes the instruction that matters.

    An unparseable or absent rubric yields ``""`` — the judge then works
    from the task text alone, which is worse but still honest. It must not
    raise: a malformed rubric is a content bug, not a reason to deny a
    child a verdict.
    """
    if not item.rubric_json:
        return ""
    try:
        rubric = json.loads(item.rubric_json)
    except json.JSONDecodeError:
        return ""
    if not isinstance(rubric, dict):
        return ""
    lines = []
    for key in _RUBRIC_GUIDANCE_KEYS:
        value = rubric.get(key)
        if value in (None, "", [], {}):
            continue
        lines.append(f"- {key.replace('_', ' ')}: {value}")
    return "\n".join(lines)


def build_prompt(item: AssessmentItem, response: str) -> str:
    parts = [f"TASK:\n{item.prompt or '(no prompt stored)'}"]
    focus = _marking_focus(item)
    if focus:
        parts.append(f"MARKING FOCUS:\n{focus}")
    if item.expected_answer:
        parts.append(f"REFERENCE ANSWER:\n{item.expected_answer}")
    parts.append(f"STUDENT'S ANSWER:\n{response}")
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
