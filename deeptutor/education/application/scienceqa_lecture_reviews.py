"""Offline, source-bound ScienceQA lecture corrections; never approve questions.

Produces revised retrieval documents, a concept work queue, and a new immutable
admin catalog. Deployment/index activation are deliberately separate operations.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import shutil
import sqlite3

from .content_stock import parse_file
from .scienceqa_explanation_reviews import patch_document as patch_explanations
from .scienceqa_context_reviews import patch_document as patch_contexts, prior_reviews_by_path


def sha(value: str | bytes) -> str:
    return hashlib.sha256(value.encode() if isinstance(value, str) else value).hexdigest()


def concept_id(text: str) -> str:
    return sha(re.sub(r'\s+', ' ', text).strip())


def patch_document(text: str, reviews: dict[str, dict]) -> tuple[str, Counter]:
    """Replace only complete Lecture bodies; preserve all other source bytes."""
    counts = Counter()
    pattern = re.compile(r'(^### Lecture\n)(.*?)(?=^### |^## |^---\s*$|\Z)', re.M | re.S)

    def replace(match):
        original = match[2]
        key = concept_id(original)
        review = reviews.get(key)
        if review is None:
            return match[0]
        if concept_id(review['lecture_before']) != key:
            raise ValueError('Review does not match its concept hash')
        new = review['lecture_after']
        if not new.strip() or re.search(r'^#{1,3} ', new, re.M):
            raise ValueError('Invalid replacement lecture')
        leading = original[:len(original) - len(original.lstrip())]
        trailing = original[len(original.rstrip()):]
        counts[key] += 1
        return match[1] + leading + new.strip() + trailing

    return pattern.sub(replace, text), counts


def validate_roundtrip(filename: str, before: str, after: str, reviews: dict) -> int:
    old = parse_file('scienceqa', filename, before)
    new = parse_file('scienceqa', filename, after)
    changed = 0
    for a, b in zip(old, new, strict=True):
        key = concept_id(a['lecture'])
        expected = reviews[key]['lecture_after'] if key in reviews else a['lecture']
        if b['lecture'] != expected:
            raise ValueError('Reparsed lecture differs from reviewed replacement')
        for field in a.keys() | b.keys():
            if field not in {'lecture', 'start', 'end'} and a.get(field) != b.get(field):
                raise ValueError('Question data changed: ' + field)
        changed += a['lecture'] != b['lecture']
    return changed


def build(base: Path, recipe_path: Path, output: Path) -> dict:
    base = base.resolve()
    previous = json.loads((base / 'summary.json').read_text())
    if previous['snapshot_id'] != base.name:
        raise ValueError('Snapshot identity mismatch')
    if sha((base / 'catalog.sqlite3').read_bytes()) != previous['catalog_sha256']:
        raise ValueError('Catalog checksum mismatch')
    recipe = json.loads(recipe_path.read_text())
    reviews = {x['concept_id']: x for x in recipe['reviews']}
    if len(reviews) != len(recipe['reviews']) or recipe['library'] != 'scienceqa':
        raise ValueError('Invalid review identities')
    for key, item in reviews.items():
        if concept_id(item['lecture_before']) != key or not item['references']:
            raise ValueError('Review evidence missing or changed')
    with sqlite3.connect((base / 'catalog.sqlite3').as_uri() + '?mode=ro', uri=True) as db:
        rows = [json.loads(x[0]) for x in db.execute("select data_json from records where library='scienceqa' order by rowid")]
    if len(rows) != recipe['expected_total_records']:
        raise ValueError('ScienceQA inventory changed')
    # Reconstruct earlier corrections from immutable provenance, so a later
    # batch on the same file cannot silently restore an older lecture.
    prior_reviews = {}
    review_fields = set(next(iter(reviews.values())))
    for row in rows:
        prior = row['metadata'].get('lecture_review')
        if not prior:
            continue
        if not review_fields <= prior.keys() or row['lecture'] != prior['lecture_after']:
            raise ValueError('Previous lecture provenance is incomplete or changed')
        key = prior['concept_id']
        normalized = {field:prior[field] for field in review_fields}
        if key != concept_id(prior['lecture_before']):
            raise ValueError('Previous lecture identity changed')
        if key in prior_reviews and prior_reviews[key] != normalized:
            raise ValueError('Conflicting prior lecture reviews')
        prior_reviews[key] = normalized
    prior_explanations = {}
    for row in rows:
        prior = row['metadata'].get('individual_explanation_review')
        if not prior:
            continue
        if any(prior.get(k) != row[k] for k in ('source_path', 'source_sha256', 'raw_sha256')) or prior.get('record_id') != row['id'] or prior.get('source_title') != row['title'] or prior.get('answer_before') != row['answer'] or prior.get('explanation_after') != row['explanation']:
            raise ValueError('Previous individual explanation provenance changed')
        if prior.get('answer_on_hold') and row['state'] not in {'needs_fact_check', 'duplicate'}:
            raise ValueError('Previous answer hold was cleared')
        prior_explanations.setdefault(row['source_path'], []).append(prior)
    prior_contexts = prior_reviews_by_path(rows)
    if reviews.keys() & prior_reviews.keys():
        raise ValueError('Concept already reviewed; preserve its history instead of reapplying')
    def original_lecture(row):
        return row['metadata'].get('lecture_review', {}).get('lecture_before', row['lecture'])
    counts = Counter(concept_id(original_lecture(x)) for x in rows)
    combined_reviews = {**prior_reviews, **reviews}
    for key, prior in prior_reviews.items():
        if counts[key] != prior['expected_records']:
            raise ValueError('Prior review population changed')
    for key, review in reviews.items():
        if counts[key] != review['expected_records']:
            raise ValueError('Linked review count changed')
    identity = sha(json.dumps({'base':base.name, 'recipe':sha(recipe_path.read_bytes()), 'processor':sha(Path(__file__).read_bytes())}, sort_keys=True))
    target = output / identity
    target.mkdir(parents=True, exist_ok=False)
    shutil.copytree(base / 'objects', target / 'objects')
    shutil.copy2(base / 'sources.json', target / 'sources.json')
    # A later subject batch must retain other subjects' repair queues/assets.
    rebuilt = {'objects', 'sources.json', 'catalog.sqlite3', 'summary.json',
               'revised-documents', 'revised-documents.json',
               'scienceqa-lecture-reviews.json', 'scienceqa-concept-queue.json'}
    for item in base.iterdir():
        if item.name in rebuilt:
            continue
        if item.is_symlink():
            raise ValueError('Unexpected symlink in immutable snapshot')
        if item.is_dir():
            shutil.copytree(item, target / item.name)
        else:
            shutil.copy2(item, target / item.name)
    corrected = target / 'revised-documents'
    corrected.mkdir()
    manifest = []
    all_counts = Counter()
    by_path = {}
    for row in rows:
        by_path.setdefault(row['source_path'], row['source_sha256'])
        if by_path[row['source_path']] != row['source_sha256']:
            raise ValueError('Source path has inconsistent hashes')
    for source_path, source_sha in sorted(by_path.items()):
        blob = (base / 'objects' / (source_sha + '.md')).read_bytes()
        if sha(blob) != source_sha:
            raise ValueError('Source bytes changed')
        text = blob.decode('utf-8')
        before, _ = patch_document(text, prior_reviews)
        after, combined_counts = patch_document(text, combined_reviews)
        # Rebuild both sides from immutable source and the complete prior ledger.
        # The expected-current hash must describe the live corrected document.
        if source_path in prior_explanations:
            selected_explanations = prior_explanations[source_path]
            before = patch_explanations(Path(source_path).name, before, selected_explanations)
            after = patch_explanations(Path(source_path).name, after, selected_explanations)
        if source_path in prior_contexts:
            before = patch_contexts(Path(source_path).name, before, prior_contexts[source_path])
            after = patch_contexts(Path(source_path).name, after, prior_contexts[source_path])
        linked = Counter({k:v for k,v in combined_counts.items() if k in reviews})
        all_counts.update(linked)
        if not linked:
            continue
        filename = Path(source_path).name
        if validate_roundtrip(filename, before, after, reviews) != sum(linked.values()):
            raise ValueError('Document/parser replacement count mismatch')
        new_sha = sha(after)
        (corrected / filename).write_text(after, encoding='utf-8')
        (target / 'objects' / (new_sha + '.md')).write_text(after, encoding='utf-8')
        manifest.append({'source_path':source_path, 'source_sha256':source_sha, 'expected_current_sha256':sha(before), 'revised_sha256':new_sha, 'changed_lectures':sum(linked.values())})
    if dict(all_counts) != {k:v['expected_records'] for k,v in reviews.items()}:
        raise ValueError('Not all reviewed lectures were replaced')
    changed = sum(all_counts.values())
    if changed != recipe['expected_changed_records']:
        raise ValueError('Unexpected correction total')
    file_map = {x['source_path']:x for x in manifest}
    with sqlite3.connect((base / 'catalog.sqlite3').as_uri() + '?mode=ro', uri=True) as a, sqlite3.connect(target / 'catalog.sqlite3') as b:
        a.backup(b)
        for row in rows:
            key = concept_id(row['lecture'])
            if key not in reviews:
                continue
            review = reviews[key]
            row['lecture'] = review['lecture_after']
            row['metadata'] = {**row['metadata'], 'lecture_review':{
                **review, 'original_source_sha256':row['source_sha256'],
                'revised_document_sha256':file_map[row['source_path']]['revised_sha256'],
                'recipe_sha256':sha(recipe_path.read_bytes()),
            }}
            b.execute('update records set data_json=? where id=?', (json.dumps(row,ensure_ascii=False),row['id']))
        b.commit()
        if b.execute('pragma integrity_check').fetchone()[0] != 'ok':
            raise ValueError('Catalog integrity failure')
        actual = 0
        for old, new in zip(a.execute('select data_json from records order by id'), b.execute('select data_json from records order by id'), strict=True):
            old, new = json.loads(old[0]), json.loads(new[0])
            if old == new:
                continue
            if old['library'] != 'scienceqa' or concept_id(old['lecture']) not in reviews:
                raise ValueError('Unrelated record modified')
            if {k for k in old.keys() | new.keys() if old.get(k) != new.get(k)} != {'lecture','metadata'}:
                raise ValueError('Question/approval/source identity modified')
            actual += 1
        if actual != changed:
            raise ValueError('Catalog correction count mismatch')
    concepts = {}
    for row in rows:
        # Original immutable source lecture remains the grouping identity.
        review = row['metadata'].get('lecture_review')
        original = review['lecture_before'] if review else row['lecture']
        key = concept_id(original)
        item = concepts.setdefault(key, {'id':key,'lecture_original':original,'linked_records':0,'source_paths':set(),'skills':set(),'state':'pending_review' if original.strip() else 'missing_lecture'})
        item['linked_records'] += 1
        item['source_paths'].add(row['source_path'])
        item['skills'].add(row['metadata'].get('skill',''))
        if key in combined_reviews:
            item.update(state='shared_lecture_corrected', lecture_revised=combined_reviews[key]['lecture_after'], review_scope='Not a review of individual questions, answers, diagrams, or grade suitability.')
    queue = []
    for item in concepts.values():
        item['source_paths'] = sorted(item['source_paths']); item['skills'] = sorted(item['skills'])
        queue.append(item)
    report = {**previous,'snapshot_id':identity,'base_snapshot_id':base.name,'created_at':datetime.now(timezone.utc).isoformat(),
        'catalog_sha256':sha((target/'catalog.sqlite3').read_bytes()),'committed_batches':previous['committed_batches']+1,
        'scienceqa_shared_lectures_corrected':len(combined_reviews),'scienceqa_linked_lectures_corrected':sum(x['expected_records'] for x in combined_reviews.values()),
        'scienceqa_batch_shared_lectures_corrected':len(reviews),'scienceqa_batch_linked_lectures_corrected':changed,
        'scienceqa_review_recipe_sha256':sha(recipe_path.read_bytes()),
        'scienceqa_review_note':'Original source identities/spans retained; only derived lecture and provenance updated. No question, answer, grade, or approval change.'}
    (target/'summary.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    (target/'scienceqa-lecture-reviews.json').write_bytes(recipe_path.read_bytes())
    (target/'revised-documents.json').write_text(json.dumps(manifest,indent=2)+'\n')
    (target/'scienceqa-concept-queue.json').write_text(json.dumps(queue,ensure_ascii=False,indent=2)+'\n')
    return {'snapshot_id':identity,'changed_lectures':changed,'changed_documents':manifest,'shared_concepts':sum(bool(x['lecture_original'].strip()) for x in queue),'missing_lecture_records':sum(x['linked_records'] for x in queue if not x['lecture_original'].strip()),'question_or_answer_changes':0,'formal_items_created':0}
