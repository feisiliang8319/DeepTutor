"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { ArrowLeft, CheckCircle2, KeyRound, Loader2, PlugZap } from "lucide-react";
import { t, useTeachingLocale } from "./teaching-i18n";

type Settings = {
  key_configured: boolean;
  model: string;
  material_processing_enabled: false;
  last_test_at: string | null;
  last_test_status: string | null;
};
const endpoint = "/api/v1/teaching/intelligence";
const errorText: Record<string, string> = {
  invalid_key: "密钥无效，请检查后重新保存。",
  not_configured: "请先保存 Jev 专用 API Key。",
  rate_limited: "服务繁忙或调用受限，请稍后重试。",
  timeout: "连接超时，请稍后重试。",
  provider_unavailable: "暂时无法连接 TypeSafe，请稍后重试。",
  invalid_response: "服务返回格式异常，连接测试未通过。",
  test_inconclusive: "已收到回复，但样例判断未通过，请稍后重试。",
  configuration_changed: "密钥已变更，请重新测试。",
  invalid_request: "提交格式有误，请检查密钥。",
};
async function request<T>(path: string, method = "GET", body?: unknown): Promise<T> {
  const response = await fetch(endpoint + path, {
    method, credentials: "same-origin", cache: "no-store",
    headers: body === undefined ? undefined : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const data = await response.json().catch(() => null);
  if (!response.ok) throw new Error(response.status === 401 || response.status === 403
    ? "请以管理员身份重新登录。"
    : errorText[data?.detail?.code] || "操作未完成，请稍后重试。");
  return data as T;
}
export default function MaterialIntelligence() {
  const { i18n } = useTeachingLocale();
  const [settings, setSettings] = useState<Settings | null>(null);
  const [key, setKey] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  useEffect(() => {
    let active = true;
    request<Settings>("/settings").then(value => { if (active) setSettings(value); })
      .catch(() => { if (active) setError("配置加载失败，请刷新页面重试。"); });
    return () => { active = false; };
  }, []);
  async function save() {
    setBusy(true); setError(""); setNotice("");
    try {
      setSettings(await request<Settings>("/settings", "PUT", { api_key: key.trim() }));
      setKey(""); setNotice("密钥已保存，可开始测试连接。");
    } catch (cause) { setError(cause instanceof Error ? cause.message : "操作未完成，请稍后重试。"); }
    finally { setBusy(false); }
  }
  async function test() {
    setBusy(true); setError(""); setNotice("");
    try {
      await request("/test", "POST", {});
      setNotice("中英文样例测试通过，Jev 连接正常。");
    } catch (cause) { setError(cause instanceof Error ? cause.message : "操作未完成，请稍后重试。"); }
    finally {
      try { setSettings(await request<Settings>("/settings")); }
      catch { setSettings(null); setError("配置加载失败，请刷新页面重试。"); }
      setBusy(false);
    }
  }
  const connected = settings?.last_test_status === "connected";
  const inputClass = "mt-3 w-full rounded-xl border border-[var(--border)] bg-[var(--background)] px-4 py-3 text-sm outline-none focus-visible:ring-2 focus-visible:ring-[var(--primary)]";
  const buttonClass = "inline-flex min-h-11 items-center justify-center gap-2 rounded-xl px-5 py-3 text-sm font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--primary)] focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50";
  return <section className="mx-auto max-w-3xl pb-8">
    <Link href="/settings/models" className="inline-flex items-center gap-2 text-sm text-[var(--muted-foreground)] hover:text-[var(--foreground)]"><ArrowLeft size={16}/>{t("返回模型配置")}</Link>
    <div className="mt-7 flex items-start gap-4">
      <div className="rounded-2xl bg-[var(--accent)] p-3 text-[var(--primary)]"><PlugZap size={26}/></div>
      <div><h1 className="text-2xl font-semibold leading-snug">{t("资料智能处理（Jev）")}</h1>
        <p className="mt-2 text-sm leading-7 text-[var(--muted-foreground)]">{t("配置 Jev 专用密钥，并用中英文固定样例测试连接。")}</p></div>
    </div>
    <div className="mt-7 rounded-2xl border border-[var(--border)] bg-[var(--accent)] p-5 text-sm leading-7">
      <p className="font-medium">{t("当前阶段：连接配置")}</p>
      <p className="mt-1 text-[var(--muted-foreground)]">{t("资料处理尚未启用。连接测试只发送系统预设的两句三角形样例，不读取或发送教材、家庭资料或学生记录。")}</p>
    </div>
    <form className="mt-6 rounded-2xl border border-[var(--border)] bg-[var(--card)] p-5 sm:p-7" onSubmit={event => { event.preventDefault(); if (!busy && settings && key.trim()) void save(); }}>
      <div className="flex flex-wrap items-center justify-between gap-3"><h2 className="flex items-center gap-2 font-medium"><KeyRound size={19}/>{t("专用 API Key")}</h2>
        <span className="rounded-full bg-[var(--accent)] px-3 py-1 text-xs">{settings ? t(settings.key_configured ? "已保存密钥" : "尚未配置") : t("正在加载配置")}</span></div>
      <label htmlFor="jev-key" className="mt-6 block text-sm font-medium">{t("TypeSafe API Key")}</label>
      <input id="jev-key" name="jev-api-key" type="password" autoComplete="new-password" spellCheck={false} maxLength={4096} value={key} onChange={event => { setKey(event.target.value); setNotice(""); }} disabled={busy || !settings} className={inputClass} placeholder={t(settings?.key_configured ? "输入新密钥以替换已保存的密钥" : "填写为 DeepTutor 申请的专用密钥")} aria-describedby="jev-key-help"/>
      <p id="jev-key-help" className="mt-3 text-xs leading-6 text-[var(--muted-foreground)]">{t("密钥仅保存在服务器，保存后不会显示；留空不会修改现有密钥。")}</p>
      <div className="mt-6 flex flex-col gap-3 sm:flex-row">
        <button type="submit" disabled={busy || !settings || !key.trim()} className={buttonClass + " bg-[var(--primary)] text-[var(--primary-foreground)]"}>{busy && <Loader2 size={16} className="animate-spin motion-reduce:animate-none"/>}{t("保存密钥")}</button>
        <button type="button" onClick={() => void test()} disabled={busy || !settings?.key_configured || !!key.trim()} className={buttonClass + " border border-[var(--border)] hover:bg-[var(--accent)]"}>{t("测试连接")}</button>
      </div>
      {!!key.trim() && <p className="mt-3 text-xs text-[var(--muted-foreground)]">{t("请先保存密钥，再测试连接。")}</p>}
    </form>
    <div aria-live="polite" aria-atomic="true" className="mt-5 text-sm leading-7">
      {error && <p role="alert" className="rounded-xl border border-[var(--border)] bg-[var(--accent)] p-4">{t(error)}</p>}
      {notice && <p className="flex items-center gap-2 text-[var(--primary)]"><CheckCircle2 size={18}/>{t(notice)}</p>}
    </div>
    {settings && <dl className="mt-6 space-y-3 text-sm">
      <div className="flex flex-wrap justify-between gap-2"><dt className="text-[var(--muted-foreground)]">{t("服务模型")}</dt><dd>{settings.model}</dd></div>
      <div className="flex flex-wrap justify-between gap-2"><dt className="text-[var(--muted-foreground)]">{t("最近连接测试")}</dt><dd>{t(!settings.last_test_at ? "尚未测试" : connected ? "连接正常" : "测试未通过")}</dd></div>
      {settings.last_test_at && <div className="text-right text-xs text-[var(--muted-foreground)]">{new Date(settings.last_test_at).toLocaleString(i18n.language)}</div>}
    </dl>}
  </section>;
}
