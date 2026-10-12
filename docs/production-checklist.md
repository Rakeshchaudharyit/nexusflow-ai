# Production release checklist

Local validation and deployment are separate. Complete these operator gates before serving users:

- [ ] Reviewed source release and image IDs recorded; license chosen by owner before public distribution.
- [ ] Unique production secrets generated; mode-600 env file and encrypted off-host backup storage.
- [ ] Explicit HTTPS origins/hosts, Secure cookies, debug off, deterministic-provider limitations disclosed.
- [ ] Private DB/Redis/MCP ports; restricted SSH; Nginx 11 MB body cap; TLS renewal verified.
- [ ] Backups of database and knowledge volume taken together; isolated restore drill completed.
- [ ] Single migration operator, expected `0010_observability_evaluation` head, schema check clean.
- [ ] API/worker/web images built, non-root runtime verified, all services healthy.
- [ ] Tenant/role tests and requested lint/type/build checks green for the release.
- [ ] Auth, queued run, cancellation, approval/rejection, memory, retrieval, trace and evaluation smoke tests.
- [ ] No public demo owner credentials, production data in screenshots, logs or dumps in source/build context.
- [ ] Monitoring of queue age, worker health, disk, TLS expiry and failed backups configured.
- [ ] Rotate any exposed credentials; review MCP exact-host allowlist and tool grants.
- [ ] Validate upload volume permissions, size caps and backup coverage.
- [ ] Review log/trace privacy; set and operate a trace retention/deletion policy (no automatic retention).
- [ ] Remove demo accounts/workspaces from production; never publish owner passwords.
- [ ] Assess authentication/API rate limits at the reverse proxy before public access; application rate limiting is not claimed.
- [ ] Rollback compatibility reviewed; no `down -v`; DNS/deployment approval obtained.

See [deployment procedure](deployment.md) and [M11 evidence](m11-validation.md). These unchecked deployment gates are intentional: M11 prepares deployment and does not perform it.
