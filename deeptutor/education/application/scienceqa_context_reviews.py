"""Correct source-bound ScienceQA passages or a question attribution line.

Original source IDs, spans, answers, rights, figure gates and approvals remain.
The processor creates an immutable candidate; indexing/activation are separate.
"""
from collections import defaultdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import shutil
import sqlite3

from .content_stock import parse_file


def sha(value):
    return hashlib.sha256(value.encode() if isinstance(value, str) else value).hexdigest()



def reviewed_fields(review):
    mode = review.get('mode', 'context_and_explanation')
    if mode == 'context_and_explanation':
        return ('prompt', 'explanation')
    if mode == 'question_attribution':
        # This mode can change only one complete attribution line, never the
        # question conditions, answer choices, or explanatory reasoning.
        for key in ('fragment_before', 'fragment_after'):
            if not re.fullmatch(r'—[^\r\n]+', review.get(key, '')):
                raise ValueError('Invalid question attribution line')
        return ('prompt',)
    raise ValueError('Unsupported passage review mode')


def patch_document(filename, text, reviews):
    old = parse_file('scienceqa', filename, text)
    selected = {r['source_title']: r for r in reviews}
    if len(selected) != len(reviews):
        raise ValueError('Ambiguous context review titles')
    edits = []
    for row in old:
        r = selected.get(row['title'])
        if r is None:
            continue
        if any(row[field] != r[field + '_before'] for field in ('prompt', 'explanation', 'answer')):
            raise ValueError('Context or explanation source changed')
        fields = reviewed_fields(r)
        before, after = r['fragment_before'], r['fragment_after']
        if not before.strip() or not after.strip() or before == after or re.search(r'^#{1,3} |^---\s*$', after, re.M):
            raise ValueError('Invalid context replacement')
        block = text[row['start']:row['end']]
        patterns = [r'(\*\*Context:\*\*\s*)(.*?)(?=^### |\Z)',
                    r'(^### Explanation\n)(.*?)(?=^### |^## |^---\s*$|\Z)']
        if fields == ('prompt',):
            patterns = [r'(^### Question\n)(.*?)(?=^\*\*Options:\*\*|^### |^## |^---\s*$|\Z)']
        for pattern in patterns:
            matches = list(re.finditer(pattern, block, re.M | re.S))
            if len(matches) != 1 or matches[0][2].count(before) != 1:
                raise ValueError('Context/explanation fragment boundary mismatch')
            m = matches[0]
            if fields == ('prompt',) and before not in m[2].splitlines():
                raise ValueError('Attribution must occupy a complete question line')
            block = block[:m.start(2)] + m[2].replace(before, after, 1) + block[m.end(2):]
        edits.append((row['start'], row['end'], block))
    if len(edits) != len(reviews):
        raise ValueError('Context review records missing')
    revised = text
    for start, end, block in reversed(edits):
        revised = revised[:start] + block + revised[end:]
    for a, b in zip(old, parse_file('scienceqa', filename, revised), strict=True):
        r = selected.get(a['title'])
        for field in a.keys() | b.keys():
            if field in ('start', 'end'):
                continue
            expected = r[field + '_after'] if r and field in ('prompt', 'explanation') else a.get(field)
            if b.get(field) != expected:
                raise ValueError('Context revision changed unrelated data: ' + field)
    return revised


def prior_reviews_by_path(rows):
    grouped = defaultdict(list)
    for row in rows:
        r = row['metadata'].get('individual_context_review')
        if r is None:
            continue
        if ('individual_explanation_review' in row['metadata'] or
            r['record_id'] != row['id'] or r['source_title'] != row['title'] or
            any(r[k] != row[k] for k in ('source_path', 'source_sha256', 'raw_sha256')) or
            any(r[k + '_after'] != row[k] for k in ('prompt', 'explanation')) or
            r['answer_before'] != row['answer']):
            raise ValueError('Previous context provenance changed or has unsupported overlapping review')
        grouped[row['source_path']].append(r)
    return grouped


