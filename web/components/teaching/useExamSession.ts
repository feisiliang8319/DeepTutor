"use client";
import { useEffect, useRef, useState } from 'react';
import { education } from './education-api';
import type { Exam } from './assessment-types';

export function useExamSession(exam: Exam | null, onInvalid: (exam: Exam) => void) {
  // Deliberately not in local/session storage: a reload is a new page session.
  const [pageSession, setPageSession] = useState('');
  useEffect(() => { setPageSession(crypto.randomUUID()); }, []);
  const [offline, setOffline] = useState(false);
  const [leaving, setLeaving] = useState(false);
  const latest = useRef({ exam, onInvalid });
  latest.current = { exam, onInvalid };
  const running = Boolean(exam && !exam.submitted && exam.integrity?.state === 'active');
  const interrupted = useRef(false);

  useEffect(() => {
    window.dispatchEvent(new CustomEvent('quiz-exam-state', { detail: running }));
    if (!running) return;
    let mounted = true;
    let pending = false;
    interrupted.current = false;
    setLeaving(false); setOffline(false);
    const id = exam!.set_id;
    const signal = async (reason?: 'page_hidden' | 'page_left') => {
      if (pending && !reason) return;
      if (reason) { interrupted.current = true; setLeaving(true); }
      pending = true;
      try {
        const next = await education<Exam>(`assessments/${id}/presence`, {
          method: 'POST', keepalive: Boolean(reason), headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ page_session: pageSession, reason: reason ?? null }),
        });
        if (mounted) {
          setOffline(false);
          if (next.integrity?.state === 'invalidated') latest.current.onInvalid(next);
        }
      } catch {
        if (mounted) setOffline(true);
        // A missing unload report cannot grant more time: the server presence
        // lease expires, and a new page session cannot resume this exam.
      } finally { pending = false; }
    };
    const hidden = () => { if (document.visibilityState === 'hidden') void signal('page_hidden'); };
    const left = () => { void signal('page_left'); };
    const navigate = (event: MouseEvent) => {
      const anchor = (event.target as Element)?.closest?.('a[href]') as HTMLAnchorElement | null;
      if (event.defaultPrevented || !anchor) return;
      const destination = new URL(anchor.href, location.href);
      if (destination.origin !== location.origin || destination.pathname !== location.pathname || destination.search !== location.search) left();
    };
    document.addEventListener('visibilitychange', hidden);
    window.addEventListener('pagehide', left);
    window.addEventListener('popstate', left);
    document.addEventListener('click', navigate);
    const timer = window.setInterval(() => { void signal(interrupted.current ? 'page_left' : undefined); }, 5000);
    if (document.visibilityState === 'hidden') hidden();
    else void signal();
    return () => {
      mounted = false;
      clearInterval(timer);
      document.removeEventListener('visibilitychange', hidden);
      window.removeEventListener('pagehide', left);
      window.removeEventListener('popstate', left);
      document.removeEventListener('click', navigate);
      window.dispatchEvent(new CustomEvent('quiz-exam-state', { detail: false }));
      // React development effect replay is not navigation. Only report when
      // the document has really unmounted its active Quiz owner.
      queueMicrotask(() => {
        if (latest.current.exam?.integrity?.state === 'active' && !latest.current.exam.submitted && !document.querySelector(`[data-quiz-session="${pageSession}"]`)) void signal('page_left');
      });
    };
  }, [running, exam?.set_id, pageSession]);
  return { pageSession, headers: { 'X-Quiz-Session': pageSession }, offline, leaving };
}
