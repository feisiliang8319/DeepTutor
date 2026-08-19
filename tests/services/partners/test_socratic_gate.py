"""Unit tests for the deterministic Socratic-gate detector.

Positive/negative samples for ``has_answer_dump`` / ``ends_with_question``
are taken verbatim from real gpt-5.6-luna replies captured on 2026-08-19
while measuring soul-adherence (1/3 on the factor-pairs prompt, 0/3 on the
chlorophyll prompt) — see the handoff for that session. Everything else is
a synthetic case for a specific exemption or the truncate fallback.
"""

from __future__ import annotations

import pytest

from deeptutor.services.partners import socratic_gate as gate

# ── real captured violations (2026-08-19, gpt-5.6-luna) ────────────────

MATH_ANSWER_DUMP = (
    "The factor pairs of 36 are: 1 × 36, 2 × 18, 3 × 12, 4 × 9, 6 × 6"
)

CHLOROPHYLL_DUMP = (
    "Leaves change color in autumn because chlorophyll, the green pigment "
    "that captures sunlight for photosynthesis, breaks down as daylight "
    "shortens and temperatures drop. As the green fades, other pigments "
    "that were there all along become visible: carotenoids give the yellow "
    "and orange colors, and in some trees, anthocyanins form and produce "
    "reds and purples. Eventually the tree seals off the leaf stem, cutting "
    "off water and nutrients, and the leaf falls."
)

MATH_COMPLIANT = (
    "I won't give the whole list for you to copy — you're closer than you "
    "think. A factor pair is two whole numbers that multiply to make 36. "
    "One pair is 1 × 36. What number completes 2 × ___ = 36?"
)


class TestHasAnswerDump:
    def test_inline_factor_pairs_trip_it(self):
        assert gate.has_answer_dump(MATH_ANSWER_DUMP) is True

    def test_markdown_numbered_list_trips_it(self):
        text = "Here you go:\n1. First step\n2. Second step\n3. Third step\n"
        assert gate.has_answer_dump(text) is True

    def test_two_items_does_not_trip_it(self):
        text = "1 × 36, 2 × 18 — see the pattern?"
        assert gate.has_answer_dump(text) is False

    def test_prose_explanation_without_lists_does_not_trip_it(self):
        assert gate.has_answer_dump(CHLOROPHYLL_DUMP) is False

    def test_compliant_single_hint_does_not_trip_it(self):
        assert gate.has_answer_dump(MATH_COMPLIANT) is False


class TestEndsWithQuestion:
    def test_compliant_reply_ends_with_question(self):
        assert gate.ends_with_question(MATH_COMPLIANT) is True

    def test_chlorophyll_dump_has_no_question(self):
        assert gate.ends_with_question(CHLOROPHYLL_DUMP) is False

    def test_source_disclaimer_line_is_skipped(self):
        text = (
            "One pair is 1 × 36. What number completes 2 × ___ = 36?\n\n"
            "*(This isn't from your course materials — check it against "
            "your textbook.)*"
        )
        assert gate.ends_with_question(text) is True

    def test_source_disclaimer_cannot_rescue_a_non_question_reply(self):
        text = (
            f"{CHLOROPHYLL_DUMP}\n\n"
            "*(This isn't from your course materials — check it against "
            "your textbook.)*"
        )
        assert gate.ends_with_question(text) is False

    def test_plain_non_italic_disclaimer_is_also_skipped(self):
        # Found live (2026-08-19): gpt-5.6-luna doesn't always italicise the
        # disclaimer like the soul's own worked example — a plain
        # "(This help is not from your course materials.)" trailer must not
        # make a genuinely-question-ending reply read as a violation.
        text = (
            "What number belongs in 2 × ___ = 36?\n\n"
            "(This help is not from your course materials — check it "
            "against your textbook.)"
        )
        assert gate.ends_with_question(text) is True

    def test_short_parenthetical_final_answer_is_not_treated_as_disclaimer(self):
        # A bare final answer hiding in parens must not dodge the question
        # check just by looking parenthetical.
        text = "The area of the rectangle is (12)."
        assert gate.ends_with_question(text) is False


