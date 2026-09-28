"""Exact complete solution sets for bounded one-variable rational equations.

Only linear/quadratic cross-products with rational real roots. Original divisor
conditions are checked so cross multiplication cannot certify extraneous roots.
No inferred inequalities, word-problem interpretation, or curriculum approval.
"""
from fractions import Fraction
import re
from .closed_algebra_checks import Budget,Parser
from .closed_math_checks import Unsupported,evaluate,exact_root


def coefficients(poly,variable):
    result={}
    for monomial,value in poly.items():
        if any(v!=variable for v,e in monomial):raise Unsupported('more_than_one_variable')
        degree=sum(e for v,e in monomial)
        result[degree]=result.get(degree,Fraction(0))+value
    return {e:c for e,c in result.items() if c}


def at(poly,variable,value):
    return sum(c*value**e for e,c in coefficients(poly,variable).items())


def solve(equation,variable):
    if equation.count('=')!=1:raise Unsupported('one_equality_required')
    left,right=equation.split('=');budget=Budget()
    a=Parser(left,budget);av=a.parse();b=Parser(right,budget);bv=b.parse()
    if (a.variables|b.variables)!={variable}:raise Unsupported('one_named_variable_required')
    value=av-bv;terms=coefficients(value.n,variable)
    if not terms:raise Unsupported('identity_has_nonfinite_solution_set')
    degree=max(terms)
    if degree>2:raise Unsupported('equation_degree_limit')
    if degree==0:roots=set()
    elif degree==1:roots={-terms.get(0,Fraction(0))/terms[1]}
    else:
        aa=terms[2];bb=terms.get(1,Fraction(0));cc=terms.get(0,Fraction(0))
        discriminant=bb*bb-4*aa*cc
        if discriminant<0:raise Unsupported('nonreal_roots_require_explicit_domain')
        radical=exact_root(discriminant,2)
        roots={(-bb-radical)/(2*aa),(-bb+radical)/(2*aa)}
    exclusions=[];allowed=set()
    conditions=[{tuple((v,e) for v,e in m):Fraction(c) for c,m in cond['nonzero_polynomial']} for cond in budget.conditions]
    for root in roots:
        if all(at(p,variable,root)!=0 for p in conditions):allowed.add(root)
        else:exclusions.append(str(root))
    return {'solutions':sorted(allowed),'excluded_poles':sorted(exclusions),'nonzero_conditions':budget.conditions,'degree':degree}


def numeric_answers(answer,variable):
    answer=answer.strip()
    if answer.startswith('$') and answer.endswith('$'):answer=answer[1:-1].strip()
    answer=re.sub(r'^'+re.escape(variable)+r'\s*=\s*','',answer)
    if not answer or len(answer)>4096:raise Unsupported('unsupported_answer_set')
    pieces=answer.split(',')
    if len(pieces)>2 or any(not p.strip() for p in pieces):raise Unsupported('unsupported_answer_set')
    return {evaluate(p.strip()) for p in pieces}


def check(row):
    if any(x in row['issues'] for x in ('missing_figure','unrendered_diagram')):return None
    prompt=row['prompt'].strip()
    suffix=r'(?:\s*Express your answer as a (?:simplified )?(?:common )?fraction\.)?'
    patterns=[
        r'Solve for \$([a-zA-Z])\$:\s*(\$\$.*?\$\$|\$[^$]+\$|\\\[.*?\\\])[.!]?'+suffix,
        r'Solve(?: the equation)?\s*(\$\$.*?\$\$|\$[^$]+\$|\\\[.*?\\\])\s*for \$([a-zA-Z])\$[.!]?'+suffix,
    ]
    match=re.fullmatch(patterns[0],prompt,re.S)
    if match:variable,wrapped=match.groups()
    else:
        match=re.fullmatch(patterns[1],prompt,re.S)
        if not match:return None
        wrapped,variable=match.groups()
    equation=wrapped[2:-2] if wrapped.startswith(('$$',r'\[')) else wrapped[1:-1]
    equation=equation.strip()
    if equation.endswith('.'):equation=equation[:-1]
    try:
        result=solve(equation,variable);answers=numeric_answers(row['answer'],variable)
        return {**result,'solutions':[str(x) for x in result['solutions']],'source_answer_values':[str(x) for x in sorted(answers)],'status':'match' if set(result['solutions'])==answers else 'mismatch','equation':equation,'variable':variable,'method':'exact complete rational roots of degree <= 2, with original denominator exclusions','scope':'Complete solution set for this bounded rational equation only; original explanations, rights, assets and curriculum approval unchanged.'}
    except (Unsupported,ValueError,ZeroDivisionError,RecursionError) as exc:
        return {'status':'held','reason':str(exc),'scope':'Unsupported equation or answer form; no answer approval.'}

