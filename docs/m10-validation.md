# M10 Validation: Observability, Tracing and Evaluation

Date: 2026-10-10. Validated on the local Docker stack (six services, all healthy: web, api, worker, postgres + pgvector 0.8.6, redis, mcp-demo). Live Alembic revision: `0010_observability_evaluation (head)`. There is no external observability SaaS, no collector, no live LLM and no token or cost data.

## Preflight

- **No other writer:** no other process had the repository open and no files had changed in the previous hour.
- **Starting state:** `0009_knowledge_rag`.
- **Inspected:** `AgentRunEvent` and the event stream, the team recorder hooks, M7 jobs (claim, heartbeat, recovery, release), M8 memory usage metadata, M9 knowledge metadata, run-detail traces, the deterministic providers and the existing duration fields.
- **Backup:** `pg_dump` taken before migrating.

## Automated results

| Suite | Command | Result |
| --- | --- | --- |
| API, PostgreSQL | `make api-test-postgres` | **467 passed** |
| API, SQLite | `make api-test` | **462 passed, 5 skipped** (PostgreSQL-only: migrations, row locks, pgvector SQL) |
| Observability (M10) | `pytest tests/test_observability.py` | **18 passed** (SQLite and PostgreSQL) |
| Evaluation (M10) | `pytest tests/test_evaluation.py` | **15 passed** (SQLite and PostgreSQL) |
| Worker | `make worker-test` | **32 passed, 1 skipped** |
| MCP demo server | `make mcp-test` | **15 passed** |
| Frontend | `npm test` in `node:22-alpine` | **49 passed** (44 + 5 new) |
| Ruff lint and format | `make api-lint` | All checks passed; 169 files formatted |
| MCP lint | `make mcp-lint` | clean |
| ESLint | `make web-lint` | clean |
| TypeScript (strict) | `make web-typecheck` | clean |
| Production build | `make web-build` | success; routes `/app/traces`, `/app/traces/[traceId]`, `/app/evaluations`, `/app/evaluations/datasets/[datasetId]`, `/app/evaluations/runs/[runId]`, `/app/evaluations/runs/[runId]/compare/[otherId]` |
| Compose | `docker compose config -q` | valid |

## Observability tests (`tests/test_observability.py`)

| Requirement | Test | Result |
| --- | --- | --- |
| Single-agent trace | `test_single_agent_trace_has_attempt_nodes_and_tool` | worker root → 4 nodes → `calculator` under "Execute tool"; valid timings; input summary `operation=multiply, left=125, right=24` |
| MCP trace | `test_mcp_span_records_server_and_tool` | `mcp` span: server id/name, tool `calculate`, server duration; no URL |
| Team trace | `test_team_trace_hierarchy` | Supervisor, Customer Specialist (with its tool), Researcher, Analyst (92), Writer, Validator (valid, 0.95), "No action proposed" |
| Memory trace | `test_memory_retrieval_span_holds_counts_only` | counts and characters only; no memory text; no tool span on recall |
| RAG trace | `test_knowledge_search_span_records_retrieval_metrics` | results, candidates, top score, context characters, sources; citations count on compose; no document text or embeddings |
| Retry trace | `test_retry_trace_keeps_one_logical_trace` | one trace; attempts (1 failed, 2 completed); retry span (attempt, next attempt, delay, `mcp` category); MCP spans per attempt |
| Failed trace | `test_persistent_failure_trace` | 3 attempts, 2 retries, `mcp_unavailable` / `mcp`; failing spans with safe messages; no traceback |
| Recovery | `test_recovered_worker_loss_is_traced` | lost attempt span plus "stale heartbeat (recovery)" retry span |
| Approval trace | `test_approval_trace_spans_request_and_continuation`, `test_rejection_is_traced` | policy `require_approval` and "Approval requested" (pending). After approval, the same trace gains an `approval_action` worker span, "Approval approved" and an action span (simulated); no payload. Rejection is traced |
| Policy deny | `test_policy_deny_trace` | policy span failed `policy_denied`, rule key, `delete_record`; no action span |
| Queue wait | `test_queue_wait_is_measured_from_job_creation` | queued trace has no spans; afterwards queue wait equals claim − created (within 2 ms) |
| Failure safety | `test_tracing_failure_never_breaks_a_run` | trace writes forced to fail; the run still completes |
| Privacy and bounds | `test_summaries_are_sanitized_and_bounded` | bearer token masked; summaries ≤ 200 chars |
| Events vs traces | `test_events_and_traces_stay_separate` | still 10 events, plus 6 spans |
| Aggregates | `test_observability_summary_is_derived_from_stored_rows` | runs, statuses, `policy` error category, tool usage from stored rows; no token or cost keys |
| Filters | `test_trace_filters` | type, status, agent, team, error code and category, `since`; limit bounded (422 above 100) |
| Tenant isolation | `test_traces_are_tenant_isolated` | Org B: empty list, 404 detail, no data via A's run or agent ids, zero aggregates. A cross-tenant span or trace insert raises `IntegrityError` (composite FKs) |

