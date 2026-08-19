"""Storage operations for the LlamaIndex RAG pipeline."""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
import json
import logging
from pathlib import Path
import re
import shutil
import threading
import time
from typing import Any

from deeptutor.services.embedding.validation import validate_embedding_batch
from deeptutor.services.rag.curriculum import standard_index as curriculum_index
from deeptutor.services.rag.index_versioning import (
    EmbeddingSignature,
    find_matching_version,
    resolve_storage_dir_for_read,
    resolve_storage_dir_for_write,
)

from . import ingestion, retrievers, vector_store

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AddStoragePlan:
    existing_storage: Path | None
    storage_dir: Path


def _storage_path_from_version_entry(entry: dict[str, Any]) -> Path | None:
    storage_path = entry.get("storage_path")
    if storage_path:
        return Path(str(storage_path))

    version_path = entry.get("version_path")
    if not version_path:
        return None

    path = Path(str(version_path))
    layout = str(entry.get("layout") or "")
    if layout == "nested_legacy":
        return path / "llamaindex_storage"
    return path


def cleanup_failed_version_dir(storage_dir: Path) -> bool:
    """Remove an empty flat version dir created by a failed indexing attempt."""
    if not storage_dir.is_dir() or not storage_dir.name.startswith("version-"):
        return False
    storage_empty = not any(child for child in storage_dir.iterdir() if child.name != "meta.json")
    meta_path = storage_dir / "meta.json"
    if storage_empty and not meta_path.exists():
        shutil.rmtree(storage_dir, ignore_errors=True)
        return True
    return False


def resolve_add_storage_plan(kb_dir: Path, signature: EmbeddingSignature | None) -> AddStoragePlan:
    """Choose existing/new storage dirs for incremental adds."""
    matching_version = find_matching_version(kb_dir, signature) if signature is not None else None
    existing_storage = (
        _storage_path_from_version_entry(matching_version) if matching_version else None
    )

    if matching_version and existing_storage and matching_version.get("layout") == "flat":
        return AddStoragePlan(existing_storage=existing_storage, storage_dir=existing_storage)

    if matching_version and existing_storage:
        return AddStoragePlan(
            existing_storage=existing_storage,
            storage_dir=resolve_storage_dir_for_write(kb_dir, signature),
        )

    fallback_storage = resolve_storage_dir_for_read(kb_dir, signature)
    existing_storage = fallback_storage
    fallback_is_flat = (
        fallback_storage is not None
        and fallback_storage.parent == kb_dir
        and fallback_storage.name.startswith("version-")
    )
    storage_dir = (
        fallback_storage if fallback_is_flat else resolve_storage_dir_for_write(kb_dir, signature)
    )
    return AddStoragePlan(existing_storage=existing_storage, storage_dir=storage_dir)


def persist_curriculum_index(index: Any, storage_dir: Path) -> bool:
    """Rebuild the curriculum sidecar from everything currently in the index.

    Derived from the persisted docstore rather than from the batch just
    ingested, so a knowledge base built up over several ``add_documents`` calls
    ends with one sidecar describing all of it. Absence of curriculum metadata
    simply yields no sidecar.
    """
    docstore = getattr(index, "docstore", None)
    docs = getattr(docstore, "docs", None)
    if not isinstance(docs, dict) or not docs:
        return False
    try:
        return curriculum_index.persist(
            curriculum_index.build_from_nodes(list(docs.values())), Path(storage_dir)
        )
    except Exception as exc:  # pragma: no cover - sidecar must never break indexing
        logger.warning("Failed to persist curriculum index in %s: %s", storage_dir, exc)
        return False


def create_index(documents: list[Any], storage_dir: Path, *, show_progress: bool = True) -> int:
    index, count = ingestion.create_index_from_documents(
        documents, storage_dir, show_progress=show_progress
    )
    retrievers.persist_bm25_retriever(index, storage_dir, top_k=20)
    persist_curriculum_index(index, storage_dir)
    return count


