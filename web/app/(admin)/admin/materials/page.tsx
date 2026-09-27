"use client";
import Link from "next/link";
import MaterialScopes from "@/components/teaching/MaterialScopes";
import { t, useTeachingLocale } from "@/components/teaching/teaching-i18n";
export default function MaterialsPage() {
  useTeachingLocale();
  return <main className="h-full overflow-auto"><div className="mx-auto max-w-5xl px-5 py-10 md:px-10">
    <h1 className="text-3xl font-semibold">{t("知识库与资料")}</h1>
    <p className="mt-4 max-w-2xl text-sm leading-7 text-[var(--muted-foreground)]">{t("主库与家庭资料统一检索，保留来源与授权范围。学生无需选择知识库。")}</p>
    <Link href="/knowledge" className="mt-6 inline-flex rounded-xl bg-[var(--primary)] px-5 py-3 text-sm text-[var(--primary-foreground)]">{t("管理主库教材")}</Link>
    <MaterialScopes administrator/>
  </div></main>;
}
