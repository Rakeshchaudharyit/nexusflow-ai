# Multi-agent orchestration (M5)

M5 lets several tenant-owned agents work as a team under a supervisor. Orchestration is a real LangGraph `StateGraph`: the supervisor plans the work, picks the next agent through conditional edges after every step, and sends the draft to a validator. A bounded revision loop handles rejections. Execution is deterministic by default. (Human approvals arrived in M6; background execution with durable jobs and recovery in M7. Node-level checkpoint resume, memory, RAG, web research and live LLM providers are not implemented.) Single-agent M3 runs are unchanged.

## Team model

| Table | Purpose |
| --- | --- |
| `agent_teams` | Organization-owned team: name, slug, description, `draft`/`active`/`archived` status |
| `agent_team_members` | Agent ↔ team with an orchestration `role`, `position` and `is_required` |
| `agent_team_runs` | One execution: objective, status, final output, state snapshot, safe error, timings |
| `agent_tools` | Per-agent tool permissions (`tool_key`, `is_enabled`, and `mcp_tool_id` for MCP tools) |
| `agent_run_events` | **Extended**, not duplicated: every event belongs to exactly one agent run *or* team run and may name the acting `agent_id`/`agent_role` |

Roles are orchestration roles, unrelated to organization RBAC: `supervisor`, `customer_specialist`, `researcher`, `analyst`, `writer`, `validator`. Each role is filled at most once per team (`uq_agent_team_members_team_role`), which also makes the supervisor unique, and an agent appears once per team. A team can be activated, and run, only with exactly one supervisor, at least one specialist (customer specialist, researcher or analyst), a writer, a validator, and all member agents active. Changes to an active team's membership are rejected if they would make it invalid. Archived teams are read-only until restored to draft. Behaviour comes from the configured role, never from agent names.

Database ownership guarantees: composite foreign keys tie members to the team's organization and the agent's organization, team runs to their team's organization, events to their run's organization, and MCP tool assignments to an MCP tool row in the same organization. Each event row has exactly one parent run, enforced by `ck_agent_run_events_single_parent`.

## Graph

```text
START → supervisor_plan → supervisor_review ──(conditional)──┬→ customer_specialist ┐
                              ▲                             ├→ researcher          │
                              │                             ├→ analyst             │
                              │                             ├→ writer              │
                              │                             ├→ validator           │
                              └─────────────────────────────┴──────────────────────┘
                                                            └→ finalize → END
```

- **supervisor_plan** asks the provider for a plan, then maps each planned role to the server-built roster. Plans that name roles the team lacks, repeat a role, include the supervisor, or omit the writer, the validator or every specialist fail with `invalid_plan`. The provider never supplies agent IDs.
- **supervisor_review** runs after planning and after every agent. It computes the legal next steps (`legal_next`), asks the provider to choose, rejects illegal choices (`invalid_supervisor_decision`), and routes through a conditional edge.
- **Agent nodes** (one per role) receive only their task context, do their work, and return to the supervisor. Specialists never call each other.
- **finalize** assembles the structured result.

`legal_next` always moves the run forward: information gatherers (customer specialist, researcher) first in any order, then the analyst, then writer → validator → finalize, and back to the writer only after a rejected draft. The routing test shows a team without a customer specialist skipping straight from planning to the researcher. A provider that reorders gathering is honored, but one that jumps ahead is refused.

## Shared state

`TeamState` (TypedDict, JSON values only): `run_id`, `organization_id`, `team_id`, `objective`, `company`, `plan`, `current_agent`, `next_agent`, `completed_agents`, `failed_agents`, `customer_context`, `research_context`, `analysis_context`, `draft_output`, `validation_result`, `final_output`, `errors`, `iteration`, `revisions`. Sessions, tool clients, the team roster and agent instructions live in `TeamRunContext` (LangGraph runtime context), never in state. The persisted `state_snapshot` is an allow-listed model of the same fields.

## Roles

| Role | Receives | Produces | Tools |
| --- | --- | --- | --- |
| Supervisor | objective, roster (role + agent name) | plan; next-step decisions; revision requests | none |
| Customer Specialist | objective, company | company, segment, status, account owner, region, source | its assigned customer lookup: `internal:customer_lookup` or `mcp:<server>:search_customer` |
| Researcher | objective, company | demonstration signals labelled "NexusFlow demonstration research dataset", plus a not-current-research notice | none (no web access) |
| Analyst | company, customer context, research context | opportunity score, strengths, risks, recommended action | none |
| Writer | objective, company, customer, research and analysis contexts, revision feedback | title, executive summary, key findings, next steps, cited facts and signals | none |
| Validator | draft, customer, research and analysis contexts | `{valid, issues, confidence}` | none |

The customer specialist uses the first enabled assignment, in assignment order, whose tool is `customer_lookup` or `search_customer`, so configuration decides between internal and MCP lookup. With MCP, the call goes through the M4 `McpToolProvider` and `McpClient` unchanged.

## Provider

`TeamProvider` (`plan`, `decide`, `analyze`, `write`, `validate`) is the reasoning seam; `DeterministicTeamProvider` is the M5 default, selected by `LLM_PROVIDER=deterministic`. It extracts a demo company from the objective, follows the plan order, scores opportunities with explicit rules (e.g. Acme: 50 + Enterprise 20 + active 10 + 3 signals × 4 = 92), writes a bounded draft (summary ≤ 600 characters, lists ≤ 8 items), and validates grounding. Validation checks that required sections are present, that every cited fact (company, segment, status, account owner, score) matches earlier findings, that cited signals exist in the research context, and that the analyst's recommended action is included. No external API is called.

