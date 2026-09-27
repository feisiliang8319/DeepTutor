"""Reported learning-data defects, exercised with synthetic databases only."""
import json
import time

import pytest
from fastapi.testclient import TestClient

from deeptutor.education.api.app import create_app
from deeptutor.education.application import to_iso_timestamp
from deeptutor.education.application.record_attempt import NewAttemptInput, record_attempt
from deeptutor.education.application.rebuild_mastery import compute_node_mastery
from deeptutor.education.storage import sqlite as db
from deeptutor.education.tests.test_web_loop import web_db, LEARNER, CV
from deeptutor.learning.grading import grade_answer


@pytest.mark.parametrize('response,key,correct', [
    ('6 × 7 = 41', '6 × 7 = 42', False),
    ('3,000 + 400 + 7', '3,000 + 400 + 6', False),
    ('0.7 < 0.65', '0.7 > 0.65', False),
    ('>', '0.7 > 0.65', True), ('1/2', '4/8', True),
    ('3', '12/4 = 3', True), ('10', '10 times', True),
    ('0.5', '4/8', True), ('1/0', '4/8', False),
    ('41+1=99', '42', False), ('1,2', '12', False),
    ('__import__("os").system("id")', '42', False),
    ('10', '10 cm', False), ('10 m', '10 cm', False),
    ('2**1000000000', '42', False), ('nan', '42', False),
])
def test_mathematics_is_not_string_similarity(response, key, correct):
    assert grade_answer(response, key, 'short') is correct


def _submit(client, issue, response='42'):
    return client.post('/api/edu/set/submit', json={
        'learner_id': LEARNER, 'course_version_id': CV, 'set_id': issue['set_id'],
        'answers': [{'item_id': x['id'], 'response': response} for x in issue['items']],
    })


class CorrectJudge:
    def complete(self, system, user):
        return json.dumps({'verdict':'correct', 'confidence':0.99, 'rationale':'fixture'})


def test_resolved_judgment_drives_feedback_and_review_card(web_db):
    conn = db.open_database(web_db)
    conn.execute("UPDATE assessment_items SET item_type='multi_step'")
    conn.close()
    client = TestClient(create_app(web_db, content_mode="trial", judge=CorrectJudge()))
    issue = client.post('/api/edu/set', params={'learner_id':LEARNER,'course_version_id':CV}).json()
    result = _submit(client, issue).json()
    assert result['summary']['awaiting_review'] == 0
    assert result['summary']['correct'] == len(issue['items'])
    assert all(r['is_correct'] is True and r['review'] is not None for r in result['results'])
    conn = db.open_database(web_db)
    assert all(r[0] is None for r in conn.execute('SELECT is_correct FROM student_attempts'))
    conn.close()


def test_repetition_of_one_item_does_not_establish_mastery(web_db):
    conn = db.open_database(web_db)
    now = to_iso_timestamp(time.time())
    for i in range(3):
        record_attempt(conn, NewAttemptInput(learner_id=LEARNER,
            assessment_item_id='item-A-1', response='42', started_at=now,
            submitted_at=now, source='test', client_attempt_id=f'repeat-{i}'))
    assert compute_node_mastery(conn, LEARNER, 'node-A').status != 'mastered'
    conn.close()


def test_due_review_is_served_after_mastery(web_db):
    conn = db.open_database(web_db)
    now = to_iso_timestamp(time.time())
    record_attempt(conn, NewAttemptInput(learner_id=LEARNER,
        assessment_item_id='item-A-1', response='42', started_at=now,
        submitted_at=now, source='test'))
    conn.execute("UPDATE mastery_snapshots SET status='mastered'")
    conn.execute("UPDATE review_states SET due_at='2000-01-01T00:00:00+00:00'")
    conn.execute("DELETE FROM knowledge_edges")
    conn.execute("DELETE FROM knowledge_nodes WHERE id='node-B'")
    conn.close()
    client = TestClient(create_app(web_db, content_mode="trial"))
    result = client.post('/api/edu/set',params={'learner_id':LEARNER,'course_version_id':CV}).json()
    assert result['done'] is False
    assert result['items']


