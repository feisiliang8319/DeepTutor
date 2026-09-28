"use client";
import { useEffect, useRef, useState } from "react";
import { Camera, X } from "lucide-react";
import { t, useTeachingLocale } from "./teaching-i18n";

export default function CameraCapture({ disabled, onPhoto }: { disabled: boolean; onPhoto: (file: File) => void }) {
  useTeachingLocale();
  const dialog = useRef<HTMLDialogElement>(null);
  const video = useRef<HTMLVideoElement>(null);
  const stream = useRef<MediaStream | null>(null);
  const generation = useRef(0);
  const [ready, setReady] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [photo, setPhoto] = useState<Blob | null>(null);
  const [preview, setPreview] = useState("");
  const release = () => { stream.current?.getTracks().forEach(track => track.stop()); stream.current = null; };
  function close() { generation.current++; release(); setReady(false); setBusy(false); setPhoto(null); dialog.current?.close(); }
  useEffect(() => () => { generation.current++; release(); }, []);
  useEffect(() => { if (!photo) { setPreview(""); return; } const url = URL.createObjectURL(photo); setPreview(url); return () => URL.revokeObjectURL(url); }, [photo]);
  async function start() {
    const current = ++generation.current;
    release(); setPhoto(null); setReady(false); setError(""); setBusy(true);
    try {
      if (!navigator.mediaDevices?.getUserMedia) throw new Error(t("此浏览器无法打开相机，请使用手机拍照或上传图片。"));
      const next = await navigator.mediaDevices.getUserMedia({ video: { facingMode: { ideal: "environment" } }, audio: false });
      if (generation.current !== current) { next.getTracks().forEach(track => track.stop()); return; }
      stream.current = next;
      if (video.current) { video.current.srcObject = next; await video.current.play(); }
    } catch (e) {
      if (generation.current === current) { release(); setError(e instanceof DOMException ? t("未能打开相机，请检查权限或改用图片上传。") : (e as Error).message); }
    } finally { if (generation.current === current) setBusy(false); }
  }
  function take() {
    if (!video.current?.videoWidth) return;
    const canvas = document.createElement("canvas");
    const scale = Math.min(1, 2000 / Math.max(video.current.videoWidth, video.current.videoHeight));
    canvas.width = Math.round(video.current.videoWidth * scale); canvas.height = Math.round(video.current.videoHeight * scale);
    const context = canvas.getContext("2d");
    if (!context) { setError(t("照片生成失败，请重试。")); return; }
    context.drawImage(video.current, 0, 0, canvas.width, canvas.height);
    const current = generation.current;
    canvas.toBlob(blob => { if (generation.current !== current) return; if (!blob) { setError(t("照片生成失败，请重试。")); return; } setPhoto(blob); release(); setReady(false); }, "image/jpeg", 0.9);
  }
  return <><button type="button" disabled={disabled} onClick={() => { setError(""); setPhoto(null); dialog.current?.showModal(); }} className="inline-flex items-center gap-1.5 px-2 py-2 text-xs disabled:opacity-40"><Camera size={18}/>{t("拍照")}</button>
    <dialog ref={dialog} onCancel={close} aria-labelledby="camera-title" className="w-[min(94vw,640px)] max-h-[90dvh] overflow-auto rounded-2xl border border-[var(--border)] bg-[var(--card)] p-5 text-[var(--foreground)] backdrop:bg-[#24372f]/30">
      <div className="flex items-center justify-between"><h2 id="camera-title" className="text-lg font-semibold">{t("拍下你的作业")}</h2><button type="button" onClick={close} aria-label={t("关闭相机")} className="p-2"><X size={18}/></button></div>
      <p className="my-3 text-sm leading-6">{t("先检查照片是否清晰，确认后放入输入框，不会自动发送。")}</p>
      {preview ? <img src={preview} alt={t("待确认的作业照片")} className="max-h-[50dvh] w-full rounded-xl object-contain"/> : <video ref={video} autoPlay muted playsInline onLoadedData={() => setReady(true)} className={`max-h-[50dvh] w-full rounded-xl bg-[var(--secondary)] ${!ready&&!busy?"hidden":""}`}/>}
      {!photo&&!ready&&!busy&&<div className="flex min-h-36 flex-col items-center justify-center gap-3 rounded-xl bg-[var(--secondary)] text-sm text-[var(--muted-foreground)]"><Camera size={28}/><p>{t("相机尚未开启")}</p></div>}
      {error && <p role="alert" className="mt-3 text-sm text-red-700">{error}</p>}
      <div className="mt-4 flex flex-wrap gap-3">{photo ? <><button type="button" onClick={start} className="border px-4 py-2">{t("重拍")}</button><button type="button" onClick={() => { onPhoto(new File([photo], `homework-${Date.now()}.jpg`, { type: "image/jpeg" })); close(); }} className="bg-[var(--primary)] px-4 py-2 text-[var(--primary-foreground)]">{t("使用这张照片")}</button></> : ready ? <button type="button" onClick={take} className="bg-[var(--primary)] px-4 py-2 text-[var(--primary-foreground)]">{t("拍下照片")}</button> : <button type="button" disabled={busy} onClick={start} className="bg-[var(--primary)] px-4 py-2 text-[var(--primary-foreground)] disabled:opacity-40">{busy ? t("正在打开相机…") : t("打开相机")}</button>}
        <label className="inline-flex cursor-pointer items-center rounded-xl border border-[var(--border)] bg-[var(--card)] px-4 py-2 text-sm">{t("使用手机相机")}<input type="file" accept="image/*" capture="environment" className="sr-only" onChange={e => { const file = e.target.files?.[0]; e.target.value = ""; if (file) { onPhoto(file); close(); } }}/></label>
      </div>
    </dialog></>;
}
