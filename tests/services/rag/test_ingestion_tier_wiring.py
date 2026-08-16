"""The three ingestion seams must take their LLM from the ingestion tier.

These are wiring tests on purpose. The cost regression they guard against is
invisible at runtime — indexing still works if a seam quietly falls back to the
interactive model, it just bills a frontier rate for bulk work. Only the import
graph shows the difference, so that is what gets asserted.
"""

import ast
import inspect
from pathlib import Path

import pytest

INGESTION_SEAMS = [
    ("deeptutor/services/rag/pipelines/llamaindex/document_loader.py", "_describe_image"),
    ("deeptutor/services/rag/pipelines/llamaindex/document_loader.py", "_load_image_nodes"),
    ("deeptutor/services/rag/pipelines/lightrag/config.py", "build_llm_model_func"),
    ("deeptutor/services/rag/pipelines/lightrag/config.py", "build_vision_model_func"),
]

REPO_ROOT = Path(__file__).resolve().parents[3]


def _function_source(rel_path: str, func_name: str) -> str:
    tree = ast.parse((REPO_ROOT / rel_path).read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncFunctionDef | ast.FunctionDef) and node.name == func_name:
            return ast.get_source_segment((REPO_ROOT / rel_path).read_text(encoding="utf-8"), node)
    raise AssertionError(f"{func_name} not found in {rel_path}")


@pytest.mark.parametrize(("rel_path", "func_name"), INGESTION_SEAMS)
def test_seam_uses_ingestion_tier(rel_path, func_name):
    source = _function_source(rel_path, func_name)
    assert "get_tier_llm_client(INGESTION)" in source, (
        f"{rel_path}:{func_name} must take its client from the ingestion tier; "
        "calling get_llm_client() here bills bulk indexing at the interactive rate"
    )


def test_no_ingestion_seam_still_imports_the_interactive_singleton():
    for rel_path in {path for path, _ in INGESTION_SEAMS}:
        text = (REPO_ROOT / rel_path).read_text(encoding="utf-8")
        assert "get_llm_client" not in text, (
            f"{rel_path} still references get_llm_client; the ingestion tier is bypassed"
        )


def test_graphrag_settings_resolve_through_the_tier():
    from deeptutor.services.rag.pipelines.graphrag import config as graphrag_config

    source = inspect.getsource(graphrag_config.build_settings)
    assert "resolve_tier_config(INGESTION)" in source
    assert "resolve_llm_runtime_config()" not in source
