"""Exact checks of explicitly stated numeric binomial expressions in existing stock."""
from fractions import Fraction
from math import comb
import re
from .closed_math_checks import Parser,Unsupported,bounded


class BinomialParser(Parser):
    def atom(self):
        self.skip()
        if any(self.take(command) for command in (r'\dbinom',r'\tbinom',r'\binom')):
            self.enter()
            n,k=self.argument(),self.argument()
            if n.denominator!=1 or k.denominator!=1 or not 0<=k<=n<=10000:
                raise Unsupported('binomial_nonnegative_integer_domain_or_size')
            value=bounded(Fraction(comb(n.numerator,k.numerator)))
            self.depth-=1
            return value
        return super().atom()


def evaluate_binomial(text):
    return BinomialParser(text).parse()


def check(row):
    if any(x in row['issues'] for x in ('missing_figure','unrendered_diagram')):return None
    match=re.fullmatch(r'(?:Evaluate|Simplify|Compute|What is(?: the value of)?)\s+\$([^$]+)\$[.!?]?',row['prompt'].strip(),re.I|re.S)
    if not match or not re.search(r'\\(?:d|t)?binom(?![A-Za-z])',match[1]):return None
    expression=match[1].strip();answer=row['answer'].strip()
    if answer.startswith('$') and answer.endswith('$'):answer=answer[1:-1].strip()
    grouped=re.sub(r'\\[,!]','',answer).replace('{,}',',')
    if re.fullmatch(r'[+-]?\d{1,3}(?:,\d{3})+',grouped):answer=grouped.replace(',','')
    try:
        value=evaluate_binomial(expression);expected=evaluate_binomial(answer)
        return {'status':'match' if value==expected else 'mismatch','expression':expression,'computed':str(value),'source_answer_value':str(expected),'method':'bounded numeric LaTeX parser and exact integer binomial coefficients','scope':'Stated expression and answer only; no interpretation of word problems, reasoning or curriculum approval.'}
    except (Unsupported,ValueError,ZeroDivisionError,RecursionError) as exc:
        return {'status':'held','reason':str(exc),'scope':'Unsupported expression or answer; no approval.'}


def build(base,output):
    from collections import Counter
    from datetime import datetime,timezone
    import hashlib,inspect,json,shutil,sqlite3
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
        if 'closed_binomial_check' in row['metadata']:raise ValueError('Review already exists')
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
        review={**result,'record_id':row['id'],'source_sha256':source,'source_raw_sha256':row['raw_sha256'],'prompt_sha256':sha(row['prompt']),'answer_sha256':sha(row['answer']),'checker_sha256':sha(Path(__file__).read_bytes()),'numeric_parser_sha256':sha(Path(inspect.getfile(Parser)).read_bytes()),'approval':'unchanged'}
        results.append(review)
        row['metadata']={**row['metadata'],'closed_binomial_check':review}
        if result['status']=='mismatch' and row['state']!='duplicate':row['state']='needs_fact_check'
        updates[row['id']]=row
    if not results:raise ValueError('No supported question forms')
    identity=sha(json.dumps({'base':base.name,'checker':sha(Path(__file__).read_bytes()),'numeric_parser':sha(Path(inspect.getfile(Parser)).read_bytes())},sort_keys=True));target=Path(output)/identity;shutil.copytree(base,target)
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
                if a['id'] not in updates or not {k for k in a.keys()|b.keys() if a.get(k)!=b.get(k)}<={'metadata','state'} or {k:v for k,v in b['metadata'].items() if k!='closed_binomial_check'}!=a['metadata']:raise ValueError('Unrelated data changed')
        if changed!=len(updates):raise ValueError('Changed population mismatch')
        for lib in summary['libraries']:
            if lib['library'] in ('harp-competition','math-competition'):lib['states']=dict(db.execute('select state,count(*) from records where library=? group by state',(lib['library'],)))
    counts=dict(Counter(x['status'] for x in results));reasons=dict(Counter(x['reason'] for x in results if x['status']=='held'))
    report={**summary,'snapshot_id':identity,'base_snapshot_id':base.name,'created_at':datetime.now(timezone.utc).isoformat(),'catalog_sha256':sha((target/'catalog.sqlite3').read_bytes()),'committed_batches':summary['committed_batches']+1,'closed_binomial_checks':{'total':len(results),'counts':counts,'held_reasons':reasons,'scope':'Explicit numeric binomial expressions only; all original answers, explanations, asset/rights and curriculum approval gates retained.'}}
    (target/'summary.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n');(target/'closed-binomial-review-queue.json').write_text(json.dumps(results,ensure_ascii=False,indent=2)+'\n')
    return {k:report[k] for k in ('snapshot_id','base_snapshot_id','catalog_sha256','committed_batches','closed_binomial_checks')}
