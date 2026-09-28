"""Restricted exact arithmetic checker for self-contained stock questions.

Parses a small numeric LaTeX grammar directly. No eval, exec, sympify, external
programs, floating approximation, variable substitution, or LLM judgement.
Unsupported notation is held, never silently interpreted or approved.
"""
from fractions import Fraction
from math import factorial, isqrt
import re

class Unsupported(ValueError):
    pass


def bounded(value):
    if max(abs(value.numerator).bit_length(),value.denominator.bit_length())>20000:
        raise Unsupported('arithmetic_size_limit')
    return value


def exact_root(value,degree):
    if degree<1 or degree>20 or value<0:raise Unsupported('root_domain_or_degree')
    def root(n):
        if degree==2:r=isqrt(n)
        else:
            low,high=0,1<<((n.bit_length()+degree-1)//degree)
            while low<high:
                middle=(low+high+1)//2
                if middle**degree<=n:low=middle
                else:high=middle-1
            r=low
        if r**degree!=n:raise Unsupported('irrational_intermediate')
        return r
    return Fraction(root(value.numerator),root(value.denominator))


class Parser:
    def __init__(self,text):
        if len(text)>4096:raise Unsupported('expression_length')
        self.text=re.sub(r'\\(?:left|right|displaystyle)(?![a-zA-Z])','',text)
        self.text=re.sub(r'\\[,!;:]','',self.text).strip()
        if re.search(r'\d\s*\\(?:dfrac|tfrac|frac)',self.text):raise Unsupported('mixed_number_or_implicit_product')
        self.i=0;self.depth=0;self.steps=0

    def skip(self):
        while self.i<len(self.text) and self.text[self.i].isspace():self.i+=1

    def take(self,value):
        self.skip()
        if self.text.startswith(value,self.i):self.i+=len(value);return True
        return False

    def require(self,value):
        if not self.take(value):raise Unsupported('missing_delimiter')

    def enter(self):
        self.depth+=1;self.steps+=1
        if self.depth>64 or self.steps>2048:raise Unsupported('expression_complexity')

    def expression(self):
        self.enter();value=self.term()
        while True:
            if self.take('+'):value=bounded(value+self.term())
            elif self.take('-'):value=bounded(value-self.term())
            else:break
        self.depth-=1;return value

    def term(self):
        value=self.unary();unbracketed_division=False
        while True:
            if self.take('*') or self.take(r'\cdot') or self.take(r'\times'):
                value=bounded(value*self.unary())
            elif self.take('/') or self.take(r'\div'):
                unbracketed_division=True
                denominator=self.unary()
                if denominator==0:raise Unsupported('division_by_zero')
                value=bounded(value/denominator)
            else:
                self.skip()
                # Parenthesized/fraction/root juxtaposition only; digit adjacency
                # and mixed numbers are deliberately not guessed.
                starts=('(', '{', r'\sqrt', r'\frac', r'\dfrac', r'\tfrac',r'\cfrac',r'\lfloor',r'\lceil')
                if any(self.text.startswith(s,self.i) for s in starts):
                    if unbracketed_division:raise Unsupported('ambiguous_juxtaposed_division')
                    value=bounded(value*self.unary())
                else:break
        return value

    def unary(self):
        self.enter()
        if self.take('+'):value=self.unary()
        elif self.take('-'):value=-self.unary()
        else:value=self.power()
        self.depth-=1;return value

    def power(self):
        value=self.atom()
        if self.take('!'):
            if value.denominator!=1 or not 0<=value<=200:raise Unsupported('factorial_domain_or_limit')
            value=Fraction(factorial(value.numerator))
            if self.take('!'):raise Unsupported('double_factorial')
        if self.take('^'):
            exponent=self.argument()
            if abs(exponent.numerator)>200 or exponent.denominator>20:raise Unsupported('exponent_limit')
            if value==0 and exponent<=0:raise Unsupported('undefined_zero_power')
            if exponent.denominator!=1:value=exact_root(value,exponent.denominator)
            value=bounded(value**exponent.numerator)
        return value

    def argument(self):
        self.skip()
        if self.take('{'):
            value=self.expression();self.require('}');return value
        if self.i<len(self.text) and self.text[self.i].isdigit():
            value=Fraction(int(self.text[self.i]));self.i+=1;return value
        if self.i<len(self.text) and self.text[self.i]=='\\':return self.atom()
        raise Unsupported('unbraced_argument')

    def atom(self):
        self.enter();self.skip()
        if self.take('('):value=self.expression();self.require(')')
        elif self.take('{'):value=self.expression();self.require('}')
        elif self.take('|'):value=abs(self.expression());self.require('|')
        elif self.take(r'\lfloor'):
            value=self.expression();self.require(r'\rfloor');value=Fraction(value.numerator//value.denominator)
        elif self.take(r'\lceil'):
            value=self.expression();self.require(r'\rceil');value=Fraction(-(-value.numerator//value.denominator))
        elif self.take(r'\dfrac') or self.take(r'\tfrac') or self.take(r'\cfrac') or self.take(r'\frac'):
            numerator=self.argument();denominator=self.argument()
            if not denominator:raise Unsupported('division_by_zero')
            value=bounded(numerator/denominator)
        elif self.take(r'\sqrt'):
            degree=Fraction(2)
            if self.take('['):degree=self.expression();self.require(']')
            if degree.denominator!=1:raise Unsupported('noninteger_root_degree')
            value=exact_root(self.argument(),degree.numerator)
        else:
            number=re.match(r'(?:\d+(?:\.\d*)?|\.\d+)',self.text[self.i:])
            if not number or len(number[0])>200:raise Unsupported('unsupported_atom')
            self.i+=len(number[0]);value=Fraction(number[0])
        self.depth-=1;return bounded(value)

    def parse(self):
        value=self.expression();self.skip()
        if self.i!=len(self.text):raise Unsupported('trailing_or_unsupported_notation')
        return value


def evaluate(text):
    return Parser(text).parse()


def check(row):
    pattern=r'(?:Evaluate|Simplify|Compute|What is(?: the value of)?)\s+\$([^$]+)\$[.!?]?'
    match=re.fullmatch(pattern,row['prompt'].strip(),re.I|re.S)
    if not match:return None
    if any(x in row['issues'] for x in ('missing_figure','unrendered_diagram')):return None
    expression=match[1].strip()
    # Some source prose places the final sentence period inside math delimiters.
    if expression.endswith('.') and not re.search(r'\d\.$',expression):expression=expression[:-1]
    answer=row['answer'].strip()
    if answer.startswith('$') and answer.endswith('$'):answer=answer[1:-1].strip()
    try:
        value=evaluate(expression);expected=evaluate(answer)
    except (Unsupported,ValueError,ZeroDivisionError,RecursionError) as exc:
        return {'status':'held','reason':str(exc),'scope':'exact_arithmetic_only'}
    return {'status':'match' if value==expected else 'mismatch','computed':str(value),'source_answer_value':str(expected),'expression':expression,'scope':'exact arithmetic equality only; source rights, explanation and curriculum approval unchanged'}


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
        if 'closed_arithmetic_check' in row['metadata']:raise ValueError('Review already exists')
        source=row['source_sha256']
        if source not in objects:
            blob=(base/'objects'/(source+'.md')).read_bytes()
            if sha(blob)!=source:raise ValueError('Source object changed')
            objects[source]=blob.decode()
        original=objects[source][row['start']:row['end']]
        if sha(original)!=row['raw_sha256'] or row['prompt'] not in original:raise ValueError('Source span changed')
        review={**result,'record_id':row['id'],'source_sha256':source,'source_raw_sha256':row['raw_sha256'],'prompt_sha256':sha(row['prompt']),'answer_sha256':sha(row['answer']),'checker_sha256':sha(Path(__file__).read_bytes()),'approval':'unchanged'}
        results.append(review)
        row['metadata']={**row['metadata'],'closed_arithmetic_check':review}
        if result['status']=='mismatch' and row['state']!='duplicate':row['state']='needs_fact_check'
        updates[row['id']]=row
    if not results:raise ValueError('No supported question forms')
    identity=sha(json.dumps({'base':base.name,'checker':sha(Path(__file__).read_bytes())},sort_keys=True));target=Path(output)/identity;shutil.copytree(base,target)
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
                if a['id'] not in updates or not {k for k in a.keys()|b.keys() if a.get(k)!=b.get(k)}<={'metadata','state'} or {k:v for k,v in b['metadata'].items() if k!='closed_arithmetic_check'}!=a['metadata']:raise ValueError('Unrelated data changed')
        if changed!=len(updates):raise ValueError('Changed population mismatch')
        for lib in summary['libraries']:
            if lib['library'] in ('harp-competition','math-competition'):lib['states']=dict(db.execute('select state,count(*) from records where library=? group by state',(lib['library'],)))
    counts=dict(Counter(x['status'] for x in results));reasons=dict(Counter(x['reason'] for x in results if x['status']=='held'))
    report={**summary,'snapshot_id':identity,'base_snapshot_id':base.name,'created_at':datetime.now(timezone.utc).isoformat(),'catalog_sha256':sha((target/'catalog.sqlite3').read_bytes()),'committed_batches':summary['committed_batches']+1,'closed_arithmetic_checks':{'total':len(results),'counts':counts,'held_reasons':reasons,'scope':'Numeric equality only; all original answers, explanations, asset/rights and curriculum approval gates retained.'}}
    (target/'summary.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n');(target/'closed-arithmetic-review-queue.json').write_text(json.dumps(results,ensure_ascii=False,indent=2)+'\n')
    return {k:report[k] for k in ('snapshot_id','base_snapshot_id','catalog_sha256','committed_batches','closed_arithmetic_checks')}
