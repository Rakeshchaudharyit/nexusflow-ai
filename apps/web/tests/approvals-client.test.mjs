import assert from "node:assert/strict";
import { test } from "node:test";
import { freshClients, json, session } from "./client-loader.mjs";

const ORG = "44444444-4444-4444-8444-444444444444";
const APPROVAL = {
  id: "a1",
  team_run_id: "r1",
  status: "pending",
  action_type: "send_followup_email",
  risk_level: "medium",
  execution: null,
};

async function signedIn(context, respond) {
  const { auth, client } = await freshClients("approvals");
  const calls = [];
  context.mock.method(globalThis, "fetch", async (path, init) => {
    if (path.endsWith("/login")) return session("token-1");
    if (path.endsWith("/refresh")) {
      calls.push({ path, init, refresh: true });
      return session("token-2");
    }
    calls.push({ path, init });
    return respond(path, init);
  });
  await auth.login("owner@example.com", "password");
  return { client, calls };
}

test("approval list sends only supplied filters, scoped and authenticated", async (context) => {
  const { client, calls } = await signedIn(context, () => json([APPROVAL]));
  const items = await client.listApprovals(ORG);
  await client.listApprovals(ORG, {
    status: "pending",
    risk_level: "medium",
    team_run_id: "r 1",
    limit: 10,
  });
  assert.equal(items[0].team_run_id, "r1");
  assert.deepEqual(
    calls.map(({ path }) => path),
    [
      "/api/backend/approvals",
      "/api/backend/approvals?status=pending&risk_level=medium&team_run_id=r+1&limit=10",
    ],
  );
  for (const { init } of calls) {
    assert.equal(init.headers["X-Organization-ID"], ORG);
    assert.equal(init.headers.Authorization, "Bearer token-1");
  }
});

test("approval detail encodes the id", async (context) => {
  const { client, calls } = await signedIn(context, () => json(APPROVAL));
  const approval = await client.getApproval(ORG, "a/../b");
  assert.equal(approval.action_type, "send_followup_email");
  assert.equal(calls[0].path, "/api/backend/approvals/a%2F..%2Fb");
  assert.equal(calls[0].init.method, undefined);
});

test("approve and reject post only an optional comment", async (context) => {
  const { client, calls } = await signedIn(context, () =>
    json({ ...APPROVAL, status: "approved" }),
  );
  await client.approveAction(ORG, "a1", "  Looks right  ");
  await client.rejectAction(ORG, "a1");
  await client.rejectAction(ORG, "a1", "   ");
  assert.deepEqual(
    calls.map(({ path, init }) => [init.method, path, init.body]),
    [
      [
        "POST",
        "/api/backend/approvals/a1/approve",
        '{"comment":"Looks right"}',
      ],
      ["POST", "/api/backend/approvals/a1/reject", '{"comment":null}'],
      ["POST", "/api/backend/approvals/a1/reject", '{"comment":null}'],
    ],
  );
  assert.equal(calls[0].init.headers["Content-Type"], "application/json");
});

test("member and already-decided errors surface without a session refresh", async (context) => {
  const responses = [
    json(
      {
        error: {
          code: "forbidden",
          message: "Your organization role does not permit this action.",
        },
      },
      403,
    ),
    json(
      {
        error: {
          code: "approval_not_pending",
          message: "This approval has already been decided.",
        },
      },
      409,
    ),
    json(
      { error: { code: "approval_not_found", message: "Approval not found." } },
      404,
    ),
  ];
  const { client, calls } = await signedIn(context, () => responses.shift());
  await assert.rejects(
    client.approveAction(ORG, "a1"),
    (e) => e.status === 403,
  );
  await assert.rejects(
    client.rejectAction(ORG, "a1"),
    (e) => e.status === 409 && e.code === "approval_not_pending",
  );
  await assert.rejects(
    client.getApproval(ORG, "other-tenant"),
    (e) => e.status === 404 && e.code === "approval_not_found",
  );
  assert.equal(calls.filter((call) => call.refresh).length, 0);
});
