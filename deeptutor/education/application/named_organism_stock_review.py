"""Check stated binomial-name relations; do not certify taxonomy or images."""
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import shutil
import sqlite3

from .content_stock import parse_file

CONCEPT = '294384df51365aced9d26ed7d3ac59a4fb84126426b029c897301446a6dec3bb'
KEY = 'given_name_relation_check'
NAME = r'[A-Z][a-z]+ [a-z]+'


def sha(value):
    return hashlib.sha256(value.encode() if isinstance(value,str) else value).hexdigest()


def concept(row):
    original = row['metadata'].get('lecture_review',{}).get('lecture_before',row['lecture'])
    return sha(re.sub(r'\s+',' ',original).strip())


def verify(row):
    if row['library'] != 'scienceqa' or concept(row) != CONCEPT:
        raise ValueError('Outside reviewed name-relation family')
    if set(row['issues']) - {'missing_figure'}:
        raise ValueError('Other unresolved structural issues')
    match = re.fullmatch(r'This organism is (?:a|an) ([^.\n]+)\. Its scientific name is ('+NAME+r')\.\n\nSelect the organism in the same (genus|species) as the ([^.\n]+)\.', row['prompt'])
    if not match or match[1] != match[4]:
        raise ValueError('Unsupported or inconsistent subject premise')
    options = row['options']
    if len(options)<2 or len(set(options))!=len(options) or not all(re.fullmatch(NAME,o) for o in options):
        raise ValueError('Unsupported or duplicate scientific-name options')
    name, relation = match[2],match[3]
    comparisons = {o:(o.split()[0]==name.split()[0] if relation=='genus' else o==name) for o in options}
    selected = [o for o,matches in comparisons.items() if matches]
    if len(selected)!=1:
        raise ValueError('Name relation does not select a unique option')
    if selected[0]!=row['answer']:
        raise ValueError('Source answer contradicts stated-name comparison')
    return {'algorithm':'Compare genus tokens or complete binomina supplied in the text; require one matching option.','stated_name':name,'relation':relation,'option_matches':comparisons,'answer':selected[0],'scope':'Conditional on the explicitly stated names. Does not certify current biological taxonomy, image identity, all explanation claims, curriculum, rights or whole-question approval.','missing_figure_gate_retained':'missing_figure' in row['issues']}


def annotate(base, output, expected=341):
    base,output=Path(base).resolve(),Path(output)
    previous=json.loads((base/'summary.json').read_text())
    if previous['snapshot_id']!=base.name or sha((base/'catalog.sqlite3').read_bytes())!=previous['catalog_sha256']:
        raise ValueError('Base snapshot changed')
    checks={};objects={};parsed={}
    with sqlite3.connect((base/'catalog.sqlite3').as_uri()+'?mode=ro',uri=True) as db:
        for payload, in db.execute("select data_json from records where library='scienceqa'"):
            row=json.loads(payload)
            if concept(row)!=CONCEPT:
                continue
            if KEY in row['metadata']:
                raise ValueError('Existing name-relation proof requires an explicit revision')
            source_sha=row['source_sha256']
            if source_sha not in objects:
                blob=(base/'objects'/(source_sha+'.md')).read_bytes()
                if sha(blob)!=source_sha:
                    raise ValueError('Source object changed')
                objects[source_sha]=blob.decode()
                parsed[source_sha]={r['start']:r for r in parse_file('scienceqa',Path(row['source_path']).name,objects[source_sha])}
            if sha(objects[source_sha][row['start']:row['end']])!=row['raw_sha256']:
                raise ValueError('Question source span changed')
            original=parsed[source_sha].get(row['start'])
            if not original or any(original[k]!=row[k] for k in ('title','prompt','options','answer')):
                raise ValueError('Current question differs from immutable source')
            check=verify(row)
            checks[row['id']]={**check,**{k:row[k] for k in ('source_sha256','raw_sha256','source_path','source_line')},'checker_sha256':sha(Path(__file__).read_bytes()),'checked_on':'2026-09-28'}
    if len(checks)!=expected:
        raise ValueError('Reviewed family count changed')
    identity=sha(json.dumps({'base':base.name,'checks':checks,'processor':sha(Path(__file__).read_bytes())},sort_keys=True))
    target=output/identity
    shutil.copytree(base,target)
    with sqlite3.connect((base/'catalog.sqlite3').as_uri()+'?mode=ro',uri=True) as old,sqlite3.connect(target/'catalog.sqlite3') as new:
        for record_id,check in checks.items():
            row=json.loads(new.execute('select data_json from records where id=?',(record_id,)).fetchone()[0])
            row['metadata']={**row['metadata'],KEY:check}
            new.execute('update records set data_json=? where id=?',(json.dumps(row,ensure_ascii=False),record_id))
        new.commit()
        if new.execute('pragma integrity_check').fetchone()[0]!='ok':
            raise ValueError('Catalog integrity failure')
        actual=0
        for a,b in zip(old.execute('select data_json from records order by id'),new.execute('select data_json from records order by id'),strict=True):
            a,b=json.loads(a[0]),json.loads(b[0])
            if a==b:
                continue
            if (a['id'] not in checks or {k for k in a.keys()|b.keys() if a.get(k)!=b.get(k)}!={'metadata'} or
                {k:v for k,v in b['metadata'].items() if k!=KEY}!=a['metadata']):
                raise ValueError('Unrelated data changed')
            actual+=1
        if actual!=expected:
            raise ValueError('Annotation count mismatch')
    report={'source_snapshot':base.name,'snapshot_id':identity,'verified':len(checks),'by_relation':dict(Counter(r['relation'] for r in checks.values())),'missing_figure_flags_retained':sum(r['missing_figure_gate_retained'] for r in checks.values()),'question_answer_approval_changes':0,'records':checks}
    summary={**previous,'snapshot_id':identity,'base_snapshot_id':base.name,'created_at':datetime.now(timezone.utc).isoformat(),'catalog_sha256':sha((target/'catalog.sqlite3').read_bytes()),'committed_batches':previous['committed_batches']+1,'given_name_relation_answers_checked':len(checks),'given_name_relation_checker_sha256':sha(Path(__file__).read_bytes())}
    (target/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n')
    (target/'given-name-relation-checks.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    return {k:v for k,v in report.items() if k!='records'}
