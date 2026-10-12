# M4 validation — 2026-10-07

M4 is complete. M5 has not started. Earlier records: [M3](m3-validation.md), [M2](m2-validation.md), [M1](validation.md).

| Check | Executed result |
| --- | --- |
| PostgreSQL backend suite | 238 passed (127 M1–M3 + 111 M4), `-W error` clean |
| SQLite fallback suite | 236 passed, 2 skipped (PostgreSQL concurrency and migrations) |
| Demo MCP server suite (`apps/mcp-demo`) | 15 passed, `-W error` clean |
| Frontend tests | 13 passed (6 auth + 4 agents + 3 MCP client) |
| MCP protocol tests | API tests run the real demo server and a mutable test server over loopback Streamable HTTP (protocol `2026-07-28`); deterministic `ExceptionGroup` classification tests cover transport failures |
| Discovery | First discovery, idempotent rediscovery, added/updated/retired tools, reappearing tools, preserved disable choice, URL change retiring tools |
| Execution | MCP customer lookup, calculation and platform info through LangGraph; events, snapshot and `tool_calls` persisted; internal tools unchanged |
| Failures | Unavailable, timeout (slow tool, under 3 s), tool removed from live server, invalid arguments (fields only, no values), output-schema mismatch, tool error, disabled tool, disabled server, no server configured |
| Tenant isolation | Both directions: read/update/test/discover/list tools/toggle tools → 404; spoofed organization header → 404; foreign tool under own server → 404; foreign agent cannot resolve or execute; composite FK rejects a cross-tenant tool row; adapter rejects mismatched context |
| SSRF | 42 URL-policy cases plus API-level rejection: loopback, `localhost`, link-local metadata, RFC 1918, Compose service names, `file`/`gopher`/`ftp`/`unix`/`ws`, credentials, queries, fragments, malformed ports, long URLs, and DNS answers containing any private address in public mode |
| Migration | `0004_mcp_registry`: upgrade → downgrade to 0003 → 0002 → 0001 → upgrade in an isolated schema; `alembic check` clean; schemas stored as JSONB |
| Ruff | API 72 files, demo 4 files: check and format passed |
| ESLint / TypeScript / build | Passed / strict typecheck passed / Next.js Webpack build passed (locally and in Docker) |
| Docker | `docker compose config` valid; web, api, postgres, redis and mcp-demo all healthy; SDK 2.3.0 in both images |
| Dependency audit | `pip check` clean; `pip-audit` reports no known vulnerabilities in either lock; `npm audit --omit=dev` 0 vulnerabilities |

## Live demo (Docker stack)

| Step | Result |
| --- | --- |
| Register `http://127.0.0.1:8765/mcp`, `http://169.254.169.254/...`, `file:///etc/passwd`, `http://postgres:5432/` | 422 `mcp_url_rejected` |
| Register NexusFlow Demo Tools at `http://mcp-demo:8765/mcp` | `pending`, slug `nexusflow-demo-tools` |
| Test connection | connected · `nexusflow-demo-mcp` 0.4.0 · protocol `2026-07-28` · 42 ms |
| Discover | `search_customer`, `calculate`, `get_platform_info` |
| "Use the MCP customer tool to look up Acme Corporation." | completed · `mcp:nexusflow-demo-tools:search_customer` · MCP / NexusFlow Demo Tools / 20 ms |
| "Use MCP to calculate 125 multiplied by 24." | completed · 3000 |
| M3 internal inputs | completed with `internal:customer_lookup`, `internal:calculator`, `internal:system_status` |
| `mcp-demo` stopped | failed `mcp_unavailable` in 0.17 s; server marked unavailable; readiness stayed 200 |
| `mcp-demo` paused (unresponsive) | failed `mcp_timeout` in 5.07 s (bounded by the 5 s request timeout; under the 8 s web proxy limit) |
| Restart | connection test connected; MCP calculation completed again |
| Organization B | empty server list; 404 on A's server for every action; spoofed header 404; MCP request fails `mcp_tool_unavailable` even when the prompt names A's server and organization |

Events for the MCP run carried `tool_key`, `tool_type: mcp`, `server_id`, `server_name` and duration; the internal URL `mcp-demo:8765` appeared nowhere in events. The failed run's `node_failed` payload named the tool and server with `mcp_unavailable`, after events 1–6.

## Browser

Logged in and created a new workspace with no servers. In Add MCP server, only Streamable HTTP is offered, and a metadata URL showed "the host is not on the MCP allowlist". Added the demo server, ran Test Connection (connected, protocol 2026-07-28) and Discover Tools (3 tools with schema summaries and enable toggles). Created and activated an agent and ran both MCP demo inputs. The result and the run detail show Tool type MCP, Server NexusFlow Demo Tools, Tool, Duration and Status, plus the event timeline. With `mcp-demo` stopped, the run showed a safe failure with the failed MCP call. The server page showed `unavailable` with the last error, and Test Connection restored `connected` after restart. Switching workspaces from the server detail page redirected to the other workspace's own list; the first workspace's server URL showed "not found" there, and switching back restored it. At 375 × 812 the MCP list, MCP detail and run detail matched the viewport width, with tables scrolling inside their containers (two CSS overflow bugs found here were fixed). Logout redirected to `/login`, and `/app/mcp` then required sign-in.

Synthetic identities only; credentials are in the ignored `.env.m4-validation` (mode 0600).

## Caveats

- Public MCP mode (`MCP_ALLOW_PUBLIC_HOSTS=true`) validates DNS before connecting but does not pin the connection to the checked address, so DNS rebinding is possible there. It is off by default; pin connections before enabling it.
- MCP calls run synchronously inside the agent run request, like the rest of M3 execution.
- Carried over from M3: a PostgreSQL outage mid-run can leave a run `running`; recovery belongs to the queue/reliability milestone.
- Server status reflects the last observed interaction, not continuous monitoring.
- The `execute_demo_tool` node name dates from M3; it now runs internal and MCP tools.
