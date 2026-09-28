"""Bounded exact rational-function identities for source-bound stock review.

Formal polynomial expansion and cross multiplication, never random substitution,
eval, symbolic string evaluation, or LLM judgement. A match holds only where both
expressions are defined; it does not certify equal domains or approve an item.
"""
from fractions import Fraction
import re
from .closed_math_checks import Parser as NumericParser, Unsupported


class Budget:
    def __init__(self):
        self.operations=0;self.conditions=[];self.side='source_expression'

    def spend(self,n=1):
        self.operations+=n
        if self.operations>100000:raise Unsupported('polynomial_operation_limit')

    def require_nonzero(self,p):
        if not p:raise Unsupported('identically_zero_denominator')
        if set(p)!={()}:
            condition={'side':self.side,'nonzero_polynomial':[[str(c),list(m)] for m,c in sorted(p.items())]}
            if condition not in self.conditions:self.conditions.append(condition)


def clean(p):
    p={m:c for m,c in p.items() if c}
    if len(p)>512:raise Unsupported('polynomial_term_limit')
    for m,c in p.items():
        if sum(e for _,e in m)>64 or max(abs(c.numerator).bit_length(),c.denominator.bit_length())>2048:
            raise Unsupported('polynomial_degree_or_coefficient_limit')
    return p


def add(a,b,budget):
    budget.spend(len(a)+len(b));result=dict(a)
    for m,c in b.items():result[m]=result.get(m,Fraction(0))+c
    return clean(result)


def multiply(a,b,budget):
    budget.spend(len(a)*len(b));result={}
    for am,ac in a.items():
        for bm,bc in b.items():
            powers=dict(am)
            for v,e in bm:powers[v]=powers.get(v,0)+e
            monomial=tuple(sorted(powers.items()))
            result[monomial]=result.get(monomial,Fraction(0))+ac*bc
            if len(result)>512:raise Unsupported('polynomial_term_limit')
    return clean(result)


class Rational:
    def __init__(self,n,budget,d=None):
        self.n=clean(n);self.d=clean(d if d is not None else {():Fraction(1)});self.budget=budget
        if not self.d:raise Unsupported('identically_zero_denominator')

    @classmethod
    def constant(cls,value,budget):return cls({():Fraction(value)},budget)

    def __neg__(self):return Rational({m:-c for m,c in self.n.items()},self.budget,self.d)
    def __add__(self,other):
        b=self.budget
        return Rational(add(multiply(self.n,other.d,b),multiply(other.n,self.d,b),b),b,multiply(self.d,other.d,b))
    def __sub__(self,other):return self+-other
    def __mul__(self,other):return Rational(multiply(self.n,other.n,self.budget),self.budget,multiply(self.d,other.d,self.budget))
    def __truediv__(self,other):
        self.budget.require_nonzero(other.n)
        return Rational(multiply(self.n,other.d,self.budget),self.budget,multiply(self.d,other.n,self.budget))

    def power(self,e):
        if abs(e)>16:raise Unsupported('polynomial_exponent_limit')
        if e<=0:self.budget.require_nonzero(self.n)
        base=self if e>=0 else Rational(self.d,self.budget,self.n)
        result=Rational.constant(1,self.budget)
        for _ in range(abs(e)):result=result*base
        return result


class Parser(NumericParser):
    def __init__(self,text,budget):
        super().__init__(text);self.budget=budget;self.variables=set()
        if re.search(r'(?:sin|cos|tan|cot|sec|csc|log|ln|exp)',self.text):raise Unsupported('unsupported_function')

    def expression(self):
        self.enter();value=self.term()
        while True:
            if self.take('+'):value=value+self.term()
            elif self.take('-'):value=value-self.term()
            else:break
        self.depth-=1;return value

    def term(self):
        value=self.unary();unbracketed_division=False
        while True:
            if self.take('*') or self.take(r'\cdot') or self.take(r'\times'):value=value*self.unary()
            elif self.take('/') or self.take(r'\div'):
                unbracketed_division=True;value=value/self.unary()
            else:
                self.skip();tail=self.text[self.i:]
                starts=tail[:1].isascii() and tail[:1].isalpha()
                starts=starts or any(tail.startswith(x) for x in ('(', '{',r'\frac',r'\dfrac',r'\tfrac'))
                if not starts:break
                if unbracketed_division:raise Unsupported('ambiguous_juxtaposed_division')
                value=value*self.unary()
        return value

    def argument(self):
        self.skip()
        if self.take('{'):
            value=self.expression();self.require('}');return value
        if self.i<len(self.text) and self.text[self.i].isdigit():
            value=Rational.constant(self.text[self.i],self.budget);self.i+=1;return value
        if self.i<len(self.text) and self.text[self.i].isascii() and self.text[self.i].isalpha():return self.atom()
        raise Unsupported('unbraced_polynomial_argument')

    def power(self):
        value=self.atom()
        if self.take('^'):
            self.skip()
            if self.take('{'):
                end=self.text.find('}',self.i)
                if end<0:raise Unsupported('missing_delimiter')
                exponent=self.text[self.i:end].strip()
                if not re.fullmatch(r'[+-]?\d{1,2}',exponent):raise Unsupported('noninteger_polynomial_exponent')
                self.i=end+1
            else:
                if self.i>=len(self.text) or not self.text[self.i].isdigit():raise Unsupported('unbraced_argument')
                exponent=self.text[self.i];self.i+=1
                if self.i<len(self.text) and self.text[self.i].isdigit():raise Unsupported('unbraced_multidigit_exponent')
            value=value.power(int(exponent))
        return value

    def atom(self):
        self.enter();self.skip()
        if self.take('('):value=self.expression();self.require(')')
        elif self.take('{'):value=self.expression();self.require('}')
        elif self.take(r'\frac') or self.take(r'\dfrac') or self.take(r'\tfrac'):
            numerator=self.argument();denominator=self.argument();value=numerator/denominator
        elif self.i<len(self.text) and self.text[self.i].isascii() and self.text[self.i].isalpha():
            variable=self.text[self.i];self.i+=1
            if variable in 'eiEI':raise Unsupported('reserved_constant_or_ambiguous_variable')
            self.variables.add(variable)
            if len(self.variables)>6:raise Unsupported('variable_count_limit')
            value=Rational({((variable,1),):Fraction(1)},self.budget)
        else:
            match=re.match(r'(?:\d+(?:\.\d*)?|\.\d+)',self.text[self.i:])
            if not match or len(match[0])>100:raise Unsupported('unsupported_polynomial_atom')
            self.i+=len(match[0]);value=Rational.constant(match[0],self.budget)
        self.depth-=1;return value


