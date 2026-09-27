"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useTranslation } from "react-i18next";
import { BookOpen, Cpu, LayoutGrid, Settings, Users, Wrench } from "lucide-react";
import { useSidebarDrawer } from "@/components/layout/AppShell";
import { LogoutButton } from "@/components/auth/LogoutButton";
import { ProfileLink } from "@/components/auth/ProfileLink";

const entries = [
  { href: "/admin", zh: "管理首页", en: "Management home", icon: LayoutGrid },
  { href: "/settings/models", zh: "模型与服务", en: "Models & services", icon: Cpu },
  { href: "/knowledge", zh: "知识库与教材", en: "Knowledge & materials", icon: BookOpen },
  { href: "/settings/tools", zh: "工具配置", en: "Tools", icon: Wrench },
  { href: "/admin/users", zh: "账号与权限", en: "Accounts & access", icon: Users },
  { href: "/settings", zh: "系统设置", en: "Settings", icon: Settings },
];

export default function ManagementSidebar() {
  const pathname = usePathname();
  const { i18n } = useTranslation();
  const zh = i18n.language?.startsWith("zh");
  const drawer = useSidebarDrawer();
  const active = entries.filter(item => pathname === item.href || pathname.startsWith(item.href + "/"))
    .sort((a, b) => b.href.length - a.href.length)[0]?.href;

  return (
    <aside className="flex h-dvh w-[220px] shrink-0 flex-col border-r border-[var(--border)]/60 bg-[var(--secondary)]">
      <Link href="/admin" onClick={() => drawer?.close()} className="px-5 pb-6 pt-7">
        <span className="font-serif text-xl font-semibold text-[var(--foreground)]">DeepTutor</span>
        <span className="mt-2 block text-xs text-[var(--muted-foreground)]">{zh ? "家长 · 资源管理" : "Parent · Resource management"}</span>
      </Link>
      <nav aria-label={zh ? "资源管理导航" : "Resource management navigation"} className="space-y-1 px-2">
        {entries.map(item => (
          <Link key={item.href} href={item.href} onClick={() => drawer?.close()}
            aria-current={active === item.href ? "page" : undefined}
            className={`flex items-center gap-3 rounded-lg px-3 py-2.5 text-sm transition-colors focus-visible:outline focus-visible:outline-2 focus-visible:outline-[var(--primary)] ${active === item.href ? "bg-[var(--accent)] font-medium text-[var(--foreground)]" : "text-[var(--muted-foreground)] hover:bg-[var(--background)] hover:text-[var(--foreground)]"}`}>
            <item.icon size={17} aria-hidden="true" />{zh ? item.zh : item.en}
          </Link>
        ))}
      </nav>
      <div className="mt-auto border-t border-[var(--border)]/60 p-2">
        <ProfileLink /><LogoutButton />
      </div>
    </aside>
  );
}
