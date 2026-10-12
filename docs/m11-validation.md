# M11 validation and final report

Validation date: 2026-10-12. Scope: final hardening and portfolio preparation in `the repository root`; no M12, public deployment or schema migration. Initial writer/repository/Docker/environment/database/navigation inspection completed before edits. Existing Claude session was idle for approximately 37 hours, not an active writer. Existing user workspaces were preserved.

## Release changes

Production settings/host/docs safeguards; full JWT redaction; bounded chunked uploads in API/proxy; deterministic demo seed/evaluate/inspect/reset; standalone production Compose; mobile activity-grid constraint and stale footer correction; README/deployment/portfolio/evidence documents and real screenshots.

## Requested 76-point report

1. **Security review:** Reviewed auth/session cookies, CORS, hosts, docs, uploads, MCP, tenant queries, roles, queue payloads, memory, retrieval, traces and evaluation boundaries. Concrete gaps fixed; this is a release review, not a penetration-test certification.

2. **Production configuration:** Requires generated 48+ byte JWT, 16+ character DB password, explicit HTTPS origins/hosts, Secure cookies, queue mode, Redis/MCP/upload settings and TLS for remote DB/Redis. TrustedHost middleware added; production OpenAPI disabled.

3. **Environment template:** `.env.example` documents APP_ENV (the actual name), optional embedding key, allowed hosts, upload timeout and opt-in demo credentials; no real secret values.

4. **Secret scan:** 368 source/document files scanned for private keys, provider keys and AWS credentials. One clearly synthetic provider-key fixture in tests/test_production.py matched; reviewed as test data. No real credential found. Reviewed credential configuration and exclusions. No Git metadata: committed history cannot be certified.

5. **Health/readiness:** Live liveness/readiness work; readiness reports DB/Redis safely. All six local Compose services healthy.

6. **Worker health:** Kept separate Compose heartbeat check, stale after 90 seconds. API readiness deliberately does not imply worker availability.

7. **Migrations:** Zero M11 schema changes. One release operator runs migrations after backup; API/worker do not race migrations at startup. Head remains 0010_observability_evaluation.

8. **Backup/restore:** Deployment guide includes maintenance-window pg_dump plus upload archive and isolated restore commands. An off-host production restore drill remains an operator release gate.

9. **Persistence:** PostgreSQL data and knowledge uploads are named volumes. Knowledge backup includes originals and demo manifests. Redis is ephemeral delivery; persisted jobs support redelivery.

10. **Docker hardening:** Non-root API/worker UID 10001 and web/MCP runtimes retained. Production application services drop capabilities, deny new privileges, bound JSON logs and restart unless stopped. No source mounts.

11. **Production Compose:** Standalone docker-compose.prod.yml validates. Private DB/Redis/MCP have no published ports; API/web loopback only. Disposable production-settings process validated at UID 10001. Production stack was not started.

12. **Reverse proxy:** Nginx server-block fragments, forwarded headers, 11 MB body cap, TLS issuance/renewal and trusted loopback boundary documented.

13. **VPS/Hostinger:** Prepared for an SSH-managed Linux VPS with Docker/Nginx, not shared PHP hosting. Resource estimate explicitly unbenchmarked. No VPS/DNS/firewall changes performed.

14. **Deployment document:** docs/deployment.md contains configuration, build/migrate/start, health checks, troubleshooting, backup/restore and rollback strategy; official Docker/Certbot installation references.

15. **Demo seed:** Opt-in Python CLI; deterministic UUID5 workspace and reserved slug. Bootstraps identity only, then uses real APIs, ingestion and worker execution. Advisory lock and manifest support recovery.

16. **Demo reset:** Exact UUID confirmation, reserved marker, original sole owner, recorded rows and no active jobs required. Descendants of recorded worker runs are recognized. Unknown user resources/extra memberships are refused. Disposable reset verified; all 18 other organizations preserved.

