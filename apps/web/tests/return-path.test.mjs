import assert from "node:assert/strict";
import { test } from "node:test";
import { loadModule } from "./client-loader.mjs";

const { loginURL, returnPath } = await loadModule("lib/return-path.ts");

test("workspace deep links survive sign-in", () => {
  assert.equal(returnPath("/app/agents/new"), "/app/agents/new");
  assert.equal(
    returnPath("/app/approvals?status=pending"),
    "/app/approvals?status=pending",
  );
  assert.equal(
    loginURL("/app/team-runs/abc"),
    "/login?next=%2Fapp%2Fteam-runs%2Fabc",
  );
});

test("the workspace root needs no return path", () => {
  assert.equal(loginURL("/app"), "/login");
  assert.equal(loginURL(null), "/login");
});

test("anything outside the workspace falls back to /app", () => {
  for (const unsafe of [
    "//evil.example/app",
    "https://evil.example/app",
    "/application",
    "/login",
    "/app\\@evil.example",
    "/app /x",
    "",
    undefined,
  ])
    assert.equal(returnPath(unsafe), "/app", String(unsafe));
});
