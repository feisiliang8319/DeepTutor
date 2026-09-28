"""Formal assessment policy, separate from tutoring and optional practice.

All selection, deadlines, scores and promotions are server-owned. Source answers
remain in the existing append-only attempt/submission tables.
"""
from __future__ import annotations
from collections import defaultdict
from functools import lru_cache
import hashlib
import json
import random
import re
import sqlite3
import time
import unicodedata
from uuid import uuid4
from fastapi import HTTPException
from deeptutor.education.application import to_iso_timestamp
from deeptutor.education.application import exam_integrity as integrity
from deeptutor.education.application.content_readiness import admitted
from deeptutor.education.application.grading_policy import is_servable
from deeptutor.education.storage.sqlite import transaction
from deeptutor.education.storage.repositories import AssessmentItemRepository, JudgmentRepository

STEM_SUBJECTS = {
    "mathematics": {"mathematics", "math", "maths"},
    "science": {"science", "physics", "chemistry", "biology", "earth_science"},
    "technology": {"technology", "computer_science", "computing"},
    "engineering": {"engineering"},
}

SPECS = {"checkin": (10,20), "daily": (20,50), "unit": (25,70), "final": (35,90), "promotion": (35,90), "competition": (20,90), "foundation": (35,90)}


def quotas(count):
    raw = [count * p for p in (.15,.65,.20)]
    result = [int(n) for n in raw]
    for index in sorted(range(3), key=lambda i: (-(raw[i]-result[i]),i))[:count-sum(result)]:
        result[index] += 1
    return dict(zip("ABC",result))


def grading_signature(item):
    return hashlib.sha256(json.dumps([item.prompt,item.expected_answer,item.rubric_json,item.choices_json,item.content_hash],ensure_ascii=False).encode()).hexdigest()


def fingerprint(prompt):
    normalized = re.sub(r"\s+", " ", unicodedata.normalize("NFKC", prompt or "")).strip().casefold()
    return hashlib.sha256(normalized.encode()).hexdigest()


def course(conn, version, *, active=True):
    row = conn.execute("SELECT a.*,c.subject_key,c.title FROM assessment_courses a JOIN course_versions v ON v.id=a.course_version_id JOIN courses c ON c.id=v.course_id WHERE v.id=? AND (?=0 OR v.status='active')",(version,int(active))).fetchone()
    if row is None: raise HTTPException(409,"这门课程尚未配置正式考核范围。")
    return dict(row)


def placement(conn, learner, config):
    row = conn.execute("SELECT * FROM subject_placements WHERE learner_id=? AND subject_key=? AND curriculum_key=?",(learner,config['subject_key'],config['curriculum_key'])).fetchone()
    if row is None: raise HTTPException(409,"请家长先设置这门学科的学习起点。")
    return dict(row)


def configure(conn, version, curriculum_key, grade, units, actor, competition_domain=None):
    subject = conn.execute("SELECT c.subject_key FROM courses c JOIN course_versions v ON v.course_id=c.id WHERE v.id=? AND v.status='active'", (version,)).fetchone()
    if subject is None: raise HTTPException(404,"课程不存在或尚未发布。")
    if competition_domain is not None and subject[0].casefold() not in STEM_SUBJECTS.get(competition_domain,set()):
        raise HTTPException(400,"该学科不属于所选STEM竞赛领域。")
    valid = {r[0] for r in conn.execute("SELECT id FROM knowledge_nodes WHERE course_version_id=?",(version,))}
    if not units or len(set(units)) != len(units) or not set(units) <= valid:
        raise HTTPException(400,"必修单元必须来自该课程，且不能重复或为空。")
    with transaction(conn):
        if conn.execute("SELECT 1 FROM formal_exams WHERE course_version_id=?",(version,)).fetchone():
            raise HTTPException(409,"已发卷的考核范围不能改写；请发布新的课程版本。")
        conn.execute("INSERT INTO assessment_courses VALUES(?,?,?,?,?,?,?) ON CONFLICT(course_version_id) DO UPDATE SET curriculum_key=excluded.curriculum_key,grade=excluded.grade,units_json=excluded.units_json,configured_by=excluded.configured_by,configured_at=excluded.configured_at,competition_domain=excluded.competition_domain",(version,curriculum_key,grade,json.dumps(units),actor,to_iso_timestamp(time.time()),competition_domain))