def insert_documents(existing_storage: Path, storage_dir: Path, documents: list[Any]) -> int:
    index = vector_store.load_index(existing_storage)
    _validate_persisted_embeddings(index, existing_storage)
    if hasattr(index, "insert_nodes"):
        count = ingestion.insert_documents_into_index(index, documents, show_progress=True)
    else:
        # Some tests use a tiny fake index that only implements insert().
        for document in documents:
            index.insert(document)
        count = len(documents)
    index.storage_context.persist(persist_dir=str(storage_dir))
    retrievers.persist_bm25_retriever(index, storage_dir, top_k=20)
    persist_curriculum_index(index, storage_dir)
    return count


def _validate_embedding_dict(embedding_dict: Any, *, label: str) -> None:
    if not isinstance(embedding_dict, dict) or not embedding_dict:
        return

    validate_embedding_batch(
        list(embedding_dict.values()),
        expected_count=len(embedding_dict),
        binding="llamaindex",
        model=f"persisted-index:{label}",
    )


def _iter_index_embedding_dicts(index: Any):
    """Yield embedding dictionaries exposed by loaded LlamaIndex vector stores."""
    seen: set[int] = set()

    def _yield_store(label: str, vector_store: Any):
        if vector_store is None:
            return
        store_id = id(vector_store)
        if store_id in seen:
            return
        seen.add(store_id)
        data = getattr(vector_store, "data", None)
        embedding_dict = getattr(data, "embedding_dict", None)
        if isinstance(embedding_dict, dict):
            yield label, embedding_dict

    yield from _yield_store("default", getattr(index, "vector_store", None))

    storage_context = getattr(index, "storage_context", None)
    vector_stores = getattr(storage_context, "vector_stores", None)
    if isinstance(vector_stores, dict):
        for namespace, vector_store in vector_stores.items():
            yield from _yield_store(str(namespace), vector_store)


def _embedding_dict_from_payload(payload: Any) -> Any:
    if not isinstance(payload, dict):
        return None
    if isinstance(payload.get("embedding_dict"), dict):
        return payload["embedding_dict"]
    data = payload.get("data")
    if isinstance(data, dict) and isinstance(data.get("embedding_dict"), dict):
        return data["embedding_dict"]
    return None


def _iter_file_embedding_dicts(storage_dir: Path):
    """Yield embedding dictionaries from persisted SimpleVectorStore JSON files.

    Binary FAISS indexes share the ``*vector_store.json`` filename but are not
    JSON, so they are skipped (their vectors are validated at index build time).
    """
    for path in sorted(storage_dir.glob("*vector_store.json")):
        try:
            with open(path, "rb") as probe:
                if probe.read(1)[:1] != b"{":
                    continue  # binary FAISS index, not a JSON vector store
            with open(path, encoding="utf-8") as handle:
                payload = json.load(handle)
        except Exception:
            continue
        embedding_dict = _embedding_dict_from_payload(payload)
        if isinstance(embedding_dict, dict):
            yield path.name, embedding_dict


def _validate_persisted_embeddings(index: Any, storage_dir: Path | None = None) -> None:
    """Fail early when a persisted vector store contains unusable vectors."""
    try:
        for label, embedding_dict in _iter_index_embedding_dicts(index):
            _validate_embedding_dict(embedding_dict, label=label)
        if storage_dir is not None:
            for label, embedding_dict in _iter_file_embedding_dicts(storage_dir):
                _validate_embedding_dict(embedding_dict, label=label)
    except ValueError as exc:
        raise ValueError(
            "RAG index contains invalid embedding vectors. Re-index the "
            "knowledge base with the current embedding provider/model before "
            f"querying it again. Details: {exc}"
        ) from exc


def validate_storage_embeddings(storage_dir: Path) -> None:
    """Validate persisted vector-store files without running a retrieval."""
    _validate_persisted_embeddings(None, storage_dir)


# Loaded indexes are cached per storage dir so repeated queries never re-read or
# re-validate the (potentially large) persisted store. Entries are keyed by a
# freshness token derived from the store files' mtimes, so a re-index or
# incremental insert naturally invalidates the stale entry.
@dataclass
class _CachedIndex:
    index: Any
    last_used: float


_INDEX_CACHE: "OrderedDict[tuple[str, tuple[int, ...]], _CachedIndex]" = OrderedDict()
_INDEX_CACHE_LOCK = threading.Lock()
_INDEX_CACHE_MAXSIZE = 2
_INDEX_CACHE_IDLE_SECONDS = 10 * 60


