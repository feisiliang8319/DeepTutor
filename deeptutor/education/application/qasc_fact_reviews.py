"""Offline fact-chain review with source preservation and no answer approval.

Case-sensitive exact fact identities avoid conflating scientific symbols.
The entire affected inference is withdrawn: correcting one premise alone does
not make a question or its original answer valid. Activation is separate.
"""
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import shutil
import sqlite3
from .content_stock import parse_file

NOTICE = 'FACT CHECK REQUIRED: The original dataset answer remains unverified. The original reasoning chain has been withdrawn because at least one premise is false or overbroad. These notes correct background knowledge only; they do not establish a valid answer or a usable assessment item.'


def sha(value):
    return hashlib.sha256(value.encode() if isinstance(value, str) else value).hexdigest()


def facts(explanation):
    matches = re.findall(r'^\*\*Fact ([12]):\*\*\s*([^\n]+)', explanation, re.M)
    if len(matches) != 2 or {x[0] for x in matches} != {'1', '2'}:
        raise ValueError('Expected exactly two source facts')
    return [text.strip() for _, text in matches]


def reviewed_explanation(reviews):
    parts = [NOTICE]
    for item in reviews:
        parts += [item['correction'], 'Review note: ' + item['reason'], 'Fact-check references: ' + ' ; '.join(item['references'])]
    return '\n\n'.join(parts)


def patch_document(filename, text, reviews):
    old = parse_file('qasc', filename, text)
    changes = []
    for row in old:
        selected = [reviews[sha(f)] for f in facts(row['explanation']) if sha(f) in reviews]
        if not selected:
            continue
        block = text[row['start']:row['end']]
        pattern = re.compile(r'(^### Reasoning \(fact chain\)\n)(.*?)(?=^---\s*$|\Z)', re.M | re.S)
        matched = pattern.search(block)
        if not matched or matched[2].strip() != row['explanation']:
            raise ValueError('Reasoning block does not match source record')
        body = matched[2]
        leading, trailing = body[:len(body)-len(body.lstrip())], body[len(body.rstrip()):]
        replacement = pattern.sub(lambda m: m[1] + leading + reviewed_explanation(selected) + trailing, block, count=1)
        changes.append((row['start'], row['end'], replacement, selected))
    after = text
    for start, end, replacement, _ in reversed(changes):
        after = after[:start] + replacement + after[end:]
    parsed = parse_file('qasc', filename, after)
    changed = 0
    for a, b in zip(old, parsed, strict=True):
        selected = [reviews[sha(f)] for f in facts(a['explanation']) if sha(f) in reviews]
        if b['explanation'] != (reviewed_explanation(selected) if selected else a['explanation']):
            raise ValueError('Reparsed explanation mismatch')
        for field in a.keys() | b.keys():
            if field not in {'explanation', 'start', 'end'} and a.get(field) != b.get(field):
                raise ValueError('Question or source fields changed: ' + field)
        changed += bool(selected)
    if changed != len(changes):
        raise ValueError('Document population mismatch')
    return after, changed


