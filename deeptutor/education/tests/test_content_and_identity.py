"""Admission, availability and real signed parent-identity regressions."""
import json
import time
from pathlib import Path

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from starlette.requests import Request

from deeptutor.education.api.app import create_app
from deeptutor.education.api.parent_identity import CloudflareParentIdentity
from deeptutor.education.application.content_readiness import course_readiness
from deeptutor.education.storage import sqlite as db
from deeptutor.education.tests.test_web_loop import (
    web_db, judge_free_db, _seed_pending_attempt, CV, LEARNER,
)


def test_production_never_issues_candidate_or_unreviewed_items(web_db):
    client = TestClient(create_app(web_db))
    query = {'learner_id': LEARNER, 'course_version_id': CV}
    assert client.post('/api/edu/set', params=query).json()['state'] == 'content_unavailable'
    conn = db.open_database(web_db)
    conn.execute("UPDATE assessment_items SET status='production'")
    assert client.post('/api/edu/set', params=query).json()['items'] == []
    conn.execute("UPDATE assessment_items SET reviewer='content-review-fixture', reviewed_at='2026-09-26T00:00:00+00:00', explanation='Fixture explanation', explanation_source='authored'")
    assert client.post('/api/edu/set', params=query).json()['items']
    conn.close()


def test_explicit_trial_reports_optional_content_without_prerequisite_locks(web_db):
    conn = db.open_database(web_db)
    result = course_readiness(conn, CV, content_mode='trial')
    assert result['practice_available_nodes'] == 1
    assert result['prerequisites_enforced'] is False
    assert result['gaps'][0]['servable_items'] == 0
    assert conn.execute('SELECT count(*) FROM mastery_snapshots').fetchone()[0] == 0
    conn.close()
    client = TestClient(create_app(web_db, content_mode='trial'))
    batch = client.post('/api/edu/set', params={'learner_id':LEARNER,'course_version_id':CV}).json()
    assert batch['content_mode'] == 'trial' and batch['items']


def test_profile_choice_cannot_authorize_review(web_db):
    client = TestClient(create_app(web_db, content_mode='trial'))
    assert client.get('/api/edu/review-queue', params={'course_version_id':CV}).status_code == 503
    response = client.post('/api/edu/review', json={'reviewer':'parent-owner','attempt_id':'anything','verdict':'correct'})
    assert response.status_code == 503
    conn = db.open_database(web_db)
    assert conn.execute('SELECT count(*) FROM judgment_records').fetchone()[0] == 0
    conn.close()


def test_lesson_is_linked_to_matching_course_and_hash_checked(web_db, monkeypatch):
    import importlib
    api = importlib.import_module('deeptutor.education.api.app')
    conn = db.open_database(web_db)
    conn.execute("UPDATE knowledge_nodes SET code='G4.OA.B4.FACTOR_PAIRS' WHERE id='node-A'")
    conn.close()
    client = TestClient(create_app(web_db, content_mode='trial'))
    query = {'learner_id':LEARNER,'course_version_id':CV}
    entries = client.get('/api/edu/lessons', params=query).json()['lessons']
    assert [e['id'] for e in entries] == ['number-structure']
    page = client.get(entries[0]['url'])
    assert page.status_code == 200 and '<svg' in page.text and '<table' in page.text
    assert "default-src 'none'" in page.headers['content-security-policy']
    assert TestClient(create_app(web_db)).get(entries[0]['url']).status_code == 404
    original = api.hashlib.sha256
    class Wrong:
        def hexdigest(self): return '0'*64
    monkeypatch.setattr(api.hashlib, 'sha256', lambda data: Wrong())
    assert client.get(entries[0]['url']).status_code == 503
    monkeypatch.setattr(api.hashlib, 'sha256', original)


@pytest.fixture
def signing_key():
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.hazmat.primitives import serialization
    from jose import jwk
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
    public = key.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
    public_jwk = jwk.construct(public, algorithm='RS256').to_dict()
    public_jwk['kid'] = 'test-signing-key'
    return pem, {'keys':[public_jwk]}


def signed_request(pem, **overrides):
    from jose import jwt
    claims = {'iss':'https://fixture.cloudflareaccess.com','aud':['education'],
              'iat':int(time.time()),'exp':int(time.time())+60,'sub':'verified-subject',
              'email':'parent@example.invalid'}
    claims.update(overrides)
    token = jwt.encode(claims, pem, algorithm='RS256', headers={'kid':'test-signing-key'})
    return Request({'type':'http','headers':[(b'cf-access-jwt-assertion',token.encode())]})