@pytest.mark.parametrize('fail_on', [1, 3, 5])
def test_entire_submission_survives_grading_interruption(web_db, monkeypatch, fail_on):
    import importlib
    api = importlib.import_module('deeptutor.education.api.app')
    conn = db.open_database(web_db)
    conn.execute("UPDATE assessment_items SET item_type='multi_step'")
    row = dict(conn.execute("SELECT * FROM assessment_items LIMIT 1").fetchone())
    for i in range(3):
        row['id'] = f'extra-{i}'
        conn.execute(f"INSERT INTO assessment_items ({','.join(row)}) VALUES ({','.join('?' for _ in row)})", tuple(row.values()))
    conn.close()
    client = TestClient(create_app(web_db, content_mode="trial", judge=CorrectJudge()))
    issue = client.post('/api/edu/set', params={'learner_id':LEARNER,'course_version_id':CV}).json()
    original = api.judge_open_response
    calls = 0

    def interrupt(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == fail_on:
            raise RuntimeError('synthetic worker interruption')
        return original(*args, **kwargs)

    monkeypatch.setattr(api, 'judge_open_response', interrupt)
    with pytest.raises(RuntimeError, match='synthetic worker interruption'):
        _submit(client, issue, 'original answer')
    conn = db.open_database(web_db)
    saved = conn.execute('SELECT answers_json FROM task_set_submissions').fetchone()
    assert len(json.loads(saved[0])) == 5
    conn.close()
    monkeypatch.setattr(api, 'judge_open_response', original)
    later = time.time() + 120
    monkeypatch.setattr(api.time, 'time', lambda: later)
    # New app instance models restart; malicious replacement replies are ignored.
    restarted = TestClient(create_app(web_db, content_mode="trial", judge=CorrectJudge()))
    pending = restarted.post('/api/edu/set', params={'learner_id': LEARNER, 'course_version_id': CV}).json()
    assert pending['pending_submission'] is True
    assert pending['set_id'] == issue['set_id']
    result = restarted.post('/api/edu/set/recover', json={
        'learner_id': LEARNER, 'course_version_id': CV, 'set_id': issue['set_id'],
    }).json()
    assert _submit(restarted, issue, 'changed answer').json()['results'] == result['results']
    assert len(result['results']) == 5
    assert all(r['your_response'] == 'original answer' for r in result['results'])
    conn = db.open_database(web_db)
    assert conn.execute('SELECT COUNT(*) FROM student_attempts').fetchone()[0] == 5
    conn.close()


def test_three_distinct_items_can_establish_mastery(web_db):
    conn = db.open_database(web_db)
    row = dict(conn.execute("SELECT * FROM assessment_items WHERE id='item-A-1'").fetchone())
    row['id'] = 'item-A-3'
    conn.execute(f"INSERT INTO assessment_items ({','.join(row)}) VALUES ({','.join('?' for _ in row)})", tuple(row.values()))
    now = to_iso_timestamp(time.time())
    for item_id in ['item-A-1', 'item-A-2', 'item-A-3']:
        record_attempt(conn, NewAttemptInput(learner_id=LEARNER,
            assessment_item_id=item_id, response='42', started_at=now,
            submitted_at=now, source='test'))
    assert compute_node_mastery(conn, LEARNER, 'node-A').status == 'mastered'
    conn.close()


def test_human_correction_replays_review_at_original_time(web_db):
    from deeptutor.education.application.rebuild_mastery import append_human_judgment_and_recompute
    from deeptutor.education.application.record_attempt import replay_review_state
    from deeptutor.education.domain.evidence import Verdict
    conn = db.open_database(web_db)
    then = '2026-01-01T12:00:00+00:00'
    record_attempt(conn, NewAttemptInput(learner_id=LEARNER,
        assessment_item_id='item-A-1', response='42', started_at=then,
        submitted_at=then, source='test', client_attempt_id='review-fixture'))
    append_human_judgment_and_recompute(conn, attempt_id='review-fixture',
        judge_ref='parent-fixture', verdict=Verdict.INCORRECT, confidence=1.0)
    replay = replay_review_state(conn, LEARNER, 'node-A')
    assert replay.matches
    assert replay.online.last_review_at == then
    assert conn.execute("SELECT is_correct FROM student_attempts").fetchone()[0] == 1
    append_human_judgment_and_recompute(conn, attempt_id='review-fixture',
        judge_ref='parent-fixture', verdict=Verdict.NEEDS_REVIEW, confidence=1.0)
    assert conn.execute('SELECT COUNT(*) FROM review_states').fetchone()[0] == 0
    conn.close()


def test_packaged_figures_render_and_missing_assets_fail_closed(web_db):
    client = TestClient(create_app(web_db, content_mode="trial"))
    conn = db.open_database(web_db)
    conn.execute("UPDATE assessment_items SET figure_spec_id='cemc-shape-sums'")
    conn.close()
    result = client.post('/api/edu/set',params={'learner_id':LEARNER,'course_version_id':CV})
    url = result.json()['items'][0]['figure_url']
    figure = client.get(url)
    assert figure.status_code == 200
    assert '<svg' in figure.text and 'xmlns=' in figure.text
    assert 'sandbox' in figure.headers['content-security-policy']
    assert client.get('/api/edu/figures/missing').status_code == 404
    conn = db.open_database(web_db)
    conn.execute("UPDATE assessment_items SET figure_spec_id='missing'")
    conn.close()
    assert client.post('/api/edu/set',params={'learner_id':LEARNER,'course_version_id':CV}).status_code == 503


def test_invalid_arithmetic_reference_cannot_pass_by_copying():
    assert grade_answer('6*7=41', '6*7=41', 'short') is False


def test_native_api_cannot_write_education_projection(tmp_path, monkeypatch):
    from fastapi import FastAPI
    from deeptutor.api.routers import mastery_path
    from deeptutor.learning.storage import LearningStore
    from deeptutor.learning.models import LearningProgress
    writer = LearningStore(root=tmp_path, education_projection_writer=True)
    writer.save(LearningProgress(book_id='edu-fixture'))
    monkeypatch.setattr(mastery_path, 'LearningStore', lambda: LearningStore(root=tmp_path))
    app = FastAPI()
    app.include_router(mastery_path.router)
    client = TestClient(app)
    prefix = mastery_path.router.prefix
    for method, suffix, body in [
        ('DELETE', '', None), ('POST', '/redo', None),
        ('POST', '/init-modules', {'modules':[]}),
        ('POST', '/import-from-book', {'chapters':[]}),
        ('POST', '/generate-from-notebook', {'notebook_id':'fixture', 'records':[]}),
    ]:
        r = client.request(method, prefix+'/progress/edu-fixture'+suffix, json=body)
        assert r.status_code == 409, r.text
    assert client.get(prefix+'/progress/edu-missing').status_code == 404
    assert client.get(prefix+'/progress/edu-fixture').status_code == 200
    assert writer.load('edu-fixture').version == 1


def test_repair_appends_correction_without_rewriting_original_evidence(web_db, monkeypatch):
    import importlib
    record = importlib.import_module('deeptutor.education.application.record_attempt')
    from deeptutor.education.application.repair_grades import repair_deterministic_evidence
    from deeptutor.education.storage.repositories import JudgmentRepository
    from deeptutor.education.domain.evidence import Verdict
    conn = db.open_database(web_db)
    conn.execute("UPDATE assessment_items SET item_type='short', expected_answer='6 × 7 = 42' WHERE id='item-A-1'")
    with monkeypatch.context() as m:
        m.setattr(record, '_grade', lambda item, answer: (True, 1.0))
        then = '2026-01-01T12:00:00+00:00'
        record_attempt(conn, NewAttemptInput(learner_id=LEARNER,
            assessment_item_id='item-A-1', response='6 × 7 = 41', started_at=then,
            submitted_at=then, source='old-grader-fixture', grader_version='p0-v1',
            client_attempt_id='historical-grade'))
    original = dict(conn.execute('SELECT * FROM student_attempts').fetchone())
    assert repair_deterministic_evidence(conn)['corrections'] == 1
    assert conn.execute('SELECT COUNT(*) FROM judgment_records').fetchone()[0] == 0
    report = repair_deterministic_evidence(conn, apply=True)
    assert report['corrections'] == 1 and report['derived_pairs_rebuilt'] == 1
    assert dict(conn.execute('SELECT * FROM student_attempts').fetchone()) == original
    assert JudgmentRepository(conn).latest_for_attempt('historical-grade').verdict is Verdict.INCORRECT
    assert repair_deterministic_evidence(conn, apply=True)['corrections'] == 0
    assert conn.execute('SELECT COUNT(*) FROM judgment_records').fetchone()[0] == 1
    assert compute_node_mastery(conn, LEARNER, 'node-A').score == 0
    from deeptutor.education.application.rebuild_mastery import append_human_judgment_and_recompute
    append_human_judgment_and_recompute(conn, attempt_id='historical-grade',
        judge_ref='parent-fixture', verdict=Verdict.CORRECT, confidence=1.0)
    assert repair_deterministic_evidence(conn, apply=True)['corrections'] == 0
    assert JudgmentRepository(conn).latest_for_attempt('historical-grade').verdict is Verdict.CORRECT
    conn.close()
