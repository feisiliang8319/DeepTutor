"""Ingestion transform that stamps curriculum lesson identity onto chunks.

Placed *before* the sentence splitter, this component rewrites a course
document into one document per lesson, each carrying the lesson's identity and
CCSS standard codes as metadata. Two things follow:

* chunks no longer straddle a lesson boundary, and
* every chunk inherits ``curriculum_lesson_key`` / ``curriculum_standards``,
  which is what lets a diagnosis expressed as a standard code ("stuck on
  4.NF.B.3") be resolved to the passages that teach it.

The transform is a no-op for any document without lesson markers, so knowledge
bases built from other corpora (competition problem sets, science QA) are not
touched and carry no new metadata.

The added keys are excluded from both the embedding text and the LLM-visible
text. They exist to be filtered on, not to be read: including them would change
every vector in the index and leak bookkeeping into the tutor's context.
"""

from __future__ import annotations

from typing import Any, Sequence

from llama_index.core.schema import BaseNode, Document, TransformComponent

from .lesson_markers import LessonSegment, merge_segments, segment_by_lesson, split_preamble

UNIT = "curriculum_unit"
LESSON = "curriculum_lesson"
LESSON_KEY = "curriculum_lesson_key"
UNIT_TITLE = "curriculum_unit_title"
STANDARDS = "curriculum_standards"
PREREQUISITES = "curriculum_prerequisites"
BUILDING_TOWARDS = "curriculum_building_towards"

CURRICULUM_METADATA_KEYS = (
    UNIT,
    LESSON,
    LESSON_KEY,
    UNIT_TITLE,
    STANDARDS,
    PREREQUISITES,
    BUILDING_TOWARDS,
)


def _join(codes: list[str]) -> str:
    """Flatten a code list for metadata storage.

    Vector stores accept only scalar metadata values, so lists are stored as a
    comma-separated string and re-split on read by
    :func:`standards_of`.
    """
    return ",".join(codes)


def standards_of(node: Any, key: str = STANDARDS) -> list[str]:
    """Read a curriculum code list back off a node's metadata."""
    metadata = getattr(node, "metadata", None) or {}
    raw = metadata.get(key) or ""
    if isinstance(raw, (list, tuple)):
        return [str(code) for code in raw]
    return [code for code in str(raw).split(",") if code]


def segment_metadata(segment: LessonSegment) -> dict[str, Any]:
    return {
        UNIT: segment.unit,
        LESSON: segment.lesson,
        LESSON_KEY: segment.lesson_key,
        UNIT_TITLE: segment.unit_title,
        STANDARDS: _join(segment.addressing),
        PREREQUISITES: _join(segment.building_on),
        BUILDING_TOWARDS: _join(segment.building_towards),
    }


class CurriculumLessonEnricher(TransformComponent):
    """Split curriculum documents per lesson and attach standard codes."""

    @classmethod
    def class_name(cls) -> str:
        return "CurriculumLessonEnricher"

    def __call__(self, nodes: Sequence[BaseNode], **kwargs: Any) -> Sequence[BaseNode]:
        output: list[BaseNode] = []
        for node in nodes:
            output.extend(self._expand(node))
        return output

    def _expand(self, node: BaseNode) -> list[BaseNode]:
        if not isinstance(node, Document):
            return [node]

        text = node.get_content() or ""
        segments = merge_segments(segment_by_lesson(text))
        if not segments:
            return [node]

        documents: list[BaseNode] = []

        # Whatever precedes the first lesson marker is the unit heading and the
        # source/licence attribution. It belongs to no lesson, so it is emitted
        # as its own document without curriculum metadata rather than being
        # dropped or misfiled under lesson 1.
        preamble, _ = split_preamble(text)
        if preamble.strip():
            documents.append(Document(text=preamble, metadata=dict(node.metadata or {})))

        for segment in segments:
            metadata = dict(node.metadata or {})
            metadata.update(segment_metadata(segment))
            if segment.unit == "deeptutor-trial":
                metadata["curriculum_content_status"] = "trial_pending_review"
                metadata["curriculum_lesson_url"] = f"/api/edu/lessons/{segment.lesson}"
            excluded_embed = list(node.excluded_embed_metadata_keys or [])
            excluded_llm = list(node.excluded_llm_metadata_keys or [])
            for key in CURRICULUM_METADATA_KEYS:
                if key not in excluded_embed:
                    excluded_embed.append(key)
                if key not in excluded_llm:
                    excluded_llm.append(key)
            documents.append(
                Document(
                    text=segment.text,
                    metadata=metadata,
                    excluded_embed_metadata_keys=excluded_embed,
                    excluded_llm_metadata_keys=excluded_llm,
                )
            )
        return documents


__all__ = [
    "BUILDING_TOWARDS",
    "CURRICULUM_METADATA_KEYS",
    "CurriculumLessonEnricher",
    "LESSON",
    "LESSON_KEY",
    "PREREQUISITES",
    "STANDARDS",
    "UNIT",
    "UNIT_TITLE",
    "segment_metadata",
    "standards_of",
]
