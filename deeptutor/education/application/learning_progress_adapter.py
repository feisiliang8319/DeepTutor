"""把教育层的掌握度投影成主应用能显示的 ``LearningProgress``。

方向是**单向的**：教育层 DB 是学业事实的唯一权威源，这里只把它渲染成
DeepTutor 学习页认识的形状，让孩子在主应用里就能看到进度，而不必再开一个
入口（2026-08-14 Sol 裁定的方案 2）。反向不成立——主应用那边的作答不回流，
它的判分路径已实证会泄题（08-13），不能作为学业证据。

三个刻意的取舍：

* **写用 upstream 自己的 ``LearningStore``**，不自己拼路径、不自己写文件。
  它带原子写、模块级 CAS 锁和 book_id 路径穿越校验；绕过它等于把这三样
  重新实现一遍。
* **node_type 的映射是显式表**，不做"猜一个差不多的"。教育层有
  fact/skill/strategy，DeepTutor 只有 memory/concept/procedure/design，
  两套词表不同源，靠默认值兜底会把语义悄悄改掉。
* **不编造 ``RepetitionState`` 里没有对应量的字段**。FSRS 的 stability /
  difficulty / reps 与它的 interval_index / consecutive_* 不是同一套模型，
  只有"下次该复习的时刻"是共通的，所以只填那个，其余留 0 并在此说明。

已知风险（配套回归见 tests/test_learning_progress_adapter.py）：
``LearningProgress`` 是 pydantic 且 ``extra="ignore"`` —— upstream 改字段名
时我们写的旧字段会被静默丢弃，页面表现为空白而不是报错。所以测试必须
"写完再用 ``LearningStore.load()`` 读回来逐字段比对"，不能只断言写成功。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import sqlite3

from deeptutor.education.storage.repositories import (
    KnowledgeGraphRepository,
    LearnerRepository,
    MasterySnapshotRepository,
    ReviewStateRepository,
)
from deeptutor.learning.models import (
    KnowledgePoint,
    KnowledgeType,
    LearningModule,
    LearningProgress,
    LearningStage,
    RepetitionState,
    ReviewTask,
)
from deeptutor.learning.storage import LearningStore

# 教育层的 node_type 词表 → DeepTutor 的 KnowledgeType。两套词表不同源，
# 缺项要显式补，不给默认值兜底。
NODE_TYPE_MAP: dict[str, KnowledgeType] = {
    "concept": KnowledgeType.CONCEPT,
    "procedure": KnowledgeType.PROCEDURE,
    "fact": KnowledgeType.MEMORY,
    "skill": KnowledgeType.PROCEDURE,
    "strategy": KnowledgeType.DESIGN,
}


class UnmappedNodeType(ValueError):
    """教育层出现了映射表里没有的 node_type。

    宁可拒绝同步也不要静默塞一个 CONCEPT：那会让主应用把一个策略题显示成
    概念题，而没有任何地方报错。
    """


@dataclass(frozen=True, slots=True)
class SyncReport:
    book_id: str
    modules: int
    knowledge_points: int
    mastered: int
    due_reviews: int
    path: Path


def _epoch(iso: str) -> float:
    dt = datetime.fromisoformat(iso)
    return (dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)).timestamp()


def _module_key(node) -> str:
    """按标准编码的域分组：4.OA.B.4 → 4.OA；没有编码的归到 'other'。

    教育层的图是扁平节点 + 前置边，没有"模块"这一层；而 DeepTutor 的进度页
    以模块为骨架。用标准域分组是唯一不需要额外人工输入、且对课程读者有意义
    的切法（一个域＝课标里的一章）。
    """
    code = node.standard_code or ""
    parts = code.split(".")
    return ".".join(parts[:2]) if len(parts) >= 2 else "other"


def build_progress(
    conn: sqlite3.Connection, *, learner_id: str, course_version_id: str, book_id: str
) -> LearningProgress:
    nodes = KnowledgeGraphRepository(conn).list_nodes(course_version_id)
    snapshots = {
        s.knowledge_node_id: s for s in MasterySnapshotRepository(conn).list_for_learner(learner_id)
    }

    grouped: dict[str, list] = {}
    for node in nodes:
        grouped.setdefault(_module_key(node), []).append(node)

    modules: list[LearningModule] = []
    knowledge_types: dict[str, KnowledgeType] = {}
    mastery_levels: dict[str, float] = {}
    qualitative: dict[str, bool] = {}

    def _domain_order(key: str) -> tuple:
        """按年级再按域名排，而不是按 seed 里的 sort_order。

        sort_order 是各批 seed 内部的编号（4.OA 用 1–23、4.NBT 用 100+），
        跨批之间没有可比性——照它排会把后补进 4.OA 那批的 3.MD 前置排到
        4.OA 后面，孩子看到的顺序就成了"先四年级再三年级"。
        """
        head = key.split(".")[0]
        return (int(head), key) if head.isdigit() else (99, key)

    for order, key in enumerate(sorted(grouped, key=_domain_order)):
        points = []
        for node in sorted(grouped[key], key=lambda n: n.sort_order):
            if node.node_type not in NODE_TYPE_MAP:
                raise UnmappedNodeType(
                    f"node {node.code!r} 的 node_type {node.node_type!r} 不在映射表里；"
                    f"补 NODE_TYPE_MAP 后再同步，不要让它默认成 concept"
                )
            ktype = NODE_TYPE_MAP[node.node_type]
            points.append(
                KnowledgePoint(id=node.id, name=node.title, type=ktype, module_id=f"mod-{key}")
            )
            knowledge_types[node.id] = ktype
            snap = snapshots.get(node.id)
            if snap is not None:
                mastery_levels[node.id] = round(snap.score, 4)
                # 只有真 mastered 才算过定性关；learning / pending_recompute 都不算。
                qualitative[node.id] = snap.status == "mastered"
        modules.append(
            LearningModule(id=f"mod-{key}", name=key, order=order, knowledge_points=points)
        )

    review_repo = ReviewStateRepository(conn)
    repetition: dict[str, RepetitionState] = {}
    queue: list[ReviewTask] = []
    for node in nodes:
        state = review_repo.get(learner_id, node.id)
        if state is None:
            continue
        due = _epoch(state.due_at)
        # interval_index / consecutive_* 在 FSRS 里没有对应量（那边是
        # stability/difficulty/reps），不编造，留 0。
        rep = RepetitionState(next_review_at=due)
        repetition[node.id] = rep
        queue.append(
            ReviewTask(
                id=f"rev-{node.id}",
                knowledge_point_id=node.id,
                knowledge_type=knowledge_types[node.id],
                due_at=due,
                # 越早该复习的排越前；用 due 的相对早晚做优先级，避免再引入
                # 一套主应用不认识的打分。
                priority=0,
                state=rep,
            )
        )
    queue.sort(key=lambda t: t.due_at)
    for index, task in enumerate(queue):
        task.priority = index

    first_unmastered = next(
        (m.id for m in modules
         if any(not qualitative.get(kp.id, False) for kp in m.knowledge_points)),
        modules[0].id if modules else "",
    )

    return LearningProgress(
        book_id=book_id,
        modules=modules,
        current_module_id=first_unmastered,
        # 教育层自己跑诊断/练习循环，这里只是投影；用 PRACTICE 表示"在练"，
        # 不用 DIAGNOSTIC（那会让主应用以为还没开始）。
        current_stage=LearningStage.PRACTICE,
        mastery_levels=mastery_levels,
        qualitative_mastery=qualitative,
        knowledge_types=knowledge_types,
        repetition_states=repetition,
        review_queue=queue,
    )


def sync_learner(
    conn: sqlite3.Connection,
    *,
    learner_id: str,
    course_version_id: str,
    learning_root: Path,
    book_id: str | None = None,
) -> SyncReport:
    """把一个学习者的进度写进指定的 learning 目录。

    ``learning_root`` 由调用方给出而不是从 path_service 取：主应用是多用户
    分域存储（``data/users/<uid>/user/workspace/learning``），而本进程不在
    那个用户的请求上下文里，让 path_service 猜会写错人。
    """
    if LearnerRepository(conn).get(learner_id) is None:
        raise ValueError(f"unknown learner_id {learner_id!r}")

    book = book_id or f"edu-{course_version_id}"
    progress = build_progress(
        conn, learner_id=learner_id, course_version_id=course_version_id, book_id=book
    )
    store = LearningStore(root=learning_root, education_projection_writer=True)
    store.save(progress)

    return SyncReport(
        book_id=book,
        modules=len(progress.modules),
        knowledge_points=sum(len(m.knowledge_points) for m in progress.modules),
        mastered=sum(1 for v in progress.qualitative_mastery.values() if v),
        due_reviews=len(progress.review_queue),
        path=learning_root / f"{book}.json",
    )


__all__ = [
    "NODE_TYPE_MAP",
    "SyncReport",
    "UnmappedNodeType",
    "build_progress",
    "sync_learner",
]