def build(base, recipe_path, output):
    base = Path(base).resolve(); recipe_path = Path(recipe_path)
    previous = json.loads((base/'summary.json').read_text())
    if previous['snapshot_id'] != base.name or sha((base/'catalog.sqlite3').read_bytes()) != previous['catalog_sha256']:
        raise ValueError('Base snapshot changed')
    recipe = json.loads(recipe_path.read_text()); reviews = {x['fact_id']: x for x in recipe['reviews']}
    if recipe['library'] != 'qasc' or len(reviews) != len(recipe['reviews']):
        raise ValueError('Invalid review recipe')
    for identity, item in reviews.items():
        if identity != sha(item['fact_before']) or not item['references'] or not item['correction'].strip() or re.search(r'^#{1,3} ', reviewed_explanation([item]), re.M):
            raise ValueError('Missing or unsafe review evidence')
    with sqlite3.connect((base/'catalog.sqlite3').as_uri()+'?mode=ro', uri=True) as db:
        rows = [json.loads(x[0]) for x in db.execute("select data_json from records where library='qasc' order by rowid")]
    if len(rows) != recipe['expected_records'] or any('fact_chain_review' in r['metadata'] for r in rows):
        raise ValueError('Unexpected population or review already applied')
    selected = {}; counts = Counter(); groups = {}
    for row in rows:
        local = []
        for fact in set(facts(row['explanation'])):
            identity = sha(fact)
            groups.setdefault(identity, {'id': identity, 'original_fact': fact, 'records': [], 'state': 'pending_semantic_review'})['records'].append(row['id'])
            if identity in reviews:
                local.append(reviews[identity]); counts[identity] += 1
        if local:
            selected[row['id']] = sorted(local, key=lambda r:r['fact_id'])
    if dict(counts) != {k:v['expected_records'] for k,v in reviews.items()} or len(selected) != recipe['expected_changed_records']:
        raise ValueError('Review population changed')
    identity = sha(json.dumps({'base':base.name,'recipe':sha(recipe_path.read_bytes()),'processor':sha(Path(__file__).read_bytes())},sort_keys=True))
    target = Path(output)/identity; shutil.copytree(base,target)
    corrected = target/'qasc-revised-documents'; corrected.mkdir(exist_ok=False); manifest=[]
    paths = {r['source_path']:r['source_sha256'] for r in rows}
    for path, source_sha in paths.items():
        blob=(base/'objects'/(source_sha+'.md')).read_bytes()
        if sha(blob) != source_sha:
            raise ValueError('Source object changed')
        before=blob.decode(); after, changed=patch_document(Path(path).name,before,reviews)
        if not changed:
            continue
        revised_sha=sha(after);(corrected/Path(path).name).write_text(after);(target/'objects'/(revised_sha+'.md')).write_text(after)
        manifest.append({'source_path':path,'expected_current_sha256':source_sha,'revised_sha256':revised_sha,'changed_questions':changed})
    if sum(x['changed_questions'] for x in manifest) != len(selected):
        raise ValueError('Source and catalog counts differ')
    with sqlite3.connect(target/'catalog.sqlite3') as db:
        for row in rows:
            if row['id'] not in selected:
                continue
            original=(base/'objects'/(row['source_sha256']+'.md')).read_text()
            if sha(original[row['start']:row['end']]) != row['raw_sha256']:
                raise ValueError('Source span changed')
            # Preserve fact order, matching the natural document patch.
            items=[reviews[sha(f)] for f in facts(row['explanation']) if sha(f) in reviews]
            row['metadata']={**row['metadata'],'fact_chain_review':{'reviews':items,'explanation_before':row['explanation'],'answer_approval':'unchanged','source_sha256':row['source_sha256'],'raw_sha256':row['raw_sha256'],'recipe_sha256':sha(recipe_path.read_bytes())}}
            row['explanation']=reviewed_explanation(items)
            if row['state'] != 'duplicate': row['state']='needs_fact_check'
            db.execute('update records set state=?,data_json=? where id=?',(row['state'],json.dumps(row,ensure_ascii=False),row['id']))
        db.commit()
        if db.execute('pragma integrity_check').fetchone()[0] != 'ok':raise ValueError('Catalog integrity failure')
        with sqlite3.connect((base/'catalog.sqlite3').as_uri()+'?mode=ro',uri=True) as old:
            changed=0
            for a,b in zip(old.execute('select data_json from records order by id'),db.execute('select data_json from records order by id'),strict=True):
                a,b=json.loads(a[0]),json.loads(b[0])
                if a==b:continue
                changed+=1
                if a['id'] not in selected or not {k for k in a.keys()|b.keys() if a.get(k)!=b.get(k)} <= {'explanation','metadata','state'}:
                    raise ValueError('Unrelated data changed')
            if changed!=len(selected):raise ValueError('Catalog correction count mismatch')
        states=dict(db.execute("select state,count(*) from records where library='qasc' group by state"))
    for key,review in reviews.items():groups[key].update(state='background_corrected_inference_withdrawn',review=review)
    report={**previous,'snapshot_id':identity,'base_snapshot_id':base.name,'created_at':datetime.now(timezone.utc).isoformat(),'catalog_sha256':sha((target/'catalog.sqlite3').read_bytes()),'committed_batches':previous['committed_batches']+1,'qasc_fact_groups':len(groups),'qasc_reviewed_fact_groups':len(reviews),'qasc_inferences_withdrawn':len(selected),'qasc_formal_items_created':0}
    for library in report['libraries']:
        if library['library']=='qasc':library['states']=states
    (target/'summary.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    (target/'qasc-fact-queue.json').write_text(json.dumps(list(groups.values()),ensure_ascii=False,indent=2)+'\n')
    (target/'qasc-revised-documents.json').write_text(json.dumps(manifest,indent=2)+'\n')
    (target/'qasc-fact-reviews.json').write_bytes(recipe_path.read_bytes())
    return {'snapshot_id':identity,'changed_records':len(selected),'fact_groups':len(groups),'reviewed_fact_groups':len(reviews),'question_answer_approval_changes':0,'changed_documents':manifest,'states':states}
