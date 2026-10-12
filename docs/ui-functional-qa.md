# UI functional QA — M1 to M6

Browser QA run on 2026-10-08, before the visual redesign.
- **Scope:** functional fixes only. No visual identity, palette, typography or layout-system changes. M7 was not started.
- **Environment:** the Docker Compose stack (web, api, postgres, redis, mcp-demo), driven through the built-in browser at `http://localhost:3000`. The API is published on `http://localhost:8002/api/v1`.
- **Test data:** synthetic users `qa.{owner,admin,member}.ec8082@example.com` (credentials in the ignored file `.env.qa-validation`, mode 0600), plus workspaces "QA Org A" and "QA Org B".
- **Member and admin roles:** there is no invitation feature in M1–M6, so these memberships in QA Org A were added with a direct database insert.

## Browser flows tested

| Area | Flows |
| --- | --- |
| Authentication | Register (new user and workspace); duplicate registration with different email case; login; wrong password; malformed email; logout from nested pages; session restore on hard refresh; a protected route while signed out; deep link → login → original page; `/login` while signed in; `?next=` open-redirect attempt; browser Back after logout |
| Workspaces | Create a workspace from a nested page; switch workspaces from detail pages; refresh after switching; Back/Forward after switching; direct URLs after switching; every list (agents, runs, teams, team runs, approvals, MCP servers) refetches for the new workspace |
| Roles | Owner, admin and member: UI controls on every page, plus an API matrix covering create/update agent, assign tool, create team, run agent/team, MCP test/create, view, approve and reject |
| Agents | List; create (double-click submit); detail; edit details; activate; assign an internal and an MCP tool (double-click); remove an assignment; run; run detail; another workspace's agent URL |
| Single agent | The four M3/M4 inputs; run detail timeline; no approval or policy UI |
| MCP | Add a server (blocked metadata URL, then the allowlisted demo URL); test connection; discover; tool schemas; disable/enable a tool (persists after reload); server detail; another workspace's URL; `mcp-demo` stopped (connection test and MCP run), then restarted (recovery) |
| Teams | Create a team with six roles; activate; detail; run; run detail (handoffs, timeline, final result, validator) |
| Multi-agent | The default objective with internal tools, then with the Customer Specialist on `mcp:nexusflow-demo-tools:search_customer` |
| Approvals | Approve (double-click), reject with a comment, ALLOW, DENY, decision from a stale second tab, member view, other-workspace URL, switching back |
| Errors | API stopped (full page load, and an action on an already-loaded page); invalid UUIDs; unknown `/app/*` path; forbidden create forms; already-decided approval |
| Responsive | 1440, 1024, 768 and 390 px: page overflow measured on overview, agent, run, team, team run, approval, MCP and auth pages; table scrolling; payload wrapping; mobile navigation and approval controls |
| Accessibility | Labels, keyboard focus order and visible focus on the approval review form, genuinely disabled buttons, error message wording |

## Issues found and fixed

| # | Issue | Fix |
| --- | --- | --- |
| 1 | A signed-out deep link (for example `/app/agents/new`) went to `/login`, and after sign-in the user landed on `/app`, losing the page. | `src/proxy.ts` forwards the requested `/app` path. The layout redirects to `/login?next=…`. The auth form returns there after sign-in. A mid-session expiry keeps the user's place the same way. `lib/return-path.ts` accepts only same-origin `/app` paths (open redirects are blocked). |
| 2 | A signed-in user opening `/login` or `/register` saw the sign-in form. | Both pages now redirect a valid session to the workspace, honouring a safe `next`. |
| 3 | An unknown URL showed Next's bare 404 with no way back. | Root `not-found` page with a "Go to workspace" link. |
| 4 | Agents could not be edited in the UI, although the API supports it. | An "Edit details" form (name, description, instructions) for owners and admins. |
| 5 | Agent status-change errors appeared in the Test console, away from the buttons. | Shown under the management controls. |
| 6 | Members could open working create forms for agents, teams and MCP servers by direct URL; submitting returned 403. | Members see "Not available for your role" with a link back. The API remains authoritative. |
| 7 | Detail pages titled any load failure "X not found" with no retry. A failed refresh after an action (for example, approving while the API was down) replaced the whole page. | "Not found" appears only for a real 404; other failures say "Could not load this …" and offer Retry. `useResource` keeps already-loaded data when a refresh fails, so the action's error appears beside intact controls. |
| 8 | Retry on the "Workspace unavailable" screen always went to `/app`. | It returns to the requested page. |
| 9 | The Runs, Team runs and Approvals empty states had no next action. | Each links to where runs and approvals originate. |
| 10 | The six "Required" checkboxes on the team form were indistinguishable to assistive technology. | Each is labelled by role, for example "Supervisor required". |
| 11 | The approval inbox intro text touched the filter labels. | Spacing added above the filters. |

One regression of my own was caught and fixed during QA: an explicit logout from a nested page briefly kept `?next=`.

## Results

