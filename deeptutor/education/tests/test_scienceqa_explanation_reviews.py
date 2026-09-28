import pytest
from deeptutor.education.application.scienceqa_explanation_reviews import patch_document

TEXT='''# Fixture
Entries: 2
## First
### Question
Which part becomes the seed?
**Options:**
- ovule
- pollen
**Correct answer:** ovule
### Lecture
A previously corrected lecture.
### Explanation
Old explanation.
---
## Second
### Question
Which part becomes the seed?
**Options:**
- ovule
- pollen
**Correct answer:** ovule
### Lecture
Another lecture.
### Explanation
Untouched explanation.
---
'''

def review():return {'source_title':'First','answer_before':'ovule','explanation_before':'Old explanation.','explanation_after':'New bounded explanation.'}

def test_only_target_explanation_changes():
    after=patch_document('fixture.md',TEXT,[review()])
    assert after.replace('New bounded explanation.','Old explanation.')==TEXT
    with pytest.raises(ValueError):patch_document('fixture.md',after,[review()])

def test_source_answer_mismatch_and_heading_injection_rejected():
    r=review();r['answer_before']='pollen'
    with pytest.raises(ValueError):patch_document('fixture.md',TEXT,[r])
    r=review();r['explanation_after']='## New question'
    with pytest.raises(ValueError):patch_document('fixture.md',TEXT,[r])

def test_missing_explanation_cannot_consume_next_record():
    text=TEXT.replace('### Explanation\nOld explanation.\n','')
    with pytest.raises(ValueError):patch_document('fixture.md',text,[review()])


def test_individual_batches_keep_prior_corrections_and_totals(tmp_path):
    import json,sqlite3
    from deeptutor.education.application.content_stock import parse_file
    from deeptutor.education.application.scienceqa_explanation_reviews import build,sha
    base=tmp_path/'base';base.mkdir();(base/'objects').mkdir();(base/'revised-documents').mkdir()
    digest=sha(TEXT);(base/'objects'/(digest+'.md')).write_text(TEXT)
    (base/'revised-documents/fixture.md').write_text(TEXT)
    manifest=[{'source_path':'scienceqa/raw/fixture.md','source_sha256':digest,'expected_current_sha256':digest,'revised_sha256':digest}]
    (base/'revised-documents.json').write_text(json.dumps(manifest))
    rows=parse_file('scienceqa','fixture.md',TEXT)
    with sqlite3.connect(base/'catalog.sqlite3') as db:
        db.execute('create table records(id text primary key,library text,state text,data_json text)')
        for i,row in enumerate(rows):
            row.update(id=str(i),library='scienceqa',source_path='scienceqa/raw/fixture.md',source_sha256=digest,raw_sha256=sha(TEXT[row['start']:row['end']]),state='needs_curriculum_review')
            db.execute('insert into records values(?,?,?,?)',(row['id'],'scienceqa',row['state'],json.dumps(row)))
    summary={'snapshot_id':'base','catalog_sha256':sha((base/'catalog.sqlite3').read_bytes()),'committed_batches':1,'scienceqa_batch_linked_lectures_corrected':0,'libraries':[{'library':'scienceqa','states':{'needs_curriculum_review':2}}]}
    (base/'summary.json').write_text(json.dumps(summary))
    def run(source,row,after,name,hold):
        r={k:row[k] for k in ('source_path','source_sha256','raw_sha256')}
        r.update(record_id=row['id'],source_title=row['title'],answer_before=row['answer'],explanation_before=row['explanation'],explanation_after=after,answer_on_hold=hold)
        p=tmp_path/(name+'.json');p.write_text(json.dumps({'library':'scienceqa','expected_changed_records':1,'expected_answers_on_hold':int(hold),'records':[r]}))
        result=build(source,p,tmp_path/'snapshots');return tmp_path/'snapshots'/result['snapshot_id']
    first=run(base,rows[0],'First correction.','first',False)
    second=run(first,rows[1],'SOURCE ANSWER ON HOLD: second correction.','second',True)
    assert (second/'first.json').read_bytes()==(first/'first.json').read_bytes()
    text=(second/'revised-documents/fixture.md').read_text()
    assert 'First correction.' in text and 'SOURCE ANSWER ON HOLD: second correction.' in text
    meta=json.loads((second/'summary.json').read_text())
    assert meta['scienceqa_individual_explanations_corrected']==2 and meta['scienceqa_source_answers_on_hold']==1
    with sqlite3.connect(first/'catalog.sqlite3') as a,sqlite3.connect(second/'catalog.sqlite3') as b:
        assert a.execute("select data_json from records where id='0'").fetchone()==b.execute("select data_json from records where id='0'").fetchone()
    with pytest.raises(ValueError):run(second,rows[1],'Another correction.','repeat',True)
