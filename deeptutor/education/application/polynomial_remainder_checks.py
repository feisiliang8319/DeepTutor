"""Exact long division for complete, bounded, one-variable polynomial prompts."""
from fractions import Fraction
import re
from .closed_algebra_checks import Budget,Parser
from .closed_math_checks import Unsupported


def unwrap(text):
    text=text.strip().rstrip('.?').strip()
    if text.startswith('$$') and text.endswith('$$'):text=text[2:-2]
    elif text.startswith('$') and text.endswith('$'):text=text[1:-1]
    elif text.startswith(r'\[') and text.endswith(r'\]'):text=text[2:-2]
    return text.strip().rstrip('.?').strip()


def polynomial(text,budget):
    parser=Parser(unwrap(text),budget);value=parser.parse()
    if set(value.d)!={()} or budget.conditions:raise Unsupported('polynomial_without_variable_denominators_required')
    if len(parser.variables)>1:raise Unsupported('one_variable_required')
    denominator=value.d[()]
    return {sum(e for _,e in m):c/denominator for m,c in value.n.items()},parser.variables


def divide(a,b):
    if not b:raise Unsupported('zero_polynomial_divisor')
    degree=max(b)
    if degree==0:raise Unsupported('nonconstant_polynomial_divisor_required')
    quotient={};remainder=dict(a);steps=0
    while remainder and max(remainder)>=degree:
        steps+=1
        if steps>65:raise Unsupported('polynomial_division_step_limit')
        old_degree=max(remainder);power=old_degree-degree;coefficient=remainder[old_degree]/b[degree]
        quotient[power]=quotient.get(power,Fraction(0))+coefficient
        for exponent,value in b.items():
            key=exponent+power;remainder[key]=remainder.get(key,Fraction(0))-coefficient*value
            if not remainder[key]:del remainder[key]
        if remainder and max(remainder)>=old_degree:raise ArithmeticError('Polynomial degree did not decrease')
    # Independent identity reconstruction guards the long-division result.
    reconstructed=dict(remainder)
    for i,q in quotient.items():
        for j,v in b.items():reconstructed[i+j]=reconstructed.get(i+j,Fraction(0))+q*v
    if {e:c for e,c in reconstructed.items() if c}!=a:raise ArithmeticError('Polynomial identity mismatch')
    return quotient,remainder


def check(row):
    if any(x in row['issues'] for x in ('missing_figure','unrendered_diagram')):return None
    wrapped=r'(\$\$.*?\$\$|\$[^$]+\$|\\\[.*?\\\])'
    prefix=r'(?:Find|Determine|What is) the remainder when '
    m=re.fullmatch(prefix+r'(?:the polynomial )?'+wrapped+r'\s*is divided by (?:the polynomial )?'+wrapped+r'[.?]?',row['prompt'].strip(),re.S|re.I)
    if m:left,right=m.groups()
    else:
        m=re.fullmatch(prefix+wrapped+r'\s*divides '+wrapped+r'[.?]?',row['prompt'].strip(),re.S|re.I)
        if not m:return None
        right,left=m.groups()
    combined=left+' '+right
    if any(token in combined for token in (r'\text',r'\underbrace',r'\dots',r'\ldots',r'\cdots')):return None
    if not re.search(r'(?<![A-Za-z\\])[a-zA-Z](?![A-Za-z])',combined):return None
    try:
        budget=Budget();a,av=polynomial(left,budget);b,bv=polynomial(right,budget)
        variables=av|bv
        if not variables:return None
        if len(variables)!=1:raise Unsupported('one_variable_required')
        quotient,remainder=divide(a,b)
        answer,answer_vars=polynomial(row['answer'],budget)
        if not answer_vars<=variables:raise Unsupported('answer_variable_mismatch')
        matched=answer==remainder
        pack=lambda p:{str(e):str(c) for e,c in sorted(p.items())}
        return {'status':'match' if matched else 'mismatch','variable':next(iter(variables)),'dividend':pack(a),'divisor':pack(b),'quotient':pack(quotient),'computed_remainder':pack(remainder),'source_answer_polynomial':pack(answer),'method':'exact rational-coefficient long division, decreasing degree and independent q*d+r reconstruction','scope':'Complete remainder polynomial only; full source explanation, rights, grade and formal approval unchanged.'}
    except (Unsupported,ValueError,ZeroDivisionError,RecursionError) as exc:
        return {'status':'held','reason':str(exc),'scope':'Unsupported polynomial, domain or answer form; no approval.'}

