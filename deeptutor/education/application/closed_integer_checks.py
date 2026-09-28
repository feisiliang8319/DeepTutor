"""Bounded exact checks of explicitly requested integer operations in stock.

Only full-prompt grammars are supported. No language-model answer guessing,
source execution, floating point, inferred constraints or publication approval.
"""
import math
import re
from .closed_math_checks import Unsupported,evaluate


def numeric(text):
    text=text.strip().rstrip('.?').strip()
    if text.startswith('$$') and text.endswith('$$'):text=text[2:-2]
    elif text.startswith('$') and text.endswith('$'):text=text[1:-1]
    elif text.startswith(r'\[') and text.endswith(r'\]'):text=text[2:-2]
    text=text.strip().rstrip('.?').strip().replace('{,}',',')
    text=re.sub(r'\\[,!]','',text)
    if re.fullmatch(r'[+-]?\d{1,3}(?:,\d{3})+',text):text=text.replace(',','')
    value=evaluate(text)
    if value.denominator!=1:raise Unsupported('integer_operand_required')
    return value.numerator


def operands(text):
    saved=[]
    def protect(match):saved.append(match[0]);return '@'+str(len(saved)-1)+'@'
    masked=re.sub(r'\$[^$]+\$',protect,text)
    parts=re.split(r',\s+|\s+and\s+',masked)
    parts=[re.sub(r'^and\s+','',part.strip()) for part in parts]
    if not 2<=len(parts)<=20:raise Unsupported('explicit_integer_list_required')
    result=[]
    for part in parts:
        for i,original in enumerate(saved):part=part.replace('@'+str(i)+'@',original)
        value=numeric(part)
        if value<=0:raise Unsupported('positive_integer_operands_required')
        result.append(value)
    return result


def factor(n):
    if not 1<=n<=10**10:raise Unsupported('factorization_domain_or_size_limit')
    result={};d=2
    while d*d<=n:
        while n%d==0:result[d]=result.get(d,0)+1;n//=d
        d=3 if d==2 else d+2
    if n>1:result[n]=result.get(n,0)+1
    return result