def _prune_index_cache_locked(now: float) -> None:
    stale = [
        key
        for key, entry in _INDEX_CACHE.items()
        if now - entry.last_used >= _INDEX_CACHE_IDLE_SECONDS
    ]
    for key in stale:
        _INDEX_CACHE.pop(key, None)


def _freshness_token(storage_dir: Path) -> tuple[int, ...]:
    token: list[int] = []
    for name in ("docstore.json", vector_store.DEFAULT_VECTOR_STORE_FILENAME):
        try:
            token.append((storage_dir / name).stat().st_mtime_ns)
        except OSError:
            token.append(0)
    return tuple(token)


def _load_validated_index(storage_dir: Path) -> Any:
    """Load an index once and validate its embeddings (cache-miss path)."""
    index = vector_store.load_index(storage_dir)
    _validate_persisted_embeddings(index, storage_dir)
    return index


def _cached_index(storage_dir: Path) -> Any:
    key = (str(storage_dir.resolve()), _freshness_token(storage_dir))
    now = time.monotonic()
    with _INDEX_CACHE_LOCK:
        _prune_index_cache_locked(now)
        entry = _INDEX_CACHE.get(key)
        if entry is not None:
            entry.last_used = now
            _INDEX_CACHE.move_to_end(key)
            return entry.index

    # Load outside the lock so a slow first load of one KB does not block other
    # KBs' queries. A concurrent duplicate load is harmless (idempotent).
    index = _load_validated_index(storage_dir)
    with _INDEX_CACHE_LOCK:
        # Drop any superseded entry for the same storage dir (older token).
        for stale in [existing for existing in _INDEX_CACHE if existing[0] == key[0]]:
            _INDEX_CACHE.pop(stale, None)
        _INDEX_CACHE[key] = _CachedIndex(index=index, last_used=time.monotonic())
        _INDEX_CACHE.move_to_end(key)
        while len(_INDEX_CACHE) > _INDEX_CACHE_MAXSIZE:
            _INDEX_CACHE.popitem(last=False)
    return index


def clear_index_cache() -> None:
    """Drop all cached indexes (used by tests and after destructive edits)."""
    with _INDEX_CACHE_LOCK:
        _INDEX_CACHE.clear()


def prune_index_cache() -> int:
    """Drop indexes idle past the single-user warm window."""
    with _INDEX_CACHE_LOCK:
        before = len(_INDEX_CACHE)
        _prune_index_cache_locked(time.monotonic())
        return before - len(_INDEX_CACHE)


# How many extra candidates to pull before a curriculum filter is applied.
# Neither FAISS nor BM25 can filter during retrieval, so scoping to a standard
# means over-fetching and discarding — this factor decides how deep to dig
# before giving up on filling top_k.
_FILTER_OVERSAMPLE = 8
_FILTER_MIN_CANDIDATES = 40


def _lesson_key_of(node: Any) -> str | None:
    """Read the lesson key off a retrieved node or its wrapper."""
    metadata = getattr(node, "metadata", None)
    if not isinstance(metadata, dict):
        inner = getattr(node, "node", None)
        metadata = getattr(inner, "metadata", None)
    if not isinstance(metadata, dict):
        return None
    value = metadata.get(curriculum_index.LESSON_KEY)
    return str(value) if value else None


def is_curriculum_aware(storage_dir: Path) -> bool:
    """Whether this index carries curriculum alignment at all.

    Distinguishes "no lesson teaches that standard" from "this knowledge base
    has no notion of standards", which callers must not conflate: the first is
    an answer, the second means a requested scope was never applied.
    """
    return curriculum_index.load(Path(storage_dir)) is not None


def resolve_lesson_keys(storage_dir: Path, standard_code: str) -> list[str]:
    """Lesson keys teaching ``standard_code``; empty when none or no sidecar."""
    sidecar = curriculum_index.load(Path(storage_dir))
    if sidecar is None:
        return []
    return sidecar.lessons_for_standard(standard_code)


