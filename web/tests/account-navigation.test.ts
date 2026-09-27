import test from "node:test";
import assert from "node:assert/strict";
import { accountAreaRedirect, accountDestination, isManagementSession } from "../lib/account-navigation";

const parent = { enabled: true, authenticated: true, role: "admin" };
const student = { enabled: true, authenticated: true, role: "user" };

test("parent lands in resource management even with an old learning bookmark", () => {
  for (const path of [null, "/", "/practice", "/home", "/space/learning", "/home/session123"]) {
    assert.equal(accountDestination(parent, path), "/admin");
  }
  assert.equal(accountDestination(parent, "/settings/models?view=all"), "/settings/models?view=all");
  assert.equal(accountDestination(parent, "/knowledge"), "/knowledge");
});

test("student opens the main workspace without a practice or assessment step", () => {
  assert.equal(accountDestination(student), "/home");
  assert.equal(accountDestination(student, "/practice"), "/home");
  assert.equal(accountDestination(student, "/home/session123"), "/home/session123");
  assert.equal(accountDestination(student, "/admin/users"), "/home");
  assert.equal(accountAreaRedirect(student, "management", "/admin"), "/home");
  assert.equal(accountAreaRedirect(student, "workspace", "/home"), null);
});

test("parent keeps management navigation through resource pages, including direct visits", () => {
  for (const path of ["/knowledge", "/settings/models", "/settings/llm", "/space/mcp", "/profile"]) {
    assert.equal(accountAreaRedirect(parent, "utility", path), null);
  }
  assert.equal(accountAreaRedirect(parent, "utility", "/space/learning"), "/admin");
  assert.equal(accountAreaRedirect(parent, "workspace", "/home"), "/admin");
});

test("unverified, disabled auth and cross-origin return URLs never select parent mode", () => {
  assert.equal(isManagementSession({ ...parent, authenticated: false }), false);
  assert.equal(isManagementSession({ ...parent, enabled: false }), false);
  assert.equal(accountAreaRedirect({ ...parent, authenticated: false }, "management", "/admin"), "/login?next=%2Fadmin");
  for (const path of ["https://evil.invalid", "//evil.invalid", "/\\evil.invalid", "/\nevil.invalid", "/login", "/register"]) {
    assert.equal(accountDestination(parent, path), "/admin");
    assert.equal(accountDestination(student, path), "/home");
  }
  assert.equal(accountDestination({ ...parent, enabled: false }), "/home");
});

test("teaching roles keep only their own entry points and working model configuration links", () => {
  const status = { enabled: true, authenticated: true, product_mode: "teaching" as const };
  const admin = { ...status, role: "admin" };
  const family = { ...status, role: "parent" };
  const learner = { ...status, role: "student" };
  for (const path of ["/settings/models", "/settings/llm", "/settings/embedding", "/settings/search", "/admin/materials"]) {
    assert.equal(accountAreaRedirect(admin, "utility", path), null);
    assert.equal(accountAreaRedirect(family, "utility", path), "/parent");
    assert.equal(accountAreaRedirect(learner, "utility", path), "/home");
  }
  for (const path of ["/settings/image", "/settings/video", "/space/mcp", "/settings/tools"]) {
    assert.equal(accountDestination(admin, path), "/admin");
  }
  assert.equal(accountDestination(family, "/quiz"), "/parent");
  assert.equal(accountDestination(learner, "/quiz"), "/quiz");
  assert.equal(accountDestination(learner, "/parent"), "/home");
});
