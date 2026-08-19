"""Sidecar index mapping CCSS standard codes to the lessons that teach them.

The vector store cannot answer "which passages address 4.NF.B.3?". FAISS — the
backend used for every re-indexed knowledge base — has no metadata filtering,
and neither does the BM25 retriever, so the lookup has to live beside the
index rather than inside it.

That constraint turns out to be a feature: resolving a standard code to lessons
is a deterministic table lookup, not a similarity problem, and it should not be
subject to embedding drift or retrieval noise. The sidecar is rebuilt from the
enriched nodes every time the index is written, so the two cannot disagree.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import json
import logging
from pathlib import Path
from typing import Any, Iterable, Sequence

from .enricher import LESSON, LESSON_KEY, STANDARDS, UNIT, UNIT_TITLE, standards_of

logger = logging.getLogger(__name__)

INDEX_FILENAME = "curriculum_index.json"
INDEX_VERSION = 1


def code_matches(left: str, right: str) -> bool:
    """Whether two CCSS codes denote the same standard.

    Course exports mix granularities — a lesson may cite the coarse ``3.MD.C``
    while the knowledge graph pins the finer ``3.MD.C.7.a`` — so a dotted
    prefix in either direction counts as a match. Comparison is anchored on the
    dot so that ``4.OA.B.1`` never matches ``4.OA.B.11``.
    """
    left, right = left.strip().upper(), right.strip().upper()
    if not left or not right:
        return False
    if left == right:
        return True
    return left.startswith(right + ".") or right.startswith(left + ".")


@dataclass
class CurriculumIndex:
    """Loaded sidecar: standards, lessons, and the chunks belonging to each."""

    lessons: dict[str, dict[str, Any]] = field(default_factory=dict)
    lesson_node_ids: dict[str, list[str]] = field(default_factory=dict)

    @property
    def standards(self) -> list[str]:
        seen: set[str] = set()
        for meta in self.lessons.values():
            seen.update(meta.get("standards", []))
        return sorted(seen)

    def lessons_for_standard(self, standard_code: str) -> list[str]:
        """Lesson keys whose *addressing* standards match ``standard_code``."""
        code = (standard_code or "").strip()
        if not code:
            return []
        return sorted(
            key
            for key, meta in self.lessons.items()
            if any(code_matches(known, code) for known in meta.get("standards", []))
        )

    def node_ids_for_lessons(self, lesson_keys: Iterable[str]) -> set[str]:
        allowed: set[str] = set()
        for key in lesson_keys:
            allowed.update(self.lesson_node_ids.get(key, []))
        return allowed

    def describe_lesson(self, lesson_key: str) -> dict[str, Any] | None:
        meta = self.lessons.get(lesson_key)
        if meta is None:
            return None
        return {"lesson_key": lesson_key, **meta}

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": INDEX_VERSION,
            "lessons": self.lessons,
            "lesson_node_ids": self.lesson_node_ids,
        }


def build_from_nodes(nodes: Sequence[Any]) -> CurriculumIndex:
    """Derive the sidecar from nodes already stamped by the enricher."""
    lessons: dict[str, dict[str, Any]] = {}
    lesson_node_ids: dict[str, list[str]] = {}

    for node in nodes:
        metadata = getattr(node, "metadata", None) or {}
        lesson_key = metadata.get(LESSON_KEY)
        if not lesson_key:
            continue

        entry = lessons.setdefault(
            lesson_key,
            {
                "unit": metadata.get(UNIT),
                "lesson": metadata.get(LESSON),
                "unit_title": metadata.get(UNIT_TITLE),
                "standards": [],
            },
        )
        merged = set(entry["standards"]) | set(standards_of(node, STANDARDS))
        entry["standards"] = sorted(merged)

        node_id = getattr(node, "node_id", None) or getattr(node, "id_", None)
        if node_id:
            lesson_node_ids.setdefault(lesson_key, []).append(str(node_id))

    return CurriculumIndex(lessons=lessons, lesson_node_ids=lesson_node_ids)


def persist(index: CurriculumIndex, storage_dir: Path) -> bool:
    """Write the sidecar next to the vector index.

    Returns False (without raising) when there is nothing to record, so a
    non-curriculum knowledge base simply has no sidecar file.
    """
    if not index.lessons:
        return False
    storage_dir.mkdir(parents=True, exist_ok=True)
    target = storage_dir / INDEX_FILENAME
    target.write_text(json.dumps(index.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info(
        "Persisted curriculum index: %d lessons, %d standards -> %s",
        len(index.lessons),
        len(index.standards),
        target,
    )
    return True


def load(storage_dir: Path) -> CurriculumIndex | None:
    """Load the sidecar, or None when this knowledge base has none."""
    target = Path(storage_dir) / INDEX_FILENAME
    if not target.exists():
        return None
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("Ignoring unreadable curriculum index at %s: %s", target, exc)
        return None
    if payload.get("version") != INDEX_VERSION:
        logger.warning(
            "Ignoring curriculum index at %s: version %s is not the expected %s",
            target,
            payload.get("version"),
            INDEX_VERSION,
        )
        return None
    return CurriculumIndex(
        lessons=payload.get("lessons") or {},
        lesson_node_ids=payload.get("lesson_node_ids") or {},
    )


__all__ = [
    "CurriculumIndex",
    "INDEX_FILENAME",
    "INDEX_VERSION",
    "build_from_nodes",
    "code_matches",
    "load",
    "persist",
]
