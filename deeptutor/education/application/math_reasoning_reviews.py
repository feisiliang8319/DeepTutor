"""Traceable corrections to existing HARP reasoning; no answer or approval changes."""
from datetime import datetime, timezone
import hashlib,json,shutil,sqlite3
from pathlib import Path
from deeptutor.education.application.content_stock import parse_file


def sha(value):
    return hashlib.sha256(value.encode() if isinstance(value,str) else value).hexdigest()


def patch_document(filename,text,reviews):
    before=parse_file('harp-competition',filename,text)
    changes=[];selected={}
    for row in before:
        matches=[r for r in reviews if r['title']==row['title']]
        if not matches:continue
        if len(matches)!=1:raise ValueError('Ambiguous review title')
        r=matches[0]
        if row['answer']!=r['answer_before'] or row['explanation']!=r['explanation_before']:
            raise ValueError('Source explanation or answer changed')
        block=text[row['start']:row['end']]
        old=r['explanation_before'].split('\n\n');new=r['explanation_after'].split('\n\n')
        if len(old)!=len(new):raise ValueError('Solution count changed')
        for a,b in zip(old,new,strict=True):
            if a==b:continue
            if not b.strip() or '\n#' in b or block.count(a)!=1:raise ValueError('Ambiguous solution boundary')
            block=block.replace(a,b,1)
        changes.append((row['start'],row['end'],block));selected[row['title']]=r
    if len(selected)!=len(reviews):raise ValueError('Review population missing')
    after=text
    for start,end,block in reversed(changes):after=after[:start]+block+after[end:]
    parsed=parse_file('harp-competition',filename,after)
    for a,b in zip(before,parsed,strict=True):
        expected=selected[a['title']]['explanation_after'] if a['title'] in selected else a['explanation']
        if b['explanation']!=expected:raise ValueError('Explanation reconstruction mismatch')
        if any(a.get(k)!=b.get(k) for k in (a.keys()|b.keys())-{'explanation','start','end'}):
            raise ValueError('Question or other parsed content changed')
    return after


def build(base,recipe_path,output):
    base=Path(base).resolve();recipe_path=Path(recipe_path)
    summary=json.loads((base/'summary.json').read_text())
    if summary['snapshot_id']!=base.name or sha((base/'catalog.sqlite3').read_bytes())!=summary['catalog_sha256']:
        raise ValueError('Base changed')
    recipe=json.loads(recipe_path.read_text());reviews={r['id']:r for r in recipe['records']}
    if recipe['library']!='harp-competition' or len(reviews)!=len(recipe['records']) or not 0<len(reviews)<=100:
        raise ValueError('Invalid review population')
    with sqlite3.connect((base/'catalog.sqlite3').as_uri()+'?mode=ro',uri=True) as db:
        rows={k:json.loads(db.execute('select data_json from records where id=?',(k,)).fetchone()[0]) for k in reviews}
    for k,row in rows.items():
        r=reviews[k]
        if row['library']!='harp-competition' or any(row[x]!=r[x] for x in ('title','source_path','source_sha256','raw_sha256')) or row['answer']!=r['answer_before'] or row['explanation']!=r['explanation_before'] or 'math_reasoning_review' in row['metadata']:
            raise ValueError('Stale or already applied source review')
        source=(base/'objects'/(row['source_sha256']+'.md')).read_text()
        if sha(source)!=row['source_sha256'] or sha(source[row['start']:row['end']])!=row['raw_sha256']:
            raise ValueError('Original source span changed')
    # Resolve the latest previously revised document, retaining earlier repairs.
    latest={}
    for name in ('math-figure-revised-documents.json','math-reasoning-revised-documents.json'):
        if (base/name).exists():
            latest.update({m['source_path']:m['revised_sha256'] for m in json.loads((base/name).read_text())})
    documents={};manifest=[]
    for path in sorted({r['source_path'] for r in reviews.values()}):
        selection=[r for r in reviews.values() if r['source_path']==path]
        current_hash=latest.get(path,selection[0]['source_sha256'])
        current=(base/'objects'/(current_hash+'.md')).read_text()
        if sha(current)!=current_hash:raise ValueError('Current revised document changed')
        after=patch_document(Path(path).name,current,selection)
        documents[Path(path).name]=after
        manifest.append({'source_path':path,'expected_current_sha256':current_hash,'revised_sha256':sha(after),'changed_questions':len(selection)})
    for k,row in rows.items():
        r=reviews[k];row['explanation']=r['explanation_after']
        row['metadata']={**row['metadata'],'math_reasoning_review':{**r,'recipe_sha256':sha(recipe_path.read_bytes()),'approval':'unchanged','diagram_and_rights_holds':'retained'}}
    identity=sha(json.dumps({'base':base.name,'recipe':sha(recipe_path.read_bytes()),'processor':sha(Path(__file__).read_bytes())},sort_keys=True))
    target=Path(output)/identity;shutil.copytree(base,target)
    destination=target/'math-reasoning-revised-documents';destination.mkdir(exist_ok=True)
    for name,text in documents.items():
        (destination/name).write_text(text);(target/'objects'/(sha(text)+'.md')).write_text(text)
    with sqlite3.connect(target/'catalog.sqlite3') as db:
        for r in rows.values():db.execute('update records set data_json=? where id=?',(json.dumps(r,ensure_ascii=False),r['id']))
        db.commit()
        if db.execute('pragma integrity_check').fetchone()[0]!='ok':raise ValueError('Catalog integrity failure')
        with sqlite3.connect((base/'catalog.sqlite3').as_uri()+'?mode=ro',uri=True) as old:
            changed=0
            for left,right in zip(old.execute('select data_json from records order by id'),db.execute('select data_json from records order by id'),strict=True):
                a,b=json.loads(left[0]),json.loads(right[0])
                if a==b:continue
                changed+=1
                if a['id'] not in reviews or any(a.get(k)!=b.get(k) for k in (a.keys()|b.keys())-{'explanation','metadata'}) or {k:v for k,v in b['metadata'].items() if k!='math_reasoning_review'}!=a['metadata']:
                    raise ValueError('Unrelated content/state/approval changed')
            if changed!=len(reviews):raise ValueError('Changed record count mismatch')
    report={**summary,'snapshot_id':identity,'base_snapshot_id':base.name,'created_at':datetime.now(timezone.utc).isoformat(),'catalog_sha256':sha((target/'catalog.sqlite3').read_bytes()),'committed_batches':summary['committed_batches']+1,'math_reasoning_records_corrected':summary.get('math_reasoning_records_corrected',0)+len(reviews)}
    (target/'summary.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    previous={}
    if (base/'math-reasoning-revised-documents.json').exists():previous={m['source_path']:m for m in json.loads((base/'math-reasoning-revised-documents.json').read_text())}
    previous.update({m['source_path']:m for m in manifest})
    (target/'math-reasoning-revised-documents.json').write_text(json.dumps(list(previous.values()),indent=2)+'\n')
    (target/recipe_path.name).write_bytes(recipe_path.read_bytes())
    return {'snapshot_id':identity,'base_snapshot_id':base.name,'changed_documents':manifest,'changed_records':len(reviews),'question_answer_approval_changes':0}
