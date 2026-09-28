from pathlib import Path
import json
import sqlite3
import pytest
from deeptutor.education.application.content_stock import parse_file
from deeptutor.education.application.scienceqa_context_reviews import build, patch_document, sha
from deeptutor.education.application.scienceqa_lecture_reviews import build as lecture_build, concept_id

TEXT='''# Test source
Entries: 2
## earth · Q1
**Subject:** natural science **Grade:** grade8
**Note:** the original problem includes a figure that is not bundled in this knowledge base.
**Context:** Read the passage and look at the picture.
Old date.
### Question
Which boundary?
**Options:**
- convergent
- divergent
**Correct answer:** convergent
### Lecture
First old lecture.
### Explanation
Old date. The plates move together.
---
## earth · Q2
**Subject:** natural science **Grade:** grade8
### Question
Which motion?
**Options:**
- together
- apart
**Correct answer:** together
### Lecture
Second old lecture.
### Explanation
The plates move together.
---
'''


def fixture(tmp_path):
    base=tmp_path/'base';base.mkdir();(base/'objects').mkdir()
    (base/'objects'/(sha(TEXT)+'.md')).write_text(TEXT)
    (base/'sources.json').write_text('[]')
    (base/'other-review.json').write_text('{"keep":true}')
    with sqlite3.connect(base/'catalog.sqlite3') as db:
        db.execute('create table records(id text primary key, library text, state text, data_json text)')
        for i,row in enumerate(parse_file('scienceqa','fixture.md',TEXT)):
            row.update(id=str(i),library='scienceqa',state='needs_repair',source_path='scienceqa/raw/fixture.md',source_sha256=sha(TEXT),raw_sha256=sha(TEXT[row['start']:row['end']]),fingerprint='original-'+str(i))
            db.execute('insert into records values(?,?,?,?)',(str(i),'scienceqa',row['state'],json.dumps(row)))
    (base/'summary.json').write_text(json.dumps({'snapshot_id':'base','catalog_sha256':sha((base/'catalog.sqlite3').read_bytes()),'committed_batches':1,'records':2}))
    return base


def recipe(base,tmp_path):
    with sqlite3.connect(base/'catalog.sqlite3') as db:
        row=json.loads(db.execute("select data_json from records where id='0'").fetchone()[0])
    r={'record_id':'0','source_title':row['title'],**{k:row[k] for k in ('source_path','source_sha256','raw_sha256')},'fragment_before':'Old date.','fragment_after':'Correct date.','references':[{'url':'https://example.test/reference'}]}
    for k in ('prompt','explanation'):
        r[k+'_before']=row[k];r[k+'_after']=row[k].replace('Old date.','Correct date.')
    r['answer_before']=row['answer']
    p=tmp_path/'recipe.json';p.write_text(json.dumps({'library':'scienceqa','expected_total_records':2,'expected_changed_records':1,'records':[r]}))
    return p,r


def lecture(base,tmp_path,before,after,name):
    p=tmp_path/(name+'.json');p.write_text(json.dumps({'library':'scienceqa','expected_total_records':2,'expected_changed_records':1,'reviews':[{'concept_id':concept_id(before),'lecture_before':before,'lecture_after':after,'expected_records':1,'references':[{'url':'https://example.test/reference'}]}]}))
    r=lecture_build(base,p,tmp_path/'snapshots')
    return tmp_path/'snapshots'/r['snapshot_id']


def test_source_bound_context_and_explanation_keep_other_fields_and_next_record(tmp_path):
    base=fixture(tmp_path);p,r=recipe(base,tmp_path);old_db=(base/'catalog.sqlite3').read_bytes()
    result=build(base,p,tmp_path/'snapshots');new=tmp_path/'snapshots'/result['snapshot_id']
    text=(new/'revised-documents/fixture.md').read_text()
    assert text.count('Correct date.')==2 and 'Old date.' not in text
    assert text.replace('Correct date.','Old date.')==TEXT
    assert (base/'catalog.sqlite3').read_bytes()==old_db
    assert (new/'other-review.json').read_bytes()==(base/'other-review.json').read_bytes()
    with sqlite3.connect(new/'catalog.sqlite3') as db:
        row=json.loads(db.execute("select data_json from records where id='0'").fetchone()[0])
        assert row['answer']=='convergent' and row['approval']=='unreviewed' and row['state']=='needs_repair'
        assert row['issues']==['missing_figure'] and row['fingerprint']=='original-0'
        assert row['source_sha256']==sha(TEXT)
    with pytest.raises(ValueError,match='Existing individual review'):
        build(new,p,tmp_path/'repeated')


@pytest.mark.parametrize('case',['source_hash','fragment','outside_section','injected_heading','answer','altered_prompt'])
def test_rejects_stale_ambiguous_or_scope_expanding_review(tmp_path,case):
    base=fixture(tmp_path);p,r=recipe(base,tmp_path)
    if case=='source_hash':r['raw_sha256']='0'*64
    if case=='fragment':r['fragment_before']='Absent date.'
    if case=='outside_section':r['fragment_before']='convergent'
    if case=='injected_heading':
        r['fragment_after']='## injected'
        for k in ('prompt','explanation'):r[k+'_after']=r[k+'_before'].replace('Old date.','## injected')
    if case=='answer':r['answer_before']='divergent'
    if case=='altered_prompt':r['prompt_after']+=' Unreviewed extra sentence.'
    obj=json.loads(p.read_text());obj['records']=[r];p.write_text(json.dumps(obj))
    with pytest.raises(ValueError):build(base,p,tmp_path/'out')


