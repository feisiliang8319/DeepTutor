"""Destructive-injection tests #5, #6, #7 and the P0-DESIGN.md §2.4
fail-closed rules not covered elsewhere: missing content_scope, RESTRICTED,
PRIVATE_INTERNAL export, CC-license-without-attribution, and paper_ref's
"no prompt/expected_answer text" invariant.
"""

from __future__ import annotations

import pytest

from deeptutor.education.domain.course import ContentScope
from deeptutor.education.storage.repositories import (
    AssessmentItemRepository,
    ExportDenied,
    ImportRejected,
    KnowledgeGraphRepository,
)
from deeptutor.education.tests.fixtures import (
    build_fixture_a_math,
    build_fixture_b_history,
    content_hash,
)


def _base_row(course_version_id: str, node_id: str, **overrides: object) -> dict[str, object]:
    row: dict[str, object] = {
        "id": "item-under-test",
        "course_version_id": course_version_id,
        "knowledge_node_id": node_id,
        "item_type": "short",
        "prompt": "2 + 2 = ?",
        "expected_answer": "4",
        "rubric_json": None,
        "difficulty": 1,
        "content_scope": "BUNDLED",
        "source_ref": None,
        "license_note": None,
        "attribution_text": None,
        "derived_from_item_id": None,
        "reviewer": None,
        "reviewed_at": None,
        "content_hash": content_hash("item-under-test"),
        "status": "candidate",
    }
    row.update(overrides)
    return row


def _import_one_node(conn, course_version_id: str) -> str:
    bundle = build_fixture_a_math(course_version_id)
    KnowledgeGraphRepository(conn).import_nodes_and_edges(
        course_version_id=course_version_id, nodes=bundle.nodes[:1], edges=[]
    )
    return bundle.nodes[0].id


# ---- test #5: missing content_scope ----------------------------------------


def test_missing_content_scope_rejects_whole_batch(conn, course_version):
    node_id = _import_one_node(conn, course_version.id)
    good_row = _base_row(course_version.id, node_id, id="item-good")
    bad_row = _base_row(course_version.id, node_id, id="item-bad")
    del bad_row["content_scope"]

    with pytest.raises(ImportRejected, match="content_scope"):
        AssessmentItemRepository(conn).import_items([good_row, bad_row])

    count = conn.execute("SELECT COUNT(*) AS n FROM assessment_items").fetchone()["n"]
    assert count == 0, "one bad row must reject the entire batch, including the otherwise-valid row"


def test_empty_string_content_scope_also_rejected(conn, course_version):
    node_id = _import_one_node(conn, course_version.id)
    row = _base_row(course_version.id, node_id, content_scope="")
    with pytest.raises(ImportRejected, match="content_scope"):
        AssessmentItemRepository(conn).import_items([row])


# ---- test #6: RESTRICTED content_scope -------------------------------------


def test_restricted_content_scope_rejected(conn, course_version):
    node_id = _import_one_node(conn, course_version.id)
    row = _base_row(course_version.id, node_id, content_scope="RESTRICTED")
    with pytest.raises(ImportRejected, match="RESTRICTED"):
        AssessmentItemRepository(conn).import_items([row])


# ---- test #7: exporting PRIVATE_INTERNAL is denied -------------------------


def test_export_private_internal_denied(conn, course_version):
    node_id = _import_one_node(conn, course_version.id)
    row = _base_row(course_version.id, node_id, content_scope="PRIVATE_INTERNAL")
    [item] = AssessmentItemRepository(conn).import_items([row])
    with pytest.raises(ExportDenied):
        AssessmentItemRepository(conn).export_items([item.id])


def test_export_reference_only_denied(conn, course_version):
    node_id = _import_one_node(conn, course_version.id)
    row = _base_row(
        course_version.id,
        node_id,
        item_type="paper_ref",
        content_scope="REFERENCE_ONLY",
        prompt=None,
        expected_answer=None,
        source_ref="BA-4A|p.37|#12",
    )
    [item] = AssessmentItemRepository(conn).import_items([row])
    with pytest.raises(ExportDenied):
        AssessmentItemRepository(conn).export_items([item.id])


