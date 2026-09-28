"use client";

import { useEffect, useState } from "react";
import { FileCheck2, Loader2 } from "lucide-react";
import { request } from "./material-intelligence-api";
import { t, useTeachingLocale } from "./teaching-i18n";

type Choice = { choice: string; confidence: number; needs_review: boolean };
type Review = { id: string; kb: string; filename: string; excerpt: string; source_hash: string; status: string; result: Record<string, Choice> | null };
type History = Pick<Review, "id" | "kb" | "filename" | "status">;
const labels: Record<string, string> = {
  mathematics: "数学", science: "科学", physics: "物理", chemistry: "化学", biology: "生物", computing: "计算机科学", engineering: "工程",
  english: "英语", chinese: "语文", history: "历史", geography: "地理", mixed: "跨多个类别", other: "其他", unknown: "依据不足",
  primary_lower: "小学低年级（1–3年级）", primary_upper: "小学高年级（4–6年级）", middle: "初中（7–9年级）", high: "高中（10–12年级）", advanced: "高中以上",
  readable: "文字清晰可读", incomplete: "片段内容不完整", noisy: "文字或排版存在干扰",
};
const dimensions: Record<string, string> = {subject:"建议学科",level:"建议学段",quality:"片段质量"};
export default function MaterialReview({enabled}:{enabled:boolean}) {
  useTeachingLocale();
  const [libraries,setLibraries]=useState<string[]>([]);
  const [files,setFiles]=useState<string[]>([]);
  const [kb,setKb]=useState("");
  const [filename,setFilename]=useState("");
  const [current,setCurrent]=useState<Review|null>(null);
  const [history,setHistory]=useState<History[]>([]);
  const [confirmed,setConfirmed]=useState(false);
  const [busy,setBusy]=useState(false);
  const [loadingFiles,setLoadingFiles]=useState(false);
  const [error,setError]=useState("");
  useEffect(()=>{
    let active=true;
    Promise.all([request<{libraries:string[]}>("/libraries"),request<{reviews:History[]}>("/reviews")]).then(([list,past])=>{if(active){setLibraries(list.libraries);setHistory(past.reviews);}}).catch(()=>{if(active)setError("资料列表加载失败，请刷新重试。");});
    return()=>{active=false;};
  },[]);
  useEffect(()=>{
    let active=true; setFiles([]);setFilename("");setCurrent(null);setConfirmed(false);
    if(!kb){setLoadingFiles(false);return()=>{active=false;};}
    setLoadingFiles(true);setError("");
    request<{documents:string[]}>("/documents?kb="+encodeURIComponent(kb)).then(data=>{if(active)setFiles(data.documents);}).catch(cause=>{if(active)setError(cause.message);}).finally(()=>{if(active)setLoadingFiles(false);});
    return()=>{active=false;};
  },[kb]);
  async function refreshHistory(){setHistory((await request<{reviews:History[]}>("/reviews")).reviews);}
  async function prepare(){
    setBusy(true);setError("");setCurrent(null);setConfirmed(false);
    try {setCurrent(await request<Review>("/preview","POST",{kb,filename}));await refreshHistory();}
    catch(cause){setError(cause instanceof Error?cause.message:"操作未完成，请稍后重试。");}
    finally{setBusy(false);}
  }
  async function analyze(){
    if(!current||!confirmed)return;
    setBusy(true);setError("");
    try {setCurrent(await request<Review>(`/reviews/${current.id}/analyze`,"POST",{confirmed_nonpersonal_export:true}));await refreshHistory();}
    catch(cause){setError(cause instanceof Error?cause.message:"操作未完成，请稍后重试。");try{setCurrent(await request<Review>(`/reviews/${current.id}`));await refreshHistory();}catch{/* Preserve the visible failure; never claim a successful analysis. */}}
    finally{setBusy(false);}
  }
  async function open(id:string){
    setBusy(true);setError("");setConfirmed(false);
    try{setCurrent(await request<Review>(`/reviews/${id}`));}
    catch(cause){setError(cause instanceof Error?cause.message:"操作未完成，请稍后重试。");}
    finally{setBusy(false);}
  }
  const control="mt-2 min-h-11 w-full rounded-xl border border-[var(--border)] bg-[var(--background)] px-3 py-3 text-sm outline-none focus-visible:ring-2 focus-visible:ring-[var(--primary)] disabled:opacity-50";
  const button="min-h-11 rounded-xl bg-[var(--primary)] px-5 py-3 text-sm font-medium text-[var(--primary-foreground)] disabled:cursor-not-allowed disabled:opacity-50 focus-visible:ring-2 focus-visible:ring-[var(--primary)] focus-visible:ring-offset-2";
  return <section id="material-review" className="mt-10 border-t border-[var(--border)] pt-8">
    <h2 className="flex items-center gap-2 text-xl font-semibold"><FileCheck2 size={22}/>{t("主库资料建议")}</h2>
    <p className="mt-3 text-sm leading-7 text-[var(--muted-foreground)]">{t("选择一份资料，先查看最多6000字的实际发送片段，再决定是否交给 Jev。不会发送文件名、账号信息或整份文件。")}</p>
    <div className="mt-5 grid gap-4 sm:grid-cols-2">
      <label className="min-w-0 text-sm">{t("主库")}<select className={control} value={kb} disabled={busy} onChange={e=>setKb(e.target.value)}><option value="">{t("请选择主库")}</option>{libraries.map(name=><option key={name} value={name}>{name}</option>)}</select></label>
      <label className="min-w-0 text-sm">{t("资料文件")}<select className={control} value={filename} disabled={busy||!kb||loadingFiles} onChange={e=>{setFilename(e.target.value);setCurrent(null);setConfirmed(false);}}><option value="">{t(loadingFiles?"正在读取文件…":"请选择资料文件")}</option>{files.map(name=><option key={name} value={name}>{name}</option>)}</select></label>
    </div>
    <p className="mt-3 text-xs leading-6 text-[var(--muted-foreground)]">{t("支持文本、PDF 和 Office 文档，每份不超过20 MB；扫描件优先读取已有 OCR 文字，未提取文字时会提示。")}</p>
    <button type="button" onClick={()=>void prepare()} disabled={busy||!kb||!filename} className={button+" mt-4"}>{t("预览发送片段")}</button>
    {busy&&<p role="status" className="mt-4 flex items-center gap-2 text-sm"><Loader2 size={16} className="animate-spin motion-reduce:animate-none"/>{t("正在处理，请稍候…")}</p>}
    {error&&<p role="alert" className="mt-4 rounded-xl border border-[var(--border)] bg-[var(--accent)] p-4 text-sm leading-6">{t(error)}</p>}
    {current&&<article className="mt-6 rounded-2xl border border-[var(--border)] bg-[var(--card)] p-5">
      <h3 className="break-words font-medium">{current.filename}</h3><p className="mt-1 break-words text-xs text-[var(--muted-foreground)]">{current.kb} · {t("资料版本")} {current.source_hash.slice(0,12)}</p>
      <details className="mt-4" open={current.status==="preview"}><summary className="cursor-pointer text-sm font-medium">{t("实际发送片段")}</summary><pre className="mt-3 max-h-72 overflow-y-auto whitespace-pre-wrap break-words rounded-xl bg-[var(--background)] p-4 font-sans text-sm leading-7">{current.excerpt}</pre></details>
      {current.status==="preview"&&<><label className="mt-5 flex items-start gap-3 text-sm leading-7"><input type="checkbox" className="mt-1.5 h-4 w-4 shrink-0 accent-[var(--primary)]" checked={confirmed} disabled={busy} onChange={e=>setConfirmed(e.target.checked)}/><span>{t("我确认所示片段可发送至 TypeSafe，且不含个人信息、学生聊天、作答或家庭资料。")}</span></label><button type="button" className={button+" mt-4"} disabled={busy||!confirmed||!enabled} onClick={()=>void analyze()}>{t("确认并获取建议")}</button>{!enabled&&<p className="mt-3 text-sm">{t("请先保存 Jev 专用 API Key。")}</p>}<p className="mt-3 text-xs leading-6 text-[var(--muted-foreground)]">{t("确认只适用于这份资料的当前片段。预览15分钟后失效，文件更新后需重新预览。")}</p></>}
      {current.status==="running"&&<p className="mt-4 text-sm">{t("请求处理中；请稍后从最近记录重新打开。")}</p>}
      {current.status==="failed"&&<p className="mt-4 text-sm">{t("本次处理未完成，请重新预览后重试。")}</p>}
      {current.result&&<><dl className="mt-6 space-y-4">{Object.entries(current.result).map(([dimension,answer])=><div key={dimension}><dt className="text-xs text-[var(--muted-foreground)]">{t(dimensions[dimension]||dimension)}</dt><dd className="mt-1 font-medium">{t(labels[answer.choice]||answer.choice)}{answer.needs_review&&<span className="ml-2 text-xs font-normal text-[var(--muted-foreground)]">{t("需人工核对")}</span>}</dd></div>)}</dl><p className="mt-5 text-xs leading-6 text-[var(--muted-foreground)]">{t("这些是基于片段的建议，不代表整份资料已经审核。不会自动修改资料范围、学生年级或测试成绩。")}</p></>}
    </article>}
    {!!history.length&&<div className="mt-7"><h3 className="text-sm font-medium">{t("最近建议记录")}</h3><ul className="mt-3 divide-y divide-[var(--border)]">{history.map(item=><li key={item.id}><button type="button" disabled={busy} onClick={()=>void open(item.id)} className="w-full py-3 text-left text-sm"><span className="block break-words">{item.filename}</span><span className="mt-1 block text-xs text-[var(--muted-foreground)]">{item.kb} · {t(item.status==="completed"?"已生成建议":item.status==="failed"?"处理未完成":item.status==="running"?"处理中":"待确认片段")}</span></button></li>)}</ul></div>}
  </section>;
}