class TestExemptions:
    def test_student_already_listed_answer_is_exempt(self):
        student = "1x36, 2x18, 3x12, 4x9, 6x6 — is that all of them?"
        decision = gate.evaluate(student, "Yes, that's all six pairs! Nice work.")
        assert decision.exempt is True
        assert decision.exempt_reason == "student_provided_answer"

    def test_thanks_is_exempt(self):
        decision = gate.evaluate("thanks, I get it now", "You're welcome! 🎉")
        assert decision.exempt is True
        assert decision.exempt_reason == "non_substantive_exchange"

    def test_capability_question_is_exempt(self):
        decision = gate.evaluate(
            "what can you help me with",
            "I can help with math, science, reading, writing, and social studies.",
        )
        assert decision.exempt is True
        assert decision.exempt_reason == "non_substantive_exchange"

    def test_handoff_reply_is_exempt(self):
        decision = gate.evaluate(
            "can you help me with 2+2=?",
            "That's fourth-grade fractions — Study Buddy has the actual course "
            "materials for that. Bring me the competition version any time.",
        )
        assert decision.exempt is True
        assert decision.exempt_reason == "handoff_referral"

    def test_long_thanks_message_is_not_exempt(self):
        # "thanks" appears, but the message goes on to ask something
        # substantive — must not be waved through.
        student = (
            "thanks for explaining that, but I still don't get how the "
            "exponent rule works when the base is negative, can you help "
            "with that part specifically"
        )
        decision = gate.evaluate(student, CHLOROPHYLL_DUMP)
        assert decision.exempt is False

    def test_long_reply_mentioning_other_coach_is_not_exempt(self):
        # Mentions the other partner in passing but is a full explanation,
        # not a one-line hand-off — must still be gated.
        long_reply = (
            "Study Buddy usually handles arithmetic like this, but since "
            "you're here: " + CHLOROPHYLL_DUMP
        )
        decision = gate.evaluate("why do leaves change color", long_reply)
        assert decision.exempt is False


class TestEvaluateViolations:
    def test_math_dump_is_flagged_answer_dump(self):
        decision = gate.evaluate("factor pairs of 36 please", MATH_ANSWER_DUMP)
        assert decision.violated is True
        assert decision.violation_reason == "answer_dump"

    def test_chlorophyll_dump_is_flagged_no_question(self):
        decision = gate.evaluate("why do leaves change color", CHLOROPHYLL_DUMP)
        assert decision.violated is True
        assert decision.violation_reason == "no_question"

    def test_compliant_reply_is_not_violated(self):
        decision = gate.evaluate("factor pairs of 36 please", MATH_COMPLIANT)
        assert decision.violated is False
        assert decision.exempt is False


class TestTruncateToSafeStep:
    def test_cuts_before_inline_enumeration(self):
        out = gate.truncate_to_safe_step(MATH_ANSWER_DUMP)
        assert "36" not in out or "1 × 36, 2 × 18" not in out
        assert out.rstrip().endswith(("?", "？"))
        assert gate.has_answer_dump(out) is False

    def test_cuts_before_markdown_list(self):
        text = "Here is how to solve it:\n1. Step one\n2. Step two\n3. Step three\n"
        out = gate.truncate_to_safe_step(text)
        assert gate.has_answer_dump(out) is False
        assert out.rstrip().endswith(("?", "？"))

    def test_keeps_first_paragraph_when_no_enumeration(self):
        out = gate.truncate_to_safe_step(CHLOROPHYLL_DUMP)
        assert gate.ends_with_question(out) is True
        # Only the first sentence/paragraph survives verbatim, not the whole
        # explanation — "one step", per SOUL.md.
        assert len(out) < len(CHLOROPHYLL_DUMP)

    def test_empty_input_still_produces_a_question(self):
        out = gate.truncate_to_safe_step("   ")
        assert out.rstrip().endswith(("?", "？"))

    def test_output_never_reintroduces_a_violation(self):
        # Regression guard for the remediation path itself: whatever comes
        # out of truncate_to_safe_step must never re-trip evaluate() as a
        # violation on its own (it has no student-message context, so check
        # the two mechanical rules directly).
        for sample in (MATH_ANSWER_DUMP, CHLOROPHYLL_DUMP):
            out = gate.truncate_to_safe_step(sample)
            assert gate.has_answer_dump(out) is False
            assert gate.ends_with_question(out) is True