def test_export_bundled_succeeds(conn, course_version):
    node_id = _import_one_node(conn, course_version.id)
    row = _base_row(course_version.id, node_id, content_scope="BUNDLED")
    [item] = AssessmentItemRepository(conn).import_items([row])
    [exported] = AssessmentItemRepository(conn).export_items([item.id])
    assert exported.id == item.id


def test_export_checks_every_item_before_returning_any(conn, course_version):
    """A batch export of [ok, forbidden] must deny the whole call, not
    silently hand back the one item that was fine."""
    node_id = _import_one_node(conn, course_version.id)
    ok_row = _base_row(course_version.id, node_id, id="item-ok", content_scope="BUNDLED")
    bad_row = _base_row(course_version.id, node_id, id="item-bad", content_scope="PRIVATE_INTERNAL")
    items = AssessmentItemRepository(conn).import_items([ok_row, bad_row])
    with pytest.raises(ExportDenied):
        AssessmentItemRepository(conn).export_items([i.id for i in items])


# ---- CC-license-without-attribution fail-closed rule -----------------------


def test_cc_licensed_bundled_item_without_attribution_rejected(conn, course_version):
    node_id = _import_one_node(conn, course_version.id)
    row = _base_row(
        course_version.id,
        node_id,
        content_scope="BUNDLED",
        license_note="CC BY-NC 4.0",
        attribution_text=None,
    )
    with pytest.raises(ImportRejected, match="attribution"):
        AssessmentItemRepository(conn).import_items([row])


def test_cc_licensed_bundled_item_with_attribution_accepted(conn, course_version):
    node_id = _import_one_node(conn, course_version.id)
    row = _base_row(
        course_version.id,
        node_id,
        content_scope="BUNDLED",
        license_note="CC BY-NC 4.0",
        attribution_text="Problem of the Week, CEMC, University of Waterloo",
    )
    [item] = AssessmentItemRepository(conn).import_items([row])
    assert item.attribution_text is not None


# ---- paper_ref invariants ---------------------------------------------------


def test_paper_ref_must_use_reference_only_scope(conn, course_version):
    node_id = _import_one_node(conn, course_version.id)
    row = _base_row(
        course_version.id,
        node_id,
        item_type="paper_ref",
        content_scope="BUNDLED",  # wrong on purpose
        prompt=None,
        expected_answer=None,
        source_ref="BA-4A|p.37|#12",
    )
    with pytest.raises(ImportRejected, match="REFERENCE_ONLY"):
        AssessmentItemRepository(conn).import_items([row])


def test_paper_ref_must_not_store_prompt_text(conn, course_version):
    node_id = _import_one_node(conn, course_version.id)
    row = _base_row(
        course_version.id,
        node_id,
        item_type="paper_ref",
        content_scope="REFERENCE_ONLY",
        prompt="What is 6 x 7?",  # forbidden — this is what makes it not a copy
        expected_answer=None,
        source_ref="BA-4A|p.37|#12",
    )
    with pytest.raises(ImportRejected, match="prompt"):
        AssessmentItemRepository(conn).import_items([row])


def test_paper_ref_reference_only_index_pointer_accepted(conn, course_version):
    node_id = _import_one_node(conn, course_version.id)
    row = _base_row(
        course_version.id,
        node_id,
        id="item-paper-ref",
        item_type="paper_ref",
        content_scope="REFERENCE_ONLY",
        prompt=None,
        expected_answer=None,
        source_ref="BA-4A|p.37|#12",
    )
    [item] = AssessmentItemRepository(conn).import_items([row])
    assert item.content_scope is ContentScope.REFERENCE_ONLY
    assert item.prompt is None
    assert item.source_ref == "BA-4A|p.37|#12"


# ---- third-party provenance gate ------------------------------------------
#
# The CC-licence check fires on what the row *claims* its licence is, so a
# mislabelled (or blank) licence used to carry third-party text past
# attribution entirely. These cover the provenance-based gate that closes it.