## Evaluation tests (`tests/test_evaluation.py`)

| Requirement | Test | Result |
| --- | --- | --- |
| Calculator and customer evals | `test_agent_cases_pass_with_named_checks` | pass; named checks; result links to its trace (origin `evaluation`) |
| MCP and memory evals | `test_mcp_and_memory_cases` | `mcp:*:calculate`, 3000; setup lookup then `memory_recall`, no tool, Maya Chen / North America |
| Team, policy, approval evals | `test_team_policy_and_approval_cases` | 92, `validation.valid`, 0.95, policy none; deny with no execution; `awaiting_approval` then cancelled with its request; inbox empty |
| RAG and no-match evals | `test_rag_and_no_match_cases_check_retrieval_and_citations` | citation checks, Hit@3 at rank 1, `cited_excerpt_contains`, hit rate 1.0, MRR 1.0; no-match response |
| Failed expectation | `test_failed_expectations_are_results_not_errors` | a `failed` result scoring 0.75 with a precise reason; job completed |
| Unrunnable case | `test_unrunnable_case_is_an_error_and_others_continue` | `error` result; other cases continue |
| Adversarial memory | `test_adversarial_memory_does_not_bypass_approval` | "approval not required" in memory, and still `require_approval`; 0 executions |
| Demo dataset | `test_demo_dataset_covers_the_platform` | 10 cases; snapshot and hash; only the fixture-specific RAG document case differs |
| Regression and improvement | `test_regression_then_improvement_comparison` | baseline 2/2 → tool disabled → 1 regression (−50 pts, config changed) → restored → 1 improvement; hash equals the baseline again; cross-dataset compare is 409 |
| Worker | `test_evaluation_runs_in_the_worker` | 201 `queued`, no runs yet; worker drains to completed |
| Eval retry | `test_expectation_failure_does_not_retry_but_infrastructure_faults_do` | an infrastructure fault in case 2 retries the job; case 1 is not re-run; results unique per case; attempt 2 completes |
| Memory isolation | `test_evaluations_do_not_pollute_user_memory_runs_or_threads` | user thread memory unchanged; evaluation thread hidden (404) and unusable by user runs; run lists, memory list and traces exclude evaluation data |
| Datasets and roles | `test_dataset_crud_and_roles` | CRUD; members can read but get 403 on writes and runs; invalid expectations are 422 |
| Tenant isolation | `test_evaluations_are_tenant_isolated` | Org B gets 404 on every A dataset, case, run, result, baseline and comparison, and cannot target A's agent; a cross-tenant result insert raises `IntegrityError` |
| No spurious retry | `test_knowledge_tool_regression_is_not_an_infrastructure_retry` | the evaluation job completes on attempt 1 |

## Migration

- **Live database:** `alembic upgrade head` gave `0010_observability_evaluation`, and `alembic check` reports "No new upgrade operations detected". Counts (users / orgs / events / agents / teams / team runs / agent runs / memory / jobs / chunks) were `12|17|1357|27|4|52|65|16|38|8` before and after.
- **Round trip on a copy with M10 data** (`nexusflow_m10_roundtrip`):
  - The copy held 36 traces, 262 spans, 1 dataset, 3 evaluation runs, 30 results, and 21 agent and 12 team evaluation runs.
  - Downgrading to 0009 removed only M10 data: the trace and evaluation tables, the evaluation-created runs and isolated threads (36 memory entries), and 6 evaluation approvals.
  - User data was unchanged: 67 agent runs, 53 team runs, 17 memory entries, 8 chunks and 14 approvals.
  - Upgrading back reached head with `check` clean; the copy was dropped.
- **Migration test:** `test_migrations.py` runs 0010 → 0009 → 0010 inside the full chain on PostgreSQL.

## Browser validation (QA Org A / QA Org B)