17. **Demo workspace:** NexusFlow Demo; deterministic workspace UUID recorded by make demo-inspect. Private ignored mode-600 .env.demo holds login credentials; none printed or published.

18. **Demo agents:** Eight named operational agents plus a dedicated evaluation memory-only agent; nine active total. No-tool memory agent is deliberate.

19. **Demo tools:** Explicit internal calculator/customer/knowledge assignments; customer specialist also has discovered MCP search_customer. Team tool access remains per-agent.

20. **Demo MCP:** NexusFlow Demo Tools connected over allowlisted streamable HTTP; three tools discovered. MCP lookup and calculation were exercised.

21. **Demo team:** Enterprise Account Intelligence Team: supervisor, customer specialist, researcher, analyst, writer and validator. Active with six required members.

22. **Demo knowledge:** Enterprise Security Knowledge contains real ingested synthetic PDF, DOCX and Markdown files. Worker-generated chunks and retrieval citations are persisted.

23. **Demo thread/memory:** Acme Opportunity Discussion with pinned owner, region and response-preference facts. Memory-only run recalls Maya Chen and North America without tools.

24. **Demo runs:** Five seeded agent runs and six team runs through normal queue, plus evaluation-owned runs. Completed customer/calculator/MCP/memory/RAG and team analysis; policy-denied failure is intentional.

25. **Demo approvals:** Pending, approved and rejected email examples; allowed CRM note; denied destructive objective. Actions remain simulations. Pending expiry is 24 hours; reset/reseed refreshes presentation state.

26. **Evaluation dataset:** Demo · platform regression: ten cases covering calculator, lookup, MCP, memory, team, approval, denial, adversarial memory, RAG citation and no-match.

27. **Baseline strategy:** Two real evaluation executions: 10/10 each, 100% score/pass rate; first marked baseline. Comparison shows zero regressions/improvements and same config. Retrieval Hit@K=100%, MRR=1.00 on the deterministic fixture.

28. **UX issues/fixes:** Fixed mobile recent-execution grid overflow using minmax(0,1fr); removed stale M1–M6 landing-footer claim. Streamed proxy/API body limits prevent unbounded buffering. No visual redesign.

29. **Navigation:** All twelve destinations loaded from the final navigation. Numbering and cyan active styling preserved; section labels separate. Drawer scrolls to Observe routes, closes on navigation and Escape.

30. **Control Plane:** Compact operational strip shows nine agents, one team, three MCP tools and one pending approval. Recent runs and dependency status are real. Mobile grid overflow fixed and rechecked.

31. **Agents UI:** Identity codes, capabilities, enabled tool grants, detail page and test-console labels inspected. Memory-only/no-tools state remains understandable.

32. **Team UI:** Six-node control rail topology and permissions inspected; execution handoffs/result visible on completed run. Configured topology is explicitly distinguished from actual execution order.

33. **Knowledge UI:** Source/documents loaded; cited SSO/MFA answer links to the PDF, chunk and retrieval scores. Assigned-source behavior covered by API tests.

34. **Memory UI:** Memory and Threads loaded; real recall shows thread context and zero tool calls. Member ownership boundaries retained, including safe edits of their own manual memories.

35. **Trace UI:** Team waterfall shows worker, specialist, MCP and policy spans. Run links, attempt count and queue wait are real; no fabricated token/cost estimates.

36. **Evaluation UI:** Ten passing case rows, baseline marker and linked comparison inspected; no LLM judge or statistical-significance claim.

37. **Screenshot files:** Twelve required portfolio images plus four responsive/drawer images in docs/screenshots. Every final portfolio image was opened and visually inspected; denied-policy screenshot is intentional evidence.

38. **README:** Rewritten with verified feature scope, reproducible local/demo commands, six real screenshots, security, deployment links, validation and explicit limitations.

39. **Architecture diagram:** Mermaid in README connects browser/proxy/API, PostgreSQL, Redis/worker, LangGraph, tools, policy, context and uploads. Architecture guide updated for M11.