def operation(prompt):
    prefix=r'(?:Find|Compute|Give|What is) the '
    suffix=r'[.?]?'
    match=re.fullmatch(prefix+r'(greatest common divisor|greatest common factor|least common multiple) of (?:the numbers )?(.+?)'+suffix,prompt,re.I|re.S)
    if match:
        name,raw=match.groups();values=operands(raw)
        answer=math.lcm(*values) if name.lower()=='least common multiple' else math.gcd(*values)
        return answer,{'operation':name.lower(),'operands':[str(v) for v in values]}
    match=re.fullmatch(r'(?:How many (?:distinct,? )?positive (?:integer )?(?:factors|divisors) does (?:the number )?(.+?) have\?|(?:Find the number of|What is the number of) (?:distinct )?positive (?:integer )?(?:factors|divisors) of (.+?)[.?]?)',prompt,re.I|re.S)
    if match:
        n=numeric(next(x for x in match.groups() if x is not None));factors=factor(n)
        return math.prod(e+1 for e in factors.values()),{'operation':'positive_divisor_count','integer':str(n),'prime_exponents':factors}
    match=re.fullmatch(prefix+r'(sum|product) of (?:all (?:of )?)?the positive (?:integer )?(?:factors|divisors) of (.+?)'+suffix,prompt,re.I|re.S)
    if match:
        name,raw=match.groups();n=numeric(raw);factors=factor(n)
        if name.lower()=='sum':value=math.prod((p**(e+1)-1)//(p-1) for p,e in factors.items())
        else:
            count=math.prod(e+1 for e in factors.values())
            if count*n.bit_length()>20000:raise Unsupported('divisor_product_size_limit')
            value=n**(count//2)*(math.isqrt(n) if count%2 else 1)
        return value,{'operation':'positive_divisor_'+name.lower(),'integer':str(n),'prime_exponents':factors}
    match=re.fullmatch(prefix+r'(largest|greatest|smallest|least) prime factor of (.+?)'+suffix,prompt,re.I|re.S)
    if match:
        name,raw=match.groups();n=numeric(raw);factors=factor(n)
        if not factors:raise Unsupported('no_prime_factor')
        value=max(factors) if name.lower() in ('largest','greatest') else min(factors)
        return value,{'operation':name.lower()+'_prime_factor','integer':str(n),'prime_exponents':factors}
    match=re.fullmatch(prefix+r'sum of the (?:distinct|different) prime factors of (.+?)'+suffix,prompt,re.I|re.S)
    if match:
        n=numeric(match[1]);factors=factor(n)
        return sum(factors),{'operation':'distinct_prime_factor_sum','integer':str(n),'prime_exponents':factors}
    match=re.fullmatch(r'(?:Find|Determine|What is) the remainder when (?:the product )?(.+?)\s*is divided by (.+?)[.?]?',prompt,re.I|re.S)
    if match:
        raw,divisor=match.groups();n=numeric(raw);d=numeric(divisor)
        if n<0 or d<=0:raise Unsupported('nonnegative_dividend_positive_divisor_required')
        return n%d,{'operation':'integer_remainder','dividend':str(n),'divisor':str(d)}
    return None


def check(row):
    if any(x in row['issues'] for x in ('missing_figure','unrendered_diagram')):return None
    try:
        result=operation(row['prompt'].strip())
        if result is None:return None
        value,evidence=result;answer=numeric(row['answer'])
        return {**evidence,'computed':str(value),'source_answer_value':str(answer),'status':'match' if value==answer else 'mismatch','method':'bounded exact integer arithmetic and trial-division factorization','scope':'Explicit integer operation and answer only; explanation, source rights, diagrams and curriculum approval unchanged.'}
    except (Unsupported,ValueError,ZeroDivisionError,RecursionError) as exc:
        return {'status':'held','reason':str(exc),'scope':'Unsupported operation or answer; no approval.'}

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
        if 'closed_integer_check' in row['metadata']:raise ValueError('Review already exists')
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
        review={**result,'record_id':row['id'],'source_sha256':source,'source_raw_sha256':row['raw_sha256'],'prompt_sha256':sha(row['prompt']),'answer_sha256':sha(row['answer']),'checker_sha256':sha(Path(__file__).read_bytes()),'numeric_parser_sha256':sha(Path(__file__).with_name('closed_math_checks.py').read_bytes()),'approval':'unchanged'}
        results.append(review)
        row['metadata']={**row['metadata'],'closed_integer_check':review}
        if result['status']=='mismatch' and row['state']!='duplicate':row['state']='needs_fact_check'
        updates[row['id']]=row
    if not results:raise ValueError('No supported question forms')
    identity=sha(json.dumps({'base':base.name,'checker':sha(Path(__file__).read_bytes()),'numeric_parser':sha(Path(__file__).with_name('closed_math_checks.py').read_bytes())},sort_keys=True));target=Path(output)/identity;shutil.copytree(base,target)
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
                if a['id'] not in updates or not {k for k in a.keys()|b.keys() if a.get(k)!=b.get(k)}<={'metadata','state'} or {k:v for k,v in b['metadata'].items() if k!='closed_integer_check'}!=a['metadata']:raise ValueError('Unrelated data changed')
        if changed!=len(updates):raise ValueError('Changed population mismatch')
        for lib in summary['libraries']:
            if lib['library'] in ('harp-competition','math-competition'):lib['states']=dict(db.execute('select state,count(*) from records where library=? group by state',(lib['library'],)))
    counts=dict(Counter(x['status'] for x in results));reasons=dict(Counter(x['reason'] for x in results if x['status']=='held'))
    report={**summary,'snapshot_id':identity,'base_snapshot_id':base.name,'created_at':datetime.now(timezone.utc).isoformat(),'catalog_sha256':sha((target/'catalog.sqlite3').read_bytes()),'committed_batches':summary['committed_batches']+1,'closed_integer_checks':{'total':len(results),'counts':counts,'held_reasons':reasons,'scope':'Explicit integer operations only; all original answers, explanations, asset/rights and curriculum approval gates retained.'}}
    (target/'summary.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n');(target/'closed-integer-review-queue.json').write_text(json.dumps(results,ensure_ascii=False,indent=2)+'\n')
    return {k:report[k] for k in ('snapshot_id','base_snapshot_id','catalog_sha256','committed_batches','closed_integer_checks')}
