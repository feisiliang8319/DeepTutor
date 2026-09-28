"use client";
import { useEffect,useState,type ReactNode } from 'react';
import { ChevronDown, ArrowUpRight } from 'lucide-react';
import Link from 'next/link';
import { education } from './education-api';
import { t,useTeachingLocale } from './teaching-i18n';
import { modeNames,promotionText,foundationText,type AssessmentResult } from './assessment-types';
import MarkdownRenderer from '@/components/common/MarkdownRenderer';
type Course={course_version_id:string;title:string;subject_key:string;curriculum_key:string;grade:number;learning_grade:number|null;entry_level:string|null;revision:number|null;assessed:boolean};
type RecordRow={set_id:string;kind:string;subject_key:string;grade:number;result:AssessmentResult};
type Plan={school_grade:number|null;courses:Course[];exams:RecordRow[]};
const primary='rounded-xl bg-[var(--primary)] px-4 py-2.5 text-sm text-[var(--primary-foreground)] disabled:opacity-40';
function PlacementForm({studentId,courses,school,onSave}:{studentId:string;courses:Course[];school:number|null;onSave:()=>Promise<void>}){
 const current=courses.find(c=>c.grade===c.learning_grade)||courses[0];
 const [version,setVersion]=useState(current.course_version_id),[level,setLevel]=useState(current.entry_level||'standard');
 const [busy,setBusy]=useState(false),[error,setError]=useState('');
 const selected=courses.find(c=>c.course_version_id===version)!;
 async function save(){setBusy(true);setError('');try{await education(`students/${studentId}/learning-plan`,{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({course_version_id:version,grade:selected.assessed?selected.learning_grade:selected.grade,school_grade:school,entry_level:level,revision:selected.revision||0})});await onSave();}catch(e){setError((e as Error).message);}finally{setBusy(false);}}
 return <form onSubmit={e=>{e.preventDefault();void save();}} className="space-y-4 rounded-2xl border border-[var(--border)] bg-[var(--card)] p-5"><h3 className="font-semibold">{current.title}</h3><p className="text-xs text-[var(--muted-foreground)]">{current.curriculum_key} · {current.learning_grade?t('当前学科学习年级：{{grade}}',{grade:current.learning_grade}):t('尚未设置学习起点')}</p><fieldset disabled={busy} className="grid gap-4 sm:grid-cols-2"><label className="text-sm">{t('学科学习起点')}<select disabled={current.assessed} value={version} onChange={e=>setVersion(e.target.value)} className="mt-2 w-full border p-3">{courses.map(c=><option key={c.course_version_id} value={c.course_version_id}>{t('{{grade}} 年级',{grade:current.assessed?current.learning_grade:c.grade})} · {c.title}</option>)}</select></label><label className="text-sm sm:col-span-2">{t('当前学习准备')}<select value={level} onChange={e=>setLevel(e.target.value)} className="mt-2 w-full border p-3"><option value="foundation">{t('需要巩固基础')}</option><option value="standard">{t('跟随本年级学习')}</option><option value="extension">{t('准备深入拓展')}</option></select></label></fieldset><p className="text-xs leading-6 text-[var(--muted-foreground)]">{t('起点用于安排教学，不代表已经掌握。正式测试后，年级变化由晋级证据决定。')}</p>{error&&<p role="alert" className="text-sm text-red-700">{error}</p>}<button disabled={busy} className={primary}>{busy?t('正在保存…'):t('保存学习安排')}</button></form>;
}
function ScoreReview({setId,onSave}:{setId:string;onSave:()=>Promise<void>}){
 const [items,setItems]=useState<Array<{item_id:string;prompt:string;response:string;expected_answer:string;rubric_json:string|null;maximum:number}>>([]),[selected,setSelected]=useState(''),[points,setPoints]=useState(''),[note,setNote]=useState(''),[error,setError]=useState(''),[busy,setBusy]=useState(false);
 useEffect(()=>{education<{items:typeof items}>(`assessments/${setId}/review`).then(d=>{setItems(d.items);setSelected(d.items[0]?.item_id||'');}).catch(e=>setError(e.message));},[setId]);
 const item=items.find(i=>i.item_id===selected);
 async function save(){setBusy(true);setError('');try{const data=await education<{chat_handoff_error?:string}>(`assessments/${setId}/review`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({item_id:selected,points:Number(points),note})});if(data.chat_handoff_error)setError(t('评分已保存，讲解同步尚未完成。'));await onSave();setNote('');setPoints('');}catch(e){setError((e as Error).message);}finally{setBusy(false);}}
 return <form className="mt-5 space-y-4 border-t border-[var(--border)] pt-5" onSubmit={e=>{e.preventDefault();void save();}}><label className="block text-sm">{t('复核题目')}<select className="mt-2 w-full border p-3" value={selected} onChange={e=>{setSelected(e.target.value);setPoints('');setNote('');}}>{items.map((i,n)=><option key={i.item_id} value={i.item_id}>{t('第 {{value0}} 题',{value0:n+1})}</option>)}</select></label>{item&&<><MarkdownRenderer content={item.prompt}/><p className="whitespace-pre-wrap text-sm">{t('你的作答：')}{item.response||'—'}</p><p className="text-sm">{t('参考答案：')}{item.expected_answer}</p>{item.rubric_json&&<details className="text-sm"><summary>{t('评分依据')}</summary><pre className="mt-3 whitespace-pre-wrap break-words">{item.rubric_json}</pre></details>}<label className="block text-sm">{t('本题得分')} / {item.maximum}<input required type="number" step="0.01" min={0} max={item.maximum} value={points} onChange={e=>setPoints(e.target.value)} className="ml-3 w-24 border p-2"/></label><label className="block text-sm">{t('复核依据与反馈')}<textarea required minLength={10} maxLength={4000} rows={3} value={note} onChange={e=>setNote(e.target.value)} className="mt-2 w-full border p-3"/></label><button disabled={busy||!points||note.trim().length<10} className={primary}>{t('保存分值复核')}</button></>}{error&&<p role="alert" className="text-sm text-red-700">{error}</p>}</form>;
}
function SchoolGradeForm({studentId,grade,onSave}:{studentId:string;grade:number|null;onSave:()=>Promise<void>}){
 const [value,setValue]=useState(grade?.toString()||''),[busy,setBusy]=useState(false),[error,setError]=useState('');
 useEffect(()=>setValue(grade?.toString()||''),[grade]);
 async function save(){setBusy(true);setError('');try{await education(`students/${studentId}/school-grade`,{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({grade:value?Number(value):null})});await onSave();}catch(e){setError((e as Error).message);}finally{setBusy(false);}}
 return <form className="my-5 flex flex-wrap items-end gap-3" onSubmit={e=>{e.preventDefault();void save();}}><label className="text-sm">{t('学校在读年级')}<select disabled={busy} value={value} onChange={e=>setValue(e.target.value)} className="mt-2 block min-w-44 border p-3"><option value="">{t('暂不填写')}</option>{Array.from({length:13},(_,i)=><option key={i+1} value={i+1}>{t('{{grade}} 年级',{grade:i+1})}</option>)}</select></label><button disabled={busy} className="rounded-xl border border-[var(--border)] px-4 py-3 text-sm">{t('保存学校年级')}</button>{error&&<p role="alert" className="text-sm text-red-700">{error}</p>}</form>;
}
export default function LearningPlan({studentId,goalEditor,children}:{studentId:string;goalEditor?:ReactNode;children?:ReactNode}){
 useTeachingLocale();
 const [data,setData]=useState<Plan|null>(null),[error,setError]=useState(''),[review,setReview]=useState(''),[busy,setBusy]=useState(false),[saved,setSaved]=useState(false);
 async function load(){setData(await education<Plan>(`students/${studentId}/learning-plan`));}
 useEffect(()=>{let live=true;setData(null);setReview('');setSaved(false);setError('');education<Plan>(`students/${studentId}/learning-plan`).then(d=>{if(live)setData(d);}).catch(e=>{if(live)setError(e.message);});return()=>{live=false;};},[studentId]);
 async function refreshed(){await load();setSaved(true);}
 async function confirm(setId:string){setBusy(true);setError('');try{await education(`assessments/${setId}/confirm-promotion`,{method:'POST'});await load();}catch(e){setError((e as Error).message);}finally{setBusy(false);}}
 const groups=new Map<string,Course[]>();
 data?.courses.forEach(c=>{const key=c.subject_key+':'+c.curriculum_key;groups.set(key,[...(groups.get(key)||[]),c]);});
 const names=modeNames();
 const pending=data?.exams.filter(exam=>exam.result.promotion?.status==='parent_confirmation')||[];
 return <>
   <section aria-labelledby="subject-progress">
     <div className="flex flex-wrap items-baseline justify-between gap-3">
       <h2 id="subject-progress" className="text-xl font-semibold">{t('学科学习进展')}</h2>
       {data?.school_grade&&<p className="text-sm text-[var(--muted-foreground)]">{t('学校在读年级')} · {t('{{grade}} 年级',{grade:data.school_grade})}</p>}
     </div>
     <p className="mt-2 text-sm leading-7 text-[var(--muted-foreground)]">{t('每个学科独立学习、测试和晋级。')}</p>
     {error&&<div role="alert" className="mt-4 rounded-xl border border-[var(--border)] p-4 text-sm"><p>{error}</p><div className="mt-3 flex gap-5"><button onClick={()=>{setError('');void load().catch(e=>setError((e as Error).message));}} className="underline">{t('重试')}</button><Link href="/parent/students" className="text-[var(--primary)] underline">{t('学生账号')}</Link></div></div>}
     {!data&&!error&&<p role="status" className="py-6 text-sm">{t('正在读取…')}</p>}
     {data&&<div className="mt-5 divide-y divide-[var(--border)] rounded-2xl bg-[var(--secondary)] px-5">
       {Array.from(groups,([key,courses])=>{const current=courses.find(c=>c.grade===c.learning_grade)||courses[0];return <div key={key} className="flex flex-wrap items-center justify-between gap-3 py-5">
         <div className="min-w-0"><h3 className="break-words font-medium">{current.title}</h3><p className="mt-1 text-xs text-[var(--muted-foreground)]">{t('当前学习年级')}</p></div>
         <p className="text-lg font-semibold text-[var(--primary)]">{current.learning_grade?t('{{grade}} 年级',{grade:current.learning_grade}):t('尚未设置学习起点')}</p>
       </div>;})}
       {!groups.size&&<div className="py-5"><p className="text-sm leading-7">{t('请先在学生账号中分配课程；课程正式考核范围由管理员准备。')}</p><Link href="/parent/students" className="mt-2 inline-flex items-center gap-1 text-sm text-[var(--primary)] underline">{t('学生账号')}<ArrowUpRight size={14} aria-hidden="true"/></Link></div>}
     </div>}
   </section>
   {pending.length>0&&<aside aria-label={t('待确认晋级')} className="mt-6 rounded-xl border border-[var(--primary)] p-5">
     <h2 className="font-semibold">{t('待确认晋级')}</h2><p className="mt-2 text-sm leading-7 text-[var(--muted-foreground)]">{t('孩子已达到提前晋级要求，请在下方考核记录中确认。')}</p>
   </aside>}
   {children}
   {data&&<section className="my-8" aria-labelledby="assessment-history">
     <h2 id="assessment-history" className="text-lg font-semibold">{t('学科考核与晋级记录')}</h2>
     {!data.exams.length?<p className="mt-4 text-sm text-[var(--muted-foreground)]">{t('完成测试后，这里会显示成绩与晋级进展。')}</p>:<div className="mt-4 space-y-3">{data.exams.map(exam=><details key={exam.set_id} open={exam.result.promotion?.status==='parent_confirmation'?true:undefined} className="rounded-xl border border-[var(--border)] bg-[var(--card)] p-4">
       <summary className="cursor-pointer text-sm leading-7">{exam.subject_key} · {t('{{grade}} 年级',{grade:exam.grade})} · {names[exam.kind as keyof typeof names]} · {exam.result.percent??'—'}/100</summary>
       <p className="mt-3 text-sm leading-7">{promotionText(exam.result)}</p>
       {exam.result.foundation_followup&&<p className="mt-2 text-sm leading-7 text-[var(--muted-foreground)]">{foundationText(exam.result.foundation_followup)}</p>}
       {exam.result.promotion?.status==='parent_confirmation'&&<button onClick={()=>confirm(exam.set_id)} disabled={busy} className={primary}>{t('确认本学科升至 {{grade}} 年级',{grade:exam.result.promotion.to_grade})}</button>}
       <button onClick={()=>setReview(review===exam.set_id?'':exam.set_id)} className="mt-3 block text-sm underline">{t('查看与复核评分')}</button>
       {review===exam.set_id&&<ScoreReview setId={exam.set_id} onSave={load}/>}
     </details>)}</div>}
   </section>}
   <details className="group mt-8 rounded-2xl border border-[var(--border)] p-5">
     <summary className="flex cursor-pointer list-none items-center justify-between gap-3 [&::-webkit-details-marker]:hidden">
       <span><span className="block font-medium">{t('学习安排')}</span><span className="mt-1 block text-xs leading-6 text-[var(--muted-foreground)]">{t('目标、学校年级与各学科学习起点')}</span></span>
       <ChevronDown size={18} aria-hidden="true" className="shrink-0 transition-transform group-open:rotate-180 motion-reduce:transition-none"/>
     </summary>
     {goalEditor}
     <p className="mt-5 text-sm leading-7 text-[var(--muted-foreground)]">{t('学校年级与学科学习年级分别记录。每个学科独立测试和晋级。')}</p>
     {saved&&<p role="status" className="mt-4 text-sm">{t('学习安排已保存。')}</p>}
     {data&&<SchoolGradeForm studentId={studentId} grade={data.school_grade} onSave={refreshed}/>}
     <div className="mt-5 space-y-4">{Array.from(groups,([key,courses])=><PlacementForm key={studentId+key+courses[0].revision} studentId={studentId} courses={courses} school={data?.school_grade??null} onSave={refreshed}/>)}</div>
   </details>
 </>;
}