def fetch_lesson_nodes(storage_dir: Path, lesson_keys: list[str], *, limit: int = 20) -> list[Any]:
    """Return a lesson's chunks directly, with no similarity search involved.

    Resolving "the learner is stuck on 4.NF.B.3" to the passages that teach it
    is a lookup, not a ranking problem; routing it through the retriever would
    reintroduce exactly the guesswork this bridge exists to remove.
    """
    if not lesson_keys:
        return []
    sidecar = curriculum_index.load(Path(storage_dir))
    if sidecar is None:
        return []
    allowed = sidecar.node_ids_for_lessons(lesson_keys)
    if not allowed:
        return []

    index = _cached_index(Path(storage_dir))
    docs = getattr(getattr(index, "docstore", None), "docs", None)
    if not isinstance(docs, dict):
        return []

    # Docstore order is an artefact of how the index was built, so passages are
    # re-ordered into teaching order — unit, then lesson, then the order the
    # chunks appear within that lesson. A truncated result is then the start of
    # the earliest relevant lesson rather than an arbitrary slice.
    ordering = {key: position for position, key in enumerate(lesson_keys)}
    selected = [
        (position, node)
        for position, (node_id, node) in enumerate(docs.items())
        if node_id in allowed
    ]
    selected.sort(
        key=lambda item: (
            _sort_key_for_lesson(_lesson_key_of(item[1]), ordering),
            item[0],
        )
    )
    return [node for _, node in selected[: max(1, int(limit))]]


def _sort_key_for_lesson(lesson_key: str | None, ordering: dict[str, int]) -> tuple[int, int, int]:
    """Order lessons by unit then lesson number, falling back to request order."""
    if not lesson_key:
        return (1, 0, 0)
    match = re.fullmatch(r"U(\d+)L(\d+)", lesson_key)
    if match:
        return (0, int(match.group(1)), int(match.group(2)))
    return (1, 0, ordering.get(lesson_key, 0))


def retrieve_nodes(
    storage_dir: Path,
    query: str,
    *,
    top_k: int = 5,
    standard_code: str | None = None,
    lesson_keys: list[str] | None = None,
) -> list[Any]:
    """Retrieve for ``query``, optionally scoped to one curriculum standard.

    Without a scope this is the original unfiltered path, byte for byte. With
    one, candidates are over-fetched and then filtered on chunk metadata, since
    the FAISS and BM25 backends accept no filters of their own.
    """
    storage_dir = Path(storage_dir)
    index = _cached_index(storage_dir)

    scope: set[str] = set(lesson_keys or [])
    curriculum_aware = False
    if standard_code:
        sidecar = curriculum_index.load(storage_dir)
        if sidecar is not None:
            # The knowledge base knows about standards, so the scope is
            # authoritative: an unknown code means "nothing here teaches it",
            # not "search everything". Widening here would hand back
            # off-standard passages under the label of a standard — the exact
            # guesswork this scoping exists to remove.
            curriculum_aware = True
            scope.update(sidecar.lessons_for_standard(standard_code))

    if not scope:
        if curriculum_aware:
            return []
        retriever = retrievers.build_retriever(index, storage_dir, top_k=top_k)
        return retriever.retrieve(query)

    candidates = max(top_k * _FILTER_OVERSAMPLE, _FILTER_MIN_CANDIDATES)
    retriever = retrievers.build_retriever(index, storage_dir, top_k=candidates)
    matched = [node for node in retriever.retrieve(query) if _lesson_key_of(node) in scope]
    if matched:
        return matched[:top_k]

    # The over-fetch window is a heuristic: content that genuinely teaches the
    # standard can rank below it and be filtered out, leaving nothing. Reporting
    # "no lesson covers this standard" would then be a false statement, because
    # the sidecar knows exactly which passages do. Fall back to that lookup —
    # scored as None, since these were not ranked against the query.
    from llama_index.core.schema import NodeWithScore

    fallback = fetch_lesson_nodes(storage_dir, sorted(scope), limit=top_k)
    return [NodeWithScore(node=node, score=None) for node in fallback]


def delete_kb_dir(kb_dir: Path) -> bool:
    if kb_dir.exists():
        shutil.rmtree(kb_dir)
        return True
    return False
