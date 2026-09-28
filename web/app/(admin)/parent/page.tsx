"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { fetchAuthStatus } from "@/lib/auth";
import { t, useTeachingLocale } from "@/components/teaching/teaching-i18n";
import { teachingApi, type Account } from "@/components/teaching/api";
import ParentStudentProgress from "@/components/teaching/ParentStudentProgress";

export default function ParentPage() {
  useTeachingLocale();
  const [students, setStudents] = useState<Account[] | null>(null);
  const [selected, setSelected] = useState("");
  const [storageKey, setStorageKey] = useState("");
  const [error, setError] = useState("");
  const [storageError, setStorageError] = useState(false);
  const [retry, setRetry] = useState(0);

  useEffect(() => {
    let live = true;
    setError("");
    setStudents(null);
    Promise.all([fetchAuthStatus(), teachingApi<{ students: Account[] }>("/api/v1/teaching/students")])
      .then(([auth, data]) => {
        if (!live) return;
        if (!auth?.user_id || auth.role !== "parent") throw new Error(t("无法确认家长身份，请重新登录。"));
        const key = `deeptutor:parent:${auth.user_id}:student`;
        let remembered: string | null = null;
        try { remembered = sessionStorage.getItem(key); }
        catch { setStorageError(true); }
        // Remembered navigation state never grants access to a student.
        const id = data.students.find(student => student.id === remembered)?.id || data.students[0]?.id || "";
        setStorageKey(key);
        setSelected(id);
        setStudents(data.students);
      }).catch(e => { if (live) setError((e as Error).message); });
    return () => { live = false; };
  }, [retry]);

  function selectStudent(id: string) {
    setSelected(id);
    try { sessionStorage.setItem(storageKey, id); setStorageError(false); }
    catch { setStorageError(true); }
  }

  const student = students?.find(item => item.id === selected);
  return <div className="h-full overflow-auto">
    <div className="mx-auto max-w-5xl px-5 py-8 md:px-10 md:py-12">
      <header className="mb-8">
        <p className="mb-3 text-sm font-medium text-[var(--primary)]">{t("家长工作台")}</p>
        <h1 className="text-3xl font-semibold tracking-tight">{t("学习进展")}</h1>
        <p className="mt-3 text-sm leading-7 text-[var(--muted-foreground)]">{t("看见每个孩子的进步，陪伴每一次理解。")}</p>
      </header>
      {error ? <div role="alert" className="rounded-2xl border border-[var(--border)] p-5"><p>{error}</p><button onClick={() => setRetry(value => value + 1)} className="mt-3 text-sm underline">{t("重试")}</button></div>
        : !students ? <p role="status" className="py-8 text-sm text-[var(--muted-foreground)]">{t("正在读取…")}</p>
        : student ? <>
          <div className="mb-8 flex flex-wrap items-end justify-between gap-4 border-b border-[var(--border)] pb-6">
            <label htmlFor="parent-student" className="block w-full max-w-xs text-sm font-medium">{t("正在关注")}
              <select id="parent-student" value={selected} onChange={event => selectStudent(event.target.value)} className="mt-2 w-full border bg-[var(--card)] p-3">
                {students.map(item => <option key={item.id} value={item.id}>{item.username}</option>)}
              </select>
            </label>
            <p className="text-xs leading-6 text-[var(--muted-foreground)]">{t("目标、进展和学习记录均独立保存。")}</p>
          </div>
          {storageError && <p role="status" className="mb-5 text-sm">{t("浏览器无法记住本次选择，返回页面时请重新选择孩子。")}</p>}
          <ParentStudentProgress key={student.id} student={student} onGoalSaved={(id, goal) => setStudents(current => current?.map(item => item.id === id ? { ...item, goal } : item) ?? null)}/>
        </> : <div className="rounded-2xl bg-[var(--secondary)] p-7">
          <h2 className="text-xl font-semibold">{t("先为孩子准备一个账号")}</h2>
          <p className="mt-3 text-sm leading-7">{t("每个孩子都有独立的对话和学习记录，你可以管理最多 5 个学生账号。")}</p>
          <Link href="/parent/students" className="mt-5 inline-flex rounded-xl bg-[var(--primary)] px-5 py-3 text-sm text-[var(--primary-foreground)]">{t("创建学生账号")}</Link>
        </div>}
    </div>
  </div>;
}
