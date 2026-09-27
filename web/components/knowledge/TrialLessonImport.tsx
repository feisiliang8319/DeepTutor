"use client";

import { useState } from "react";
import { useTranslation } from "react-i18next";
import { useAuthStatus } from "@/hooks/useAuthStatus";
import { apiFetch } from "@/lib/api";

/** Stage the authored sample for the normal, permission-checked upload flow. */
export default function TrialLessonImport({
  disabled,
  selected,
  onSelect,
}: {
  disabled: boolean;
  selected: boolean;
  onSelect: (file: File) => void;
}) {
  const { i18n } = useTranslation();
  const zh = i18n.language?.startsWith("zh");
  const auth = useAuthStatus();
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  if (auth.loading || auth.error || auth.productMode === "teaching" || (auth.enabled && !auth.isAdmin)) return null;

  const selectLesson = async () => {
    if (loading || disabled) return;
    setLoading(true);
    setError(null);
    try {
      const response = await apiFetch("/api/edu/lessons/number-structure/source");
      if (!response.ok || !response.headers.get("content-type")?.includes("text/markdown")) {
        throw new Error(zh
          ? `样章暂不可用（${response.status}），请确认试用内容已开放后重试。`
          : `Sample unavailable (${response.status}). Check that trial content is available, then retry.`);
      }
      const text = await response.text();
      onSelect(new File([text], "deeptutor-trial-number-structure.md", { type: "text/markdown" }));
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  };

  return (
    <section aria-labelledby="trial-lesson-heading" className="border-y border-[var(--border)] py-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0 flex-1 basis-56">
          <h3 id="trial-lesson-heading" className="text-[13px] font-medium text-[var(--foreground)]">
            {zh ? "进阶数学试用样章" : "Advanced mathematics · trial lesson"}
          </h3>
          <p className="mt-1 text-[12px] leading-6 text-[var(--muted-foreground)]">
            {zh ? "因数与数的结构：完整讲解、提示、表格和图形说明。样章待人工审查，导入不会激活新课程。" : "Factors and the structure of numbers: explanations, hints, tables and diagram descriptions. Pending human review; importing does not activate a course."}
          </p>
        </div>
        <button type="button" onClick={() => void selectLesson()} disabled={disabled || loading}
          className="shrink-0 whitespace-nowrap rounded-lg border border-[var(--border)] px-3 py-2 text-[12px] font-medium text-[var(--foreground)] hover:bg-[var(--secondary)] focus-visible:outline focus-visible:outline-2 focus-visible:outline-[var(--primary)] disabled:cursor-not-allowed disabled:opacity-40">
          {loading ? (zh ? "读取中…" : "Loading…") : (zh ? "加入待上传列表" : "Add to upload list")}
        </button>
      </div>
      <p className="mt-2 text-[11.5px] leading-6 text-[var(--muted-foreground)]">
        {zh ? "加入后点击下方“上传”。索引完成后，学生可在工作台选择已获授权的知识库提问。" : "Then click Upload below. Once indexing finishes, students can select the assigned knowledge base in their workspace and ask questions."}
        {" "}<a className="whitespace-nowrap underline underline-offset-2" href="/api/edu/lessons/number-structure" target="_blank" rel="noreferrer">{zh ? "阅读样章" : "Read lesson"}</a>
        {" · "}<a className="whitespace-nowrap underline underline-offset-2" href="/admin/users">{zh ? "分配资源权限" : "Assign resource access"}</a>
      </p>
      {selected && <p role="status" className="mt-2 text-[12px] text-[var(--foreground)]">{zh ? "已加入待上传列表；尚未上传或索引。" : "Added to the upload list; not yet uploaded or indexed."}</p>}
      {error && <p role="alert" className="mt-2 text-[12px] text-red-700 dark:text-red-300">{error}</p>}
    </section>
  );
}
