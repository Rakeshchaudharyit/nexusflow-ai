# M2 authentication and multi-tenancy

Registration atomically creates a normalized-email user, organization, and owner membership. Passwords require 12–128 characters and use Argon2id. Login uses a dummy hash for unknown accounts and rehashes outdated hashes. Responses exclude password hashes and refresh tokens.

## API

All paths are under /api/v1.

| Method | Path | Behavior |
| --- | --- | --- |
| POST | /auth/register | Create user and initial organization; 201 |
| POST | /auth/login | Authenticate and establish session |
| POST | /auth/refresh | Rotate refresh cookie and issue access JWT |
| POST | /auth/logout | Revoke session family and expire cookie; idempotent 204 |
| GET | /auth/me | Bearer-authenticated user and memberships |
| GET | /auth/session | Nonrotating cookie session read for server protection |
| GET | /organizations | List current memberships |
| POST | /organizations | Create organization and owner membership |
| GET | /organizations/current | Verify X-Organization-ID context |
| GET | /organizations/{id} | Return organization only with membership |

Auth POST requests require an exact allowed Origin, including registration and login. CLI callers must also send the configured frontend Origin. CORS accepts explicit origins with credentials. Errors return sanitized error.code and error.message; validation never echoes passwords.

## Tokens and cookies

Access JWTs use pinned HS256 with a required random secret of at least 32 bytes in development; production requires a generated secret of at least 48 bytes with character diversity. Signature, issuer, audience, expiration, issued-at, subject, session family, and token type are validated. Default lifetime is 15 minutes. Each protected request verifies the active user and session family in PostgreSQL, so logout or replay immediately invalidates that family's access JWTs. JWTs contain no organization permissions.

Refresh tokens are random 256-bit opaque values; only SHA-256 hashes are stored. Rotation revokes the old row and inserts a new row in the same family, preserving its original absolute expiry (default 30 days). User row locks serialize refresh/logout operations. Reuse of a revoked token revokes the entire family. Independent login families remain active. Concurrent duplicate refresh deliberately fails closed.

The refresh cookie is host-only, HttpOnly, SameSite=Lax by default, and uses path / so Next.js can protect /app. Production requires Secure and HTTPS; SameSite=None also requires Secure. Logout expires the same cookie. Auth responses use Cache-Control: no-store.

## Frontend and protection

The central typed auth client calls the allowlisted same-origin Next.js /api/backend/* proxy. The proxy forwards to server-only API_INTERNAL_URL and relays Set-Cookie. Access JWTs remain in module memory. Passwords, access tokens, and refresh tokens never enter localStorage. Only the selected organization UUID is persisted, scoped to user ID.

The /app server layout checks /auth/session before rendering and redirects unauthenticated visitors to /login. This read does not rotate cookies. The client provider bootstraps through refresh and gates content; service failures have a retry state. Login and registration redirect to /app. Logout clears identity.

Refresh uses a shared in-flight promise, one retry after 401, and Web Locks where available to serialize tabs. BroadcastChannel announces session changes without credentials. A 403 never triggers refresh. Browsers without Web Locks have per-tab coordination; simultaneous refresh in multiple tabs may require signing in again because replay protection fails closed.

## Tenant and roles

An organization UUID is context, never authorization. Every organization query verifies current membership. Foreign or missing organizations return 404 without exposing data. Header context validates UUID syntax and membership. Owner, admin, and member roles are database-controlled; reusable role dependencies read current roles rather than JWT claims. M2 has no role assignment, invitations, or ownership transfer endpoints.

Future agents, runs, tools, and MCP resources must carry organization foreign keys and use this verified tenant context for every query. These resources are outside M2.

## Operations and limitations

Use a generated JWT secret, explicit HTTPS origins, production mode, and Secure cookies before deployment. Configure edge body limits and login rate limiting before public exposure. Email verification flows, password reset, invitations, MFA, and session cleanup scheduling are not implemented. The verification flag is schema groundwork.

Redis is a readiness dependency; authentication and refresh depend only on PostgreSQL. Revision 0002_identity follows the unchanged 0001_foundation. Run migrations explicitly with make migrate. Downgrading M2 deletes identity tables and their data and is for disposable environments only.

make api-test-postgres creates and cleans unique isolated schemas, including an upgrade/downgrade/upgrade migration check. SQLite tests skip PostgreSQL concurrency and migration checks.
