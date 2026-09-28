import copy
from pathlib import Path
import json
import sqlite3
import pytest
from deeptutor.education.application.content_stock import process, parse_file
from deeptutor.education.application.qasc_fact_reviews import build, patch_document, sha, NOTICE

FACT='All plants are of bush type.'
REVIEW={'fact_id':sha(FACT),'fact_before':FACT,'correction':'Bushes are one plant growth form; trees and grasses are also plants.','reason':'A subset was confused with the whole category.','expected_records':1,'references':['https://plants.usda.gov/assets/docs/PLANTS_Help_Document.pdf']}
TEXT='''# QASC
Problems in this file: 2

## biology · Q1
**Subject:** natural science  **Dataset id:** synthetic-1

### Question
Which group contains trees?

**Options:**
- A) plants
- B) insects

**Correct answer:** A) plants

### Reasoning (fact chain)

**Fact 1:** All plants are of bush type.
**Fact 2:** Trees are plants.
**Combined:** Trees are bushes.

---

## biology · Q2
**Subject:** natural science  **Dataset id:** synthetic-2

### Question
What is the formula for water?

**Options:**
- A) H2O
- B) CO2

**Correct answer:** A) H2O

### Reasoning (fact chain)

**Fact 1:** Water contains hydrogen.
**Fact 2:** Water contains oxygen.
**Combined:** Water contains hydrogen and oxygen.

---
'''


def test_withdraws_entire_inference_preserves_question_and_next_record():
    after,count=patch_document('qasc-biology.md',TEXT,{sha(FACT):REVIEW})
    assert count==1 and 'Trees are bushes.' not in after and NOTICE in after
    old=parse_file('qasc','qasc-biology.md',TEXT);new=parse_file('qasc','qasc-biology.md',after)
    for a,b in zip(old,new,strict=True):
        for key in ('prompt','answer','options','approval','issues','metadata'):
            assert a[key]==b[key]
    assert old[1]['explanation']==new[1]['explanation']


def test_case_sensitive_fact_identity_does_not_change_similar_text():
    after,count=patch_document('qasc-biology.md',TEXT,{sha(FACT.lower()):{**REVIEW,'fact_before':FACT.lower()}})
    assert after==TEXT and count==0


def test_missing_fact_refuses_partial_patch():
    with pytest.raises(ValueError,match='exactly two'):
        patch_document('qasc-biology.md',TEXT.replace('**Fact 2:** Trees are plants.',''),{sha(FACT):REVIEW})


def test_catalog_source_and_prior_metadata_preserved(tmp_path):
    base=tmp_path/'base';base.mkdir();(base/'objects').mkdir()
    source_sha=sha(TEXT);(base/'objects'/(source_sha+'.md')).write_text(TEXT)
    (base/'sources.json').write_text('[]')
    with sqlite3.connect(base/'catalog.sqlite3') as db:
        db.execute('create table records(id text primary key, library text, state text, data_json text)')
        for i,row in enumerate(parse_file('qasc','fixture.md',TEXT)):
            row.update(id=str(i),library='qasc',source_path='qasc/raw/fixture.md',source_sha256=source_sha,raw_sha256=sha(TEXT[row['start']:row['end']]),state='needs_curriculum_review')
            row['metadata']['prior_evidence']='must remain'
            db.execute('insert into records values(?,?,?,?)',(str(i),'qasc',row['state'],json.dumps(row)))
    (base/'summary.json').write_text(json.dumps({'snapshot_id':base.name,'catalog_sha256':sha((base/'catalog.sqlite3').read_bytes()),'committed_batches':1,'libraries':[{'library':'qasc','states':{'needs_curriculum_review':2}}]}))
    recipe={'library':'qasc','expected_records':2,'expected_changed_records':1,'reviews':[REVIEW]}
    path=tmp_path/'recipe.json';path.write_text(json.dumps(recipe))
    result=build(base,path,tmp_path/'snapshots');target=tmp_path/'snapshots'/result['snapshot_id']
    assert (target/'objects'/(source_sha+'.md')).read_text()==TEXT
    with sqlite3.connect(target/'catalog.sqlite3') as db:
        state,raw=db.execute('select state,data_json from records where id="0"').fetchone();row=json.loads(raw)
        assert state==row['state']=='needs_fact_check' and row['approval']=='unreviewed'
        assert row['answer']=='A) plants' and row['metadata']['prior_evidence']=='must remain'
        assert row['metadata']['fact_chain_review']['explanation_before'].endswith('Trees are bushes.')
        assert db.execute('select state from records where id="1"').fetchone()[0]=='needs_curriculum_review'
    with pytest.raises(ValueError,match='already applied'):build(target,path,tmp_path/'snapshots')
    # A later correction in the same source must retain the first review.
    (target/'math-review-assets').mkdir();(target/'math-review-assets/figure.svg').write_text('<svg/>')
    second_fact='Trees are plants.'
    second_review={**REVIEW,'fact_id':sha(second_fact),'fact_before':second_fact,
                   'correction':'Trees are woody plants.','reason':'Add the relevant growth-form scope.'}
    path2=tmp_path/'second.json';path2.write_text(json.dumps({**recipe,'reviews':[second_review]}))
    result2=build(target,path2,tmp_path/'snapshots');target2=tmp_path/'snapshots'/result2['snapshot_id']
    latest=(target2/'qasc-revised-documents/fixture.md').read_text()
    assert REVIEW['correction'] in latest and second_review['correction'] in latest
    assert 'Trees are bushes.' not in latest
    assert (target2/'math-review-assets/figure.svg').read_text()=='<svg/>'
    manifest=json.loads((target2/'qasc-revised-documents.json').read_text())
    assert manifest[0]['expected_current_sha256']==sha((target/'qasc-revised-documents/fixture.md').read_bytes())
    report=json.loads((target2/'summary.json').read_text())
    assert report['qasc_reviewed_fact_groups']==2 and report['qasc_inferences_withdrawn']==1
    with sqlite3.connect(target2/'catalog.sqlite3') as db:
        row=json.loads(db.execute("select data_json from records where id='0'").fetchone()[0])
        assert row['metadata']['fact_chain_review']['previous_review']['reviews']==[REVIEW]
        assert row['metadata']['fact_chain_review']['explanation_before'].endswith('Trees are bushes.')
    third_fact='Water contains oxygen.'
    third_review={**REVIEW,'fact_id':sha(third_fact),'fact_before':third_fact,
                  'correction':'Water molecules contain oxygen atoms chemically bonded to hydrogen.',
                  'reason':'Distinguish oxygen atoms from dissolved oxygen gas.'}
    path3=tmp_path/'third.json';path3.write_text(json.dumps({**recipe,'reviews':[third_review]}))
    result3=build(target2,path3,tmp_path/'snapshots');target3=tmp_path/'snapshots'/result3['snapshot_id']
    latest=(target3/'qasc-revised-documents/fixture.md').read_text()
    assert all(r['correction'] in latest for r in [REVIEW,second_review,third_review])
    with sqlite3.connect(target2/'catalog.sqlite3') as a,sqlite3.connect(target3/'catalog.sqlite3') as b:
        assert a.execute("select data_json from records where id='0'").fetchone()==b.execute("select data_json from records where id='0'").fetchone()
    report=json.loads((target3/'summary.json').read_text())
    assert report['qasc_reviewed_fact_groups']==3 and report['qasc_inferences_withdrawn']==2
    bad=copy.deepcopy(recipe);bad['reviews'][0]['expected_records']=2;path.write_text(json.dumps(bad))
    with pytest.raises(ValueError,match='population changed'):build(base,path,tmp_path/'snapshots')
