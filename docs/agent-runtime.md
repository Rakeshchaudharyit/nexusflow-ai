# Agent runtime (M3)

M3 adds the execution core that later NexusFlow agents will use: tenant-owned agent definitions, a LangGraph `StateGraph`, deterministic local tools, persisted runs, and an ordered event stream. It is infrastructure, not an autonomous agent. M4 adds MCP tools behind the same tool contract; see [MCP integration](mcp-integration.md). **Multi-agent supervision, RAG, approvals, background workers and checkpoint/resume are not implemented.**

## Dependency

`langgraph==1.2.14`, pinned in `apps/api/pyproject.toml` and locked with its full transitive graph in `apps/api/requirements.lock`. The code uses only `StateGraph`, `START`/`END`, `add_conditional_edges`, `context_schema` and `langgraph.runtime.Runtime`; no deprecated APIs (verified with `pytest -W error`).

LangChain is not used directly. `langchain-core` (and `langsmith` through it) is a hard dependency of `langgraph` itself, so it appears in the lock. LangSmith tracing is off unless explicitly enabled through its own environment variables; tests force it off and disable its pytest plugin. `langgraph-sdk` caps `websockets<17`, so uvicorn's optional websockets dependency moved from 17.2 to 16.1.1.

## Code layout

| Module | Responsibility |
| --- | --- |
| `app/agents/state.py` | `AgentState` (graph schema), plan/tool/output shapes, `RunStateSnapshot` |
| `app/agents/intents.py` | Rule-based intent classification |
| `app/agents/nodes.py` | The four graph nodes; pure state transforms, no persistence |
| `app/agents/graph.py` | Graph topology, lifecycle instrumentation, compiled graph |
| `app/agents/context.py` | `RunContext` passed to LangGraph; `ExecutionRecorder` protocol |
| `app/agents/tools/` | Tool contract, internal registry, the three internal demo tools, and the `ToolResolver` (M4) that routes `internal:` and `mcp:` keys |
| `app/agents/providers.py` | `LLMProvider` protocol and `DeterministicLLMProvider` |
| `app/agents/recorder.py` | `RunRecorder`: run status, events and snapshot persistence |
| `app/agents/runtime.py` | `AgentRuntime.execute(run_id)`: orchestration and failure handling |
| `app/agents/errors.py` | Safe runtime exceptions |
| `app/services/agents.py` | Tenant-scoped CRUD, run creation, listing and detail |
| `app/api/v1/agents.py` | HTTP routes only |
| `app/models/agents.py`, `app/schemas/agents.py` | Persistence models and API schemas, kept separate |

## State model

`AgentState` is a `TypedDict`. LangGraph nodes return partial dictionaries that are merged into state, which a `TypedDict` describes directly without per-step validation or object copying. Validation happens at the boundaries instead: tool arguments are validated by each tool's Pydantic input model, and anything persisted or returned goes through Pydantic (`RunStateSnapshot`, API schemas). Every state value must be JSON-serializable.

| Key | Meaning |
| --- | --- |
| `run_id`, `organization_id`, `agent_id` | Informational string copies for the snapshot; never used for authorization |
| `user_input`, `instructions` | Untrusted text |
| `intent`, `arguments` | Classification result and extracted tool arguments |
| `plan` | Ordered `call_tool` / `compose_response` steps |
| `tool_source` | `internal`, or `mcp` when the input asks for MCP (M4) |
| `tool_results` | `{step, tool, tool_key, tool_type, status, output, metadata}` records |
| `final_output` | `{intent, summary, tools_used, provider}` |
| `errors`, `current_step` | Failure records and the last completed node |

The persisted `state_snapshot` is an allow-list: run, organization and agent ids, `input_text`, intent, plan, tool results, final output, errors and current step. Agent instructions and any other key are excluded.

Per-run dependencies — the tool execution context, tool resolver, LLM provider and recorder — are passed through LangGraph's `context=` (`RunContext`), not state. Nodes cannot modify them and they are never persisted.

## Graph

```text
START → analyze_request → create_plan ─┬─→ execute_demo_tool → compose_response → END
                                        └─────────────────────→ compose_response   (no tool planned)
```

- **analyze_request** classifies the input with ordered rules: two standalone numbers joined by an operator → `calculation`; a named demo customer → `customer_lookup`; platform/system/service wording with status/health/readiness → `system_status`; look-up wording → `customer_lookup`; otherwise `general`. Digits inside identifiers (UUIDs, SKUs) are not treated as arithmetic.
- **create_plan** maps the intent to at most one tool call followed by `compose_response`. There are no planning loops.
- **execute_demo_tool** runs each `call_tool` step's `tool_key` through the resolver with the server-created execution context. The name dates from M3; it executes internal and MCP tools alike.
- **compose_response** asks the configured provider for the summary and assembles the structured output.

The conditional edge skips the tool node for `general` requests, so the event trace never shows a tool step that did not happen. The graph is compiled once without a checkpointer; it holds no per-run data and is safe to share across concurrent runs.

## Tools

`ToolDefinition` (name, description, Pydantic input model, JSON schema), `ToolResult` and `ToolExecutionContext` (organization, user and run UUIDs) form the contract. `ToolRegistry.execute` refuses to run without a valid context, rejects unknown tools, validates arguments, and converts outputs to JSON-safe values. **The internal registry is in-process and is not an MCP server.** Since M4, plans carry stable keys (`internal:calculator`, `mcp:<server-slug>:<tool>`) and nodes call a `ToolResolver`, which sends internal keys to the registry and `mcp:` keys to an organization-bound `McpToolProvider`. `tools_used` lists these keys.