| Area | Result |
| --- | --- |
| Authentication | Pass. No redirect loops, no infinite loading, no stale authenticated state after logout or Back. The wrong password shows a generic message. A duplicate email returns 409 "An account with this email already exists." (case-insensitive). |
| Workspaces | Pass. Switching from a detail page returns to that section's list. Data refetches; the selection persists across refreshes; Back/Forward show the current workspace's state. |
| Roles | Pass. Members can view and run, but get 403 for create, update, tool assignment, team creation, MCP test/create, approve and reject; the UI shows no management controls. Admins can do all management actions. |
| Agents | Pass. The double-clicked Create made one agent; the double-clicked Assign made one assignment; edit and status changes work. |
| Single agent | Pass. Customer lookup (Acme, owner Maya Chen); 3000; "API ok, PostgreSQL ok, Redis ok"; 3000 via MCP `calculate`. Each run has 10 events and no approval, policy or action UI. |
| MCP | Pass. The blocked URL is rejected with an allowlist message. Connect and discover found 3 tools; the enable toggle persists. With mcp-demo stopped, the run fails with "The MCP server could not be reached." and the server shows `unavailable` with the error code (no traceback, no spinner). After restart, status is `connected` and the error clears. |
| Teams / multi-agent | Pass. Customer Specialist → Researcher → Analyst → Writer → Validator; score 92; validator approved (confidence 0.95); handoffs and a 13-event timeline. No business action is proposed for the default objective. The MCP variant gives the same result, with `search_customer` via NexusFlow Demo Tools shown. |
| Approval | Pass. The run is `awaiting_approval`, listed in the inbox. The double-clicked Approve sent one POST and created one execution; the UI says no real email was sent. |
| Rejection | Pass. The comment is recorded, there are 0 executions, and the run completed with the action rejected. A stale tab's Approve shows "This approval has already been decided." and refreshes. |
| ALLOW | Pass. "Allowed automatically · m6.create_crm_note", the simulated CRM note was created, and there is no approval link. |
| DENY | Pass. "Denied · m6.delete_record", the run failed with `policy_denied`, and there was no approval or execution. |
| Member restriction | Pass. No Approve/Reject controls in the UI; direct API approve and reject both return 403. |
| Cross-tenant | Pass. In QA Org B, the Org A agent, run, MCP server, team, team run and approval URLs all show "not found in QA Org B", and every list is empty. After switching back, the pending approval is listed again. |
| Desktop (1440) | Pass |
| Tablet (1024, 768) | Pass. No page-wide overflow. |
| Mobile (390) | Pass. No page-wide overflow; navigation wraps; wide tables scroll inside their containers; the payload wraps; Approve/Reject stay reachable. |
| Console | Only expected resource errors: 401 (refresh probes while signed out), 404 (missing resources), 409 (duplicate registration), 422 (blocked MCP URL) and 502 (during the deliberate API stop). No uncaught errors, React warnings or hydration warnings. |
| Network | No polling or request loops. A page load makes one refresh, one organization lookup and the page's own requests. Double-clicks never produced duplicate writes. Tenant responses always matched the selected workspace (headers were not inspected directly; the API rejects a missing or foreign `X-Organization-ID`). Link prefetches do not trigger extra API session checks. |
| Tenant isolation | Pass (browser and API) |
| Data integrity | 0 duplicate executions, approvals, team members/roles or tool assignments; 0 executions for non-approved approvals; 0 cross-tenant links; 0 stuck runs; 0 case-duplicate users. |

## Remaining issues (not fixed in this pass)

- **Team membership is fixed after creation.** The UI cannot add, remove or replace a team member; the API has member endpoints. This is a feature gap, left for a later milestone.
- **Membership management is out of scope.** There is no invitation or role management in M1–M6; QA roles were assigned in the database.
- **Stale milestone labels.** The overview eyebrow reads "AGENT RUNTIME / M3" and the landing header "M2 / IDENTITY". These are cosmetic and left for the redesign.
- **Internal tool duration.** Internal tool calls show "—" for duration (MCP calls show timings).
- **Stale login error.** The previous error message stays visible when native validation blocks the next submission.
- **Other-workspace deep links.** A link to another workspace's resource shows "not found" rather than switching workspace. This is intentional (no automatic cross-tenant switching).
- **Token expiry not waited out.** Refresh was exercised by every page load and is covered by the auth-client unit tests.
- **Local tooling.** `npm test` uses a test glob that needs Node 21+. The project's runtime is Node 22 (Dockerfile), and the suite passes there; this machine's default Node via nvm is 20.20.2, and Homebrew's Node is broken (missing `libsimdutf`).
- **Leftover approvals.** Pending approvals remain as test data: QA Org A `53b2c595…` and M4 UI Workspace `b6253291…`.

## Regression after fixes

| Check | Result |
| --- | --- |
| `make api-test-postgres` | 337 passed |
| `make api-test` (SQLite) | 334 passed, 3 skipped (PostgreSQL-only) |
| `make mcp-test` | 15 passed |
| `make web-test` | 30 passed (Node 22 in `node:22-alpine`; also 30/30 on Node 20 with an expanded glob) |
| `make api-lint` | Ruff: all checks passed; 108 files formatted |
| `make mcp-lint` | All checks passed; 4 files formatted |
| `make web-lint` | Clean |
| `make web-typecheck` | Clean |
| `make web-build` | Success (Proxy and `/_not-found` built) |
| `docker compose config -q` | Valid |
| `docker compose exec api alembic current` | `0006_human_approval_policy (head)` |
| `docker compose exec api alembic check` | No new upgrade operations detected |
| Docker | web, api, postgres, redis, mcp-demo all healthy |
