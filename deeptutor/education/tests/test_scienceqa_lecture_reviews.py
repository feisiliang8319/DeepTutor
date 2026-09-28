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
