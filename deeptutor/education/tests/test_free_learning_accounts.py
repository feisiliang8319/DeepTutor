"""Account boundaries and optional learning, using only synthetic evidence."""
from concurrent.futures import ThreadPoolExecutor
import json
import threading
import time

from fastapi.testclient import TestClient
import pytest

from deeptutor.education.api.account_identity import NativeAccountAccess
from deeptutor.education.api.app import create_app
from deeptutor.education.application import to_iso_timestamp
from deeptutor.education.domain.learner import Enrollment, LearnerProfile
from deeptutor.education.storage import sqlite as db
from deeptutor.education.storage.repositories import EnrollmentRepository, LearnerRepository
from deeptutor.education.tests.test_web_loop import web_db, CV, LEARNER


@pytest.fixture
def accounts(web_db, monkeypatch):
    from deeptutor.services import auth

    monkeypatch.setattr(auth, 'AUTH_SECRET', 'synthetic-test-key-never-used-in-a-deployment')
    monkeypatch.setattr(auth, 'POCKETBASE_ENABLED', False)
    records = {
        'dtu-web': {'id': 'u_child', 'role': 'user'},
        'dtu-other': {'id': 'u_other', 'role': 'user'},
        'dtu-parent': {'id': 'u_parent', 'role': 'admin'},
        'unmapped': {'id': 'u_unmapped', 'role': 'user'},
    }
    tokens = {name: auth.create_token(name, value['role'], value['id']) for name, value in records.items()}
    now = to_iso_timestamp(time.time())
    conn = db.open_database(web_db)
    for identifier, username in [('learner-other', 'dtu-other'), ('parent-owner', 'dtu-parent')]:
        LearnerRepository(conn).create(LearnerProfile(id=identifier, deep_tutor_user_id=username,
            display_name='Synthetic account', locale='en-US', created_at=now, updated_at=now))
        EnrollmentRepository(conn).enroll(Enrollment(identifier, CV, 'active', now, now))
    item = dict(conn.execute("SELECT * FROM assessment_items WHERE id='item-A-1'").fetchone())
    item.update(id='item-B-1', knowledge_node_id='node-B', prompt='Synthetic optional topic problem')
    conn.execute('INSERT INTO assessment_items (' + ','.join(item) + ') VALUES (' + ','.join('?' for _ in item) + ')', tuple(item.values()))
    conn.commit()
    conn.close()
    access = NativeAccountAccess(decode=auth.decode_token, lookup=records.get)
    return records, tokens, access


@pytest.fixture
def account_client(web_db, accounts):
    return TestClient(create_app(web_db, content_mode='trial', account_access=accounts[2]))


def headers(accounts, name='dtu-web'):
    return {'Authorization': 'Bearer ' + accounts[1][name]}


def issue(client, accounts, topic='node-B'):
    return client.post('/api/edu/set', params={'learner_id':LEARNER, 'course_version_id':CV, 'topic_id':topic}, headers=headers(accounts))


def submission(batch):
    return {'learner_id':LEARNER, 'course_version_id':CV, 'set_id':batch['set_id'],
            'answers':[{'item_id':item['id'], 'response':'41'} for item in batch['items']]}


@pytest.mark.parametrize('path', ['/api/edu/people', '/api/edu/progress', '/api/edu/topics',
                                  '/api/edu/review-queue', '/api/edu/lessons/number-structure',
                                  '/api/edu/figures/diagnostic-ribbon-line-plot', '/openapi.json'])
def test_anonymous_and_spoofed_access_headers_cannot_read(account_client, path):
    response = account_client.get(path, headers={'Cf-Access-Authenticated-User-Email':'parent@example.invalid',
                                                 'Cf-Access-Jwt-Assertion':'fake'})
    assert response.status_code == 401
    assert response.headers['cache-control'] == 'no-store'


def test_page_uses_normal_account_login_and_profiles_are_account_bound(account_client, accounts):
    response = account_client.get('/practice', follow_redirects=False)
    assert response.status_code == 303 and response.headers['location'] == '/login?next=%2Fpractice'
    response = account_client.get('/api/edu/people?as=parent-owner', headers=headers(accounts))
    data = response.json()
    assert [p['id'] for p in data['people']] == [LEARNER]
    assert data['signed_in_profile_id'] == LEARNER
    assert response.headers['cache-control'] == 'private, no-store'
    assert account_client.get('/api/edu/people', headers=headers(accounts, 'unmapped')).status_code == 403


