"""Parse curriculum lesson markers and CCSS standard codes out of raw course text.

Why this exists
---------------
DeepTutor keeps two representations of the same subject matter:

* ``education.db`` — a knowledge graph whose nodes carry a ``standard_code``
  (``4.OA.B.4``). Diagnosis speaks this language: "the learner is stuck on
  4.NF.B.3".
* A LlamaIndex knowledge base — the actual lesson prose the tutor teaches from.

Before this module the two were unrelated: chunk metadata held only
``file_name`` / ``file_path``, so a diagnosis could not be turned into "retrieve
*these* lessons". The missing key was never missing from the corpus, only from
the index — Illustrative Mathematics course exports label every passage with

    **[Grade 4 · Unit 1: Factors and Multiples · Lesson 1]**

and declare each lesson's standards in a ``CCSS Standards`` block. Both are
regular enough to parse mechanically, and both are *content-derived*: they are
recomputed identically on every re-index, unlike LlamaIndex node ids which are
regenerated and therefore cannot be used as a join key.

Everything here is deliberately format-detecting rather than format-assuming:
a corpus without markers yields no segments at all, so non-curriculum knowledge
bases flow through the ingestion pipeline untouched.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import re

# **[Grade 4 · Unit 1: Factors and Multiples · Lesson 1]**
# The separator is U+00B7 MIDDLE DOT as emitted by the course export.
MARKER_RE = re.compile(
    r"^\*\*\[Grade\s+(?P<grade>\d+)\s*·\s*Unit\s+(?P<unit>\d+)\s*:\s*"
    r"(?P<unit_title>.+?)\s*·\s*Lesson\s+(?P<lesson>\d+)\]\*\*\s*$",
    re.MULTILINE,
)

CCSS_HEADING = "CCSS Standards"

# A standard code such as 4.OA.B.4, 4.NF.B.4.a, or the coarse form 3.MD.C.
STANDARD_CODE_RE = re.compile(r"^\d\.[A-Z]{1,3}(?:\.[A-Z])?(?:\.\d+)?(?:\.[a-z])?$")

_BUCKETS = {
    "Building On": "building_on",
    "Addressing": "addressing",
    "Building Towards": "building_towards",
}


@dataclass
class LessonSegment:
    """One lesson's contiguous span of a course document."""

    unit: int
    lesson: int
    unit_title: str
    grade: int
    text: str
    building_on: list[str] = field(default_factory=list)
    addressing: list[str] = field(default_factory=list)
    building_towards: list[str] = field(default_factory=list)

    @property
    def lesson_key(self) -> str:
        """Stable, content-derived identifier: ``U1L3``.

        Deliberately *not* derived from a node id, a file path or an ingestion
        timestamp — re-indexing the same corpus must produce the same key.
        """
        return f"U{self.unit}L{self.lesson}"


def extract_standards(text: str) -> dict[str, list[str]]:
    """Collect CCSS codes from every ``CCSS Standards`` block inside ``text``.

    A lesson repeats the block once per activity, so codes are unioned across
    blocks and returned sorted. Any line that is neither a bucket heading nor a
    standard code terminates the current block — the exports do not delimit it
    otherwise.
    """
    found: dict[str, set[str]] = {name: set() for name in _BUCKETS.values()}
    in_block = False
    bucket: str | None = None

    for raw_line in text.splitlines():
        line = raw_line.strip()

        if line == CCSS_HEADING:
            in_block = True
            bucket = None
            continue
        if not in_block:
            continue
        if line in _BUCKETS:
            bucket = _BUCKETS[line]
            continue
        if not line:
            continue
        if STANDARD_CODE_RE.match(line):
            if bucket is not None:
                found[bucket].add(line)
            continue
        in_block = False
        bucket = None

    return {name: sorted(codes) for name, codes in found.items()}


def split_preamble(text: str) -> tuple[str, str]:
    """Split ``text`` into (preamble, lessons) at the first lesson marker.

    The preamble is whatever precedes the first marker. Callers must keep it:
    dropping it silently removed the unit heading and the CC BY attribution
    block from every indexed course file.

    Returns ``("", text)`` when there is no marker at all, so a non-curriculum
    document passes through untouched.
    """
    match = MARKER_RE.search(text)
    if match is None:
        return "", text
    return text[: match.start()], text[match.start() :]


def segment_by_lesson(text: str) -> list[LessonSegment]:
    """Split course text into one segment per lesson.

    Markers repeat many times within a single lesson (roughly once per
    passage), so consecutive markers naming the same lesson are merged rather
    than treated as boundaries.

    Text preceding the first marker belongs to no lesson and is returned
    separately by :func:`split_preamble` rather than silently dropped — in the
    Illustrative Mathematics exports that leading block is the unit title and
    the CC BY source attribution, so losing it would strip provenance out of
    the index.

    Returns an empty list when the corpus carries no markers, which is the
    signal that this document is not a curriculum export.
    """
    matches = list(MARKER_RE.finditer(text))
    if not matches:
        return []

    # Collapse runs of markers that name the same lesson into one boundary.
    boundaries: list[tuple[int, re.Match[str]]] = []
    for match in matches:
        key = (int(match.group("unit")), int(match.group("lesson")))
        if boundaries and boundaries[-1][0] == key:
            continue
        boundaries.append((key, match))  # type: ignore[arg-type]

    segments: list[LessonSegment] = []
    for position, (key, match) in enumerate(boundaries):
        start = match.start()
        end = boundaries[position + 1][1].start() if position + 1 < len(boundaries) else len(text)
        body = text[start:end]
        standards = extract_standards(body)
        segments.append(
            LessonSegment(
                unit=key[0],
                lesson=key[1],
                unit_title=match.group("unit_title"),
                grade=int(match.group("grade")),
                text=body,
                **standards,
            )
        )
    return segments


def merge_segments(segments: list[LessonSegment]) -> list[LessonSegment]:
    """Merge segments that describe the same lesson.

    A lesson is exported as separate ``Preparation`` and ``Lesson Content``
    sections, and a course may be split across files, so the same
    ``(unit, lesson)`` can legitimately appear more than once. Text is
    concatenated in encounter order and standards are unioned.
    """
    merged: dict[tuple[int, int], LessonSegment] = {}
    for segment in segments:
        key = (segment.unit, segment.lesson)
        existing = merged.get(key)
        if existing is None:
            merged[key] = segment
            continue
        existing.text = f"{existing.text}\n{segment.text}"
        for bucket in ("building_on", "addressing", "building_towards"):
            combined = set(getattr(existing, bucket)) | set(getattr(segment, bucket))
            setattr(existing, bucket, sorted(combined))
    return list(merged.values())


__all__ = [
    "LessonSegment",
    "MARKER_RE",
    "STANDARD_CODE_RE",
    "extract_standards",
    "merge_segments",
    "segment_by_lesson",
    "split_preamble",
]
