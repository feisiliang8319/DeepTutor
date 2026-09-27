"use client";

import { useEffect, type ReactNode } from "react";
import { usePathname } from "next/navigation";
import { useTranslation } from "react-i18next";
import { useAuthStatus } from "@/hooks/useAuthStatus";
import { accountAreaRedirect, isManagementSession, type AccountArea } from "@/lib/account-navigation";
import AppShell from "@/components/layout/AppShell";
import ManagementSidebar from "@/components/sidebar/ManagementSidebar";
import UtilitySidebar from "@/components/sidebar/UtilitySidebar";
import WorkspaceSidebar from "@/components/sidebar/WorkspaceSidebar";

/** Resolve the authenticated account before mounting either mode's content. */
export default function AccountShell({ area, children }: { area: AccountArea; children: ReactNode }) {
  const auth = useAuthStatus();
  const pathname = usePathname();
  const { i18n } = useTranslation();
  const zh = i18n.language?.startsWith("zh");
  const status = { ...auth, role: auth.isAdmin ? "admin" : "user" };
  const redirect = auth.loading || auth.error ? null : accountAreaRedirect(status, area, pathname);

  useEffect(() => {
    if (redirect) window.location.replace(redirect);
  }, [redirect]);

  if (auth.error) return (
    <div role="alert" className="p-8 text-[var(--foreground)]">
      <p>{zh ? "暂时无法确认账号身份。请重试。" : "Unable to verify your account. Please retry."}</p>
      <button onClick={() => window.location.reload()} className="mt-4 rounded-lg border border-[var(--border)] px-4 py-2">
        {zh ? "重试" : "Retry"}
      </button>
    </div>
  );
  if (auth.loading || redirect) return <p role="status" className="p-8 text-sm text-[var(--muted-foreground)]">{zh ? "正在打开工作台…" : "Opening your workspace…"}</p>;

  const sidebar = isManagementSession(status) ? <ManagementSidebar /> : area === "workspace" ? <WorkspaceSidebar /> : <UtilitySidebar />;
  return <AppShell sidebar={sidebar}>{children}</AppShell>;
}
