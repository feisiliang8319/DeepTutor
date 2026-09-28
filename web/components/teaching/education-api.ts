
import { t, useTeachingLocale } from "@/components/teaching/teaching-i18n";
export async function education<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`/api/edu/${path}`, {credentials:"same-origin", ...init});
  const data = await response.json();
  if (!response.ok) throw new Error(t(typeof data.detail === "string" ? data.detail : data.detail?.message || "请求未完成，请重试。", data.detail?.values || {}));
  return data as T;
}
export type Person = { id:string; display_name:string };
export type Course = { course_version_id:string; title:string };
