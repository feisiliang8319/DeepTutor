import json
from pathlib import Path
import sqlite3
import pytest
from deeptutor.education.application.content_stock import parse_file
from deeptutor.education.application.history_answer_reviews import build, patch_document, sha

TEXT = '''# History fixture
Entries: 2
## First year?
### Question
First year?
### Answer
The event began in **76 BCE**. Other unreviewed claims stay.
---
## Second year?
### Question
Second year?
### Answer
Another event began in **76 BCE**.
---
'''


def fixture(tmp_path):
    base = tmp_path/'base'; base.mkdir(); (base/'objects').mkdir()
    (base/'objects'/(sha(TEXT)+'.md')).write_text(TEXT)
    (base/'unrelated-review.json').write_text('{"unchanged":true}')
    with sqlite3.connect(base/'catalog.sqlite3') as db:
        db.execute('create table records(id text primary key, library text, state text, data_json text)')
        for i,row in enumerate(parse_file('world-history-1500','fixture.md',TEXT)):
            row.update(id=str(i),library='world-history-1500',state='needs_fact_check',source_path='world-history-1500/raw/fixture.md',source_sha256=sha(TEXT),raw_sha256=sha(TEXT[row['start']:row['end']]),fingerprint='original-'+str(i))
            db.execute('insert into records values(?,?,?,?)',(str(i),row['library'],row['state'],json.dumps(row)))
    (base/'summary.json').write_text(json.dumps({'snapshot_id':'base','catalog_sha256':sha((base/'catalog.sqlite3').read_bytes()),'committed_batches':1,'records':2}))
    return base


def recipe(base,tmp_path,key='0'):
    with sqlite3.connect(base/'catalog.sqlite3') as db:
        row=json.loads(db.execute('select data_json from records where id=?',(key,)).fetchone()[0])
    r={'record_id':key,'source_title':row['title'],**{k:row[k] for k in ('source_path','source_sha256','raw_sha256')},'fragment_before':'76 BCE','fragment_after':'73 BCE','prompt_before':row['prompt'],'answer_before':row['answer'],'answer_after':row['answer'].replace('76 BCE','73 BCE'),'references':[{'url':'https://example.test/source'}]}
    p=tmp_path/('recipe-'+key+'.json');p.write_text(json.dumps({'library':'world-history-1500','expected_total_records':2,'expected_changed_records':1,'records':[r]}))
    return p,r


def test_corrects_only_selected_answer_and_retains_originals_and_gates(tmp_path):
    base=fixture(tmp_path);p,r=recipe(base,tmp_path);old=(base/'catalog.sqlite3').read_bytes()
    result=build(base,p,tmp_path/'out');new=tmp_path/'out'/result['snapshot_id']
    text=(new/'revised-documents/fixture.md').read_text()
    assert text==TEXT.replace('76 BCE','73 BCE',1)
    assert (base/'catalog.sqlite3').read_bytes()==old
    assert (new/'unrelated-review.json').read_bytes()==(base/'unrelated-review.json').read_bytes()
    with sqlite3.connect(new/'catalog.sqlite3') as db:
        row=json.loads(db.execute("select data_json from records where id='0'").fetchone()[0])
        assert row['state']=='needs_fact_check' and row['approval']=='unreviewed'
        assert row['issues']==['historical_fact_check'] and row['fingerprint']=='original-0'
        assert row['metadata']['historical_answer_review']['answer_before']==r['answer_before']
    with pytest.raises(ValueError,match='Existing answer review'):
        build(new,p,tmp_path/'replay')


@pytest.mark.parametrize('case',['source','wrong_answer','unreviewed_extra','heading','duplicate','missing_reference'])
def test_rejects_stale_or_scope_expanding_recipe(tmp_path,case):
    base=fixture(tmp_path);p,r=recipe(base,tmp_path)
    if case=='source':r['raw_sha256']='0'*64
    if case=='wrong_answer':r['answer_before']='Unrelated'
    if case=='unreviewed_extra':r['answer_after']+=' Unreviewed assertion.'
    if case=='heading':
        r['fragment_after']='\n## New question';r['answer_after']=r['answer_before'].replace('76 BCE',r['fragment_after'])
    if case=='missing_reference':r['references']=[]
    obj=json.loads(p.read_text());obj['records']=[r,r] if case=='duplicate' else [r];p.write_text(json.dumps(obj))
    with pytest.raises(ValueError):build(base,p,tmp_path/'out')


def test_later_same_file_correction_keeps_prior_review(tmp_path):
    base=fixture(tmp_path);p,_=recipe(base,tmp_path)
    first=build(base,p,tmp_path/'out');first=tmp_path/'out'/first['snapshot_id']
    p,_=recipe(first,tmp_path,'1');second=build(first,p,tmp_path/'out');second=tmp_path/'out'/second['snapshot_id']
    assert (second/'revised-documents/fixture.md').read_text()==TEXT.replace('76 BCE','73 BCE')
    m=json.loads((second/'revised-documents.json').read_text())
    assert m[0]['expected_current_sha256']==sha((first/'revised-documents/fixture.md').read_bytes())
    assert json.loads((second/'summary.json').read_text())['historical_answer_passages_corrected']==2


def test_duplicate_source_titles_cannot_change_multiple_questions():
    row=parse_file('world-history-1500','fixture.md',TEXT)[0]
    r={'source_title':row['title'],'prompt_before':row['prompt'],'answer_before':row['answer'],'answer_after':row['answer'].replace('76 BCE','73 BCE'),'fragment_before':'76 BCE','fragment_after':'73 BCE'}
    with pytest.raises(ValueError):patch_document('fixture.md',TEXT.replace('Entries: 2','Entries: 4')+TEXT,[r])
