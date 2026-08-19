"""Tests for the curriculum standard <-> lesson content bridge."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from llama_index.core.schema import Document, TextNode
import pytest

from deeptutor.services.rag.curriculum import standard_index
from deeptutor.services.rag.curriculum.enricher import (
    CURRICULUM_METADATA_KEYS,
    LESSON_KEY,
    STANDARDS,
    CurriculumLessonEnricher,
    standards_of,
)
from deeptutor.services.rag.curriculum.lesson_markers import (
    extract_standards,
    merge_segments,
    segment_by_lesson,
)
from deeptutor.services.rag.pipelines.llamaindex import storage

COURSE_TEXT = """# Grade 4, Unit 1: Factors and Multiples

## Lesson 1 — Preparation

**[Grade 4 · Unit 1: Factors and Multiples · Lesson 1]**

CCSS Standards

Building On

3.MD.C
3.MD.C.7.a

Addressing

4.OA.B.4

Building Towards

4.OA.B.4

Lesson Timeline

**[Grade 4 · Unit 1: Factors and Multiples · Lesson 1]**

Warm-up: find the factors of 24.

## Lesson 2 — Preparation

**[Grade 4 · Unit 2: Fractions · Lesson 2]**

CCSS Standards

Addressing

4.NF.B.3

Compare fractions with unlike denominators.
"""

PLAIN_TEXT = "A competition problem set with no curriculum markers at all.\n\nProblem 1: ...\n"


# ---- marker parsing -------------------------------------------------------


def test_segments_split_on_lesson_change_not_on_every_marker():
    segments = merge_segments(segment_by_lesson(COURSE_TEXT))
    assert [(s.unit, s.lesson) for s in segments] == [(1, 1), (2, 2)]
    assert segments[0].lesson_key == "U1L1"
    # The repeated marker inside lesson 1 must not start a new segment.
    assert "Warm-up: find the factors of 24." in segments[0].text


def test_repeated_markers_within_one_lesson_do_not_start_new_segments():
    # COURSE_TEXT carries three markers but only two lessons. Tested on the
    # unmerged entry point on purpose: merge_segments would otherwise mask a
    # boundary bug by stitching the fragments back together downstream.
    raw = segment_by_lesson(COURSE_TEXT)
    assert [(s.unit, s.lesson) for s in raw] == [(1, 1), (2, 2)]


def test_standards_are_bucketed_by_ccss_heading():
    segments = merge_segments(segment_by_lesson(COURSE_TEXT))
    first = segments[0]
    assert first.addressing == ["4.OA.B.4"]
    assert first.building_on == ["3.MD.C", "3.MD.C.7.a"]
    assert first.building_towards == ["4.OA.B.4"]


def test_corpus_without_markers_yields_no_segments():
    assert segment_by_lesson(PLAIN_TEXT) == []


def test_prose_terminates_a_standards_block():
    # "Compare fractions..." must not be mistaken for a code, and no bucket
    # may absorb text that follows the block.
    found = extract_standards(COURSE_TEXT)
    assert "Compare fractions with unlike denominators." not in found["addressing"]
    assert set(found["addressing"]) == {"4.OA.B.4", "4.NF.B.3"}


def test_lesson_key_is_content_derived_and_stable():
    first = merge_segments(segment_by_lesson(COURSE_TEXT))[0]
    again = merge_segments(segment_by_lesson(COURSE_TEXT))[0]
    assert first.lesson_key == again.lesson_key == "U1L1"


# ---- enricher -------------------------------------------------------------


def test_enricher_splits_course_document_per_lesson():
    doc = Document(text=COURSE_TEXT, metadata={"file_name": "unit1.md"})
    out = CurriculumLessonEnricher()([doc])
    keys = [d.metadata.get(LESSON_KEY) for d in out]
    # One document per lesson, preceded by the unlabelled preamble.
    assert keys == [None, "U1L1", "U2L2"]
    # Pre-existing metadata survives on every emitted document.
    assert all(d.metadata["file_name"] == "unit1.md" for d in out)


def test_enricher_keeps_the_preamble_instead_of_dropping_it():
    """The block before the first marker carries the title and the licence.

    Dropping it silently removed the CC BY source attribution from every
    indexed course file — a real loss found in review, not a hypothetical.
    """
    doc = Document(text=COURSE_TEXT, metadata={"file_name": "unit1.md"})
    out = CurriculumLessonEnricher()([doc])

    assert "# Grade 4, Unit 1: Factors and Multiples" in out[0].get_content()
    # The preamble belongs to no lesson, so it must not claim one.
    assert LESSON_KEY not in out[0].metadata


def test_enricher_loses_no_characters_of_a_course_document():
    doc = Document(text=COURSE_TEXT)
    out = CurriculumLessonEnricher()([doc])
    assert sum(len(d.get_content()) for d in out) == len(COURSE_TEXT)


def test_split_preamble_passes_non_curriculum_text_through():
    from deeptutor.services.rag.curriculum.lesson_markers import split_preamble

    preamble, rest = split_preamble(PLAIN_TEXT)
    assert preamble == ""
    assert rest == PLAIN_TEXT


def test_enricher_excludes_its_keys_from_embedding_and_llm_text():
    doc = Document(text=COURSE_TEXT, metadata={"file_name": "unit1.md"})
    out = CurriculumLessonEnricher()([doc])
    lesson_docs = [d for d in out if d.metadata.get(LESSON_KEY)]
    assert lesson_docs
    for key in CURRICULUM_METADATA_KEYS:
        assert key in lesson_docs[0].excluded_embed_metadata_keys
        assert key in lesson_docs[0].excluded_llm_metadata_keys


def test_enricher_is_a_noop_for_non_curriculum_documents():
    doc = Document(text=PLAIN_TEXT, metadata={"file_name": "problems.md"})
    out = CurriculumLessonEnricher()([doc])
    assert out == [doc]
    assert not any(key in out[0].metadata for key in CURRICULUM_METADATA_KEYS)


def test_enricher_passes_through_non_documents():
    node = TextNode(text="already a chunk")
    assert CurriculumLessonEnricher()([node]) == [node]


# ---- sidecar index --------------------------------------------------------


def _enriched_nodes() -> list[TextNode]:
    docs = [
        d
        for d in CurriculumLessonEnricher()([Document(text=COURSE_TEXT)])
        if d.metadata.get(LESSON_KEY)
    ]
    return [
        TextNode(text=d.get_content(), metadata=dict(d.metadata), id_=f"n{i}")
        for i, d in enumerate(docs)
    ]


def test_sidecar_maps_standard_to_lessons():
    index = standard_index.build_from_nodes(_enriched_nodes())
    assert index.lessons_for_standard("4.OA.B.4") == ["U1L1"]
    assert index.lessons_for_standard("4.NF.B.3") == ["U2L2"]
    assert index.lessons_for_standard("9.ZZ.A.1") == []


def test_coarse_and_fine_codes_match_but_numeric_neighbours_do_not():
    assert standard_index.code_matches("3.MD.C.7.a", "3.MD.C")
    assert standard_index.code_matches("3.MD.C", "3.MD.C.7.a")
    # The dot anchor is what stops 4.OA.B.1 from swallowing 4.OA.B.11.
    assert not standard_index.code_matches("4.OA.B.1", "4.OA.B.11")
    assert not standard_index.code_matches("4.OA.B.11", "4.OA.B.1")


def test_sidecar_round_trips_through_disk(tmp_path: Path):
    built = standard_index.build_from_nodes(_enriched_nodes())
    assert standard_index.persist(built, tmp_path) is True
    loaded = standard_index.load(tmp_path)
    assert loaded is not None
    assert loaded.lessons_for_standard("4.OA.B.4") == ["U1L1"]
    assert loaded.node_ids_for_lessons(["U1L1"]) == {"n0"}


def test_no_sidecar_written_for_non_curriculum_corpus(tmp_path: Path):
    nodes = [TextNode(text="no markers", id_="x")]
    assert standard_index.persist(standard_index.build_from_nodes(nodes), tmp_path) is False
    assert not (tmp_path / standard_index.INDEX_FILENAME).exists()
    assert standard_index.load(tmp_path) is None


def test_future_sidecar_version_is_ignored_rather_than_misread(tmp_path: Path):
    (tmp_path / standard_index.INDEX_FILENAME).write_text(
        json.dumps({"version": standard_index.INDEX_VERSION + 1, "lessons": {"U1L1": {}}}),
        encoding="utf-8",
    )
    assert standard_index.load(tmp_path) is None


def test_corrupt_sidecar_does_not_raise(tmp_path: Path):
    (tmp_path / standard_index.INDEX_FILENAME).write_text("{not json", encoding="utf-8")
    assert standard_index.load(tmp_path) is None


def test_standards_of_reads_back_the_flattened_list():
    node = TextNode(text="x", metadata={STANDARDS: "4.OA.B.4,4.NBT.B.5"})
    assert standards_of(node) == ["4.OA.B.4", "4.NBT.B.5"]
    assert standards_of(TextNode(text="x")) == []


# ---- filtered retrieval ---------------------------------------------------


class _FakeScored:
    def __init__(self, node):
        self.node = node
        self.score = 1.0


class _FakeRetriever:
    def __init__(self, nodes):
        self._nodes = nodes
        self.requested_top_k: int | None = None

    def retrieve(self, _query):
        return [_FakeScored(n) for n in self._nodes]


def _install_fake_index(monkeypatch, nodes) -> dict:
    seen: dict = {}

    def fake_cached_index(_dir):
        return object()

    def fake_build_retriever(_index, _dir, *, top_k):
        seen["top_k"] = top_k
        return _FakeRetriever(nodes)

    monkeypatch.setattr(storage, "_cached_index", fake_cached_index)
    monkeypatch.setattr(storage.retrievers, "build_retriever", fake_build_retriever)
    return seen


def test_unscoped_retrieval_keeps_the_original_path(monkeypatch, tmp_path):
    nodes = [
        TextNode(text="a", metadata={LESSON_KEY: "U1L1"}),
        TextNode(text="b", metadata={LESSON_KEY: "U2L2"}),
    ]
    seen = _install_fake_index(monkeypatch, nodes)
    got = storage.retrieve_nodes(tmp_path, "q", top_k=2)
    assert len(got) == 2
    assert seen["top_k"] == 2  # no oversampling when nothing is filtered


def test_scoped_retrieval_drops_off_standard_chunks(monkeypatch, tmp_path):
    standard_index.persist(standard_index.build_from_nodes(_enriched_nodes()), tmp_path)
    nodes = [
        TextNode(text="a", metadata={LESSON_KEY: "U1L1"}),
        TextNode(text="b", metadata={LESSON_KEY: "U2L2"}),
    ]
    seen = _install_fake_index(monkeypatch, nodes)
    got = storage.retrieve_nodes(tmp_path, "q", top_k=5, standard_code="4.NF.B.3")
    assert [n.node.get_content() for n in got] == ["b"]
    assert seen["top_k"] >= 40  # oversampled because filtering discards


def test_scope_with_no_matching_lesson_returns_nothing(monkeypatch, tmp_path):
    standard_index.persist(standard_index.build_from_nodes(_enriched_nodes()), tmp_path)
    nodes = [TextNode(text="a", metadata={LESSON_KEY: "U1L1"})]
    _install_fake_index(monkeypatch, nodes)
    assert storage.retrieve_nodes(tmp_path, "q", standard_code="9.ZZ.A.1") == []


def test_missing_sidecar_falls_back_to_unscoped_retrieval(monkeypatch, tmp_path):
    nodes = [TextNode(text="a", metadata={LESSON_KEY: "U1L1"})]
    _install_fake_index(monkeypatch, nodes)
    got = storage.retrieve_nodes(tmp_path, "q", standard_code="4.OA.B.4")
    assert len(got) == 1


# ---- real corpus (skipped when the course export is absent) ---------------

RAW_DIR = Path.home() / "deeptutor-prod/data/knowledge_bases/im-g4-full/raw"


@pytest.mark.skipif(not RAW_DIR.exists(), reason="IM Grade 4 course export not present")
def test_real_corpus_parses_to_the_published_lesson_count():
    segments = []
    for path in sorted(RAW_DIR.glob("grade4-unit*.md")):
        segments.extend(segment_by_lesson(path.read_text(encoding="utf-8")))
    merged = merge_segments(segments)
    assert len(merged) == 149, f"expected 149 IM Grade 4 lessons, parsed {len(merged)}"
    with_standards = [s for s in merged if s.addressing]
    assert len(with_standards) == 146


# ---- deterministic passage order -----------------------------------------


class _FakeDocstore:
    def __init__(self, docs):
        self.docs = docs


class _FakeIndex:
    def __init__(self, docs):
        self.docstore = _FakeDocstore(docs)

    def insert_nodes(self, nodes):  # exercised by the insert_documents path
        for node in nodes:
            self.docstore.docs[node.node_id] = node


def test_lesson_passages_come_back_in_teaching_order(monkeypatch, tmp_path):
    """Docstore order is a build artefact; the tutor needs curriculum order."""
    lessons = {
        "U10L2": {"unit": 10, "lesson": 2, "unit_title": "t", "standards": ["4.OA.B.4"]},
        "U2L10": {"unit": 2, "lesson": 10, "unit_title": "t", "standards": ["4.OA.B.4"]},
        "U2L3": {"unit": 2, "lesson": 3, "unit_title": "t", "standards": ["4.OA.B.4"]},
    }
    index = standard_index.CurriculumIndex(
        lessons=lessons,
        lesson_node_ids={"U10L2": ["c"], "U2L10": ["b"], "U2L3": ["a"]},
    )
    standard_index.persist(index, tmp_path)

    # Deliberately shuffled relative to teaching order.
    docs = {
        "c": TextNode(text="unit 10 lesson 2", metadata={LESSON_KEY: "U10L2"}, id_="c"),
        "a": TextNode(text="unit 2 lesson 3", metadata={LESSON_KEY: "U2L3"}, id_="a"),
        "b": TextNode(text="unit 2 lesson 10", metadata={LESSON_KEY: "U2L10"}, id_="b"),
    }
    monkeypatch.setattr(storage, "_cached_index", lambda _dir: _FakeIndex(docs))

    got = storage.fetch_lesson_nodes(tmp_path, ["U10L2", "U2L10", "U2L3"], limit=10)
    assert [n.metadata[LESSON_KEY] for n in got] == ["U2L3", "U2L10", "U10L2"]
    # Lesson 10 must sort after lesson 3, not lexicographically before it.


def test_lesson_passage_limit_is_honoured(monkeypatch, tmp_path):
    index = standard_index.CurriculumIndex(
        lessons={"U1L1": {"unit": 1, "lesson": 1, "unit_title": "t", "standards": ["4.OA.B.4"]}},
        lesson_node_ids={"U1L1": ["a", "b", "c"]},
    )
    standard_index.persist(index, tmp_path)
    docs = {
        node_id: TextNode(text=node_id, metadata={LESSON_KEY: "U1L1"}, id_=node_id)
        for node_id in ("a", "b", "c")
    }
    monkeypatch.setattr(storage, "_cached_index", lambda _dir: _FakeIndex(docs))
    assert len(storage.fetch_lesson_nodes(tmp_path, ["U1L1"], limit=2)) == 2


def test_fetch_without_a_sidecar_returns_nothing(monkeypatch, tmp_path):
    monkeypatch.setattr(storage, "_cached_index", lambda _dir: _FakeIndex({}))
    assert storage.fetch_lesson_nodes(tmp_path, ["U1L1"]) == []


# ---- model-facing tool ----------------------------------------------------


def test_tool_exposes_no_query_parameter():
    """The whole point of a separate tool: it cannot be used as fuzzy search."""
    from deeptutor.tools.builtin import CurriculumLessonsTool

    definition = CurriculumLessonsTool().get_definition()
    names = {parameter.name for parameter in definition.parameters}
    assert names == {"standard_code", "kb_name"}
    assert "query" not in names


def test_tool_is_registered_and_mounts_with_a_knowledge_base():
    from deeptutor.agents._shared import tool_composition
    from deeptutor.tools.builtin import BUILTIN_TOOL_NAMES, CONFIGURABLE_BUILTIN_TOOL_NAMES

    assert "curriculum_lessons" in BUILTIN_TOOL_NAMES
    assert "curriculum_lessons" in CONFIGURABLE_BUILTIN_TOOL_NAMES
    assert tool_composition._CONDITIONAL_MOUNT_FLAGS["curriculum_lessons"] == "has_kb"


def test_tool_reports_an_uncovered_standard_instead_of_inventing_content(monkeypatch):
    import asyncio

    from deeptutor.tools import builtin as builtin_tools

    async def fake_lookup(**kwargs):
        return {
            "standard_code": kwargs["standard_code"],
            "lessons": [],
            "passages": [],
            "available": True,
            "reason": "No indexed lesson addresses standard '9.ZZ.A.1'.",
        }

    monkeypatch.setattr("deeptutor.tools.rag_tool.lookup_lessons_for_standard", fake_lookup)
    tool = builtin_tools.CurriculumLessonsTool()
    result = asyncio.run(tool.execute(standard_code="9.ZZ.A.1", kb_name="kb"))
    assert "No indexed lesson" in result.content


def test_tool_rejects_a_blank_standard_code():
    import asyncio

    from deeptutor.tools.builtin import CurriculumLessonsTool

    with pytest.raises(ValueError):
        asyncio.run(CurriculumLessonsTool().execute(standard_code="  ", kb_name="kb"))


def test_tool_prompt_hints_exist_in_both_languages():
    from deeptutor.tools.builtin import CurriculumLessonsTool

    tool = CurriculumLessonsTool()
    for language in ("en", "zh"):
        hints = tool.get_prompt_hints(language=language)
        assert hints is not None, f"missing {language} prompt hints"
        assert hints.short_description


# ---- honesty about whether a requested scope was actually applied ---------


def _pipeline_over(tmp_path, monkeypatch, nodes):
    """A LlamaIndexPipeline whose retrieval is stubbed to return ``nodes``."""
    from deeptutor.services.rag.pipelines.llamaindex import storage as storage_module
    from deeptutor.services.rag.pipelines.llamaindex.pipeline import LlamaIndexPipeline

    storage_dir = tmp_path / "kb" / "version-1"
    storage_dir.mkdir(parents=True, exist_ok=True)
    (storage_dir / "docstore.json").write_text("{}", encoding="utf-8")

    monkeypatch.setattr(LlamaIndexPipeline, "_configure_settings", lambda self: None)
    monkeypatch.setattr(
        storage_module,
        "retrieve_nodes",
        lambda storage_dir, query, top_k=5, **kwargs: nodes,
    )
    return LlamaIndexPipeline(
        kb_base_dir=str(tmp_path), signature_provider=lambda: None
    ), storage_dir


def test_scope_request_on_an_unaligned_kb_says_so_instead_of_pretending(tmp_path, monkeypatch):
    """Unscoped passages are acceptable; calling them the standard's material is not."""
    node = _FakeScored(TextNode(text="unrelated passage", metadata={}))
    pipeline, _ = _pipeline_over(tmp_path, monkeypatch, [node])

    result = asyncio.run(pipeline.search("anything", "kb", standard_code="4.NF.B.3"))

    assert result["standard_scope_applied"] is False
    assert "no curriculum alignment" in result["warning"]
    assert result["sources"]