def tag_item(conn, item_id, values):
    item = AssessmentItemRepository(conn).get(item_id)
    if item is None: raise HTTPException(404,"题目不存在。")
    config = course(conn,item.course_version_id)
    if values['unit_id'] not in json.loads(config['units_json']): raise HTTPException(400,"题目必须映射到已配置的必修单元。")
    if values['bank']=='competition' and not config['competition_domain']: raise HTTPException(400,"非STEM课程不能配置竞赛题库。")
    if values['bank']=='competition' and values['tier']!='A': raise HTTPException(400,"竞赛正式卷只使用难题。")
    with transaction(conn):
        if conn.execute("SELECT 1 FROM formal_exams f, json_each(f.snapshot_json,'$.items') j WHERE json_extract(j.value,'$.id')=?",(item_id,)).fetchone(): raise HTTPException(409,"已发出的题目分类不能改写，请录入新题。")
        conn.execute("INSERT INTO assessment_item_tags VALUES(?,?,?,?,?,?,?) ON CONFLICT(item_id) DO UPDATE SET unit_id=excluded.unit_id,tier=excluded.tier,bank=excluded.bank,core=excluded.core,points=excluded.points,family_key=excluded.family_key",(item_id,values['unit_id'],values['tier'],values['bank'],int(values['core']),values['points'],values.get('family_key') or item.derived_from_item_id or fingerprint(item.prompt)))


def set_placement(conn, learner, config, grade, entry_level, school_grade, actor, revision):
    with transaction(conn):
        existing = conn.execute("SELECT * FROM subject_placements WHERE learner_id=? AND subject_key=? AND curriculum_key=?",(learner,config['subject_key'],config['curriculum_key'])).fetchone()
        if (existing['revision'] if existing else 0) != revision: raise HTTPException(409,"学习安排已变化，请刷新后保存。")
        # A parent sets the initial placement. Subsequent grade changes use an
        # evidenced promotion, never overwrite tested progression with a form.
        if existing and existing['grade'] != grade and conn.execute("SELECT 1 FROM formal_exams WHERE learner_id=? AND subject_key=? AND curriculum_key=?",(learner,config['subject_key'],config['curriculum_key'])).fetchone(): raise HTTPException(409,"已有正式测试记录；调整年级请使用晋级流程。")
        stamp=to_iso_timestamp(time.time())
        conn.execute("INSERT INTO subject_placements VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(learner_id,subject_key,curriculum_key) DO UPDATE SET grade=excluded.grade,entry_level=excluded.entry_level,revision=excluded.revision,updated_by=excluded.updated_by,updated_at=excluded.updated_at",(learner,config['subject_key'],config['curriculum_key'],grade,entry_level,revision+1,actor,stamp))
        conn.execute("INSERT INTO academic_background VALUES(?,?,?,?) ON CONFLICT(learner_id) DO NOTHING",(learner,school_grade,actor,stamp))
        conn.execute("INSERT INTO placement_events(learner_id,subject_key,curriculum_key,grade,actor_id,source,created_at) VALUES(?,?,?,?,?,?,?)",(learner,config['subject_key'],config['curriculum_key'],grade,actor,'parent_context_update' if existing else 'parent_initial_placement',time.time()))


def records(conn, learner, config, grade):
    return [dict(r) for r in conn.execute("SELECT * FROM formal_exams WHERE learner_id=? AND subject_key=? AND curriculum_key=? AND grade=? AND result_json IS NOT NULL ORDER BY deadline",(learner,config['subject_key'],config['curriculum_key'],grade))]


def unit_evidence(conn, learner, config, grade):
    units = set(json.loads(config['units_json']))
    passed={}; core={}
    for exam in records(conn,learner,config,grade):
        if exam['course_version_id'] != config['course_version_id']: continue
        result=json.loads(exam['result_json'])
        if result.get('status') != 'final': continue
        for unit, value in result.get('core',{}).items():
            if value['count'] >= 2 and value['percent'] >= 80: core[unit]=exam['set_id']
        if exam['kind']=='unit' and result['passed']: passed[exam['unit_id']]=exam['set_id']
    return {'units':passed,'core':core,'missing_units':sorted(units-set(passed)),'missing_core':sorted(units-set(core))}


