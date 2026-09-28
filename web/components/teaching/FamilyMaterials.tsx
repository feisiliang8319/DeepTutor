"use client";
import { t, useTeachingLocale } from "@/components/teaching/teaching-i18n";

import {useEffect,useState} from "react";
import {createKnowledgeBase,listKnowledgeBases,listKnowledgeBaseFiles,uploadKnowledgeBaseFiles,type KnowledgeBaseFile} from "@/lib/knowledge-api";
import {teachingApi} from "./api";
import MaterialScopes from "./MaterialScopes";
const LIBRARY="family-materials";
export default function FamilyMaterials({standalone=false}:{standalone?:boolean}){
  useTeachingLocale();

  const [scopeRevision,setScopeRevision]=useState(0);
  const [files,setFiles]=useState<KnowledgeBaseFile[]>([]);const [busy,setBusy]=useState(false);const [status,setStatus]=useState("");const [processing,setProcessing]=useState(false);const [error,setError]=useState("");
  async function refresh(){const libraries=await listKnowledgeBases({force:true});if(libraries.some(k=>k.name===LIBRARY&&!k.read_only)){const data=await listKnowledgeBaseFiles(LIBRARY);setFiles(data);setScopeRevision(value=>value+1);return true;}return false;}
  useEffect(()=>{refresh().then(exists=>{if(exists)setProcessing(true);}).catch(()=>setError(t("资料暂时无法读取。")));},[]);
  async function upload(selected:FileList|null){if(!selected?.length)return;const selectedFiles=Array.from(selected);setBusy(true);setError("");setStatus(t("正在上传资料…"));try{const libraries=await listKnowledgeBases({force:true});if(libraries.some(k=>k.name===LIBRARY&&!k.read_only))await uploadKnowledgeBaseFiles(LIBRARY,selectedFiles);else await createKnowledgeBase({name:LIBRARY,files:selectedFiles});setStatus(t("资料已接收，正在准备检索。准备完成后会自动用于孩子的学习。"));setProcessing(true);await refresh();}catch(e){setError((e as Error).message);setStatus("");}finally{setBusy(false);}}
  useEffect(()=>{if(!processing)return;const timer=setInterval(async()=>{try{const p=await teachingApi<{stage?:string;status?:string;message?:string}>(`/api/v1/knowledge/${LIBRARY}/progress`);if(p.status==="not_started"){setProcessing(false);}else if(p.stage==="completed"){setStatus(t("资料已准备好，会自动参与孩子的学习。"));setProcessing(false);await refresh();}else if(p.stage==="failed"||p.stage==="error"){setError(p.message||t("资料处理失败，请联系管理员。"));setStatus("");setProcessing(false);}}catch{setError(t("暂时无法确认资料处理状态，请稍后刷新。"));setStatus("");setProcessing(false);}},3000);return()=>clearInterval(timer);},[processing]);
  return <section className={standalone?"":"mt-10"}>{standalone?<h1 className="text-3xl font-semibold tracking-tight">{t("家庭资料")}</h1>:<h2 className="text-xl font-semibold">{t("给孩子的资料")}</h2>}<p className="mt-3 max-w-2xl text-sm leading-7 text-[var(--muted-foreground)]">{t("上传教材、讲义或参考资料，导师会按学习内容自动查找。资料默认仅供你的家庭使用。")}</p><label className="mt-5 inline-flex cursor-pointer rounded-xl border border-[var(--border)] bg-[var(--card)] px-5 py-3 text-sm focus-within:outline"><input type="file" multiple disabled={busy} className="sr-only" onChange={e=>{void upload(e.target.files);e.target.value="";}}/>{busy?t("正在上传…"):t("上传资料")}</label>{status&&<p role="status" className="mt-4 text-sm">{status}</p>}{error&&<p role="alert" className="mt-4 text-sm text-red-700">{error}</p>}<ul className="mt-5 space-y-2">{files.map((file,i)=><li key={i} className="rounded-lg bg-[var(--card)] p-3 text-sm">{file.name}</li>)}</ul><MaterialScopes refreshKey={scopeRevision}/></section>;
}
