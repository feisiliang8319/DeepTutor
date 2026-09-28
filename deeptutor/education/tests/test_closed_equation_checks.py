import pytest
from fractions import Fraction
from deeptutor.education.application.closed_equation_checks import solve,check,Unsupported

@pytest.mark.parametrize('equation,roots',[
 ('2x+3=7',[2]),('0.1x+0.2=0.3',[1]),
 ('x^2-3x+2=0',[1,2]),('(x+3)^2=0',[-3]),
 (r'\frac{1}{2}+\frac{1}{x}=\frac{5}{6}',[3]),
 ('(x^2-1)/(x-1)=0',[-1]),('x/(x-1)=1',[]),
 ('x/x=0',[]), ('(x+1)/(x+1)=x', [1]),
])
def test_complete_roots_not_just_source_answer_substitution(equation,roots):
    assert solve(equation,'x')['solutions']==list(map(Fraction,roots))


def test_cross_multiplication_excludes_original_poles():
    result=solve('(x^2-1)/(x-1)=0','x')
    assert result['excluded_poles']==['1'] and result['nonzero_conditions']
    row={'prompt':r'Solve for $x$: $x^2-3x+2=0$.','answer':'1','issues':[]}
    assert check(row)['status']=='mismatch'
    assert check({**row,'answer':'2,1'})['status']=='match'

@pytest.mark.parametrize('equation',[
 'x/x=1','x^3=1','x^2=2','x^2=-1','x+y=2','x/0=1',
 'x=1=2',r'\log x=1',r'\sqrt{x}=2','x^x=2',
])
def test_unsupported_nonfinite_or_complex_forms_are_held(equation):
    with pytest.raises((Unsupported,ValueError)):solve(equation,'x')


def test_whole_prompt_scope_and_answer_notation():
    row={'prompt':r'Solve for $x$: $$2x+3=7.$$','answer':'x=2','issues':[]}
    assert check(row)['status']=='match'
    assert check({**row,'issues':['missing_figure']}) is None
    assert check({**row,'prompt':r'Solve for the positive value of $x$: $x^2=4$.'}) is None
    assert check({**row,'prompt':r'Solve for $x$: $x^2=4$. Assume x>0.'}) is None
    assert check({**row,'answer':'2 or 3'})['status']=='held'
    assert check({**row,'answer':'2,3,4'})['status']=='held'

def test_catalog_keeps_source_prior_reviews_and_approval(tmp_path):
    import hashlib,json,sqlite3
    from deeptutor.education.application.closed_equation_checks import build
    digest=lambda data:hashlib.sha256(data).hexdigest()
    base=tmp_path/'base';base.mkdir();(base/'objects').mkdir()
    original='Solve for $x$: $x^2-3x+2=0$.\nAnswer: 1\n'
    source=digest(original.encode());(base/'objects'/(source+'.md')).write_text(original)
    row={'id':'algebra-1','library':'math-competition','kind':'question','prompt':'Solve for $x$: $x^2-3x+2=0$.','answer':'1','issues':[], 'metadata':{'closed_arithmetic_check':{'status':'held'}},'source_sha256':source,'start':0,'end':len(original),'raw_sha256':source,'state':'needs_curriculum_review','approval':'unreviewed'}
    other={**row,'id':'science-1','library':'scienceqa','metadata':{'individual_explanation_review':{'preserved':True}}}
    with sqlite3.connect(base/'catalog.sqlite3') as db:
        db.execute('create table records (id text,library text,kind text,state text,data_json text)')
        for item in (row,other):db.execute('insert into records values (?,?,?,?,?)',(item['id'],item['library'],item['kind'],item['state'],json.dumps(item)))
    before=(base/'catalog.sqlite3').read_bytes()
    summary={'snapshot_id':'base','catalog_sha256':digest(before),'committed_batches':4,'libraries':[{'library':'math-competition'}]}
    (base/'summary.json').write_text(json.dumps(summary));(base/'prior-review-queue.json').write_text('prior evidence')
    result=build(base,tmp_path/'output');folder=tmp_path/'output'/result['snapshot_id']
    assert (base/'catalog.sqlite3').read_bytes()==before
    assert (folder/'objects'/(source+'.md')).read_text()==original
    assert (folder/'prior-review-queue.json').read_text()=='prior evidence'
    with sqlite3.connect(folder/'catalog.sqlite3') as db:
        saved=json.loads(db.execute('select data_json from records where id=?',(row['id'],)).fetchone()[0])
        assert json.loads(db.execute('select data_json from records where id=?',(other['id'],)).fetchone()[0])==other
    assert saved['answer']==row['answer'] and saved['approval']=='unreviewed'
    assert saved['metadata']['closed_arithmetic_check']==row['metadata']['closed_arithmetic_check']
    assert saved['state']=='needs_fact_check'
    assert saved['metadata']['closed_equation_check']['status']=='mismatch'
    assert saved['metadata']['closed_equation_check']['solutions']==['1','2']
    assert saved['metadata']['closed_equation_check']['checker_dependencies']['numeric_parser_sha256']
    with pytest.raises(ValueError,match='already exists'):build(folder,tmp_path/'repeated')
    with sqlite3.connect(base/'catalog.sqlite3') as db:db.execute("update records set state='changed'")
    with pytest.raises(ValueError,match='Base changed'):build(base,tmp_path/'tampered')
