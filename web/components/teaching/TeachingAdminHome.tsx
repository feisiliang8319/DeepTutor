"use client";
import { t, useTeachingLocale } from "@/components/teaching/teaching-i18n";

import Link from "next/link";
import { BookOpen, Users, Cpu, GraduationCap, Brain, ArrowUpRight } from "lucide-react";
export default function TeachingAdminHome(){
  useTeachingLocale();

 const entries=[
  {href:"/admin/materials",icon:BookOpen,title:t("知识库"),detail:t("注入主库教材，查看家庭资料与共享范围。")},
  {href:"/admin/teaching",icon:GraduationCap,title:t("教学策略"),detail:t("定义导师职责、讲解方式与后台模型路由。")},
  {href:"/settings/models",icon:Cpu,title:t("模型与服务"),detail:t("配置可分配给家长的执行资源。")},
  {href:"/admin/memory",icon:Brain,title:t("学习证据与记忆"),detail:t("查看可追溯的学习状态，保留原始作答。")},
  {href:"/admin/users",icon:Users,title:t("家长账户与授权"),detail:t("分配家长权限上限；学生账户只供查阅。")},
 ];
 return <div className="h-full overflow-auto"><main className="mx-auto max-w-5xl px-6 py-10 md:px-10"><p className="text-sm text-[var(--muted-foreground)]">{t("DeepTutor · 管理端")}</p><h1 className="mt-3 text-3xl font-semibold">{t("为教学准备好一切")}</h1><p className="mt-4 max-w-2xl text-sm leading-7 text-[var(--muted-foreground)]">{t("资源与教学规则在这里统一管理。家长负责孩子的账户和学习范围，学生专注于学习。")}</p><div className="mt-10 divide-y divide-[var(--border)]">{entries.map(e=><Link key={e.href} href={e.href} className="group flex items-center gap-5 py-6"><e.icon className="text-[var(--primary)]" size={24}/><div className="flex-1"><h2 className="font-semibold">{e.title}</h2><p className="mt-2 text-sm leading-6 text-[var(--muted-foreground)]">{e.detail}</p></div><ArrowUpRight size={18}/></Link>)}</div></main></div>;
}