def test_scope_request_on_an_aligned_kb_is_marked_applied(tmp_path, monkeypatch):
    node = _FakeScored(TextNode(text="lesson passage", metadata={LESSON_KEY: "U1L1"}))
    pipeline, storage_dir = _pipeline_over(tmp_path, monkeypatch, [node])
    standard_index.persist(standard_index.build_from_nodes(_enriched_nodes()), storage_dir)

    result = asyncio.run(pipeline.search("anything", "kb", standard_code="4.OA.B.4"))

    assert result["standard_scope_applied"] is True
    assert "warning" not in result or "no curriculum alignment" not in result.get("warning", "")


def test_empty_scoped_result_is_reported_as_uncovered_not_as_failure(tmp_path, monkeypatch):
    pipeline, storage_dir = _pipeline_over(tmp_path, monkeypatch, [])
    standard_index.persist(standard_index.build_from_nodes(_enriched_nodes()), storage_dir)

    result = asyncio.run(pipeline.search("anything", "kb", standard_code="4.OA.B.4"))

    assert result["sources"] == []
    assert result["standard_scope_applied"] is True
    assert "No indexed lesson content" in result["answer"]
    assert not result.get("error_type")


def test_is_curriculum_aware_distinguishes_absent_alignment_from_absent_match(tmp_path):
    assert storage.is_curriculum_aware(tmp_path) is False
    standard_index.persist(standard_index.build_from_nodes(_enriched_nodes()), tmp_path)
    assert storage.is_curriculum_aware(tmp_path) is True


