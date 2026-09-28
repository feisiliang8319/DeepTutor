"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { ArrowDownToLine, ArrowUpRight, BookOpen, CheckCheck, FileInput, Loader2 } from "lucide-react";
import { education } from "./education-api";
import { t, useTeachingLocale } from "./teaching-i18n";
import MaterialScopes from "./MaterialScopes";

type Node = {id:string;code:string;title:string};
type Course = {id:string;title:string;level:string;subject_key:string;total:number;candidate:number;published:number;quiz_ready:number;covered_nodes:number;blueprint:boolean;nodes:Node[];issues:Record<string,number>};
type Receipt = {id:string;source_name:string;inserted:number;skipped:number;needs_review:number;errors:Array<{row:number;message:string}>;issues:Record<string,number>;replayed?:boolean};
type Catalog = {courses:Course[];issue_labels:Record<string,string>;imports:Receipt[]};
type Item = {id:string;prompt:string;expected_answer:string;explanation:string;source_ref:string;license_note:string;attribution_text:string;status:string;revision:string;issues:string[]};
const button = "inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-xl border border-[var(--border)] px-4 py-3 text-sm disabled:opacity-50";
const primary = `${button} bg-[var(--primary)] text-[var(--primary-foreground)]`;
const post = (body:unknown) => ({method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(body)});

