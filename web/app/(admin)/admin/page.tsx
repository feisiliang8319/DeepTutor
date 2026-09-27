"use client";

import Link from "next/link";
import { useAuthStatus } from "@/hooks/useAuthStatus";
import TeachingAdminHome from "@/components/teaching/TeachingAdminHome";
import { useTranslation } from "react-i18next";
import { ArrowUpRight, BookOpen, Cpu, Users, Wrench, Settings, Plug } from "lucide-react";

const resources = [
  { href: "/settings/models", icon: Cpu, zh: "模型与服务", en: "Models & services", detail: "配置 AI 模型、嵌入、搜索和语音服务。", english: "Configure AI models, embeddings, search and voice services." },
  { href: "/knowledge", icon: BookOpen, zh: "知识库与教材", en: "Knowledge & materials", detail: "导入教材与文档，管理知识库及检索资源。", english: "Import documents and materials; manage knowledge bases and retrieval." },
  { href: "/admin/users", icon: Users, zh: "账号与权限", en: "Accounts & access", detail: "管理学生账号，分配可用模型和资源权限。", english: "Manage student accounts and assign model and resource access." },
];
const configuration = [
  { href: "/settings/tools", icon: Wrench, zh: "工具配置", en: "Tools", detail: "搜索、推理及可调用工具", english: "Search, reasoning and available tools" },
  { href: "/settings/capabilities", icon: Settings, zh: "功能配置", en: "Capabilities", detail: "各项 AI 功能与运行参数", english: "AI capabilities and runtime options" },
  { href: "/space/mcp", icon: Plug, zh: "外部资源连接", en: "Resource connections", detail: "MCP 服务与连接配置", english: "MCP services and connections" },
  { href: "/settings", icon: Settings, zh: "系统设置", en: "System settings", detail: "网络、文档解析与更多配置", english: "Network, document parsing and other settings" },
];

function LegacyManagementHome() {
  const { i18n } = useTranslation();
  const zh = i18n.language?.startsWith("zh");
  return (
    <div className="h-full overflow-y-auto bg-[var(--background)]">
      <div className="mx-auto max-w-6xl px-5 py-8 md:px-10 md:py-12">
        <header className="mb-10 border-b border-[var(--border)] pb-8">
          <p className="mb-3 text-xs font-medium tracking-widest text-[var(--muted-foreground)]">{zh ? "家长工作台" : "PARENT WORKSPACE"}</p>
          <h1 className="font-serif text-3xl font-semibold tracking-tight text-[var(--foreground)] md:text-4xl">{zh ? "平台资源管理" : "Platform resources"}</h1>
          <p className="mt-4 max-w-2xl text-sm leading-7 text-[var(--muted-foreground)]">{zh ? "为孩子准备可用的模型、教材和工具，统一管理账号与资源权限。" : "Prepare models, materials and tools for your children, and manage accounts and resource access."}</p>
        </header>
        <div className="grid gap-10 lg:grid-cols-[1.4fr_1fr] lg:gap-12">
          <section aria-labelledby="resource-heading">
            <h2 id="resource-heading" className="mb-2 text-base font-semibold text-[var(--foreground)]">{zh ? "资源与账号" : "Resources & accounts"}</h2>
            <div className="divide-y divide-[var(--border)]">
              {resources.map(item => <Link key={item.href} href={item.href} className="group flex items-start gap-4 py-6 focus-visible:outline focus-visible:outline-2 focus-visible:outline-[var(--primary)]">
                <item.icon size={22} className="mt-1 shrink-0 text-[var(--primary)]" aria-hidden="true" />
                <div className="min-w-0 flex-1"><h3 className="font-medium text-[var(--foreground)] group-hover:text-[var(--primary)]">{zh ? item.zh : item.en}</h3><p className="mt-2 text-sm leading-6 text-[var(--muted-foreground)]">{zh ? item.detail : item.english}</p></div>
                <ArrowUpRight size={17} className="mt-1 shrink-0 text-[var(--muted-foreground)]" aria-hidden="true" />
              </Link>)}
            </div>
          </section>
          <section aria-labelledby="configuration-heading" className="lg:border-l lg:border-[var(--border)] lg:pl-10">
            <h2 id="configuration-heading" className="mb-2 text-base font-semibold text-[var(--foreground)]">{zh ? "功能与连接" : "Capabilities & connections"}</h2>
            <div className="space-y-1">{configuration.map(item => <Link key={item.href} href={item.href} className="group -mx-3 flex items-start gap-3 rounded-lg px-3 py-4 hover:bg-[var(--secondary)] focus-visible:outline focus-visible:outline-2 focus-visible:outline-[var(--primary)]">
              <item.icon size={17} className="mt-1 shrink-0 text-[var(--muted-foreground)]" aria-hidden="true" />
              <div className="min-w-0"><h3 className="text-sm font-medium text-[var(--foreground)]">{zh ? item.zh : item.en}</h3><p className="mt-1 text-xs leading-6 text-[var(--muted-foreground)]">{zh ? item.detail : item.english}</p></div>
            </Link>)}</div>
          </section>
        </div>
      </div>
    </div>
  );
}

export default function ManagementHome() {
  const {productMode,loading}=useAuthStatus();
  if(loading)return null;
  return productMode === "teaching" ? <TeachingAdminHome/> : <LegacyManagementHome/>;
}
