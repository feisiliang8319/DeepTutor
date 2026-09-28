"use client";
import { t, useTeachingLocale } from "@/components/teaching/teaching-i18n";

import { PersonalizeButton, TeachingLanguageSelector } from "./TeachingPreferences";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { MessageSquare, ClipboardCheck, BookOpen, Users, Settings, Brain, GraduationCap, LayoutDashboard } from "lucide-react";
import { LogoutButton } from "@/components/auth/LogoutButton";
import { ProfileLink } from "@/components/auth/ProfileLink";
import { useSidebarDrawer } from "@/components/layout/AppShell";

export default function TeachingSidebar({ role }: { role: string }) {
  useTeachingLocale();

const student = [
  { href: "/home", label: "Chat", detail: t("学习与讲解"), icon: MessageSquare },
  { href: "/quiz", label: "Quiz", detail: t("测试与结果"), icon: ClipboardCheck },
];
const parent = [
  { href: "/parent", label: t("学习进展"), detail: t("每个孩子的成长"), icon: GraduationCap },
  { href: "/parent/students", label: t("学生账号"), detail: t("账号、课程与可用范围"), icon: Users },
  { href: "/parent/materials", label: t("家庭资料"), detail: t("教材与参考资料"), icon: BookOpen },
];
const admin = [
  { href: "/admin", label: t("管理总览"), icon: LayoutDashboard },
  { href: "/admin/materials", label: t("知识库"), icon: BookOpen },
  { href: "/admin/teaching", label: t("教学数据与策略"), icon: GraduationCap },
  { href: "/settings/models", label: t("模型配置"), icon: Settings },
  { href: "/admin/memory", label: t("学习记忆"), icon: Brain },
  { href: "/admin/users", label: t("账户与访问"), icon: Users },
];

  const pathname = usePathname();
  const drawer = useSidebarDrawer();
  const entries = role === "student" ? student : role === "parent" ? parent : admin;
  const active = entries.filter(e => pathname === e.href || pathname.startsWith(e.href + "/")).sort((a,b) => b.href.length-a.href.length)[0]?.href;
  return <aside className="flex h-dvh w-[220px] flex-col border-r border-[var(--border)] bg-[var(--secondary)]">
    <div className="px-5 pb-8 pt-7"><p className="text-xl font-semibold">DeepTutor</p>{process.env.NEXT_PUBLIC_TEACHING_PREVIEW==="true"&&<p className="mt-2 text-xs text-[var(--primary)]">{t("隔离预览 · 合成数据")}</p>}<p className="mt-2 text-xs text-[var(--muted-foreground)]">{role === "student" ? t("专注每一次理解") : role === "parent" ? t("家长工作台") : t("教学系统管理")}</p></div>
    <nav aria-label={t("教学导航")} className="space-y-2 px-3">{entries.map(e => <Link key={e.href} href={e.href} onClick={() => drawer?.close()} aria-current={e.href===active ? "page" : undefined} className={`flex gap-3 rounded-lg p-3 focus-visible:outline focus-visible:outline-2 ${e.href===active ? "bg-[var(--background)] text-[var(--foreground)]" : "text-[var(--muted-foreground)] hover:bg-[var(--background)]"}`}><e.icon size={19} aria-hidden="true"/><span className="text-sm font-medium">{e.label}{"detail" in e && <span className="mt-1 block text-xs font-normal text-[var(--muted-foreground)]">{String(e.detail)}</span>}</span></Link>)}</nav>
    <div className="mt-auto border-t border-[var(--border)] p-3">{role === "student" && <PersonalizeButton/>}<TeachingLanguageSelector/><ProfileLink/><LogoutButton/></div>
  </aside>;
}