def remedied(conn, exam):
    """An actual follow-up exchange is engagement evidence, never mastery."""
    from deeptutor.multi_user.paths import scope_for_user,get_path_service_for_scope
    owner=conn.execute('SELECT deep_tutor_user_id FROM learner_profiles WHERE id=?',(exam['learner_id'],)).fetchone()[0]
    path=get_path_service_for_scope(scope_for_user(owner,is_admin=False)).get_chat_history_db()
    if not path.exists(): return False
    session='unified_quiz_'+hashlib.sha256(exam['set_id'].encode()).hexdigest()[:24]
    db=sqlite3.connect('file:'+str(path)+'?mode=ro',uri=True)
    try:
        # Every normal completed tutor turn has a user and assistant message.
        return db.execute("SELECT 1 FROM messages u JOIN messages a ON a.session_id=u.session_id AND a.role='assistant' AND a.id>u.id WHERE u.session_id=? AND u.role='user' AND length(trim(a.content))>0 AND EXISTS(SELECT 1 FROM turns t WHERE t.session_id=u.session_id AND t.status='completed' AND t.finished_at>=u.created_at AND t.created_at<=a.created_at) LIMIT 1",(session,)).fetchone() is not None
    finally: db.close()


def _select(pool, requested, units, require_core):
    """Allocate core coverage with memoized capacity search, then random fill."""
    groups=defaultdict(list)
    for row in pool: groups[(row['unit_id'],row['tier'],bool(row['core']))].append(row)
    for group in groups.values(): random.SystemRandom().shuffle(group)
    core_counts={(unit,tier):len(groups[(unit,tier,True)]) for unit in units for tier in 'ABC'}
    @lru_cache(None)
    def allocation(index,a,b,c):
        if index==len(units): return ()
        if not require_core: return ()
        unit=units[index]
        for ha in range(min(a,core_counts[(unit,'A')],2)+1):
            for me in range(min(b,core_counts[(unit,'B')],2-ha)+1):
                ea=2-ha-me
                if ea<=c and ea<=core_counts[(unit,'C')]:
                    rest=allocation(index+1,a-ha,b-me,c-ea)
                    if rest is not None: return ((ha,me,ea),)+rest
        return None
    plan=allocation(0,*[requested[t] for t in 'ABC'])
    if plan is None: raise HTTPException(409,"题库不足以同时满足核心覆盖与难度配额，请管理员补充已审核题目。")
    chosen=[]
    if require_core:
        for unit, counts in zip(units,plan):
            for tier,count in zip('ABC',counts): chosen.extend(groups[(unit,tier,True)][:count])
    picked={r['id'] for r in chosen}
    for tier,count in requested.items():
        candidates=[r for r in pool if r['tier']==tier and r['id'] not in picked]
        left=count-sum(r['tier']==tier for r in chosen)
        if len(candidates)<left: raise HTTPException(409,{"message":"未见过的已审核题目不足：难度 {{tier}} 还需 {{needed}} 题，可用 {{available}} 题。","values":{"tier":tier,"needed":left,"available":len(candidates)}})
        additions=random.SystemRandom().sample(candidates,left);chosen.extend(additions);picked.update(r['id'] for r in additions)
    random.SystemRandom().shuffle(chosen)
    return chosen