40. **Portfolio story:** docs/portfolio-story.md explains inspectable orchestration, governance, tenancy and deterministic-runtime tradeoffs.

41. **Portfolio summary:** docs/portfolio-summary.md provides concise product/stack description with truthful limits.

42. **Captions:** docs/screenshots/README.md lists all twelve required images with concise captions (under 140 characters).

43. **API docs:** Development Swagger/OpenAPI retained; production both disabled. Existing schemas/routes for all M1–M10 features retained. Authentication guide updated for stronger production secret requirement.

44. **Errors/privacy:** Safe error envelope retained; no input/password echo, SQL or stack traces in normal frontend. Unexpected exceptions log type only. JWT trace-redaction regex now masks all three segments, and provider-key masking includes hyphens/underscores; regression cases added.

45. **Tenant isolation:** Live HTTP checks from a separate synthetic workspace returned 404 for foreign agents, teams, MCP, knowledge, threads, agent/team runs, approvals, evaluation datasets/runs, traces and memory. Full isolation/constraint suites green.

46. **Roles:** Owner/admin/member API coverage passed for M1–M10 resources. Live member read_agents=200, create_agent=403, review_approval=403, create_evaluation=403. Temporary membership role restored before guarded reset. Memory intentionally permits members to manage their own manual entries; it does not permit managing others/derived entries.

47. **Upload QA:** Seed ingested valid PDF/DOCX/MD; suite covers text, unsupported types, unsafe names, malformed PDF and oversize. New chunked-body regression returns 413 without persisting a document. API and frontend now bound bytes while streaming.

48. **Worker QA:** Representative live queued/completed/approval workflows plus automated queued/running/completed/retry/failed/cancelled/recovery checks. PostgreSQL is job truth; no queue credentials/raw payloads added.

49. **Approval QA:** Live seed exercised pending/approve/reject/allow/deny; automated role, expiry, concurrency and idempotent-execution coverage passed. No real messages sent.

50. **Memory QA:** Live thread recall/manual pinned facts; automated deactivate/delete, own-member entries, workspace opt-in, budgets, injection boundaries and evaluation isolation passed.

51. **RAG QA:** Live cited SSO/MFA answer and evaluation no-match; automated archive, assignments, ingestion failure, tenant retrieval and prompt-injection cases passed.

52. **Trace QA:** Live agent/team/RAG/denied traces; automated retry/redaction/tenant tests passed. Entire-JWT and provider-key redaction regressions passed.

53. **Evaluation QA:** Two real ten-case runs, memory-only recall, retrieval metrics, baseline and comparison verified. Evaluation fixtures stay within the demo tenant and clean up approval waits.

54. **Responsive QA:** 1440/1024/768/390 inspected. Core Control Plane/team/approval/trace/evaluation screens fit; RAG also checked at all four widths. Mobile activity overflow found and fixed. Drawer keyboard/navigation closure verified. Dense tables use bounded local scrolling.

55. **Accessibility QA:** Inspected labels/headings/status text; keyboard focus reaches links, Escape closes drawer. Existing focus-visible/reduced-motion CSS retained. This was a focused manual pass, not a certified accessibility audit.

56. **Performance QA:** Reviewed bounded active-run polling with unmount/workspace cleanup, bounded summaries/context, capped lists and production build. No evidence justified architectural optimization; no load-capacity benchmark is claimed.

57. **PostgreSQL tests:** 487 passed in 211.96 seconds in the final full run; subsequent final provider-key masking change passed 35 focused privacy/observability tests on PostgreSQL and 35 on SQLite.

58. **SQLite tests:** 482 passed, five PostgreSQL-specific skips, 95.77 seconds (final full run including demo guard tests); subsequent provider-key masking change passed 35 focused privacy/observability tests on SQLite.

59. **Worker tests:** 32 passed, one PostgreSQL-specific skip in standalone SQLite worker run; full PostgreSQL suite includes that check.

60. **MCP tests:** 15 passed; Ruff check/format clean.

61. **Frontend tests:** 49 passed, zero failures.

