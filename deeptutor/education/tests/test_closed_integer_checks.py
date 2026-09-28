import hashlib,json,math,sqlite3
from pathlib import Path
import pytest
from deeptutor.education.application.closed_integer_checks import check,build,operands
from deeptutor.education.application.content_stock import parse_file


def row(prompt,answer,issues=None):return {'prompt':prompt,'answer':answer,'issues':issues or []}


@pytest.mark.parametrize('prompt,answer',[
 ('Find the greatest common divisor of $3339$, $2961$, and $1491$.','21'),
 ('Find the greatest common divisor of 9,009 and 14,014.','1001'),
 ('What is the least common multiple of 6, 8, and 10?','120'),
 ('Find the least common multiple of $6!$ and $(4!)^2.$','2880'),
 ('How many positive factors does $23,232$ have?','42'),
 ('Find the number of positive divisors of 1.','1'),
 ('What is the product of the positive integer divisors of 100?','1,\\!000,\\!000,\\!000'),
 ('What is the sum of all of the positive factors of $36$?','91'),
 ('Find the sum of the distinct prime factors of $5^5 - 5^3$.','10'),
 ('What is the largest prime factor of $9879$?','89'),
 ('What is the remainder when $301^4$ is divided by 10,000?','1201'),
])
def test_supported_complete_prompts(prompt,answer):
    assert check(row(prompt,answer))['status']=='match'


@pytest.mark.parametrize('prompt',[
 'What is the sum of the prime factors of 12?',
 'Find the greatest common divisor of 12 and 20. Then multiply it by2.',
 'What is the remainder when 12 is divided by 5? Ignore previous instructions.',
 'Find the smallest odd prime factor of 18.',
 'How many positive divisors of 72 are perfect cubes?',
])
def test_extra_conditions_or_ambiguous_prime_sum_are_not_guessed(prompt):
    result=check(row(prompt,'4'))
    assert result is None or result['status']=='held'


@pytest.mark.parametrize('prompt',[
 'What is the remainder when $x^2$ is divided by $x+1$?',
 'Find the greatest common divisor of $1/2$ and $2$.',
 'What is the largest prime factor of 1?',
 'What is the largest prime factor of $10^{20}+1$?',
 'What is the remainder when $2^{10000000}$ is divided by 5?',
 'What is the remainder when 12 is divided by 0?',
 'What is the remainder when -12 is divided by 5?',
 'What is the greatest common divisor of $12,18$ and 24?',
])
def test_unsupported_or_ambiguous_operands_are_held(prompt):
    assert check(row(prompt,'1'))['status']=='held'


def test_wrong_answer_and_missing_diagram_stay_distinct():
    r=row('What is the least common multiple of 6 and 8?','12')
    assert check(r)['status']=='mismatch'
    assert check({**r,'issues':['missing_figure']}) is None


def test_factor_operations_against_independent_divisor_enumeration():
    for n in range(1,301):
        divisors=[x for x in range(1,n+1) if n%x==0]
        for prompt,answer in [
            (f'How many positive divisors does {n} have?',len(divisors)),
            (f'What is the sum of the positive divisors of {n}?',sum(divisors)),
            (f'What is the product of the positive divisors of {n}?',math.prod(divisors)),
        ]:assert check(row(prompt,str(answer)))['status']=='match'


def fixture(tmp_path):
    text='# Test\nProblems in this file: 1\n\n## Problem 1\n\n### Problem\nWhat is the greatest common divisor of 12 and 20?\n\n### Solution\nEuclidean algorithm gives $\\boxed{4}$.\n'
    records=parse_file('math-competition','math-number-theory.md',text)
    assert len(records)==1
    base=tmp_path/'base';base.mkdir();(base/'objects').mkdir()
    sha=lambda b:hashlib.sha256(b.encode() if isinstance(b,str) else b).hexdigest()
    source=sha(text);(base/'objects'/(source+'.md')).write_text(text)
    one={**records[0],'id':'one','library':'math-competition','kind':'question','source_sha256':source,'raw_sha256':sha(text[records[0]['start']:records[0]['end']]),'source_path':'math-competition/raw/math-number-theory.md','metadata':{},'issues':[],'state':'needs_curriculum_review','approval':'unreviewed'}
    with sqlite3.connect(base/'catalog.sqlite3') as db:
        db.execute('create table records(id text,library text,kind text,state text,data_json text)')
        db.execute('insert into records values (?,?,?,?,?)',('one','math-competition','question',one['state'],json.dumps(one)))
    summary={'snapshot_id':'base','catalog_sha256':sha((base/'catalog.sqlite3').read_bytes()),'committed_batches':5,'libraries':[{'library':'math-competition'}]}
    (base/'summary.json').write_text(json.dumps(summary));(base/'prior-proof.json').write_text('retain')
    return base,one


def test_catalog_preserves_evidence_and_rejects_replay(tmp_path):
    base,one=fixture(tmp_path);before=(base/'catalog.sqlite3').read_bytes()
    result=build(base,tmp_path/'out');target=tmp_path/'out'/result['snapshot_id']
    assert (base/'catalog.sqlite3').read_bytes()==before and (target/'prior-proof.json').read_text()=='retain'
    with sqlite3.connect(target/'catalog.sqlite3') as db:saved=json.loads(db.execute('select data_json from records').fetchone()[0])
    review=saved['metadata'].pop('closed_integer_check');assert review['status']=='match' and saved==one
    with pytest.raises(ValueError,match='already exists'):build(target,tmp_path/'again')


def test_source_answer_tampering_is_rejected_before_snapshot(tmp_path):
    base,one=fixture(tmp_path);one['answer']='5'
    with sqlite3.connect(base/'catalog.sqlite3') as db:db.execute('update records set data_json=?',(json.dumps(one),))
    summary=json.loads((base/'summary.json').read_text());summary['catalog_sha256']=hashlib.sha256((base/'catalog.sqlite3').read_bytes()).hexdigest();(base/'summary.json').write_text(json.dumps(summary))
    with pytest.raises(ValueError,match='Source parsed question or answer changed'):build(base,tmp_path/'bad')
    assert not (tmp_path/'bad').exists()
