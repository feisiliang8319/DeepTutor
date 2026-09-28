"""Synthetic policy fixtures; these questions do not certify a curriculum."""
import json
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from deeptutor.education.application import assessment_engine as engine
from deeptutor.education.storage.sqlite import open_database,check_trigger_integrity
from deeptutor.education.storage.repositories import AssessmentItemRepository
from deeptutor.education.tests.test_web_loop import web_db,CV,LEARNER
from deeptutor.education.api.app import create_app


@pytest.fixture
def formal(web_db):
    conn=open_database(web_db)
    engine.configure(conn,CV,'synthetic',4,['node-A','node-B'],'admin','mathematics')
    rows=[]
    for bank in ('regular','competition'):
        for tier in ('A','B','C') if bank=='regular' else ('A',):
            for n in range(120):
                name=f'{bank}-{tier}-{n}'
                rows.append({'id':name,'course_version_id':CV,'knowledge_node_id':'node-A' if n%2==0 else 'node-B','item_type':'numeric','prompt':f'Synthetic policy fixture {name}: {n}+1?','expected_answer':str(n+1),'rubric_json':None,'difficulty':3,'content_scope':'BUNDLED','source_ref':'self-authored synthetic policy test only','license_note':None,'attribution_text':None,'derived_from_item_id':None,'reviewer':'synthetic-review','reviewed_at':'2026-09-27T00:00:00Z','content_hash':engine.fingerprint(name),'status':'production','explanation':f'{n}+1={n+1}.','explanation_source':'authored'})
    AssessmentItemRepository(conn).import_items(rows)
    for row in rows:
        bank,tier,_=row['id'].split('-')
        engine.tag_item(conn,row['id'],dict(unit_id=row['knowledge_node_id'],tier=tier,bank=bank,core=True,points=5,family_key=row['id']))
    engine.set_placement(conn,LEARNER,engine.course(conn,CV),4,'standard',3,'parent',0)
    yield conn,TestClient(create_app(web_db,content_mode='trial'))
    conn.close()


def issue(formal,kind='daily',unit=None):
    return engine.issue(formal[0],LEARNER,CV,kind,unit)


def submit(formal,paper,correct=1):
    conn,client=formal
    count=round(len(paper['items'])*correct)
    responses=[{'item_id':item['id'],'response':AssessmentItemRepository(conn).get(item['id']).expected_answer if index<count else '-999'} for index,item in enumerate(paper['items'])]
    response=client.post('/api/edu/set/submit',json={'learner_id':LEARNER,'course_version_id':CV,'set_id':paper['set_id'],'answers':responses})
    assert response.status_code==200,response.text
    return response.json()


@pytest.mark.parametrize('count,expected',[(20,{'A':3,'B':13,'C':4}),(25,{'A':4,'B':16,'C':5}),(35,{'A':5,'B':23,'C':7})])
def test_difficulty_allocation(count,expected): assert engine.quotas(count)==expected


def test_competition_stem_and_hard_only(formal):
    conn,_=formal
    paper=issue(formal,'competition')
    assert len(paper['items'])==20 and paper['minutes']==90
    snapshot=json.loads(conn.execute('SELECT snapshot_json FROM formal_exams WHERE set_id=?',(paper['set_id'],)).fetchone()[0])
    assert {i['tier'] for i in snapshot['items']}=={'A'}
    conn.execute("UPDATE courses SET subject_key='history' WHERE id='c-web'");conn.commit()
    with pytest.raises(HTTPException):engine.configure(conn,CV,'synthetic',4,['node-A'],'admin','mathematics')


def test_no_unreviewed_or_seen_variant_fill(formal):
    conn,_=formal
    paper=issue(formal)
    assert len(paper['items'])==20 and 'expected_answer' not in json.dumps(paper) and 'rubric' not in json.dumps(paper)
    submit(formal,paper)
    again=issue(formal)
    assert not {i['id'] for i in paper['items']} & {i['id'] for i in again['items']}
    # An exhausted pool fails rather than admitting candidate or repeated items.
    conn.execute("UPDATE assessment_items SET status='candidate'");conn.execute('UPDATE task_sets SET skipped_at=issued_at WHERE id=?',(again['set_id'],));conn.commit()
    with pytest.raises(HTTPException):issue(formal)


