"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import { apiFetch, apiUrl } from "@/lib/api";

export type RecorderState = "idle" | "requesting" | "recording" | "transcribing";
/** Explicit recording -> transcription -> editable text. Cancel/unmount never uploads. */
export function useVoiceRecorder(onTranscript: (text: string) => void, options: {language?: string; maxSeconds?: number} = {}) {
  const [state, setState] = useState<RecorderState>("idle");
  const [error, setError] = useState<string | null>(null);
  const [seconds, setSeconds] = useState(0);
  const stateRef = useRef<RecorderState>("idle");
  const recorder = useRef<MediaRecorder | null>(null);
  const stream = useRef<MediaStream | null>(null);
  const generation = useRef(0);
  const timer = useRef<ReturnType<typeof setInterval> | null>(null);
  const request = useRef<AbortController | null>(null);
  const callback = useRef(onTranscript); callback.current = onTranscript;
  const settings = useRef(options); settings.current = options;
  const transition = useCallback((next: RecorderState) => { stateRef.current = next; setState(next); }, []);
  const release = useCallback(() => { stream.current?.getTracks().forEach(track => track.stop()); stream.current = null; if (timer.current) clearInterval(timer.current); timer.current = null; }, []);
  const dispose = useCallback(() => { generation.current++; request.current?.abort(); request.current = null; if (recorder.current?.state === "recording") recorder.current.stop(); recorder.current = null; release(); }, [release]);
  const cancel = useCallback(() => { dispose(); transition("idle"); setSeconds(0); }, [dispose, transition]);
  const stop = useCallback(() => { if (recorder.current?.state === "recording") recorder.current.stop(); }, []);
  const start = useCallback(async () => {
    if (stateRef.current !== "idle") return;
    const current = ++generation.current;
    setError(null); setSeconds(0); transition("requesting");
    try {
      if (!navigator.mediaDevices?.getUserMedia || typeof MediaRecorder === "undefined") throw new Error("Recording is not supported in this browser.");
      const next = await navigator.mediaDevices.getUserMedia({ audio: true });
      if (current !== generation.current) { next.getTracks().forEach(track => track.stop()); return; }
      stream.current = next;
      const capture = new MediaRecorder(next); recorder.current = capture;
      const chunks: Blob[] = [];
      capture.ondataavailable = event => { if (event.data.size) chunks.push(event.data); };
      capture.onerror = () => { if (current === generation.current) { dispose(); transition("idle"); setError("Recording failed. Please try again."); } };
      capture.onstop = async () => {
        if (current !== generation.current) return;
        release();
        const mime = capture.mimeType || "audio/webm";
        const audio = new Blob(chunks, {type: mime});
        if (!audio.size) { transition("idle"); return; }
        transition("transcribing");
        const abort = new AbortController(); request.current = abort;
        try {
          const ext = mime.includes("mp4") ? "mp4" : mime.includes("ogg") ? "ogg" : "webm";
          const form = new FormData(); form.append("file", audio, `recording.${ext}`);
          if (settings.current.language) form.append("language", settings.current.language);
          const response = await apiFetch(apiUrl("/api/v1/voice/stt"), {method:"POST",body:form,signal:abort.signal});
          if (!response.ok) throw new Error("Transcription failed. Please try again.");
          const result = await response.json();
          if (current === generation.current && result.text?.trim()) callback.current(result.text.trim());
        } catch (e) { if (current === generation.current) setError((e as Error).message); }
        finally { if (current === generation.current) { request.current = null; transition("idle"); } }
      };
      capture.start(1000); transition("recording");
      const started = Date.now();
      timer.current = setInterval(() => { const elapsed = Math.floor((Date.now()-started)/1000); setSeconds(elapsed); if (elapsed >= (settings.current.maxSeconds ?? 120)) stop(); }, 250);
    } catch (e) {
      if (current === generation.current) { release(); transition("idle"); setError(e instanceof DOMException ? "Microphone permission denied." : (e as Error).message); }
    }
  }, [dispose, release, stop, transition]);
  const toggle = useCallback(() => { if (stateRef.current === "recording") stop(); else if (stateRef.current === "idle") void start(); }, [start,stop]);
  useEffect(() => dispose, [dispose]);
  return {state, error, seconds, start, stop, toggle, cancel};
}
