# Observability, Tracing and Evaluation (M10)

M10 adds two separate capabilities:

| | Observability (`app/observability/`) | Evaluation (`app/evaluation/`) |
| --- | --- | --- |
| Question | What actually happened during a run? | How correct was the behavior against defined expectations? |
| Tables | `run_traces`, `trace_spans` | `evaluation_datasets`, `evaluation_cases`, `evaluation_runs`, `evaluation_results` |
| Written by | the worker, observing real runs | the worker, executing cases as real runs |

Every number shown comes from persisted runtime or evaluation data. There are no estimated token counts, costs, synthetic latencies or trend percentages.

## Trace model

`RunTrace` holds exactly one trace per agent or team run, enforced by unique constraints on `agent_run_id` and `team_run_id`. It is created **in the same transaction as the run**, so every run since M10 has a trace, even while it is still queued. Runs from before M10 have no trace; if such a run is ever re-executed, a trace is created on first observation. Retries, recovery and the approval continuation all add spans to that same logical trace.

The trace stores only observability data the run does not already hold:
- `attempt_count`, `retry_count`, `span_count`
- `queue_wait_ms`
- `last_error_category`
- linkage: agent/team, thread, and `evaluation_run_id` (origin)

Status, timestamps, duration and error code are always **read from the run row**, which stays authoritative. The two can therefore never disagree.

## Span model

`TraceSpan` fields:
- **Identity and tree:** `id`, `organization_id`, `trace_id`, `parent_span_id` (the tree), `sequence` (unique per trace), `span_type`, `name`, `status`, `attempt`.
- **References:** `agent_id`, `tool_key`, `mcp_server_id` and `knowledge_source_id`, stored as observational values without foreign keys, so deleting a server never erases history.
- **Timing:** `started_at`, `completed_at`, and `duration_ms`, a float (fractional milliseconds).
- **Content:** bounded `input_summary` and `output_summary`, sanitized `metadata_json`, and `error_code`, `error_category`, `error_message`.

| Span type | Recorded when | Typical metadata |
| --- | --- | --- |
| `worker` | one job attempt on a worker | job id, job type, attempt / max, worker id, queue wait, job status |
| `graph_node` | single-agent node (analyze, plan, execute tool, compose), revision requests | intent, planned tools, tool calls, citations count |
| `agent` | team member work, supervisor plan | role, tool calls, score, validity, confidence, knowledge results |
| `tool` / `mcp` / `knowledge_search` | every real tool call | tool key; MCP server name, tool name, server-side duration; retrieval counts |
| `memory_retrieval` | memory context loaded for a run | entry counts per scope, facts, summary used, context chars, truncated |
| `policy` | M6 policy evaluation, or "No action proposed" | action type, decision, risk level, rule key |
| `approval` | requested (pending), approved, rejected | action type, risk, decision |
| `action` | simulated action execution | action type, status, reused execution, simulated |
| `retry` | an attempt ended and the job was re-queued (or recovered) | attempt, next attempt, retry delay, reason, outcome |

## Events vs traces

The immutable `AgentRunEvent` timeline (M3–M9) is unchanged and remains the business, user-readable record. Spans are a separate, technical view with a tree and timings.

- Nothing is migrated from events into spans, and no second user-facing timeline is created.
- A test asserts that a single-agent run still has exactly its 10 M3 events while gaining 6 spans.

## Hierarchy

```text
Team run trace                          Single-agent trace
├─ Worker · attempt 1                   ├─ Worker · attempt 1
│  ├─ Memory retrieval                  │  ├─ Memory retrieval (thread runs)
│  ├─ Supervisor · plan                 │  ├─ Analyze request
│  ├─ Customer Specialist               │  ├─ Create plan
│  │  └─ MCP search_customer            │  ├─ Execute tool
│  ├─ Researcher                        │  │  └─ calculator | MCP | knowledge_search
│  │  └─ knowledge_search               │  └─ Compose response
│  ├─ Analyst · Writer · Validator      ├─ Retry (if re-queued)
│  └─ Policy (+ Approval requested)     └─ Worker · attempt 2 …
└─ Worker · approved action (later job)
   ├─ Approval approved
   └─ Action · send_followup_email
```

