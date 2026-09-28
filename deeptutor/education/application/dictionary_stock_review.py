"""Independently verify a closed, source-bound family of dictionary questions."""
from __future__ import annotations
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import shutil
import sqlite3

CONCEPTS = {'68864b133adc678f7b5c350bf3ab608165221eaae1ab2db2cdccc6a71e86bf1c', '6db1fc2affa619d5e0e5d493f6a975c7fd5dd7288c61fece3b5f794ce6278c9f'}


def sha(value):
    return hashlib.sha256(value.encode() if isinstance(value, str) else value).hexdigest()


def verify(row):
    """Reject unsupported grammars instead of guessing an answer."""
    if row['library'] != 'scienceqa' or row['issues']:
        raise ValueError('Question has unresolved structural issues')
    key = sha(re.sub(r'\s+', ' ', row['lecture']).strip())
    if key not in CONCEPTS:
        raise ValueError('Question is outside the reviewed concept family')
    match = re.fullmatch(r'(?:Which word would you find|Would you find the word ([a-z]+)) on a dictionary page with the following guide words\?\n([a-z]+) - ([a-z]+)', row['prompt'])
    if not match:
        raise ValueError('Unsupported prompt grammar')
    word, lower, upper = match.groups()
    if lower > upper:
        raise ValueError('Guide words are reversed')
    if word:
        if len(row['options']) != 2 or set(row['options']) != {'yes', 'no'}:
            raise ValueError('Invalid yes/no options')
        answer = 'yes' if lower <= word <= upper else 'no'
        witness = {'kind':'membership','word':word,'lower':lower,'upper':upper,'in_range':lower <= word <= upper}
    else:
        if len(row['options']) < 2 or len(set(row['options'])) != len(row['options']) or not all(re.fullmatch('[a-z]+', option) for option in row['options']):
            raise ValueError('Unsupported or duplicate options')
        selected = [option for option in row['options'] if lower <= option <= upper]
        if len(selected) != 1:
            raise ValueError('Answer is not unique')
        answer = selected[0]
        witness = {'kind':'unique_option','lower':lower,'upper':upper,'in_range':{option:lower <= option <= upper for option in row['options']}}
    if answer != row['answer']:
        raise ValueError('Source answer contradicts independent comparison')
    return {'algorithm':'ASCII lowercase lexicographic order, inclusive bounds, unique choice or yes/no membership','answer':answer,'witness':witness,'scope':'Answer verification only; original approval, curriculum, rights and grading gates remain.'}


def annotate(base: Path, output: Path, expected: int = 697) -> dict:
    previous = json.loads((base/'summary.json').read_text())
    if previous['snapshot_id'] != base.name or sha((base/'catalog.sqlite3').read_bytes()) != previous['catalog_sha256']:
        raise ValueError('Base snapshot changed')
    checks = {}; objects = {}
    with sqlite3.connect((base/'catalog.sqlite3').as_uri()+'?mode=ro',uri=True) as db:
        for (payload,) in db.execute("select data_json from records where library='scienceqa'"):
            row = json.loads(payload)
            if sha(re.sub(r'\s+', ' ', row['lecture']).strip()) not in CONCEPTS:
                continue
            source_sha = row['source_sha256']
            if source_sha not in objects:
                blob = (base/'objects'/(source_sha+'.md')).read_bytes()
                if sha(blob) != source_sha: raise ValueError('Source hash changed')
                objects[source_sha] = blob.decode('utf-8')
            if sha(objects[source_sha][row['start']:row['end']]) != row['raw_sha256']:
                raise ValueError('Question source span changed')
            check = verify(row)
            checks[row['id']] = {**check,'source_sha256':source_sha,'raw_sha256':row['raw_sha256'],'source_path':row['source_path'],'source_line':row['source_line']}
    if len(checks) != expected:
        raise ValueError('Reviewed family count changed')
    identity = sha(json.dumps({'base':base.name,'checks':checks,'processor':sha(Path(__file__).read_bytes())},sort_keys=True))
    target = output / identity
    shutil.copytree(base,target)
    with sqlite3.connect((base/'catalog.sqlite3').as_uri()+'?mode=ro',uri=True) as old, sqlite3.connect(target/'catalog.sqlite3') as new:
        for record_id,check in checks.items():
            row = json.loads(new.execute('select data_json from records where id=?',(record_id,)).fetchone()[0])
            row['metadata'] = {**row['metadata'],'independent_answer_check':check}
            new.execute('update records set data_json=? where id=?',(json.dumps(row,ensure_ascii=False),record_id))
        new.commit()
        if new.execute('pragma integrity_check').fetchone()[0] != 'ok': raise ValueError('Integrity failure')
        actual = 0
        for a,b in zip(old.execute('select data_json from records order by id'),new.execute('select data_json from records order by id'),strict=True):
            a,b=json.loads(a[0]),json.loads(b[0])
            if a==b:continue
            if a['id'] not in checks or {k for k in a.keys()|b.keys() if a.get(k)!=b.get(k)} != {'metadata'}:
                raise ValueError('Unexpected record mutation')
            actual+=1
        if actual!=expected:raise ValueError('Annotation count mismatch')
    summary={**previous,'snapshot_id':identity,'base_snapshot_id':base.name,'created_at':datetime.now(timezone.utc).isoformat(),'catalog_sha256':sha((target/'catalog.sqlite3').read_bytes()),'committed_batches':previous['committed_batches']+1,'dictionary_answers_independently_checked':expected,'dictionary_review_processor_sha256':sha(Path(__file__).read_bytes())}
    (target/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n')
    report={'source_snapshot':base.name,'snapshot_id':identity,'verified':len(checks),'answer_or_approval_changes':0,'records':checks}
    (target/'dictionary-answer-checks.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    return {k:v for k,v in report.items() if k!='records'}
