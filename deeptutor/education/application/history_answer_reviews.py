"""Apply narrowly reviewed historical-answer corrections to immutable stock.

Original source identities and all curriculum/rights/approval gates are retained.
The output is a candidate snapshot, not an activated index or approved question.
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

LIBRARY = 'world-history-1500'
REVIEW_KEY = 'historical_answer_review'


def sha(value):
    return hashlib.sha256(value.encode() if isinstance(value, str) else value).hexdigest()


def patch_document(filename, text, reviews):
    old = parse_file(LIBRARY, filename, text)
    selected = {r['source_title']: r for r in reviews}
    if len(selected) != len(reviews):
        raise ValueError('Ambiguous answer review titles')
    edits = []
    for row in old:
        r = selected.get(row['title'])
        if r is None:
            continue
        if row['prompt'] != r['prompt_before'] or row['answer'] != r['answer_before']:
            raise ValueError('Answer source changed')
        before, after = r['fragment_before'], r['fragment_after']
        if (not before.strip() or not after.strip() or before == after or
            re.search(r'^#{1,3} |^---\s*$', after, re.M) or
            row['answer'].count(before) != 1 or
            r['answer_after'] != row['answer'].replace(before, after, 1)):
            raise ValueError('Replacement exceeds reviewed fragment')
        block = text[row['start']:row['end']]
        matches = list(re.finditer(r'(^### Answer\n)(.*?)(?=^### |^## |^---\s*$|\Z)', block, re.M | re.S))
        if len(matches) != 1 or matches[0][2].count(before) != 1:
            raise ValueError('Answer fragment boundary mismatch')
        m = matches[0]
        block = block[:m.start(2)] + m[2].replace(before, after, 1) + block[m.end(2):]
        edits.append((row['start'], row['end'], block))
    if len(edits) != len(reviews):
        raise ValueError('Answer review records missing or duplicated')
    revised = text
    for start, end, block in reversed(edits):
        revised = revised[:start] + block + revised[end:]
    for a, b in zip(old, parse_file(LIBRARY, filename, revised), strict=True):
        r = selected.get(a['title'])
        for field in a.keys() | b.keys():
            if field in ('start', 'end'):
                continue
            expected = r['answer_after'] if r and field == 'answer' else a.get(field)
            if b.get(field) != expected:
                raise ValueError('Answer revision changed unrelated data: ' + field)
    return revised


def build(base, recipe_path, output):
    base, recipe_path = Path(base).resolve(), Path(recipe_path)
    summary = json.loads((base/'summary.json').read_text())
    if summary['snapshot_id'] != base.name or summary['catalog_sha256'] != sha((base/'catalog.sqlite3').read_bytes()):
        raise ValueError('Base catalog changed')
    recipe = json.loads(recipe_path.read_text())
    reviews = {r['record_id']: r for r in recipe['records']}
    if (recipe['library'] != LIBRARY or not reviews or len(reviews) != len(recipe['records']) or
        len(reviews) != recipe['expected_changed_records']):
        raise ValueError('Answer review population mismatch')
    with sqlite3.connect((base/'catalog.sqlite3').as_uri()+'?mode=ro', uri=True) as db:
        rows = [json.loads(x[0]) for x in db.execute('select data_json from records where library=?', (LIBRARY,))]
    if len(rows) != recipe['expected_total_records']:
        raise ValueError('History inventory changed')
    prior = defaultdict(list)
    for row in rows:
        r = row['metadata'].get(REVIEW_KEY)
        if r is not None:
            if (r['record_id'] != row['id'] or r['source_title'] != row['title'] or
                any(r[k] != row[k] for k in ('source_path','source_sha256','raw_sha256')) or
                r['answer_after'] != row['answer'] or r['prompt_before'] != row['prompt']):
                raise ValueError('Previous answer provenance changed')
            prior[row['source_path']].append(r)
    by_id = {row['id']: row for row in rows}
    chosen = {}
    for key, r in reviews.items():
        row = by_id.get(key)
        if (not row or not r.get('references') or
            any(row[k] != r[k] for k in ('source_path','source_sha256','raw_sha256')) or
            r['source_title'] != row['title']):
            raise ValueError('Source binding changed')
        if REVIEW_KEY in row['metadata']:
            raise ValueError('Existing answer review requires an explicit revision')
        if row['prompt'] != r['prompt_before'] or row['answer'] != r['answer_before']:
            raise ValueError('Source passage changed')
        blob = (base/'objects'/(row['source_sha256']+'.md')).read_bytes()
        if sha(blob) != row['source_sha256'] or sha(blob.decode()[row['start']:row['end']]) != row['raw_sha256']:
            raise ValueError('Immutable source bytes changed')
        chosen[key] = row
    documents, manifest = {}, []
    for path in sorted({r['source_path'] for r in reviews.values()}):
        source_rows = [r for r in rows if r['source_path'] == path]
        source_sha = source_rows[0]['source_sha256']
        if any(r['source_sha256'] != source_sha for r in source_rows):
            raise ValueError('Inconsistent source identity')
        original = (base/'objects'/(source_sha+'.md')).read_text()
        current = patch_document(Path(path).name, original, prior[path]) if prior[path] else original
        revised = patch_document(Path(path).name, current, [r for r in reviews.values() if r['source_path'] == path])
        documents[Path(path).name] = revised
        manifest.append({'source_path':path,'source_sha256':source_sha,'expected_current_sha256':sha(current),'revised_sha256':sha(revised)})
    identity = sha(json.dumps({'base':base.name,'recipe':sha(recipe_path.read_bytes()),'processor':sha(Path(__file__).read_bytes())}, sort_keys=True))
    target = Path(output)/identity
    target.mkdir(parents=True, exist_ok=False)
    for p in base.iterdir():
        if p.name in ('revised-documents','revised-documents.json'):
            continue
        if p.is_symlink():
            raise ValueError('Unexpected snapshot symlink')
        if p.is_dir():
            shutil.copytree(p,target/p.name)
        else:
            shutil.copy2(p,target/p.name)
    (target/'revised-documents').mkdir()
    for name, text in documents.items():
        (target/'revised-documents'/name).write_text(text)
        (target/'objects'/(sha(text)+'.md')).write_text(text)
    with sqlite3.connect(target/'catalog.sqlite3') as db:
        for key, row in chosen.items():
            r = reviews[key]
            row['answer'] = r['answer_after']
            row['metadata'] = {**row['metadata'], REVIEW_KEY:{**r,'recipe_sha256':sha(recipe_path.read_bytes()),'scope':'Reviewed fragment only; all other historical claims and whole-question approval remain pending.','approval':'unchanged'}}
            db.execute('update records set data_json=? where id=?',(json.dumps(row,ensure_ascii=False),key))
        db.commit()
        if db.execute('pragma integrity_check').fetchone()[0] != 'ok':
            raise ValueError('Catalog integrity failure')
        with sqlite3.connect((base/'catalog.sqlite3').as_uri()+'?mode=ro', uri=True) as old:
            changed = 0
            for a,b in zip(old.execute('select data_json from records order by id'),db.execute('select data_json from records order by id'),strict=True):
                a,b = json.loads(a[0]),json.loads(b[0])
                if a == b:
                    continue
                changed += 1
                if (a['id'] not in chosen or {k for k in a.keys()|b.keys() if a.get(k)!=b.get(k)} != {'answer','metadata'} or
                    {k:v for k,v in b['metadata'].items() if k!=REVIEW_KEY} != a['metadata']):
                    raise ValueError('Unrelated data changed')
            if changed != len(reviews):
                raise ValueError('Answer correction count mismatch')
    report = {**summary,'snapshot_id':identity,'base_snapshot_id':base.name,'created_at':datetime.now(timezone.utc).isoformat(),'catalog_sha256':sha((target/'catalog.sqlite3').read_bytes()),'committed_batches':summary['committed_batches']+1,'historical_answer_passages_corrected':sum(map(len,prior.values()))+len(reviews)}
    (target/'summary.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    (target/'revised-documents.json').write_text(json.dumps(manifest,indent=2)+'\n')
    (target/recipe_path.name).write_bytes(recipe_path.read_bytes())
    return {'snapshot_id':identity,'changed_answers':len(reviews),'changed_documents':manifest,'approval_changes':0,'formal_items_created':0}
