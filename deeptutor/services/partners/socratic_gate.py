"""Deterministic post-generation gate for Socratic-method tutoring partners.

``study-buddy`` and ``ap-stem-coach`` each carry a SOUL.md with HARD RULES
that forbid handing a student a complete answer: at most one step per reply,
every reply ends in a question (unless it's a one-line hand-off to the other
coach), never a finished answer list / boxed result / finished piece of
writing. Those rules are written as "override everything else" instructions
to the model, but adherence is *probabilistic*, not guaranteed: the
``gpt-5.6`` family the partners run on only accepts ``temperature=1`` (a
server-side hard constraint that cannot be tuned down) and must run with
``reasoning_effort="none"`` to keep function-tool calling working, so there
is no reasoning pass and maximum sampling entropy behind rule adherence.
Measured on 2026-08-19 with the live model: the math "factor pairs of 36"
prompt held the rule 1/3 of the time, and an open-ended "why do leaves change
color" prompt held it 0/3 of the time — on the *same* soul text, back to
back, with no prompt change between runs. This module is the deterministic
backstop for the two mechanically-checkable rules (no answer dump, must end
in a question); it does not and cannot verify pedagogical quality.

Pure / side-effect-free by design — no LLM calls, no I/O — so it is fully
unit-testable without a live model. The rewrite/truncate remediation that
*uses* these checks lives in ``runtime.PartnerRunner._execute_turn``, which
also owns the one thing this module deliberately doesn't: logging.

Known, accepted blind spots (see module docstring in runtime.py for the
streaming-path caveat, which is a *delivery* gap, not a detection gap):

* A short, single-value final answer with no explanation and no enumerated
  list ("It's 12.") trips neither signal implemented here. Catching that
  would need semantic answer-detection, which is exactly what this module
  avoids (a semantic check *is* an LLM call, i.e. the same probabilistic
  problem this module exists to route around).
* ``is_handoff_reply`` / ``is_non_substantive_message`` are regex
  allowlists tuned to the two SOUL.md files and the two current partner
  display names. A third tutoring partner, or a soul rewrite that changes
  the hand-off phrasing, would need this module updated to match.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Awaitable, Callable

# ── tunables ──────────────────────────────────────────────────────────
ENUMERATION_THRESHOLD = 3
SHORT_REPLY_WORDS = 40
NON_SUBSTANTIVE_WORDS = 15

# ── detection patterns ───────────────────────────────────────────────
_LIST_ITEM_RE = re.compile(r"(?m)^[ \t]*(?:[-*+]|\d+[.)])[ \t]+\S")
_MULT_PAIR_RE = re.compile(r"\d+\s*[×xX*]\s*\d+")
_TUPLE_PAIR_RE = re.compile(r"\(\s*\d+\s*,\s*\d+\s*\)")
# A trailing source-disclaimer line, e.g. "*(This isn't from your course
# materials — check it against your textbook.)*" — legitimate per SOUL.md
# rule 5 and allowed to sit *after* the question that actually did the work.
# Discovered live (2026-08-19 verification run): the model doesn't always
# italicise it exactly like the soul's own example — a plain
# "(This help is not from your course materials.)" is just as legitimate a
# disclaimer, and treating it as "the last paragraph" wrongly flagged a
# reply that DID end in a question as a no_question violation. Matched on
# shape (a whole paragraph entirely wrapped in parens, optionally italic)
# with a length floor so a genuinely short parenthetical — a bare final
# answer like "(12)" — can't dodge the question check by looking like one.
_TRAILING_NOTE_RE = re.compile(r"(?s)^[*_]?\(.{15,}\)[*_]?$")

_GREETING_RE = re.compile(
    r"\b(hi|hello|hey|thanks|thank you|thx|ty|bye|goodbye)\b"
    r"|what can you (do|help)|who are you|what are you"
    r"|你好|谢谢|你是谁|你能帮我什么|你能做什么|再见",
    re.IGNORECASE,
)

# Hardcoded: this is a two-partner home deployment. A third tutoring partner
# needs its display name (and the other side's hand-off phrasing) added here
# to be recognised as a legitimate hand-off target.
_HANDOFF_TARGET_NAMES = (
    "study buddy",
    "ap & stem coach",
    "ap&stem coach",
    "ap stem coach",
)


def _word_count(text: str) -> int:
    return len(text.split())


def _count_enumeration_signals(text: str) -> int:
    return max(
        len(_LIST_ITEM_RE.findall(text)),
        len(_MULT_PAIR_RE.findall(text)),
        len(_TUPLE_PAIR_RE.findall(text)),
    )


def has_answer_dump(text: str) -> bool:
    """≥3 parallel answer items: a markdown/numbered list, ≥3 inline
    ``n × n`` results, or ≥3 ``(n, n)`` tuples — the shapes SOUL.md's own
    "Wrong" examples use for a dumped factor-pair list or step outline."""
    return _count_enumeration_signals(text) >= ENUMERATION_THRESHOLD


def _paragraphs(text: str) -> list[str]:
    return [p.strip() for p in re.split(r"\n\s*\n|\n", text) if p.strip()]


def _last_substantive_paragraph(text: str) -> str:
    paras = _paragraphs(text)
    while paras and _TRAILING_NOTE_RE.match(paras[-1]):
        paras.pop()
    return paras[-1] if paras else ""


def ends_with_question(text: str) -> bool:
    """Whether the last substantive paragraph (skipping a trailing italic
    source-disclaimer line) contains a question mark."""
    para = _last_substantive_paragraph(text)
    return "?" in para or "？" in para


def is_non_substantive_message(student_message: str) -> bool:
    """Short greeting / thanks / "what can you do" — not a tutoring ask, so
    the reply shouldn't be held to the answer-withholding rules at all."""
    msg = student_message.strip()
    if not msg:
        return True
    if _word_count(msg) > NON_SUBSTANTIVE_WORDS:
        return False
    return bool(_GREETING_RE.search(msg))