def build(base,output):
    from collections import Counter
    from datetime import datetime,timezone
    import hashlib,json,shutil,sqlite3
    from pathlib import Path
    from .content_stock import parse_file
    sha=lambda v:hashlib.sha256(v.encode() if isinstance(v,str) else v).hexdigest()
    base=Path(base).resolve();summary=json.loads((base/'summary.json').read_text())
    if base.name!=summary['snapshot_id'] or sha((base/'catalog.sqlite3').read_bytes())!=summary['catalog_sha256']:raise ValueError('Base changed')
    with sqlite3.connect((base/'catalog.sqlite3').as_uri()+'?mode=ro',uri=True) as db:
        rows=[json.loads(x[0]) for x in db.execute("select data_json from records where library in ('harp-competition','math-competition') and kind='question'")]
    objects={};parsed={};updates={};results=[]
    for row in rows:
        result=check(row)
        if result is None:continue
        if 'polynomial_remainder_check' in row['metadata']:raise ValueError('Review already exists')
        source=row['source_sha256']
        if source not in objects:
            blob=(base/'objects'/(source+'.md')).read_bytes()
            if sha(blob)!=source:raise ValueError('Source object changed')
            objects[source]=blob.decode()
            parsed[source]={entry['start']:entry for entry in parse_file(row['library'],Path(row['source_path']).name,objects[source])}
        original=objects[source][row['start']:row['end']]
        if sha(original)!=row['raw_sha256'] or row['prompt'] not in original:raise ValueError('Source span changed')
        source_record=parsed[source].get(row['start'])
        if source_record is None or any(row[k]!=source_record[k] for k in ('prompt','answer','title','options')):raise ValueError('Source parsed question or answer changed')
        review={**result,'record_id':row['id'],'source_sha256':source,'source_raw_sha256':row['raw_sha256'],'prompt_sha256':sha(row['prompt']),'answer_sha256':sha(row['answer']),'checker_sha256':sha(Path(__file__).read_bytes()),'numeric_parser_sha256':sha(Path(__file__).with_name('closed_math_checks.py').read_bytes()),'algebra_parser_sha256':sha(Path(__file__).with_name('closed_algebra_checks.py').read_bytes()),'approval':'unchanged'}
        results.append(review)
        row['metadata']={**row['metadata'],'polynomial_remainder_check':review}
        if result['status']=='mismatch' and row['state']!='duplicate':row['state']='needs_fact_check'
        updates[row['id']]=row
    if not results:raise ValueError('No supported question forms')
    identity=sha(json.dumps({'base':base.name,'checker':sha(Path(__file__).read_bytes()),'numeric_parser':sha(Path(__file__).with_name('closed_math_checks.py').read_bytes()),'algebra_parser':sha(Path(__file__).with_name('closed_algebra_checks.py').read_bytes())},sort_keys=True));target=Path(output)/identity;shutil.copytree(base,target)
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
                if a['id'] not in updates or not {k for k in a.keys()|b.keys() if a.get(k)!=b.get(k)}<={'metadata','state'} or {k:v for k,v in b['metadata'].items() if k!='polynomial_remainder_check'}!=a['metadata']:raise ValueError('Unrelated data changed')
        if changed!=len(updates):raise ValueError('Changed population mismatch')
        for lib in summary['libraries']:
            if lib['library'] in ('harp-competition','math-competition'):lib['states']=dict(db.execute('select state,count(*) from records where library=? group by state',(lib['library'],)))
    counts=dict(Counter(x['status'] for x in results));reasons=dict(Counter(x['reason'] for x in results if x['status']=='held'))
    report={**summary,'snapshot_id':identity,'base_snapshot_id':base.name,'created_at':datetime.now(timezone.utc).isoformat(),'catalog_sha256':sha((target/'catalog.sqlite3').read_bytes()),'committed_batches':summary['committed_batches']+1,'polynomial_remainder_checks':{'total':len(results),'counts':counts,'held_reasons':reasons,'scope':'Bounded exact polynomial remainder only; all original answers, explanations, asset/rights and curriculum approval gates retained.'}}
    (target/'summary.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n');(target/'polynomial-remainder-review-queue.json').write_text(json.dumps(results,ensure_ascii=False,indent=2)+'\n')
    return {k:report[k] for k in ('snapshot_id','base_snapshot_id','catalog_sha256','committed_batches','polynomial_remainder_checks')}
