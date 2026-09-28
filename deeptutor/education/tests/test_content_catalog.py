import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from deeptutor.education.api.app import create_app
from deeptutor.education.application import content_catalog as catalog
from deeptutor.education.storage.sqlite import open_database, check_trigger_integrity
from deeptutor.education.tests.test_web_loop import web_db, CV
from deeptutor.education.tests.test_free_learning_accounts import accounts, headers


def package():
    return {'course_version_id':CV,'source_name':'Synthetic import fixture','items':[
        {'id':'content-import-1','knowledge_node_id':'node-A','item_type':'numeric',
         'prompt':'A synthetic test: 6 times 7?', 'expected_answer':'42',
         'explanation':'Six groups of seven give forty-two.','explanation_source':'authored',
         'difficulty':2,'content_scope':'BUNDLED','source_ref':'self-authored fixture',
         'status':'production','reviewer':'forged-reviewer','reviewed_at':'2026-01-01'}]}


def test_import_is_candidate_idempotent_and_never_changes_learning(web_db):
    c=open_database(web_db)
    before={t:c.execute(f'SELECT count(*) FROM {t}').fetchone()[0] for t in ('student_attempts','subject_placements','enrollments','assessment_courses','assessment_item_tags')}
    preview,rows=catalog.plan_import(c,package())
    assert preview['inserted']==1 and not preview['errors']
    assert not c.execute("SELECT 1 FROM assessment_items WHERE id='content-import-1'").fetchone()
    first=catalog.import_package(c,package(),'admin')
    again=catalog.import_package(c,package(),'admin')
    assert first['inserted']==1 and not first['replayed'] and again['replayed']
    row=dict(c.execute("SELECT * FROM assessment_items WHERE id='content-import-1'").fetchone())
    assert row['status']=='candidate' and row['reviewer'] is None and row['reviewed_at'] is None
    assert before=={t:c.execute(f'SELECT count(*) FROM {t}').fetchone()[0] for t in before}
    assert not check_trigger_integrity(c)
    assert c.execute('SELECT count(*) FROM content_imports').fetchone()[0]==1
    c.execute('DROP TRIGGER content_reviews_no_update')
    assert 'content_reviews_no_update' in check_trigger_integrity(c)
    c.close()


@pytest.mark.parametrize('change',[
    {'knowledge_node_id':'missing'}, {'content_scope':'PRIVATE_INTERNAL'},
    {'content_scope':'RESTRICTED'}, {'source_ref':None}, {'difficulty':float('nan')},
    {'item_type':'choice','choices_json':[{'label':'A','text':'One','answer':True}]},
])
def test_invalid_batch_writes_nothing(web_db,change):
    c=open_database(web_db);body=package();bad={**body['items'][0],**change,'id':'bad'};body['items'].append(bad)
    with pytest.raises(HTTPException): catalog.import_package(c,body,'admin')
    assert not c.execute("SELECT 1 FROM assessment_items WHERE id='content-import-1'").fetchone()
    assert c.execute('SELECT count(*) FROM content_imports').fetchone()[0]==0
    c.close()


def test_conflict_does_not_overwrite_and_version_is_bound(web_db):
    c=open_database(web_db);body=package();catalog.import_package(c,body,'admin')
    body['items'][0]['expected_answer']='43'
    with pytest.raises(HTTPException):catalog.import_package(c,body,'admin')
    assert c.execute("SELECT expected_answer FROM assessment_items WHERE id='content-import-1'").fetchone()[0]=='42'
    body['items'][0]['id']='new';body['items'][0]['course_version_id']='other-course'
    with pytest.raises(HTTPException):catalog.import_package(c,body,'admin')
    c.close()


def test_review_requires_current_content_and_records_real_actor(web_db):
    c=open_database(web_db);catalog.import_package(c,package(),'admin')
    row=dict(c.execute("SELECT * FROM assessment_items WHERE id='content-import-1'").fetchone())
    with pytest.raises(HTTPException):catalog.review_item(c,row['id'],expected_revision='0'*64,decision='publish',note='Checked source and arithmetic',actor='admin')
    catalog.review_item(c,row['id'],expected_revision=catalog.revision(row),decision='publish',note='Checked source and arithmetic',actor='admin')
    updated=dict(c.execute('SELECT * FROM assessment_items WHERE id=?',(row['id'],)).fetchone())
    assert updated['reviewer']=='admin' and updated['status']=='production'
    result=catalog.catalog(c)['courses'][0]
    assert result['published']==1 and result['quiz_ready']==0 and not result['blueprint']
    with pytest.raises(Exception): c.execute("UPDATE content_reviews SET actor_id='fake'")
    c.close()


