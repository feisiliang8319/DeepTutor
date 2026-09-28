"""Apply source-bound, independently checked diagram reviews to a candidate catalog.

Artifacts remain internal review files. Figure/rights/curriculum and student
approval gates are never cleared. Only one invalid source solution is replaced;
the source's other two correct solutions remain byte-identical.
"""
from datetime import datetime,timezone
import hashlib,json,re,shutil,sqlite3
from pathlib import Path
import xml.etree.ElementTree as ET
from .content_stock import parse_file

CORRECTION = ('DeepTutor reviewed correction: Choosing any three of nine cells does not count the requested configurations; its numerical result 84 is coincidental. Both monochromatic lines must be disjoint. A diagonal intersects every other possible line, and a row intersects every column, so only distinct parallel rows or distinct parallel columns can work. For rows, six configurations have three monochromatic rows using both symbols; another 3*2*(2^3-2)=36 have one circle row, one triangle row and one mixed row. Thus there are 42 row cases. The 42 column cases cannot overlap the row cases. Total: 84. Independent exhaustive enumeration of all 512 binary grids gives the same result. Existing diagram, rights, grade suitability and student approval checks remain pending.')

def sha(value):return hashlib.sha256(value.encode() if isinstance(value,str) else value).hexdigest()

def safe_artifact(folder,review):
    folder=Path(folder)
    if not re.fullmatch(r'stock-math-[a-z-]+-v1',review['id']):raise ValueError('Invalid figure identifier')
    values={}
    for suffix,key in [('svg','svg_sha256'),('json','spec_sha256')]:
        path=folder/(review['id']+'.'+suffix)
        if path.is_symlink():raise ValueError('Symlink artifact')
        blob=path.read_bytes()
        if sha(blob)!=review[key]:raise ValueError('Figure artifact changed')
        values[suffix]=blob
    spec=json.loads(values['json'])
    if spec['source_record_id']!=review['source_record_id'] or spec['source_raw_sha256']!=review['source_raw_sha256'] or spec['source_sha256']!=review['source_sha256'] or spec['data']!=review['data'] or spec['kind']!=review['kind']:
        raise ValueError('Figure source binding changed')
    allowed_attributes={'width','height','viewBox','role','aria-label','rx','fill','font-family','x','y','cx','cy','r','d','stroke','stroke-width','stroke-linejoin','text-anchor','dominant-baseline','font-size'}
    for node in ET.fromstring(values['svg']).iter():
        if node.tag.rsplit('}',1)[-1] not in {'svg','g','rect','circle','path','text'} or any(k not in allowed_attributes or re.search(r'url\s*\(|javascript:',v,re.I) for k,v in node.attrib.items()):raise ValueError('Unsupported SVG content')
    return values


def patch_document(filename,text,review):
    old=parse_file('harp-competition',filename,text)
    matches=[r for r in old if r['title']==review['source_title']]
    if len(matches)!=1:raise ValueError('Target question not unique')
    row=matches[0]
    if sha(row['explanation'])!=review['explanation_before_sha256'] or row['answer']!=review['answer_before']:raise ValueError('Source answer or reasoning changed')
    block=text[row['start']:row['end']]
    pattern=re.compile(r'(^### Solution 1 of 3\n\n)(.*?)(?=\n\n### Solution 2 of 3\n)',re.M|re.S)
    if len(list(pattern.finditer(block)))!=1:raise ValueError('Expected first-solution boundary')
    patched=pattern.sub(lambda m:m[1]+CORRECTION,block,count=1)
    after=text[:row['start']]+patched+text[row['end']:]
    parsed=parse_file('harp-competition',filename,after);changed=0;new_explanation=None
    for a,b in zip(old,parsed,strict=True):
        allowed={'start','end'}
        if a['title']==review['source_title']:
            allowed.add('explanation');changed+=1;new_explanation=b['explanation']
            first=a['explanation'].split('\n\n')[0]
            if b['explanation']!=CORRECTION+a['explanation'][len(first):]:raise ValueError('Other solutions changed')
        if any(a.get(k)!=b.get(k) for k in (a.keys()|b.keys())-allowed):raise ValueError('Unrelated question/source content changed')
    if changed!=1:raise ValueError('Correction count mismatch')
    return after,new_explanation