EDU_DB = Path.home() / "Projects/deeptutor-education/data/education.db"


@pytest.mark.skipif(
    not RAW_DIR.exists() or not EDU_DB.exists(),
    reason="course export or education knowledge graph not present",
)
def test_every_grade4_graph_standard_is_taught_by_some_lesson():
    """The bridge is only worth anything if both ends actually meet.

    Checked in both directions on purpose: a one-way check passes happily while
    half the graph points at nothing. Grade 3 standards are prerequisites held
    in the graph but not taught by a Grade 4 course, and ``PS.*`` is a locally
    authored namespace outside CCSS — neither belongs in this corpus, so both
    are excluded rather than counted as gaps.
    """
    import sqlite3

    segments = []
    for path in sorted(RAW_DIR.glob("grade4-unit*.md")):
        segments.extend(segment_by_lesson(path.read_text(encoding="utf-8")))
    lessons = merge_segments(segments)

    corpus_codes = {code for lesson in lessons for code in lesson.addressing}

    connection = sqlite3.connect(EDU_DB)
    try:
        graph_codes = {
            row[0]
            for row in connection.execute(
                "SELECT DISTINCT standard_code FROM knowledge_nodes WHERE standard_code IS NOT NULL"
            )
        }
    finally:
        connection.close()

    grade4 = {code for code in graph_codes if code.startswith("4.")}
    assert grade4, "expected the knowledge graph to hold Grade 4 standards"

    def covered(code: str) -> bool:
        return any(standard_index.code_matches(code, known) for known in corpus_codes)

    unteachable = sorted(code for code in grade4 if not covered(code))
    assert not unteachable, f"graph standards no lesson teaches: {unteachable}"

    unmappable = sorted(
        code
        for code in corpus_codes
        if not any(standard_index.code_matches(known, code) for known in graph_codes)
    )
    assert not unmappable, f"lesson standards with no graph node: {unmappable}"