@pytest.mark.parametrize('path', ['courses','progress','lessons','readiness','topics'])
def test_student_cannot_read_another_learner(account_client, accounts, path):
    response = account_client.get('/api/edu/' + path, params={'learner_id':'learner-other','course_version_id':CV}, headers=headers(accounts))
    assert response.status_code == 403


def test_parent_review_permission_comes_from_account_not_profile(account_client, accounts):
    assert account_client.get('/api/edu/review-queue', params={'course_version_id':CV}, headers=headers(accounts)).status_code == 403
    assert account_client.get('/api/edu/review-queue', params={'course_version_id':CV}, headers=headers(accounts,'dtu-parent')).status_code == 200
    assert account_client.post('/api/edu/set', params={'learner_id':LEARNER,'course_version_id':CV}, headers=headers(accounts,'dtu-parent')).status_code == 403
    assert account_client.get('/api/edu/progress', params={'learner_id':LEARNER,'course_version_id':CV}, headers=headers(accounts,'dtu-parent')).status_code == 200


@pytest.mark.parametrize('path', ['set/recover','set/skip','set/submit'])
def test_account_cannot_write_a_sibling_record(account_client, accounts, path):
    payload={'learner_id':'learner-other','course_version_id':CV,'set_id':'not-owned'}
    if path.endswith('submit'):
        payload['answers']=[{'item_id':'item-A-1','response':'42'}]
    assert account_client.post('/api/edu/'+path,json=payload,headers=headers(accounts)).status_code == 403


def test_expired_disabled_or_wrong_user_id_session_is_rejected(account_client, accounts):
    from jose import jwt
    from deeptutor.services import auth
    expired=jwt.encode({'sub':'dtu-web','user_id':'u_child','exp':time.time()-5}, auth.AUTH_SECRET, algorithm='HS256')
    assert account_client.get('/api/edu/people',headers={'Authorization':'Bearer '+expired}).status_code == 401
    accounts[0]['dtu-web']['disabled']=True
    assert account_client.get('/api/edu/people',headers=headers(accounts)).status_code == 403
    accounts[0]['dtu-web']['disabled']=False
    accounts[0]['dtu-web']['id']='u_recreated'
    assert account_client.get('/api/edu/people',headers=headers(accounts)).status_code == 403


def test_cookie_writes_require_same_origin(account_client, accounts, monkeypatch):
    account_client.cookies.set('dt_token', accounts[1]['dtu-web'])
    query={'learner_id':LEARNER,'course_version_id':CV,'topic_id':'node-B'}
    assert account_client.post('/api/edu/set',params=query).status_code == 403
    assert account_client.post('/api/edu/set',params=query,headers={'Origin':'https://elsewhere.invalid'}).status_code == 403
    monkeypatch.setenv('EDU_PUBLIC_ORIGIN','https://mytutors.cc')
    assert account_client.post('/api/edu/set',params=query,headers={'Origin':'https://mytutors.cc'}).status_code == 200


def test_topic_choice_and_reading_never_require_prior_drilling(account_client, accounts, web_db):
    response=account_client.get('/api/edu/topics',params={'learner_id':LEARNER,'course_version_id':CV},headers=headers(accounts))
    assert response.status_code == 200 and response.json()['learning_mode'] == 'free'
    assert {t['id'] for t in response.json()['topics']} == {'node-A','node-B'}
    conn=db.open_database(web_db)
    assert conn.execute('SELECT count(*) FROM task_sets').fetchone()[0] == 0
    assert conn.execute('SELECT count(*) FROM mastery_snapshots').fetchone()[0] == 0
    conn.close()
    issued=issue(account_client,accounts).json()
    assert [i['id'] for i in issued['items']] == ['item-B-1']
    answered=account_client.post('/api/edu/set/submit',json=submission(issued),headers=headers(accounts))
    assert answered.status_code == 200 and answered.json()['summary']['correct'] == 0
    assert issue(account_client,accounts,'node-A').status_code == 200


def test_skipping_keeps_history_and_does_not_create_learning_evidence(account_client, accounts, web_db):
    issued=issue(account_client,accounts).json()
    payload={k:v for k,v in submission(issued).items() if k!='answers'}
    assert account_client.post('/api/edu/set/skip',json=payload,headers=headers(accounts)).status_code == 200
    assert account_client.post('/api/edu/set/submit',json=submission(issued),headers=headers(accounts)).status_code == 409
    next_set=issue(account_client,accounts,'node-A')
    assert next_set.status_code == 200 and next_set.json()['set_id'] != issued['set_id']
    conn=db.open_database(web_db)
    assert conn.execute('SELECT skipped_at FROM task_sets WHERE id=?',(issued['set_id'],)).fetchone()[0]
    for table in ('student_attempts','judgment_records','mastery_snapshots'):
        assert conn.execute('SELECT count(*) FROM '+table).fetchone()[0] == 0
    assert conn.execute('PRAGMA foreign_key_check').fetchall() == []
    conn.close()


