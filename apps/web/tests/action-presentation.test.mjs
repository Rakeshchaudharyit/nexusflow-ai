import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { test } from "node:test";
import { freshClients, json, loadModule, session } from "./client-loader.mjs";

const actions = await loadModule("lib/actions.ts");
const action = (overrides) => ({
  action_type: "send_followup_email",
  decision: "require_approval",
  status: "awaiting_approval",
  ...overrides,
});

test("awaiting approval says the action has not run", () => {
  assert.equal(
    actions.policyLabel("require_approval"),
    "Human approval required",
  );
  assert.match(actions.actionOutcome(action()), /has not run/);
  assert.equal(actions.actionExecuted("awaiting_approval"), false);
});

test("approved actions are presented as simulated executions", () => {
  const outcome = actions.actionOutcome(action({ status: "completed" }));
  assert.equal(outcome, "Simulated action executed: send follow-up email.");
  assert.equal(actions.actionExecuted("completed"), true);
  assert.match(actions.SIMULATION_NOTICE, /no real email was sent/);
});

test("rejected and expired approvals never claim execution", () => {
  for (const status of ["rejected", "expired"]) {
    assert.match(actions.actionOutcome(action({ status })), /not executed/);
    assert.equal(actions.actionExecuted(status), false);
  }
});

test("ALLOW and DENY outcomes use backend status", () => {
  const allowed = action({
    action_type: "create_crm_note",
    decision: "allow",
    status: "completed",
  });
  assert.equal(actions.policyLabel(allowed.decision), "Allowed automatically");
  assert.equal(
    actions.actionOutcome(allowed),
    "Simulated action executed: create crm note.",
  );
  const denied = action({
    action_type: "delete_record",
    decision: "deny",
    status: "denied",
  });
  assert.equal(actions.policyLabel(denied.decision), "Denied");
  assert.equal(actions.actionLabel("delete_record"), "Delete record");
  assert.match(
    actions.actionOutcome(denied),
    /Denied by policy\. The action was not executed\./,
  );
});

test("team run detail carries action and approval; denial-only output has no analysis", async (context) => {
  const { auth, client } = await freshClients("teams");
  const detail = {
    id: "r1",
    status: "awaiting_approval",
    final_output: { action: action() },
    action: action({ approval_id: "a1" }),
    approval: {
      approval_id: "a1",
      approval_status: "pending",
      execution: null,
    },
  };
  context.mock.method(globalThis, "fetch", async (path) =>
    path.endsWith("/login") ? session("t") : json(detail),
  );
  await auth.login("owner@example.com", "password");
  const run = await client.getTeamRun("org", "r1");
  assert.equal(run.action.approval_id, "a1");
  assert.equal(run.approval.approval_status, "pending");
  assert.equal(client.hasAnalysis(run.final_output), false);
  assert.equal(
    client.hasAnalysis({
      company: "Acme Corporation",
      recommended_next_steps: [],
    }),
    true,
  );
});

test("single-agent API contract has no approval concepts", async () => {
  const source = await readFile(
    new URL("../src/lib/api/agents.ts", import.meta.url),
    "utf8",
  );
  for (const stale of [
    "approval",
    "action_outcome",
    "awaiting_approval",
    "policy_",
  ])
    assert.equal(source.includes(stale), false, `agents.ts mentions ${stale}`);
  const page = await readFile(
    new URL("../src/components/agents/run-detail.tsx", import.meta.url),
    "utf8",
  );
  assert.equal(page.includes("approval"), false);
});