def is_handoff_reply(reply: str) -> bool:
    """A short reply naming the other coach — SOUL.md's own worked hand-off
    examples are one sentence and deliberately don't end in a question."""
    if _word_count(reply) > SHORT_REPLY_WORDS:
        return False
    lowered = reply.lower()
    return any(name in lowered for name in _HANDOFF_TARGET_NAMES)


def student_already_answered(student_message: str) -> bool:
    """SOUL.md: the student gets the full list only after *they* produced
    every item — at which point the partner may confirm it in full."""
    return _count_enumeration_signals(student_message) >= ENUMERATION_THRESHOLD


@dataclass(frozen=True)
class GateDecision:
    exempt: bool
    exempt_reason: str = ""
    violated: bool = False
    violation_reason: str = ""


def evaluate(student_message: str, reply: str) -> GateDecision:
    """The one entry point runtime.py needs: exemption first, then the two
    mechanical rule checks. Either check tripping is a violation — SOUL.md
    states them as independent hard rules, not a joint condition."""
    if student_already_answered(student_message):
        return GateDecision(exempt=True, exempt_reason="student_provided_answer")
    if is_non_substantive_message(student_message):
        return GateDecision(exempt=True, exempt_reason="non_substantive_exchange")
    if is_handoff_reply(reply):
        return GateDecision(exempt=True, exempt_reason="handoff_referral")

    if has_answer_dump(reply):
        return GateDecision(exempt=False, violated=True, violation_reason="answer_dump")
    if not ends_with_question(reply):
        return GateDecision(exempt=False, violated=True, violation_reason="no_question")
    return GateDecision(exempt=False, violated=False)


# ── remediation ──────────────────────────────────────────────────────