| Tool | Behaviour |
| --- | --- |
| `calculator` | One of add/subtract/multiply/divide on two `Decimal` operands bounded to ±10¹². No `eval`, no expression parsing. Division by zero raises `ToolExecutionError(code="division_by_zero")`. |
| `customer_lookup` | Matches three fixed records (Acme Corporation, Northstar Labs, Atlas Retail). Every result carries `data_source: "demonstration"`; these are not CRM records. Unknown names return `found: false`. |
| `system_status` | Calls `app.services.health.check_readiness`, the same probe behind `/health/ready`, so it reports live PostgreSQL and Redis state. |

## Provider abstraction

`LLMProvider` is a protocol with one method, `generate(GenerationRequest) -> str`. M3 ships only `DeterministicLLMProvider`, which renders fixed templates from tool results. It does not reason or call a model, and every output records `provider: "deterministic"`. `LLM_PROVIDER=deterministic` is the only accepted value. A live OpenAI provider was deferred: adding it cleanly needs a client dependency, key handling, timeouts and cost controls that do not belong in this milestone. Tests, Docker and CI need no API keys or network access.

## Run lifecycle and transactions

```text
POST /agents/{id}/runs
  1. membership + tenant-scoped agent lookup; agent must be active        (request session)
  2. insert run status=queued; COMMIT
  3. AgentRuntime.execute(run_id)
       start():  lock run, queued→running, started_at, event run_started; COMMIT
       each node: node_started; COMMIT … node_completed | node_failed; COMMIT
       finish:   status, completed_at, duration, step_count, snapshot,
                 final_output or error, event run_completed | run_failed; COMMIT
  4. reload run and return AgentRunResult
```

No transaction is held open while the graph runs. Each write is a short transaction on a fresh session from the application's session factory, so events are durable as they happen and earlier events survive a later failure. `execute` only accepts `queued` runs (`run_not_queued` otherwise) and re-checks that the agent is active, so a future worker can call it unchanged.

Since M7, execution runs in the background worker, not inside the request: the API persists the run and an `ExecutionJob`, enqueues the job id and returns `queued`; the worker claims the job and calls `execute(run_id, control)`. The `JobControl` adds attempt tagging, cooperative cancellation between graph stages (`POST /agent-runs/{id}/cancel`), and retries for transient failures. See [background execution](background-execution.md).

## Events

`agent_run_events` is append-only: rows are inserted once and never updated. Each run's `RunRecorder` numbers its events 1..n, and `uq_agent_run_events_run_sequence` rejects duplicates. A successful tool run produces:

```text
1 run_started   2–3 analyze_request   4–5 create_plan   6–7 execute_demo_tool
8–9 compose_response   10 run_completed
```

`node_started` stores the state keys that node reads; `node_completed` stores the node's state update; failure events store an error code and safe message. Durations are milliseconds. Payloads are JSONB on PostgreSQL (JSON on the SQLite test fallback).

## Error model

| Situation | Result |
| --- | --- |
| Unknown or other-tenant agent/run | 404 `agent_not_found` / `run_not_found` |
| Organization header without membership | 404 `organization_not_found` (M2 behaviour) |
| Draft or archived agent | 409 `agent_not_active`; no run is created |
| Invalid status transition / editing an archived agent | 409 `invalid_status_transition` / `agent_archived` |
| `AgentRuntimeError` during execution (e.g. `division_by_zero`, `invalid_tool_arguments`, `unknown_tool`) | 201 with `status: failed` and its safe code/message |
| Any other exception during execution | 201 with `status: failed`, `agent_execution_failed`, generic message; details only in server logs |

A failed run is a created, persisted resource, so the run endpoint returns 201 with the failure in the body and the full timeline available from the detail endpoint. Raw exception text, types and tracebacks never reach responses, events or snapshots.

## Tenant boundaries

- Agent routes use M2's `CurrentMembership`, which verifies the `X-Organization-ID` header against PostgreSQL on every request. Creating and updating agents additionally requires owner or admin; members can list, read and run.
- All lookups go through `app/services/agents.py` with `organization_id` in the `WHERE` clause, so another tenant's UUID is indistinguishable from a missing one.
- Composite foreign keys enforce ownership in the database: `agent_runs(agent_id, organization_id) → agents(id, organization_id)` and `agent_run_events(run_id, organization_id) → agent_runs(id, organization_id)`. A run cannot reference another organization's agent even through a direct insert.
- Request bodies forbid unknown fields, so a client cannot supply `organization_id` or `created_by_user_id`.
- Tools receive a `ToolExecutionContext` built from the persisted run row, never from input text, instructions or graph state.

### Prompt-injection rule

Agent instructions and user input are untrusted application data. They can influence generated prose but never authorization, tenant context, tool selection permissions or execution context. MCP tools (M4) follow the same rule: the provider is bound to the run's organization from the persisted run, and server names or IDs in input text never select a server.

## Indexes

`uq_agents_organization_slug` serves per-organization agent lookups and listing; `ix_agent_runs_organization_created` serves run history; `ix_agent_runs_agent_id` serves per-agent filtering and cascade checks; `uq_agent_run_events_run_sequence` serves ordered event reads. Low-cardinality status columns are not indexed on their own.

## Extension points

- **Live LLM providers:** implement `LLMProvider` and extend `create_llm_provider`.
- **More tool sources:** implement `ToolProvider` (`find`, `execute`) and register it with `AgentRuntime(providers=...)`, as M4 does for MCP.
- **Background workers:** enqueue the `queued` run and call `AgentRuntime.execute(run_id)` from the worker.
- **Checkpoint/resume:** compile the graph with a LangGraph checkpointer; M3 deliberately does not, and runs are not resumable.
