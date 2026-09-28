"use client";
import { useEffect, useState } from "react";
import { Mic, Square, X } from "lucide-react";
import { useVoiceRecorder } from "@/hooks/useVoiceRecorder";
import { teachingApi } from "./api";
import { t, useTeachingLocale } from "./teaching-i18n";
import { useTeachingPreferences } from "./TeachingPreferences";
export default function VoiceInput({disabled,onTranscript,onBusy}:{disabled:boolean;onTranscript:(text:string)=>void;onBusy:(busy:boolean)=>void}) {
  useTeachingLocale();
  const {preferences}=useTeachingPreferences();
  const [configured,setConfigured]=useState<boolean|null>(null);
  const [loadError,setLoadError]=useState(false);
  const recorder=useVoiceRecorder(onTranscript,{language:preferences.language,maxSeconds:120});
  useEffect(()=>{let alive=true;teachingApi<{configured:boolean}>("/api/v1/voice/status").then(d=>{if(alive)setConfigured(d.configured);}).catch(()=>{if(alive)setLoadError(true);});return()=>{alive=false;};},[]);
  useEffect(()=>{onBusy(recorder.state!=="idle");},[recorder.state,onBusy]);
  return <div className="flex flex-wrap items-center gap-2 text-xs">
    <button type="button" disabled={disabled||configured!==true||recorder.state==="requesting"||recorder.state==="transcribing"} onClick={recorder.toggle} className="inline-flex items-center gap-1.5 px-2 py-2 disabled:opacity-40" title={configured===false?t("语音服务待管理员启用"):t("语音转成文字后，可以检查修改再发送。")}>{recorder.state==="recording"?<Square size={17}/>:<Mic size={18}/>}<span>{recorder.state==="recording"?t("完成录音"):recorder.state==="transcribing"?t("正在转成文字…"):recorder.state==="requesting"?t("等待麦克风权限…"):t("语音")}</span></button>
    {recorder.state!=="idle"&&<><span role="status">{recorder.state==="recording"?`${recorder.seconds}s / 120s`:""}</span><button type="button" onClick={recorder.cancel} aria-label={t("取消语音输入")} className="p-2"><X size={16}/></button></>}
    {configured===false&&<span className="text-[var(--muted-foreground)]">{t("语音服务待管理员启用")}</span>}
    {loadError&&<span role="alert">{t("暂时无法读取语音服务状态，请刷新重试。")}</span>}
    {recorder.error&&<span role="alert" className="text-red-700">{t(recorder.error)}</span>}
  </div>;
}