The trace itself is the root (shown as the run). Each attempt is a top-level `worker` span. Parents come from a stack, because graph nodes run sequentially.

## Timing strategy

- **Durations:** `time.perf_counter()` (monotonic), to the microsecond, stored as fractional milliseconds. Local deterministic steps often take under 1 ms and are shown as such ("<0.1 ms", "0.42 ms"); they are never rounded up.
- **Timestamps:** UTC wall clock captured at span start; `completed_at = started_at + duration`.
- **What a span measures:** node and agent spans open *after* their event write and close *before* the completion write, so they time the work rather than the bookkeeping.
- **Queue wait:** `queue_wait_ms = worker claim time − job created_at`, measured at the first claim from two persisted UTC values. Job `created_at` is now stamped with microseconds.
- **Waterfall offsets:** derived from span start times relative to the trace's first span.

## Persistence and failure safety

- **In memory first:** spans are collected in memory per attempt and flushed **once per attempt, in one short transaction, after the business transaction has committed**. No commit is made per measurement.
- **Never fails a run:** if flushing fails, the error is logged (type only), the spans are dropped, and the run is unaffected. A test makes `_write` raise and confirms the run still completes.
- **Lost attempts:** an attempt that dies (worker crash) cannot flush. Recovery therefore records a `worker` span with status `lost`, timed from the attempt's persisted `started_at` to its last heartbeat, plus a `retry` span with the recovery outcome.
- **Bounds:** at most 400 spans per flush.

## Worker linkage, retries and approvals

- **Attempts:** each M7 attempt gets a `worker` span carrying job id, job type, attempt / max, worker id (`hostname:pid:random`) and queue wait. Redis message contents are never recorded.
- **Retries:** a re-queued attempt adds a `retry` span with error code and category, attempt, next attempt, `retry_delay_ms` (until `next_retry_at`) and reason. The trace counts `retry_count`. Retry boundaries are visible as separate attempt subtrees.
- **Approval continuation:** this is a separate `approval_action` job. It adds its own `worker` span, `Approval approved` and the `action` span, all to the team run's trace. A rejection, which happens in the API request, adds an `Approval rejected` span.
- **Authority:** the approval and execution tables stay authoritative; spans only observe them.

## Error classification

`categorize(error_code)` maps safe codes to:
- `validation`
- `permission`
- `tenant`
- `tool`
- `mcp`
- `knowledge`
- `policy`
- `approval`
- `worker`
- `provider`
- `cancelled`
- `internal`

The original safe `error_code` is always kept next to the category. The UI shows the category, code, safe message, the failing span(s) and attempts, never a stack trace.

## Memory and RAG metadata

- **Memory spans:** counts only (thread / agent / workspace entries, facts, characters, truncated). The injected memory text is never stored.
- **Knowledge spans:**
  - query summary (≤120 chars)
  - allowed and searched source counts, source names
  - candidates, results, top score
  - context characters, truncated, insufficient
  - document names

  No chunk text and no embeddings are stored. Tests assert that neither document phrases nor "embedding" appear anywhere in a trace.

## Privacy and redaction

- **Summaries:** single-line and bounded to 200 characters. Argument summaries are `key=value` with secret-named keys (password, token, api key, authorization, cookie, secret…) replaced by `[redacted]`. Secret-looking values (bearer tokens, `sk-…` keys, JWT prefixes) are masked.
- **Metadata:** scalars and short scalar lists only (at most 30 keys, values at most 200 characters).
- **Never stored:** prompts, document text, memory text, action payloads (subject/body), MCP URLs or credentials.
- **Prompt injection:** document or memory instructions cannot become trace metadata, because only server-computed counts and identifiers are recorded.

## Token usage and cost

The deterministic provider reports no token usage, so **no token or cost fields exist** and none are shown. The UI states this explicitly. Real usage can be added as span metadata when a live provider returns it; nothing is estimated.

## Retention

Traces are kept with their runs: deleting a run (or its organization) cascades to its trace and spans. M10 implements **no automatic purge**. The recommended strategy is a periodic job deleting `run_traces` older than a retention window (for example 90 days). Spans cascade, and the runs and their events are kept. That window would be a `TRACE_RETENTION_DAYS` setting when the job is introduced. Evaluation data persists until its dataset is deleted.