62. **Ruff:** API check and format: clean (173 files); MCP check and format: clean (four files).

63. **ESLint:** Passed after final frontend fixes.

64. **TypeScript:** tsc --noEmit passed after final frontend fixes.

65. **Production build:** Next.js production build passed after final frontend fixes; no material warning.

66. **Docker:** All local images built; all six services healthy after up --no-recreate --wait. Production Compose config and disposable settings process passed; no production deployment.

67. **Alembic:** current: 0010_observability_evaluation (head); check: no new upgrade operations. PostgreSQL migration round-trip coverage passed in full suite.

68. **Production checklist:** docs/production-checklist.md prepared. Operator gates for actual DNS/TLS/deployment, off-host backups and restore drill remain unchecked by design.

69. **Ignore audit:** Credentials/env variants, caches, uploads, logs, dumps, backups and private keys excluded. Desired portfolio images are not gitignored; screenshots excluded from Docker build context.

70. **License:** No project-level license found. Owner must choose before public distribution; dependency licenses retained. No license was invented.

71. **Caveats:** Deterministic text and hash embeddings; simulated actions; single-VPS target, unmeasured capacity; no live LLM/email/CRM, external tracing export, password recovery or public playground. No Git history or production restore/deployment certification.

72. **Local commands:** `cp .env.example .env` → fill secrets → `make up` → `make migrate`; web localhost:3000, default API localhost:8000 (current validation 8002). See README for overrides.

73. **Demo seed commands:** Create private .env.demo, then `set -a; . ./.env.demo; set +a`, `make demo-seed`, `make demo-evaluate`, `make demo-inspect`. No credentials in commands/source.

74. **Demo reset commands:** With exported demo email: `make demo-inspect`, then `make demo-reset CONFIRM=<exact-demo-uuid>`. Refuses unknown normal data. User account retained.

75. **Production commands:** Exact config/build/migrate/start/health/backup/restore commands are in docs/deployment.md using `--env-file .env.production -f docker-compose.prod.yml`. Prepared only; deployment requires operator approval.

76. **Test commands:** `make api-test api-test-postgres worker-test mcp-test api-lint mcp-lint web-test web-lint web-typecheck web-build`; migration checks via `docker compose exec -T api alembic current` and `alembic check`.

## Changed files

- API: `app/core/config.py`, `app/main.py`, `app/api/v1/knowledge.py`, `app/observability/redact.py`, new `app/demo/__init__.py` and `app/demo/seed.py` (under apps/api).
- API checks: `tests/test_foundation.py`, `tests/test_knowledge.py`, new `tests/test_production.py` and `tests/test_demo_seed.py` (under apps/api).
- Frontend: `apps/web/src/app/api/backend/[...path]/route.ts`, `apps/web/src/app/globals.css`, `apps/web/src/app/page.tsx`.
- Operations: `.env.example`, `.gitignore`, `.dockerignore`, `Makefile`, `docker-compose.yml`, new `docker-compose.prod.yml`, `infra/docker/api.Dockerfile`.
- Documentation: `README.md`, `docs/architecture.md`, `docs/authentication.md`; new deployment, demo-environment, production-checklist, tech-stack, portfolio-story, portfolio-summary and m11-validation guides; screenshots and caption index under docs/screenshots.
- Ignored local env variants hold validation/demo credentials. They are excluded from source/build contexts and are not portfolio artifacts.

## Execution notes

Initial sandboxed API tests could not bind local MCP sockets; re-run with local socket access passed. The initial PostgreSQL run overlapped a database image rebuild and had connection errors; the stable-stack rerun passed. These attempts are not counted as passing runs. Demo client integration mismatches (Origin, run_id, passed_count and asynchronously appended worker descendants) were corrected before the final successful seed/evaluation/idempotence/reset checks.

Production runtime, DNS, TLS, firewall, public account access and live recovery were not performed. Installation references in deployment.md were checked against official Docker and Certbot documentation.

M11 STATUS: COMPLETE
