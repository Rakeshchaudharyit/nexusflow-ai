import assert from "node:assert/strict";
import { test } from "node:test";
import { freshClients, json, loadModule, session } from "./client-loader.mjs";

const ORG = "66666666-6666-4666-8666-666666666666";
const memory = await loadModule("lib/memory.ts");

async function signedIn(context, name, respond = () => json({})) {
  const { auth, client } = await freshClients(name);
  const calls = [];
  context.mock.method(globalThis, "fetch", async (path, init) => {
    if (path.endsWith("/login")) return session("token-1");
    calls.push({ path, init });
    return respond(path, init);
  });
  await auth.login("owner@example.com", "password");
  return { client, calls };
}

test("facts read as key = value; notes show their summary", () => {
  assert.equal(
    memory.memoryText({ fact_key: "account_owner", fact_value: "Maya Chen", summary: null, content: "x" }),
    "account_owner = Maya Chen",
  );
  assert.equal(
    memory.memoryText({ fact_key: null, fact_value: null, summary: "short", content: "long" }),
    "short",
  );
});

test("manual memory is deleted; run-derived memory is deactivated", () => {
  assert.equal(memory.removalLabel({ source_type: "manual_user_entry" }), "Delete");
  assert.equal(memory.removalLabel({ source_type: "agent_run" }), "Deactivate");
  assert.equal(memory.memoryStatus({ is_active: false, in_context: false }), "inactive");
  assert.equal(memory.memoryStatus({ is_active: true, in_context: false }), "expired");
  assert.equal(memory.memoryStatus({ is_active: true, in_context: true }), "active");
});

test("run memory usage is reported as counts only", () => {
  assert.equal(memory.usageLine(null), null);
  assert.equal(
    memory.usageLine({
      thread: 4, agent: 2, workspace: 1, facts: 3, summary: true,
      workspace_enabled: true, chars: 400, truncated: false, entry_ids: ["a"],
    }),
    "Thread memory: 4 · Agent memory: 2 · Workspace memory: 1 · thread summary",
  );
  assert.match(
    memory.usageLine({
      thread: 3, agent: 0, workspace: 0, facts: 0, summary: false,
      workspace_enabled: false, chars: 10, truncated: true, entry_ids: [],
    }),
    /Workspace memory: off · budget reached/,
  );
});

test("memory client sends only supplied filters and scoped requests", async (context) => {
  const { client, calls } = await signedIn(context, "memory", () => json([]));
  await client.listMemory(ORG);
  await client.listMemory(ORG, { memory_type: "fact_memory", active: false, thread_id: "t 1" });
  await client.deleteMemory(ORG, "m/1");
  await client.createThread(ORG, "Acme");
  assert.deepEqual(
    calls.map(({ path, init }) => [path, init.method]),
    [
      ["/api/backend/memory", undefined],
      ["/api/backend/memory?memory_type=fact_memory&active=false&thread_id=t+1", undefined],
      ["/api/backend/memory/m%2F1", "DELETE"],
      ["/api/backend/threads", "POST"],
    ],
  );
  assert.equal(JSON.parse(calls[3].init.body).title, "Acme");
  for (const { init } of calls) assert.equal(init.headers["X-Organization-ID"], ORG);
});

test("runs carry a thread only when one is chosen", async (context) => {
  const { client, calls } = await signedIn(context, "agents", () => json({ run_id: "r1", status: "queued" }));
  await client.runAgent(ORG, "a1", "Who owns this account?", "t1");
  await client.runAgent(ORG, "a1", "125 multiplied by 24.");
  assert.deepEqual(JSON.parse(calls[0].init.body), { input: "Who owns this account?", thread_id: "t1" });
  assert.deepEqual(JSON.parse(calls[1].init.body), { input: "125 multiplied by 24." });
});