def issue(conn, learner, version, kind, unit=None, *, judge_available=False, competition_set_id=None, page_session=None):
    if kind not in SPECS: raise HTTPException(400,"未知测试类型。")
    with transaction(conn):
        integrity.require_retake_permission(conn,learner)
        config=course(conn,version,active=kind!='foundation'); current=placement(conn,learner,config)
        if kind=='foundation':
            source=conn.execute("SELECT f.*,p.to_grade FROM formal_exams f JOIN promotion_events p ON p.set_id=f.set_id WHERE f.set_id=? AND f.learner_id=? AND f.course_version_id=? AND f.kind='competition'",(competition_set_id,learner,version)).fetchone()
            source_result=json.loads(source['result_json'] or '{}') if source else {}
            if not source or not source_result.get('passed') or source_result.get('promotion',{}).get('review_required'):
                raise HTTPException(409,"基础补测只能在竞赛通过并晋级后开始。")
            if conn.execute('SELECT 1 FROM competition_foundation_choices WHERE competition_set_id=?',(competition_set_id,)).fetchone():
                raise HTTPException(409,"这次竞赛的补测选择已记录。")
        if kind=='competition' and config['subject_key'].casefold() not in STEM_SUBJECTS.get(config['competition_domain'],set()): raise HTTPException(403,"竞赛测试仅向已配置竞赛题库的STEM课程开放。")
        units=json.loads(config['units_json'])
        if kind=='unit':
            if unit not in units: raise HTTPException(400,"请选择有效单元。")
            units=[unit]
        elif unit is not None: raise HTTPException(400,"该测试不接受单元参数。")
        if kind!='foundation' and config['grade']!=current['grade'] and not (kind=='promotion' and config['grade']>current['grade']): raise HTTPException(409,"这份试卷与当前学科学习年级不匹配。")
        if kind=='promotion' and config['grade']>current['grade']:
            for grade in range(current['grade'],config['grade']):
                if not any(json.loads(r['result_json']).get('qualified') for r in records(conn,learner,config,grade) if r['kind']=='promotion'):
                    raise HTTPException(409,"跨级前须先通过被跳过年级的综合考核。")
        evidence=unit_evidence(conn,learner,config,config['grade'])
        if kind=='final' and evidence['missing_units']: raise HTTPException(409,"请先完成所有必修单元测试并达到80分。")
        existing=conn.execute("SELECT f.* FROM formal_exams f JOIN task_sets t ON t.id=f.set_id WHERE f.learner_id=? AND t.skipped_at IS NULL AND (t.submitted_at IS NULL OR f.result_json IS NULL OR json_extract(f.result_json,'$.status')='grading')",(learner,)).fetchone()
        if existing:
            if kind=='foundation': raise HTTPException(409,"请先完成当前测试，再开始基础补测。")
            integrity.inspect(conn,existing['set_id'],page_session)
            return public_exam(conn,existing['set_id'])
        if conn.execute("SELECT 1 FROM task_sets WHERE learner_id=? AND course_version_id=? AND submitted_at IS NULL AND skipped_at IS NULL",(learner,version)).fetchone(): raise HTTPException(409,"请先完成现有练习，再开始正式测试。")
        previous=conn.execute("SELECT * FROM formal_exams WHERE learner_id=? AND course_version_id=? AND kind=? AND unit_id IS ? AND result_json IS NOT NULL ORDER BY deadline DESC LIMIT 1",(learner,version,kind,unit)).fetchone()
        if previous and kind!='foundation':
            result=json.loads(previous['result_json'])
            if result.get('status') not in {'final','invalidated'}: raise HTTPException(409,"上次测试仍有题目等待复核。")
            if result.get('status')!='invalidated' and not result['passed'] and not remedied(conn,previous): raise HTTPException(409,"请先到上次测试的Chat完成订正交流，再领取新卷。")
        seen_ids={r[0] for r in conn.execute('SELECT assessment_item_id FROM student_attempts WHERE learner_id=?',(learner,))}
        for row in conn.execute('SELECT item_ids_json FROM task_sets WHERE learner_id=?',(learner,)): seen_ids.update(json.loads(row[0]))
        seen_families=set();seen_prints=set()
        repo=AssessmentItemRepository(conn)
        for item_id in seen_ids:
            old=repo.get(item_id)
            if old: seen_prints.add(fingerprint(old.prompt))
            tag=conn.execute('SELECT family_key FROM assessment_item_tags WHERE item_id=?',(item_id,)).fetchone()
            if tag: seen_families.add(tag[0])
        candidates=[];bank='competition' if kind=='competition' else 'regular'
        for row in conn.execute('SELECT t.* FROM assessment_item_tags t JOIN assessment_items i ON i.id=t.item_id WHERE i.course_version_id=? AND t.bank=?',(version,bank)):
            tag=dict(row);item=repo.get(tag['item_id'])
            if tag['unit_id'] not in units or item.id in seen_ids or tag['family_key'] in seen_families or fingerprint(item.prompt) in seen_prints: continue
            if not admitted(item,'production') or not is_servable(item,judge_available=judge_available): continue
            candidates.append({**tag,'id':item.id,'content_hash':item.content_hash,'grading_signature':grading_signature(item),'fingerprint':fingerprint(item.prompt),'public':item.to_public_payload()})
        # One representative per identical prompt or curated variant family.
        random.SystemRandom().shuffle(candidates); candidates.sort(key=lambda row: not row['core']); pool=[];families=set();prints=set()
        for candidate in candidates:
            if candidate['family_key'] in families or candidate['fingerprint'] in prints: continue
            families.add(candidate['family_key']);prints.add(candidate['fingerprint']);pool.append(candidate)
        count,minutes=SPECS[kind]
        selected=_select(pool,{'A':count,'B':0,'C':0} if kind=='competition' else quotas(count),units,kind in {'unit','final','promotion','foundation'})
        set_id='exam-'+uuid4().hex;now=time.time()
        snapshot={'version':2,'competition_set_id':competition_set_id,'count':count,'minutes':minutes,'units':units,'items':selected,'threshold':70 if kind=='competition' else 90 if kind=='promotion' else 80}
        conn.execute('INSERT INTO task_sets(id,learner_id,course_version_id,item_ids_json,issued_at) VALUES(?,?,?,?,?)',(set_id,learner,version,json.dumps([r['id'] for r in selected]),to_iso_timestamp(now)))
        conn.execute('INSERT INTO formal_exams(set_id,learner_id,course_version_id,subject_key,curriculum_key,grade,placement_revision,placement_grade,kind,unit_id,deadline,snapshot_json) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',(set_id,learner,version,config['subject_key'],config['curriculum_key'],config['grade'],current['revision'],current['grade'],kind,unit,now+minutes*60,json.dumps(snapshot)))
        integrity.start(conn,set_id,page_session)
        return public_exam(conn,set_id)