## Handoffs and context minimization

Each agent node records `handoff_started` with `from: supervisor`, the target role and agent name, the task, and exactly the context slice it passes (`CONTEXT_FOR`). The customer specialist gets only the objective and company; the analyst gets only the customer and research contexts; and so on. Results return as `agent_completed` (output and tool calls), and the supervisor chooses again. The detail API reconstructs handoffs and per-agent results from these events.

## Tool permissions

`agent_tools` assigns tool keys to agents. A key is accepted only if it resolves to an internal tool or to an available MCP tool discovered in the caller's organization; other organizations' tools are rejected with the same error as missing ones, and `mcp_tool_id` makes a cross-tenant MCP grant impossible in the database. At run start the server loads each member's **enabled** assignments into its `AgentToolbox`. A specialist calling anything else fails with `tool_not_permitted`. MCP server and tool enablement is still enforced by the M4 adapter (`mcp_server_disabled`, `mcp_tool_disabled`). Researcher, analyst, writer, validator and supervisor use no tools in M5. M3 single-agent runs do not consult assignments, so their behaviour is unchanged; enforcing assignments there is a later change.

## Bounded loops

- **Revisions:** at most `MAX_REVISIONS = 1`. After a rejected draft the supervisor may send it back to the writer once (`revision_requested`). A second rejection fails the run with `revision_limit_exceeded`.
- **Iterations:** supervisor reviews are capped at `plan length + 2 × max_revisions + 1`, which is 8 for a full team. Exceeding it fails with `iteration_limit_exceeded`.
- **Backstop:** LangGraph `recursion_limit = 64`; a `GraphRecursionError` also maps to `iteration_limit_exceeded`.

All limits live in `TeamLimits`; tests raise `max_revisions` and lower `max_iterations` to prove the cap stops a supervisor that keeps asking for revisions.

## Events

New event types: `team_run_started`, `supervisor_plan_created`, `handoff_started`, `agent_completed`, `agent_failed`, `validation_failed`, `revision_requested`, `team_run_completed`, `team_run_failed`. A successful five-agent run produces 13 events. Payloads hold plans, task context slices, outputs, tool-call metadata (key, type, server, duration) and safe error codes. They never hold instructions, credentials, URLs or raw exceptions.

## Transactions

As in M3: the run is committed as `queued` before execution. Every event and status change is its own short transaction through the shared `EventStream`, so the plan, each handoff and each agent result are durable when they happen. The final snapshot and output are written in the last transaction. No transaction spans graph execution.

## Failure handling

| Failure | Behaviour |
| --- | --- |
| Required specialist, writer or validator fails | `agent_failed` (safe code, `fatal: true`) → run `failed`; earlier events, results and snapshot contexts are kept |
| Optional specialist fails (`is_required = false`) | `agent_failed` (`fatal: false`), role added to `failed_agents`, team continues; e.g. analysis notes the missing customer record |
| Tool not assigned or disabled | `tool_not_permitted` |
| MCP outage, timeout, disabled MCP tool | M4 codes (`mcp_unavailable`, `mcp_timeout`, `mcp_tool_disabled`) with tool and server details on the failure event |
| Invalid plan or decision, malformed validator output | `invalid_plan`, `invalid_supervisor_decision`, `invalid_output` |
| Unknown company, nothing to analyze | `objective_not_supported`, `insufficient_context` |
| Validator rejects twice | `revision_limit_exceeded` |
| Team inactive or member agent inactive at run time | 409 `team_not_active` before a run is created; `team_not_runnable` if it changes after |
| Anything unexpected | generic `team_execution_failed`; details only in server logs |

## Tenant isolation and security

Every team, member, assignment and run query filters by the caller's verified organization, and composite foreign keys back that up. The roster, the tool assignments and the execution context (organization, user, team run ID) are built by the server at run start. The objective and agent instructions are untrusted text: they cannot change organization context, add members, grant tools, select MCP servers or change roles. A test runs an objective that asks for exactly that and checks that nothing changes. Owners and admins manage teams and assignments; members can view and run teams.

## API

`/api/v1/agent-teams` (POST, GET), `/agent-teams/{id}` (GET, PATCH), `/agent-teams/{id}/members` (POST), `/agent-teams/{id}/members/{member_id}` (PATCH, DELETE), `/agent-teams/{id}/runs` (POST), `/agent-team-runs` (GET with `team_id`, `status`, `limit`), `/agent-team-runs/{id}` (GET: plan, results, handoffs, validation, events). Tool permissions: `/agents/{id}/tools` (GET, POST), `/agents/{id}/tools/{assignment_id}` (PATCH, DELETE), and `/tools` for the assignable catalog.

## Known limits

Since M7, team runs execute in the background worker (see [background execution](background-execution.md)). Each role is filled once per team. Research is a fixed demonstration dataset. Agent instructions are passed to the provider but ignored by the deterministic one. Since M7, a run whose worker dies is recovered by stale-heartbeat detection (retried or failed), so it no longer stays `running`.
