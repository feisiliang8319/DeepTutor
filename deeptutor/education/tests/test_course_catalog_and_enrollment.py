"""课程目录按 (学科 × 等级) 查询，学生靠 enrollment 挂载。

这条线的规矩（2026-08-15 Sol 定）：内容按学科和等级组织，学生只是挂上去，
加到第 10 个学生也不该动内容结构。所以这里既测"能按学科拉到课"，也测
"内容拉取不看学生是谁"——后者是容易悄悄退化的那一半。
"""

from __future__ import annotations

import time

import pytest

from deeptutor.education.application import to_iso_timestamp
from deeptutor.education.domain.course import Course, CourseVersion, CourseVersionStatus
from deeptutor.education.domain.learner import Enrollment, LearnerProfile
from deeptutor.education.storage.repositories import (
    CourseRepository,
    EnrollmentRepository,
    ImportRejected,
    LearnerRepository,
)

from .conftest import content_hash


def _now() -> str:
    return to_iso_timestamp(time.time())


def _make_course(conn, course_id: str, subject: str, level: str, cv_id: str) -> CourseVersion:
    now = _now()
    repo = CourseRepository(conn)
    repo.create_course(
        Course(id=course_id, subject_key=subject, title=f"{subject} {level}", created_at=now, level=level)
    )
    version = CourseVersion(
        id=cv_id,
        course_id=course_id,
        version="1.0.0",
        content_hash=content_hash(cv_id),
        status=CourseVersionStatus.ACTIVE,
        created_at=now,
    )
    repo.create_course_version(version)
    return version


def _make_learner(conn, learner_id: str) -> LearnerProfile:
    now = _now()
    profile = LearnerProfile(
        id=learner_id,
        deep_tutor_user_id=f"dtu-{learner_id}",
        display_name=learner_id,
        locale="en-US",
        created_at=now,
        updated_at=now,
    )
    LearnerRepository(conn).create(profile)
    return profile


def test_course_without_level_is_rejected(conn) -> None:
    """留空的课查不到，且这个后果要等到有人找不到它才暴露——所以写入就拦。"""
    with pytest.raises(ImportRejected, match="缺 level"):
        CourseRepository(conn).create_course(
            Course(id="c-nolevel", subject_key="mathematics", title="X", created_at=_now())
        )


def test_same_subject_different_levels_are_distinct_courses(conn) -> None:
    """subject_key 区分不了 G4 数学和 AP 数学——这正是加 level 的理由。"""
    _make_course(conn, "c-math-g4", "mathematics", "G4", "cv-math-g4")
    _make_course(conn, "c-math-ap", "mathematics", "AP-HS", "cv-math-ap")
    repo = CourseRepository(conn)

    assert [c.id for c in repo.find_courses(subject_key="mathematics")] == [
        "c-math-ap",
        "c-math-g4",
    ]
    assert [c.id for c in repo.find_courses(subject_key="mathematics", level="G4")] == ["c-math-g4"]
    assert repo.find_active_version(subject_key="mathematics", level="AP-HS").id == "cv-math-ap"
    assert repo.find_active_version(subject_key="mathematics", level="G13") is None


def test_catalog_lookup_is_identical_for_every_learner(conn) -> None:
    """内容拉取只由 (学科, 等级) 决定。三个学生拿到的是同一个课程版本。

    这条如果哪天失败，说明有人把 learner_id 塞进了目录查询——那就是把内容
    重新绑回了人。
    """
    version = _make_course(conn, "c-wh", "world_history", "AP-HS", "cv-wh")
    for lid in ("learner-a", "learner-b", "learner-c"):
        _make_learner(conn, lid)

    repo = CourseRepository(conn)
    resolved = {
        lid: repo.find_active_version(subject_key="world_history", level="AP-HS").id
        for lid in ("learner-a", "learner-b", "learner-c")
    }
    assert set(resolved.values()) == {version.id}


def test_enrollment_is_many_to_many_and_idempotent(conn) -> None:
    math = _make_course(conn, "c-m", "mathematics", "G4", "cv-m")
    hist = _make_course(conn, "c-h", "world_history", "AP-HS", "cv-h")
    _make_learner(conn, "learner-a")
    _make_learner(conn, "learner-b")
    repo = EnrollmentRepository(conn)
    now = _now()

    for lid, cv in (("learner-a", math.id), ("learner-a", hist.id), ("learner-b", hist.id)):
        repo.enroll(Enrollment(lid, cv, "active", now, now))
    # 重复选同一门课不该报错、不该插重复行
    repo.enroll(Enrollment("learner-a", math.id, "active", now, now))

    # 同一时刻选的课按 course_version_id 定序（enrolled_at 相同时的 tiebreak），
    # 不按插入顺序——排序必须是确定的，否则名册每次读出来次序都可能不同。
    assert [e.course_version_id for e in repo.list_for_learner("learner-a")] == sorted(
        [math.id, hist.id]
    )
    assert repo.list_learners(hist.id) == ["learner-a", "learner-b"]
    assert repo.list_learners(math.id) == ["learner-a"]
    assert repo.is_enrolled("learner-b", math.id) is False


def test_withdrawn_enrollment_disappears_from_roster_but_row_survives(conn) -> None:
    """退选是状态变更不是删行：作答记录还在，enrollment 行消失会让它们成为孤儿。"""
    math = _make_course(conn, "c-m", "mathematics", "G4", "cv-m")
    _make_learner(conn, "learner-a")
    repo = EnrollmentRepository(conn)
    now = _now()
    repo.enroll(Enrollment("learner-a", math.id, "active", now, now))

    repo.set_status("learner-a", math.id, "withdrawn", at=_now())

    assert repo.list_learners(math.id) == []
    assert repo.is_enrolled("learner-a", math.id) is False
    assert [e.status for e in repo.list_for_learner("learner-a", active_only=False)] == ["withdrawn"]


def test_adding_a_learner_does_not_touch_content_tables(conn) -> None:
    """加学生只加行。内容表的行数必须一动不动——这是整条主线的验收点。"""
    _make_course(conn, "c-m", "mathematics", "G4", "cv-m")
    counts_before = {
        t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        for t in ("courses", "course_versions", "knowledge_nodes", "assessment_items", "knowledge_edges")
    }

    now = _now()
    for lid in ("learner-x", "learner-y", "learner-z"):
        _make_learner(conn, lid)
        EnrollmentRepository(conn).enroll(Enrollment(lid, "cv-m", "active", now, now))

    counts_after = {
        t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in counts_before
    }
    assert counts_after == counts_before