def test_signed_parent_identity_and_spoofing(signing_key):
    pem, keys = signing_key
    verify = CloudflareParentIdentity('https://fixture.cloudflareaccess.com','education',
               {'parent@example.invalid':'parent-fixture'},fetch_keys=lambda:keys)
    assert verify(signed_request(pem)) == 'parent-fixture'
    for override in [{'aud':['different-app']},{'iss':'https://other.cloudflareaccess.com'},
                     {'exp':int(time.time())-60},{'email':'child@example.invalid'}]:
        with pytest.raises(HTTPException): verify(signed_request(pem, **override))
    with pytest.raises(HTTPException) as missing:
        verify(Request({'type':'http','headers':[(b'cf-access-authenticated-user-email',b'parent@example.invalid')]}))
    assert missing.value.status_code == 401
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.hazmat.primitives import serialization
    other = rsa.generate_private_key(public_exponent=65537, key_size=2048).private_bytes(
        serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption())
    with pytest.raises(HTTPException): verify(signed_request(other))


def test_environment_identity_authorizes_review_without_rewriting_attempt(
    judge_free_db, signing_key, monkeypatch,
):
    """The real environment loader, JWT verifier and review route compose safely."""
    from deeptutor.education.application import to_iso_timestamp
    from deeptutor.education.domain.learner import LearnerProfile
    from deeptutor.education.storage.repositories import LearnerRepository

    pem, keys = signing_key
    parent = 'parent-fixture'
    monkeypatch.setenv('EDU_CONTENT_MODE', 'trial')
    monkeypatch.setenv('EDU_ACCESS_ISSUER', 'https://fixture.cloudflareaccess.com')
    monkeypatch.setenv('EDU_ACCESS_AUDIENCE', 'education')
    monkeypatch.setenv('EDU_PARENT_IDENTITIES', json.dumps({'parent@example.invalid': parent}))
    # Only the public-key transport is substituted; identity resolution is real.
    monkeypatch.setattr(CloudflareParentIdentity, '_fetch_keys', lambda self: keys)
    conn = db.open_database(judge_free_db)
    now = to_iso_timestamp(time.time())
    LearnerRepository(conn).create(LearnerProfile(
        id=parent, deep_tutor_user_id='dtu-parent-fixture', display_name='Parent fixture',
        locale='en-US', created_at=now, updated_at=now,
    ))
    conn.close()
    _seed_pending_attempt(judge_free_db, 'Synthetic explanation for identity rehearsal', 'identity-attempt')
    conn = db.open_database(judge_free_db)
    before = [tuple(row) for row in conn.execute('SELECT * FROM student_attempts')]
    conn.close()
    client = TestClient(create_app(judge_free_db))
    query = {'course_version_id': CV}
    payload = {'reviewer': parent, 'attempt_id': 'identity-attempt', 'verdict': 'correct'}

    denied = [({}, 401), ({'Cf-Access-Authenticated-User-Email': 'parent@example.invalid'}, 401)]
    for overrides, status in [({'aud': ['different-app']}, 401),
                              ({'iss': 'https://other.cloudflareaccess.com'}, 401),
                              ({'exp': int(time.time()) - 60}, 401),
                              ({'email': 'child@example.invalid'}, 403)]:
        denied.append((dict(signed_request(pem, **overrides).headers), status))
    for headers, expected in denied:
        assert client.get('/api/edu/review-queue', params=query, headers=headers).status_code == expected
        assert client.post('/api/edu/review', json=payload, headers=headers).status_code == expected

    headers = dict(signed_request(pem).headers)
    queue = client.get('/api/edu/review-queue', params=query, headers=headers)
    assert queue.status_code == 200
    assert [row['attempt_id'] for row in queue.json()['pending']] == ['identity-attempt']
    assert client.post('/api/edu/review', headers=headers,
                       json={**payload, 'reviewer': 'parent-other'}).status_code == 403
    conn = db.open_database(judge_free_db)
    assert conn.execute('SELECT count(*) FROM judgment_records').fetchone()[0] == 0
    conn.close()

    reviewed = client.post('/api/edu/review', json=payload, headers=headers)
    assert reviewed.status_code == 200, reviewed.text
    assert client.get('/api/edu/review-queue', params=query, headers=headers).json()['pending'] == []
    conn = db.open_database(judge_free_db)
    assert [tuple(row) for row in conn.execute('SELECT * FROM student_attempts')] == before
    assert [tuple(row) for row in conn.execute(
        'SELECT judge_kind, judge_ref, verdict FROM judgment_records'
    )] == [('human', parent, 'correct')]
    conn.close()


@pytest.mark.parametrize('missing', ['EDU_ACCESS_ISSUER', 'EDU_ACCESS_AUDIENCE', 'EDU_PARENT_IDENTITIES'])
def test_partial_identity_configuration_fails_at_startup(web_db, monkeypatch, missing):
    monkeypatch.setenv('EDU_ACCESS_ISSUER', 'https://fixture.cloudflareaccess.com')
    monkeypatch.setenv('EDU_ACCESS_AUDIENCE', 'education')
    monkeypatch.setenv('EDU_PARENT_IDENTITIES', '{"parent@example.invalid":"parent-fixture"}')
    monkeypatch.delenv(missing)
    with pytest.raises(ValueError, match='All three'):
        create_app(web_db)
