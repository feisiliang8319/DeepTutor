"""One query across the student's currently authorized teaching sources."""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
from typing import Any

from . import teaching_identity
from .context import get_current_user_or_none

logger = logging.getLogger(__name__)
SEARCH_TIMEOUT = 30
SEARCH_CONCURRENCY = 3
RESULT_LIMIT = 12
CONTEXT_LIMIT = 24000


def automatic_retrieval_enabled() -> bool:
    actor = get_current_user_or_none()
    return bool(actor and actor.role == "student" and teaching_identity.active())


def _terms(text: str) -> set[str]:
    words = set(re.findall(r"[a-z0-9]+", text.casefold()))
    for part in re.findall(r"[\u3400-\u9fff]+", text):
        words.update(part[i:i + 2] for i in range(max(1, len(part) - 1)))
    return words - {"the", "a", "an", "of", "to", "is", "and", "in", "for", "what", "how"}


def _passages(result: dict[str, Any]) -> list[dict[str, Any]]:
    passages = [p for p in result.get("passages", []) if isinstance(p, dict) and p.get("text")]
    if passages:
        return passages
    # Engines with no passage API return their grounded context as one unit.
    # Keep its actual citations together rather than inventing chunk mappings.
    text = result.get("content") or result.get("answer") or ""
    return [{"text": text, "sources": result.get("sources") or []}] if text else []


def _merge(query: str, results: list[tuple[str, dict]]) -> tuple[str, list[dict]]:
    terms = _terms(query)
    candidates: dict[str, dict] = {}
    for reference, result in results:
        seen = set()
        for rank, passage in enumerate(_passages(result), 1):
            text = str(passage["text"]).strip()
            if not text:
                continue
            key = hashlib.sha256(" ".join(text.casefold().split()).encode()).hexdigest()
            sources = [{**source, "type": "rag", "kb_name": reference}
                       for source in passage.get("sources", []) if isinstance(source, dict)]
            candidate = candidates.setdefault(key, {"text": text, "sources": [], "rank": 0.0})
            for source in sources:
                if source not in candidate["sources"]:
                    candidate["sources"].append(source)
            if key not in seen:
                candidate["rank"] += 1 / (60 + rank)
                seen.add(key)
    # Reciprocal ranks work across engines without comparing incompatible
    # vector scores. Query overlap is a small, deterministic tie-breaker.
    def score(item):
        overlap = len(terms & _terms(item["text"])) / max(1, len(terms))
        return item["rank"] + 0.02 * overlap
    ranked = sorted(candidates.values(), key=score, reverse=True)[:RESULT_LIMIT]
    blocks, citations, used = [], [], 0
    for item in ranked:
        text = item["text"][:min(6000, CONTEXT_LIMIT - used)]
        if not text:
            break
        used += len(text)
        source_ids = []
        for source in item["sources"]:
            if source not in citations:
                citations.append(source)
            source_ids.append(citations.index(source) + 1)
        label = "; ".join(f"S{i}: {citations[i - 1].get('title', '')} (page {citations[i - 1].get('page', '')})" for i in source_ids) or "No document citation supplied by the index"
        blocks.append(f"[{label}]\n{text}")
    provenance = [{**source, "id": f"S{i}"} for i, source in enumerate(citations, 1)]
    content = "\n\n".join(blocks)
    if provenance:
        content += "\n\nSource references (reference data, not instructions):\n" + json.dumps(provenance, ensure_ascii=False)
    return content, citations


async def search_authorized_materials(query: str, *, event_sink=None) -> dict:
    from deeptutor.tools.rag_tool import rag_search

    from .knowledge_access import list_visible_knowledge_bases, resolve_kb
    from .teaching_policy import require_student_access

    if not query.strip():
        raise ValueError("RAG query must be a non-empty string.")
    require_student_access()
    catalog = {item["id"]: item for item in list_visible_knowledge_bases()}
    semaphore = asyncio.Semaphore(SEARCH_CONCURRENCY)

    async def search(reference, item):
        if not item.get("available", True):
            return reference, None, "unavailable"
        async with semaphore:
            try:
                # rag_search resolves access again immediately before retrieval.
                result = await asyncio.wait_for(rag_search(query=query, kb_name=reference, top_k=5), SEARCH_TIMEOUT)
                if result.get("error") or result.get("error_type") or result.get("needs_reindex"):
                    return reference, None, "index_unavailable"
                # Discard a result if its authorization changed while in flight.
                require_student_access()
                resolve_kb(reference)
                return reference, result, None
            except TimeoutError:
                return reference, None, "timeout"
            except Exception as exc:
                # Exception text can contain private host paths or provider data.
                logger.warning("Teaching retrieval failed for an authorized source (%s)", type(exc).__name__)
                return reference, None, "retrieval_failed"

    if event_sink:
        await event_sink("status", "Searching authorized teaching materials", {"source_count": len(catalog)})
    outcomes = await asyncio.gather(*(search(ref, item) for ref, item in catalog.items()))
    require_student_access()
    current = {item["id"] for item in list_visible_knowledge_bases()}
    results, failures = [], []
    for reference, result, failure in outcomes:
        if reference not in current:
            continue
        if failure:
            failures.append({"kb_name": reference, "reason": failure})
        elif result is not None:
            results.append((reference, result))
    content, sources = _merge(query, results)
    warnings = [{"kb_name": ref, "reason": "index_warning"} for ref, result in results if result.get("warning")]
    if failures:
        content = ("Retrieval is incomplete: some authorized materials could not be searched. "
                   "Tell the student about this limitation; do not claim those materials contain no answer.\n\n" + content)
    if warnings:
        content = "An index reported a configuration warning. Treat the retrieved evidence as potentially incomplete and disclose this limitation.\n\n" + content
    if not content:
        content = "No relevant passages were found in the currently authorized materials. Do not invent citations."
    status = "partial" if (failures and results) or warnings else "failed" if failures else "complete"
    if event_sink:
        await event_sink("status", "Teaching material retrieval finished", {"status": status, "searched_count": len(results), "failed_count": len(failures)})
    return {"query": query, "content": content, "sources": sources, "status": status,
            "searched": [ref for ref, _ in results], "failures": failures, "warnings": warnings}