def public_exam(conn,set_id):
    row=conn.execute('SELECT f.*,t.submitted_at FROM formal_exams f JOIN task_sets t ON t.id=f.set_id WHERE f.set_id=?',(set_id,)).fetchone()
    if not row: raise HTTPException(404,"测试不存在。")
    snapshot=json.loads(row['snapshot_json']);draft=conn.execute('SELECT * FROM exam_drafts WHERE set_id=?',(set_id,)).fetchone()
    result=exam_result(conn,row)
    return {'set_id':set_id,'learner_id':row['learner_id'],'course_version_id':row['course_version_id'],'kind':row['kind'],'grade':row['grade'],'deadline':row['deadline'],'server_now':time.time(),'submitted':row['submitted_at'] is not None,'draft':json.loads(draft['answers_json']) if draft else {},'draft_revision':draft['revision'] if draft else 0,'items':[{'id':i['id'],'prompt':i['public']['prompt'],'choices':json.loads(i['public']['choices_json']) if i['public'].get('choices_json') else None,'figure_url':'/api/edu/figures/'+i['public']['figure_spec_id'] if i['public'].get('figure_spec_id') else None,'points':i['points']} for i in snapshot['items']],'minutes':snapshot['minutes'],'result':result,'integrity':integrity.status(conn,set_id)}


def save_draft(conn,set_id,answers,revision,*,page_session=None):
    with transaction(conn):
        integrity.inspect(conn,set_id,page_session)
        if integrity.invalid_result(conn,set_id): return integrity.report(conn,set_id)
        row=conn.execute('SELECT f.*,t.submitted_at FROM formal_exams f JOIN task_sets t ON t.id=f.set_id WHERE f.set_id=?',(set_id,)).fetchone()
        if not row or row['submitted_at'] is not None or time.time()>row['deadline']: raise HTTPException(409,"测试已结束，不能继续修改作答。")
        allowed={i['id'] for i in json.loads(row['snapshot_json'])['items']}
        if not set(answers)<=allowed: raise HTTPException(400,"包含未发出的题目。")
        old=conn.execute('SELECT revision FROM exam_drafts WHERE set_id=?',(set_id,)).fetchone()
        if (old[0] if old else 0)!=revision: raise HTTPException(409,"草稿已在另一页面变化，请重新载入。")
        conn.execute('INSERT INTO exam_drafts VALUES(?,?,?,?) ON CONFLICT(set_id) DO UPDATE SET answers_json=excluded.answers_json,revision=excluded.revision,saved_at=excluded.saved_at',(set_id,json.dumps(answers),revision+1,time.time()))
    return {'revision':revision+1,'saved_at':time.time()}