def build(base,output):
    from collections import Counter
    from datetime import datetime,timezone
    import hashlib,json,shutil,sqlite3
    from pathlib import Path
    sha=lambda v:hashlib.sha256(v.encode() if isinstance(v,str) else v).hexdigest()
    base=Path(base).resolve();summary=json.loads((base/'summary.json').read_text())
    if base.name!=summary['snapshot_id'] or sha((base/'catalog.sqlite3').read_bytes())!=summary['catalog_sha256']:raise ValueError('Base changed')
    with sqlite3.connect((base/'catalog.sqlite3').as_uri()+'?mode=ro',uri=True) as db:
        rows=[json.loads(x[0]) for x in db.execute("select data_json from records where library in ('harp-competition','math-competition') and kind='question'")]
    objects={};updates={};results=[]
    for row in rows:
        result=check(row)
        if result is None:continue
        if 'closed_equation_check' in row['metadata']:raise ValueError('Review already exists')
        source=row['source_sha256']
        if source not in objects:
            blob=(base/'objects'/(source+'.md')).read_bytes()
            if sha(blob)!=source:raise ValueError('Source object changed')
            objects[source]=blob.decode()
        original=objects[source][row['start']:row['end']]
        if sha(original)!=row['raw_sha256'] or row['prompt'] not in original:raise ValueError('Source span changed')
        review={**result,'record_id':row['id'],'source_sha256':source,'source_raw_sha256':row['raw_sha256'],'prompt_sha256':sha(row['prompt']),'answer_sha256':sha(row['answer']),'checker_sha256':sha(Path(__file__).read_bytes()),'checker_dependencies':{'algebra_parser_sha256':sha(Path(__file__).with_name('closed_algebra_checks.py').read_bytes()),'numeric_parser_sha256':sha(Path(__file__).with_name('closed_math_checks.py').read_bytes())},'approval':'unchanged'}
        results.append(review)
        row['metadata']={**row['metadata'],'closed_equation_check':review}
        if result['status']=='mismatch' and row['state']!='duplicate':row['state']='needs_fact_check'
        updates[row['id']]=row
    if not results:raise ValueError('No supported question forms')
    identity=sha(json.dumps({'base':base.name,'checker':sha(Path(__file__).read_bytes()),'algebra_parser':sha(Path(__file__).with_name('closed_algebra_checks.py').read_bytes()),'numeric_parser':sha(Path(__file__).with_name('closed_math_checks.py').read_bytes())},sort_keys=True));target=Path(output)/identity;shutil.copytree(base,target)
    with sqlite3.connect(target/'catalog.sqlite3') as db:
        for row in updates.values():db.execute('update records set state=?,data_json=? where id=?',(row['state'],json.dumps(row,ensure_ascii=False),row['id']))
        db.commit()
        if db.execute('pragma integrity_check').fetchone()[0]!='ok':raise ValueError('Catalog integrity failure')
        changed=0
        with sqlite3.connect((base/'catalog.sqlite3').as_uri()+'?mode=ro',uri=True) as old:
            for a,b in zip(old.execute('select data_json from records order by id'),db.execute('select data_json from records order by id'),strict=True):
                a,b=json.loads(a[0]),json.loads(b[0])
                if a==b:continue
                changed+=1
                if a['id'] not in updates or not {k for k in a.keys()|b.keys() if a.get(k)!=b.get(k)}<={'metadata','state'} or {k:v for k,v in b['metadata'].items() if k!='closed_equation_check'}!=a['metadata']:raise ValueError('Unrelated data changed')
        if changed!=len(updates):raise ValueError('Changed population mismatch')
        for lib in summary['libraries']:
            if lib['library'] in ('harp-competition','math-competition'):lib['states']=dict(db.execute('select state,count(*) from records where library=? group by state',(lib['library'],)))
    counts=dict(Counter(x['status'] for x in results));reasons=dict(Counter(x['reason'] for x in results if x['status']=='held'))
    report={**summary,'snapshot_id':identity,'base_snapshot_id':base.name,'created_at':datetime.now(timezone.utc).isoformat(),'catalog_sha256':sha((target/'catalog.sqlite3').read_bytes()),'committed_batches':summary['committed_batches']+1,'closed_equation_checks':{'total':len(results),'counts':counts,'held_reasons':reasons,'scope':'Complete bounded rational equation solutions only; original answers, explanations, rights, assets and curriculum approval unchanged.'}}
    (target/'summary.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n');(target/'closed-equation-review-queue.json').write_text(json.dumps(results,ensure_ascii=False,indent=2)+'\n')
    return {k:report[k] for k in ('snapshot_id','base_snapshot_id','catalog_sha256','committed_batches','closed_equation_checks')}
