"""Record scoped, source-bound lecture reviews that require no text changes.

This ledger never approves a question, restores a missing image, or changes RAG.
"""
from __future__ import annotations
from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import sqlite3
from .content_stock import parse_file
from .scienceqa_lecture_reviews import concept_id, sha

STATE = 'shared_lecture_checked_unchanged'
SCOPE = 'shared_lecture_only_not_question_or_answer_approval'


def build(base: Path, recipe_path: Path, output: Path) -> dict:
    base, recipe_path, output = Path(base).resolve(), Path(recipe_path), Path(output)
    summary = json.loads((base / 'summary.json').read_text())
    if summary['snapshot_id'] != base.name or summary['catalog_sha256'] != sha((base / 'catalog.sqlite3').read_bytes()):
        raise ValueError('Base identity or checksum changed')
    recipe = json.loads(recipe_path.read_text())
    reviews = {r['concept_id']: r for r in recipe['reviews']}
    if not reviews or len(reviews) != len(recipe['reviews']) or recipe['library'] != 'scienceqa':
        raise ValueError('Invalid assessment identities')
    for key, review in reviews.items():
        if not review['lecture'].strip() or concept_id(review['lecture']) != key or review.get('scope') != SCOPE or review.get('decision') != 'checked_unchanged':
            raise ValueError('Invalid assessment scope or source')
        if not review.get('references') or any(not r.get('url', '').startswith('https://') or not r.get('supports') for r in review['references']) or not review.get('reason') or not review.get('limitations'):
            raise ValueError('Assessment evidence and limitations required')
    with sqlite3.connect((base / 'catalog.sqlite3').as_uri() + '?mode=ro', uri=True) as db:
        rows = [json.loads(x[0]) for x in db.execute("select data_json from records where library='scienceqa'")]
    if len(rows) != recipe['expected_total_records']:
        raise ValueError('ScienceQA population changed')
    updates, originals, objects = {}, {}, {}
    counts = Counter()
    prior_counts = Counter()
    for row in rows:
        prior = row['metadata'].get('lecture_assessment')
        if prior:
            prior_counts[prior['concept_id']] += 1
        key = concept_id(row['lecture'])
        if key not in reviews:
            continue
        if prior or row['metadata'].get('lecture_review'):
            raise ValueError('Lecture already reviewed')
        review = reviews[key]
        if row['lecture'] != review['lecture']:
            raise ValueError('Lecture exact text changed')
        source = row['source_sha256']
        if source not in objects:
            blob = (base / 'objects' / (source + '.md')).read_bytes()
            if sha(blob) != source:
                raise ValueError('Original source hash changed')
            objects[source] = blob.decode()
            originals[source] = {entry['start']: entry for entry in parse_file('scienceqa', Path(row['source_path']).name, objects[source])}
        span = objects[source][row['start']:row['end']]
        source_row = originals[source].get(row['start'])
        if sha(span) != row['raw_sha256'] or source_row is None or source_row['lecture'] != row['lecture']:
            raise ValueError('Original lecture span changed')
        row['metadata'] = {**row['metadata'], 'lecture_assessment': {
            **review, 'source_sha256': source, 'source_raw_sha256': row['raw_sha256'],
            'recipe_sha256': sha(recipe_path.read_bytes()), 'approval': 'unchanged',
        }}
        updates[row['id']] = row
        counts[key] += 1
    if counts != Counter({k: r['expected_records'] for k, r in reviews.items()}) or sum(counts.values()) != recipe['expected_linked_records']:
        raise ValueError('Assessment population changed')
    queue = json.loads((base / 'scienceqa-concept-queue.json').read_text())
    for item in queue:
        if item['id'] not in reviews:
            continue
        review = reviews[item['id']]
        if item['state'] != 'pending_review' or item['lecture_original'] != review['lecture'] or item['linked_records'] != review['expected_records']:
            raise ValueError('Concept queue changed')
        item.update(state=STATE, review_scope=SCOPE, review_limitations=review['limitations'])
    if {q['id'] for q in queue if q['id'] in reviews} != reviews.keys():
        raise ValueError('Concept missing from queue')
    identity = sha(json.dumps({'base': base.name, 'recipe': sha(recipe_path.read_bytes()), 'processor': sha(Path(__file__).read_bytes())}, sort_keys=True))
    target = output / identity
    shutil.copytree(base, target)
    with sqlite3.connect(target / 'catalog.sqlite3') as db:
        for key, row in updates.items():
            db.execute('update records set data_json=? where id=?', (json.dumps(row, ensure_ascii=False), key))
        db.commit()
        if db.execute('pragma integrity_check').fetchone()[0] != 'ok':
            raise ValueError('Catalog integrity failure')
        changed = 0
        with sqlite3.connect((base / 'catalog.sqlite3').as_uri() + '?mode=ro', uri=True) as old:
            for a, b in zip(old.execute('select data_json from records order by id'), db.execute('select data_json from records order by id'), strict=True):
                a, b = json.loads(a[0]), json.loads(b[0])
                if a == b:
                    continue
                changed += 1
                if b['id'] not in updates or {k for k in a.keys() | b.keys() if a.get(k) != b.get(k)} != {'metadata'} or {k: v for k, v in b['metadata'].items() if k != 'lecture_assessment'} != a['metadata']:
                    raise ValueError('Unrelated data or approval changed')
        if changed != len(updates):
            raise ValueError('Changed count mismatch')
    report = {**summary, 'snapshot_id': identity, 'base_snapshot_id': base.name,
        'created_at': datetime.now(timezone.utc).isoformat(), 'catalog_sha256': sha((target / 'catalog.sqlite3').read_bytes()),
        'committed_batches': summary['committed_batches'] + 1,
        'scienceqa_shared_lectures_assessed_unchanged': len(prior_counts) + len(reviews),
        'scienceqa_linked_lectures_assessed_unchanged': sum(prior_counts.values()) + sum(counts.values())}
    (target / 'summary.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    (target / 'scienceqa-concept-queue.json').write_text(json.dumps(queue, ensure_ascii=False, indent=2) + '\n')
    archive = target / 'scienceqa-lecture-assessments'
    archive.mkdir(exist_ok=True)
    (archive / (sha(recipe_path.read_bytes()) + '.json')).write_bytes(recipe_path.read_bytes())
    return {'snapshot_id': identity, 'base_snapshot_id': base.name, 'catalog_sha256': report['catalog_sha256'],
        'committed_batches': report['committed_batches'], 'checked_concepts': len(reviews), 'linked_records': len(updates),
        'question_answer_approval_changes': 0, 'source_or_retrieval_changes': 0}
