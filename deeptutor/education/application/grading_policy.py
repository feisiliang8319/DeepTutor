"""Which items a deterministic grader can actually settle.

One predicate, three call sites — ``select_item`` (may we serve this at
all?), ``record_attempt`` (may we mark it ourselves?) and ``api.app`` (must
we call the judge?). They were previously three *different* answers to the
same question, and the disagreement was not academic:

* ``select_item`` served any ``short`` item that merely *had* an
  ``expected_answer``;
* ``record_attempt`` then handed that answer to ``grade_answer`` — which,
  for a reference answer longer than ``SHORT_FUZZY_MAX_CHARS``, skips its
  fuzzy branch entirely and can only return ``True`` on a byte-exact reply;
* so 45 of the 91 servable Grade-4 ``short`` items (reference answers of 31
  to 288 characters) were being marked **wrong no matter what the child
  wrote**, and nothing anywhere reported that (2026-08-21 audit).

The mirror-image failure was on the other side of the same line: an item
with *no* reference answer but a written rubric could never be served at
all, so 16 items (6 AP World History SAQs + 10 Illustrative Mathematics
open tasks) sat in the database as dead inventory.

The rule this module encodes: **an item is auto-gradable when a string
comparison can settle it, and needs a judge otherwise** — which is a
property of the reference answer, not of the item type. ``short`` straddles
the line; ``numeric`` and ``choice`` never do (a float parse and a label
comparison do not care how long the stored answer is).

Fail-closed on purpose: when in doubt this returns ``True`` (needs a
judge), because the cost of a judged item is a slower verdict, while the
cost of a wrongly auto-graded item is a child told they are wrong when they
are right.
"""

from __future__ import annotations

from deeptutor.education.domain.course import AssessmentItem, ItemType
from deeptutor.learning.grading import SHORT_FUZZY_MAX_CHARS

# Types whose answers a deterministic grader may attempt at all.
AUTO_GRADABLE_TYPES = (ItemType.NUMERIC, ItemType.SHORT, ItemType.CHOICE)

# Open tasks no string comparison can mark ("draw every rectangle with this
# area", "explain ONE way in which…"). Servable only when a judge is wired
# in, otherwise a child answers into a void: the attempt is stored with
# is_correct=None and never resolves.
JUDGEABLE_TYPES = (ItemType.MULTI_STEP, ItemType.VISUAL_MODEL)

# Points at a page in a physical book; the outcome is phoned in by a parent,
# so neither the grader nor the judge has anything to work with.
HUMAN_ONLY_TYPES = (ItemType.PAPER_REF,)


def needs_judgment(item: AssessmentItem) -> bool:
    """True when no deterministic grader can settle this item.

    Such an item is servable only when a judge is available, and
    ``record_attempt`` must leave its ``is_correct`` unset so the judge's
    verdict — not a string comparison — becomes the evidence.
    """
    if item.item_type in JUDGEABLE_TYPES or item.item_type in HUMAN_ONLY_TYPES:
        return True
    if item.expected_answer is None or not item.expected_answer.strip():
        # No key to compare against. (Empty string counts: it is what an
        # unfilled column looks like after a CSV import, and treating it as
        # "a reference answer that happens to be blank" would auto-mark
        # every reply wrong.)
        return True
    if item.item_type is ItemType.SHORT:
        return len(item.expected_answer.strip()) > SHORT_FUZZY_MAX_CHARS
    return False


def is_servable(item: AssessmentItem, *, judge_available: bool) -> bool:
    """Whether this item may be put in front of a learner right now."""
    if item.item_type in HUMAN_ONLY_TYPES:
        return False
    if item.item_type not in AUTO_GRADABLE_TYPES + JUDGEABLE_TYPES:
        return False
    return judge_available or not needs_judgment(item)


__all__ = [
    "AUTO_GRADABLE_TYPES",
    "HUMAN_ONLY_TYPES",
    "JUDGEABLE_TYPES",
    "is_servable",
    "needs_judgment",
]
