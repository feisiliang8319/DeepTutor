"""Resolve immutable raw answers and their latest appended judgment."""
from deeptutor.education.domain.evidence import Verdict

LOW_CONFIDENCE_FLOOR = 0.6


def effective_correctness(raw: bool | None, judgment) -> bool | None:
    if judgment is None:
        return raw
    if judgment.verdict == Verdict.NEEDS_REVIEW or (
        judgment.confidence is not None and judgment.confidence < LOW_CONFIDENCE_FLOOR
    ):
        return None
    return judgment.verdict == Verdict.CORRECT
