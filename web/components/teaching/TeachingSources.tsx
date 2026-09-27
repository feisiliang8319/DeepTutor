"use client";
import type { MessageItem } from "@/context/UnifiedChatContext";
import { t } from "./teaching-i18n";

export default function TeachingSources({ events }: Pick<MessageItem, "events">) {
  const sources = new Map<string, { title: string; excerpt: string }>();
  for (const event of events || []) {
    if (event.type !== "sources" || !Array.isArray(event.metadata?.sources)) continue;
    for (const value of event.metadata.sources) {
      if (!value || typeof value !== "object") continue;
      const source = value as Record<string, unknown>;
      const title = typeof source.title === "string" ? source.title.split(/[\\/]/).pop() || "" : "";
      if (title && !sources.has(title)) sources.set(title, { title, excerpt: typeof source.content === "string" ? source.content.slice(0, 600) : "" });
    }
  }
  if (!sources.size) return null;
  return <details className="mt-4 rounded-xl border border-[var(--border)] bg-[var(--card)] px-4 py-3 text-sm">
    <summary className="cursor-pointer font-medium">{t("参考资料")} · {sources.size}</summary>
    <div className="mt-4 space-y-4">{Array.from(sources.values()).map(source => <div key={source.title}>
      <p className="break-words font-medium">{source.title}</p>
      {source.excerpt && <p className="mt-2 whitespace-pre-wrap break-words text-sm leading-7 text-[var(--muted-foreground)]">{source.excerpt}</p>}
    </div>)}</div>
  </details>;
}