export default function ContentWorkbench() {
  useTeachingLocale();
  const [tab,setTab]=useState("courses"),[data,setData]=useState<Catalog|null>(null),[version,setVersion]=useState("");
  const [error,setError]=useState(""),[busy,setBusy]=useState(false),[message,setMessage]=useState("");
  const [payload,setPayload]=useState<Record<string,unknown>|null>(null),[receipt,setReceipt]=useState<Receipt|null>(null),[imported,setImported]=useState(false);
  const [items,setItems]=useState<Item[]>([]),[page,setPage]=useState(0),[total,setTotal]=useState(0),[itemsLoading,setItemsLoading]=useState(false);
  const [selected,setSelected]=useState<Item|null>(null),[note,setNote]=useState("");
  const course=data?.courses.find(c=>c.id===version);
  async function refresh(){const value=await education<Catalog>("content-admin/catalog");setData(value);setVersion(old=>old||value.courses[0]?.id||"");}
  useEffect(()=>{refresh().catch(e=>setError(e.message));},[]);
  useEffect(()=>{
    let cancelled=false;
    if(!version||tab!=="questions")return;
    setItemsLoading(true);setSelected(null);
    education<{items:Item[];total:number}>(`content-admin/courses/${encodeURIComponent(version)}/items?page=${page}`).then(value=>{if(!cancelled){setItems(value.items);setTotal(value.total);}}).catch(e=>{if(!cancelled)setError(e.message);}).finally(()=>{if(!cancelled)setItemsLoading(false);});
    return()=>{cancelled=true;};
  },[tab,version,page,message]);
  function selectVersion(value:string){setVersion(value);setPage(0);setPayload(null);setReceipt(null);setImported(false);setSelected(null);}
  async function run(action:()=>Promise<void>){setBusy(true);setError("");try{await action();}catch(e){setError((e as Error).message);}finally{setBusy(false);}}
  async function loadFile(file:File|undefined){if(!file)return;await run(async()=>{
    setPayload(null);setReceipt(null);setImported(false);
    if(file.size>4*1024*1024)throw new Error(t("课包不得超过4 MiB。"));
    let value;
    try{value=JSON.parse(await file.text());}
    catch{throw new Error(t("文件不是有效的JSON，请检查格式后重试。"));}
    if(!value||typeof value!=="object"||Array.isArray(value))throw new Error(t("请选择包含items数组的题库JSON。"));
    const pack={...value,course_version_id:version,source_name:file.name};
    const preview=await education<Receipt>("content-admin/import/preview",post(pack));setPayload(pack);setReceipt(preview);
  });}
  async function loadStarter(){await run(async()=>{
    setPayload(null);setReceipt(null);setImported(false);
    const pack=await education<Record<string,unknown>>(`content-admin/starter?course_version_id=${encodeURIComponent(version)}`);
    const preview=await education<Receipt>("content-admin/import/preview",post(pack));setPayload(pack);setReceipt(preview);
  });}
  async function ingest(){if(!payload)return;await run(async()=>{
    const result=await education<Receipt>("content-admin/import",post(payload));setReceipt(result);setImported(true);await refresh();setMessage(t(result.replayed?"已返回原导入回执，本次没有重复新增。":"导入完成，题目已进入待审区。"));
  });}
  async function review(decision:"publish"|"retire"){if(!selected)return;await run(async()=>{
    await education(`content-admin/items/${encodeURIComponent(selected.id)}/review`,post({revision:selected.revision,decision,note}));
    setSelected(null);setNote("");await refresh();setMessage(`${t("审核记录已保存。")} ${new Date().toLocaleTimeString()}`);
  });}
  const summaryCourses=tab!=="courses"&&course?[course]:data?.courses;
  const totals=summaryCourses?.reduce((a,c)=>({candidate:a.candidate+c.candidate,ready:a.ready+c.quiz_ready,total:a.total+c.total}),{candidate:0,ready:0,total:0});
  return <div className="h-full overflow-auto"><div className="mx-auto max-w-6xl px-5 py-8 md:px-10 md:py-12">
    <div className="flex flex-wrap items-start justify-between gap-5"><div><p className="mb-3 text-xs tracking-wide text-[var(--primary)]">{t("从资料到学习")}</p><h1 className="text-3xl font-semibold">{t("课程与知识库")}</h1><p className="mt-4 max-w-2xl text-sm leading-7 text-[var(--muted-foreground)]">{t("整理教材、补齐题库，让每一份资料真正进入教学。")}</p></div><Link href="/knowledge" className={button}><BookOpen size={17}/>{t("教材文件与索引")}<ArrowUpRight size={15}/></Link></div>
    {totals&&<div className="my-7 flex flex-wrap gap-x-10 gap-y-4 border-y border-[var(--border)] py-5" aria-label={t("内容概况")}>{[[totals.total,"已有题目"],[totals.candidate,"待审题目"],[totals.ready,"可供正式抽题"]].map(([value,label])=><div key={label}><span className="mr-3 text-2xl font-semibold tabular-nums">{value}</span><span className="text-sm text-[var(--muted-foreground)]">{t(String(label))}</span></div>)}</div>}
    <nav aria-label={t("内容工作区")} className="mb-7 flex flex-wrap gap-2">{[["courses","课程与教材"],["questions","题库审核"],["intake","资料导入"],["quality","质量与覆盖"]].map(([key,label])=><button key={key} onClick={()=>{setTab(key);setError("");}} aria-pressed={tab===key} className={`${button} ${tab===key?"bg-[var(--secondary)] font-semibold":"border-transparent"}`}>{t(label)}</button>)}</nav>
    {error&&<p role="alert" className="mb-5 rounded-xl border border-[var(--border)] bg-[var(--secondary)] p-4 text-sm">{error}</p>}
    {message&&<p role="status" className="mb-5 text-sm text-[var(--primary)]">{message}</p>}
    {!data&&!error&&<p className="flex items-center gap-2 text-sm"><Loader2 size={17} className="animate-spin"/>{t("正在读取课程内容…")}</p>}
    {data&&!data.courses.length&&<p className="rounded-xl bg-[var(--secondary)] p-6 text-sm">{t("暂无课程目录，请先建立课程与知识点，再导入题目。")}</p>}
    {tab==="courses"&&data&&<div className="divide-y divide-[var(--border)]">{data.courses.map(c=><article key={c.id} className="py-6 first:pt-0"><div className="flex flex-wrap items-start justify-between gap-4"><div><p className="text-xs text-[var(--muted-foreground)]">{c.subject_key} · {c.level}</p><h2 className="mt-2 text-xl font-semibold">{c.title}</h2></div><button className={button} onClick={()=>{selectVersion(c.id);setTab("questions");}}>{t("查看并整理题目")}<ArrowUpRight size={15}/></button></div><p className="mt-4 text-sm leading-7">{t("{{nodes}}个知识点 · {{candidate}}道待审 · {{ready}}道可供正式抽题",{nodes:c.nodes.length,candidate:c.candidate,ready:c.quiz_ready})}</p><p className="mt-2 text-xs text-[var(--muted-foreground)]">{c.blueprint?t("已配置考核范围；能否组卷还需满足覆盖、难度与未见题要求。"):t("尚未配置正式考核范围，不代表已完成全年级课程。")}</p></article>)}</div>}
    {tab!=="courses"&&data?.courses.length!==0&&<label className="mb-6 block max-w-xl text-sm">{t("课程版本")}<select className="mt-2 w-full rounded-xl border border-[var(--border)] bg-[var(--card)] p-3" value={version} disabled={busy} onChange={e=>selectVersion(e.target.value)}>{data?.courses.map(c=><option value={c.id} key={c.id}>{c.title} · {c.level}</option>)}</select></label>}
    {tab==="intake"&&<section className="space-y-6">
      <div className="rounded-2xl bg-[var(--secondary)] p-6"><h2 className="flex items-center gap-2 text-lg font-semibold"><FileInput size={20}/>{t("批量导入题库")}</h2><p className="mt-3 max-w-2xl text-sm leading-7">{t("导入JSON课包，自动校验知识点、来源与重复记录。所有新题先进入待审区，不自动成为正式考题。")}</p><div className="mt-5 flex flex-wrap items-center gap-3"><label className={primary}><ArrowDownToLine size={16}/>{t("选择题库文件")}<input aria-label={t("选择题库文件")} type="file" accept=".json,application/json" className="sr-only" disabled={busy||!version} onChange={e=>{void loadFile(e.target.files?.[0]);e.target.value="";}}/></label><button className={button} disabled={busy||!version} onClick={loadStarter}>{t("载入数与结构首批课包")}</button></div><p className="mt-3 text-xs leading-6 text-[var(--muted-foreground)]">{t("支持现有种子题库格式；单批最多1000题、4 MiB。重复导入不会重复建题。")}</p></div>
      {receipt&&<div className="rounded-xl border border-[var(--border)] p-5" aria-live="polite"><h3 className="font-semibold">{imported?t("导入回执"):t("导入预检")}</h3><p className="mt-3 text-sm">{t("新增{{inserted}}题 · 跳过{{skipped}}题 · {{errors}}项错误",{inserted:receipt.inserted,skipped:receipt.skipped,errors:receipt.errors.length})}</p>{receipt.errors.length>0&&<ul className="mt-4 space-y-2 text-sm">{receipt.errors.map(e=><li key={e.row}>{t("第{{row}}条",{row:e.row})}：{e.message}</li>)}</ul>}{Object.keys(receipt.issues).length>0&&<p className="mt-3 text-xs leading-6">{Object.entries(receipt.issues).map(([key,count])=>`${t(data?.issue_labels[key]||key)} ${count}`).join(" · ")}</p>}<button className={`${primary} mt-5`} disabled={busy||receipt.errors.length>0||imported} onClick={ingest}>{busy?t("正在处理…"):imported?t("已进入待审区"):t("确认导入待审区")}</button></div>}
      <div className="border-t border-[var(--border)] pt-6"><h2 className="font-semibold">{t("教材与扫描资料")}</h2><p className="my-3 text-sm leading-7 text-[var(--muted-foreground)]">{t("PDF、图片与教材文件沿用现有上传和本机解析流程；文字提取完成不等于题目审核通过。")}</p><div className="flex flex-wrap gap-4"><Link href="/knowledge" className="text-sm underline">{t("上传教材与建立索引")}</Link><Link href="/admin/material-intelligence" className="text-sm underline">{t("查看资料分类与质检建议")}</Link></div></div>
      {data&&data.imports.length>0&&<div><h3 className="mb-3 font-semibold">{t("最近导入")}</h3>{data.imports.map(r=><p key={r.id} className="break-words border-t border-[var(--border)] py-3 text-sm">{r.source_name} · {t("新增{{count}}题",{count:r.inserted})}</p>)}</div>}
    </section>}
    {tab==="questions"&&<section><p className="mb-5 text-sm leading-7 text-[var(--muted-foreground)]">{t("逐题核对题干、答案、讲解和来源。发布后仍需配置正式考核分类，系统才会纳入对应抽题范围。")}</p>{itemsLoading?<p>{t("正在读取课程内容…")}</p>:<div className="divide-y divide-[var(--border)]">{items.map(item=><article key={item.id} className="py-5"><div className="flex items-start justify-between gap-4"><p className="min-w-0 flex-1 whitespace-pre-wrap break-words text-sm leading-7">{item.prompt||item.source_ref}</p><button className={button} disabled={busy} onClick={()=>{setSelected(selected?.id===item.id?null:item);setNote("");}}>{t("核对")}</button></div><p className="mt-2 text-xs text-[var(--muted-foreground)]">{t(item.status==="candidate"?"待审核":item.status==="production"?"已发布":"已停用")}{item.issues.length?" · "+item.issues.map(key=>t(data?.issue_labels[key]||key)).join(" · "):""}</p>{selected?.id===item.id&&<div className="mt-4 rounded-xl bg-[var(--secondary)] p-5"><dl className="space-y-4 text-sm leading-7">{[["参考答案",item.expected_answer],["解题讲解",item.explanation],["来源与许可",[item.source_ref,item.license_note,item.attribution_text].filter(Boolean).join("\n")]].map(([label,value])=><div key={label}><dt className="font-semibold">{t(label)}</dt><dd className="mt-1 whitespace-pre-wrap break-words">{value||t("尚未补齐")}</dd></div>)}</dl><label className="mt-5 block text-sm">{t("审核依据（至少12个字符）")}<textarea rows={3} maxLength={4000} value={note} onChange={e=>setNote(e.target.value)} className="mt-2 w-full rounded-xl border border-[var(--border)] bg-[var(--card)] p-3"/></label><div className="mt-4 flex flex-wrap gap-3"><button className={primary} disabled={busy||note.trim().length<12||item.issues.length>0||item.status!=="candidate"} onClick={()=>review("publish")}><CheckCheck size={17}/>{t("确认核对并发布")}</button><button className={button} disabled={busy||note.trim().length<12||item.status==="retired"} onClick={()=>review("retire")}>{t("停用此题")}</button></div></div>}</article>)}</div>}{!itemsLoading&&!items.length&&<p className="py-6 text-sm">{t("这门课程还没有题目，请从资料导入开始。")}</p>}<div className="mt-6 flex items-center gap-4"><button className={button} disabled={!page||itemsLoading} onClick={()=>setPage(p=>p-1)}>{t("上一页")}</button><span className="text-sm">{page+1} / {Math.max(1,Math.ceil(total/40))}</span><button className={button} disabled={(page+1)*40>=total||itemsLoading} onClick={()=>setPage(p=>p+1)}>{t("下一页")}</button></div></section>}
    {tab==="quality"&&course&&<section><h2 className="text-xl font-semibold">{t("把缺口变成可处理的待办")}</h2><p className="mt-3 text-sm leading-7 text-[var(--muted-foreground)]">{t("这里统计内容准备情况，不代表学生掌握程度；一题可能有多个待办。")}</p><div className="my-5 divide-y divide-[var(--border)]">{Object.entries(course.issues).map(([key,count])=><div key={key} className="flex justify-between gap-4 py-4 text-sm"><span>{t(data?.issue_labels[key]||key)}</span><span className="tabular-nums">{count}</span></div>)}</div><Link href="/admin/teaching/assessments" className={button}>{t("整理考核范围与题目分类")}<ArrowUpRight size={15}/></Link><MaterialScopes administrator/></section>}
    <details className="mt-10 border-t border-[var(--border)] pt-5"><summary className="cursor-pointer text-sm text-[var(--muted-foreground)]">{t("高级设置与资料连接")}</summary><Link href="/knowledge" className="mt-4 inline-block text-sm underline">{t("检索引擎、外部资料与原始文件")}</Link></details>
  </div></div>;
}
