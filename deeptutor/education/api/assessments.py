"""Teaching-only formal exams and delegated family learning placement."""
from __future__ import annotations
import json
import time
from typing import Literal
from fastapi import HTTPException, Request
from pydantic import BaseModel, Field, field_validator
from deeptutor.education.application import assessment_engine as engine
from deeptutor.education.application import exam_integrity as integrity
from deeptutor.education.storage.sqlite import transaction


class Blueprint(BaseModel):
    curriculum_key: str = Field(min_length=1,max_length=80,pattern=r'^[a-zA-Z0-9_.-]+$')
    grade: int = Field(ge=1,le=12)
    units: list[str] = Field(min_length=1,max_length=17)
    competition_domain: Literal['mathematics','science','technology','engineering'] | None = None


class ItemTags(BaseModel):
    unit_id: str
    tier: Literal['A','B','C']
    bank: Literal['regular','competition'] = 'regular'
    core: bool = False
    points: int = Field(ge=1,le=100)
    family_key: str = Field(min_length=1,max_length=160)


class SchoolGrade(BaseModel):
    grade: int | None = Field(default=None,ge=1,le=13)


class Placement(BaseModel):
    course_version_id: str
    grade: int = Field(ge=1,le=13)
    school_grade: int | None = Field(default=None,ge=1,le=13)
    entry_level: Literal['foundation','standard','extension'] = 'standard'
    revision: int = Field(ge=0)


class NewExam(BaseModel):
    page_session: str = Field(min_length=32,max_length=128,pattern=r'^[a-zA-Z0-9-]+$')
    rules_accepted: Literal[True]
    learner_id: str
    course_version_id: str
    kind: Literal['checkin','daily','unit','final','promotion','competition']
    unit_id: str | None = None


class FoundationChoice(BaseModel):
    choice: Literal['yes','no']
    page_session: str | None = Field(default=None,min_length=32,max_length=128,pattern=r'^[a-zA-Z0-9-]+$')
    rules_accepted: bool = False


class Presence(BaseModel):
    page_session: str = Field(min_length=32,max_length=128,pattern=r'^[a-zA-Z0-9-]+$')
    reason: Literal['page_hidden','page_left','connection_lost'] | None = None


class Draft(BaseModel):
    answers: dict[str,str] = Field(max_length=35)
    revision: int = Field(ge=0)


class ScoreReview(BaseModel):
    item_id: str
    points: float = Field(ge=0,le=100,allow_inf_nan=False)
    note: str = Field(min_length=10,max_length=4000)

    @field_validator('note')
    @classmethod
    def substantive_note(cls,value):
        if len(value.strip())<10: raise ValueError('Provide at least 10 characters of review rationale')
        return value.strip()