def test_deadline_uses_saved_draft_and_cannot_skip(formal,monkeypatch):
    conn,client=formal;paper=issue(formal)
    first=paper['items'][0];answer=AssessmentItemRepository(conn).get(first['id']).expected_answer
    engine.save_draft(conn,paper['set_id'],{first['id']:answer},0)
    with pytest.raises(HTTPException):engine.save_draft(conn,paper['set_id'],{},0)
    conn.execute('UPDATE formal_exams SET deadline=0 WHERE set_id=?',(paper['set_id'],));conn.commit()
    with pytest.raises(HTTPException):engine.save_draft(conn,paper['set_id'],{},1)
    rejected=client.post('/api/edu/set/skip',json={'learner_id':LEARNER,'course_version_id':CV,'set_id':paper['set_id']})
    assert rejected.status_code==409
    result=submit(formal,paper)
    assert result['assessment']['percent']==5
    assert sum(bool(r['your_response']) for r in result['results'])==1
    assert submit(formal,paper)['assessment']['percent']==5


def test_failed_retry_requires_chat_engagement(formal,monkeypatch):
    paper=issue(formal);submit(formal,paper,0)
    monkeypatch.setattr(engine,'remedied',lambda *_:False)
    with pytest.raises(HTTPException):issue(formal)
    monkeypatch.setattr(engine,'remedied',lambda *_:True)
    assert issue(formal)['set_id']!=paper['set_id']


def test_final_requires_units_and_promotes_once(formal):
    conn,_=formal
    with pytest.raises(HTTPException):issue(formal,'final')
    for unit in ('node-A','node-B'):assert submit(formal,issue(formal,'unit',unit))['assessment']['passed']
    final=issue(formal,'final');result=submit(formal,final)['assessment']
    assert result['promotion']['to_grade']==5
    for _ in range(3):assert engine.finalize(conn,final['set_id'])['promotion']['to_grade']==5
    assert conn.execute('SELECT COUNT(*) FROM promotion_events').fetchone()[0]==1
    assert conn.execute('SELECT school_grade FROM academic_background').fetchone()[0]==3


def test_early_promotion_parent_confirmation(formal):
    conn,_=formal;paper=issue(formal,'promotion');result=submit(formal,paper)['assessment']
    assert result['promotion']['status']=='parent_confirmation'
    assert conn.execute('SELECT grade FROM subject_placements').fetchone()[0]==4
    assert engine.finalize(conn,paper['set_id'],parent_actor='parent')['promotion']['to_grade']==5


def test_competition_70_promotes_before_optional_foundation(formal):
    conn,_=formal;paper=issue(formal,'competition');result=submit(formal,paper,.7)['assessment']
    assert result['percent']==70 and result['passed']
    assert result['promotion']['to_grade']==5
    assert result['foundation_followup']['status']=='offered'
    assert conn.execute('SELECT grade FROM subject_placements').fetchone()[0]==5
    assert conn.execute('SELECT school_grade FROM academic_background').fetchone()[0]==3
    followup=engine.choose_foundation(conn,paper['set_id'],'yes','student')['exam']
    assert followup['kind']=='foundation' and followup['grade']==4
    assert len(followup['items'])==35 and followup['minutes']==90
    assert engine.choose_foundation(conn,paper['set_id'],'yes','student')['exam']['set_id']==followup['set_id']
    assert not {i['id'] for i in paper['items']} & {i['id'] for i in followup['items']}
    failed=submit(formal,followup,0)['assessment']
    assert failed['diagnostic_only'] and not failed['passed'] and failed['promotion'] is None
    original=engine.finalize(conn,paper['set_id'])
    assert original['foundation_followup']['status']=='completed'
    assert original['promotion']['review_required'] is False
    assert conn.execute('SELECT grade FROM subject_placements').fetchone()[0]==5
    assert conn.execute('SELECT COUNT(*) FROM promotion_events').fetchone()[0]==1


def test_declined_foundation_ends_without_claiming_mastery(formal):
    conn,_=formal;paper=issue(formal,'competition');submit(formal,paper,.7)
    choice=engine.choose_foundation(conn,paper['set_id'],'no','student')
    assert choice['exam'] is None and choice['foundation_followup']['status']=='declined'
    assert engine.choose_foundation(conn,paper['set_id'],'no','student')==choice
    with pytest.raises(HTTPException):engine.choose_foundation(conn,paper['set_id'],'yes','student')
    assert conn.execute('SELECT COUNT(*) FROM formal_exams').fetchone()[0]==1
    assert conn.execute('SELECT COUNT(*) FROM promotion_events').fetchone()[0]==1
    assert conn.execute('SELECT COUNT(*) FROM student_attempts').fetchone()[0]==20
    assert engine.public_exam(conn,paper['set_id'])['result']['foundation_followup']['status']=='declined'


