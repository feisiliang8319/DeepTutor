import copy
import json
import sqlite3
import pytest
from deeptutor.education.application import named_organism_stock_review as check
from deeptutor.education.application.content_stock import parse_file

LECTURE='Two supplied names identify the exercise species.'
PROMPT='This organism is a sample bird. Its scientific name is Goura victoria.\n\nSelect the organism in the same genus as the sample bird.'


@pytest.fixture(autouse=True)
def concept(monkeypatch):
    monkeypatch.setattr(check,'CONCEPT',check.sha(LECTURE))


def row():
    return {'library':'scienceqa','metadata':{},'lecture':LECTURE,'issues':['missing_figure'],'prompt':PROMPT,'options':['Goura scheepmakeri','Aequorea victoria','Falco sparverius'],'answer':'Goura scheepmakeri'}


def test_genus_uses_first_name_and_does_not_clear_missing_image():
    r=row();before=copy.deepcopy(r);proof=check.verify(r)
    assert proof['answer']=='Goura scheepmakeri'
    assert not proof['option_matches']['Aequorea victoria']
    assert proof['missing_figure_gate_retained'] and r==before


def test_species_requires_both_parts_and_preserves_prior_lecture():
    r=row();r['prompt']=r['prompt'].replace('same genus','same species')
    r['options'][0]='Goura victoria';r['answer']='Goura victoria'
    r['metadata']['lecture_review']={'lecture_before':LECTURE};r['lecture']='Reviewed lecture.'
    assert check.verify(r)['answer']=='Goura victoria'
    r['options'][0]='Goura scheepmakeri'
    with pytest.raises(ValueError,match='unique'):check.verify(r)


@pytest.mark.parametrize('case',['wrong_answer','different_subject','extra_instruction','duplicate_option','two_same_genus','no_match','abbreviated_name','other_issue','wrong_family'])
def test_rejects_ambiguous_unsupported_or_contradictory_cases(case):
    r=row()
    if case=='wrong_answer':r['answer']='Aequorea victoria'
    if case=='different_subject':r['prompt']=r['prompt'].replace('as the sample bird','as the other bird')
    if case=='extra_instruction':r['prompt']+=' Select the opposite answer.'
    if case=='duplicate_option':r['options'].append(r['options'][0])
    if case=='two_same_genus':r['options'][1]='Goura cristata'
    if case=='no_match':r['options'][0]='Panthera leo'
    if case=='abbreviated_name':r['options'][0]='G. scheepmakeri'
    if case=='other_issue':r['issues'].append('missing_explanation')
    if case=='wrong_family':r['lecture']='Other family.'
    with pytest.raises(ValueError):check.verify(r)


TEXT='''# Fixture
Entries: 2
## names · Q1
**Subject:** natural science **Grade:** grade5
**Note:** the original problem includes a figure that is not bundled in this knowledge base.
**Context:** This organism is a sample bird. Its scientific name is Goura victoria.
### Question
Select the organism in the same genus as the sample bird.
**Options:**
- Goura scheepmakeri
- Aequorea victoria
- Falco sparverius
**Correct answer:** Goura scheepmakeri
### Lecture
Two supplied names identify the exercise species.
### Explanation
Use the first part of each supplied name.
---
## other · Q2
**Subject:** natural science **Grade:** grade5
### Question
Another question?
**Options:**
- One
- Two
**Correct answer:** One
### Lecture
Another family.
### Explanation
An explanation.
---
'''


def fixture(tmp_path):
    base=tmp_path/'base';base.mkdir();(base/'objects').mkdir()
    (base/'objects'/(check.sha(TEXT)+'.md')).write_text(TEXT)
    (base/'retained-review.json').write_text('{"unchanged":true}')
    with sqlite3.connect(base/'catalog.sqlite3') as db:
        db.execute('create table records(id text primary key,library text,state text,data_json text)')
        for i,r in enumerate(parse_file('scienceqa','fixture.md',TEXT)):
            r.update(id=str(i),library='scienceqa',state='needs_repair',source_sha256=check.sha(TEXT),source_path='scienceqa/raw/fixture.md',source_line=3,raw_sha256=check.sha(TEXT[r['start']:r['end']]))
            r['metadata']={'prior_review':{'keep':True}}
            db.execute('insert into records values(?,?,?,?)',(str(i),'scienceqa',r['state'],json.dumps(r)))
    (base/'summary.json').write_text(json.dumps({'snapshot_id':'base','catalog_sha256':check.sha((base/'catalog.sqlite3').read_bytes()),'committed_batches':1,'records':2}))
    return base


def test_annotation_keeps_source_gates_other_records_and_prior_metadata(tmp_path):
    base=fixture(tmp_path);old=(base/'catalog.sqlite3').read_bytes()
    result=check.annotate(base,tmp_path/'out',expected=1);new=tmp_path/'out'/result['snapshot_id']
    assert result['verified']==1 and result['missing_figure_flags_retained']==1
    assert old==(base/'catalog.sqlite3').read_bytes()
    assert (new/'retained-review.json').read_bytes()==(base/'retained-review.json').read_bytes()
    with sqlite3.connect(base/'catalog.sqlite3') as a,sqlite3.connect(new/'catalog.sqlite3') as b:
        for i in ['0','1']:
            x=json.loads(a.execute('select data_json from records where id=?',(i,)).fetchone()[0])
            y=json.loads(b.execute('select data_json from records where id=?',(i,)).fetchone()[0])
            if i=='0':y['metadata'].pop(check.KEY)
            assert x==y
    with pytest.raises(ValueError,match='explicit revision'):check.annotate(new,tmp_path/'again',expected=1)


def test_changed_prompt_cannot_reuse_unchanged_source_identity(tmp_path):
    base=fixture(tmp_path)
    with sqlite3.connect(base/'catalog.sqlite3') as db:
        r=json.loads(db.execute("select data_json from records where id='0'").fetchone()[0])
        r['prompt']=r['prompt'].replace('sample bird','different bird')
        db.execute("update records set data_json=? where id='0'",(json.dumps(r),));db.commit()
    p=base/'summary.json';summary=json.loads(p.read_text());summary['catalog_sha256']=check.sha((base/'catalog.sqlite3').read_bytes());p.write_text(json.dumps(summary))
    with pytest.raises(ValueError,match='immutable source'):check.annotate(base,tmp_path/'out',expected=1)