## APIs

| Endpoint | Purpose |
| --- | --- |
| `GET /traces` | Filters: `run_type`, `status`, `agent_id`, `team_id`, `run_id`, `error_code`, `error_category`, `origin` (user/evaluation/all), `since`, `until`, `limit` (≤100), `offset` |
| `GET /traces/{id}` | Summary, run linkage, jobs (created, enqueued, started, heartbeat, completed, retry, execution time), attempts, the span list with parent ids and waterfall offsets, failing spans |
| `GET /observability/summary?hours=24` (1–720) | Runs by status and type, completed/failed, average and max duration, average and max queue wait, retries, errors by category, tool usage (count, failures, average duration), knowledge searches/no-match/average results, approvals by status |

Every query filters by the caller's `organization_id`, including the aggregates.

## Evaluation architecture

```text
Evaluation Dataset ─ cases (deterministic expectations)
        ↓  POST /evaluation-datasets/{id}/runs  → 201 queued (run + job committed together)
Evaluation Run Job (M7 execution_jobs, job_type evaluation_run)
        ↓  worker: EvaluationRunner
Real Agent/Team Runtime (child runs tagged evaluation_run_id, executed through the same JobExecutor)
        ↓
Actual Run (+ its trace)
        ↓
Deterministic Checks
        ↓
Evaluation Result (one per case)
        ↓
Comparison / Regression
```

## Datasets and cases

`EvaluationDataset` has a name, description, type (`agent`, `team`, `rag`, `policy`, `mixed`) and status.

