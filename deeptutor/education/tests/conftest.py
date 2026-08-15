from __future__ import annotations

import hashlib
from pathlib import Path
import time

import pytest

from deeptutor.education.application import to_iso_timestamp
from deeptutor.education.domain.course import Course, CourseVersion, CourseVersionStatus
from deeptutor.education.domain.learner import LearnerProfile
from deeptutor.education.storage import sqlite as edu_sqlite
from deeptutor.education.storage.repositories import CourseRepository, LearnerRepository


def content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "education.db"


@pytest.fixture
def conn(db_path: Path):
    connection = edu_sqlite.open_database(db_path)
    yield connection
    connection.close()


@pytest.fixture
def learner(conn) -> LearnerProfile:
    now = to_iso_timestamp(time.time())
    profile = LearnerProfile(
        id="learner-1",
        deep_tutor_user_id="dtu-1",
        display_name="Test Learner",
        locale="en-US",
        created_at=now,
        updated_at=now,
    )
    LearnerRepository(conn).create(profile)
    return profile


@pytest.fixture
def course_version(conn) -> CourseVersion:
    now = to_iso_timestamp(time.time())
    course = Course(id="course-math", subject_key="mathematics", title="Test Math", created_at=now)
    version = CourseVersion(
        id="cv-math-1",
        course_id=course.id,
        version="1.0.0",
        content_hash=content_hash("math-v1"),
        status=CourseVersionStatus.ACTIVE,
        created_at=now,
    )
    repo = CourseRepository(conn)
    repo.create_course(course)
    repo.create_course_version(version)
    return version
