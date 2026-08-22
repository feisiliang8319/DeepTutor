"""投影快照的新鲜度判据。

这条判据存在的理由是一个真实缺陷：教育层的掌握度靠 launchd job 每 10 分钟
复制一份到学习库，job 停掉时快照只是**静止**，没有任何一层会报错，tutor 会
拿着任意旧的数据继续讲。下面每条断言对应一种当时会静默通过的输入。
"""

import pytest

from deeptutor.learning.freshness import (
    STALE_AFTER_SECONDS,
    is_projected,
    projection_staleness,
)

NOW = 1_800_000_000.0


def test_projected_books_are_identified_by_prefix():
    assert is_projected("edu-cv-hist-apworld-1.0.0") is True
    assert is_projected("edu-cv-ccss-g4-1.0.0") is True
    # tutor 自己写的书：不带前缀，永远不该被判过期
    assert is_projected("book_abc123") is False
    assert is_projected("") is False
    # 前缀必须在开头，不能是"名字里碰巧有 edu-"
    assert is_projected("my-edu-notes") is False


def test_fresh_projection_is_not_stale():
    # 刚同步完
    assert projection_staleness("edu-x", NOW, now=NOW) is None
    # 落后一个同步周期：属正常抖动，不该报
    assert projection_staleness("edu-x", NOW - 600, now=NOW) is None
    # 恰好卡在阈值上：不报（阈值是"超过"才算）
    assert projection_staleness("edu-x", NOW - STALE_AFTER_SECONDS, now=NOW) is None


def test_cold_projection_is_reported_with_age():
    stale = projection_staleness("edu-x", NOW - 3600, now=NOW)
    assert stale is not None
    assert stale.age_minutes == 60
    text = stale.message()
    # 消息必须让模型知道"可能过期"且"别断言学生没练过"——这正是缺陷的后果
    assert "60 minutes ago" in text
    assert "out of date" in text
    assert "not practised" in text


def test_self_written_books_never_go_stale():
    """学生一个月没学，不是数据问题，不该冒充数据问题。"""
    assert projection_staleness("book_abc123", NOW - 30 * 86400, now=NOW) is None


@pytest.mark.parametrize("bad", [None, "", "not-a-number", True, False])
def test_missing_or_bogus_timestamp_reports_nothing(bad):
    """缺时间戳不是"过期"的证据；猜一个比不报更糟。

    True/False 也在此列：bool 是 int 的子类，不排除的话 ``updated_at=True``
    会被当成 1970 年的时间戳，直接算出一个荒谬的"过期 28000000 分钟"。
    """
    assert projection_staleness("edu-x", bad, now=NOW) is None
