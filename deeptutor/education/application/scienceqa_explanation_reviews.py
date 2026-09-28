"""Source-bound ScienceQA explanation corrections on a staged lecture snapshot.

Keep original answer choices for traceability; explicitly hold questions whose
choices embody the source misconception. Never approve or clear figure gates.
The revised manifest still targets the original live documents, so the lecture
and explanation corrections can be activated together after index verification.
"""
from datetime import datetime,timezone
import hashlib,json,re,shutil,sqlite3
from pathlib import Path
from .content_stock import parse_file

def sha(value):return hashlib.sha256(value.encode() if isinstance(value,str) else value).hexdigest()

def patch_document(filename,text,reviews):
    old=parse_file('scienceqa',filename,text);changes=[];selected={}
    for row in old:
        candidates=[r for r in reviews if r['source_title']==row['title']]
        if not candidates:continue
        if len(candidates)!=1:raise ValueError('Ambiguous source title')
        review=candidates[0]
        if row['answer']!=review['answer_before'] or row['explanation']!=review['explanation_before']:raise ValueError('Source explanation or answer changed')
        replacement=review['explanation_after']
        if not replacement.strip() or re.search(r'^#{1,3} |^---\s*$',replacement,re.M):raise ValueError('Invalid replacement')
        block=text[row['start']:row['end']]
        pattern=re.compile(r'(^### Explanation\n)(.*?)(?=^### |^## |^---\s*$|\Z)',re.M|re.S)
        matches=list(pattern.finditer(block))
        if len(matches)!=1 or matches[0][2].strip()!=row['explanation']:raise ValueError('Explanation boundary mismatch')
        body=matches[0][2];leading=body[:len(body)-len(body.lstrip())];trailing=body[len(body.rstrip()):]
        patched=pattern.sub(lambda m:m[1]+leading+replacement+trailing,block,count=1)
        changes.append((row['start'],row['end'],patched));selected[row['title']]=review
    if len(selected)!=len(reviews):raise ValueError('Some records were not found')
    after=text
    for start,end,block in reversed(changes):after=after[:start]+block+after[end:]
    parsed=parse_file('scienceqa',filename,after)
    for a,b in zip(old,parsed,strict=True):
        expected=selected[a['title']]['explanation_after'] if a['title'] in selected else a['explanation']
        if b['explanation']!=expected:raise ValueError('Reparsed explanation mismatch')
        if any(a.get(k)!=b.get(k) for k in (a.keys()|b.keys())-{'explanation','start','end'}):raise ValueError('Question or original answer changed')
    return after


