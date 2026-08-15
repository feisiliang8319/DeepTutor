"""教育层 → 主应用 LearningProgress 的投影。

最要紧的一条是**读回来比对**：`LearningProgress` 是 pydantic 且
``extra="ignore"``，upstream 一旦改字段名，我们写进去的旧字段会被静默丢弃，
页面表现为空白而不是报错。只断言"写成功"发现不了这种事，所以每条断言都走
``LearningStore.load()`` 读回后的对象。
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import time

import pytest

from deeptutor.education.application import to_iso_timestamp
from deeptutor.education.application.learning_progress_adapter import (
    UnmappedNodeType,
    build_progress,
    sync_learner,
)
from deeptutor.education.domain.course import KnowledgeNode
from deeptutor.education.domain.learner import LearnerProfile, MasterySnapshot, ReviewState
from deeptutor.education.storage.repositories import (
    KnowledgeGraphRepository,
    LearnerRepository,
    MasterySnapshotRepository,
    ReviewStateRepository,
)
from deeptutor.learning.models import KnowledgeType, LearningStage
from deeptutor.learning.storage import LearningStore

LEARNER = "learner-x"


@pytest.fixture
def graph(conn, course_version):
    now = to_iso_timestamp(time.time())
    LearnerRepository(conn).create(
        LearnerProfile(id=LEARNER, deep_tutor_user_id="dtu-x", display_name="Kid",
                       locale="en-US", created_at=now, updated_at=now)
    )
    nodes = [
        KnowledgeNode(id="n-fact", course_version_id=course_version.id, code="G3.OA.C7",
                      node_type="fact", title="乘法口算", sort_order=1, standard_code="3.OA.C.7"),
        KnowledgeNode(id="n-proc", course_version_id=course_version.id, code="G4.OA.B4.PAIRS",
                      node_type="procedure", title="找因数对", sort_order=2,
                      standard_code="4.OA.B.4"),
        KnowledgeNode(id="n-strat", course_version_id=course_version.id, code="G4.OA.A3.REASON",
                      node_type="strategy", title="估算判断合理性", sort_order=3,
                      standard_code="4.OA.A.3"),
    ]
    KnowledgeGraphRepository(conn).import_nodes_and_edges(
        course_version_id=course_version.id, nodes=nodes, edges=[]
    )
    return nodes


def snapshot(conn, node_id: str, score: float, status: str) -> None:
    MasterySnapshotRepository(conn).upsert(
        MasterySnapshot(
            learner_id=LEARNER, knowledge_node_id=node_id, score=score, status=status,
            policy_version="test", updated_at=to_iso_timestamp(time.time()),
        )
    )


def load_back(root: Path, book_id: str):
    return LearningStore(root=root).load(book_id)


# ---- 词表映射：显式表，不给默认值兜底 -------------------------------------


def test_node_types_map_across_two_different_vocabularies(conn, course_version, graph, tmp_path):
    snapshot(conn, "n-proc", 0.5, "learning")
    sync_learner(conn, learner_id=LEARNER, course_version_id=course_version.id,
                 learning_root=tmp_path, book_id="edu-test")
    p = load_back(tmp_path, "edu-test")
    assert p.knowledge_types["n-fact"] is KnowledgeType.MEMORY, "fact→memory 不能丢"
    assert p.knowledge_types["n-proc"] is KnowledgeType.PROCEDURE
    assert p.knowledge_types["n-strat"] is KnowledgeType.DESIGN, "strategy→design 不能丢"


def test_unknown_node_type_refuses_to_sync(conn, course_version, tmp_path):
    """宁可拒绝同步，也不要静默塞一个 concept —— 那会把语义悄悄改掉且无人报错。"""
    now = to_iso_timestamp(time.time())
    LearnerRepository(conn).create(
        LearnerProfile(id=LEARNER, deep_tutor_user_id="d", display_name="K",
                       locale="en-US", created_at=now, updated_at=now)
    )
    KnowledgeGraphRepository(conn).import_nodes_and_edges(
        course_version_id=course_version.id,
        nodes=[KnowledgeNode(id="n-weird", course_version_id=course_version.id, code="W",
                             node_type="habit", title="怪类型", sort_order=1,
                             standard_code="4.OA.B.4")],
        edges=[],
    )
    with pytest.raises(UnmappedNodeType, match="habit"):
        build_progress(conn, learner_id=LEARNER, course_version_id=course_version.id,
                       book_id="edu-test")


# ---- 掌握度与定性关 --------------------------------------------------------


def test_only_mastered_passes_the_qualitative_gate(conn, course_version, graph, tmp_path):
    snapshot(conn, "n-fact", 1.0, "mastered")
    snapshot(conn, "n-proc", 0.87, "learning")
    sync_learner(conn, learner_id=LEARNER, course_version_id=course_version.id,
                 learning_root=tmp_path, book_id="edu-test")
    p = load_back(tmp_path, "edu-test")
    assert p.mastery_levels == {"n-fact": 1.0, "n-proc": 0.87}
    assert p.qualitative_mastery["n-fact"] is True
    assert p.qualitative_mastery["n-proc"] is False, "0.87 分但没 mastered，不能算过关"
    assert "n-strat" not in p.mastery_levels, "没作答过的节点不该凭空出现分数"


def test_modules_group_by_standard_domain(conn, course_version, graph, tmp_path):
    sync_learner(conn, learner_id=LEARNER, course_version_id=course_version.id,
                 learning_root=tmp_path, book_id="edu-test")
    p = load_back(tmp_path, "edu-test")
    names = [m.name for m in p.modules]
    assert names == ["3.OA", "4.OA"], f"应按标准域分组并按 sort_order 排序，实得 {names}"
    assert [kp.id for m in p.modules for kp in m.knowledge_points] == ["n-fact", "n-proc", "n-strat"]


def test_modules_order_by_grade_not_by_seed_numbering(conn, course_version, tmp_path):
    """seed 的 sort_order 是各批内部编号，跨批不可比：4.OA 那批用 1–23、
    4.NBT 那批用 100+，照它排会把后补进第一批的 3.MD 前置排到 4.OA 之后。"""
    now = to_iso_timestamp(time.time())
    LearnerRepository(conn).create(
        LearnerProfile(id=LEARNER, deep_tutor_user_id="d", display_name="K",
                       locale="en-US", created_at=now, updated_at=now)
    )
    KnowledgeGraphRepository(conn).import_nodes_and_edges(
        course_version_id=course_version.id,
        nodes=[
            KnowledgeNode(id="a", course_version_id=course_version.id, code="A", node_type="concept",
                          title="四年级题", sort_order=1, standard_code="4.OA.B.4"),
            # 三年级前置，但在 seed 里是后来补的，编号更大
            KnowledgeNode(id="b", course_version_id=course_version.id, code="B", node_type="concept",
                          title="三年级面积", sort_order=23, standard_code="3.MD.C.7"),
            KnowledgeNode(id="c", course_version_id=course_version.id, code="C", node_type="fact",
                          title="四年级位值", sort_order=110, standard_code="4.NBT.A.1"),
        ],
        edges=[],
    )
    sync_learner(conn, learner_id=LEARNER, course_version_id=course_version.id,
                 learning_root=tmp_path, book_id="edu-test")
    p = load_back(tmp_path, "edu-test")
    assert [m.name for m in p.modules] == ["3.MD", "4.NBT", "4.OA"], \
        "三年级的域必须排在四年级前面，无论 seed 编号"


def test_current_module_points_at_the_first_unfinished_one(conn, course_version, graph, tmp_path):
    snapshot(conn, "n-fact", 1.0, "mastered")
    sync_learner(conn, learner_id=LEARNER, course_version_id=course_version.id,
                 learning_root=tmp_path, book_id="edu-test")
    p = load_back(tmp_path, "edu-test")
    assert p.current_module_id == "mod-4.OA", "3.OA 全掌握后应指向下一个未完成的域"
    assert p.current_stage is LearningStage.PRACTICE


# ---- 复习排程 --------------------------------------------------------------


def test_review_queue_carries_due_times_in_order(conn, course_version, graph, tmp_path):
    later = datetime(2026, 9, 1, tzinfo=timezone.utc)
    sooner = datetime(2026, 8, 20, tzinfo=timezone.utc)
    for node_id, due in (("n-fact", later), ("n-proc", sooner)):
        ReviewStateRepository(conn).upsert(
            ReviewState(learner_id=LEARNER, knowledge_node_id=node_id, stability=1.0,
                        difficulty=5.0, due_at=due.isoformat(), fsrs_params_ver="test")
        )
    sync_learner(conn, learner_id=LEARNER, course_version_id=course_version.id,
                 learning_root=tmp_path, book_id="edu-test")
    p = load_back(tmp_path, "edu-test")
    assert [t.knowledge_point_id for t in p.review_queue] == ["n-proc", "n-fact"], "该先复习的排前面"
    assert [t.priority for t in p.review_queue] == [0, 1]
    assert p.review_queue[0].due_at == sooner.timestamp()
    assert p.repetition_states["n-proc"].next_review_at == sooner.timestamp()
    # 没有对应量的字段留 0，不编造
    assert p.repetition_states["n-proc"].consecutive_correct == 0


def test_nodes_without_review_state_are_absent_not_zeroed(conn, course_version, graph, tmp_path):
    sync_learner(conn, learner_id=LEARNER, course_version_id=course_version.id,
                 learning_root=tmp_path, book_id="edu-test")
    p = load_back(tmp_path, "edu-test")
    assert p.repetition_states == {}
    assert p.review_queue == []


# ---- 重复同步与失败模式 ----------------------------------------------------


def test_resync_overwrites_rather_than_accumulates(conn, course_version, graph, tmp_path):
    sync_learner(conn, learner_id=LEARNER, course_version_id=course_version.id,
                 learning_root=tmp_path, book_id="edu-test")
    snapshot(conn, "n-proc", 1.0, "mastered")
    report = sync_learner(conn, learner_id=LEARNER, course_version_id=course_version.id,
                          learning_root=tmp_path, book_id="edu-test")
    p = load_back(tmp_path, "edu-test")
    assert p.qualitative_mastery["n-proc"] is True
    assert report.mastered == 1
    assert len(list(tmp_path.glob("*.json"))) == 1, "同一个 book_id 只应有一份文件"


def test_unknown_learner_is_rejected(conn, course_version, graph, tmp_path):
    with pytest.raises(ValueError, match="unknown learner_id"):
        sync_learner(conn, learner_id="nobody", course_version_id=course_version.id,
                     learning_root=tmp_path, book_id="edu-test")
