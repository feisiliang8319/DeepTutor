"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { fetchAuthStatus } from "@/lib/auth";
import { accountDestination } from "@/lib/account-navigation";

/**
 * Resolve the account workspace; keep explicit legacy chat links for students.
 * Handles backward compatibility for /?session=xxx URLs.
 */
export default function HomePage() {
  const router = useRouter();

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const sessionId = params.get("session");
    const capability = params.get("capability");
    const tools = params.getAll("tool");

    let target = sessionId ? `/home/${sessionId}` : "/home";

    const query: string[] = [];
    if (capability) query.push(`capability=${encodeURIComponent(capability)}`);
    tools.forEach((t) => query.push(`tool=${encodeURIComponent(t)}`));
    if (query.length) target += `?${query.join("&")}`;

    let active = true;
    fetchAuthStatus().then(status => {
      if (!active || !status) return;
      // Education is a separate HTML service and requires a document navigation.
      const requested = sessionId || query.length ? target : null;
      window.location.replace(accountDestination(status, requested));
    });
    return () => { active = false; };
  }, [router]);

  return null;
}
