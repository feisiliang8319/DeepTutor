"use client";
import { useEffect,useState } from "react";
import { education,type Course } from "./education-api";
import { t,useTeachingLocale } from "./teaching-i18n";
import type {Account} from "./api";
export default function StudentCourses({account,onClose}:{account:Account;onClose:()=>void}){
 useTeachingLocale();const [courses,setCourses]=useState<Course[]>([]);const [selected,setSelected]=useState<string[]>([]);const [loaded,setLoaded]=useState(false);const [error,setError]=useState("");const [busy,setBusy]=useState(false);
 useEffect(()=>{education<{courses:Course[];selected:string[]}>(`students/${account.id}/courses`).then(d=>{setCourses(d.courses);setSelected(d.selected);setLoaded(true);}).catch(e=>setError(e.message));},[account.id]);
 async function save(){setBusy(true);setError("");try{await education(`students/${account.id}/courses`,{method:"PUT",headers:{"Content-Type":"application/json"},body:JSON.stringify({course_versions:selected})});onClose();}catch(e){setError((e as Error).message);}finally{setBusy(false);}}
 return <section className="mt-5 rounded-2xl border border-[var(--border)] bg-[var(--card)] p-5"><div className="flex items-center justify-between gap-3"><h3 className="font-semibold">{account.username} · {t("学习课程")}</h3><button onClick={onClose}>{t("关闭")}</button></div><p className="mt-3 text-sm leading-7 text-[var(--muted-foreground)]">{t("选择孩子可以测试的课程。取消课程会保留已有作答记录。")}</p>{error&&<p role="alert" className="mt-4 text-sm text-red-700">{error}</p>}<fieldset disabled={busy||!loaded} className="my-5 space-y-3">{courses.map(c=><label key={c.course_version_id} className="flex items-center gap-3 text-sm"><input type="checkbox" checked={selected.includes(c.course_version_id)} onChange={e=>setSelected(old=>e.target.checked?[...old,c.course_version_id]:old.filter(id=>id!==c.course_version_id))}/>{c.title}</label>)}</fieldset>{loaded&&!courses.length&&<p className="text-sm">{t("暂无已发布的课程")}</p>}<button disabled={busy||!loaded} onClick={save} className="mt-3 rounded-xl bg-[var(--primary)] px-5 py-3 text-sm text-[var(--primary-foreground)]">{busy?t("正在保存…"):t("保存课程")}</button></section>;
}