def test_foundation_requires_pass_and_atomic_available_bank(formal):
    conn,_=formal;paper=issue(formal,'competition')
    with pytest.raises(HTTPException):engine.choose_foundation(conn,paper['set_id'],'yes','student')
    with pytest.raises(HTTPException):engine.issue(conn,LEARNER,CV,'foundation')
    submit(formal,paper,.7)
    conn.execute("UPDATE assessment_items SET status='candidate' WHERE id LIKE 'regular-%'")
    with pytest.raises(HTTPException):engine.choose_foundation(conn,paper['set_id'],'yes','student')
    assert conn.execute('SELECT COUNT(*) FROM competition_foundation_choices').fetchone()[0]==0
    assert conn.execute('SELECT COUNT(*) FROM formal_exams').fetchone()[0]==1
    assert engine.public_exam(conn,paper['set_id'])['result']['foundation_followup']['status']=='offered'
    conn.execute("UPDATE assessment_items SET status='production' WHERE id LIKE 'regular-%'")
    foundation=engine.choose_foundation(conn,paper['set_id'],'yes','student')['exam']
    full=submit(formal,foundation)['assessment']
    assert full['percent']==100 and full['diagnostic_only'] and full['promotion'] is None
    assert conn.execute('SELECT COUNT(*) FROM promotion_events').fetchone()[0]==1


def test_pending_partial_review_cannot_promote_and_trigger_integrity(formal):
    conn,_=formal;paper=issue(formal,'promotion');submit(formal,paper)
    from deeptutor.education.application.rebuild_mastery import append_human_judgment_and_recompute
    from deeptutor.education.domain.evidence import Verdict
    append_human_judgment_and_recompute(conn,attempt_id=paper['set_id']+':'+paper['items'][0]['id'],judge_ref='parent',verdict=Verdict.PARTIAL,confidence=1.,rationale='partial credit awaiting points')
    result=engine.finalize(conn,paper['set_id'],parent_actor='parent')
    assert result['status']=='awaiting_review' and not result['passed'] and result['promotion'] is None
    conn.execute('DROP TRIGGER promotion_events_no_update');conn.commit()
    assert 'promotion_events_no_update' in check_trigger_integrity(conn)


@pytest.mark.parametrize('kind,correct,expected', [('daily',.75,False),('daily',.8,True),('promotion',31/35,False),('promotion',32/35,True),('competition',.65,False),('competition',.7,True)])
def test_thresholds_apply_to_unrounded_score(formal,kind,correct,expected):
    # For advancement papers keep mistakes outside the minimum core evidence;
    # any remaining foundational gap must still block promotion separately.
    paper=issue(formal,kind);result=submit(formal,paper,correct)['assessment']
    assert (result['percent']>=result['threshold'])==expected
    if not expected:assert not result['passed'] and result['promotion'] is None


def test_current_exam_blocks_chat_and_content_edit_cannot_regrade(formal,monkeypatch):
    conn,_=formal;paper=issue(formal)
    from deeptutor.multi_user.teaching_evidence import assert_no_active_assessment
    path=conn.execute('PRAGMA database_list').fetchone()[2]
    monkeypatch.setenv('TEACHING_EDUCATION_DB',path)
    with pytest.raises(RuntimeError,match='Quiz'):assert_no_active_assessment('dtu-web')
    assert_no_active_assessment('unrelated-student')
    item=paper['items'][0]
    conn.execute('UPDATE assessment_items SET expected_answer=? WHERE id=?',('rewritten-answer',item['id']));conn.commit()
    from deeptutor.education.api.app import SetSubmission,SetAnswer
    body=SetSubmission(learner_id=LEARNER,course_version_id=CV,set_id=paper['set_id'],answers=[SetAnswer(item_id=i['id'],response='1') for i in paper['items']])
    with pytest.raises(HTTPException):engine.validate_submission(conn,body)
    assert conn.execute('SELECT COUNT(*) FROM task_set_submissions').fetchone()[0]==0


