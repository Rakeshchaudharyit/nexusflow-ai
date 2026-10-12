import assert from "node:assert/strict";
import { test } from "node:test";
import { freshClients, json, session } from "./client-loader.mjs";

const ORG = "33333333-3333-4333-8333-333333333333";

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

const summary = (calls) =>
  calls.map(({ path, init }) => [init.method ?? "GET", path, init.body ?? null]);

test("team calls are organization scoped with expected methods", async (context) => {
  const { client, calls } = await signedIn(context, "teams");
  await client.listTeams(ORG);
  await client.getTeam(ORG, "team/../x");
  await client.createTeam(ORG, {
    name: "Team",
    description: "",
    members: [{ agent_id: "a", role: "supervisor" }],
  });
  await client.updateTeam(ORG, "t", { status: "active" });
  await client.addTeamMember(ORG, "t", { agent_id: "b", role: "writer" });
  await client.updateTeamMember(ORG, "t", "m", { is_required: false });
  await client.removeTeamMember(ORG, "t", "m");
  await client.runTeam(ORG, "t", "Analyze Acme Corporation");
  assert.deepEqual(summary(calls), [
    ["GET", "/api/backend/agent-teams", null],
    ["GET", "/api/backend/agent-teams/team%2F..%2Fx", null],
    [
      "POST",
      "/api/backend/agent-teams",
      '{"name":"Team","description":"","members":[{"agent_id":"a","role":"supervisor"}]}',
    ],
    ["PATCH", "/api/backend/agent-teams/t", '{"status":"active"}'],
    ["POST", "/api/backend/agent-teams/t/members", '{"agent_id":"b","role":"writer"}'],
    ["PATCH", "/api/backend/agent-teams/t/members/m", '{"is_required":false}'],
    ["DELETE", "/api/backend/agent-teams/t/members/m", null],
    ["POST", "/api/backend/agent-teams/t/runs", '{"objective":"Analyze Acme Corporation"}'],
  ]);
  for (const { init } of calls) {
    assert.equal(init.headers["X-Organization-ID"], ORG);
    assert.equal(init.headers.Authorization, "Bearer token-1");
  }
});

test("team run filters are encoded as query parameters", async (context) => {
  const { client, calls } = await signedIn(context, "teams", () => json([]));
  await client.listTeamRuns(ORG);
  await client.listTeamRuns(ORG, { teamId: "t 1", status: "failed" });
  await client.getTeamRun(ORG, "r");
  assert.deepEqual(
    calls.map(({ path }) => path),
    [
      "/api/backend/agent-team-runs",
      "/api/backend/agent-team-runs?team_id=t+1&status=failed",
      "/api/backend/agent-team-runs/r",
    ],
  );
});

test("tool assignment calls handle 204 deletes", async (context) => {
  const { client, calls } = await signedIn(context, "agents", (path, init) =>
    init.method === "DELETE" ? new Response(null, { status: 204 }) : json({}),
  );
  await client.listToolCatalog(ORG);
  await client.listAgentTools(ORG, "a");
  await client.assignAgentTool(ORG, "a", "mcp:nexusflow-demo-tools:search_customer");
  await client.updateAgentTool(ORG, "a", "x", false);
  assert.equal(await client.removeAgentTool(ORG, "a", "x"), undefined);
  assert.deepEqual(summary(calls), [
    ["GET", "/api/backend/tools", null],
    ["GET", "/api/backend/agents/a/tools", null],
    [
      "POST",
      "/api/backend/agents/a/tools",
      '{"tool_key":"mcp:nexusflow-demo-tools:search_customer"}',
    ],
    ["PATCH", "/api/backend/agents/a/tools/x", '{"is_enabled":false}'],
    ["DELETE", "/api/backend/agents/a/tools/x", null],
  ]);
});

test("cross-tenant 404s surface without refreshing the session", async (context) => {
  let refreshes = 0;
  const { client } = await signedIn(context, "teams", (path) => {
    if (path.endsWith("/refresh")) refreshes++;
    return json({ error: { code: "team_not_found", message: "Team not found." } }, 404);
  });
  await assert.rejects(
    client.getTeam(ORG, "other-tenant-team"),
    (error) => error.status === 404 && error.code === "team_not_found",
  );
  assert.equal(refreshes, 0);
});
