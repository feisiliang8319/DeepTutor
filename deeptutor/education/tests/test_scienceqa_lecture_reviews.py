import pytest
from deeptutor.education.application.scienceqa_lecture_reviews import concept_id, patch_document, validate_roundtrip

TEXT='''# Sample stock
Entries: 2

## sample · Q1
**Subject:** language science **Grade:** grade2 **Skill:** tense
### Question
Choose the past form.
**Options:**
- played
- will play
**Correct answer:** played
### Lecture
All future verbs require will.

### Explanation
Played ends in -ed.
---
## sample · Q2
**Subject:** language science **Grade:** grade2 **Skill:** tense
### Question
Choose the past form again.
**Options:**
- looked
- will look
**Correct answer:** looked
### Lecture
All future verbs require will.

### Explanation
Looked ends in -ed.
---
'''

def recipe():
    before='All future verbs require will.'
    return {concept_id(before):{'lecture_before':before,'lecture_after':'This task uses will + base verb; other expressions can refer to future time.'}}

def test_repeated_lecture_only_preserves_questions_and_answers():
    reviews=recipe()
    after,counts=patch_document(TEXT,reviews)
    assert sum(counts.values())==2
    assert validate_roundtrip('fixture.md',TEXT,after,reviews)==2
    assert after.replace(next(iter(reviews.values()))['lecture_after'],next(iter(reviews.values()))['lecture_before'])==TEXT

def test_stale_review_and_heading_injection_rejected():
    reviews=recipe(); key=next(iter(reviews))
    reviews[key]['lecture_before']='A changed statement'
    with pytest.raises(ValueError,match='hash'):patch_document(TEXT,reviews)
    reviews=recipe(); reviews[key]['lecture_after']='## Question escape'
    with pytest.raises(ValueError,match='replacement'):patch_document(TEXT,reviews)

def test_roundtrip_rejects_unrelated_answer_change():
    reviews=recipe(); after,_=patch_document(TEXT,reviews)
    after=after.replace('Correct answer:** played','Correct answer:** will play')
    with pytest.raises(ValueError,match='Question data changed'):validate_roundtrip('fixture.md',TEXT,after,reviews)

def test_unknown_concepts_are_unchanged():
    after,counts=patch_document(TEXT,{})
    assert after==TEXT and not counts
    assert validate_roundtrip('fixture.md',TEXT,after,{})==0

def test_later_batch_keeps_prior_fix_in_same_document(tmp_path):
    import json,sqlite3
    from deeptutor.education.application.content_stock import parse_file
    from deeptutor.education.application.scienceqa_lecture_reviews import build,sha
    text=TEXT.replace('All future verbs require will.','One old lecture.',1).replace('All future verbs require will.','Another old lecture.',1)
    base=tmp_path/'source-snapshot';base.mkdir();(base/'objects').mkdir()
    source_sha=sha(text);(base/'objects'/(source_sha+'.md')).write_text(text)
    (base/'sources.json').write_text('[]')
    (base/'newspaper-page-queue.json').write_text('{"pages": []}')
    (base/'math-figure-review-assets').mkdir()
    (base/'math-figure-review-assets/checked.svg').write_text('<svg/>')
    with sqlite3.connect(base/'catalog.sqlite3') as c:
        c.execute('create table records(id text primary key, library text, data_json text)')
        for i,row in enumerate(parse_file('scienceqa','fixture.md',text)):
            row.update(id=str(i),library='scienceqa',source_path='scienceqa/raw/fixture.md',source_sha256=source_sha,raw_sha256=sha(text[row['start']:row['end']]),state='needs_curriculum_review')
            c.execute('insert into records values(?,?,?)',(str(i),'scienceqa',json.dumps(row)))
    (base/'summary.json').write_text(json.dumps({'snapshot_id':base.name,'catalog_sha256':sha((base/'catalog.sqlite3').read_bytes()),'committed_batches':1,'records':2}))
    def run(source,original,replacement,name):
        recipe={'library':'scienceqa','expected_total_records':2,'expected_changed_records':1,'reviews':[{'concept_id':concept_id(original),'expected_records':1,'lecture_before':original,'lecture_after':replacement,'references':[{'url':'https://example.test/source'}]}]}
        path=tmp_path/(name+'.json');path.write_text(json.dumps(recipe))
        result=build(source,path,tmp_path/'snapshots')
        return tmp_path/'snapshots'/result['snapshot_id']
    first=run(base,'One old lecture.','First correction.','first')
    second=run(first,'Another old lecture.','Second correction.','second')
    assert (second/'newspaper-page-queue.json').read_bytes()==(base/'newspaper-page-queue.json').read_bytes()
    assert (second/'math-figure-review-assets/checked.svg').read_bytes()==(base/'math-figure-review-assets/checked.svg').read_bytes()
    latest=(second/'revised-documents/fixture.md').read_text()
    assert 'First correction.' in latest and 'Second correction.' in latest
    assert 'old lecture.' not in latest
    manifest=json.loads((second/'revised-documents.json').read_text())
    assert manifest[0]['expected_current_sha256']==sha((first/'revised-documents/fixture.md').read_bytes())
    summary=json.loads((second/'summary.json').read_text())
    assert summary['scienceqa_shared_lectures_corrected']==2
    assert summary['scienceqa_linked_lectures_corrected']==2
    assert summary['scienceqa_batch_linked_lectures_corrected']==1
    with sqlite3.connect(first/'catalog.sqlite3') as a,sqlite3.connect(second/'catalog.sqlite3') as b:
        assert a.execute("select data_json from records where id='0'").fetchone()==b.execute("select data_json from records where id='0'").fetchone()
    with pytest.raises(ValueError,match='already reviewed'):run(first,'One old lecture.','Different correction.','duplicate')


def test_lecture_without_explanation_does_not_consume_next_question():
    text=TEXT.replace('### Explanation\nPlayed ends in -ed.\n','',1)
    reviews=recipe();after,counts=patch_document(text,reviews)
    assert sum(counts.values())==2
    assert validate_roundtrip('fixture.md',text,after,reviews)==2
    from deeptutor.education.application.content_stock import parse_file
    rows=parse_file('scienceqa','fixture.md',after)
    assert 'missing_explanation' in rows[0]['issues']
    assert rows[1]['explanation']=='Looked ends in -ed.'
