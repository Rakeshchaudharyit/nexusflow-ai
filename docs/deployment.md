# Single-VPS deployment (prepared, not deployed)

Use a Linux VPS with SSH/root administration (including a Hostinger VPS), not shared PHP hosting. Start with 2 vCPU, 4 GB RAM and 30 GB SSD as an unbenchmarked planning estimate; monitor real memory, disk and job latency before sizing production. Provision Ubuntu supported by [Docker's installation guide](https://docs.docker.com/engine/install/ubuntu/) and install Engine plus the Compose plugin from its official repository. Follow [Certbot's current Nginx instructions](https://certbot.eff.org/instructions) for the selected OS. Public DNS, TLS certificates, firewall changes and deployment require the operator's approval. None were performed for M11.

## Environment and network

Keep `/opt/nexusflow-ai/.env.production` mode 600, outside public directories. Copy `.env.example`, then set the following (replace example domains):

```dotenv
APP_ENV=production
DEBUG=false
AUTH_COOKIE_SECURE=true
FRONTEND_URL=https://app.example.com
CORS_ORIGINS=["https://app.example.com"]
ALLOWED_HOSTS=["app.example.com","api.example.com","api","localhost","127.0.0.1"]
NEXT_PUBLIC_API_URL=https://api.example.com/api/v1
API_PORT=8000
EXECUTION_MODE=queue
MCP_ALLOWED_HOSTS=["mcp-demo:8765"]
MCP_ALLOW_PUBLIC_HOSTS=false
KNOWLEDGE_UPLOAD_DIR=/data/knowledge
```

Generate unique JWT and PostgreSQL secrets using `python3 -c 'import secrets; print(secrets.token_urlsafe(48))'`. Never reuse development secrets. JWT must have at least 48 bytes and meaningful character diversity; DB password at least 16 characters. Settings fail closed on insecure production cookies, debug, inline execution, wildcard hosts, HTTP origins, non-absolute upload directories, or remote DB/Redis without TLS. JSON arrays must remain valid JSON. APP_ENV is the actual setting name. `NEXT_PUBLIC_*` values are public and built into browser assets; never place secrets there. Changing the public URL requires rebuilding web.

`docker-compose.prod.yml` is a **standalone** file; do not merge it with the development file. It supplies internal PostgreSQL/Redis addresses, production mode, Secure cookies, queue execution and absolute upload storage. PostgreSQL, Redis and MCP have no published ports. API and web bind loopback for host Nginx. Expose only 80/443 and restricted SSH at the VPS firewall. Redis has no persistence: PostgreSQL execution jobs allow redelivery after broker loss. For managed services configure a separate reviewed Compose adaptation; the current stack deliberately uses its private services.

## Build, migration and start

Transfer a reviewed source release excluding secrets, uploads, caches and backups to `/opt/nexusflow-ai`. Keep a versioned prior release and record its image IDs; this checkout has no Git metadata, so no repository URL or release tag is invented.

```sh
cd /opt/nexusflow-ai
docker compose --env-file .env.production -f docker-compose.prod.yml config --quiet
docker compose --env-file .env.production -f docker-compose.prod.yml build
docker compose --env-file .env.production -f docker-compose.prod.yml up -d --wait postgres redis mcp-demo
# Stop API and worker before applying migrations on an existing installation.
docker compose --env-file .env.production -f docker-compose.prod.yml stop api worker
# One release operator applies migrations; entrypoints do not migrate automatically.
docker compose --env-file .env.production -f docker-compose.prod.yml run --rm --no-deps api alembic upgrade head
docker compose --env-file .env.production -f docker-compose.prod.yml up -d --wait
docker compose --env-file .env.production -f docker-compose.prod.yml exec -T api alembic current
docker compose --env-file .env.production -f docker-compose.prod.yml exec -T api alembic check
curl --fail http://127.0.0.1:8000/api/v1/health/ready
```

M11 adds no migration. Expected head: `0010_observability_evaluation`. Back up before upgrades. Test migrations on a restored copy. Never use `down -v` for updates. Reverting application images is safe only if compatible with the installed schema; otherwise restore the matched database and uploads in an isolated recovery project. Do not automatically downgrade production.

## Nginx and HTTPS

Create two HTTP server blocks initially, using the locations below, then issue certificates and enable HTTPS using `sudo certbot --nginx -d app.example.com -d api.example.com`. Certbot installs certificate directives and HTTP redirects; inspect them with `sudo nginx -t` before reloading. Run `sudo certbot renew --dry-run` and verify the renewal timer. The final HTTPS application blocks should include:

```nginx
# Inside server { listen 443 ssl; server_name app.example.com; ...TLS directives... }
client_max_body_size 11m;
add_header X-Content-Type-Options nosniff always;
add_header Referrer-Policy strict-origin-when-cross-origin always;
location / {
    proxy_pass http://127.0.0.1:3000;
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_read_timeout 35s;
}
# In a separate HTTPS server for api.example.com:
client_max_body_size 11m;
location / {
    proxy_pass http://127.0.0.1:8000;
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_read_timeout 35s;
}
```

These are server-block fragments, not a complete certificate-bearing configuration. Use HSTS only after HTTPS and renewal are verified. Trust forwarded headers only from loopback Nginx; do not expose an alternate public API port. The browser normally uses `/api/backend` on the app domain, which forwards to the internal API. API docs/OpenAPI are disabled in production; use a private development instance for contract exploration.

## Backups and restore

Both PostgreSQL and `knowledge_uploads` are persistent named volumes. Uploads include original documents and the demo manifest; pgvector embeddings/chunks and all execution metadata are in PostgreSQL. Redis is disposable transport. Store encrypted backups off-host with restricted access, retention and a restore drill. Dumps contain tenant data, not just infrastructure.

For a consistent maintenance snapshot, stop API/worker, record actual volume names with `docker volume ls`, and run (set COMPOSE_PROJECT_NAME consistently with the existing deployment):

```sh
mkdir -p backups
chmod 700 backups
docker compose --env-file .env.production -f docker-compose.prod.yml stop api worker
docker compose --env-file .env.production -f docker-compose.prod.yml exec -T postgres sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc' > backups/database.dump
docker compose --env-file .env.production -f docker-compose.prod.yml run --rm -T --no-deps --entrypoint tar api -C /data/knowledge -czf - . > backups/knowledge.tar.gz
chmod 600 backups/*
docker compose --env-file .env.production -f docker-compose.prod.yml up -d --wait api worker
```

Restore **into an empty isolated project**, never over the working installation. Use a separate `.env.restore` and `-p nexusflow-restore`; assign unused loopback web/API ports in a copied Compose file to prevent collisions. Start only PostgreSQL/Redis, then:

```sh
docker compose -p nexusflow-restore --env-file .env.restore -f docker-compose.restore.yml exec -T postgres sh -c 'pg_restore --exit-on-error --no-owner -U "$POSTGRES_USER" -d "$POSTGRES_DB"' < backups/database.dump
docker compose -p nexusflow-restore --env-file .env.restore -f docker-compose.restore.yml run --rm -T --no-deps --entrypoint tar api -C /data/knowledge -xzf - < backups/knowledge.tar.gz
```

Use the matching PostgreSQL/pgvector image and release. Verify restored document permissions for UID 10001, migration head, counts, readiness, cited retrieval, pending approvals, traces and worker execution before accepting a recovery. Do not enable workers on a restored production copy until queued external actions have been reviewed. M11 documents this recovery procedure; no production restore is claimed.

## Health and operations

`GET /api/v1/health` is liveness; `/health/ready` checks DB and Redis, returning safe component states and 503 on failure. Worker health stays separate: its recovery loop refreshes `/tmp/nexusflow-worker-alive`; Compose marks it unhealthy after 90 seconds of stale heartbeat. API readiness does not falsely imply a worker is live. Monitor both API readiness and worker health, queued-job age, retry/failed counts, disk, PostgreSQL backups and TLS expiry. Use bounded `docker compose logs --tail 100 api worker`; do not publish logs, bearer headers or `.env` files.

If jobs remain queued, inspect worker health, Redis connectivity and persisted execution attempts. If uploads fail, check the size/type limits, upload-volume ownership and available disk. If MCP fails, check exact host:port allowlisting and its health; do not disable SSRF controls. If HTTPS login fails, check Origin/CORS, Secure-cookie and public URL alignment. A clean health probe is not a substitute for these smoke tests.