def test_family_and_identical_question_deduplication(formal):
    conn,_=formal
    first=issue(formal);submit(formal,first)
    old=first['items'][0]
    # A new ID cannot reuse a seen question or a curated family.
    available=conn.execute("SELECT item_id FROM assessment_item_tags WHERE bank='regular' AND item_id NOT IN (SELECT assessment_item_id FROM student_attempts) LIMIT 2").fetchall()
    conn.execute('UPDATE assessment_items SET prompt=? WHERE id=?',(old['prompt'],available[0][0]))
    conn.execute('UPDATE assessment_item_tags SET family_key=? WHERE item_id=?',(old['id'],available[1][0]));conn.commit()
    second=issue(formal)
    assert not {r[0] for r in available} & {i['id'] for i in second['items']}


def test_parent_readiness_update_does_not_invalidate_earned_promotion(formal):
    conn,_=formal;paper=issue(formal,'promotion');submit(formal,paper)
    config=engine.course(conn,CV)
    current=engine.placement(conn,LEARNER,config)
    engine.set_placement(conn,LEARNER,config,4,'extension',3,'parent',current['revision'])
    with pytest.raises(HTTPException):engine.set_placement(conn,LEARNER,config,4,'standard',3,'parent',current['revision'])
    assert engine.finalize(conn,paper['set_id'],parent_actor='parent')['promotion']['to_grade']==5


def test_review_flags_old_promotion_without_rewriting_history(formal):
    conn,_=formal
    units=[]
    for unit in ('node-A','node-B'):
        paper=issue(formal,'unit',unit);units.append(paper);submit(formal,paper)
    final=issue(formal,'final');submit(formal,final)
    from deeptutor.education.application.rebuild_mastery import append_human_judgment_and_recompute
    from deeptutor.education.domain.evidence import Verdict
    for item in units[0]['items'][:6]:
        append_human_judgment_and_recompute(conn,attempt_id=units[0]['set_id']+':'+item['id'],judge_ref='parent',verdict=Verdict.INCORRECT,confidence=1.,rationale='Evidence corrected in a later review')
    engine.finalize(conn,units[0]['set_id'])
    result=json.loads(conn.execute('SELECT result_json FROM formal_exams WHERE set_id=?',(final['set_id'],)).fetchone()[0])
    assert result['promotion']['review_required'] is True
    assert conn.execute('SELECT grade FROM subject_placements').fetchone()[0]==5
    assert conn.execute('SELECT COUNT(*) FROM promotion_events').fetchone()[0]==1
    assert conn.execute('SELECT MIN(is_correct) FROM student_attempts').fetchone()[0]==1


def test_foundation_migration_preserves_existing_references_and_rolls_back(formal,tmp_path):
    from deeptutor.education.storage.sqlite import apply_migration,MIGRATIONS_DIR,MigrationError
    conn,_=formal
    paper=issue(formal,'competition');submit(formal,paper,.7)
    # Model an existing 009 database containing exam, draft and promotion rows.
    conn.execute('DROP TABLE competition_foundation_choices')
    conn.execute("DELETE FROM schema_migrations WHERE filename='010_competition_foundation.sql'")
    conn.execute('INSERT INTO exam_drafts VALUES(?,?,?,?)',(paper['set_id'],'{}',1,1))
    before={table:[tuple(r) for r in conn.execute('SELECT * FROM '+table)] for table in ('formal_exams','exam_drafts','promotion_events','student_attempts','task_set_submissions')}
    bad=tmp_path/'010_competition_foundation.sql'
    bad.write_text((MIGRATIONS_DIR/bad.name).read_text()+"\nINSERT INTO exam_drafts VALUES('missing','{}',1,1);\n")
    with pytest.raises(MigrationError):apply_migration(conn,bad)
    assert conn.execute('PRAGMA foreign_keys').fetchone()[0]==1
    assert conn.execute("SELECT 1 FROM schema_migrations WHERE filename=?",(bad.name,)).fetchone() is None
    for table,rows in before.items():assert [tuple(r) for r in conn.execute('SELECT * FROM '+table)]==rows
    apply_migration(conn,MIGRATIONS_DIR/bad.name)
    for table,rows in before.items():assert [tuple(r) for r in conn.execute('SELECT * FROM '+table)]==rows
    assert not conn.execute('PRAGMA foreign_key_check').fetchall()
    assert conn.execute('PRAGMA foreign_keys').fetchone()[0]==1
    assert not check_trigger_integrity(conn)
    apply_migration(conn,MIGRATIONS_DIR/bad.name) # Idempotent ledger.
