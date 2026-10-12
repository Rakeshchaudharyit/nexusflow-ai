# Architecture through M11

Browser authentication flows through the same-origin Next.js /api/backend/* proxy to FastAPI /api/v1 and PostgreSQL. The Next.js /app server layout reads a nonrotating cookie session before rendering. The public M1 status panel continues calling API health/readiness directly.

API_INTERNAL_URL is server-only and resolves to the api service in Compose. NEXT_PUBLIC_API_URL is browser-accessible. Container hostnames are never used by the browser.

FastAPI opens SQLAlchemy and Redis clients during lifespan startup and closes them on shutdown. Auth uses request-scoped database sessions. Configuration validates database/JWT secrets, production cookie security, and explicit origins. See [authentication](authentication.md) for sessions, roles, and tenant boundaries.

Health is independent of infrastructure. Readiness performs PostgreSQL SELECT 1 and Redis PING and reports dependency failures independently with HTTP 503. Redis is not used for authentication.

Compose gates startup on healthy services, binds local ports to loopback, and runs API/web as unprivileged users. PostgreSQL persists in a named volume; Redis is ephemeral (since M7 it carries job ids only, and recovery re-sends anything a Redis restart loses). The existing local API port is 8002. These settings are a local development baseline.

Alembic preserves M1's empty baseline, adds four identity tables in M2, three agent runtime tables in M3 (0003_agent_runtime), two MCP registry tables in M4 (0004_mcp_registry) and four team tables plus team-aware events in M5 (0005_multi_agent_orchestration), with UUID foreign keys, unique emails/slugs/memberships, role constraints, and refresh-session indexes. Migrations run explicitly rather than racing on application startup.

Approval, memory, knowledge, tracing and evaluation resources use organization foreign keys and verified membership dependencies. M11 preserves this architecture, adds production configuration validation and bounded upload parsing, and introduces an opt-in demo lifecycle without schema changes.

## Agent Runtime Architecture

```text
Authenticated user
  │  JWT access token (M2)
Organization context
  │  X-Organization-ID verified against organization_memberships on every request
Agent definition          agents            (organization-owned, draft/active/archived)
  │
Agent run API             POST /api/v1/agents/{id}/runs
  │
Agent runtime service     AgentRuntime.execute(run_id)
  │
LangGraph StateGraph      analyze_request → create_plan → [execute_demo_tool] → compose_response
  │                       └─ tools: calculator, customer_lookup, system_status (local, deterministic)
Run + events              agent_runs (status, snapshot, output)  agent_run_events (append-only)
  │
PostgreSQL
```

Route handlers only parse requests and call `app/services/agents.py`, which owns tenant-scoped lookups and run creation. Orchestration lives in `app/agents/`, independent of HTTP, so the Dramatiq worker executes the same persisted queued runs. Nodes are pure state transforms; persistence happens in a recorder invoked by a wrapper around each node. Per-run dependencies travel through LangGraph's runtime `context`, not graph state.

Runs commit as `queued` before execution, and each lifecycle write is its own short transaction; no transaction spans graph execution. PostgreSQL is the source of truth; Redis is not used by the runtime. Composite foreign keys tie runs and events to the same organization as their agent and run. See [agent runtime](agent-runtime.md) for the state model, transaction and error details.

## Tool and MCP Architecture (M4)

```text
LangGraph runtime
  │
Tool Resolver ─────────────┐   keys: internal:<tool> | mcp:<server-slug>:<tool>
  │                        │
Internal tools          MCP Tool Adapter (per run, bound to the run's organization)
(ToolRegistry, M3)         │  enabled/available checks, JSON Schema argument validation
                           │
                        MCP Client (official SDK v2, bounded httpx2, URL policy on every call)
                           │  Streamable HTTP (internal Docker network)
                           │
                        MCP Server (mcp-demo container)
                           ├─ search_customer
                           ├─ calculate
                           └─ get_platform_info
```

MCP servers and their discovered tools are organization-owned rows (`mcp_servers`, `mcp_tools`, migration 0004). Graph nodes and route handlers never speak MCP: nodes see only tool keys and results, and routes call `app/services/mcp_servers.py`. Discovery persists normalized tool metadata, but every call re-checks the live server. Outbound URLs pass an allowlist-first SSRF policy, and only `mcp-demo:8765` is allowlisted in Compose. MCP availability is tracked per server and does not affect `/health/ready`. See [MCP integration](mcp-integration.md).

## Multi-Agent Architecture (M5)

```text
User goal
  │
Supervisor (supervisor_plan → supervisor_review)
  │
LangGraph router (conditional edges; legal-step checks, revision cap, iteration cap)
  ├───────────────┬───────────────┬───────────────┐
Customer        Researcher       Analyst          (only roles the team has, in plan order)
Specialist      (demo dataset)   (scoring)
  │ toolbox: assigned internal or MCP lookup
  └───────────────┴───────────────┘
          │ every result returns to the supervisor
        Writer
          │
        Validator ── rejected (max 1) ──► Writer
          │ approved
        Result (agent_team_runs.final_output)
```

Teams, members, team runs and per-agent tool assignments are organization-owned tables (migration 0005). They are tied together by composite foreign keys, so a team cannot include another tenant's agent and an agent cannot be granted another tenant's MCP tool. Team runs reuse the M3 machinery: the immutable `agent_run_events` table (extended with `team_run_id`, `agent_id`, `agent_role`), the shared `EventStream` for short-transaction persistence, the `ToolResolver`, and the M4 MCP adapter. Specialists get only role-specific context slices and only their enabled tool assignments. See [multi-agent orchestration](multi-agent-orchestration.md).

Compose runs five services: web, api, postgres, redis and mcp-demo. The API does not depend on mcp-demo starting; MCP is an optional integration.


## Human Approval and Policy Controls (M6)

A team run may propose one business action after its validated result. The flow:

```text
Supervisor
  ↓
Specialists
  ↓
Writer
  ↓
Validator
  ↓
Finalize
  ↓
Propose Action
  ↓
Apply Policy
├── ALLOW
│     ↓
│   Execute Action
│     ↓
│   Complete
│
├── REQUIRE_APPROVAL
│     ↓
│   Persist Approval
│     ↓
│   Awaiting Approval   (the HTTP request ends here)
│
└── DENY
      ↓
    Record Denial
      ↓
    Complete            (run status failed, error policy_denied; nothing executed)
```

A later, separate human request continues the run:

```text
Pending Approval
  ↓
Human Approves          (owner/admin; members receive 403)
  ↓
Policy Rechecked        (approval row, then run row, locked FOR UPDATE)
  ↓
Execute Exactly Once    (unique constraints on action_executions)
  ↓
Complete Team Run
```

A rejection records the decision and completes the run with action status `rejected`; nothing executes.

**This is application-level persisted approval continuation. It is NOT yet general-purpose durable LangGraph checkpoint resume.** The graph is not re-entered after a pause. Since M7 the approve request commits the decision and an `approval_action` job; the worker (`execute_approved_action`) runs the action once and finishes the run from persisted rows in one locked transaction.

- **Policy:** rules live only in `app/policies/engine.py`, separate from tool permissions. Prompts, instructions and payloads are never policy inputs.
- **Actions:** local simulations in `app/actions/`. No email, CRM or MCP call is made, and the MCP layer is unchanged.
- **TeamState:** gains `proposed_action`, `policy_decision`, `approval_request_id` and `action_result`, all plain JSON.
- **Events:** M6 events go to the shared `agent_run_events` stream on the team run's sequence; there is no second timeline.
- **Tenancy:** approvals and executions are organization-owned (migration 0006), with composite tenant foreign keys and organization-scoped queries.
- **Scope:** single-agent runs are unaffected by policy. (M7 moved execution of all runs, including approved actions, into the background worker.)

See [human approval](human-approval.md) and [M6 validation](m6-validation.md).


## Background Execution, Durable Jobs and Recovery (M7)

Graph execution no longer happens inside HTTP requests. The API persists the run and an `ExecutionJob` in one transaction, enqueues only the job id, and returns `queued` within milliseconds. A separate `worker` service (Dramatiq 2.2.1, same image as the API) claims the job in PostgreSQL and runs the unchanged LangGraph runtimes.

```text
Browser
  ↓
FastAPI
  ↓
PostgreSQL Run + ExecutionJob      (one transaction; PostgreSQL is authoritative)
  ↓
Redis Queue                        (job id only; transport, never state)
  ↓
Worker                             (atomic claim: queued → running, one winner)
  ↓
LangGraph                          (AgentRuntime / TeamRuntime, unchanged graphs)
  ↓
Events / Result                    (shared immutable timeline, events tagged with attempt)
  ↓
PostgreSQL                         (run + job settled in the same transaction)
```

Recovery, run by every worker at boot and every `JOB_RECOVERY_SECONDS`:

```text
Running
  ↓
Stale Heartbeat                    (no heartbeat for JOB_STALE_AFTER_SECONDS)
  ↓
Recovery                           (lock approval → run → job, re-check)
  ↓
Retry / Fail                       (attempts left: re-queue · limit reached: fail · cancel requested: cancel)
```

- **Retries:** transient failures (`mcp_unavailable`, `mcp_timeout`, lost worker) retry with bounded backoff, up to `JOB_MAX_ATTEMPTS`. Permanent failures (`policy_denied`, invalid input or tools) fail once.
- **Redelivery:** queued jobs never handed to Redis, or whose messages were lost, are re-sent.
- **Exactly-once:** duplicate deliveries are harmless because claiming admits one execution. Business actions stay exactly-once across restarts: earlier approvals and executions are reused.
- **Cancellation:** immediate for queued runs, cooperative between graph stages for running runs. A run awaiting approval is cancelled along with its pending approval.
- **Not node-level resume:** restarted attempts re-run the graph from the beginning. This is durable job restart, not LangGraph checkpoint resume.

See [background execution](background-execution.md) and [M7 validation](m7-validation.md).


## Agent Memory and Context Management (M8)

Runs may belong to a **thread** (a conversation). Before graph execution the worker loads a bounded, tenant-scoped memory context, passes it to the graph as delimited reference data, and after a validated result writes new facts back in the same transaction that completes the run.

```text
User / Agent Run                   (optional thread_id; validated: same org, not archived)
  ↓
Thread                             (memory_threads; runs link via composite FK)
  ↓
Memory Retrieval                   (org + active + not expired + scope: thread / agent / opt-in workspace)
  ↓
Context Builder                    (summary → pinned → scope → importance → recency;
                                    MEMORY_MAX_ENTRIES / MEMORY_MAX_CHARS; count-only usage on the run)
  ↓
LangGraph                          (RunContext.memory / TeamRunContext.memory, never graph state;
                                    "MEMORY CONTEXT … END MEMORY CONTEXT" as data, not instructions)
  ↓
Validated Result                   (customer lookup found · team validation passed · approval executed)
  ↓
Memory Writer                      (idempotent upserts under a thread row lock; one memory_saved/updated event)
  ↓
PostgreSQL                         (memory_entries with source traceability; deterministic thread summary)
```

- **Memory has no authority.** It never selects tools, changes routing or plans, or affects M6 policy, which still evaluates the proposed action.
- **Team runs:** the supervisor receives the context. Only the writer's handoff carries memory, at most 3 notes about the company.
- **Failure paths:** failed and cancelled runs write nothing. Retries and duplicate deliveries upsert the same rows.
- **Not RAG:** there are no embeddings, vector search or documents.

See [memory and context](memory-context.md) and [M8 validation](m8-validation.md).


## Knowledge / RAG Platform (M9)

Organizations upload reference documents. The M7 worker ingests them into PostgreSQL with pgvector (Compose builds pgvector 0.8.6 into the same `postgres:17-alpine` image, so the data volume and collation are unchanged). Agents search only the sources they were granted. Knowledge is separate from M8 memory: different tables, a different context block, and no shared writes.

Ingestion:

```text
Knowledge Source
      ↓
Document                 (validated, checksummed, stored on the knowledge_uploads volume)
      ↓
M7 Worker                (knowledge_ingestion job; retries, recovery, cancellation as in M7)
      ↓
Extract                  (TXT/MD · pypdf · python-docx; no OCR)
      ↓
Chunk                    (structure-aware, 1200 / 200 overlap, page-bounded)
      ↓
Embed                    (deterministic_local 384-d, or OpenAI at 384-d)
      ↓
PostgreSQL + pgvector    (chunks replaced in one transaction with the job; HNSW + GIN indexes)
```

Query:

```text
Agent
  ↓
knowledge_search         (internal tool; needs the tool grant AND source grants)
  ↓
Tenant/Permission Filter (organization_id + allowed source_ids inside the SQL)
  ↓
Semantic + Lexical Retrieval (pgvector cosine · PostgreSQL full-text)
  ↓
Hybrid Rank              (0.7 × semantic + 0.3 × keyword, threshold, diversity, budget)
  ↓
Context + Citations      (KNOWLEDGE CONTEXT block, [K#] ids, structured citations)
  ↓
LangGraph
  ↓
Grounded Answer          (quoted passages with [K#]; "could not find enough information" otherwise)
```

- **Team runs:** each member searches only its own agent's grants. In the deterministic team the researcher retrieves, the writer cites at most 2 passages, and the validator rejects any citation that does not match a retrieved passage.
- **Untrusted data:** document text is delimited, one line per passage. It never changes tools, routing, sources or M6 policy.

See [knowledge and RAG](knowledge-rag.md) and [M9 validation](m9-validation.md).


## Observability, Tracing and Evaluation (M10)

Two separate systems. **Observability** records what actually happened; **evaluation** checks behavior against defined expectations. They share no tables.

Runtime path:

```text
Run                      (agent/team run + its RunTrace, committed together)
 ↓
Execution Job            (M7, PostgreSQL-authoritative)
 ↓
Worker                   (attempt = worker span: job id, attempt, worker id, queue wait)
 ↓
LangGraph                (node / agent / tool / MCP / memory / knowledge / policy /
                          approval / action spans, monotonic timings, collected in memory)
 ↓
Trace + Spans            (flushed once per attempt after the business commit; never fails a run)
 ↓
Events / Results         (the immutable business timeline and run results, unchanged)
```

Evaluation:

```text
Evaluation Dataset       (cases with deterministic expectations)
 ↓
Evaluation Run Job       (M7 job_type evaluation_run; API returns queued)
 ↓
Real Agent/Team Runtime  (child runs tagged evaluation_run_id, isolated threads, never approved)
 ↓
Actual Run               (with its own trace)
 ↓
Deterministic Checks     (status, intent, tool, output, values, policy, citations, Hit@K, MRR)
 ↓
Evaluation Result        (one per case; config snapshot + hash on the run)
 ↓
Comparison / Regression  (regressions, improvements, deltas vs a baseline)
```

- **Authority:** the run row stays authoritative for status, timings and errors. Traces add attempts, queue wait, retries and the span tree. Retries, recovery and the approval continuation stay in one logical trace.
- **Tenant isolation:** every trace, span, dataset, case, run, result and aggregate is organization-scoped in SQL and by composite foreign keys.
- **Self-contained:** no external APM, collector or SaaS; no token or cost figures, because none are reported.

See [observability and evaluation](observability-evaluation.md) and [M10 validation](m10-validation.md).
