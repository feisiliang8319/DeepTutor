"use client";
import { t, useTeachingLocale } from "@/components/teaching/teaching-i18n";

import { createContext, useContext, useEffect, useRef, useState, type ReactNode } from "react";
import { Paintbrush, X, Check } from "lucide-react";
import { apiFetch, apiUrl } from "@/lib/api";
import { writeStoredLanguage,writeStoredResponseLanguage } from "@/context/app-shell-storage";
import { type AppLanguage } from "@/i18n/init";

export type Appearance = { scene:"grove"|"tide"|"apricot"; nickname:string; text_size:"comfortable"|"large"; motion:boolean; companion:boolean; language:AppLanguage };
const defaults:Appearance={scene:"grove",nickname:"",text_size:"comfortable",motion:true,companion:true,language:"en"};
const Context=createContext({preferences:defaults,save:async (_:Appearance)=>{},saveLanguage:async (_:AppLanguage)=>{}});
export const useTeachingPreferences=()=>useContext(Context);
export function TeachingPreferencesProvider({children,student}:{children:ReactNode;student:boolean}) {
  useTeachingLocale();

  const [preferences,setPreferences]=useState(defaults);
  useEffect(()=>{let alive=true;apiFetch(apiUrl("/api/v1/teaching/appearance")).then(async r=>{if(!r.ok)throw new Error();const p=await r.json();if(alive){setPreferences(p);writeStoredLanguage(p.language);writeStoredResponseLanguage(p.language);}}).catch(()=>{/* The editor reports read failures before saving. Display defaults do not assert saved preferences. */});return()=>{alive=false;};},[student]);
  async function save(next:Appearance){const r=await apiFetch(apiUrl("/api/v1/teaching/appearance"),{method:"PUT",headers:{"Content-Type":"application/json"},body:JSON.stringify(next)});if(!r.ok)throw new Error(t("暂时没能保存，请重试。"));const saved=await r.json();setPreferences(saved);writeStoredLanguage(saved.language);writeStoredResponseLanguage(saved.language);}
  async function saveLanguage(language:AppLanguage){const r=await apiFetch(apiUrl("/api/v1/teaching/appearance"),{method:"PATCH",headers:{"Content-Type":"application/json"},body:JSON.stringify({language})});if(!r.ok)throw new Error(t("暂时没能保存，请重试。"));const saved=await r.json();setPreferences(saved);writeStoredLanguage(saved.language);writeStoredResponseLanguage(saved.language);}
  return <Context.Provider value={{preferences,save,saveLanguage}}><div className="teaching-theme" data-scene={preferences.scene} data-text-size={preferences.text_size} data-motion={preferences.motion ? "on":"off"}>{children}</div></Context.Provider>;
}

