from datetime import datetime, timedelta, timezone

from deeptutor.education.application.learning_evidence import learning_evidence
from deeptutor.education.application.rebuild_mastery import compute_node_mastery
from deeptutor.education.application.record_attempt import NewAttemptInput, record_attempt
from deeptutor.education.storage import sqlite as db
from deeptutor.education.tests.test_web_loop import web_db, LEARNER


def add_third_item(conn):
    row = dict(conn.execute("SELECT * FROM assessment_items WHERE id='item-A-1'").fetchone())
    row['id'] = 'item-A-3'
    conn.execute(f"INSERT INTO assessment_items ({','.join(row)}) VALUES ({','.join('?' for _ in row)})", tuple(row.values()))


def answer(conn, item, value, moment):
    record_attempt(conn, NewAttemptInput(learner_id=LEARNER, assessment_item_id=item,
        response=value, started_at=moment.isoformat(), submitted_at=moment.isoformat(), source='test'))


def test_repeating_one_success_cannot_mask_two_failed_items(web_db):
    conn = db.open_database(web_db)
    add_third_item(conn)
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    answer(conn, 'item-A-1', 'wrong', start)
    answer(conn, 'item-A-2', 'wrong', start)
    for offset in range(7):
        answer(conn, 'item-A-3', '42', start + timedelta(minutes=offset+1))
    assert compute_node_mastery(conn, LEARNER, 'node-A').status == 'learning'
    evidence = learning_evidence(conn, LEARNER, 'node-A')
    assert evidence['distinct_correct_items'] == 1
    assert evidence['delayed_review'] == 'not_yet_observed'
    conn.close()


def test_same_day_success_and_delayed_success_remain_different_evidence(web_db):
    conn = db.open_database(web_db)
    add_third_item(conn)
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    for item in ['item-A-1','item-A-2','item-A-3']:
        answer(conn, item, '42', start)
    before = learning_evidence(conn, LEARNER, 'node-A')
    assert before['independent_practice'] == 'observed'
    assert before['delayed_correct_items'] == 0 and before['transfer'] == 'not_assessed'
    answer(conn, 'item-A-1', '42', start + timedelta(hours=47))
    assert learning_evidence(conn, LEARNER, 'node-A')['delayed_correct_items'] == 0
    answer(conn, 'item-A-1', '42', start + timedelta(hours=49))
    after = learning_evidence(conn, LEARNER, 'node-A')
    assert after['delayed_correct_items'] == 1 and after['transfer'] == 'not_assessed'
    answer(conn, 'item-A-1', 'wrong', start + timedelta(hours=50))
    assert learning_evidence(conn, LEARNER, 'node-A')['delayed_correct_items'] == 0
    conn.close()
