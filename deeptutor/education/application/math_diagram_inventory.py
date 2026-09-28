"""Inventory existing diagram source as inert data; never execute drawing code."""
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import shutil
import sqlite3
from .content_stock import has_unrendered_diagram, state


def sha(value):
    return hashlib.sha256(value.encode() if isinstance(value, str) else value).hexdigest()


def describe(row):
    fields={}
    for name in ('prompt','explanation'):
        text=row[name]
        parts=list(re.finditer(r'\[asy\](.*?)\[/asy\]',text,re.S|re.I))
        if len(parts)!=len(re.findall(r'\[asy\]',text,re.I)) or len(parts)!=len(re.findall(r'\[/asy\]',text,re.I)):
            raise ValueError('Incomplete Asymptote block')
        fields[name]=[{'sha256':sha(m[1]),'code':m[1],'start':m.start(1),'end':m.end(1)} for m in parts]
    role='prompt_and_solution' if all(fields.values()) else 'prompt_only' if fields['prompt'] else 'solution_only' if fields['explanation'] else 'other_syntax'
    return {'role':role,'fields':fields,'execution':'never_executed','approval':'unchanged'}


def build(base, output):
    base=Path(base).resolve();previous=json.loads((base/'summary.json').read_text())
    if previous['snapshot_id']!=base.name or sha((base/'catalog.sqlite3').read_bytes())!=previous['catalog_sha256']:raise ValueError('Base changed')
    with sqlite3.connect((base/'catalog.sqlite3').as_uri()+'?mode=ro',uri=True) as db:
        rows=[json.loads(x[0]) for x in db.execute("select data_json from records where library in ('harp-competition','math-competition')")]
    rows=[r for r in rows if 'unrendered_diagram' in r['issues']]
    if len(rows)!=3189 or any('diagram_inventory' in r['metadata'] for r in rows):raise ValueError('Unexpected or already processed population')
    objects={};blocks={};roles=Counter();updates={};repairs=[]
    for row in rows:
        source=row['source_sha256']
        if source not in objects:
            blob=(base/'objects'/(source+'.md')).read_bytes()
            if sha(blob)!=source:raise ValueError('Source changed')
            objects[source]=blob.decode()
        original=objects[source][row['start']:row['end']]
        if sha(original)!=row['raw_sha256']:raise ValueError('Source span changed')
        evidence=describe(row)
        if evidence['role']=='other_syntax':
            if row['id']!='aad8bf0daf38c076f0d21c4a1a6396b65e7500e9ce4c4d03e2ac145a50868923' or row['raw_sha256']!='fd1089050eadbca070c0577d3e20b8208fe70cbe54c9dbac8593e17374c1b4f1' or has_unrendered_diagram(original):raise ValueError('Unsupported non-Asymptote diagram')
            if [n for n in range(1,441) if (n+1)*(n+3)==440]!=[19] or row['answer']!='$10$':raise ValueError('Factorial answer check changed')
            row['issues']=[x for x in row['issues'] if x!='unrendered_diagram'];row['state']=state(row)
            evidence.update(role='factorial_not_image',reason='n![...] is factorial multiplication, not an image. n! cancels since n>0; (n+2)^2=441 gives n=19 and digit sum10. The original source and answer are unchanged.')
            repairs.append(row['id'])
        else:
            roles[evidence['role']]+=1
            for field,items in evidence['fields'].items():
                for index,item in enumerate(items):
                    if item['code'] not in original:raise ValueError('Drawing code not in original source')
                    block=blocks.setdefault(item['sha256'],{'id':item['sha256'],'code':item['code'],'references':[]})
                    block['references'].append({'record_id':row['id'],'field':field,'ordinal':index,'source_sha256':source,'raw_sha256':row['raw_sha256'],'source_path':row['source_path'],'source_line':row['source_line']})
        row['metadata']={**row['metadata'],'diagram_inventory':{**evidence,'fields':{k:[{f:v for f,v in x.items() if f!='code'} for x in items] for k,items in evidence['fields'].items()},'source_sha256':source,'raw_sha256':row['raw_sha256']}}
        updates[row['id']]=row
    if len(repairs)!=1 or sum(roles.values())!=3188 or len(blocks)!=4072:raise ValueError('Inventory totals changed')
    identity=sha(json.dumps({'base':base.name,'processor':sha(Path(__file__).read_bytes()),'parser':sha(Path(__file__).with_name('content_stock.py').read_bytes())},sort_keys=True));target=Path(output)/identity;shutil.copytree(base,target)
    with sqlite3.connect(target/'catalog.sqlite3') as db:
        for row in updates.values():db.execute('update records set state=?,data_json=? where id=?',(row['state'],json.dumps(row,ensure_ascii=False),row['id']))
        db.commit()
        if db.execute('pragma integrity_check').fetchone()[0]!='ok':raise ValueError('Integrity failure')
        with sqlite3.connect((base/'catalog.sqlite3').as_uri()+'?mode=ro',uri=True) as old:
            actual=0
            for a,b in zip(old.execute('select data_json from records order by id'),db.execute('select data_json from records order by id'),strict=True):
                a,b=json.loads(a[0]),json.loads(b[0])
                if a==b:continue
                actual+=1;allowed={'metadata','state','issues'} if a['id'] in repairs else {'metadata'}
                if a['id'] not in updates or not {k for k in a.keys()|b.keys() if a.get(k)!=b.get(k)}<=allowed:raise ValueError('Unrelated field changed')
                if {k:v for k,v in b['metadata'].items() if k!='diagram_inventory'}!=a['metadata']:raise ValueError('Prior provenance changed')
            if actual!=3189:raise ValueError('Changed record count mismatch')
        for library in previous['libraries']:
            if library['library'] not in ('harp-competition','math-competition'):continue
            members=[json.loads(x[0]) for x in db.execute('select data_json from records where library=?',(library['library'],))]
            library['states']=dict(Counter(r['state'] for r in members));library['issues']=dict(Counter(i for r in members for i in r['issues']))
    previous['issues']['unrendered_diagram']-=1
    report={**previous,'snapshot_id':identity,'base_snapshot_id':base.name,'catalog_sha256':sha((target/'catalog.sqlite3').read_bytes()),'committed_batches':previous['committed_batches']+1,'created_at':datetime.now(timezone.utc).isoformat(),'math_diagram_records':3188,'math_diagram_roles':dict(roles),'math_diagram_unique_blocks':len(blocks),'math_diagram_occurrences':sum(len(b['references']) for b in blocks.values()),'math_false_image_repairs':repairs}
    (target/'summary.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n');(target/'math-diagram-queue.json').write_text(json.dumps(list(blocks.values()),ensure_ascii=False,indent=2)+'\n')
    return {k:report[k] for k in ('snapshot_id','math_diagram_records','math_diagram_roles','math_diagram_unique_blocks','math_diagram_occurrences','math_false_image_repairs','committed_batches')}