def validate_submission(conn,payload,*,page_session=None):
    """Called INSIDE the durable-submission transaction, including legacy URL."""
    exam=conn.execute('SELECT * FROM formal_exams WHERE set_id=?',(payload.set_id,)).fetchone()
    if not exam: return payload
    integrity.inspect(conn,payload.set_id,page_session)
    if integrity.invalid_result(conn,payload.set_id): return None
    saved=conn.execute('SELECT 1 FROM task_set_submissions WHERE set_id=?',(payload.set_id,)).fetchone()
    if saved: return payload
    snapshot=json.loads(exam['snapshot_json']);repo=AssessmentItemRepository(conn)
    for row in snapshot['items']:
        item=repo.get(row['id'])
        if not item or grading_signature(item)!=row['grading_signature']: raise HTTPException(409,"试题内容发生变化，已暂停该测试，请联系家长。")
    if time.time()>exam['deadline']:
        draft=conn.execute('SELECT answers_json FROM exam_drafts WHERE set_id=?',(payload.set_id,)).fetchone()
        answers=json.loads(draft[0]) if draft else {}
        from deeptutor.education.api.app import SetAnswer
        return payload.model_copy(update={'answers':[SetAnswer(item_id=row['id'],response=answers.get(row['id'],'')) for row in snapshot['items']]})
    return payload


def calculate(conn,set_id):
    exam=conn.execute('SELECT * FROM formal_exams WHERE set_id=?',(set_id,)).fetchone()
    if not exam: return None
    invalid=integrity.invalid_result(conn,set_id)
    if invalid: return invalid
    snapshot=json.loads(exam['snapshot_json']);scores=[];core=defaultdict(lambda:{'count':0,'earned':0.0,'possible':0.0});pending=0;earned=0.0;possible=0.0
    for item in snapshot['items']:
        attempt=conn.execute('SELECT * FROM student_attempts WHERE id=?',(set_id+':'+item['id'],)).fetchone()
        if not attempt: return {'status':'grading','passed':False,'qualified':False}
        judgment=JudgmentRepository(conn).latest_for_attempt(attempt['id'])
        review=conn.execute('SELECT * FROM exam_score_reviews WHERE set_id=? AND item_id=? ORDER BY id DESC LIMIT 1',(set_id,item['id'])).fetchone()
        if review:
            awarded=review['points'];origin='review:'+str(review['id'])
        elif judgment and (judgment.verdict.value in {'partial','needs_review'} or judgment.confidence is not None and judgment.confidence<0.6): awarded=None;origin=judgment.id
        else:
            correct=judgment.verdict.value=='correct' if judgment else attempt['is_correct']
            awarded=None if correct is None else item['points'] if correct else 0
            origin=judgment.id if judgment else attempt['id']
        # Hinted/imitated answers cannot independently establish promotion.
        if attempt['hint_count'] or attempt['evidence_strength'] in {'hinted','imitated','human_reported'}: awarded=None
        pending+=awarded is None;possible+=item['points'];earned+=awarded or 0
        scores.append({'item_id':item['id'],'points':awarded,'maximum':item['points'],'evidence_id':origin})
        if item['core']:
            bucket=core[item['unit_id']];bucket['count']+=1;bucket['earned']+=awarded or 0;bucket['possible']+=item['points']
    core_result={unit:{'count':values['count'],'percent':100*values['earned']/values['possible']} for unit,values in core.items()}
    percent=100*earned/possible
    core_pass=all(core_result.get(unit,{}).get('count',0)>=2 and core_result[unit]['percent']>=80 for unit in snapshot['units'])
    threshold=snapshot['threshold']
    passed=not pending and percent>=threshold and (core_pass or exam['kind'] in {'checkin','daily','competition'})
    result={'status':'awaiting_review' if pending else 'final','percent':round(percent,2),'band':'A' if percent>=90 else 'B' if percent>=80 else 'C' if percent>=60 else 'below_C','passed':bool(passed),'qualified':bool(passed and exam['kind']=='promotion'),'threshold':threshold,'core':core_result,'scores':scores,'pending':pending,'promotion':None}
    return result


