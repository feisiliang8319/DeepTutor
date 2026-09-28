"""Link checked adaptations to immutable historical sources without approving either."""
from datetime import datetime,timezone
from pathlib import Path
import hashlib,json,shutil,sqlite3

def sha(blob):return hashlib.sha256(blob).hexdigest()

def build(base,pairs,output):
    return _build(base,pairs,output,lesson_mode=False)


def build_lessons(base,pairs,output):
    """Add worked-example provenance; missing original lesson assets stay unresolved."""
    return _build(base,pairs,output,lesson_mode=True)


def _build(base,pairs,output,*,lesson_mode):
    ledger='lesson-adaptation' if lesson_mode else 'historical-adaptation'
    field='checked_lesson_adaptation' if lesson_mode else 'checked_teaching_adaptation'
    count_field='im_lessons_with_worked_examples' if lesson_mode else 'historical_records_with_checked_adaptations'
    note_field='lesson_adaptation_note' if lesson_mode else 'historical_adaptation_note'
    base=Path(base).resolve();summary=json.loads((base/'summary.json').read_text())
    if base.name!=summary['snapshot_id'] or sha((base/'catalog.sqlite3').read_bytes())!=summary['catalog_sha256']:raise ValueError('Base changed')
    prior_path=base/(ledger+'-links.json')
    prior_list=json.loads(prior_path.read_text()) if prior_path.exists() else []
    prior={entry['source_record_id']:entry for entry in prior_list}
    if len(prior)!=len(prior_list) or len(prior)!=summary.get(count_field,0):raise ValueError('Prior adaptation ledger mismatch')
    evidence=base/(ledger+'-evidence')
    prior_artifacts={p.name:sha(p.read_bytes()) for p in evidence.iterdir() if p.is_file()} if evidence.exists() else {}
    with sqlite3.connect((base/'catalog.sqlite3').as_uri()+'?mode=ro',uri=True) as db:
        actual={}
        for (encoded,) in db.execute('select data_json from records'):
            row=json.loads(encoded);link=row.get('metadata',{}).get(field)
            if link is not None:actual[row['id']]=link
        if actual!=prior:raise ValueError('Prior adaptation records mismatch')
    for link in prior.values():
        if link['package_sha256'] not in prior_artifacts.values() or link['proof_sha256'] not in prior_artifacts.values():raise ValueError('Prior adaptation evidence changed')
    links={};artifacts={}
    for package_path,proof_path in pairs:
        package_path,proof_path=Path(package_path),Path(proof_path)
        package=json.loads(package_path.read_text());proof=json.loads(proof_path.read_text())
        if proof['package_sha256']!=sha(package_path.read_bytes()) or proof['verified_tasks']!=len(package['items']):raise ValueError('Unbound verification evidence')
        for path in (package_path,proof_path):
            if path.name in artifacts:raise ValueError('Duplicate artifact name')
            artifacts[path.name]=path.read_bytes()
        for item in package['items']:
            rubric=item['rubric_json'];key=rubric['source_record_id']
            if key in prior:raise ValueError('Adaptation already linked')
            if key in links:raise ValueError('Duplicate source adaptation')
            links[key]={'candidate_item_id':item['id'],'source_record_id':key,'source_sha256':rubric['source_sha256'],'source_spans':rubric['source_spans'],'package_sha256':proof['package_sha256'],'proof_sha256':sha(proof_path.read_bytes()),'expected_answer_sha256':sha(item['expected_answer'].encode()),'explanation_sha256':sha(item['explanation'].encode()),'scope':'Checked derived mathematical model only; original source and candidate teaching/grade/rights approval unchanged.'}
            if lesson_mode:links[key]['source_lesson_family']=rubric['source_lesson_family']
    if not 0<len(links)<=1000:raise ValueError('Invalid adaptation population')
    if artifacts.keys() & prior_artifacts.keys():raise ValueError('Prior evidence filename collision')
    objects={};updates={}
    with sqlite3.connect((base/'catalog.sqlite3').as_uri()+'?mode=ro',uri=True) as db:
        for key,link in links.items():
            found=db.execute('select data_json from records where id=?',(key,)).fetchone()
            if found is None:raise ValueError('Unknown source record')
            row=json.loads(found[0])
            if row['source_sha256']!=link['source_sha256']:raise ValueError('Source provenance changed')
            if lesson_mode:
                expected=[{'start':row['start'],'end':row['end'],'sha256':row['raw_sha256']}]
                if row['library']!='im-g4-full' or row['kind']!='lesson' or row['family']!=link['source_lesson_family'] or expected!=link['source_spans']:raise ValueError('Lesson provenance changed')
            elif row['library']!='historical-puzzle-books' or row['metadata']['spans']!=link['source_spans']:raise ValueError('Source provenance changed')
            if field in row['metadata']:raise ValueError('Adaptation already linked')
            if row['source_sha256'] not in objects:
                data=(base/'objects'/(row['source_sha256']+('.md' if lesson_mode else '.txt'))).read_bytes()
                if sha(data)!=row['source_sha256']:raise ValueError('Source bytes changed')
                objects[row['source_sha256']]=data.decode() if lesson_mode else data.decode().replace('\r\n','\n')
            text=objects[row['source_sha256']]
            for span in link['source_spans']:
                if sha(text[span['start']:span['end']].encode())!=span['sha256']:raise ValueError('Source span changed')
            row['metadata']={**row['metadata'],field:link};updates[key]=row
    identity=sha(json.dumps({'base':base.name,'links':links,'processor':sha(Path(__file__).read_bytes())},sort_keys=True).encode());target=Path(output)/identity;shutil.copytree(base,target)
    with sqlite3.connect(target/'catalog.sqlite3') as db:
        for row in updates.values():db.execute('update records set data_json=? where id=?',(json.dumps(row,ensure_ascii=False),row['id']))
        db.commit()
        if db.execute('pragma integrity_check').fetchone()[0]!='ok':raise ValueError('Catalog integrity failure')
        changed=0
        with sqlite3.connect((base/'catalog.sqlite3').as_uri()+'?mode=ro',uri=True) as old:
            for aa,bb in zip(old.execute('select data_json from records order by id'),db.execute('select data_json from records order by id'),strict=True):
                a,b=json.loads(aa[0]),json.loads(bb[0])
                if a==b:continue
                changed+=1
                if a['id'] not in links or {k for k in a.keys()|b.keys() if a.get(k)!=b.get(k)}!={'metadata'} or {k:v for k,v in b['metadata'].items() if k!=field}!=a['metadata']:raise ValueError('Unrelated data changed')
        if changed!=len(links):raise ValueError('Changed population mismatch')
    queue=target/(ledger+'-evidence');queue.mkdir(exist_ok=True)
    for name,blob in artifacts.items():(queue/name).write_bytes(blob)
    (target/(ledger+'-links.json')).write_text(json.dumps(list({**prior,**links}.values()),ensure_ascii=False,indent=2)+'\n')
    report={**summary,'snapshot_id':identity,'base_snapshot_id':base.name,'created_at':datetime.now(timezone.utc).isoformat(),'catalog_sha256':sha((target/'catalog.sqlite3').read_bytes()),'committed_batches':summary['committed_batches']+1,count_field:len(prior)+len(links),note_field:'Derived candidate links only; original source remains reference-only. No new formal test approval.'}
    (target/'summary.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    return {k:report[k] for k in ('snapshot_id','base_snapshot_id','catalog_sha256','committed_batches',count_field)}
