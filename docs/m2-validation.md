# M2 validation — 2026-10-07

M2 is complete. M3 has not started. M1's historical checks remain in [validation](validation.md).

| Check | Executed result |
| --- | --- |
| PostgreSQL backend suite | 67 passed, no warnings |
| SQLite fallback suite | 65 passed, 2 skipped (PostgreSQL concurrency and migrations) |
| Frontend auth client tests | 6 passed |
| Tenant isolation | Both directions deny foreign organization access; lists and header context scoped to membership |
| Role foundation | Owner/admin/member, forbidden member checks, live role changes and removed membership verified |
| Refresh | Rotation, original absolute expiry, expiry/revocation, replay-family invalidation, independent login families, simultaneous PostgreSQL refresh verified |
| Migration round trip | Upgrade → downgrade to M1 → upgrade in isolated PostgreSQL schema passed |
| Ruff | Check and format passed; 30 Python files |
| ESLint | Passed |
| TypeScript | Strict typecheck passed |
| Production build | Local and Docker Next.js Webpack builds passed |
| Docker Compose | Config valid; all four rebuilt services healthy |
| Alembic | 0002_identity at head; no pending model changes |
| Live API | Register/login/me, organization creation/list/context, bidirectional isolation, refresh/replay/logout passed |
| Redis outage | Login/me/refresh/logout passed with Redis stopped; liveness 200 and readiness 503 |
| Recovery | All four services healthy; readiness returned 200 |
| Browser | Register, automatic login, second workspace creation, switching, reload session restoration, wrong-password error, logout and protected-route redirect, login passed |
| Responsive layout | Login/register/app inspected at 390 × 844; document width equals viewport, no horizontal overflow |

Browser verification used synthetic test identities on the local application. Test credentials are ignored, outside source/build context. The workspace screenshot is [workspace-preview.jpg](workspace-preview.jpg).

## Runtime

Frontend: http://localhost:3000. API: http://localhost:8002/api/v1. The unrelated process on port 8000 was preserved. PostgreSQL data persists. No database reset was used; only test-created isolated schemas were removed.

Run make up followed by make migrate. Use make api-test-postgres, make api-test, make web-test, make api-lint, make web-lint, make web-typecheck, and make web-build for reproduction.

## Security limits

Refresh replay fails closed, including duplicate concurrent refresh. Web Locks coordinate supported browser tabs; unsupported browsers can require signing in again after a cross-tab race. Secure cookies and HTTPS are mandatory in production. Rate limiting, MFA, email verification flows, password reset, invitations, and cleanup scheduling are outside this milestone; configure rate limiting before public exposure.

The M1 development-only lint dependency advisory remains: five high-severity audit entries in the braces/Next ESLint chain, with no compatible upstream fix used. Production npm audit reported zero. See [historical tooling details](validation.md#upstream-tooling-limitation). No audit suppressions or unsafe overrides were added.

There are no remaining M2 implementation blockers.
