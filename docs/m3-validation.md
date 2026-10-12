# M3 validation — 2026-10-07

M3 is complete. M4 has not started. Earlier results remain in [M2 validation](m2-validation.md) and [M1 validation](validation.md).

| Check | Executed result |
| --- | --- |
| PostgreSQL backend suite | 127 passed (67 M1/M2 + 60 M3), no warnings |
| SQLite fallback suite | 125 passed, 2 skipped (PostgreSQL concurrency and migrations); also passes with `-W error` |
| Frontend tests | 10 passed (6 auth client + 4 agents client) |
| LangGraph tests | Node sequence, conditional tool skip, failed-node reporting and deterministic outputs verified without HTTP or a database |
| Tenant isolation | Both directions: foreign agents cannot be read, updated or run; foreign runs cannot be read; listings and `agent_id` filters are scoped; spoofed organization headers return 404 |
| Database ownership | Composite foreign key rejects a run referencing another organization's agent; duplicate `(run_id, sequence)` rejected |
| Tool context | Tools receive the server-created organization, user and run IDs even when input text contains other IDs; registry refuses missing or malformed context |
| Failure handling | Division by zero fails the run with `division_by_zero`, `node_failed` + `run_failed` events and earlier events retained; unexpected exceptions are replaced with a generic message in responses, events and snapshots |
| Migration round trip | Upgrade → downgrade to 0002 → downgrade to 0001 → upgrade in an isolated PostgreSQL schema; `state_snapshot` verified as JSONB |
| Alembic | `0003_agent_runtime` at head in Docker; `alembic check` reports no pending changes |
| Ruff | Check and format passed; 53 Python files |
| ESLint / TypeScript | Passed / strict typecheck passed |
| Production build | Next.js Webpack build passed locally and in Docker |
| Docker Compose | Config valid; rebuilt API and web; all four services healthy |

## Live API (Docker stack, port 8002)

| Input | Result |
| --- | --- |
| Run while draft | 409 `agent_not_active` |
| Look up Acme Corporation and summarize the account. | completed · `customer_lookup` · 4 steps · demonstration-data summary |
| What is 125 multiplied by 24? | completed · `calculator` · "125 multiplied by 24 is 3000." |
| Check platform system status. | completed · `system_status` · API, PostgreSQL, Redis ok |
| What is 7 divided by 0? | failed · `division_by_zero` · 2 completed steps |

Events for the lookup run were sequenced 1–10: `run_started`, start/complete pairs for the four nodes, `run_completed`. A second organization received 404 for the first organization's agent (read, update, run) and run, and 404 when sending the first organization's ID in `X-Organization-ID`.

With Redis stopped, login and agent runs still worked; the system status run completed and reported Redis unavailable; liveness stayed 200 and readiness 503. After Redis restarted, all services were healthy and readiness returned 200.

## Browser

Login; agent list; create "Operations Assistant" (draft, slug `operations-assistant-2` because the API pass had created the first); activate; run the three manual-test inputs from the test console; run history; run detail timelines for a completed and a failed run. Creating and switching workspaces from agent and run detail pages redirected to the new workspace's empty list; direct URLs for the other workspace's agent and run showed "not found"; switching back restored the original runs. At 375 × 812 the document width equalled the viewport. Logout redirected to `/login` and `/app/agents` required sign-in again.

Browser and API checks used synthetic identities on the local application; credentials are in the ignored `.env.m3-validation` (mode 0600).

## Caveats

- Execution is synchronous within the request; a background-worker milestone is needed for long-running agents.
- If PostgreSQL fails mid-run, the runtime cannot record the failure and the run can remain `running`; there is no reaper yet.
- Node durations exclude event persistence, so in-memory nodes typically report 0 ms; run duration includes persistence.
- Intent classification is rule-based by design and understands only the demo intents.
- The M1 development-only ESLint dependency advisory documented in [validation](validation.md#upstream-tooling-limitation) is unchanged.