# ---- gaps found by adversarial review ------------------------------------


def test_create_index_actually_writes_the_sidecar(monkeypatch, tmp_path):
    """Covers the wiring, not just the parts.

    Review found that ``persist_curriculum_index`` could be replaced with
    ``return False`` and every other test still passed: each one exercised the
    sidecar helpers directly or through a monkeypatched retriever, so nothing
    checked that indexing a course *actually produces* a sidecar on disk.
    """
    nodes = _enriched_nodes()
    fake_index = _FakeIndex({node.node_id: node for node in nodes})

    monkeypatch.setattr(
        storage.ingestion,
        "create_index_from_documents",
        lambda documents, storage_dir, show_progress=True: (fake_index, len(documents)),
    )
    monkeypatch.setattr(storage.retrievers, "persist_bm25_retriever", lambda *a, **k: False)

    count = storage.create_index([Document(text=COURSE_TEXT)], tmp_path)

    assert count == 1
    sidecar = standard_index.load(tmp_path)
    assert sidecar is not None, "indexing a course must leave a curriculum sidecar"
    assert sidecar.lessons_for_standard("4.OA.B.4") == ["U1L1"]


def test_insert_documents_also_refreshes_the_sidecar(monkeypatch, tmp_path):
    nodes = _enriched_nodes()
    fake_index = _FakeIndex({node.node_id: node for node in nodes})
    fake_index.storage_context = type("_Ctx", (), {"persist": lambda self, persist_dir: None})()

    monkeypatch.setattr(storage.vector_store, "load_index", lambda _dir: fake_index)
    monkeypatch.setattr(storage, "_validate_persisted_embeddings", lambda *a, **k: None)
    monkeypatch.setattr(
        storage.ingestion,
        "insert_documents_into_index",
        lambda index, documents, show_progress=True: len(documents),
    )
    monkeypatch.setattr(storage.retrievers, "persist_bm25_retriever", lambda *a, **k: False)

    storage.insert_documents(tmp_path, tmp_path, [Document(text=COURSE_TEXT)])

    sidecar = standard_index.load(tmp_path)
    assert sidecar is not None
    assert set(sidecar.lessons) == {"U1L1", "U2L2"}


