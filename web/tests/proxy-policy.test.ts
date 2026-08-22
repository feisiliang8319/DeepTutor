import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import path from "node:path";

// Unit tests for the pure middleware routing policy (web/lib/proxy-policy.ts).
// The policy is deliberately decoupled from `next/server`, so it can be
// exercised here without booting the Next runtime. proxy.ts itself is a thin
// adapter that maps these decisions onto NextResponse.

import {
  CODEX_CALLBACK_API_PATH,
  CODEX_CALLBACK_PATH,
  classifyToken,
  isAuthExempt,
  isBackendPath,
  isCodexCallbackPath,
  isEducationPath,
} from "../lib/proxy-policy";

function makeToken(payload: Record<string, unknown>): string {
  const encode = (value: unknown) =>
    Buffer.from(JSON.stringify(value)).toString("base64url");
  return `${encode({ alg: "HS256" })}.${encode(payload)}.signature`;
}

test("isBackendPath matches /api and /ws paths only", () => {
  assert.equal(isBackendPath("/api/v1/knowledge/list"), true);
  assert.equal(isBackendPath("/ws/chat"), true);
  assert.equal(isBackendPath("/home"), false);
  assert.equal(isBackendPath("/apidocs"), false); // no trailing slash → not backend
  assert.equal(isBackendPath("/logo.png"), false);
});

// 钉住"练习页不被主后端截走"。中间件跑在 next.config.js 的 rewrite 之前，
// 所以 /api/edu/* 一旦被 isBackendPath 认领，就会被转到 8011（那里没有这些
// 路由），练习页上每一道题都 404。这条断言防的就是有人日后把 isBackendPath
// 改回裸的 startsWith("/api/")。
test("education paths are exempt from the backend bridge", () => {
  assert.equal(isEducationPath("/practice"), true);
  assert.equal(isEducationPath("/api/edu/set"), true);
  assert.equal(isEducationPath("/api/edu/people"), true);
  assert.equal(isEducationPath("/practice-notes"), false); // 前缀相同但不是它
  assert.equal(isEducationPath("/api/education/x"), false);
  assert.equal(isEducationPath("/api/v1/knowledge/list"), false);

  // 关键回归：这两条以 /api/ 开头，但**不能**被当成主后端路径。
  assert.equal(isBackendPath("/api/edu/set"), false);
  assert.equal(isBackendPath("/api/edu/people"), false);
  assert.equal(isBackendPath("/api/v1/knowledge/list"), true);
});

test("isCodexCallbackPath matches only the exact public callback path", () => {
  assert.equal(CODEX_CALLBACK_PATH, "/auth/callback");
  assert.equal(CODEX_CALLBACK_API_PATH, "/api/v1/auth/openai-codex/callback");
  assert.equal(isCodexCallbackPath("/auth/callback"), true);
  assert.equal(isCodexCallbackPath("/auth/callback/"), false);
  assert.equal(isCodexCallbackPath("/auth/callback/extra"), false);
  assert.equal(isCodexCallbackPath("/auth/callback-near"), false);
  assert.equal(isCodexCallbackPath("/Auth/callback"), false);
});

test("proxy rewrites the exact callback before backend routing and auth gating", () => {
  const source = readFileSync(path.resolve(process.cwd(), "proxy.ts"), "utf8");
  const callbackBranch = source.indexOf("if (isCodexCallbackPath(pathname))");
  const backendBranch = source.indexOf("if (isBackendPath(pathname))");
  const authGate = source.indexOf("if (!AUTH_ENABLED");

  assert.notEqual(callbackBranch, -1);
  assert.notEqual(backendBranch, -1);
  assert.notEqual(authGate, -1);
  assert.ok(callbackBranch < backendBranch);
  assert.ok(callbackBranch < authGate);
  assert.match(
    source,
    /NextResponse\.rewrite\(\s*new URL\(\s*CODEX_CALLBACK_API_PATH \+ search,\s*API_BASE_URL,?\s*\),?\s*\)/,
  );
});

test("isAuthExempt allows public static assets through the auth gate (issue #599)", () => {
  // The Next image optimizer re-fetches these over a cookie-less loopback; if
  // the gate blocked them the sidebar logo/banner would render broken.
  assert.equal(isAuthExempt("/logo.png"), true);
  assert.equal(isAuthExempt("/banner.png"), true);
  assert.equal(isAuthExempt("/logo_black.png"), true);
  assert.equal(isAuthExempt("/apple-touch-icon.png"), true);
  assert.equal(isAuthExempt("/provider-icons/openai.svg"), true);
});

test("isAuthExempt allows auth pages and Next internals", () => {
  assert.equal(isAuthExempt("/login"), true);
  assert.equal(isAuthExempt("/register"), true);
  assert.equal(isAuthExempt("/_next/data/build/home.json"), true);
  assert.equal(isAuthExempt("/favicon-32x32.png"), true);
});

test("isAuthExempt does NOT exempt protected app routes", () => {
  assert.equal(isAuthExempt("/home"), false);
  assert.equal(isAuthExempt("/dashboard"), false);
  assert.equal(isAuthExempt("/space/agents"), false);
  assert.equal(isAuthExempt("/knowledge"), false);
});

test("classifyToken reports missing for absent or empty cookie", () => {
  const now = 1_000_000_000_000;
  assert.equal(classifyToken(undefined, now), "missing");
  assert.equal(classifyToken("", now), "missing");
});

test("classifyToken reports malformed for non-JWT shapes", () => {
  const now = 1_000_000_000_000;
  assert.equal(classifyToken("a.b", now), "malformed"); // 2 segments
  assert.equal(classifyToken("a.b.c.d", now), "malformed"); // 4 segments
  // Valid 3-segment shape but the payload is not JSON → malformed.
  const notJson = `h.${Buffer.from("not-json").toString("base64url")}.s`;
  assert.equal(classifyToken(notJson, now), "malformed");
});

test("classifyToken honors expiry and accepts unexpired / expiry-less tokens", () => {
  const now = 1_000_000_000_000; // ms
  const nowSec = now / 1000;
  assert.equal(classifyToken(makeToken({ exp: nowSec + 3600 }), now), "valid");
  assert.equal(classifyToken(makeToken({ exp: nowSec - 1 }), now), "expired");
  assert.equal(classifyToken(makeToken({}), now), "valid"); // no exp claim
});