def finalize(conn,set_id,*,parent_actor=None,reevaluate=True):
    with transaction(conn):
        result=calculate(conn,set_id)
        if result is None or result.get('status')=='invalidated':return result
        exam=dict(conn.execute('SELECT * FROM formal_exams WHERE set_id=?',(set_id,)).fetchone())
        previous=exam['result_json']
        if parent_actor and exam['kind']!='promotion': raise HTTPException(400,"只有提前晋级需要家长确认。")
        conn.execute('UPDATE formal_exams SET result_json=?,result_revision=result_revision+? WHERE set_id=?',(json.dumps(result),int(previous!=json.dumps(result)),set_id))
        existing=conn.execute('SELECT * FROM promotion_events WHERE set_id=?',(set_id,)).fetchone()
        if existing:
            config=course(conn,exam['course_version_id'],active=False)
            coverage=unit_evidence(conn,exam['learner_id'],config,exam['grade'])
            valid=result['passed'] and (exam['kind']=='competition' or not coverage['missing_core']) and (exam['kind']!='final' or not coverage['missing_units'])
            if exam['kind']=='promotion':
                for grade in range(existing['from_grade'],exam['grade']):
                    valid=valid and any(json.loads(r['result_json']).get('qualified') for r in records(conn,exam['learner_id'],config,grade) if r['kind']=='promotion')
            result['promotion']={'status':'promoted','from_grade':existing['from_grade'],'to_grade':existing['to_grade'],'review_required':not valid}
        elif result.get('status')=='final' and result['passed'] and exam['kind'] in {'final','promotion','competition'}:
            config=course(conn,exam['course_version_id'],active=False);current=placement(conn,exam['learner_id'],config)
            evidence=unit_evidence(conn,exam['learner_id'],config,exam['grade'])
            eligible=(exam['kind']=='competition' or not evidence['missing_core']) and (exam['kind']!='final' or not evidence['missing_units'])
            if exam['kind']=='promotion':
                for grade in range(current['grade'],exam['grade']):
                    eligible=eligible and any(json.loads(r['result_json']).get('qualified') for r in records(conn,exam['learner_id'],config,grade) if r['kind']=='promotion')
            if not eligible: result['promotion']={'status':'coverage_required','missing_units':evidence['missing_units'] if exam['kind']=='final' else [],'missing_core':evidence['missing_core']}
            elif exam['kind']=='promotion' and parent_actor is None: result['promotion']={'status':'parent_confirmation','to_grade':exam['grade']+1}
            elif current['grade']!=exam['placement_grade']: result['promotion']={'status':'placement_changed'}
            else:
                target=exam['grade']+1
                conn.execute('UPDATE subject_placements SET grade=?,revision=revision+1,updated_by=?,updated_at=? WHERE learner_id=? AND subject_key=? AND curriculum_key=?',(target,parent_actor or 'assessment_policy',to_iso_timestamp(time.time()),exam['learner_id'],exam['subject_key'],exam['curriculum_key']))
                conn.execute('INSERT INTO promotion_events(set_id,learner_id,subject_key,curriculum_key,from_grade,to_grade,actor_id,evidence_json,created_at) VALUES(?,?,?,?,?,?,?,?,?)',(set_id,exam['learner_id'],exam['subject_key'],exam['curriculum_key'],current['grade'],target,parent_actor or 'assessment_policy',json.dumps({'result':result,'coverage':evidence}),time.time()))
                result['promotion']={'status':'promoted','from_grade':current['grade'],'to_grade':target}
        if result.get('promotion',{} ) and result['promotion']['status']=='promoted':
            next_courses=conn.execute("SELECT a.course_version_id FROM assessment_courses a JOIN course_versions v ON v.id=a.course_version_id JOIN courses c ON c.id=v.course_id WHERE c.subject_key=? AND a.curriculum_key=? AND a.grade=? AND v.status='active'",(exam['subject_key'],exam['curriculum_key'],result['promotion']['to_grade'])).fetchall()
            result['promotion']['next_course_ready']=len(next_courses)==1
            if len(next_courses)==1:
                stamp=to_iso_timestamp(time.time())
                conn.execute("INSERT INTO enrollments VALUES(?,?,?,?,?) ON CONFLICT(learner_id,course_version_id) DO NOTHING",(exam['learner_id'],next_courses[0][0],'active',stamp,stamp))
        if exam['kind']=='foundation': result['diagnostic_only']=True
        if exam['kind']=='competition' and result.get('promotion',{} ) and result['promotion']['status']=='promoted' and not result['promotion'].get('review_required'):
            result['foundation_followup']=foundation_status(conn,set_id)
        serialized=json.dumps(result)
        conn.execute('UPDATE formal_exams SET result_json=?,result_revision=result_revision+? WHERE set_id=?',(serialized,int(previous!=serialized),set_id))
        # Recompute derived eligibility after reviews without rewriting earned
        # promotion history. Optional foundation results never gate competition.
        if reevaluate and result.get('status')!='grading':
            waiting=conn.execute("SELECT set_id FROM formal_exams WHERE learner_id=? AND subject_key=? AND curriculum_key=? AND grade>=? AND kind IN ('competition','final','promotion') AND set_id!=? AND json_extract(result_json,'$.promotion.status') IN ('coverage_required','promoted','parent_confirmation')",(exam['learner_id'],exam['subject_key'],exam['curriculum_key'],exam['grade'],set_id)).fetchall()
            for row in waiting: finalize(conn,row[0],reevaluate=False)
        return result


