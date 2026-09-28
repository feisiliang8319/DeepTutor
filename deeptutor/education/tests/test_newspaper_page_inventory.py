import hashlib
import pytest
from deeptutor.education.application.newspaper_page_inventory import describe

def fixture(body='A historical excerpt. Another column may follow.'):
    raw='## 1800-01-16 — passage 3\n\n**Published:** 1800-01-16  **Source page:** https://chroniclingamerica.loc.gov/lccn/sn83025881/1800-01-16/ed-1/seq-2.json\n\n'+body+'\n\n---\n\n'
    row={'kind':'primary_source','library':'us-newspapers-primary-source','start':100,'raw_sha256':hashlib.sha256(raw.encode()).hexdigest(),'metadata':{'published':'1800-01-16','source_page':'https://chroniclingamerica.loc.gov/lccn/sn83025881/1800-01-16/ed-1/seq-2.json'}}
    return row,raw

def test_exact_span_not_synthetic_article():
    row,raw=fixture();before=repr(row);info=describe(row,raw);span=info['body_span_in_source']
    assert raw[span['start']-100:span['end']-100]=='A historical excerpt. Another column may follow.'
    assert info['article_boundaries']=='unknown_do_not_join_excerpts'
    assert info['ocr_correction']=='not_performed' and repr(row)==before

def test_page_identity_preserves_edition_and_sequence():
    row,raw=fixture();first=describe(row,raw)
    raw=raw.replace('ed-1/seq-2','ed-2/seq-2');row['metadata']['source_page']=row['metadata']['source_page'].replace('ed-1/seq-2','ed-2/seq-2');row['raw_sha256']=hashlib.sha256(raw.encode()).hexdigest()
    assert describe(row,raw)['page_id']!=first['page_id']

@pytest.mark.parametrize('change',['date','domain','query','span'])
def test_reject_mismatch(change):
    row,raw=fixture()
    if change=='date':raw=raw.replace('**Published:** 1800-01-16','**Published:** 1800-02-16')
    if change=='domain':raw=raw.replace('chroniclingamerica.loc.gov','chroniclingamerica.loc.gov.evil.example')
    if change=='query':raw=raw.replace('seq-2.json','seq-2.json?other=1')
    if change!='span':row['raw_sha256']=hashlib.sha256(raw.encode()).hexdigest()
    else:raw+='edited'
    with pytest.raises(ValueError):describe(row,raw)

def test_measurements_are_not_quality_approval():
    row,raw=fixture('I a b c \ufffd ° C.');info=describe(row,raw)
    assert info['diagnostics']['replacement_characters']==1
    assert info['diagnostics']['isolated_letters_except_a_i']==3
    assert info['student_approval']=='unchanged' and info['scan_comparison']=='pending'

@pytest.mark.parametrize('lccn',['2018270507','sn2001061779'])
def test_existing_numeric_and_extended_lccn(lccn):
    row,raw=fixture();raw=raw.replace('sn83025881',lccn);row['metadata']['source_page']=row['metadata']['source_page'].replace('sn83025881',lccn);row['raw_sha256']=hashlib.sha256(raw.encode()).hexdigest()
    assert describe(row,raw)['newspaper_lccn']==lccn
