"""Administrator content intake. Importing is not educational approval.

Use the existing course/node/item identities and graders. Nothing in this module
enrols learners, changes placements or turns a partial course into a full grade.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import asdict
import hashlib
import json
import math
import re
import time

from fastapi import HTTPException

from deeptutor.education.application import to_iso_timestamp
from deeptutor.education.application.grading_policy import is_servable
from deeptutor.education.storage.repositories import AssessmentItemRepository, _validate_item_row
from deeptutor.education.storage.sqlite import transaction

FIELDS = (
    'id', 'knowledge_node_id', 'item_type', 'prompt', 'expected_answer', 'rubric_json',
    'difficulty', 'content_scope', 'source_ref', 'license_note', 'attribution_text',
    'derived_from_item_id', 'figure_spec_id', 'choices_json', 'explanation', 'explanation_source',
)
ISSUES = {
    'prompt': '缺少完整题干', 'answer': '缺少参考答案', 'explanation': '缺少解题讲解',
    'source': '缺少来源记录', 'rights': '使用范围尚不支持发布', 'figure': '图示尚待校对',
    'placeholder': '包含缺失内容占位符', 'numeric': '数值答案无法直接批改',
    'choice': '参考答案不对应选项', 'rubric': '缺少评分依据',
    'review': '尚未完成内容审核', 'tags': '尚未配置正式考核分类',
    'provenance': '来源许可或署名不完整',
}


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def revision(row):
    # Server-computed review identity, including classification and provenance.
    return digest({k: row.get(k) for k in (*FIELDS, 'course_version_id', 'content_hash',
                                          'status', 'reviewer', 'reviewed_at')})


def content_issues(row):
    issues = []
    for field, code in [('prompt','prompt'), ('expected_answer','answer'),
                        ('explanation','explanation'), ('source_ref','source')]:
        if not str(row.get(field) or '').strip(): issues.append(code)
    if row.get('content_scope') != 'BUNDLED': issues.append('rights')
    source = str(row.get('source_ref') or '').strip().lower()
    license_note = str(row.get('license_note') or '').strip()
    attribution = str(row.get('attribution_text') or '').strip()
    if (source and not source.startswith('self-authored') and (not license_note or not attribution)) or (license_note.upper().startswith('CC') and not attribution):
        issues.append('provenance')
    if row.get('figure_spec_id') or row.get('item_type') == 'visual_model':
        issues.append('figure')  # This intake does not certify external assets.
    if re.search(r'Teachers with a valid|&nbsp;|\[image\]|image missing', row.get('prompt') or '', re.I):
        issues.append('placeholder')
    if row.get('item_type') == 'numeric' and row.get('expected_answer'):
        try:
            if not math.isfinite(float(row['expected_answer'])): issues.append('numeric')
        except (ValueError, TypeError): issues.append('numeric')
    if row.get('item_type') == 'choice':
        try:
            labels = {x['label'] for x in json.loads(row.get('choices_json') or '[]')}
            if row.get('expected_answer') not in labels: issues.append('choice')
        except (ValueError, KeyError, TypeError): issues.append('choice')
    if row.get('item_type') in ('multi_step','visual_model'):
        try:
            if not json.loads(row.get('rubric_json') or 'null'): issues.append('rubric')
        except ValueError: issues.append('rubric')
    return list(dict.fromkeys(issues))


def catalog(conn, judge_available=False):
    courses = []
    for record in conn.execute('SELECT v.id,v.status,c.title,c.subject_key,c.level FROM course_versions v JOIN courses c ON c.id=v.course_id ORDER BY c.subject_key,c.level,c.title'):
        course = dict(record)
        rows = [dict(r) for r in conn.execute('SELECT i.*,t.unit_id FROM assessment_items i LEFT JOIN assessment_item_tags t ON t.item_id=i.id WHERE i.course_version_id=?', (course['id'],))]
        counts = Counter(r['status'] for r in rows)
        problems = Counter()
        covered = set()
        ready = 0
        repository = AssessmentItemRepository(conn)
        for row in rows:
            if row['status'] == 'retired': continue
            blockers = content_issues(row)
            if not row['reviewer'] or not row['reviewed_at'] or row['status'] != 'production': blockers.append('review')
            if not row['unit_id']: blockers.append('tags')
            problems.update(blockers)
            if not blockers and is_servable(repository.get(row['id']), judge_available=judge_available):
                ready += 1
                covered.add(row['knowledge_node_id'])
        nodes = [dict(r) for r in conn.execute('SELECT id,code,title,standard_code FROM knowledge_nodes WHERE course_version_id=? ORDER BY sort_order', (course['id'],))]
        course.update(total=len(rows), candidate=counts['candidate'], published=counts['production'],
                      retired=counts['retired'], quiz_ready=ready, covered_nodes=len(covered), nodes=nodes,
                      issues=dict(problems), blueprint=bool(conn.execute('SELECT 1 FROM assessment_courses WHERE course_version_id=?', (course['id'],)).fetchone()))
        courses.append(course)
    return {'courses':courses, 'issue_labels':ISSUES,
            'imports':[dict(r) for r in conn.execute('SELECT id,course_version_id,source_name,imported_at,inserted,skipped FROM content_imports ORDER BY imported_at DESC LIMIT 30')]}


def items(conn, version, *, page=0):
    rows = []
    for record in conn.execute('SELECT * FROM assessment_items WHERE course_version_id=? ORDER BY status,id LIMIT 40 OFFSET ?', (version, page * 40)):
        row = dict(record)
        row.update(revision=revision(row), issues=content_issues(row))
        rows.append(row)
    return {'items':rows, 'total':conn.execute('SELECT count(*) FROM assessment_items WHERE course_version_id=?', (version,)).fetchone()[0]}


def normalize(conn, version, raw):
    if not isinstance(raw, dict): raise ValueError('Each item must be an object')
    row = {key:raw.get(key) for key in FIELDS}
    if not isinstance(row['id'], str) or not re.fullmatch(r'[A-Za-z0-9_.-]{1,160}', row['id']):
        raise ValueError('Invalid item id')
    if raw.get('course_version_id') not in (None, version): raise ValueError('Course version mismatch')
    if not row['knowledge_node_id'] and raw.get('knowledge_node_code'):
        node = conn.execute('SELECT id FROM knowledge_nodes WHERE course_version_id=? AND code=?', (version, raw['knowledge_node_code'])).fetchone()
        row['knowledge_node_id'] = node[0] if node else None
    if not conn.execute('SELECT 1 FROM knowledge_nodes WHERE course_version_id=? AND id=?', (version,row['knowledge_node_id'])).fetchone():
        raise ValueError('Unknown knowledge node in this course')
    # Main-library intake cannot turn private/unknown material into shared content.
    if row['content_scope'] != 'BUNDLED': raise ValueError('Main-library intake requires BUNDLED rights; private material uses the family workflow')
    if not str(row['source_ref'] or '').strip(): raise ValueError('Source provenance is required')
    for key in ('rubric_json','choices_json'):
        if isinstance(row[key], (dict,list)): row[key] = json.dumps(row[key],ensure_ascii=False)
        elif row[key] is not None:
            if not isinstance(row[key],str): raise ValueError(f'Invalid {key}')
            json.loads(row[key])
    for key in FIELDS:
        if key != 'difficulty' and row[key] is not None and not isinstance(row[key],str): raise ValueError(f'Invalid {key}')
        if isinstance(row[key],str) and len(row[key])>24000: raise ValueError(f'{key} is too long')
    if type(row['difficulty']) is not int or not 1 <= row['difficulty'] <= 5: raise ValueError('Difficulty must be 1–5')
    if row['derived_from_item_id'] and not conn.execute('SELECT 1 FROM assessment_items WHERE id=? AND course_version_id=?', (row['derived_from_item_id'],version)).fetchone():
        raise ValueError('Unknown source item in this course')
    row.update(course_version_id=version, status='candidate', reviewer=None, reviewed_at=None,
               content_hash=digest({k:row[k] for k in FIELDS}))
    return asdict(_validate_item_row(row))


def plan_import(conn, payload):
    if not isinstance(payload,dict): raise HTTPException(400,'Expected a content package object')
    version = payload.get('course_version_id')
    if not isinstance(version,str) or not conn.execute("SELECT 1 FROM course_versions WHERE id=? AND status!='archived'",(version,)).fetchone():
        raise HTTPException(400,'Select an existing non-archived course version')
    incoming = payload.get('items')
    if not isinstance(incoming,list) or not 1 <= len(incoming) <= 1000: raise HTTPException(400,'A package must contain 1–1000 items')
    new, skipped, errors, seen = [], [], [], set()
    for index, raw in enumerate(incoming):
        try:
            row = normalize(conn,version,raw)
            if row['id'] in seen: raise ValueError('Duplicate id inside this package')
            seen.add(row['id'])
            old = conn.execute('SELECT * FROM assessment_items WHERE id=?',(row['id'],)).fetchone()
            if old:
                if old['course_version_id'] != version or any(old[k] != row[k] for k in FIELDS):
                    raise ValueError('Existing item differs; use a new id and derived_from_item_id')
                skipped.append(row['id'])
            else: new.append(row)
        except (ValueError,TypeError,KeyError) as exc:
            errors.append({'row':index+1,'message':str(exc)[:400]})
    name = str(payload.get('source_name') or 'Content package')[:160]
    try: package_id = digest({'course':version,'name':name,'items':incoming})
    except ValueError:
        errors.append({'row':0,'message':'Non-finite numbers are not valid JSON content'})
        package_id = digest({'course':version,'errors':errors})
    receipt = {'id':package_id, 'course_version_id':version,
               'source_name':name,'inserted':len(new),'skipped':len(skipped),'errors':errors,
               'needs_review':len(new), 'issues':dict(Counter(code for row in new for code in content_issues(row)))}
    return receipt,new


def import_package(conn, payload, actor):
    with transaction(conn):
        receipt,rows = plan_import(conn,payload)
        if receipt['errors']: raise HTTPException(400,{'message':'Package rejected; no items were written','errors':receipt['errors']})
        existing = conn.execute('SELECT receipt_json FROM content_imports WHERE id=?',(receipt['id'],)).fetchone()
        if existing: return {**json.loads(existing[0]),'replayed':True}
        AssessmentItemRepository(conn).import_items(rows)
        conn.execute('INSERT INTO content_imports VALUES(?,?,?,?,?,?,?,?)',
                     (receipt['id'],receipt['course_version_id'],receipt['source_name'],actor,to_iso_timestamp(time.time()),receipt['inserted'],receipt['skipped'],json.dumps(receipt,ensure_ascii=False)))
    return {**receipt,'replayed':False}


def review_item(conn, item_id, *, expected_revision, decision, note, actor):
    if decision not in ('publish','retire') or len(note.strip())<12: raise HTTPException(400,'A substantive review note is required')
    with transaction(conn):
        record = conn.execute('SELECT * FROM assessment_items WHERE id=?',(item_id,)).fetchone()
        if not record: raise HTTPException(404,'Item not found')
        row=dict(record)
        if revision(row) != expected_revision: raise HTTPException(409,'Content changed; reload before review')
        if decision == 'publish':
            blockers = content_issues(row)
            if blockers: raise HTTPException(409,{'message':'Resolve content issues before publishing','issues':blockers})
            if row['status'] != 'candidate': raise HTTPException(409,'Only a candidate can be published')
            try:
                _validate_item_row(row)
            except (ValueError, TypeError, KeyError) as exc:
                raise HTTPException(409, str(exc)) from None
        stamp=to_iso_timestamp(time.time())
        conn.execute('INSERT INTO content_reviews(item_id,content_hash,actor_id,decision,note,created_at) VALUES(?,?,?,?,?,?)',
                     (item_id,revision(row),actor,decision,note.strip(),stamp))
        conn.execute('UPDATE assessment_items SET status=?,reviewer=?,reviewed_at=? WHERE id=?',
                     ('production' if decision=='publish' else 'retired',actor,stamp,item_id))
    return {'saved':True}