# ── K-002 breakage injection: prove these tests actually discriminate ──
# (see module docstring / handoff — a validator that only ever passes is
# worthless; these directly mutate the module's decision logic in-process
# and assert the SAME test bodies above would then fail.)


class TestBreakageInjectionProvesDiscrimination:
    def test_raising_threshold_lets_the_math_dump_through(self, monkeypatch):
        monkeypatch.setattr(gate, "ENUMERATION_THRESHOLD", 99)
        assert gate.has_answer_dump(MATH_ANSWER_DUMP) is False, (
            "sanity: with the threshold sabotaged to 99, the real violating "
            "sample must now read as clean — if it doesn't, the detector "
            "isn't actually keyed off ENUMERATION_THRESHOLD and the real "
            "(un-sabotaged) test above could be passing for the wrong reason"
        )

    def test_forcing_exemption_true_hides_a_real_violation(self, monkeypatch):
        monkeypatch.setattr(gate, "is_non_substantive_message", lambda _msg: True)
        decision = gate.evaluate("why do leaves change color", CHLOROPHYLL_DUMP)
        assert decision.exempt is True, (
            "sanity: with the exemption check sabotaged to always-True, a "
            "genuine violation must now be waved through — confirms "
            "TestExemptions above is exercising a real code path, not a "
            "vacuously-true assertion"
        )

    def test_disabling_question_check_hides_the_no_question_violation(self, monkeypatch):
        monkeypatch.setattr(gate, "ends_with_question", lambda _text: True)
        decision = gate.evaluate("why do leaves change color", CHLOROPHYLL_DUMP)
        assert decision.violated is False, (
            "sanity: with ends_with_question sabotaged to always-True, the "
            "chlorophyll dump (which genuinely has no question) must now "
            "read as compliant"
        )


class TestRewriteOnce:
    @pytest.mark.asyncio
    async def test_feeds_violation_and_draft_back_to_complete_fn(self):
        seen: dict[str, str] = {}

        async def fake_complete(system: str, user: str) -> str:
            seen["system"] = system
            seen["user"] = user
            return "  Rewritten reply?  "

        out = await gate.rewrite_once(
            student_message="factor pairs of 36 please",
            draft_reply=MATH_ANSWER_DUMP,
            violation_reason="answer_dump",
            persona="SOUL TEXT",
            complete_fn=fake_complete,
        )
        assert out == "Rewritten reply?"
        assert seen["system"] == "SOUL TEXT"
        assert MATH_ANSWER_DUMP in seen["user"]
        assert "hard rule" in seen["user"]
        assert "factor pairs of 36 please" in seen["user"]

    @pytest.mark.asyncio
    async def test_no_question_feedback_differs_from_answer_dump_feedback(self):
        captured = []

        async def fake_complete(system: str, user: str) -> str:
            captured.append(user)
            return "ok"

        await gate.rewrite_once(
            student_message="x",
            draft_reply="y",
            violation_reason="answer_dump",
            persona="p",
            complete_fn=fake_complete,
        )
        await gate.rewrite_once(
            student_message="x",
            draft_reply="y",
            violation_reason="no_question",
            persona="p",
            complete_fn=fake_complete,
        )
        assert captured[0] != captured[1]
