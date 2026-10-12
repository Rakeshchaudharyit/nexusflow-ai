# M1 validation

Validated locally on 7 October 2026.

| Check | Result |
| --- | --- |
| `make api-install` | Passed with pinned runtime requirements |
| `ruff check` | Passed |
| `ruff format --check` | 17 Python files formatted |
| `pytest` | 17 passed, no warnings |
| `npm ci` | Passed from lockfile |
| `npm run lint` | Passed, no warnings |
| `npm run build` | Passed, Next.js 16.4.0 / Webpack |
| `npm run typecheck` | Passed, strict TypeScript |
| `docker compose config --quiet` | Passed |
| `docker compose up --build -d --wait` | All four services healthy |
| Alembic upgrade / current / check | `0001_foundation` at head; no pending changes |
| PostgreSQL | Real `SELECT 1` passed; only `alembic_version` in public schema |
| Redis | Real `PING` returned `PONG` |
| Liveness | HTTP 200 with service/version |
| Readiness | HTTP 200; API/PostgreSQL/Redis all `ok` |
| Redis outage | Readiness HTTP 503, Redis `unavailable`, liveness remained HTTP 200 |
| Browser status | Live connected statuses; Redis outage displayed independently |
| Mobile layout | 390 × 844 viewport verified; no horizontal overflow; cards and footer inspected |
| Recovery | Manual refresh restored all Connected statuses after services restarted |
| API outage | Frontend exited loading, displayed API Unavailable and dependency Unknown; refresh available |

## Local runtime decisions

An existing unrelated Python process owns port 8000. The generated, ignored local `.env` uses `API_PORT=8002` and `NEXT_PUBLIC_API_URL=http://localhost:8002/api/v1`. Compose's default remains 8000. The frontend is available at `http://localhost:3000`.

A random PostgreSQL password was generated in the ignored `.env`, with file mode 0600. No secret is included in source or container build context. A fresh checkout requires copying `.env.example` and setting a password.

Turbopack's CSS subprocess could not bind a port in this execution environment. Production builds use Next.js's supported Webpack option, and passed both locally and inside Docker. No type or lint checks were disabled.

## Upstream tooling limitation

`npm audit --omit=dev` reports zero production vulnerabilities. Full audit reports five high-severity entries from one `braces` vulnerability propagated through Next.js's ESLint plugin dependency chain. The [upstream advisory](https://github.com/advisories/GHSA-vfj7-8cjw-p6xm) lists no patched version. The issue involves malicious deeply nested glob patterns; this project's lint configuration uses fixed local patterns and does not process user-supplied glob input.

ESLint 9 is retained because the React/import/accessibility plugins bundled with the current Next.js configuration do not all declare ESLint 10 support. There are no peer-dependency overrides, advisory suppressions, or forced framework downgrades. Revisit these development dependencies when compatible upstream fixes are published. They are excluded from the standalone web runtime image.
