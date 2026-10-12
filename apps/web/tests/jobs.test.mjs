import assert from "node:assert/strict";
import { test } from "node:test";
import { freshClients, json, loadModule, session } from "./client-loader.mjs";

const ORG = "55555555-5555-4555-8555-555555555555";
const jobs = await loadModule("lib/jobs.ts");
const actions = await loadModule("lib/actions.ts");
const execution = (overrides) => ({
  job_id: "j1",
  job_type: "single_agent_run",
  status: "queued",
  attempt: 0,
  max_attempts: 3,
  enqueued_at: "2026-10-09T00:00:00Z",
  started_at: null,
  heartbeat_at: null,
  next_retry_at: null,
  completed_at: null,
  error_code: null,
  error_message: null,
  cancellation_requested: false,
  delivery_pending: false,
  ...overrides,
});

test("polling runs only while the worker can still change the run", () => {
  assert.equal(jobs.POLL_INTERVAL_MS, 2000);
  for (const status of ["queued", "running"])
    assert.equal(jobs.isRunActive(status), true, status);
  for (const status of [
    "completed",
    "failed",
    "cancelled",
    "awaiting_approval",
  ])
    assert.equal(jobs.isRunActive(status), false, status);
  assert.equal(jobs.isCancellable("awaiting_approval"), true);
  assert.equal(jobs.isCancellable("completed"), false);
});

test("a queued run waiting out a retry is shown as retrying", () => {
  assert.equal(jobs.displayStatus("queued", "retrying"), "retrying");
  assert.equal(jobs.displayStatus("queued", "queued"), "queued");
  assert.equal(jobs.displayStatus("running", "running"), "running");
  assert.equal(jobs.displayStatus("completed", null), "completed");
});

test("execution notes describe the real job state, never a fake completion", () => {
  assert.equal(jobs.executionNote(null), null);
  assert.match(jobs.executionNote(execution()), /Waiting for a worker/);
  assert.match(
    jobs.executionNote(execution({ delivery_pending: true, enqueued_at: null })),
    /delivered automatically/,
  );
  assert.match(
    jobs.executionNote(execution({ status: "running", attempt: 1 })),
    /attempt 1 of 3/,
  );
  assert.match(
    jobs.executionNote(
      execution({ status: "running", attempt: 1, cancellation_requested: true }),
    ),
    /stops at the next stage/,
  );
  assert.equal(
    jobs.executionNote(
      execution({
        status: "retrying",
        attempt: 1,
        error_message: "The MCP server could not be reached.",
      }),
    ),
    "Attempt 1 of 3 hit a temporary failure: The MCP server could not be reached. Retrying automatically.",
  );
  assert.equal(jobs.executionNote(execution({ status: "completed" })), null);
});

test("approved actions are 'queued' until the worker records the execution", () => {
  const approved = { status: "approved", execution: null, team_run_status: "queued" };
  assert.match(actions.approvalOutcome(approved), /queued for the worker/);
  assert.equal(actions.awaitingWorker(approved), true);
  const ran = { ...approved, execution: { id: "e1" }, team_run_status: "completed" };
  assert.equal(actions.approvalOutcome(ran), "Approved. The simulated action ran once.");
  assert.equal(actions.awaitingWorker(ran), false);
  assert.match(
    actions.approvalOutcome({ ...approved, team_run_status: "cancelled" }),
    /cancelled before the action ran/,
  );
  assert.match(
    actions.approvalOutcome({
      status: "cancelled",
      execution: null,
      team_run_status: "cancelled",
    }),
    /not executed/,
  );
  assert.equal(
    actions.approvalOutcome({ status: "pending", execution: null, team_run_status: null }),
    null,
  );
});

test("cancel posts to the scoped run endpoints", async (context) => {
  const { auth, client } = await freshClients("jobs");
  const calls = [];
  context.mock.method(globalThis, "fetch", async (path, init) => {
    if (path.endsWith("/login")) return session("token-1");
    calls.push({ path, init });
    return json({
      run_id: "r1",
      status: "cancelled",
      cancellation_requested: false,
      execution: null,
    });
  });
  await auth.login("owner@example.com", "password");
  const agent = await client.cancelRun(ORG, "r/1");
  await client.cancelTeamRun(ORG, "t1");
  assert.equal(agent.status, "cancelled");
  assert.deepEqual(
    calls.map(({ path, init }) => [path, init.method, init.headers["X-Organization-ID"]]),
    [
      ["/api/backend/agent-runs/r%2F1/cancel", "POST", ORG],
      ["/api/backend/agent-team-runs/t1/cancel", "POST", ORG],
    ],
  );
});