def build(base, recipe_path, output):
    # Local import keeps patch_document available to the rolling lecture builder.
    from .scienceqa_lecture_reviews import patch_document as lectures
    from .scienceqa_explanation_reviews import patch_document as explanations
    base, recipe_path = Path(base).resolve(), Path(recipe_path)
    summary = json.loads((base/'summary.json').read_text())
    if summary['snapshot_id'] != base.name or summary['catalog_sha256'] != sha((base/'catalog.sqlite3').read_bytes()):
        raise ValueError('Base catalog changed')
    recipe = json.loads(recipe_path.read_text())
    reviews = {r['record_id']: r for r in recipe['records']}
    if recipe['library'] != 'scienceqa' or not reviews or len(reviews) != len(recipe['records']) or len(reviews) != recipe['expected_changed_records']:
        raise ValueError('Context review population mismatch')
    with sqlite3.connect((base/'catalog.sqlite3').as_uri()+'?mode=ro', uri=True) as db:
        rows = [json.loads(x[0]) for x in db.execute("select data_json from records where library='scienceqa'")]
    if len(rows) != recipe['expected_total_records']:
        raise ValueError('ScienceQA inventory changed')
    prior_context = prior_reviews_by_path(rows)
    by_id = {row['id']: row for row in rows}
    chosen = {}
    for key, r in reviews.items():
        row = by_id.get(key)
        if not row or not r.get('references') or any(row[k] != r[k] for k in ('source_path','source_sha256','raw_sha256')) or r['source_title'] != row['title']:
            raise ValueError('Source binding changed')
        if any(k in row['metadata'] for k in ('individual_context_review','individual_explanation_review')):
            raise ValueError('Existing individual review requires an explicit revision')
        if any(row[k] != r[k+'_before'] for k in ('prompt','explanation','answer')):
            raise ValueError('Source passage changed')
        blob = (base/'objects'/(row['source_sha256']+'.md')).read_bytes()
        if sha(blob) != row['source_sha256'] or sha(blob.decode()[row['start']:row['end']]) != row['raw_sha256']:
            raise ValueError('Immutable source bytes changed')
        fields = reviewed_fields(r)
        if any(r[k+'_after'] != (r[k+'_before'].replace(r['fragment_before'],r['fragment_after'],1) if k in fields else r[k+'_before']) for k in ('prompt','explanation')):
            raise ValueError('Replacement exceeds reviewed fragment')
        chosen[key] = row
    documents, manifest = {}, []
    for source_path in sorted({r['source_path'] for r in reviews.values()}):
        source_rows = [r for r in rows if r['source_path'] == source_path]
        source_sha = source_rows[0]['source_sha256']
        if any(r['source_sha256'] != source_sha for r in source_rows):
            raise ValueError('Inconsistent source identity')
        text = (base/'objects'/(source_sha+'.md')).read_text()
        prior_lectures = {r['metadata']['lecture_review']['concept_id']: r['metadata']['lecture_review'] for r in source_rows if 'lecture_review' in r['metadata']}
        current, _ = lectures(text, prior_lectures)
        prior_explanations = [r['metadata']['individual_explanation_review'] for r in source_rows if 'individual_explanation_review' in r['metadata']]
        if prior_explanations:
            current = explanations(Path(source_path).name, current, prior_explanations)
        if source_path in prior_context:
            current = patch_document(Path(source_path).name,current,prior_context[source_path])
        selected = [r for r in reviews.values() if r['source_path'] == source_path]
        revised = patch_document(Path(source_path).name,current,selected)
        documents[Path(source_path).name] = revised
        manifest.append({'source_path':source_path,'source_sha256':source_sha,'expected_current_sha256':sha(current),'revised_sha256':sha(revised),'changed_contexts':len(selected)})
    identity = sha(json.dumps({'base':base.name,'recipe':sha(recipe_path.read_bytes()),'processor':sha(Path(__file__).read_bytes())},sort_keys=True))
    target = Path(output)/identity
    target.mkdir(parents=True,exist_ok=False)
    for p in base.iterdir():
        if p.name in ('revised-documents','revised-documents.json'):
            continue
        if p.is_symlink():
            raise ValueError('Unexpected snapshot symlink')
        if p.is_dir():shutil.copytree(p,target/p.name)
        else:shutil.copy2(p,target/p.name)
    (target/'revised-documents').mkdir()
    for name,text in documents.items():
        (target/'revised-documents'/name).write_text(text)
        (target/'objects'/(sha(text)+'.md')).write_text(text)
    with sqlite3.connect(target/'catalog.sqlite3') as db:
        for key,row in chosen.items():
            r=reviews[key]
            row['prompt'],row['explanation']=r['prompt_after'],r['explanation_after']
            row['metadata']={**row['metadata'],'individual_context_review':{**r,'recipe_sha256':sha(recipe_path.read_bytes()),'source_identity_note':'Original ID, fingerprint and spans identify the immutable source, not the revised prompt.','approval':'unchanged'}}
            db.execute('update records set data_json=? where id=?',(json.dumps(row,ensure_ascii=False),key))
        db.commit()
        if db.execute('pragma integrity_check').fetchone()[0]!='ok':raise ValueError('Catalog integrity failure')
        with sqlite3.connect((base/'catalog.sqlite3').as_uri()+'?mode=ro',uri=True) as old:
            changed=0
            for a,b in zip(old.execute('select data_json from records order by id'),db.execute('select data_json from records order by id'),strict=True):
                a,b=json.loads(a[0]),json.loads(b[0])
                if a==b:continue
                changed+=1
                if a['id'] not in chosen or {k for k in a.keys()|b.keys() if a.get(k)!=b.get(k)}!=(set(reviewed_fields(reviews[a['id']])) | {'metadata'}) or {k:v for k,v in b['metadata'].items() if k!='individual_context_review'}!=a['metadata']:
                    raise ValueError('Unrelated data changed')
            if changed!=len(reviews):raise ValueError('Context correction count mismatch')
    report={**summary,'snapshot_id':identity,'base_snapshot_id':base.name,'created_at':datetime.now(timezone.utc).isoformat(),'catalog_sha256':sha((target/'catalog.sqlite3').read_bytes()),'committed_batches':summary['committed_batches']+1,'scienceqa_context_passages_corrected':sum(map(len,prior_context.values()))+len(reviews)}
    (target/'summary.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    (target/'revised-documents.json').write_text(json.dumps(manifest,indent=2)+'\n')
    (target/recipe_path.name).write_bytes(recipe_path.read_bytes())
    return {'snapshot_id':identity,'changed_contexts':len(reviews),'changed_explanations':sum('explanation' in reviewed_fields(r) for r in reviews.values()),'changed_attributions':sum(r.get('mode')=='question_attribution' for r in reviews.values()),'changed_documents':manifest,'answer_approval_changes':0,'formal_items_created':0}