def build(base,recipe_path,output):
    base=Path(base).resolve();recipe_path=Path(recipe_path);summary=json.loads((base/'summary.json').read_text())
    if base.name!=summary['snapshot_id'] or sha((base/'catalog.sqlite3').read_bytes())!=summary['catalog_sha256']:raise ValueError('Base changed')
    recipe=json.loads(recipe_path.read_text());reviews={r['record_id']:r for r in recipe['records']}
    expected=recipe.get('expected_changed_records',16);expected_holds=recipe.get('expected_answers_on_hold',2)
    if recipe['library']!='scienceqa' or not 0 < expected <= 1000 or len(reviews)!=len(recipe['records']) or len(reviews)!=expected or any(type(r['answer_on_hold']) is not bool for r in reviews.values()) or sum(r['answer_on_hold'] for r in reviews.values())!=expected_holds:raise ValueError('Unexpected review population')
    with sqlite3.connect((base/'catalog.sqlite3').as_uri()+'?mode=ro',uri=True) as db:
        rows={key:json.loads(db.execute('select data_json from records where id=?',(key,)).fetchone()[0]) for key in reviews}
    for key,row in rows.items():
        r=reviews[key]
        if 'individual_context_review' in row['metadata']:raise ValueError('Context-reviewed passages require an explicit joint revision')
        if row['library']!='scienceqa' or row['title']!=r['source_title'] or any(row[k]!=r[k] for k in ('source_path','source_sha256','raw_sha256')) or row['answer']!=r['answer_before'] or row['explanation']!=r['explanation_before'] or 'individual_explanation_review' in row['metadata']:raise ValueError('Source review is stale')
        original=(base/'objects'/(row['source_sha256']+'.md')).read_text()
        if sha(original)!=row['source_sha256'] or sha(original[row['start']:row['end']])!=row['raw_sha256']:raise ValueError('Source bytes changed')
        row['explanation']=r['explanation_after'];row['metadata']={**row['metadata'],'individual_explanation_review':{**r,'recipe_sha256':sha(recipe_path.read_bytes()),'approval':'unchanged'}}
        if r['answer_on_hold'] and row['state']!='duplicate':row['state']='needs_fact_check'
    manifest=json.loads((base/'revised-documents.json').read_text());documents={};seen=set()
    for entry in manifest:
        filename=Path(entry['source_path']).name;before=(base/'revised-documents'/filename).read_text()
        if sha(before)!=entry['revised_sha256']:raise ValueError('Staged lecture document changed')
        selected=[r for r in reviews.values() if r['source_path']==entry['source_path']]
        if not selected:continue
        documents[filename]=patch_document(filename,before,selected);seen.update(r['record_id'] for r in selected)
        entry['revised_sha256']=sha(documents[filename]);entry['changed_explanations']=len(selected)
    if seen!=reviews.keys():raise ValueError('Missing staged source document')
    identity=sha(json.dumps({'base':base.name,'recipe':sha(recipe_path.read_bytes()),'processor':sha(Path(__file__).read_bytes())},sort_keys=True));target=Path(output)/identity;shutil.copytree(base,target)
    for name,text in documents.items():(target/'revised-documents'/name).write_text(text);(target/'objects'/(sha(text)+'.md')).write_text(text)
    with sqlite3.connect(target/'catalog.sqlite3') as db:
        for row in rows.values():db.execute('update records set state=?,data_json=? where id=?',(row['state'],json.dumps(row,ensure_ascii=False),row['id']))
        db.commit()
        if db.execute('pragma integrity_check').fetchone()[0]!='ok':raise ValueError('Catalog integrity failure')
        changed=0
        with sqlite3.connect((base/'catalog.sqlite3').as_uri()+'?mode=ro',uri=True) as old:
            for a,b in zip(old.execute('select data_json from records order by id'),db.execute('select data_json from records order by id'),strict=True):
                a,b=json.loads(a[0]),json.loads(b[0])
                if a==b:continue
                changed+=1
                if a['id'] not in rows or not {k for k in a.keys()|b.keys() if a.get(k)!=b.get(k)}<={'metadata','state','explanation'} or {k:v for k,v in b['metadata'].items() if k!='individual_explanation_review'}!=a['metadata']:raise ValueError('Unrelated data changed')
        if changed!=expected:raise ValueError('Changed population mismatch')
        total_reviewed=total_held=0
        for raw, in db.execute("select data_json from records where library='scienceqa'"):
            prior=json.loads(raw)['metadata'].get('individual_explanation_review')
            if prior:
                total_reviewed+=1;total_held+=bool(prior['answer_on_hold'])
        for lib in summary['libraries']:
            if lib['library']=='scienceqa':lib['states']=dict(db.execute("select state,count(*) from records where library='scienceqa' group by state"))
    report={**summary,'snapshot_id':identity,'base_snapshot_id':base.name,'created_at':datetime.now(timezone.utc).isoformat(),'catalog_sha256':sha((target/'catalog.sqlite3').read_bytes()),'committed_batches':summary['committed_batches']+1,'scienceqa_individual_explanations_corrected':total_reviewed,'scienceqa_source_answers_on_hold':total_held,'scienceqa_batch_individual_explanations_corrected':expected,'scienceqa_batch_source_answers_on_hold':expected_holds}
    (target/'summary.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n');(target/'revised-documents.json').write_text(json.dumps(manifest,indent=2)+'\n');(target/recipe_path.name).write_bytes(recipe_path.read_bytes())
    return {'snapshot_id':identity,'changed_lectures':summary['scienceqa_batch_linked_lectures_corrected'],'changed_explanations':expected,'answers_on_hold':expected_holds,'changed_documents':manifest,'question_or_answer_changes':0,'formal_items_created':0}