def test_later_lecture_keeps_context_fix_and_earlier_same_file_lecture(tmp_path):
    base=fixture(tmp_path)
    first=lecture(base,tmp_path,'Second old lecture.','Second corrected lecture.','first')
    p,r=recipe(first,tmp_path);result=build(first,p,tmp_path/'snapshots');context=tmp_path/'snapshots'/result['snapshot_id']
    later=lecture(context,tmp_path,'First old lecture.','First corrected lecture.','later')
    text=(later/'revised-documents/fixture.md').read_text()
    assert text.count('Correct date.')==2 and 'Old date.' not in text
    assert 'First corrected lecture.' in text and 'Second corrected lecture.' in text
    manifest=json.loads((later/'revised-documents.json').read_text())
    assert manifest[0]['expected_current_sha256']==sha((context/'revised-documents/fixture.md').read_bytes())
    with sqlite3.connect(later/'catalog.sqlite3') as db:
        row=json.loads(db.execute("select data_json from records where id='0'").fetchone()[0])
        assert row['metadata']['individual_context_review']['prompt_after']==row['prompt']
        assert row['issues']==['missing_figure'] and row['state']=='needs_repair'


def test_explanation_only_followup_cannot_bypass_existing_context_history(tmp_path):
    from deeptutor.education.application.scienceqa_explanation_reviews import build as explanation_build
    base=fixture(tmp_path);p,r=recipe(base,tmp_path)
    result=build(base,p,tmp_path/'snapshots');new=tmp_path/'snapshots'/result['snapshot_id']
    review={**r,'explanation_before':r['explanation_after'],'explanation_after':'Another explanation.','answer_on_hold':False}
    proposal=tmp_path/'overlap.json';proposal.write_text(json.dumps({'library':'scienceqa','expected_changed_records':1,'expected_answers_on_hold':0,'records':[review]}))
    unchanged=(new/'catalog.sqlite3').read_bytes()
    with pytest.raises(ValueError,match='explicit joint revision'):
        explanation_build(new,proposal,tmp_path/'overlap-output')
    assert (new/'catalog.sqlite3').read_bytes()==unchanged


def attribution_fixture(tmp_path,monkeypatch):
    monkeypatch.setitem(globals(),'TEXT',TEXT.replace('Which boundary?','Which boundary?\n—Wrong Author, "Poem"'))
    base=fixture(tmp_path);p,r=recipe(base,tmp_path)
    r.update(mode='question_attribution',fragment_before='—Wrong Author, "Poem"',fragment_after='—Correct Author, "Poem"')
    r['prompt_after']=r['prompt_before'].replace(r['fragment_before'],r['fragment_after'])
    r['explanation_after']=r['explanation_before']
    obj=json.loads(p.read_text());obj['records']=[r];p.write_text(json.dumps(obj))
    return base,p,r


def test_attribution_only_preserves_context_answer_explanation_and_future_rebuild(tmp_path,monkeypatch):
    base,p,r=attribution_fixture(tmp_path,monkeypatch);before=(base/'catalog.sqlite3').read_bytes()
    result=build(base,p,tmp_path/'snapshots');new=tmp_path/'snapshots'/result['snapshot_id']
    assert result['changed_attributions']==1 and result['changed_explanations']==0
    assert (base/'catalog.sqlite3').read_bytes()==before
    expected=TEXT.replace(r['fragment_before'],r['fragment_after'])
    assert (new/'revised-documents/fixture.md').read_text()==expected
    with sqlite3.connect(base/'catalog.sqlite3') as a,sqlite3.connect(new/'catalog.sqlite3') as b:
        for x,y in zip(a.execute('select data_json from records order by id'),b.execute('select data_json from records order by id'),strict=True):
            x,y=json.loads(x[0]),json.loads(y[0])
            if x['id']=='0':
                assert y['prompt']==r['prompt_after']
                y['prompt']=x['prompt'];y['metadata'].pop('individual_context_review')
            assert x==y
    later=lecture(new,tmp_path,'First old lecture.','First corrected lecture.','later')
    assert (later/'revised-documents/fixture.md').read_text()==expected.replace('First old lecture.','First corrected lecture.')
    with pytest.raises(ValueError,match='Existing individual review'):build(new,p,tmp_path/'repeat')


@pytest.mark.parametrize('damage',['question_condition','answer_choice','partial_line','multiline','explanation_change','unknown_mode'])
def test_attribution_scope_cannot_change_reasoning_choices_or_other_sections(tmp_path,monkeypatch,damage):
    base,p,r=attribution_fixture(tmp_path,monkeypatch)
    if damage=='question_condition':r.update(fragment_before='Which boundary?',fragment_after='Which other boundary?')
    elif damage=='answer_choice':r.update(fragment_before='convergent',fragment_after='divergent')
    elif damage=='partial_line':r.update(fragment_before='—Wrong Author',fragment_after='—Correct Author')
    elif damage=='multiline':r['fragment_after']='—Correct Author\nNew condition.'
    elif damage=='explanation_change':r['explanation_after']='Changed reasoning.'
    elif damage=='unknown_mode':r['mode']='all_fields'
    r['prompt_after']=r['prompt_before'].replace(r['fragment_before'],r['fragment_after'],1)
    obj=json.loads(p.read_text());obj['records']=[r];p.write_text(json.dumps(obj));before=(base/'catalog.sqlite3').read_bytes()
    with pytest.raises(ValueError):build(base,p,tmp_path/'out')
    assert (base/'catalog.sqlite3').read_bytes()==before and not (tmp_path/'out').exists()