def build(base,recipe_path,artifact_folder,output):
    base=Path(base).resolve();recipe_path=Path(recipe_path);summary=json.loads((base/'summary.json').read_text())
    if base.name!=summary['snapshot_id'] or sha((base/'catalog.sqlite3').read_bytes())!=summary['catalog_sha256']:raise ValueError('Base changed')
    recipe=json.loads(recipe_path.read_text());reviews={r['source_record_id']:r for r in recipe['records']}
    if len(reviews)!=8 or sum(r['replace_explanation'] for r in reviews.values())!=1:raise ValueError('Expected eight diagram checks and one correction')
    with sqlite3.connect((base/'catalog.sqlite3').as_uri()+'?mode=ro',uri=True) as db:
        rows={key:json.loads(db.execute('select data_json from records where id=?',(key,)).fetchone()[0]) for key in reviews}
    files={};assets={};changed_documents=[];corrected_row=None
    for key,row in rows.items():
        review=reviews[key]
        if row['source_sha256']!=review['source_sha256'] or row['raw_sha256']!=review['source_raw_sha256'] or row['source_path']!=review['source_path'] or row['answer']!=review['answer_before'] or sha(row['explanation'])!=review['explanation_before_sha256'] or 'math_figure_review' in row['metadata']:raise ValueError('Source review no longer matches catalog')
        source=row['source_sha256']
        if source not in files:
            blob=(base/'objects'/(source+'.md')).read_bytes()
            if sha(blob)!=source:raise ValueError('Source object changed')
            files[source]=blob.decode()
        if sha(files[source][row['start']:row['end']])!=row['raw_sha256']:raise ValueError('Source span changed')
        assets[key]=safe_artifact(artifact_folder,review)
        if review['replace_explanation']:
            after,new_explanation=patch_document(Path(row['source_path']).name,files[source],review)
            changed_documents.append({'source_path':row['source_path'],'expected_current_sha256':source,'revised_sha256':sha(after),'changed_questions':1})
            corrected_row=key;row['explanation']=new_explanation
        row['metadata']={**row['metadata'],'math_figure_review':{**review,'artifact_scope':'internal_review_only','approval':'unchanged','figure_hold':'retained','recipe_sha256':sha(recipe_path.read_bytes())}}
    identity=sha(json.dumps({'base':base.name,'recipe':sha(recipe_path.read_bytes()),'processor':sha(Path(__file__).read_bytes())},sort_keys=True));target=Path(output)/identity;shutil.copytree(base,target)
    review_dir=target/'math-figure-review-assets';review_dir.mkdir()
    for key,values in assets.items():
        for ext,blob in values.items():(review_dir/(reviews[key]['id']+'.'+ext)).write_bytes(blob)
    (review_dir/'manifest.json').write_bytes((Path(artifact_folder)/'manifest.json').read_bytes())
    revised=target/'math-figure-revised-documents';revised.mkdir();entry=changed_documents[0]
    (revised/Path(entry['source_path']).name).write_text(after);(target/'objects'/(entry['revised_sha256']+'.md')).write_text(after)
    with sqlite3.connect(target/'catalog.sqlite3') as db:
        for row in rows.values():db.execute('update records set data_json=? where id=?',(json.dumps(row,ensure_ascii=False),row['id']))
        db.commit()
        if db.execute('pragma integrity_check').fetchone()[0]!='ok':raise ValueError('Catalog integrity failure')
        changed=0
        with sqlite3.connect((base/'catalog.sqlite3').as_uri()+'?mode=ro',uri=True) as old:
            for a,b in zip(old.execute('select data_json from records order by id'),db.execute('select data_json from records order by id'),strict=True):
                a,b=json.loads(a[0]),json.loads(b[0])
                if a==b:continue
                changed+=1;allowed={'metadata','explanation'} if a['id']==corrected_row else {'metadata'}
                if a['id'] not in rows or not {k for k in a.keys()|b.keys() if a.get(k)!=b.get(k)}<=allowed or {k:v for k,v in b['metadata'].items() if k!='math_figure_review'}!=a['metadata']:raise ValueError('Unrelated field changed')
        if changed!=8:raise ValueError('Changed population mismatch')
    report={**summary,'snapshot_id':identity,'base_snapshot_id':base.name,'catalog_sha256':sha((target/'catalog.sqlite3').read_bytes()),'created_at':datetime.now(timezone.utc).isoformat(),'committed_batches':summary['committed_batches']+1,'math_diagram_answers_checked':8,'math_diagram_invalid_solution_replaced':1,'math_diagram_assets_student_published':0}
    (target/'summary.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n');(target/'math-figure-reviews.json').write_bytes(recipe_path.read_bytes());(target/'math-figure-revised-documents.json').write_text(json.dumps(changed_documents,indent=2)+'\n')
    return {'snapshot_id':identity,'changed_records':8,'changed_documents':changed_documents,'source_solutions_corrected':1,'question_answer_approval_changes':0,'student_assets_published':0}
