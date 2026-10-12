import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { test } from "node:test";
import ts from "typescript";

const source = await readFile(
  new URL("../src/lib/api/auth.ts", import.meta.url),
  "utf8",
);
const compiled = ts.transpileModule(source, {
  compilerOptions: {
    target: ts.ScriptTarget.ES2022,
    module: ts.ModuleKind.ES2022,
  },
}).outputText;
let instance = 0;
const freshClient = () =>
  import(
    `data:text/javascript,${encodeURIComponent(compiled + `\n// instance ${instance++}`)}`
  );
const user = { id: "user-id", email: "owner@example.com", organizations: [] };
const session = (token) =>
  new Response(
    JSON.stringify({
      access_token: token,
      token_type: "bearer",
      expires_in: 900,
      user,
    }),
    { status: 200 },
  );
const denied = () =>
  new Response(
    JSON.stringify({
      error: { code: "unauthorized", message: "Authentication required." },
    }),
    { status: 401 },
  );
const json = (value) => new Response(JSON.stringify(value), { status: 200 });

test("concurrent bootstrap shares a single refresh", async (context) => {
  const client = await freshClient();
  let calls = 0;
  context.mock.method(globalThis, "fetch", async (path, init) => {
    assert.equal(path, "/api/backend/auth/refresh");
    assert.equal(init.credentials, "same-origin");
    calls++;
    return session("token-1");
  });
  await Promise.all([
    client.refreshSession(),
    client.refreshSession(),
    client.refreshSession(),
  ]);
  assert.equal(calls, 1);
});

test("simultaneous 401s rotate once and retry using the new token", async (context) => {
  const client = await freshClient();
  let refreshes = 0;
  let attempts = 0;
  context.mock.method(globalThis, "fetch", async (path, init) => {
    if (path.endsWith("/login")) return session("old-token");
    if (path.endsWith("/refresh")) {
      refreshes++;
      return session("new-token");
    }
    attempts++;
    if (init.headers.Authorization === "Bearer old-token") return denied();
    assert.equal(init.headers.Authorization, "Bearer new-token");
    return json(user);
  });
  await client.login("owner@example.com", "password");
  await Promise.all([client.getCurrentUser(), client.getCurrentUser()]);
  assert.equal(refreshes, 1);
  assert.equal(attempts, 4);
});

test("a second 401 stops rather than looping", async (context) => {
  const client = await freshClient();
  let refreshes = 0;
  let attempts = 0;
  context.mock.method(globalThis, "fetch", async (path) => {
    if (path.endsWith("/login")) return session("old-token");
    if (path.endsWith("/refresh")) {
      refreshes++;
      return session("new-token");
    }
    attempts++;
    return denied();
  });
  await client.login("owner@example.com", "password");
  await assert.rejects(
    client.getCurrentUser(),
    (error) => error.status === 401,
  );
  assert.equal(refreshes, 1);
  assert.equal(attempts, 2);
});

test("authorization failure does not trigger refresh", async (context) => {
  const client = await freshClient();
  let refreshes = 0;
  context.mock.method(globalThis, "fetch", async (path) => {
    if (path.endsWith("/login")) return session("old-token");
    if (path.endsWith("/refresh")) {
      refreshes++;
      return session("new-token");
    }
    return new Response(
      JSON.stringify({ error: { code: "forbidden", message: "Forbidden." } }),
      { status: 403 },
    );
  });
  await client.login("owner@example.com", "password");
  await assert.rejects(
    client.getOrganization("other-org"),
    (error) => error.status === 403,
  );
  assert.equal(refreshes, 0);
});

test("refresh failure is surfaced without retrying the original request", async (context) => {
  const client = await freshClient();
  let requests = 0;
  context.mock.method(globalThis, "fetch", async () => {
    requests++;
    return denied();
  });
  await assert.rejects(
    client.getCurrentUser(),
    (error) => error.status === 401,
  );
  assert.equal(requests, 1);
});

test("network failure produces an actionable error", async (context) => {
  const client = await freshClient();
  context.mock.method(globalThis, "fetch", async () => {
    throw new TypeError("network");
  });
  await assert.rejects(
    client.login("owner@example.com", "password"),
    (error) => error.code === "unavailable" && error.status === 0,
  );
});
