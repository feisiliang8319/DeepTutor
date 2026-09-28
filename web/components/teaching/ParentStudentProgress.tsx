"use client";

import { useEffect, useState } from "react";
import { ChevronDown } from "lucide-react";
import LearningPlan from "./LearningPlan";
import LearningEvidence from "./LearningEvidence";
import { teachingApi, jsonBody, type Account } from "./api";
import { education, type Person, type Course } from "./education-api";
import { t, useTeachingLocale } from "./teaching-i18n";

type CourseProgress = Course & { nodes: Array<{ title: string; status: string }> };

export default function ParentStudentProgress({ student, onGoalSaved }: { student: Account; onGoalSaved: (id: string, goal: string) => void }) {
  useTeachingLocale();
  const [goal, setGoal] = useState(student.goal || "");
  const [message, setMessage] = useState("");
  const [goalError, setGoalError] = useState("");
  const [busy, setBusy] = useState(false);
  const [progress, setProgress] = useState<CourseProgress[] | null>(null);
  const [progressError, setProgressError] = useState("");
  const [showEvidence, setShowEvidence] = useState(false);

  useEffect(() => {
    let live = true;
    (async () => {
      try {
        const people = await education<{ people: Array<Person & { user_id?: string }> }>("people");
        const person = people.people.find(item => item.user_id === student.id);
        if (!person) { if (live) setProgress([]); return; }
        const { courses } = await education<{ courses: Course[] }>(`courses?learner_id=${encodeURIComponent(person.id)}`);
        const result = await Promise.all(courses.map(async course => ({ ...course,
          ...await education<{ nodes: CourseProgress["nodes"] }>(`progress?learner_id=${encodeURIComponent(person.id)}&course_version_id=${encodeURIComponent(course.course_version_id)}`),
        })));
        if (live) setProgress(result);
      } catch (error) { if (live) setProgressError((error as Error).message); }
    })();
    return () => { live = false; };
  }, [student.id]);

  async function saveGoal() {
    setBusy(true); setGoalError(""); setMessage("");
    try {
      await teachingApi(`/api/v1/teaching/students/${student.id}/goal`, jsonBody({ goal }));
      onGoalSaved(student.id, goal);
      setMessage(t("学习目标已保存。"));
    } catch (error) { setGoalError((error as Error).message); }
    finally { setBusy(false); }
  }

  const labels: Record<string, string> = {
    new: t("尚无测试记录"), learning: t("正在学习"), reviewing: t("需要复习"),
    mastered: t("测试证据支持掌握"), pending_recompute: t("学习状态正在重新计算"),
  };
  return <>
    <LearningPlan studentId={student.id} goalEditor={<form onSubmit={event => { event.preventDefault(); void saveGoal(); }} className="mt-6 border-b border-[var(--border)] pb-6">
      <label htmlFor="learning-goal" className="mb-3 block font-semibold">{t("近期学习目标")}</label>
      <textarea id="learning-goal" disabled={busy} value={goal} onChange={event => { setGoal(event.target.value); setMessage(""); }} maxLength={4000} rows={3} placeholder={t("例如：理解分数之间的关系，能说明自己的解题思路。")} className="w-full border bg-[var(--card)] p-4"/>
      <button disabled={busy} className="mt-3 rounded-xl bg-[var(--primary)] px-5 py-3 text-sm text-[var(--primary-foreground)] disabled:opacity-40">{busy ? t("正在保存…") : t("保存目标")}</button>
      {message && <p role="status" className="mt-3 text-sm">{message}</p>}
      {goalError && <p role="alert" className="mt-3 text-sm text-red-700">{goalError}</p>}
    </form>}>
      <section className="my-8" aria-labelledby="knowledge-progress">
        <h2 id="knowledge-progress" className="text-lg font-semibold">{t("知识学习进展")}</h2>
        <p className="mt-2 text-sm leading-7 text-[var(--muted-foreground)]">{t("学习状态来自作答与批改，聊天不会被直接当作已掌握。")}</p>
        {progressError ? <p role="alert" className="mt-4 text-sm text-red-700">{progressError}</p>
          : !progress ? <p role="status" className="mt-4 text-sm">{t("正在读取…")}</p>
          : progress.length ? <div className="mt-5 space-y-6">{progress.map(course => <div key={course.course_version_id}>
            <h3 className="mb-3 text-sm font-semibold">{course.title}</h3>
            {course.nodes.length ? <ul className="divide-y divide-[var(--border)] rounded-xl border border-[var(--border)] bg-[var(--card)] px-4">
              {course.nodes.map((node, index) => <li key={index} className="flex flex-wrap items-center justify-between gap-2 py-3 text-sm">
                <span className="min-w-0 break-words">{node.title}</span>
                <span className={`rounded-lg px-2.5 py-1 text-xs ${node.status === "mastered" ? "bg-[var(--secondary)] text-[var(--primary)]" : "text-[var(--muted-foreground)]"}`}>{labels[node.status] || node.status}</span>
              </li>)}
            </ul> : <p className="text-sm text-[var(--muted-foreground)]">{t("尚无测试记录")}</p>}
          </div>)}</div> : <p className="mt-4 text-sm text-[var(--muted-foreground)]">{t("尚无关联课程的测试证据。聊天不会被直接当作“已掌握”。")}</p>}
      </section>
    </LearningPlan>
    <details onToggle={event => setShowEvidence(event.currentTarget.open)} className="group mt-5 rounded-2xl border border-[var(--border)] p-5">
      <summary className="flex cursor-pointer list-none items-center justify-between gap-3 font-medium [&::-webkit-details-marker]:hidden">{t("查看详细学习记录")}<ChevronDown size={18} aria-hidden="true" className="shrink-0 transition-transform group-open:rotate-180 motion-reduce:transition-none"/></summary>
      {showEvidence && <LearningEvidence studentId={student.id}/>}
    </details>
  </>;
}