| Step | Result |
| --- | --- |
| Team trace (portfolio) | "Analyze Acme Corporation … recommend next steps." in the Acme thread, opened through the run page's "Open trace waterfall". Worker attempt (412 ms); Memory retrieval (6 ms); Supervisor plan; Customer Specialist → MCP `search_customer` (142 ms; server NexusFlow Demo Tools, server-side 133 ms); Researcher → `knowledge_search` (15 ms); Analyst, Writer, Validator; "No action proposed"; queue wait 28 ms |
| RAG trace | Knowledge Analyst question: `knowledge_search` 17 ms, 3 results from 1 source, 8 candidates, top score 0.5379, 827 context characters |
| Retry / recovery | mcp-demo stopped, MCP calculation run; the agent page showed "Attempt 1 of 3 hit a temporary failure … Retrying". mcp-demo restarted. The trace shows attempt 1 failed, retry, attempt 2 failed (MCP still starting), attempt 3 completed, over a 21.12 s window, each attempt with its own MCP span |
| Failed trace | The evaluation's policy-deny run: Failure panel shows category `policy`, "Record deletion is prohibited. (policy_denied)" and the failing spans; no stack trace |
| Summary | Real counters (runs, latency, queue wait, retries 2 / 1 run, knowledge searches) and tool usage (MCP calculate 3 calls, 2 failed) |
| Evaluation dataset | "Create demo dataset" with Knowledge Analyst for RAG gives 10 cases with readable expectations |
| Evaluation run | Target QA Operations Assistant + QA Account Team; queued immediately, then completed by the worker: **10/10 passed**, score 100%, Hit@K 100%, MRR 1.00, 884 ms, config `df12420796`; marked baseline; RAG case shows expected vs actual and checks |
| Comparison | Controlled config change: Knowledge Analyst's `knowledge_search` tool temporarily disabled. Run 2: 8/10, config `b7f236eaf0`. Compare with baseline: **2 regressions** (RAG citation, RAG no-match, with their failing checks), −20 pts, config changed. Tool re-enabled. Run 3: 10/10, config `df12420796` again; compared with run 2: **2 improvements**, +20 pts |
| Pollution | After all evaluations Org A has 0 pending approvals and only its 2 user threads; evaluation traces are listed only under the Evaluation filter |
| Cross-tenant | QA Org B: empty traces, zero counters, empty evaluations; Org A's trace and evaluation-run URLs show "not found in QA Org B" |
| Responsive | 8 pages (traces list, team trace, retry trace, evaluations, dataset, evaluation run, comparison, agent run) at 390 / 768 / 1024 / 1440: **0 px page overflow in all 32 cases**. At 390 px the waterfall bar drops below each span row |
| Console | only the expected 404s (cross-tenant checks) and one 401 from a deliberate unauthenticated fetch |

Issues found in the browser and fixed:
- The summary strips overflowed with long measured values. Fixed with a scoped `observe-strip` that stacks and wraps (the dashboard is unchanged).
- Truncated span names now have full-name tooltips.

## M1–M9 regression

- **Test suites:** all M1–M9 suites pass on SQLite and PostgreSQL. Run results, events, memory, knowledge, approvals and policy behave as before.
- **Run lists:** default run lists, the approval inbox, user threads and memory exclude evaluation artifacts.
- **Approvals:** the approval inbox now joins team runs to exclude evaluation approvals; the M6 tests pass unchanged.

## Caveats

- **Durations:** deterministic local steps are sub-millisecond, so most of the waterfall is worker and database time. Bars have a minimum width, and labels show the real durations.
- **No usage data:** no token or cost data exists, because the provider reports none.
- **Retention:** trace retention is documented, not automated.
- **Aggregation limit:** summary aggregation reads up to 5,000 traces per window.
- **No backfill:** pre-M10 runs have no traces.
- **Demo RAG case:** it expects the `docs/demo-knowledge/` PDF to be in the knowledge agent's source.
- **QA access:** the browser QA reused the existing QA session; no password was typed in this pass.

## Addendum: memory recall isolated in the demo dataset (2026-10-10)

**Root cause.** The demo's "Memory recall" case had no fixed target, so it ran on the evaluation's target agent. When that agent holds `internal:knowledge_search` and a knowledge source, the runtime correctly routes the general question to knowledge search. The answer still contained Maya Chen / North America from memory, but the intent was `knowledge_search` with a tool call, so the case failed. This was not a memory regression.

**Reproduction.** In QA Org A, the dataset was run with target QA Researcher (which holds `knowledge_search` and Enterprise Security Knowledge) and QA Account Team. The result was **9/10**: Memory recall failed with intent `knowledge_search` and tool `internal:knowledge_search`.

**Fix.**
- **Memory-only agent:** demo creation (`ensure_memory_agent`) gets or creates "Evaluation · Memory-only Agent" per workspace: active, no enabled tools, no enabled knowledge sources. It refuses (`409 memory_agent_not_isolated`) if that agent has since been given tools or knowledge.
- **Pinned case:** "Memory recall" is pinned to that agent. The expectation is unchanged: completed, `memory_recall`, no tool call, Maya Chen, North America.
- **Unchanged:** runtime routing, other agents' configuration, and every other case.
- **QA dataset:** the existing dataset was updated in place by pinning its case through `PATCH /evaluation-cases/{id}`, so its run history is kept.

**Result.** Same knowledge-enabled target: **10/10, 100% pass rate**. Memory recall: intent `memory_recall`, tools `[]`, all 5 checks pass. The run snapshot records the memory agent (tools `[]`, knowledge `[]`, status active, its own config hash). With QA Operations Assistant as target: also 10/10.

**Isolation.** 0 pending approvals; only the 2 user threads; user memory list unaffected; Org B reading the run gets 404. One memory agent per organization (tested).

**Regression.**
- PostgreSQL: 468 passed. SQLite: 463 passed, 5 skipped. Evaluation tests: 16 passed (adds `test_demo_refuses_a_memory_agent_that_is_not_isolated`; the demo test now targets a knowledge-enabled agent).
- Worker: 32 passed, 1 skipped. MCP: 15 passed. Frontend: 49 passed.
- Ruff, ESLint, TypeScript and the production build are clean. `alembic check` is clean. All six services are healthy.