_VIOLATION_FEEDBACK = {
    "answer_dump": (
        "Your reply just handed over a complete list, derivation, or finished "
        "result. That breaks your own hard rule against giving a finished "
        "answer while the student is still working — one solved step per "
        "reply, then stop. Example of the right shape (from your own rules): "
        '"I won\'t hand you the list — you\'re closer than you think. One '
        'pair is 1 × 36. What number goes in the blank: 2 × ___ = 36?" '
        "Rewrite your reply so it gives at most one step, hint, or fact, and "
        "hands the rest back to the student."
    ),
    "no_question": (
        "Your reply did not end with a question. Every reply must hand the "
        "next step back to the student with a real question, unless it is a "
        "one-sentence hand-off to the other coach. Rewrite your reply so the "
        "last line is a genuine question the student has to answer."
    ),
}

CompleteFn = Callable[[str, str], Awaitable[str]]


async def rewrite_once(
    *,
    student_message: str,
    draft_reply: str,
    violation_reason: str,
    persona: str,
    complete_fn: CompleteFn,
) -> str:
    """One corrective pass: feed the model its own violating draft, the
    specific rule it broke, and a positive example, then ask it to redo the
    reply. ``complete_fn`` is injected so this stays testable without a live
    model — see runtime.py for the production wiring against ``LLMClient``."""
    feedback = _VIOLATION_FEEDBACK.get(violation_reason, _VIOLATION_FEEDBACK["no_question"])
    user = (
        f"Your last reply to the student was:\n---\n{draft_reply}\n---\n\n"
        f"{feedback}\n\n"
        f"The student's message was: {student_message!r}\n\n"
        "Reply again to the student now, following your rules this time. "
        "Output ONLY the corrected reply text, nothing else."
    )
    result = await complete_fn(persona, user)
    return (result or "").strip()


_FALLBACK_QUESTION = "What do you think comes next?"


def truncate_to_safe_step(text: str) -> str:
    """Deterministic last resort when the rewrite pass still violates: cut
    the text down to "at most one step" and force a question ending, with no
    second model call (a second call could violate again — this can't)."""
    stripped = text.strip()
    if not stripped:
        return f"Let's take this one step at a time. {_FALLBACK_QUESTION}"

    cut_at: int | None = None
    list_match = _LIST_ITEM_RE.search(stripped)
    if list_match:
        cut_at = list_match.start()
    else:
        mult_match = _MULT_PAIR_RE.search(stripped)
        tuple_match = _TUPLE_PAIR_RE.search(stripped)
        candidates = [m.start() for m in (mult_match, tuple_match) if m is not None]
        if candidates:
            cut_at = min(candidates)

    if cut_at is not None and cut_at > 0:
        kept = stripped[:cut_at]
    elif cut_at is None:
        # No enumeration found — the violation was "no question ending" on a
        # longer explanation. "One step" means one sentence, not necessarily
        # one paragraph: a prose dump like the chlorophyll example is often
        # a single unbroken paragraph, so paragraph-level cutting would keep
        # the whole multi-fact explanation verbatim. Cut at the first
        # sentence boundary within the first paragraph instead.
        first_para = _paragraphs(stripped)[0] if _paragraphs(stripped) else stripped
        sentence_match = re.search(r"[.!?？。]\s+", first_para)
        kept = first_para[: sentence_match.end()] if sentence_match else first_para
    else:
        # Enumeration started at position 0 — nothing safe to keep verbatim.
        kept = ""

    kept = kept.strip()
    # A dangling "are:" / "is:" right before the cut reads as broken, not as
    # a step — drop a trailing colon/comma/semicolon left by the cut.
    kept = re.sub(r"[:,;]\s*$", ".", kept).strip()

    if not kept:
        return f"Let's take this one step at a time. {_FALLBACK_QUESTION}"
    if kept.endswith(("?", "？")):
        return kept
    return f"{kept}\n\n{_FALLBACK_QUESTION}"


__all__ = [
    "GateDecision",
    "evaluate",
    "has_answer_dump",
    "ends_with_question",
    "is_non_substantive_message",
    "is_handoff_reply",
    "student_already_answered",
    "rewrite_once",
    "truncate_to_safe_step",
]
