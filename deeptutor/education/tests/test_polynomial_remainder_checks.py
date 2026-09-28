from fractions import Fraction
from itertools import product
import hashlib,json,sqlite3
import pytest
from deeptutor.education.application.polynomial_remainder_checks import check,divide,build
from deeptutor.education.application.closed_math_checks import Unsupported
from deeptutor.education.application.content_stock import parse_file


def row(prompt,answer,issues=None):return {'prompt':prompt,'answer':answer,'issues':issues or []}


@pytest.mark.parametrize('prompt,answer',[
 ('Find the remainder when $x^3 - 3x + 5$ is divided by $x + 2.$','3'),
 ('What is the remainder when $x^3$ is divided by $x^2 + 5x + 1.$','24x+5'),
 ('Find the remainder when $x^4 + 1$ is divided by $x^2 - 3x + 5.$','-3x-19'),
 ('Find the remainder when $x^4 + 2$ is divided by $(x - 2)^2.$','32x-46'),
 ('What is the remainder when $x^2+7x-5$ divides $2x^4+11x^3-42x^2-60x+47$?','2x-8'),
 ('Find the remainder when $3y^4-4y^3+5y^2-13y+4$ is divided by $3y - 2.$',r'-\frac{82}{27}'),
 ('Find the remainder when $x^9-x^6+x^3-1$ is divided by $x^2+x+1.$','0'),
 ('What is the remainder when $0$ is divided by $x+1$?','0'),
 ('Find the remainder when $x/2+1/3$ is divided by $x-1$.',r'\frac{5}{6}'),
])
def test_exact_source_examples_and_rational_coefficients(prompt,answer):assert check(row(prompt,answer))['status']=='match'


def test_expected_expression_must_be_the_complete_remainder():
    r=row('Find the remainder when $x^3$ is divided by $x^2+5x+1$.','5')
    assert check(r)['status']=='mismatch'
    assert check({**r,'answer':'x^3'})['status']=='mismatch'
    assert check({**r,'answer':'24y+5'})['status']=='held'
    assert check({**r,'issues':['unrendered_diagram']}) is None
    assert check({**r,'prompt':r['prompt']+' Then evaluate it at x=0.'}) is None


@pytest.mark.parametrize('a,b',[
 ('x/x','x+1'),('x+y','x+1'),('x','y+1'),('x','0'),('x','2'),
 ('x^{1000}','x+1'),('x^{x}','x+1'),(r'\sin x','x+1'),
])
def test_outside_bounded_polynomial_domain_is_held(a,b):
    assert check(row(f'Find the remainder when ${a}$ is divided by ${b}$.','0'))['status']=='held'


def test_long_division_against_constructed_identity_grid():
    for a,b,c in product(range(-2,3),repeat=3):
        # (ax+b)(x^2+1)+cx+1; remainder cx+1 has degree<2.
        dividend={3:Fraction(a),2:Fraction(b),1:Fraction(a+c),0:Fraction(b+1)}
        dividend={e:v for e,v in dividend.items() if v}
        q,r=divide(dividend,{2:Fraction(1),0:Fraction(1)})
        assert q=={e:v for e,v in {1:Fraction(a),0:Fraction(b)}.items() if v}
        assert r=={e:v for e,v in {1:Fraction(c),0:Fraction(1)}.items() if v}


def fixture(tmp_path):
    text='# Test\nProblems in this file: 1\n\n## Problem 1\n\n### Problem\nFind the remainder when $x^3 - 3x + 5$ is divided by $x + 2.$\n\n### Solution\nThe remainder is $\\boxed{3}$.\n'
    records=parse_file('math-competition','math-algebra.md',text);assert len(records)==1
    base=tmp_path/'base';base.mkdir();(base/'objects').mkdir()
    sha=lambda b:hashlib.sha256(b.encode() if isinstance(b,str) else b).hexdigest()
    source=sha(text);(base/'objects'/(source+'.md')).write_text(text)
    one={**records[0],'id':'one','library':'math-competition','kind':'question','source_sha256':source,'raw_sha256':sha(text[records[0]['start']:records[0]['end']]),'source_path':'math-competition/raw/math-algebra.md','metadata':{'closed_integer_check':{'status':'held'}},'issues':[],'state':'needs_curriculum_review','approval':'unreviewed'}
    with sqlite3.connect(base/'catalog.sqlite3') as db:
        db.execute('create table records(id text,library text,kind text,state text,data_json text)');db.execute('insert into records values (?,?,?,?,?)',('one','math-competition','question',one['state'],json.dumps(one)))
    (base/'summary.json').write_text(json.dumps({'snapshot_id':'base','catalog_sha256':sha((base/'catalog.sqlite3').read_bytes()),'committed_batches':5,'libraries':[{'library':'math-competition'}]}));(base/'prior-proof.json').write_text('retain')
    return base,one


def test_catalog_preserves_prior_checks_and_original_approval(tmp_path):
    base,one=fixture(tmp_path);before=(base/'catalog.sqlite3').read_bytes()
    result=build(base,tmp_path/'out');target=tmp_path/'out'/result['snapshot_id']
    assert (base/'catalog.sqlite3').read_bytes()==before and (target/'prior-proof.json').read_text()=='retain'
    with sqlite3.connect(target/'catalog.sqlite3') as db:saved=json.loads(db.execute('select data_json from records').fetchone()[0])
    review=saved['metadata'].pop('polynomial_remainder_check');assert review['status']=='match' and saved==one
    with pytest.raises(ValueError,match='already exists'):build(target,tmp_path/'again')


def test_source_answer_tampering_rejected_before_snapshot(tmp_path):
    base,one=fixture(tmp_path);one['answer']='4'
    with sqlite3.connect(base/'catalog.sqlite3') as db:db.execute('update records set data_json=?',(json.dumps(one),))
    summary=json.loads((base/'summary.json').read_text());summary['catalog_sha256']=hashlib.sha256((base/'catalog.sqlite3').read_bytes()).hexdigest();(base/'summary.json').write_text(json.dumps(summary))
    with pytest.raises(ValueError,match='Source parsed question or answer changed'):build(base,tmp_path/'bad')
    assert not (tmp_path/'bad').exists()


def test_numeric_remainders_do_not_enter_polynomial_queue():
    assert check(row('What is the remainder when $7^{2010}$ is divided by $100$?','49')) is None
    assert check(row(r'Find the remainder when $3 \times 13 \times \ldots \times 193$ is divided by $5$.','1')) is None
