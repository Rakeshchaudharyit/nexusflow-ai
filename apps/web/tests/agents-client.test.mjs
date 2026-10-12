import assert from "node:assert/strict";
import { test } from "node:test";
import { freshClients as load, json, session } from "./client-loader.mjs";

async function freshClients() {
  const { auth, client } = await load("agents");
  return { auth, agents: client };
}
const ORG = "11111111-1111-4111-8111-111111111111";

test("agent requests carry bearer token and organization header", async (context) => {
  const { auth, agents } = await freshClients();
  const calls = [];
  context.mock.method(globalThis, "fetch", async (path, init) => {
    if (path.endsWith("/login")) return session("token-1");
    calls.push({ path, init });
    return json([]);
  });
  await auth.login("owner@example.com", "password");
  await agents.listAgents(ORG, "active");
  await agents.listRuns(ORG, "agent/../x");
  assert.equal(calls[0].path, "/api/backend/agents?status=active");
  assert.equal(calls[0].init.headers["X-Organization-ID"], ORG);
  assert.equal(calls[0].init.headers.Authorization, "Bearer token-1");
  assert.equal(calls[0].init.headers["Content-Type"], undefined);
  assert.equal(calls[1].path, "/api/backend/agent-runs?agent_id=agent%2F..%2Fx");
});

test("mutations send JSON with the correct method and encoded ids", async (context) => {
  const { auth, agents } = await freshClients();
  const calls = [];
  context.mock.method(globalThis, "fetch", async (path, init) => {
    if (path.endsWith("/login")) return session("token-1");
    calls.push({ path, init });
    return json({ run_id: "run", status: "completed" }, 201);
  });
  await auth.login("owner@example.com", "password");
  await agents.createAgent(ORG, {
    name: "Ops",
    description: "",
    instructions: "Help",
  });
  await agents.updateAgent(ORG, "a/b", { status: "active" });
  await agents.runAgent(ORG, "agent-id", "What is 2 plus 2?");
  assert.deepEqual(
    calls.map(({ path, init }) => [init.method, path]),
    [
      ["POST", "/api/backend/agents"],
      ["PATCH", "/api/backend/agents/a%2Fb"],
      ["POST", "/api/backend/agents/agent-id/runs"],
    ],
  );
  for (const { init } of calls) {
    assert.equal(init.headers["Content-Type"], "application/json");
    assert.equal(init.headers["X-Organization-ID"], ORG);
  }
  assert.deepEqual(JSON.parse(calls[2].init.body), {
    input: "What is 2 plus 2?",
  });
});

test("agent requests share the coordinated token refresh", async (context) => {
  const { auth, agents } = await freshClients();
  let refreshes = 0;
  context.mock.method(globalThis, "fetch", async (path, init) => {
    if (path.endsWith("/login")) return session("old-token");
    if (path.endsWith("/refresh")) {
      refreshes++;
      return session("new-token");
    }
    if (init.headers.Authorization === "Bearer old-token")
      return json({ error: { code: "unauthorized", message: "Expired." } }, 401);
    return json([]);
  });
  await auth.login("owner@example.com", "password");
  await Promise.all([agents.listAgents(ORG), agents.listRuns(ORG)]);
  assert.equal(refreshes, 1);
});

test("tenant errors surface without refreshing the session", async (context) => {
  const { auth, agents } = await freshClients();
  let refreshes = 0;
  context.mock.method(globalThis, "fetch", async (path) => {
    if (path.endsWith("/login")) return session("token-1");
    if (path.endsWith("/refresh")) refreshes++;
    return json(
      { error: { code: "agent_not_found", message: "Agent not found." } },
      404,
    );
  });
  await auth.login("owner@example.com", "password");
  await assert.rejects(
    agents.getAgent(ORG, "other-tenant-agent"),
    (error) => error.status === 404 && error.code === "agent_not_found",
  );
  assert.equal(refreshes, 0);
});
