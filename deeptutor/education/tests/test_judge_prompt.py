"""What actually reaches the judge, and what happens when the reply is odd.

Split from ``test_llm_judge.py`` on purpose: that module pins the *verdict*
semantics (every failure lands on NEEDS_REVIEW). This one pins the two
things that were silently wrong on 2026-08-21 and that no verdict assertion
could have caught, because the judge kept answering — just from worse input:

* ``build_prompt`` read the rubric key ``focus`` and only ``focus``. The six
  AP World History SAQs store their guidance under ``scoring``/``ap_format``,
  so **their rubrics never reached the model at all** — it was marking them
  off the question text alone while the code read as if it had a rubric.
* ``LocalOpenAIJudge.complete`` indexed ``message["content"]`` unguarded.
  The local oMLX server occasionally answers without that key, which
  surfaced as "judge unavailable (KeyError)" — a transport diagnosis for a
  reply-shape problem.
"""

from __future__ import annotations

import json

import pytest

from deeptutor.education.application.llm_judge import (
    LocalOpenAIJudge,
    _marking_focus,
    _reply_text,
    build_prompt,
    parse_verdict,
)
from deeptutor.education.domain.course import (
    AssessmentItem,
    ContentScope,
    ItemStatus,
    ItemType,
)

# The real shapes, verbatim key sets, as found in education.db on 2026-08-21.
AP_RUBRIC = {
    "scoring": "Explain（1 分）：须点出苏非派与主流实践的差别并说明其意义。",
    "ap_format": "AP SAQ 单点作答，1 分制",
}
IM_RUBRIC = {
    "focus": "用『因数』『倍数』各造一句正确陈述",
    "authored_by": "CC 2026-08-14",
    "source_answer_available": False,
}
SYNTH_RUBRIC = {
    "answer_derivation": "18 = 2 x 9, so Noah has 3 times as many.",
    "generator": "synth-g4-oa-a2-v3",
}


def item(rubric: dict | str | None, expected_answer: str | None = None) -> AssessmentItem:
    if isinstance(rubric, dict):
        rubric = json.dumps(rubric)
    return AssessmentItem(
        id="i", course_version_id="cv", knowledge_node_id="n",
        item_type=ItemType.SHORT, difficulty=3, content_scope=ContentScope.BUNDLED,
        content_hash="0" * 64, status=ItemStatus.CANDIDATE,
        prompt="Explain ONE example of Islamic influence in South Asia.",
        expected_answer=expected_answer, rubric_json=rubric,
    )


# --------------------------------------------------------------------------
# the rubric actually reaching the model
# --------------------------------------------------------------------------


def test_ap_rubric_reaches_the_prompt():
    """The regression. Under the old ``focus``-only read this block was
    absent and the assertion below failed while everything still "worked"."""
    prompt = build_prompt(item(AP_RUBRIC), "some answer")
    assert "MARKING FOCUS" in prompt
    assert AP_RUBRIC["scoring"] in prompt
    # ap_format carries the calibration ("1 分制"), which is the difference
    # between marking an AP SAQ and marking it like a Grade-4 warm-up.
    assert AP_RUBRIC["ap_format"] in prompt


@pytest.mark.parametrize(
    ("rubric", "expected_fragment"),
    [
        (IM_RUBRIC, IM_RUBRIC["focus"]),
        (SYNTH_RUBRIC, SYNTH_RUBRIC["answer_derivation"]),
        (AP_RUBRIC, AP_RUBRIC["scoring"]),
    ],
)
def test_every_authored_rubric_schema_is_understood(rubric, expected_fragment):
    """Three processes wrote these rubrics and they share no single key.
    A new schema showing up is the expected failure mode of this test."""
    assert expected_fragment in _marking_focus(item(rubric))


def test_bookkeeping_keys_are_left_out():
    """``authored_by`` / ``generator`` / ``source_answer_available`` say where
    the item came from, not how to mark it."""
    focus = _marking_focus(item(IM_RUBRIC | SYNTH_RUBRIC))
    assert "CC 2026-08-14" not in focus
    assert "synth-g4-oa-a2-v3" not in focus
    assert "source_answer_available" not in focus


@pytest.mark.parametrize("bad", [None, "", "not json at all", "[1, 2, 3]", "null"])
def test_malformed_rubric_degrades_to_no_focus_rather_than_raising(bad):
    """A content bug must not deny a child a verdict."""
    assert _marking_focus(item(bad)) == ""
    prompt = build_prompt(item(bad), "answer")
    assert "MARKING FOCUS" not in prompt
    assert "answer" in prompt