def foundation_status(conn,competition_set_id):
    row=conn.execute('SELECT * FROM competition_foundation_choices WHERE competition_set_id=?',(competition_set_id,)).fetchone()
    if row is None: return {'status':'offered','count':35,'minutes':90}
    if row['choice']=='no': return {'status':'declined','count':35,'minutes':90}
    exam=conn.execute('SELECT result_json FROM formal_exams WHERE set_id=?',(row['foundation_set_id'],)).fetchone()
    result=json.loads(exam[0]) if exam and exam[0] else None
    status='invalidated' if result and result.get('status')=='invalidated' else 'completed' if result and result.get('status')=='final' else 'awaiting_review' if result and result.get('status')=='awaiting_review' else 'in_progress'
    return {'status':status,'exam_id':row['foundation_set_id'],'count':35,'minutes':90}


def exam_result(conn,exam):
    result=integrity.invalid_result(conn,exam['set_id']) or (json.loads(exam['result_json']) if exam['result_json'] else None)
    if result and exam['kind']=='competition' and result.get('promotion',{} ) and result['promotion']['status']=='promoted' and not result['promotion'].get('review_required'):
        result['foundation_followup']=foundation_status(conn,exam['set_id'])
    return result


def choose_foundation(conn,set_id,choice,actor,*,judge_available=False,page_session=None):
    """One durable choice per passed competition; starting is atomic with issue."""
    if choice not in {'yes','no'}: raise HTTPException(400,"请选择是否进行基础补测。")
    with transaction(conn):
        source=conn.execute('SELECT * FROM formal_exams WHERE set_id=?',(set_id,)).fetchone()
        result=exam_result(conn,source) if source else None
        if not source or source['kind']!='competition' or not result or not result.get('passed') or result.get('promotion',{}).get('status')!='promoted' or result['promotion'].get('review_required'):
            raise HTTPException(409,"基础补测只能在竞赛通过并晋级后开始。")
        previous=conn.execute('SELECT * FROM competition_foundation_choices WHERE competition_set_id=?',(set_id,)).fetchone()
        if previous:
            if previous['choice']!=choice: raise HTTPException(409,"这次竞赛的补测选择已记录。")
            exam=public_exam(conn,previous['foundation_set_id']) if previous['foundation_set_id'] else None
        else:
            exam=issue(conn,source['learner_id'],source['course_version_id'],'foundation',judge_available=judge_available,competition_set_id=set_id,page_session=page_session) if choice=='yes' else None
            conn.execute('INSERT INTO competition_foundation_choices VALUES(?,?,?,?,?)',(set_id,choice,exam['set_id'] if exam else None,actor,time.time()))
        return {'exam':exam,'foundation_followup':foundation_status(conn,set_id)}