def compare(expression,answer):
    budget=Budget();left=Parser(expression,budget);a=left.parse()
    budget.side='source_answer';right=Parser(answer,budget);b=right.parse()
    difference=add(multiply(a.n,b.d,budget),{m:-c for m,c in multiply(b.n,a.d,budget).items()},budget)
    return {'status':'match' if not difference else 'mismatch','method':'exact rational coefficient expansion and cross multiplication','variables':sorted(left.variables|right.variables),'nonzero_conditions':budget.conditions,'residual_polynomial_terms':len(difference),'scope':'Rational-function identity only on the common defined domain. Equal domains, original explanations, source rights and curriculum approval are not certified.'}


def check(row):
    match=re.fullmatch(r'(?:Evaluate|Simplify|Compute|What is(?: the value of)?)\s+\$([^$]+)\$[.!?]?',row['prompt'].strip(),re.I|re.S)
    if not match or any(x in row['issues'] for x in ('missing_figure','unrendered_diagram')):return None
    expression=match[1].strip()
    if not re.search(r'[A-Za-z]',re.sub(r'\\[A-Za-z]+','',expression)):return None
    if expression.endswith('.') and not re.search(r'\d\.$',expression):expression=expression[:-1]
    answer=row['answer'].strip()
    if answer.startswith('$') and answer.endswith('$'):answer=answer[1:-1].strip()
    try:return {**compare(expression,answer),'expression':expression}
    except (Unsupported,ValueError,ZeroDivisionError,RecursionError) as exc:
        return {'status':'held','reason':str(exc),'scope':'Unsupported algebra form; no identity or answer approval.'}

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
        if 'closed_algebra_check' in row['metadata']:raise ValueError('Review already exists')
        source=row['source_sha256']
        if source not in objects:
            blob=(base/'objects'/(source+'.md')).read_bytes()
            if sha(blob)!=source:raise ValueError('Source object changed')
            objects[source]=blob.decode()
        original=objects[source][row['start']:row['end']]
        if sha(original)!=row['raw_sha256'] or row['prompt'] not in original:raise ValueError('Source span changed')
        review={**result,'record_id':row['id'],'source_sha256':source,'source_raw_sha256':row['raw_sha256'],'prompt_sha256':sha(row['prompt']),'answer_sha256':sha(row['answer']),'checker_sha256':sha(Path(__file__).read_bytes()),'checker_dependencies':{'numeric_parser_sha256':sha(Path(__file__).with_name('closed_math_checks.py').read_bytes())},'approval':'unchanged'}
        results.append(review)
        row['metadata']={**row['metadata'],'closed_algebra_check':review}
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
                if a['id'] not in updates or not {k for k in a.keys()|b.keys() if a.get(k)!=b.get(k)}<={'metadata','state'} or {k:v for k,v in b['metadata'].items() if k!='closed_algebra_check'}!=a['metadata']:raise ValueError('Unrelated data changed')
        if changed!=len(updates):raise ValueError('Changed population mismatch')
        for lib in summary['libraries']:
            if lib['library'] in ('harp-competition','math-competition'):lib['states']=dict(db.execute('select state,count(*) from records where library=? group by state',(lib['library'],)))
    counts=dict(Counter(x['status'] for x in results));reasons=dict(Counter(x['reason'] for x in results if x['status']=='held'))
    report={**summary,'snapshot_id':identity,'base_snapshot_id':base.name,'created_at':datetime.now(timezone.utc).isoformat(),'catalog_sha256':sha((target/'catalog.sqlite3').read_bytes()),'committed_batches':summary['committed_batches']+1,'closed_algebra_checks':{'total':len(results),'counts':counts,'held_reasons':reasons,'scope':'Rational identity on common defined domain only; original answers, explanations, rights, assets and curriculum approval unchanged.'}}
    (target/'summary.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n');(target/'closed-algebra-review-queue.json').write_text(json.dumps(results,ensure_ascii=False,indent=2)+'\n')
    return {k:report[k] for k in ('snapshot_id','base_snapshot_id','catalog_sha256','committed_batches','closed_algebra_checks')}