def test_no_never_reveal_tag_on_the_block_headers():
    """The prompt stays as short as it can be.

    Prompt length is not cosmetic here: past roughly 320 tokens the local
    server starts caching a prefix and then returns empty completions (see
    ``_CACHE_BUST_PREFIX``), and every header tag or extra instruction
    spends part of that budget. Non-disclosure in particular buys nothing,
    because ``api.app`` drops the rationale before it reaches a browser.

    (A first pass on 2026-08-21 blamed this tag for the empty replies
    outright. That was wrong — re-bisecting reproduced the empties with the
    tag removed, and the cache threshold turned out to be the actual
    trigger. Recorded because the wrong explanation is the more tempting
    one: it fits the first sample and needs no server-level cause.)
    """
    prompt = build_prompt(item(AP_RUBRIC, expected_answer="the reference"), "answer")
    assert "MARKING FOCUS:" in prompt
    assert "REFERENCE ANSWER:" in prompt
    assert "never reveal" not in prompt


def test_prompt_is_not_subject_specific():
    """v1 said "CHILD'S ANSWER" and marked "a 9-year-old's maths work"; the
    framing showed up in verdicts on history items."""
    prompt = build_prompt(item(AP_RUBRIC), "answer")
    assert "STUDENT'S ANSWER" in prompt
    assert "maths" not in prompt.lower()


# --------------------------------------------------------------------------
# odd reply shapes from the local server
# --------------------------------------------------------------------------


def test_message_without_content_key_yields_empty_text_not_keyerror():
    """Observed against oMLX on 2026-08-21. Must not raise — and must not be
    reported as a transport failure either."""
    assert _reply_text({"choices": [{"message": {"role": "assistant"}}]}) == ""


@pytest.mark.parametrize("key", ["reasoning_content", "thinking"])
def test_answer_in_a_thinking_field_is_still_read(key):
    """Known Qwen3 behaviour: content empty, answer routed to a separate
    field. Discarding those is discarding usable verdicts."""
    body = {"choices": [{"message": {"content": "", key: '{"verdict": "correct"}'}}]}
    assert _reply_text(body) == '{"verdict": "correct"}'


@pytest.mark.parametrize(
    "body",
    [{}, {"choices": []}, {"choices": [{}]}, {"choices": [{"message": "a string"}]}, None],
)
def test_structurally_broken_bodies_yield_empty_text(body):
    assert _reply_text(body) == ""


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


def _reply(content: str):
    return _FakeResponse({"choices": [{"message": {"role": "assistant", "content": content}}]})


def test_each_request_gets_a_unique_system_prefix(monkeypatch):
    """Works around a local-server prompt-cache bug (see ``_CACHE_BUST_PREFIX``).

    Once oMLX caches a 256-token prefix, every later request sharing it
    returns zero output tokens — a 200 with no content, which the pipeline
    can only file as NEEDS_REVIEW. Reproduced 2026-08-21: 1 of 5 identical
    calls answered; with a per-call nonce, 5 of 5.
    """
    sent: list[str] = []

    def fake_post(url, json, timeout):
        sent.append(json["messages"][0]["content"])
        return _reply('{"verdict": "correct", "confidence": 0.9, "rationale": "ok"}')

    monkeypatch.setattr("deeptutor.education.application.llm_judge.httpx.post", fake_post)
    judge = LocalOpenAIJudge()
    judge.complete("SYSTEM TEXT", "user a")
    judge.complete("SYSTEM TEXT", "user b")

    assert len(sent) == 2
    assert sent[0] != sent[1], "identical prefixes are exactly what triggers the bug"
    # The instruction itself must survive intact, prefix or no prefix.
    assert all(text.endswith("SYSTEM TEXT") for text in sent)


def test_an_empty_reply_is_retried_with_a_fresh_nonce(monkeypatch):
    calls: list[str] = []

    def fake_post(url, json, timeout):
        calls.append(json["messages"][0]["content"])
        if len(calls) == 1:
            return _FakeResponse({"choices": [{"message": {"role": "assistant"}}]})
        return _reply('{"verdict": "partial", "confidence": 0.7, "rationale": "ok"}')

    monkeypatch.setattr("deeptutor.education.application.llm_judge.httpx.post", fake_post)
    text = LocalOpenAIJudge().complete("SYSTEM TEXT", "user")

    assert "partial" in text, "the retry's answer should be the one returned"
    assert len(calls) == 2
    assert calls[0] != calls[1], "retrying with the same prefix would hit the same cache"


def test_persistently_empty_replies_return_empty_text_not_an_error(monkeypatch):
    """Fail-closed: the attempt still has to be recorded, and an unresolved
    attempt is a better outcome than a 500 that loses the child's answer."""
    monkeypatch.setattr(
        "deeptutor.education.application.llm_judge.httpx.post",
        lambda url, json, timeout: _FakeResponse({"choices": [{"message": {}}]}),
    )
    assert LocalOpenAIJudge().complete("SYSTEM TEXT", "user") == ""


def test_empty_reply_becomes_needs_review_with_zero_confidence():
    """The end of the chain: an unreadable reply must never become a
    verdict, and ``_reply_text`` returning "" is what routes it there."""
    judgment = parse_verdict("", model_ref="m", rubric_ver="r")
    assert judgment.verdict.value == "needs_review"
    assert judgment.confidence == 0.0