def test_ranking_truncation_falls_back_to_the_lesson_lookup(monkeypatch, tmp_path):
    """An over-fetch miss must not be reported as "nothing teaches this".

    The filter window is a heuristic; content that does address the standard can
    rank below it. The sidecar knows which passages those are, so returning them
    beats asserting the standard is uncovered.
    """
    nodes = _enriched_nodes()
    index = standard_index.build_from_nodes(nodes)
    standard_index.persist(index, tmp_path)

    docs = {node.node_id: node for node in nodes}
    monkeypatch.setattr(storage, "_cached_index", lambda _dir: _FakeIndex(docs))
    # Every ranked candidate belongs to a different lesson than the one asked for.
    monkeypatch.setattr(
        storage.retrievers,
        "build_retriever",
        lambda _index, _dir, *, top_k: _FakeRetriever(
            [TextNode(text="off-topic", metadata={LESSON_KEY: "U9L9"})]
        ),
    )

    got = storage.retrieve_nodes(tmp_path, "q", top_k=3, standard_code="4.OA.B.4")

    assert got, "must fall back to the deterministic lesson lookup"
    assert all(_lesson_key(node) == "U1L1" for node in got)
    assert all(node.score is None for node in got), "fallback results were never ranked"


def test_unknown_standard_still_returns_nothing_after_the_fallback(monkeypatch, tmp_path):
    standard_index.persist(standard_index.build_from_nodes(_enriched_nodes()), tmp_path)
    monkeypatch.setattr(storage, "_cached_index", lambda _dir: _FakeIndex({}))
    monkeypatch.setattr(
        storage.retrievers,
        "build_retriever",
        lambda _index, _dir, *, top_k: _FakeRetriever([]),
    )
    assert storage.retrieve_nodes(tmp_path, "q", standard_code="9.ZZ.A.1") == []


def _lesson_key(scored) -> str | None:
    node = getattr(scored, "node", scored)
    return (node.metadata or {}).get(LESSON_KEY)


def test_standard_codes_match_regardless_of_case_or_padding():
    """Codes arrive from a database, a URL or a model; casing is not guaranteed."""
    index = standard_index.build_from_nodes(_enriched_nodes())
    for variant in ("4.OA.B.4", "4.oa.b.4", "4.Oa.B.4", "  4.OA.B.4  "):
        assert index.lessons_for_standard(variant) == ["U1L1"], variant
    assert standard_index.code_matches("3.md.c.7.a", "3.MD.C")
    assert not standard_index.code_matches("", "4.OA.B.4")


@pytest.mark.skipif(not RAW_DIR.exists(), reason="IM Grade 4 course export not present")
def test_real_course_files_survive_enrichment_without_losing_a_character():
    for path in sorted(RAW_DIR.glob("grade4-unit*.md")):
        text = path.read_text(encoding="utf-8")
        out = CurriculumLessonEnricher()([Document(text=text)])
        assert sum(len(d.get_content()) for d in out) == len(text), path.name
