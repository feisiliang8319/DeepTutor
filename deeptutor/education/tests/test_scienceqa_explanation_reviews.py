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
