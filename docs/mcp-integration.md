# MCP integration (M4)

M4 connects the M3 agent runtime to real Model Context Protocol servers. Organizations register MCP servers, NexusFlow discovers their tools over the protocol, and agent runs can call those tools through the same execution contract as internal tools. **MCP resources, MCP prompts, authenticated or OAuth MCP servers, third-party servers, stdio/SSE transports and per-agent tool allowlists are not implemented.**

## SDK

The official MCP Python SDK, **`mcp==2.3.0`** (v2 line), with `mcp-types==2.3.0`. NexusFlow uses only v2 APIs, checked against the installed source:

| Side | API |
| --- | --- |
| Server | `mcp.server.MCPServer`, `@server.tool()` with Pydantic return models (structured output), `ToolError`, `custom_route`, `streamable_http_app(json_response=True, stateless_http=True, transport_security=...)` |
| Client | `mcp.client.Client(transport, read_timeout_seconds=..., cache=None, client_info=...)`, `mcp.client.streamable_http.streamable_http_client(url, http_client=httpx2.AsyncClient)`, `list_tools(cursor=...)`, `call_tool()` → `CallToolResult.structured_content` / `is_error` |
| Errors | `mcp.shared.exceptions.MCPError` (v1's `McpError`), code `-32001` for request timeouts |

Deprecated or removed v1 APIs (`FastMCP`, `streamablehttp_client`, camelCase result fields, `ping` under protocol `2026-07-28`) are not used; the suites run with `-W error`. The client negotiates protocol version `2026-07-28` with the demo server.

### Dependency changes

The API lock (`apps/api/requirements.lock`) gained ten packages and changed no existing versions: `mcp`, `mcp-types`, `jsonschema` (also a direct dependency, for argument/result validation), `jsonschema-specifications`, `referencing`, `rpds-py`, `attrs`, `cryptography` (via PyJWT's crypto extra required by the SDK), `python-multipart` and `sse-starlette`. `pip check` reports no conflicts. `apps/mcp-demo/requirements.lock` resolves to the same versions as the API.

## Transport

Streamable HTTP only, in stateless JSON-response mode. Each NexusFlow operation opens a session, performs one request (or list then call), and closes it. This gives a real network boundary between containers and matches how remote MCP servers are reached. `McpTransport` contains only `streamable_http`; other transports would need a client implementation before they could be added to the enum.

## Demo MCP server

`apps/mcp-demo` is a separate Python service and container (`mcp-demo`), built only on the SDK.

| Tool | Input | Output |
| --- | --- | --- |
| `search_customer` | `{"company": str}` (1–200 chars) | `found`, `company`, `segment`, `status`, `account_owner`, `region`, `available`, `source: "NexusFlow demo MCP data"` |
| `calculate` | `{"operation": add\|subtract\|multiply\|divide, "a": number, "b": number}` (±10¹²) | `operation`, `a`, `b`, `result` as exact decimal strings; division by zero is a `ToolError` |
| `get_platform_info` | `{}` | `service`, `status`, `protocol`, `transport`, `version`, `tools`, `data_notice` |

The customer records are identical to the M3 internal dataset; `test_internal_and_mcp_demo_datasets_stay_aligned` fails if they drift. The server exposes no filesystem, shell, HTTP proxy, environment or database capability, and `get_platform_info` reports only static service facts. DNS-rebinding protection is on: only `Host` headers in `MCP_DEMO_ALLOWED_HOSTS` are accepted (421 otherwise). `/healthz` backs the container health check.

In Compose the API reaches it at `http://mcp-demo:8765/mcp` on the internal network. Port 8765 is also published on `127.0.0.1` only, for local debugging.

## NexusFlow architecture

```text
LangGraph node (create_plan / execute_demo_tool)
  │  tools.resolve(source, name) / tools.execute(tool_key, args, context)
ToolResolver ── internal:<tool> ──► ToolRegistry (M3 internal tools)
  │
  └─ mcp:<server-slug>:<tool> ──► McpToolProvider (one per run, bound to the run's organization)
                                     │  DB: server/tool enabled + listed, argument schema
                                     ▼
                                  McpClient ── URL policy ── httpx2 (bounded) ── Streamable HTTP ──► MCP server
```

| Module | Responsibility |
| --- | --- |
| `app/mcp/urls.py` | SSRF policy (`validate_server_url`) |
| `app/mcp/client.py` | The only code that speaks MCP: sessions, timeouts, error classification |
| `app/mcp/schemas.py` | Validation of untrusted tool metadata and arguments (JSON Schema 2020-12) |
| `app/mcp/discovery.py` | Reconcile `tools/list` with stored metadata |
| `app/mcp/registry.py` | Tenant-scoped tool queries, tool keys, connectivity bookkeeping |
| `app/mcp/adapter.py` | `McpToolProvider`: the runtime-facing adapter |
| `app/agents/tools/resolver.py` | `ToolResolver`: routes keys to internal tools or providers |
| `app/services/mcp_servers.py`, `app/api/v1/mcp_servers.py` | Registry service and thin routes |

Neither routes nor graph nodes contain MCP calls. `McpClient` is synchronous and runs each operation on its own event loop (`anyio.run`), so the synchronous runtime and FastAPI handlers stay unchanged and a future worker can use it as is.

## Data model (migration `0004_mcp_registry`)

- **`mcp_servers`**: organization-owned; `slug` unique per organization; `transport`, `url`, `status` (`pending`/`connected`/`unavailable`/`disabled`), `is_enabled`, `last_connected_at`, `last_discovered_at`, `last_error_code`, `last_error_message`. `status` records the last observed connectivity and is never used for authorization.
- **`mcp_tools`**: `name`, `description`, `input_schema` and `output_schema` (JSONB), `is_enabled`, `is_available`, `discovered_at`. `(mcp_server_id, name)` is unique, and the composite foreign key `(mcp_server_id, organization_id) → mcp_servers(id, organization_id)` makes it impossible to attach a tool to another organization's server.

## Discovery lifecycle

`POST /mcp-servers/{id}/discover` calls `tools/list` (following pagination, up to 10 pages) and then reconciles:

- Tools with invalid names, invalid or oversized schemas (over 32 KiB) or duplicates are dropped; descriptions are normalized and truncated.
- New tools are stored **enabled and available**.
- Known tools get their description and schemas refreshed and are marked available. An operator's `is_enabled` choice is preserved.
- Tools the server no longer lists are **kept but marked `is_available = false`**, for audit and comparison, and cannot execute. They become available again if a later discovery lists them.
- Changing a server's URL marks all its tools unavailable until the next discovery.

The response reports `added`, `updated` and `removed` names. Stored metadata is only a gate: every tool call lists tools on the live server first and fails with `mcp_tool_not_found` if the tool is gone.

## Tool namespace

Stable keys: `internal:<tool>` for internal tools and `mcp:<server-slug>:<tool>` for MCP tools (e.g. `mcp:nexusflow-demo-tools:search_customer`). Slugs are unique per organization and do not change when a server is renamed. Keys appear in plans, `tools_used`, run events and API responses. They are resolved only inside the run's organization, so a key copied from another tenant resolves to nothing.

## LangGraph integration

The M3 graph is unchanged structurally. `analyze_request` sets `tool_source = "mcp"` when the input mentions "MCP" (word match); `create_plan` maps `(source, intent)` deterministically:

| Intent | Internal tool | MCP tool |
| --- | --- | --- |
| customer_lookup | `customer_lookup` | `search_customer` (`{"company": ...}`) |
| calculation | `calculator` | `calculate` (`{"operation", "a", "b"}`) |
| system_status | `system_status` | `get_platform_info` |

The resolver picks the oldest enabled server in the run's organization that offers an enabled, available tool with that name. If none exists, the run fails at `create_plan` with `mcp_tool_unavailable`. There is no autonomous tool selection. Input text can mention server names or IDs, but those never select a server.

## Execution and tenant boundaries

`McpToolProvider` is created per run with the organization from the server-built `ToolExecutionContext` (organization, user, run). Before each call it:

1. rejects a context from a different organization (`tool_context_mismatch`);
2. loads the server and tool by key inside that organization only;
3. requires the server enabled (`mcp_server_disabled`), the tool available (`mcp_tool_not_found`) and enabled (`mcp_tool_disabled`);
4. validates arguments against the stored input schema (`invalid_tool_arguments`, naming fields but never values);
5. calls the live server via `McpClient` and validates `structured_content` against the stored output schema (`mcp_malformed_result`).

Tenant identifiers are not forwarded to MCP servers. Owners and admins create, edit, test and discover servers and toggle tools; members can view the registry and run agents that use enabled tools. Every endpoint resolves servers with `organization_id` in the query, so another tenant's server UUID returns 404.

## URL and SSRF safeguards

Server URLs are tenant input, so `validate_server_url` runs at registration, on URL changes, and again before every connection:

1. Only `http`/`https`. Credentials, query strings, fragments, whitespace and control characters, malformed ports and URLs over 2048 characters are rejected. `file://`, `gopher://`, `unix`, `ws` and other schemes are rejected.
2. A `host:port` listed in `MCP_ALLOWED_HOSTS` is accepted. **This is the only way to reach private addresses.** Compose sets it to `["mcp-demo:8765"]`; tests allowlist their own loopback ports the same way. Without an allowlist entry, `localhost`, `127.0.0.1`, `::1`, `169.254.169.254`, RFC 1918, CGNAT and other non-public addresses are refused.
3. Other hosts require `MCP_ALLOW_PUBLIC_HOSTS=true` (default `false`), HTTPS, a non-internal name (`localhost`, `*.local`, `*.internal`, single-label names refused), and DNS answers that are **all** globally routable (IPv4-mapped IPv6 is unwrapped).

The HTTP client ignores proxy environment variables (`trust_env=False`), and the SDK only follows redirects that stay on the same origin. Known limitation: DNS for public hosts is checked before connecting but the connection is not pinned to the checked address, so DNS rebinding remains possible in public mode. Public mode is off by default and should stay off until connections are pinned.

## Failures and timeouts

| Failure | Code | Server status |
| --- | --- | --- |
| Connection refused, DNS failure | `mcp_unavailable` | `unavailable` |
| Connect/read/overall deadline | `mcp_timeout` | `unavailable` |
| JSON-RPC or HTTP protocol error, bad framing | `mcp_protocol_error` | `unavailable` |
| URL no longer permitted | `mcp_url_rejected` | `unavailable` |
| Tool missing from live listing | `mcp_tool_not_found` | `connected` |
| Tool `is_error` result | `mcp_tool_error` ("MCP tool error: …", first 200 characters, single line) | `connected` |
| Non-object, empty or >64 KiB result, or output-schema mismatch | `mcp_malformed_result` | `connected` |
| Disabled server / tool, no tool configured | `mcp_server_disabled` / `mcp_tool_disabled` / `mcp_tool_unavailable` | unchanged |

`MCP_CONNECT_TIMEOUT_SECONDS` (default 2) and `MCP_REQUEST_TIMEOUT_SECONDS` (default 5) bound the httpx2 client and the SDK's read timeout, and their sum is a hard deadline for each operation (`anyio.fail_after`). That stays below the web proxy's 8-second timeout. There are no automatic retries. SDK exceptions arrive as nested `ExceptionGroup`s and are flattened and classified; their text never leaves the client. A failed MCP call fails the run through the normal M3 path: `node_failed` and `run_failed` events, `error_code`/`error_message` on the run, and the snapshot error with safe `details`. Earlier events are preserved.

The connection test returns `{"status": "unavailable", "error": {...}}` (HTTP 200) on failure; discovery returns HTTP 502 with the safe code. Both persist `status`, `last_error_code` and `last_error_message`. Successful calls set `connected` and `last_connected_at`.

## Health

MCP servers are optional integrations. `/health/ready` still checks only PostgreSQL and Redis and does not change when `mcp-demo` is down. MCP health is tracked per server through `status` and `last_*` fields, updated by connection tests, discovery and runtime calls. The API container does not depend on `mcp-demo` in Compose.

## Events

No new event types. The existing node events carry MCP metadata:

- `create_plan` → `node_completed.output_payload.plan[].tool_key` and mapped arguments;
- `execute_demo_tool` → `node_completed.output_payload.tool_results[]` with `tool_key`, `tool_type: "mcp"`, `output`, and `metadata` (`server_id`, `server_name`, `duration_ms`);
- failures → `node_failed.output_payload` with `error_code`, `tool_type`, `tool_key`, `tool_name`, `server_id`, `server_name`.

Server URLs, headers, cookies, credentials and raw exceptions are never written to events or snapshots. Run responses add `tool_calls` (type, server, tool, duration, status) for display.

## Future work (not implemented)

Remote authenticated MCP servers and OAuth (the SDK's `httpx2.Auth` providers fit into `McpClient`), third-party server onboarding with connection pinning, stdio/SSE transports, MCP resources and prompts, per-agent tool allowlists and per-user permissions, agent action retry policies (planned for the reliability milestone), and background execution.
