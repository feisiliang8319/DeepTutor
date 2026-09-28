"use client";
import Link from "next/link";
import { Brain, Database, Search, Mic, PlugZap, ArrowUpRight } from "lucide-react";
import { t, useTeachingLocale } from "./teaching-i18n";
export default function TeachingModels() {
  useTeachingLocale();
  const entries = [
    { href: "/settings/stt", icon: Mic, title: t("语音输入"), detail: t("将学生的语音转成可编辑文字，由学生确认后发送。") },
    { href: "/settings/llm", icon: Brain, title: t("教学模型"), detail: t("配置可供导师调用、并可分配给家长的语言模型。") },
    { href: "/settings/embedding", icon: Database, title: t("资料检索模型"), detail: t("为教材建立索引，学生无需配置。") },
    { href: "/admin/material-intelligence", icon: PlugZap, title: t("资料智能处理（Jev）"), detail: t("配置 Jev 专用密钥，并用中英文固定样例测试连接。") },
    { href: "/settings/search", icon: Search, title: t("研究搜索服务"), detail: t("在获准的研究范围内扩展知识并引用来源。") },
  ];
  return <section><h1 className="text-2xl font-semibold">{t("模型与服务")}</h1>
    <p className="mt-3 text-sm leading-7 text-[var(--muted-foreground)]">{t("这里只配置教学所需的执行资源；导师如何使用它们，由教学策略统一决定。")}</p>
    <div className="mt-7 divide-y divide-[var(--border)]">{entries.map(entry => <Link key={entry.href} href={entry.href} className="flex items-center gap-4 py-6">
      <entry.icon className="shrink-0 text-[var(--primary)]" size={22}/><div className="flex-1"><h2 className="font-medium">{entry.title}</h2><p className="mt-2 text-sm leading-6 text-[var(--muted-foreground)]">{entry.detail}</p></div><ArrowUpRight size={17}/>
    </Link>)}</div><Link href="/admin/teaching" className="mt-5 inline-block text-sm underline">{t("查看实际教学策略")}</Link>
  </section>;
}