@pytest.mark.parametrize('field,value,issue',[
    ('expected_answer',None,'answer'),('explanation','', 'explanation'),
    ('expected_answer','NaN','numeric'),('prompt','Teachers with a valid work email','placeholder'),
    ('figure_spec_id','missing-asset','figure'),
])
def test_incomplete_item_cannot_be_published(web_db,field,value,issue):
    c=open_database(web_db);body=package();body['items'][0][field]=value
    catalog.import_package(c,body,'admin')
    row=dict(c.execute("SELECT * FROM assessment_items WHERE id='content-import-1'").fetchone())
    assert issue in catalog.content_issues(row)
    with pytest.raises(HTTPException):catalog.review_item(c,row['id'],expected_revision=catalog.revision(row),decision='publish',note='Trying to publish an incomplete item',actor='admin')
    c.close()


def test_admin_answers_are_denied_to_student_and_anonymous(web_db,accounts):
    client=TestClient(create_app(web_db,account_access=accounts[2]))
    for path in ('content-admin/catalog',f'content-admin/courses/{CV}/items',f'content-admin/starter?course_version_id={CV}'):
        assert client.get('/api/edu/'+path).status_code==401
        assert client.get('/api/edu/'+path,headers=headers(accounts)).status_code==403
        assert client.get('/api/edu/'+path,headers=headers(accounts,'dtu-parent')).status_code==200
    assert client.post('/api/edu/content-admin/import',json=package(),headers=headers(accounts)).status_code==403
    response=client.post('/api/edu/content-admin/import',json=package(),headers=headers(accounts,'dtu-parent'))
    assert response.status_code==200,response.text
    assert client.post('/api/edu/content-admin/import',content='x'*(4*1024*1024+1),headers=headers(accounts,'dtu-parent')).status_code==413
    accounts[0]['dtu-parent']['role']='parent'
    assert client.get(f'/api/edu/content-admin/courses/{CV}/items',headers=headers(accounts,'dtu-parent')).status_code==403
    assert client.post('/api/edu/content-admin/import',json=package(),headers=headers(accounts,'dtu-parent')).status_code==403


def test_legacy_incomplete_provenance_cannot_be_published(web_db):
    c=open_database(web_db)
    catalog.import_package(c,package(),'admin')
    c.execute("UPDATE assessment_items SET source_ref='https://example.invalid/source' WHERE id='content-import-1'")
    row=dict(c.execute("SELECT * FROM assessment_items WHERE id='content-import-1'").fetchone())
    assert 'provenance' in catalog.content_issues(row)
    with pytest.raises(HTTPException) as error:
        catalog.review_item(c,row['id'],expected_revision=catalog.revision(row),decision='publish',note='Reviewing this legacy source record',actor='admin')
    assert error.value.status_code==409
    c.close()


def test_starter_has_complete_explicit_provenance_and_no_approval():
    from deeptutor.education.application.number_structure_pack import package as starter
    rows=starter('example')['items']
    assert len(rows)==32 and len({r['id'] for r in rows})==32
    for row in rows:
        assert row['source_ref'].startswith('self-authored')
        assert row['expected_answer'] and row['explanation'] and row.get('status')!='production'
    # Independently enumerate the nontrivial finite cases in the authored pack.
    answers=[int(r['expected_answer']) for r in rows]
    assert answers[0]==sum(72%d==0 for d in range(1,9))
    assert answers[1]==min(2*(d+42//d) for d in range(1,43) if 42%d==0)
    assert answers[7]==sum(sum(n%d==0 for d in range(1,n+1))==3 for n in range(1,30))
    assert answers[11]==len([n for n in range(1,101) if n%7==0])
    assert answers[12]==len([n for n in range(1,101) if n%3==0 or n%5==0])
    assert answers[23]==''.join(map(str,range(1,21))).count('1')