def test_third_party_source_without_licence_rejected(conn, course_version):
    """The exact bypass: relabel a CC item as something else, drop attribution."""
    node_id = _import_one_node(conn, course_version.id)
    row = _base_row(
        course_version.id,
        node_id,
        source_ref="CEMC POTW Problem A 2024-2025, p.9 — Delivery Dilemma",
        license_note="proprietary",
        attribution_text=None,
    )
    with pytest.raises(ImportRejected, match="third-party source_ref"):
        AssessmentItemRepository(conn).import_items([row])
    assert AssessmentItemRepository(conn).list_for_version(course_version.id) == []


def test_third_party_source_with_licence_but_no_attribution_rejected(conn, course_version):
    node_id = _import_one_node(conn, course_version.id)
    row = _base_row(
        course_version.id,
        node_id,
        source_ref="IM G4 U1 Lesson 2 — Activity 1",
        license_note="some-open-licence",
        attribution_text="   ",
    )
    with pytest.raises(ImportRejected, match="third-party source_ref"):
        AssessmentItemRepository(conn).import_items([row])


def test_third_party_source_with_licence_and_attribution_accepted(conn, course_version):
    node_id = _import_one_node(conn, course_version.id)
    row = _base_row(
        course_version.id,
        node_id,
        source_ref="CEMC POTW Problem A 2024-2025, p.9",
        license_note="CC BY-NC 4.0",
        attribution_text="© University of Waterloo (CEMC), CC BY-NC 4.0",
    )
    [item] = AssessmentItemRepository(conn).import_items([row])
    assert item.license_note == "CC BY-NC 4.0"


def test_self_authored_item_needs_no_licence(conn, course_version):
    """The escape hatch — and the reason it must be explicit rather than
    inferred from an empty source_ref: 'I wrote this' is a claim someone has
    to make, not a default."""
    node_id = _import_one_node(conn, course_version.id)
    row = _base_row(
        course_version.id,
        node_id,
        source_ref="self-authored (programmatic template)",
        license_note=None,
        attribution_text=None,
    )
    [item] = AssessmentItemRepository(conn).import_items([row])
    assert item.source_ref.startswith("self-authored")


# ---- test #18 (export half): Fixture A's items are all exportable ---------


def test_fixture_a_items_are_all_bundled_and_exportable(conn, course_version):
    bundle = build_fixture_a_math(course_version.id)
    KnowledgeGraphRepository(conn).import_nodes_and_edges(
        course_version_id=course_version.id, nodes=bundle.nodes, edges=bundle.edges
    )
    items = AssessmentItemRepository(conn).import_items(bundle.item_rows)
    exported = AssessmentItemRepository(conn).export_items([i.id for i in items])
    assert len(exported) == len(items)
    item_types = {i.item_type.value for i in items}
    assert {"choice", "short", "numeric", "visual_model"} <= item_types


def test_fixture_b_history_item_is_bundled_and_exportable(conn):
    import time

    from deeptutor.education.application import to_iso_timestamp
    from deeptutor.education.domain.course import Course, CourseVersion, CourseVersionStatus
    from deeptutor.education.storage.repositories import CourseRepository

    now = to_iso_timestamp(time.time())
    course = Course(id="course-history", subject_key="social_studies", title="Test History", created_at=now, level="G4")
    version = CourseVersion(
        id="cv-history-1",
        course_id=course.id,
        version="1.0.0",
        content_hash=content_hash("history-v1"),
        status=CourseVersionStatus.ACTIVE,
        created_at=now,
    )
    repo = CourseRepository(conn)
    repo.create_course(course)
    repo.create_course_version(version)

    bundle = build_fixture_b_history(version.id)
    KnowledgeGraphRepository(conn).import_nodes_and_edges(
        course_version_id=version.id, nodes=bundle.nodes, edges=bundle.edges
    )
    items = AssessmentItemRepository(conn).import_items(bundle.item_rows)
    exported = AssessmentItemRepository(conn).export_items([i.id for i in items])
    assert len(exported) == 1
