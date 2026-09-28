import hashlib,json,sqlite3
from fractions import Fraction
from itertools import combinations
import pytest
from deeptutor.education.application.closed_binomial_checks import evaluate_binomial,check,build
from deeptutor.education.application.closed_math_checks import Unsupported

def row(prompt,answer,issues=None):return {'prompt':prompt,'answer':answer,'issues':issues or []}
def test_exact_counts_against_enumerated_subsets():
 for n in range(9):
  for k in range(n+1):
   assert evaluate_binomial(r'\binom{'+str(n)+'}{'+str(k)+'}')==sum(1 for _ in combinations(range(n),k))
@pytest.mark.parametrize('expression,expected',[(r'\dbinom{1293}{1}',1293),(r'\dbinom{505}{505}',1),(r'\binom{9}{2}\times\binom{7}{2}',756),(r'\frac{\binom{10}{2}}{45}',1),(r'-\binom{5}{2}^2',-100),(r'\binom{5}{2}+\tbinom{6}{3}',30),(r'\binom{0}{0}',1),(r'\binom{6}{2}!',1307674368000)])
def test_composition_and_boundaries(expression,expected):assert evaluate_binomial(expression)==expected
@pytest.mark.parametrize('expression',[r'\binom{-1}{0}',r'\binom{4}{5}',r'\binom{4.5}{2}',r'\binom{10001}{1}',r'\binom{n}{2}',r'\binom{6}{2}.__class__',r'\binom{6}{2};__import__("os")',r'\binom{5}'])
def test_outside_domain_or_notation_is_held(expression):
 with pytest.raises((Unsupported,ValueError)):evaluate_binomial(expression)
def test_full_prompt_and_figure_gates():
 assert check(row(r'Compute $\binom{8}{2}$.','28'))['status']=='match'
 assert check(row(r'Compute $\binom{8}{2}$.','29'))['status']=='mismatch'
 assert check(row(r'Compute $\binom{n}{2}$.','28'))['status']=='held'
 assert check(row(r'If some objects are identical, compute $\binom{8}{2}$.','28')) is None
 assert check(row(r'Compute $\binom{8}{2}$.','28',['unrendered_diagram'])) is None
 assert check(row('Compute $8+2$.','10')) is None

from deeptutor.education.application.content_stock import parse_file

def fixture(tmp_path):
    text='# Test\nProblems in this file: 1\n\n## Problem 1\n\n### Problem\nCompute $\\binom{8}{2}$.\n\n### Solution\nEnumerated pairs give $\\boxed{28}$.\n'
    records=parse_file('math-competition','math-counting-and-probability.md',text)
    assert len(records)==1
    base=tmp_path/'base';base.mkdir();(base/'objects').mkdir()
    sha=lambda b:hashlib.sha256(b.encode() if isinstance(b,str) else b).hexdigest()
    source=sha(text);(base/'objects'/(source+'.md')).write_text(text)
    one={**records[0],'id':'one','library':'math-competition','kind':'question','source_sha256':source,'raw_sha256':sha(text[records[0]['start']:records[0]['end']]),'source_path':'math-competition/raw/math-counting-and-probability.md','metadata':{},'issues':[],'state':'needs_curriculum_review','approval':'unreviewed'}
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
    review=saved['metadata'].pop('closed_binomial_check');assert review['status']=='match' and saved==one
    with pytest.raises(ValueError,match='already exists'):build(target,tmp_path/'again')


def test_source_answer_tampering_is_rejected_before_snapshot(tmp_path):
    base,one=fixture(tmp_path);one['answer']='29'
    with sqlite3.connect(base/'catalog.sqlite3') as db:db.execute('update records set data_json=?',(json.dumps(one),))
    summary=json.loads((base/'summary.json').read_text());summary['catalog_sha256']=hashlib.sha256((base/'catalog.sqlite3').read_bytes()).hexdigest();(base/'summary.json').write_text(json.dumps(summary))
    with pytest.raises(ValueError,match='Source parsed question or answer changed'):build(base,tmp_path/'bad')
    assert not (tmp_path/'bad').exists()

@pytest.mark.parametrize('answer,status',[(r'16,\!471','match'),('16,471','match'),('16,47','held'),('16,471,0','held')])
def test_answer_grouping_does_not_guess_malformed_numbers(answer,status):
 assert check(row(r'Compute $\dbinom{182}{180}$.',answer))['status']==status
