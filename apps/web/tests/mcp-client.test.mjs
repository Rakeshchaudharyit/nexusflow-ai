import assert from "node:assert/strict";
import { test } from "node:test";
import { freshClients, json, session } from "./client-loader.mjs";

const ORG = "22222222-2222-4222-8222-222222222222";

async function signedIn(context, respond) {
  const { auth, client } = await freshClients("mcp");
  const calls = [];
  context.mock.method(globalThis, "fetch", async (path, init) => {
    if (path.endsWith("/login")) return session("token-1");
    calls.push({ path, init });
    return respond(path, init);
  });
  await auth.login("owner@example.com", "password");
  return { client, calls };
}

test("MCP registry calls are organization scoped and authenticated", async (context) => {
  const { client, calls } = await signedIn(context, () => json({}));
  await client.listMcpServers(ORG);
  await client.getMcpServer(ORG, "server/../other");
  await client.listMcpTools(ORG, "server-id");
  assert.deepEqual(
    calls.map(({ path, init }) => [init.method ?? "GET", path]),
    [
      ["GET", "/api/backend/mcp-servers"],
      ["GET", "/api/backend/mcp-servers/server%2F..%2Fother"],
      ["GET", "/api/backend/mcp-servers/server-id/tools"],
    ],
  );
  for (const { init } of calls) {
    assert.equal(init.headers["X-Organization-ID"], ORG);
    assert.equal(init.headers.Authorization, "Bearer token-1");
  }
});

test("MCP mutations send the expected methods and bodies", async (context) => {
  const { client, calls } = await signedIn(context, () => json({}));
  await client.createMcpServer(ORG, {
    name: "NexusFlow Demo Tools",
    description: "",
    transport: "streamable_http",
    url: "http://mcp-demo:8765/mcp",
  });
  await client.updateMcpServer(ORG, "s", { is_enabled: false });
  await client.testMcpServer(ORG, "s");
  await client.discoverMcpTools(ORG, "s");
  await client.toggleMcpTool(ORG, "s", "t", false);
  assert.deepEqual(
    calls.map(({ path, init }) => [init.method, path, init.body ?? null]),
    [
      [
        "POST",
        "/api/backend/mcp-servers",
        JSON.stringify({
          name: "NexusFlow Demo Tools",
          description: "",
          transport: "streamable_http",
          url: "http://mcp-demo:8765/mcp",
        }),
      ],
      ["PATCH", "/api/backend/mcp-servers/s", '{"is_enabled":false}'],
      ["POST", "/api/backend/mcp-servers/s/test", null],
      ["POST", "/api/backend/mcp-servers/s/discover", null],
      ["PATCH", "/api/backend/mcp-servers/s/tools/t", '{"is_enabled":false}'],
    ],
  );
  assert.equal(calls[0].init.headers["Content-Type"], "application/json");
  assert.equal(calls[2].init.headers["Content-Type"], undefined);
});

test("MCP failures surface safe API errors without a session refresh", async (context) => {
  let refreshes = 0;
  const { client } = await signedIn(context, (path) => {
    if (path.endsWith("/refresh")) refreshes++;
    return json(
      { error: { code: "mcp_unavailable", message: "The MCP server could not be reached." } },
      502,
    );
  });
  await assert.rejects(
    client.discoverMcpTools(ORG, "s"),
    (error) => error.status === 502 && error.code === "mcp_unavailable",
  );
  assert.equal(refreshes, 0);
});
