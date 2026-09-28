"use client";

import { useState } from "react";
import { logout } from "@/lib/auth";
import { jsonBody, teachingApi } from "./api";
import { t, useTeachingLocale } from "./teaching-i18n";

export default function PasswordForm({ userId, username, reset = false, initialize = false, required = false, onClose }: {
  userId: string; username: string; reset?: boolean; initialize?: boolean; required?: boolean; onClose?: () => void;
}) {
  useTeachingLocale();
  const [current, setCurrent] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [saved, setSaved] = useState(false);
  const field = "mt-2 w-full rounded-xl border border-[var(--border)] bg-[var(--background)] px-4 py-3 text-sm";

  async function save() {
    if (busy) return;
    setError("");
    if (!initialize && password !== confirm) { setError(t("两次输入的密码不一致。")); return; }
    if (new TextEncoder().encode(password).length > 72) { setError(t("密码不能超过72个字节，请缩短后重试。")); return; }
    setBusy(true);
    try {
      if (initialize) await teachingApi(`/api/v1/teaching/accounts/${encodeURIComponent(userId)}/initialize-password`, {method:"POST"});
      else await teachingApi(`/api/v1/teaching/accounts/${encodeURIComponent(userId)}/password`, jsonBody({
        new_password: password, ...(!reset ? { current_password: current } : {}),
      }));
      setCurrent(""); setPassword(""); setConfirm(""); setSaved(true);
      if (!reset && !initialize) { await logout(); window.location.replace("/login"); }
    } catch (e) {
      const message = (e as Error).message;
      setError(message === "The current password is incorrect" ? t("当前密码不正确。") : message === "The new password must differ from the current password" ? t("新密码不能与当前密码相同。") : t("密码未能更新，请重试或联系管理员。"));
    } finally { setBusy(false); }
  }

  return <section className="mt-5 rounded-2xl border border-[var(--border)] bg-[var(--secondary)] p-5">
    <h2 className="text-base font-semibold">{initialize ? t("初始化密码") : reset ? t("重置家长密码") : t("修改我的密码")} · {username}</h2>
    {required && <p role="alert" className="mt-3 rounded-xl border border-[var(--border)] p-4 text-sm leading-6">{t("这是初始化密码。请先设置自己的新密码，再继续管理孩子的学习。")}</p>}
    <p className="mt-2 text-sm leading-6 text-[var(--muted-foreground)]">{initialize ? t("将此家长的密码设为12345678，原登录会话立即失效。家长登录后必须设置新密码，才能继续使用。") : reset
      ? t("设置新的登录密码后，该家长原有登录会话将失效。请私下告知家长新密码。")
      : t("输入当前密码并设置新密码。保存后需要重新登录；忘记密码请联系管理员重置。")}</p>
    {saved ? <p role="status" className="mt-4 text-sm">{t("密码已更新，旧登录会话已失效。")}</p> : <form onSubmit={e => { e.preventDefault(); void save(); }} className="mt-5 space-y-4">
      {!initialize && <fieldset disabled={busy} className="space-y-4">
        {!reset && <label className="block text-sm">{t("当前密码")}<input required type="password" autoComplete="current-password" value={current} onChange={e => setCurrent(e.target.value)} className={field}/></label>}
        <label className="block text-sm">{t("新密码（至少8个字符）")}<input required minLength={8} type="password" autoComplete="new-password" value={password} onChange={e => setPassword(e.target.value)} className={field}/></label>
        <label className="block text-sm">{t("确认新密码")}<input required minLength={8} type="password" autoComplete="new-password" value={confirm} onChange={e => setConfirm(e.target.value)} className={field}/></label>
      </fieldset>}
      {error && <p role="alert" className="text-sm text-red-700">{error}</p>}
      <button disabled={busy} className="rounded-xl bg-[var(--primary)] px-5 py-3 text-sm text-[var(--primary-foreground)] disabled:opacity-50">{busy ? t("正在保存…") : initialize ? t("确认初始化密码") : t("保存新密码")}</button>
    </form>}
    {onClose && <button disabled={busy} onClick={onClose} className="mt-4 text-sm underline">{t("关闭")}</button>}
  </section>;
}
