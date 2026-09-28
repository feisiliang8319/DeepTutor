import json
import sqlite3
from pathlib import Path
import pytest
from deeptutor.education.application.content_stock import parse_file
from deeptutor.education.application.scienceqa_lecture_reviews import concept_id,sha,build as revise
from deeptutor.education.application.scienceqa_lecture_assessments import build,SCOPE,STATE


def fixture(tmp_path):
    lectures=['A force pair acts on different objects.','An old statement needing correction.']
    text='# Sample\nEntries: 2\n\n'
    for n,lecture in enumerate(lectures,1):
        text+=f'## Sample · Q{n}\n**Subject:** natural science **Grade:** grade4 **Skill:** forces\n### Question\nRead force diagram {n}.\n**Options:**\n- first\n- second\n**Correct answer:** first\n### Lecture\n{lecture}\n\n### Explanation\nThe original explanation remains.\n---\n'
    base=tmp_path/'base';base.mkdir();(base/'objects').mkdir();source=sha(text)
    (base/'objects'/(source+'.md')).write_text(text);(base/'sources.json').write_text('[]');(base/'other-proof.json').write_text('retain')
    queue=[]
    with sqlite3.connect(base/'catalog.sqlite3') as db:
        db.execute('create table records(id text primary key,library text,data_json text)')
        for n,row in enumerate(parse_file('scienceqa','fixture.md',text)):
            row.update(id=str(n),library='scienceqa',source_path='scienceqa/raw/fixture.md',source_sha256=source,raw_sha256=sha(text[row['start']:row['end']]),state='needs_repair',approval='unreviewed')
            row['issues']=['missing_figure']
            db.execute('insert into records values(?,?,?)',(str(n),'scienceqa',json.dumps(row)))
            queue.append({'id':concept_id(row['lecture']),'lecture_original':row['lecture'],'linked_records':1,'source_paths':[row['source_path']],'skills':['forces'],'state':'pending_review'})
    (base/'scienceqa-concept-queue.json').write_text(json.dumps(queue))
    (base/'summary.json').write_text(json.dumps({'snapshot_id':'base','catalog_sha256':sha((base/'catalog.sqlite3').read_bytes()),'committed_batches':1,'records':2}))
    recipe={'schema_version':1,'library':'scienceqa','expected_total_records':2,'expected_linked_records':1,'reviews':[{'concept_id':concept_id(lectures[0]),'lecture':lectures[0],'expected_records':1,'decision':'checked_unchanged','scope':SCOPE,'reason':'Correct pair definition.','limitations':'Diagram and answer not reviewed.','references':[{'url':'https://example.test/physics','supports':'Force-pair principle.'}],'reviewed_on':'2026-09-28'}]}
    path=tmp_path/'review.json';path.write_text(json.dumps(recipe));return base,path,recipe,lectures


def test_unchanged_review_preserves_every_other_field_and_artifact(tmp_path):
    base,path,recipe,lectures=fixture(tmp_path);before=(base/'catalog.sqlite3').read_bytes()
    result=build(base,path,tmp_path/'out');target=tmp_path/'out'/result['snapshot_id']
    assert result['linked_records']==1 and (base/'catalog.sqlite3').read_bytes()==before
    assert (target/'other-proof.json').read_bytes()==(base/'other-proof.json').read_bytes()
    with sqlite3.connect(base/'catalog.sqlite3') as old,sqlite3.connect(target/'catalog.sqlite3') as new:
        for a,b in zip(old.execute('select data_json from records order by id'),new.execute('select data_json from records order by id'),strict=True):
            a,b=json.loads(a[0]),json.loads(b[0])
            if a['id']=='0':
                evidence=b['metadata'].pop('lecture_assessment');assert evidence['approval']=='unchanged'
            assert a==b and b['approval']=='unreviewed' and b['issues']==['missing_figure']
    queue=json.loads((target/'scienceqa-concept-queue.json').read_text());assert queue[0]['state']==STATE and queue[1]['state']=='pending_review'
    with pytest.raises(ValueError,match='already reviewed'):build(target,path,tmp_path/'again')


@pytest.mark.parametrize('damage',['source','count','scope','references','limits','queue'])
def test_invalid_evidence_is_rejected_before_snapshot(tmp_path,damage):
    base,path,recipe,lectures=fixture(tmp_path)
    if damage=='source':next((base/'objects').glob('*.md')).write_text('tampered')
    elif damage=='count':recipe['reviews'][0]['expected_records']=2
    elif damage=='scope':recipe['reviews'][0]['scope']='approve_questions'
    elif damage=='references':recipe['reviews'][0]['references']=[]
    elif damage=='limits':recipe['reviews'][0]['limitations']=''
    elif damage=='queue':
        q=json.loads((base/'scienceqa-concept-queue.json').read_text());q[0]['state']='shared_lecture_corrected';(base/'scienceqa-concept-queue.json').write_text(json.dumps(q))
    path.write_text(json.dumps(recipe))
    with pytest.raises(ValueError):build(base,path,tmp_path/'out')
    assert not (tmp_path/'out').exists()


def test_later_text_correction_retains_other_unchanged_assessment(tmp_path):
    base,path,recipe,lectures=fixture(tmp_path);first=build(base,path,tmp_path/'out');first_path=tmp_path/'out'/first['snapshot_id']
    correction={'library':'scienceqa','expected_total_records':2,'expected_changed_records':1,'reviews':[{'concept_id':concept_id(lectures[1]),'lecture_before':lectures[1],'lecture_after':'A corrected statement.','expected_records':1,'references':[{'url':'https://example.test/correction'}]}]}
    path2=tmp_path/'correction.json';path2.write_text(json.dumps(correction));second=revise(first_path,path2,tmp_path/'out');second_path=tmp_path/'out'/second['snapshot_id']
    queue={x['id']:x for x in json.loads((second_path/'scienceqa-concept-queue.json').read_text())}
    assert queue[concept_id(lectures[0])]['state']==STATE
    assert queue[concept_id(lectures[1])]['state']=='shared_lecture_corrected'
    with sqlite3.connect(first_path/'catalog.sqlite3') as a,sqlite3.connect(second_path/'catalog.sqlite3') as b:
        assert a.execute("select data_json from records where id='0'").fetchone()==b.execute("select data_json from records where id='0'").fetchone()
    assert all((second_path/'scienceqa-lecture-assessments'/p.name).read_bytes()==p.read_bytes() for p in (first_path/'scienceqa-lecture-assessments').iterdir())