def register(app, *, connect, require_learner, require_enrollment, require_linked_parent, teaching_mode, judge_available):
    def actor(request):
        if not teaching_mode() or not hasattr(request.state,'education_account'):
            raise HTTPException(409,'需要先完成教学账户迁移。')
        return request.state.education_account

    def admin(request):
        user=actor(request)
        if user.role!='admin': raise HTTPException(403,'只有管理员可以配置课程与题库。')
        return user

    def student(conn,learner,request,*,write=False):
        user=actor(request)
        require_learner(conn,learner,request,write=write)
        if user.role=='student':
            from deeptutor.multi_user.teaching_grants import effective
            if 'quiz' not in effective(user.user_id).features: raise HTTPException(403,'Quiz尚未获得授权。')
        return user

    def owned_exam(conn,set_id,request,*,write=False):
        row=conn.execute('SELECT * FROM formal_exams WHERE set_id=?',(set_id,)).fetchone()
        if not row: raise HTTPException(404,'测试不存在。')
        student(conn,row['learner_id'],request,write=write)
        require_enrollment(conn,row['learner_id'],row['course_version_id'])
        return dict(row)

    def linked_exam(conn,set_id,request):
        exam=owned_exam(conn,set_id,request)
        learner=conn.execute('SELECT deep_tutor_user_id FROM learner_profiles WHERE id=?',(exam['learner_id'],)).fetchone()
        require_linked_parent(request,learner[0])
        return exam

    def parent_learner(conn,student_id,request):
        require_linked_parent(request,student_id)
        row=conn.execute('SELECT id FROM learner_profiles WHERE deep_tutor_user_id=?',(student_id,)).fetchone()
        if not row: raise HTTPException(409,'请先为孩子保存学习课程。')
        return row[0]

    @app.get('/api/edu/assessment-admin/courses')
    def blueprints(request:Request):
        admin(request); conn=connect()
        try:
            rows=[dict(r) for r in conn.execute("SELECT v.id AS course_version_id,c.title,c.subject_key,a.curriculum_key,a.grade,a.units_json,a.competition_domain FROM course_versions v JOIN courses c ON c.id=v.course_id LEFT JOIN assessment_courses a ON a.course_version_id=v.id WHERE v.status='active' ORDER BY CASE WHEN c.subject_key IN ('mathematics','math') THEN 0 ELSE 1 END,c.title")]
            for row in rows:
                row['units']=json.loads(row.pop('units_json') or '[]')
                row['nodes']=[dict(r) for r in conn.execute('SELECT id,title FROM knowledge_nodes WHERE course_version_id=? ORDER BY sort_order',(row['course_version_id'],))]
            return {'courses':rows}
        finally: conn.close()

    @app.put('/api/edu/assessment-admin/courses/{version}')
    def save_blueprint(version:str,body:Blueprint,request:Request):
        user=admin(request); conn=connect()
        try:
            engine.configure(conn,version,body.curriculum_key,body.grade,body.units,user.user_id,body.competition_domain)
            return {'saved':True}
        finally: conn.close()

    @app.get('/api/edu/assessment-admin/courses/{version}/items')
    def items(version:str,request:Request):
        admin(request);conn=connect()
        try:
            engine.course(conn,version)
            return {'items':[dict(r) for r in conn.execute('SELECT i.id,i.prompt,i.status,i.reviewer,i.reviewed_at,t.unit_id,t.tier,t.bank,t.core,t.points,t.family_key FROM assessment_items i LEFT JOIN assessment_item_tags t ON t.item_id=i.id WHERE i.course_version_id=? ORDER BY i.id',(version,))]}
        finally: conn.close()

    @app.put('/api/edu/assessment-admin/items/{item_id}')
    def classify(item_id:str,body:ItemTags,request:Request):
        admin(request);conn=connect()
        try:
            engine.tag_item(conn,item_id,body.model_dump());return {'saved':True}
        finally:conn.close()

    @app.get('/api/edu/students/{student_id}/learning-plan')
    def learning_plan(student_id:str,request:Request):
        conn=connect()
        try:
            learner=parent_learner(conn,student_id,request)
            background=conn.execute('SELECT school_grade FROM academic_background WHERE learner_id=?',(learner,)).fetchone()
            courses=[dict(r) for r in conn.execute("SELECT a.*,c.title,c.subject_key,p.grade AS learning_grade,p.entry_level,p.revision FROM enrollments e JOIN assessment_courses a ON a.course_version_id=e.course_version_id JOIN course_versions v ON v.id=a.course_version_id JOIN courses c ON c.id=v.course_id LEFT JOIN subject_placements p ON p.learner_id=e.learner_id AND p.subject_key=c.subject_key AND p.curriculum_key=a.curriculum_key WHERE e.learner_id=? AND e.status='active' AND v.status='active' ORDER BY c.subject_key,a.grade",(learner,))]
            for item in courses:
                item['assessed']=conn.execute('SELECT 1 FROM formal_exams WHERE learner_id=? AND subject_key=? AND curriculum_key=? LIMIT 1',(learner,item['subject_key'],item['curriculum_key'])).fetchone() is not None
            exams=[dict(r) for r in conn.execute('SELECT set_id,kind,subject_key,curriculum_key,grade,result_json FROM formal_exams WHERE learner_id=? AND result_json IS NOT NULL ORDER BY deadline DESC LIMIT 50',(learner,))]
            for exam in exams:
                exam['result']=engine.exam_result(conn,exam)
                exam.pop('result_json')
            return {'learner_id':learner,'school_grade':background[0] if background else None,'courses':courses,'exams':exams}
        finally:conn.close()

    @app.put('/api/edu/students/{student_id}/school-grade')
    def save_school_grade(student_id:str,body:SchoolGrade,request:Request):
        conn=connect()
        try:
            learner=parent_learner(conn,student_id,request)
            from deeptutor.education.application import to_iso_timestamp
            with transaction(conn):
                conn.execute('INSERT INTO academic_background VALUES(?,?,?,?) ON CONFLICT(learner_id) DO UPDATE SET school_grade=excluded.school_grade,updated_by=excluded.updated_by,updated_at=excluded.updated_at',(learner,body.grade,actor(request).user_id,to_iso_timestamp(time.time())))
            return {'saved':True}
        finally:conn.close()

    @app.put('/api/edu/students/{student_id}/learning-plan')
    def save_plan(student_id:str,body:Placement,request:Request):
        conn=connect()
        try:
            learner=parent_learner(conn,student_id,request)
            require_enrollment(conn,learner,body.course_version_id)
            config=engine.course(conn,body.course_version_id)
            # Initial placement must name a published, assigned grade.
            current=conn.execute('SELECT grade FROM subject_placements WHERE learner_id=? AND subject_key=? AND curriculum_key=?',(learner,config['subject_key'],config['curriculum_key'])).fetchone()
            if body.grade!=config['grade'] and (current is None or body.grade!=current['grade']): raise HTTPException(400,'请选择对应年级的课程后设置学习起点。')
            engine.set_placement(conn,learner,config,body.grade,body.entry_level,body.school_grade,actor(request).user_id,body.revision)
            return {'saved':True}
        finally:conn.close()

    @app.get('/api/edu/assessments/catalog')
    def catalog(learner_id:str,request:Request):
        conn=connect()
        try:
            student(conn,learner_id,request)
            rows=[dict(r) for r in conn.execute("SELECT a.*,c.title,c.subject_key,p.grade AS learning_grade,p.entry_level FROM enrollments e JOIN assessment_courses a ON a.course_version_id=e.course_version_id JOIN course_versions v ON v.id=a.course_version_id JOIN courses c ON c.id=v.course_id LEFT JOIN subject_placements p ON p.learner_id=e.learner_id AND p.subject_key=c.subject_key AND p.curriculum_key=a.curriculum_key WHERE e.learner_id=? AND e.status='active' AND v.status='active' ORDER BY c.subject_key,a.grade",(learner_id,))]
            for row in rows:
                ids=json.loads(row.pop('units_json'));row['units']=[dict(r) for r in conn.execute('SELECT id,title FROM knowledge_nodes WHERE id IN ('+','.join('?' for _ in ids)+') ORDER BY sort_order',ids)]
                row['coverage']=engine.unit_evidence(conn,learner_id,{**row,'units_json':json.dumps(ids)},row['grade'])
                row['modes']=['checkin','daily','unit','final','promotion']+(['competition'] if row['subject_key'].casefold() in engine.STEM_SUBJECTS.get(row['competition_domain'],set()) else [])
            return {'courses':rows,'specs':engine.SPECS}
        finally:conn.close()

    @app.get('/api/edu/assessments/active')
    def active_exam(learner_id:str,request:Request):
        conn=connect()
        try:
            student(conn,learner_id,request)
            row=conn.execute("SELECT f.set_id FROM formal_exams f JOIN task_sets t ON t.id=f.set_id WHERE f.learner_id=? AND t.skipped_at IS NULL AND (t.submitted_at IS NULL OR f.result_json IS NULL OR json_extract(f.result_json,'$.status')='grading') ORDER BY f.deadline LIMIT 1",(learner_id,)).fetchone()
            if row is None:
                # Keep an unanswered optional choice reachable after refresh.
                row=conn.execute("SELECT f.set_id FROM formal_exams f JOIN promotion_events p ON p.set_id=f.set_id WHERE f.learner_id=? AND f.kind='competition' AND json_extract(f.result_json,'$.passed')=1 AND COALESCE(json_extract(f.result_json,'$.promotion.review_required'),0)=0 AND NOT EXISTS(SELECT 1 FROM competition_foundation_choices c WHERE c.competition_set_id=f.set_id) ORDER BY f.deadline DESC LIMIT 1",(learner_id,)).fetchone()
            if row is None:
                row=conn.execute("SELECT f.set_id FROM formal_exams f JOIN exam_integrity i ON i.set_id=f.set_id WHERE f.learner_id=? AND i.state='invalidated' AND i.retake_authorized_at IS NULL ORDER BY f.deadline DESC LIMIT 1",(learner_id,)).fetchone()
            if row:
                owned_exam(conn,row[0],request)
                if actor(request).role=='student': integrity.inspect(conn,row[0],request.headers.get('x-quiz-session'))
            legacy=None
            if row is None:
                old=conn.execute("SELECT t.id AS set_id,t.learner_id,t.course_version_id,t.submitted_at FROM task_sets t JOIN enrollments e ON e.learner_id=t.learner_id AND e.course_version_id=t.course_version_id WHERE t.learner_id=? AND e.status='active' AND t.skipped_at IS NULL AND (t.submitted_at IS NULL OR EXISTS(SELECT 1 FROM task_set_submissions s,json_each(t.item_ids_json) j WHERE s.set_id=t.id AND NOT EXISTS(SELECT 1 FROM student_attempts a WHERE a.id=t.id || ':' || j.value))) AND NOT EXISTS(SELECT 1 FROM formal_exams f WHERE f.set_id=t.id) ORDER BY t.issued_at LIMIT 1",(learner_id,)).fetchone()
                legacy=dict(old) if old else None
            return {'exam':engine.public_exam(conn,row[0]) if row else None,'legacy_task':legacy}
        finally:conn.close()

    @app.post('/api/edu/assessments')
    def new_exam(body:NewExam,request:Request):
        conn=connect()
        try:
            student(conn,body.learner_id,request,write=True);require_enrollment(conn,body.learner_id,body.course_version_id)
            return engine.issue(conn,body.learner_id,body.course_version_id,body.kind,body.unit_id,judge_available=judge_available,page_session=body.page_session)
        finally:conn.close()

    @app.get('/api/edu/assessments/{set_id}')
    def get_exam(set_id:str,request:Request):
        conn=connect()
        try:
            owned_exam(conn,set_id,request)
            if actor(request).role=='student': integrity.inspect(conn,set_id,request.headers.get('x-quiz-session'))
            return engine.public_exam(conn,set_id)
        finally:conn.close()

    @app.put('/api/edu/assessments/{set_id}/draft')
    def draft(set_id:str,body:Draft,request:Request):
        if any(len(k)>200 or len(v)>20000 for k,v in body.answers.items()): raise HTTPException(400,'作答内容过长。')
        conn=connect()
        try: owned_exam(conn,set_id,request,write=True);return engine.save_draft(conn,set_id,body.answers,body.revision,page_session=request.headers.get('x-quiz-session'))
        finally:conn.close()

    @app.post('/api/edu/assessments/{set_id}/presence')
    def presence(set_id:str,body:Presence,request:Request):
        conn=connect()
        try:
            owned_exam(conn,set_id,request,write=True)
            integrity.inspect(conn,set_id,body.page_session,reason=body.reason,heartbeat=body.reason is None)
            return engine.public_exam(conn,set_id)
        finally:conn.close()

    @app.post('/api/edu/assessments/{set_id}/allow-retake')
    def allow_retake(set_id:str,request:Request):
        conn=connect()
        try:
            linked_exam(conn,set_id,request)
            return integrity.allow_retake(conn,set_id,actor(request).user_id)
        finally:conn.close()

    @app.post('/api/edu/assessments/{set_id}/confirm-promotion')
    def confirm(set_id:str,request:Request):
        conn=connect()
        try:
            exam=linked_exam(conn,set_id,request)
            if exam['kind']!='promotion': raise HTTPException(400,'这不是提前晋级测试。')
            result=engine.finalize(conn,set_id,parent_actor=actor(request).user_id)
            if not result or not result.get('passed'): raise HTTPException(409,'尚未达到提前晋级标准。')
            return result
        finally:conn.close()

    @app.post('/api/edu/assessments/{set_id}/foundation-choice')
    def foundation_choice(set_id:str,body:FoundationChoice,request:Request):
        conn=connect()
        try:
            owned_exam(conn,set_id,request,write=True)
            if body.choice=='yes' and (not body.page_session or not body.rules_accepted): raise HTTPException(400,'开始补测前，请确认独立测试规则。')
            result=engine.choose_foundation(conn,set_id,body.choice,actor(request).user_id,judge_available=judge_available,page_session=body.page_session)
            if result['exam']:
                integrity.inspect(conn,result['exam']['set_id'],body.page_session)
                result['exam']=engine.public_exam(conn,result['exam']['set_id'])
            return result
        finally:conn.close()

    @app.get('/api/edu/assessments/{set_id}/review')
    def review_items(set_id:str,request:Request):
        conn=connect()
        try:
            exam=linked_exam(conn,set_id,request)
            if not conn.execute('SELECT 1 FROM task_set_submissions WHERE set_id=?',(set_id,)).fetchone(): raise HTTPException(409,'学生尚未提交测试。')
            snapshot=json.loads(exam['snapshot_json'])
            result=[]
            for item in snapshot['items']:
                row=conn.execute('SELECT a.response,i.prompt,i.expected_answer,i.rubric_json FROM student_attempts a JOIN assessment_items i ON i.id=a.assessment_item_id WHERE a.id=?',(set_id+':'+item['id'],)).fetchone()
                if row: result.append({**dict(row),'item_id':item['id'],'maximum':item['points']})
            return {'items':result}
        finally:conn.close()

    @app.post('/api/edu/assessments/{set_id}/review')
    def score_review(set_id:str,body:ScoreReview,request:Request):
        conn=connect()
        try:
            exam=linked_exam(conn,set_id,request); user=actor(request)
            item=next((i for i in json.loads(exam['snapshot_json'])['items'] if i['id']==body.item_id),None)
            if not item or body.points>item['points']: raise HTTPException(400,'分值超出该题上限。')
            attempt_id=set_id+':'+body.item_id
            if not conn.execute('SELECT 1 FROM student_attempts WHERE id=?',(attempt_id,)).fetchone(): raise HTTPException(409,'该题尚未提交或正在判分。')
            from deeptutor.education.application.rebuild_mastery import append_human_judgment_and_recompute
            from deeptutor.education.domain.evidence import Verdict
            with transaction(conn):
                append_human_judgment_and_recompute(conn,attempt_id=attempt_id,judge_ref=user.user_id,verdict=Verdict.CORRECT if body.points==item['points'] else Verdict.INCORRECT if body.points==0 else Verdict.PARTIAL,confidence=1.0,rationale=body.note)
                conn.execute('INSERT INTO exam_score_reviews(set_id,item_id,points,note,reviewer_id,created_at) VALUES(?,?,?,?,?,?)',(set_id,body.item_id,body.points,body.note,user.user_id,time.time()))
                result=engine.finalize(conn,set_id)
            from deeptutor.education.application.quiz_chat import handoff_review
            # Review is durable; retrying this delivery uses the existing endpoint.
            try: delivery={'chat_handoff':handoff_review(conn,attempt_id)}
            except (ValueError,RuntimeError,OSError) as exc: delivery={'chat_handoff_error':str(exc)}
            return {'assessment':result,**delivery}
        finally:conn.close()