export function PersonalizeButton(){
  useTeachingLocale();

  const {preferences,save}=useTeachingPreferences();const [draft,setDraft]=useState(defaults);const [error,setError]=useState("");const [busy,setBusy]=useState(false);const [loaded,setLoaded]=useState(false);const dialog=useRef<HTMLDialogElement>(null);
  async function open(){setError("");setLoaded(false);setDraft(preferences);dialog.current?.showModal();setBusy(true);try{const r=await apiFetch(apiUrl("/api/v1/teaching/appearance"));if(!r.ok)throw new Error();setDraft(await r.json());setLoaded(true);}catch{setError(t("暂时无法读取你的设置，请关闭后重试。"));}finally{setBusy(false);}}
  async function submit(){setBusy(true);setError("");try{await save(draft);dialog.current?.close();}catch(e){setError((e as Error).message);}finally{setBusy(false);}}
  const scenes=[{id:"grove" as const,label:t("林间书房"),color:"#c6dccc",hint:t("鼠尾草绿")},{id:"tide" as const,label:t("海边工作室"),color:"#c6dce4",hint:t("雾蓝")},{id:"apricot" as const,label:t("杏色小屋"),color:"#ecd2be",hint:t("暖杏色")}];
  return <><button onClick={open} className="mb-3 flex w-full items-center gap-2 rounded-xl border border-[var(--border)] bg-[var(--card)] px-3 py-2 text-sm"><Paintbrush size={17}/>{t("我的书房")}</button><dialog ref={dialog} className="teaching-personalizer w-[min(92vw,520px)] rounded-3xl border border-[var(--border)] bg-[var(--card)] p-6 text-[var(--foreground)] shadow-xl backdrop:bg-[#24372f]/30" aria-labelledby="personalize-title"><div className="flex items-center justify-between gap-3"><h2 id="personalize-title" className="text-xl font-semibold">{t("把这里变成你的书房")}</h2><button type="button" onClick={()=>dialog.current?.close()} aria-label={t("关闭外观设置")} className="p-2"><X size={18}/></button></div><p className="mb-6 mt-2 text-sm text-[var(--muted-foreground)]">{t("选一种心情，安放你的好奇心。")}</p>
    <fieldset disabled={busy} className="space-y-6"><div><label htmlFor="student-nickname" className="mb-2 block text-sm font-medium">{t("导师怎么称呼你")}</label><input id="student-nickname" maxLength={24} value={draft.nickname} onChange={e=>setDraft({...draft,nickname:e.target.value})} placeholder={t("你的昵称")} className="w-full rounded-xl border p-3"/></div><div><p className="mb-3 text-sm font-medium">{t("书房色彩")}</p><div className="grid grid-cols-3 gap-3">{scenes.map(scene=><button key={scene.id} type="button" aria-pressed={draft.scene===scene.id} onClick={()=>setDraft({...draft,scene:scene.id})} className={`relative rounded-2xl border p-3 text-left ${draft.scene===scene.id ? "border-[var(--primary)] ring-1 ring-[var(--primary)]":"border-[var(--border)]"}`}><span className="mb-3 block h-12 rounded-xl" style={{backgroundColor:scene.color}}/>{draft.scene===scene.id&&<Check size={17} className="absolute right-4 top-4"/>}<span className="block text-sm font-medium">{scene.label}</span><span className="mt-1 block text-xs text-[var(--muted-foreground)]">{scene.hint}</span></button>)}</div></div><div><label htmlFor="reading-size" className="mb-2 block text-sm font-medium">{t("阅读字号")}</label><select id="reading-size" value={draft.text_size} onChange={e=>setDraft({...draft,text_size:e.target.value as Appearance["text_size"]})} className="w-full rounded-xl border p-3"><option value="comfortable">{t("舒适")}</option><option value="large">{t("大一点")}</option></select></div><label className="flex items-center justify-between gap-4 text-sm">{t("让学习伙伴陪伴我")}<input type="checkbox" checked={draft.companion} onChange={e=>setDraft({...draft,companion:e.target.checked})} className="h-5 w-5 accent-[var(--primary)]"/></label><label className="flex items-center justify-between gap-4 text-sm">{t("轻柔的动态反馈")}<input type="checkbox" checked={draft.motion} onChange={e=>setDraft({...draft,motion:e.target.checked})} className="h-5 w-5 accent-[var(--primary)]"/></label></fieldset>{error&&<p role="alert" className="mt-4 text-sm text-red-700">{error}</p>}<button disabled={busy||!loaded} onClick={submit} className="mt-7 w-full rounded-xl bg-[var(--primary)] px-4 py-3 text-sm font-medium text-[var(--primary-foreground)] disabled:opacity-50">{busy?t("正在保存…"):t("就这样，开始探索")}</button></dialog></>;
}


export function TeachingLanguageSelector(){
  useTeachingLocale();

 const {preferences,saveLanguage}=useTeachingPreferences();const [busy,setBusy]=useState(false);const [error,setError]=useState("");
 return <div className="mb-4"><label htmlFor="teaching-language" className="sr-only">{t("语言 / Language")}</label><select id="teaching-language" aria-label={t("Language / 语言")} value={preferences.language} disabled={busy} onChange={async e=>{setBusy(true);setError("");try{await saveLanguage(e.target.value as AppLanguage);}catch(err){setError((err as Error).message);}finally{setBusy(false);}}} className="w-full border border-[var(--border)] bg-[var(--card)] px-3 py-2 text-sm"><option value="en">English</option><option value="zh">{t("简体中文")}</option><option value="zh-Hant">{t("繁體中文")}</option></select>{error&&<p role="alert" className="mt-2 text-xs text-red-700">{error}</p>}</div>;
}