def test_concurrent_skip_and_submit_have_one_winner(account_client, accounts, web_db):
    issued=issue(account_client,accounts).json()
    payload={k:v for k,v in submission(issued).items() if k!='answers'}
    with ThreadPoolExecutor(max_workers=2) as pool:
        skip=pool.submit(account_client.post,'/api/edu/set/skip',json=payload,headers=headers(accounts))
        submit=pool.submit(account_client.post,'/api/edu/set/submit',json=submission(issued),headers=headers(accounts))
        results=skip.result(),submit.result()
    assert sorted(r.status_code for r in results) == [200,409]
    conn=db.open_database(web_db)
    row=conn.execute('SELECT submitted_at,skipped_at FROM task_sets WHERE id=?',(issued['set_id'],)).fetchone()
    assert (row['submitted_at'] is None) != (row['skipped_at'] is None)
    assert conn.execute('SELECT count(*) FROM student_attempts').fetchone()[0] == (0 if row['skipped_at'] else 1)
    conn.close()


def test_native_access_cannot_start_with_application_auth_disabled(monkeypatch):
    from deeptutor.services import auth
    monkeypatch.setattr(auth,'AUTH_ENABLED',False)
    with pytest.raises(ValueError,match='requires application authentication'):
        NativeAccountAccess()


def test_pending_grading_does_not_lock_other_topics(account_client, accounts, web_db):
    issued=issue(account_client,accounts,'node-A').json()
    answers=submission(issued)['answers']
    now=to_iso_timestamp(time.time())
    conn=db.open_database(web_db)
    with db.transaction(conn):
        conn.execute('UPDATE task_sets SET submitted_at=? WHERE id=?',(now,issued['set_id']))
        conn.execute('INSERT INTO task_set_submissions(set_id,answers_json,received_at) VALUES(?,?,?)',
                     (issued['set_id'],json.dumps(answers),now))
    conn.close()
    topics=account_client.get('/api/edu/topics',params={'learner_id':LEARNER,'course_version_id':CV},headers=headers(accounts))
    assert topics.json()['pending_submission'] is True
    new_set=issue(account_client,accounts,'node-B')
    assert new_set.status_code == 200 and [i['id'] for i in new_set.json()['items']] == ['item-B-1']
    resumed=account_client.post('/api/edu/set',params={'learner_id':LEARNER,'course_version_id':CV},headers=headers(accounts))
    assert resumed.json()['pending_submission'] is True and resumed.json()['set_id'] == issued['set_id']


def test_concurrent_topic_selection_never_returns_the_wrong_topic(account_client, accounts, monkeypatch):
    from deeptutor.education.api import app as module
    original=module.select_next_item
    barrier=threading.Barrier(2)
    local=threading.local()
    def select_together(*args,**kwargs):
        if not getattr(local,'started',False):
            local.started=True
            barrier.wait(timeout=5)
        return original(*args,**kwargs)
    monkeypatch.setattr(module,'select_next_item',select_together)
    with ThreadPoolExecutor(max_workers=2) as pool:
        requests=[pool.submit(issue,account_client,accounts,topic) for topic in ('node-A','node-B')]
        responses=[r.result() for r in requests]
    assert sorted(r.status_code for r in responses)==[200,409]
    for letter,response in zip(('A','B'),responses):
        if response.status_code == 200:
            assert all(i['id'].startswith('item-'+letter+'-') for i in response.json()['items'])
        else:
            assert response.json()['detail']['open_set_id']


@pytest.mark.parametrize('path', ['/', '/practice'])
def test_admin_bookmark_opens_resource_management(account_client, accounts, path):
    response = account_client.get(path, headers=headers(accounts, 'dtu-parent'), follow_redirects=False)
    assert response.status_code == 303
    assert response.headers['location'] == '/admin'
    assert response.headers['cache-control'] == 'private, no-store'
    student = account_client.get(path, headers=headers(accounts), follow_redirects=False)
    assert student.status_code == 200
    assert 'studyView' in student.text


def test_changed_account_role_controls_education_entry(account_client, accounts):
    # The stored current role wins over a role embedded in an earlier login token.
    accounts[0]['dtu-parent']['role'] = 'user'
    response = account_client.get('/practice', headers=headers(accounts, 'dtu-parent'), follow_redirects=False)
    assert response.status_code == 200
