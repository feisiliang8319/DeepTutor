import type { AuthStatus } from "./auth";

type Session = Pick<AuthStatus, "enabled" | "authenticated" | "role" | "product_mode">;

function teachingPath(role: string | undefined, pathname: string): boolean {
  if (pathname === "/profile") return true;
  if (role === "student") return /^\/(home(?:\/|$)|quiz(?:\/|$))/.test(pathname);
  if (role === "parent") return /^\/parent(?:\/|$)/.test(pathname);
  if (role === "admin") return /^\/(admin(?:\/|$)|knowledge(?:\/|$)|settings\/(?:models|llm|embedding|search)(?:\/|$))/.test(pathname);
  return false;
}

export function teachingHome(role: string | undefined): string {
  return role === "admin" ? "/admin" : role === "parent" ? "/parent" : "/home";
}
export type AccountArea = "workspace" | "utility" | "management";

// These are resource configuration surfaces, not learning activities.
const MANAGEMENT_PATHS = [
  "/admin", "/settings", "/knowledge", "/profile",
  "/space/skills", "/space/mcp", "/space/personas", "/space/cli-apps",
];

export function isManagementSession(status: Session): boolean {
  return status.enabled && status.authenticated && status.role === "admin";
}

export function isManagementPath(pathname: string): boolean {
  return MANAGEMENT_PATHS.some(path => pathname === path || pathname.startsWith(path + "/"));
}

function localDestination(value: string | null): string | null {
  if (!value || !value.startsWith("/") || value.startsWith("//") || /[\\\u0000-\u0020]/.test(value)) return null;
  const base = "https://deeptutor.invalid";
  const url = new URL(value, base);
  if (url.origin !== base || /^\/(login|register)(\/|$)/.test(url.pathname)) return null;
  return url.pathname + url.search + url.hash;
}

export function accountDestination(status: Session, requested: string | null = null): string {
  const destination = localDestination(requested);
  const pathname = destination ? new URL(destination, "https://deeptutor.invalid").pathname : "/";
  if (status.product_mode === "teaching") {
    return destination && teachingPath(status.role, pathname) ? destination : teachingHome(status.role);
  }
  if (isManagementSession(status)) {
    return destination && isManagementPath(pathname) ? destination : "/admin";
  }
  if (pathname === "/admin" || pathname.startsWith("/admin/")) return "/home";
  return destination && pathname !== "/" && pathname !== "/practice" ? destination : "/home";
}

export function accountAreaRedirect(status: Session, area: AccountArea, pathname: string): string | null {
  if (status.enabled && !status.authenticated) return "/login?next=" + encodeURIComponent(pathname);
  if (status.product_mode === "teaching") {
    return teachingPath(status.role, pathname) ? null : teachingHome(status.role);
  }
  const management = isManagementSession(status);
  if (area === "management" && !management) return accountDestination(status);
  if (management && (area === "workspace" || !isManagementPath(pathname))) return "/admin";
  return null;
}
