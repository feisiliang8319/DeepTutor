"""The authored sample reaches the existing ingestion and curriculum tool."""

import asyncio
import importlib
import json

from fastapi.testclient import TestClient
from llama_index.core import Document, Settings
from llama_index.core.embeddings import MockEmbedding
import pytest

from deeptutor.education.api.app import STATIC_DIR, create_app
from deeptutor.education.api.lesson_source import export_lesson_source
from deeptutor.education.tests.test_web_loop import web_db
from deeptutor.services.rag.curriculum import standard_index
from deeptutor.services.rag.curriculum.enricher import CurriculumLessonEnricher, LESSON_KEY
from deeptutor.services.rag.curriculum.lesson_markers import segment_by_lesson
from deeptutor.services.rag.pipelines.llamaindex import ingestion, storage
from deeptutor.services.rag.pipelines.llamaindex.document_loader import LlamaIndexDocumentLoader

URL = "/api/edu/lessons/number-structure/source"
KEY = "deeptutor-trial:number-structure"


def sample_source():
    meta = json.loads((STATIC_DIR / "lessons/curriculum_index.json").read_text())["lessons"]["number-structure"]
    return export_lesson_source("number-structure", meta,
                                (STATIC_DIR / "lessons/number-structure.html").read_text())


def test_source_keeps_math_hints_table_diagram_and_attribution(web_db):
    response = TestClient(create_app(web_db, content_mode="trial")).get(URL)
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/markdown")
    assert 'filename="deeptutor-trial-number-structure.md"' in response.headers["content-disposition"]
    for text in ["72 = 2³ × 3²", "| 8 | 8 | 24 | 72 |", "A 4 by 9 rectangle and a 6 by 6 square",
                 "Hint 1", "minimum perimeter 28", "https://www.edb.gov.hk/", "Source SHA-256:",
                 "pending human review", "Practice is optional"]:
        assert text in response.text
    assert "<style>" not in response.text and "color-scheme" not in response.text
    segment = segment_by_lesson(response.text)[0]
    assert segment.lesson_key == KEY and segment.addressing == ["4.OA.B.4"]


def test_source_respects_release_and_hash_gate(web_db, monkeypatch, tmp_path):
    assert TestClient(create_app(web_db, content_mode="production")).get(URL).status_code == 404
    api = importlib.import_module("deeptutor.education.api.app")
    target = tmp_path / "assets/lessons"
    target.mkdir(parents=True)
    (target / "curriculum_index.json").write_bytes((STATIC_DIR / "lessons/curriculum_index.json").read_bytes())
    (target / "number-structure.html").write_text("changed source")
    monkeypatch.setattr(api, "STATIC_DIR", target.parent)
    client = TestClient(create_app(web_db, content_mode="trial"))
    assert client.get(URL).status_code == 503
    assert client.get("/api/edu/lessons/unknown/source").status_code == 404
    assert client.get("/api/edu/lessons/%2e%2e/source").status_code == 404


def test_source_requires_native_session(web_db):
    from fastapi import HTTPException

    class DenyAccess:
        def authenticate(self, request):
            raise HTTPException(401, "not logged in")

    client = TestClient(create_app(web_db, content_mode="trial", account_access=DenyAccess()))
    assert client.get(URL).status_code == 401


def test_trial_identity_never_merges_with_existing_numbered_lessons():
    existing = "**[Grade 4 · Unit 1: Factors and Multiples · Lesson 1]**\n\nCCSS Standards\nAddressing\n4.OA.B.4\n\nExisting lesson.\n"
    nodes = CurriculumLessonEnricher()([Document(text=existing + sample_source())])
    keys = [node.metadata[LESSON_KEY] for node in nodes]
    assert keys == ["U1L1", KEY]
    assert "Existing lesson." not in nodes[1].text
    assert nodes[1].metadata["curriculum_content_status"] == "trial_pending_review"


def test_real_loader_index_reload_and_tool_return_sample(tmp_path, monkeypatch):
    """Only embeddings are synthetic; source, ingestion, persisted lookup and tool are real."""
    from deeptutor.services.rag.pipelines.llamaindex.pipeline import LlamaIndexPipeline
    from deeptutor.services.rag import service
    from deeptutor.tools.builtin import CurriculumLessonsTool

    path = tmp_path / "deeptutor-trial-number-structure.md"
    path.write_text(sample_source())
    documents = asyncio.run(LlamaIndexDocumentLoader().load([str(path)]))
    assert len(documents) == 1
    monkeypatch.setattr(Settings, "_embed_model", MockEmbedding(embed_dim=16))
    monkeypatch.setattr(Settings, "chunk_size", 384)
    monkeypatch.setattr(Settings, "chunk_overlap", 32)
    target = tmp_path / "sample-index"
    index, _ = ingestion.create_index_from_documents(documents, target, show_progress=False)
    assert storage.persist_curriculum_index(index, target)
    assert standard_index.load(target).lessons_for_standard("4.OA.B.4") == [KEY]
    passages = storage.fetch_lesson_nodes(target, [KEY], limit=40)
    assert len(passages) > 1
    assert "minimum perimeter 28" in "\n".join(node.text for node in passages)
    assert all(node.metadata["curriculum_content_status"] == "trial_pending_review" for node in passages)

    # Resolve only the isolated KB location/configuration, never a real user or model.
    pipeline_module = importlib.import_module("deeptutor.services.rag.pipelines.llamaindex.pipeline")
    monkeypatch.setattr(LlamaIndexPipeline, "_configure_settings", lambda self: None)
    monkeypatch.setattr(LlamaIndexPipeline, "_current_signature", lambda self: None)
    monkeypatch.setattr(pipeline_module, "resolve_kb_dir", lambda *args: tmp_path)
    monkeypatch.setattr(pipeline_module, "resolve_storage_dir_for_read", lambda *args: target)
    from deeptutor.multi_user import knowledge_access
    from types import SimpleNamespace
    monkeypatch.setattr(knowledge_access, "resolve_for_rag", lambda name: SimpleNamespace(base_dir=tmp_path, name="synthetic"))
    monkeypatch.setattr(service.RAGService, "_resolve_provider", lambda self, name: "llamaindex")
    result = asyncio.run(CurriculumLessonsTool().execute(standard_code="4.OA.B.4", kb_name="synthetic", limit=40))
    assert "trial_pending_review" in result.content and "minimum perimeter 28" in result.content
    assert result.metadata["lessons"] == [KEY]
    assert result.sources and result.sources[0]["url"] == "/api/edu/lessons/number-structure"
    search = asyncio.run(LlamaIndexPipeline(kb_base_dir=str(tmp_path)).search(
        query="factor pairs and completeness", kb_name="synthetic", standard_code="4.OA.B.4", top_k=3))
    assert search["sources"] and "Trial teaching material; pending human review" in search["content"]
    assert all(source["lesson_key"] == KEY and source["content_status"] == "trial_pending_review"
               for source in search["sources"])
    empty = asyncio.run(CurriculumLessonsTool().execute(standard_code="4.NF.B.3", kb_name="synthetic"))
    assert empty.metadata["passages"] == []


def test_curriculum_tool_keeps_existing_access_guard(monkeypatch):
    from deeptutor.multi_user import knowledge_access
    from deeptutor.tools.builtin import CurriculumLessonsTool
    monkeypatch.setattr(knowledge_access, "resolve_for_rag", lambda name: None)
    with pytest.raises(ValueError, match="not accessible"):
        asyncio.run(CurriculumLessonsTool().execute(standard_code="4.OA.B.4", kb_name="unassigned"))
