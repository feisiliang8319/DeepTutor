"use client";

import { useEffect, useState } from "react";
import { t, useTeachingLocale } from "./teaching-i18n";
import { teachingApi, jsonBody, type Account } from "./api";

type Material = { id: string; name: string; owner_id: string; owner_name?: string; read_only: boolean; shared: boolean; students?: string[] | null };

function MaterialScope({ material, students, administrator, onSaved }: {
  material: Material; students: Account[]; administrator: boolean; onSaved: () => Promise<void>;
}) {
  const [selected, setSelected] = useState<string[] | null>(material.students ?? null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  useEffect(() => { setSelected(material.students ?? null); }, [material]);
  async function save() {
    setBusy(true); setError(""); setMessage("");
    try {
      // Administrators promote resources; only parents choose family recipients.
      const body = administrator ? { shared: !material.shared } : { students: selected, shared: material.shared };
      await teachingApi(`/api/v1/teaching/materials/${encodeURIComponent(material.owner_id)}/${encodeURIComponent(material.name)}/scope`, jsonBody(body));
      await onSaved();
      setMessage(t("资料范围已保存。"));
    } catch (e) { setError((e as Error).message); }
    finally { setBusy(false); }
  }
  return <article className="rounded-2xl border border-[var(--border)] bg-[var(--card)] p-5">
    <h3 className="font-semibold">{material.name === "family-materials" ? t("家庭资料") : material.name}</h3>
    {administrator && <p className="mt-2 text-sm">{t("所属家长")}：{material.owner_name || material.owner_id}</p>}
    <p className="mt-2 text-sm text-[var(--muted-foreground)]">{material.shared ? t("已进入共享目录；其他家庭仍须获得管理员授权。") : t("家庭私有资料")}</p>
    {administrator ? <p className="mt-3 text-sm leading-6 text-[var(--muted-foreground)]">{t("加入共享目录后，可分配给其他家长。家庭内的学生范围由资料所属家长管理。")}</p> : <fieldset disabled={busy} className="mt-5 space-y-3">
      <legend className="mb-3 text-sm font-medium">{t("哪些孩子可以使用")}</legend>
      <label className="flex items-center gap-3 text-sm"><input type="checkbox" checked={selected === null} onChange={e => setSelected(e.target.checked ? null : [])} className="h-5 w-5 accent-[var(--primary)]"/>{t("家中所有孩子，包括今后新增的账号")}</label>
      {selected !== null && <div className="space-y-3 pl-2">{students.map(student => <label key={student.id} className="flex items-center gap-3 text-sm"><input type="checkbox" checked={selected.includes(student.id)} onChange={e => setSelected(e.target.checked ? [...selected, student.id] : selected.filter(id => id !== student.id))} className="h-5 w-5 accent-[var(--primary)]"/>{student.username}</label>)}</div>}
      {selected?.length === 0 && <p className="text-sm text-[var(--muted-foreground)]">{t("暂不向任何学生开放。")}</p>}
    </fieldset>}
    <button disabled={busy} onClick={save} className="mt-5 rounded-xl border border-[var(--border)] px-4 py-2 text-sm disabled:opacity-50">{busy ? t("正在保存…") : administrator ? material.shared ? t("撤出共享目录") : t("加入共享目录") : t("保存资料范围")}</button>
    {error && <p role="alert" className="mt-3 text-sm text-red-700">{error}</p>}
    {message && <p role="status" className="mt-3 text-sm">{message}</p>}
  </article>;
}

export default function MaterialScopes({ administrator = false, refreshKey = 0 }: { administrator?: boolean; refreshKey?: number }) {
  useTeachingLocale();
  const [materials, setMaterials] = useState<Material[]>([]);
  const [students, setStudents] = useState<Account[]>([]);
  const [error, setError] = useState("");
  const [loaded, setLoaded] = useState(false);
  async function refresh() {
    const [sources, family] = await Promise.all([
      teachingApi<{ materials: Material[] }>("/api/v1/teaching/materials"),
      administrator ? Promise.resolve({ students: [] as Account[] }) : teachingApi<{ students: Account[] }>("/api/v1/teaching/students"),
    ]);
    setMaterials(sources.materials.filter(material => administrator || !material.read_only));
    setStudents(family.students); setLoaded(true); setError("");
  }
  useEffect(() => { refresh().catch(e => setError(e.message)); }, [administrator, refreshKey]);
  return <section className="mt-8" aria-label={t("资料可见范围")}>
    <h2 className="mb-4 text-xl font-semibold">{administrator ? t("家庭资料与共享目录") : t("资料可见范围")}</h2>
    {error && <p role="alert" className="mb-4 text-sm text-red-700">{error}</p>}
    {!loaded && !error && <p className="text-sm text-[var(--muted-foreground)]">{t("正在读取资料范围…")}</p>}
    {loaded && !materials.length && <p className="text-sm text-[var(--muted-foreground)]">{t("还没有家庭资料。上传后可在这里设置使用范围。")}</p>}
    <div className="space-y-4">{materials.map(material => <MaterialScope key={material.id} material={material} students={students} administrator={administrator} onSaved={refresh}/>)}</div>
  </section>;
}