`EvaluationCase` holds:
- **Target:** `target_kind` (agent/team), optionally a fixed agent or team (otherwise the run's target).
- **Input:** the input text, `setup_inputs` (run first in the case's isolated thread) and `setup_memory` (notes written to that thread).
- **Expectations:** `expected_status`, `expected_intent`, `expected_tool_key` (exact, `mcp:*:calculate` pattern, or `none`), `expected_output_contains` / `_excludes`, `expected_values` (dotted paths into the final output), `expected_citation_documents`, `expected_no_match`, `expected_policy_decision` (`allow`, `require_approval`, `deny`, `none`), `expected_action_type`, `retrieval_k`.

Only expectations that are set become checks.

The demo dataset pins "Memory recall" to a memory-only agent (no tools, no knowledge). Demo creation gets or creates it, and refuses one that has been given tools or knowledge. Memory recall is therefore measured in isolation even when the evaluation's target agent has knowledge access. Its configuration is part of the run's snapshot and hash.

## Deterministic checks

They are named for exactly what they verify; there is no LLM judge.

| Check | Verifies |
| --- | --- |
| `expected_status` / `expected_intent` / `expected_tool` | run status, single-agent intent, tool selection (or no tool call) |
| `output_contains:<p>` / `output_excludes:<p>` | case-insensitive phrase presence/absence in the answer |
| `expected_value:<path>` | a final-output field equals a value (e.g. `opportunity_score` 92, `validation.confidence` 0.95) |
| `policy_decision`, `action_type`, `no_action_executed` | M6 decision and proposed action; zero executions for deny/approval/none |
| `no_match_response` | the exact insufficient-knowledge answer with no citations |
| `citation_ids_valid` | every `[K#]` in the answer has a structured citation |
| `citations_map_to_chunks` | each citation is a retrieved chunk that exists in the database (same organization) |
| `expected_document_cited`, `no_unrelated_citation` | an expected document is cited; only expected documents are cited |
| `retrieval_hit_at_k` | an expected document appears in the top-K retrieved (Hit@K) |
| `cited_excerpt_contains:<p>` | **limited groundedness check**: each expected phrase appears in a quoted, cited excerpt |

The last check is not general factuality scoring. It only shows that the claim is backed by retrieved text the answer cites.

**Scores:** a case scores the share of its checks that passed, and it passes only if all of them pass. The run score is the mean case score; pass rate is passed cases over finished cases.

**Retrieval metrics** across RAG cases: Hit@K rate, and MRR (mean reciprocal rank of the first expected document).

## Isolation and side-effect safety

- **Isolated threads:** a case with setup gets an **isolated evaluation thread** owned by the evaluation run (`memory_threads.evaluation_run_id`). It is invisible to user thread and memory lists, and unusable by user runs (404). User threads and memory are never read or written.
- **Hidden runs and approvals:** evaluation-created runs are excluded from default run lists, traces (`origin=user`), dashboard summaries and the approvals inbox.
- **No external effects:** actions are simulated, and policy, approval and exactly-once rules apply unchanged. **Evaluations never approve:** a run that pauses for approval is checked, then cancelled together with its request, so nothing executes and nothing is left pending.
- **Deletion:** deleting a dataset cascades to its evaluation runs, results, and the runs and threads those evaluations created.

## Worker integration and retries

- **Job type:** `evaluation_run` joins the M7 job table (one job per evaluation run). There is no new queue or worker service.
- **Child runs:** each case's run is executed by the same `JobExecutor` (claim, heartbeat, retries, tracing). The runner waits until the run settles, following retry delays, with a bounded timeout.
- **A failed expectation** is a completed result (`failed`), never a job failure or retry.
- **A case that cannot run** (no target, inactive target, timeout) becomes an `error` result, and the remaining cases continue.
- **Infrastructure faults** (for example a dropped database connection) release the attempt through M7, and the job retries. Cases that already have results are skipped (`(evaluation_run_id, case_id)` is unique), so nothing is duplicated. The test shows case 1 executed once and case 2 retried.
- **Cancellation:** `POST /evaluation-runs/{id}/cancel` stops a queued run immediately, or a running one before its next case.

## Configuration snapshot and hash

At execution start the runner stores `target_snapshot` and a SHA-256 `config_hash` of every target used. The snapshot is safe configuration only:
- **Agents:** name, status, instructions SHA-256, workspace-memory flag, enabled tool keys, and assigned knowledge sources with each document's name, ingested version and checksum prefix.
- **Teams:** name, status, flag, and members (role, position, required, agent config hash).
- **Global:** LLM provider, embedding provider/model/dimension, app version.

The same configuration always gives the same hash. That is how comparisons know whether "configuration changed".

## Comparison, regressions and baseline

`GET /evaluation-runs/{id}/compare/{otherId}` (same dataset only) reports, per case:
- `regression`: passed before, fails now
- `improvement`: failed before, passes now
- `unchanged`, `new` or `removed`

It also reports pass-rate, score and duration deltas, and `config_changed`. No statistical significance is claimed.

One completed run per dataset can be marked **baseline** (`PATCH /evaluation-runs/{id} {is_baseline}`); the run page offers "Compare with baseline".

## Evaluation APIs

| Endpoint | Purpose |
| --- | --- |
| `GET/POST /evaluation-datasets` | List; create (optionally with cases) |
| `POST /evaluation-datasets/demo` | Create the demo dataset (`docs/demo-evaluation/`) |
| `GET/PATCH/DELETE /evaluation-datasets/{id}` | Detail with cases and runs; rename/archive; delete |
| `POST /evaluation-datasets/{id}/cases`, `PATCH/DELETE /evaluation-cases/{id}` | Manage cases |
| `POST /evaluation-datasets/{id}/runs` | Queue an evaluation (`target_agent_id`, `target_team_id`) |
| `GET /evaluation-runs`, `GET/PATCH /evaluation-runs/{id}`, `POST …/cancel` | Runs, results with checks and actual values, baseline, cancel |
| `GET /evaluation-runs/{id}/compare/{otherId}` | Regression comparison |

Owners and admins manage datasets and start runs; members can view. Organization B can never see, modify, run, read or compare organization A's evaluations, nor target A's agents (all 404).

## Limitations

- **Deterministic runtime:** the checks evaluate the deterministic provider; semantic quality of free-form text is not judged.
- **Retention:** trace retention is documented, not automated.
- **No usage data:** there is no token or cost data (none is reported).
- **Sub-millisecond waterfalls:** local deterministic steps are sub-millisecond, so most of a waterfall's width is worker and database time. Bars have a minimum width.
- **Pre-M10 runs** have no traces.
- **Per-run aggregates:** the summary aggregates up to 5,000 traces per window in the API process; very large organizations would need SQL-side aggregation.
- **Self-contained:** there is no OpenTelemetry export or external APM; NexusFlow's own model could be exported later.
