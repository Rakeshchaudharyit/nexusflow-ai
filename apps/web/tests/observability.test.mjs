import assert from "node:assert/strict";
import { test } from "node:test";
import { freshClients, json, loadModule, session } from "./client-loader.mjs";

const ORG = "88888888-8888-4888-8888-888888888888";
const observe = await loadModule("lib/observability.ts");
const evaluation = await loadModule("lib/evaluation.ts");

const span = (id, parent, sequence, extra = {}) => ({
  id,
  parent_span_id: parent,
  sequence,
  span_type: "graph_node",
  name: id,
  offset_ms: 0,
  duration_ms: 1,
  metadata: {},
  ...extra,
});

test("spans form a depth-first tree; collapsing hides descendants", () => {
  const spans = [
    span("worker", null, 1, { span_type: "worker" }),
    span("plan", "worker", 2),
    span("tool", "execute", 4, { span_type: "tool" }),
    span("execute", "worker", 3),
    span("retry", null, 5, { span_type: "retry" }),
  ];
  const rows = observe.buildTree(spans);
  assert.deepEqual(
    rows.map((row) => [row.span.id, row.depth, row.hasChildren]),
    [
      ["worker", 0, true],
      ["plan", 1, false],
      ["execute", 1, true],
      ["tool", 2, false],
      ["retry", 0, false],
    ],
  );
  assert.deepEqual(
    observe.visibleRows(rows, new Set(["execute"])).map((row) => row.span.id),
    ["worker", "plan", "execute", "retry"],
  );
  assert.deepEqual(
    observe.visibleRows(rows, new Set(["worker"])).map((row) => row.span.id),
    ["worker", "retry"],
  );
});

test("waterfall bars are proportional with a visible minimum width", () => {
  assert.deepEqual(observe.bar({ offset_ms: 50, duration_ms: 25 }, 100), { left: 50, width: 25 });
  const tiny = observe.bar({ offset_ms: 0, duration_ms: 0.001 }, 100);
  assert.equal(tiny.width, 0.6);
  const late = observe.bar({ offset_ms: 100, duration_ms: 10 }, 100);
  assert.ok(late.left + late.width <= 100);
});

test("durations are formatted honestly, including sub-millisecond steps", () => {
  assert.equal(observe.formatMs(null), "—");
  assert.equal(observe.formatMs(0.02), "<0.1 ms");
  assert.equal(observe.formatMs(0.42), "0.42 ms");
  assert.equal(observe.formatMs(15.968), "16 ms");
  assert.equal(observe.formatMs(2450), "2.45 s");
  assert.equal(observe.percent(0.875), "87.5%");
  assert.equal(observe.signedPercent(-0.5), "-50 pts");
  assert.equal(observe.signedPercent(0.25), "+25 pts");
  assert.deepEqual(observe.metadataEntries({ a_b: 1, gone: null, list: ["x", "y"] }), [
    ["a b", "1"],
    ["list", "x, y"],
  ]);
});

test("expectations read as short lines; form helpers parse phrases and values", () => {
  assert.deepEqual(
    evaluation.expectationLines({
      expected_status: "completed",
      expected_tool_key: "none",
      expected_output_contains: ["3000"],
      expected_values: { "validation.confidence": 0.95 },
      expected_citation_documents: ["Security.pdf"],
      retrieval_k: 3,
      expected_no_match: false,
    }),
    [
      "status = completed",
      "no tool call",
      'contains "3000"',
      "validation.confidence = 0.95",
      "cites Security.pdf (top 3)",
    ],
  );
  assert.deepEqual(evaluation.phrases("Maya Chen, North America\n3000"), [
    "Maya Chen",
    "North America",
    "3000",
  ]);
  assert.deepEqual(evaluation.parseValues("opportunity_score=92\nvalidation.valid=true\nname=Acme"), {
    opportunity_score: 92,
    "validation.valid": true,
    name: "Acme",
  });
});

test("trace and evaluation clients are scoped and send only supplied filters", async (context) => {
  const traces = await freshClients("observability");
  const evals = await freshClients("evaluation");
  const calls = [];
  context.mock.method(globalThis, "fetch", async (path, init) => {
    if (path.endsWith("/login")) return session("token-1");
    calls.push({ path, init });
    return json(path.includes("runs") && init.method === "POST" ? { id: "r1" } : []);
  });
  await traces.auth.login("owner@example.com", "password");
  await evals.auth.login("owner@example.com", "password");
  await traces.client.listTraces(ORG, { run_type: "team", status: "", origin: "all" });
  await traces.client.getObservabilitySummary(ORG, 168);
  await evals.client.startEvaluation(ORG, "d/1", { target_agent_id: "a1" });
  await evals.client.compareRuns(ORG, "r2", "r1");
  assert.deepEqual(
    calls.map(({ path, init }) => [path, init.method]),
    [
      ["/api/backend/traces?run_type=team&origin=all", undefined],
      ["/api/backend/observability/summary?hours=168", undefined],
      ["/api/backend/evaluation-datasets/d%2F1/runs", "POST"],
      ["/api/backend/evaluation-runs/r2/compare/r1", undefined],
    ],
  );
  assert.deepEqual(JSON.parse(calls[2].init.body), { target_agent_id: "a1" });
  for (const { init } of calls) assert.equal(init.headers["X-Organization-ID"], ORG);
});
