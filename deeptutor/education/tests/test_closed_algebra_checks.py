import pytest
from deeptutor.education.application.closed_algebra_checks import compare,check,Unsupported

@pytest.mark.parametrize('expression,answer',[
 ('(2x-5)(x+7)-(x+5)(2x-1)','-30'),
 ('(x+y)^2','x^2+2xy+y^2'),
 ('(2x^2+7x-3)-(x^2+5x-12)','x^2+2x+9'),
 (r'\frac{bx(a^2x^2+2a^2y^2+b^2y^2)+ay(a^2x^2+2b^2x^2+b^2y^2)}{bx+ay}','(ax+by)^2'),
 (r'\frac{1}{2}x+\frac{x}{3}',r'\frac{5x}{6}'),
 (r'\left(\frac{1}{2k}\right)^{-2}\cdot(-k)^3','-4k^5'),
 ('-x^2','-(x*x)'),
 (r'\frac{x}{y}\cdot y','x'),
 (r'\frac xy',r'\frac{x}{y}'),
 ('0.25x',r'\frac{x}{4}'),
])
def test_exact_identities(expression,answer):
    assert compare(expression,answer)['status']=='match'


def test_nonzero_domain_conditions_are_retained_for_both_sides():
    result=compare('(x^2-1)/(x-1)','x+1')
    assert result['status']=='match' and result['nonzero_conditions'][0]['side']=='source_expression'
    result=compare('1','x/x')
    assert result['status']=='match' and result['nonzero_conditions'][0]['side']=='source_answer'
    assert 'Equal domains' in result['scope']


def test_identity_is_not_a_few_matching_substitutions():
    assert compare('x*(x-1)*(x+1)','0')['status']=='mismatch'
    assert compare('(x+y)^2','x^2+y^2')['status']=='mismatch'


@pytest.mark.parametrize('expression',[
 r'\sqrt{x^2}',r'\sin x','cosx','i^2','x^{1/2}','x^12','x^{100}',
 'x/(x-x)', '0^0',r'\frac(x+1)(x+2)','x/y z','x;__import__("os")',
 '(a+b+c+d+f+g)^16', 'x'*4100,
])
def test_unsupported_ambiguous_or_unbounded_forms_hold(expression):
    with pytest.raises((Unsupported,ValueError)):
        compare(expression,'0')


def test_full_question_and_figure_scope():
    row={'prompt':'Simplify $(x+y)^2$.','answer':'x^2+2xy+y^2','issues':[]}
    assert check(row)['status']=='match'
    assert check({**row,'issues':['missing_figure']}) is None
    assert check({**row,'prompt':'Assume x=y. Simplify $(x+y)^2$.'}) is None
    assert check({**row,'prompt':'Compute $2+2$.'}) is None


def test_catalog_keeps_source_prior_reviews_and_approval(tmp_path):
    import hashlib,json,sqlite3
    from deeptutor.education.application.closed_algebra_checks import build
    digest=lambda data:hashlib.sha256(data).hexdigest()
    base=tmp_path/'base';base.mkdir();(base/'objects').mkdir()
    original='Simplify $(x^2-1)/(x-1)$.\nAnswer: x+1\n'
    source=digest(original.encode());(base/'objects'/(source+'.md')).write_text(original)
    row={'id':'algebra-1','library':'math-competition','kind':'question','prompt':'Simplify $(x^2-1)/(x-1)$.','answer':'x+1','issues':[], 'metadata':{'closed_arithmetic_check':{'status':'held'}},'source_sha256':source,'start':0,'end':len(original),'raw_sha256':source,'state':'needs_curriculum_review','approval':'unreviewed'}
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
    assert saved['metadata']['closed_algebra_check']['nonzero_conditions']
    assert saved['metadata']['closed_algebra_check']['checker_dependencies']['numeric_parser_sha256']
    with pytest.raises(ValueError,match='already exists'):build(folder,tmp_path/'repeated')
    with sqlite3.connect(base/'catalog.sqlite3') as db:db.execute("update records set state='changed'")
    with pytest.raises(ValueError,match='Base changed'):build(base,tmp_path/'tampered')
