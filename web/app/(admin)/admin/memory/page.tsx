"use client";
import {useEffect,useState} from "react";
import LearningEvidence from "@/components/teaching/LearningEvidence";
import {teachingApi,type Account} from "@/components/teaching/api";
import {t,useTeachingLocale} from "@/components/teaching/teaching-i18n";
export default function TeachingMemory(){
 useTeachingLocale();const [students,setStudents]=useState<Account[]>([]);const [selected,setSelected]=useState("");const [error,setError]=useState("");
 useEffect(()=>{teachingApi<{students:Account[]}>("/api/v1/teaching/students").then(d=>{setStudents(d.students);setSelected(d.students[0]?.id||"");}).catch(e=>setError(e.message));},[]);
 return <div className="h-full overflow-auto"><main className="mx-auto max-w-4xl px-6 py-10"><h1 className="text-3xl font-semibold">{t("学习证据与记忆")}</h1><p className="mt-4 text-sm leading-7 text-[var(--muted-foreground)]">{t("查看可追溯的学习状态，保留原始作答。")}</p>{error&&<p role="alert" className="mt-5 text-sm">{error}</p>}<label htmlFor="evidence-student" className="mb-3 mt-8 block text-sm">{t("学生记录")}</label><select id="evidence-student" value={selected} onChange={e=>setSelected(e.target.value)} className="w-full max-w-sm border p-3">{students.map(s=><option key={s.id} value={s.id}>{s.username}</option>)}</select><LearningEvidence studentId={selected}/></main></div>;
}
