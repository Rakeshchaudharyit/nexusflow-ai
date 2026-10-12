# M5 validation — 2026-10-07

M5 is complete. M6 has not started. Earlier records: [M4](m4-validation.md), [M3](m3-validation.md), [M2](m2-validation.md), [M1](validation.md).

| Check | Executed result |
| --- | --- |
| PostgreSQL backend suite | 293 passed (238 M1–M4 + 55 M5), `-W error` clean |
| SQLite fallback suite | 291 passed, 2 skipped (PostgreSQL concurrency and migrations) |
| Demo MCP server suite | 15 passed |
| Frontend tests | 17 passed (6 auth + 4 agents + 3 MCP + 4 teams/tool assignments) |
| Multi-agent graph tests (14) | Plan-order node sequence `supervisor_plan → customer_specialist → researcher → analyst → writer → validator → finalize`, with a supervisor review after every agent; plan-driven routing for a team without a customer specialist; supervisor may reorder gathering but cannot skip ahead; role-specific context slices |
| Revision loop | Forced bad first draft → validator rejects → exactly one revision → approved; always-bad drafts → `revision_limit_exceeded` after 2 writer calls; raised revision limit with an iteration cap of 9 → `iteration_limit_exceeded` after 9 reviews |
| Tool permissions | Internal and MCP assignment; duplicate, unknown, malformed and foreign-tenant keys rejected; unassigned, wrong and disabled assignments → `tool_not_permitted`; disabled MCP tool → `mcp_tool_disabled` through the M4 adapter |
| Failures | Specialist crash: partial results, events and snapshot kept, `agent_failed` with safe code, secrets and exception types hidden; MCP outage → `mcp_unavailable`; optional specialist outage → team continues; unsupported objective, invalid plan, invalid decision and malformed validator output covered |
| Tenant isolation | Both directions: read/edit team, add/edit/remove members, run team, read run, read/assign tools → 404; foreign agents rejected as members at create and add; listings and filters scoped; spoofed header 404; composite FKs reject cross-tenant members and MCP grants |
| Security | Objective asking to switch organization, grant a foreign MCP tool and add a supervisor changed nothing (same 5-step plan, only the assigned tool used) |
| Migration | `0005_multi_agent_orchestration` round trip (→0004 →0003 … →0001 → head) in isolated schemas; `alembic check` clean. The check found the enum column needed widening from 14 to 23 characters, which the migration now does. Downgrade removes team events first |
| Ruff / ESLint / TypeScript / build | API 94 files and demo 4 files clean / passed / strict passed (it caught team events typed as single-run events) / Next.js build passed locally and in Docker |
| Docker | All five services healthy; real database migrated to 0005 with existing M3/M4 runs intact |
| Dependencies | No new packages in M5; `npm audit --omit=dev` 0 vulnerabilities |

## Manual demo (browser, Docker stack)

1. Signed in; workspace **M4 UI Workspace**.
2. Created and activated six agents: Enterprise Supervisor, Customer Specialist, Research Agent, Opportunity Analyst, Proposal Writer, Quality Validator.
3. On Customer Specialist, assigned `internal:customer_lookup` under Allowed tools; the catalog listed internal and this workspace's MCP tools.
4. Created **Enterprise Account Intelligence Team** in Create team, one agent per role, and activated it.
5. Ran *"Analyze Acme Corporation as a potential enterprise opportunity and recommend next steps."* The run completed in 24 ms over 5 agent steps: Customer Specialist → Researcher → Analyst → Writer → Validator. Result: Acme Corporation, opportunity score 92/100, strengths, risks, three next steps, validation approved at 0.95 confidence, and sources "demonstration" and "NexusFlow demonstration research dataset".
6. Run detail showed the supervisor plan, every agent's structured output, handoffs with the context keys passed (e.g. analyst: company, customer_context, research_context), and the 13-event timeline from team run started to team run completed.
7. **MCP variant:** removed the internal assignment and assigned `mcp:nexusflow-demo-tools:search_customer`. The rerun completed with an identical graph and result; the Customer Specialist called MCP via NexusFlow Demo Tools (71 ms) and the source changed to "NexusFlow demo MCP data".
8. **MCP outage:** with `mcp-demo` stopped, the run failed safely as `mcp_unavailable`. Its timeline held the plan, the handoff, the failed Customer Specialist naming the MCP server, and team run failed. After restarting the service, runs worked again.
9. **Cross-tenant:** switching to M4 Org A from the team page redirected to an empty team list. Direct URLs for the team, the team run and the Customer Specialist agent showed "not found". Synthetic user B received 404 from the API for team, members, run, run detail, tool listing, assignment and removal, and could not assign the MCP tool key. Switching back restored the team and its three runs.
10. At 375 px the team list, create form, team detail, team run detail and agent page all match the viewport width. The six-item navigation now wraps. No script errors.

Final live regression on the rebuilt containers: login, refresh rotation and `/me` passed; the M3 internal calculation and the M4 MCP calculation returned 3000; SSRF rejection returned 422; the team run completed with score 92; readiness reported ready.

## Caveats

- Execution is synchronous within the request; no queue, streaming or resume.
- One member per role per team; research is a fixed demonstration dataset; the deterministic provider ignores agent instructions.
- Agent tool assignments are enforced for team members only; M3 single-agent runs keep their unrestricted internal/MCP routing.
- Node and agent durations under 1 ms show as 0 ms.
- Carried from M3: a PostgreSQL outage mid-run can leave a run `running` until the reliability milestone adds recovery.
- Carried from M4: public MCP mode does not pin DNS (off by default).
