"use client";
import { t, useTeachingLocale } from "@/components/teaching/teaching-i18n";

import { useEffect, useRef, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { Paperclip, ArrowUp, Square, Plus, History, X, Squirrel, Bird, Leaf } from "lucide-react";
import { useTeachingPreferences } from "./TeachingPreferences";
import Link from "next/link";
import TeachingSources from "./TeachingSources";
import { useUnifiedChat } from "@/context/UnifiedChatContext";
import MarkdownRenderer from "@/components/common/MarkdownRenderer";
import { apiFetch, apiUrl } from "@/lib/api";

type Upload = { type: string; filename: string; mime_type: string; base64: string };
export default function TeachingChat() {
  useTeachingLocale();

  const {preferences}=useTeachingPreferences();
  const Companion=preferences.scene==="tide"?Bird:Squirrel;
  const chat = useUnifiedChat();
  const { state } = chat;
  const params = useParams<{sessionId?: string[]}>();
  const routeSession = params.sessionId?.[0];
  const router = useRouter();
  const [text, setText] = useState("");
  const [uploads, setUploads] = useState<Upload[]>([]);
  const [error, setError] = useState("");
  const [history, setHistory] = useState<Array<{id:string;title:string}> | null>(null);
  const [uploading, setUploading] = useState(false);
  const end = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (routeSession && state.sessionId !== routeSession) {
      chat.loadSession(routeSession).catch(() => setError(t("对话暂时无法加载，请刷新重试。")));
    }
  }, [routeSession, chat.loadSession]); // The route selects the session; streaming updates do not reload it.
  useEffect(() => { end.current?.scrollIntoView({block:"end"}); }, [state.messages, state.isStreaming]);
  useEffect(() => {
    if (!routeSession && state.sessionId) router.replace(`/home/${state.sessionId}`);
  }, [state.sessionId, routeSession, router]);
  function submit() {
    if ((!text.trim() && !uploads.length) || state.isStreaming || uploading) return;
    setError("");
    chat.sendMessage(text.trim() || t("请帮我检查这份作业并讲解需要改进的地方。"), uploads);
    setText(""); setUploads([]);
  }
  async function upload(files: FileList | null) {
    if (!files) return;
    setUploading(true); setError("");
    try {
      const additions: Upload[] = [];
      for (const file of Array.from(files)) {
        if (file.size > 10*1024*1024) throw new Error(t("单个附件请控制在 10 MB 以内。"));
        const data = await new Promise<string>((resolve,reject) => { const reader=new FileReader(); reader.onload=()=>resolve(String(reader.result).split(",")[1]); reader.onerror=()=>reject(new Error(t("附件读取失败"))); reader.readAsDataURL(file); });
        additions.push({type:file.type.startsWith("image/") ? "image" : "file", filename:file.name,mime_type:file.type,base64:data});
      }
      setUploads(previous => [...previous, ...additions]);
    } catch(e) { setError(e instanceof Error ? e.message : t("附件读取失败")); }
    finally { setUploading(false); }
  }
  async function showHistory() {
    try { const res = await apiFetch(apiUrl("/api/v1/sessions?limit=50")); if(!res.ok) throw new Error(); const data=await res.json();setHistory(data.sessions); }
    catch { setError(t("历史记录暂时无法加载。")); }
  }
  return <div className="flex h-full min-w-0 flex-col">
    <header className="flex flex-wrap items-center justify-between gap-2 border-b border-[var(--border)] px-5 py-4"><div><h1 className="text-xl font-semibold">Chat</h1><p className="mt-1 text-xs text-[var(--muted-foreground)]">{t("提问、深入理解，或上传作业一起订正")}</p></div><div className="flex gap-2"><button onClick={showHistory} className="rounded-lg border border-[var(--border)] p-2" aria-label={t("学习对话记录")}><History size={18}/></button><button disabled={state.isStreaming} onClick={()=>{chat.newSession();router.push("/home");}} className="rounded-lg border border-[var(--border)] p-2 disabled:opacity-40" aria-label={t("新对话")}><Plus size={18}/></button></div></header>
    {history && <section className="max-h-60 overflow-auto border-b border-[var(--border)] px-5 py-3" aria-label={t("对话记录")}><button className="float-right p-1" onClick={()=>setHistory(null)} aria-label={t("关闭对话记录")}><X size={16}/></button>{history.length ? history.map(s=><Link key={s.id} href={`/home/${s.id}`} onClick={()=>setHistory(null)} className="block py-2 text-sm underline">{s.title || t("学习对话")}</Link>) : <p className="text-sm">{t("还没有学习对话。")}</p>}</section>}
    <div className="min-h-0 flex-1 overflow-y-auto px-5 py-6"><div className="mx-auto max-w-3xl space-y-7">
      {!state.messages.length && <div className="teaching-welcome py-10 md:py-14">{preferences.companion&&<div className="teaching-companion" aria-hidden="true"><Companion size={64} strokeWidth={1.35}/><Leaf className="teaching-leaf" size={22}/></div>}<p className="text-xs text-[var(--muted-foreground)]">{t("你的学习对话")}</p>{preferences.nickname&&<p className="mt-5 text-sm text-[var(--primary)]">{preferences.nickname}</p>}<h2 className="teaching-display mt-4 text-4xl leading-snug md:text-[44px]">{t("今天想弄懂什么？")}</h2><p className="mt-5 max-w-xl text-sm leading-7 text-[var(--muted-foreground)]">{t("可以从一道难题、一个疑问，或一张作业照片开始。测试在 Quiz 中完成，讲解会回到这里。")}</p></div>}
      {state.messages.map((m,i)=><article key={m.id ?? i} className={m.role === "user" ? "ml-6 rounded-xl bg-[var(--secondary)] p-4" : "py-2"}><p className="mb-2 text-xs text-[var(--muted-foreground)]">{m.role === "user" ? t("你") : t("导师")}</p><MarkdownRenderer content={m.content || (state.isStreaming ? t("正在思考…") : "")}/>{m.role === "assistant" && <TeachingSources events={m.events}/>}{m.attachments?.map((a,j)=><span key={j} className="mt-2 block text-xs text-[var(--muted-foreground)]">{t("附件：")}{a.filename}</span>)}</article>)}
      <div ref={end}/>
    </div></div>
    <div className="mx-auto w-full max-w-3xl px-5 pb-5">{error && <p role="alert" className="mb-3 text-sm text-red-600">{error}</p>}{uploads.length>0 && <ul className="mb-2 space-y-1">{uploads.map((u,i)=><li key={i} className="flex items-center gap-2 text-xs"><span className="min-w-0 truncate">{u.filename}</span><button aria-label={t("移除 {{value0}}",{value0:u.filename})} onClick={()=>setUploads(v=>v.filter((_,j)=>i!==j))}><X size={14}/></button></li>)}</ul>}
      <form onSubmit={e=>{e.preventDefault();submit();}} className="teaching-composer rounded-2xl border border-[var(--border)] bg-[var(--card)] p-3"><label htmlFor="learning-message" className="sr-only">{t("学习问题")}</label><textarea id="learning-message" value={text} onChange={e=>setText(e.target.value)} placeholder={t("写下你的问题，或上传作业…")} rows={3} className="w-full resize-none bg-transparent text-sm leading-6 outline-none focus-visible:ring-1 focus-visible:ring-[var(--primary)]" onKeyDown={e=>{if(e.key==="Enter" && !e.shiftKey && !e.nativeEvent.isComposing){e.preventDefault();submit();}}}/><div className="flex items-center justify-between"><label className="cursor-pointer rounded-lg p-2 focus-within:outline"><Paperclip size={19}/><span className="sr-only">{t("上传作业")}</span><input type="file" multiple className="sr-only" disabled={uploading || state.isStreaming} onChange={e=>{void upload(e.target.files);e.target.value="";}}/></label><span role="status" className="text-xs text-[var(--muted-foreground)]">{uploading ? t("正在读取附件…") : state.isStreaming ? t("导师正在回复…") : ""}</span>{state.isStreaming ? <button type="button" onClick={chat.cancelStreamingTurn} className="rounded-lg bg-[var(--primary)] p-2 text-[var(--primary-foreground)]" aria-label={t("停止回复")}><Square size={18}/></button> : <button disabled={uploading || (!text.trim() && !uploads.length)} className="rounded-lg bg-[var(--primary)] p-2 text-[var(--primary-foreground)] disabled:opacity-30" aria-label={t("发送问题")}><ArrowUp size={18}/></button>}</div></form>
    </div>
  </div>;
}
