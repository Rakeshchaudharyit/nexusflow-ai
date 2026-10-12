# Deterministic demonstration

This is an opt-in synthetic workspace, never an automatic startup seed. Text generation uses the deterministic provider; embeddings use the offline 384-dimensional hash provider. No paid API key, real CRM, outbound email or live model is required. The simulated business actions are explicitly labeled by the runtime.

## Start and seed

```sh
cp .env.example .env
# Fill POSTGRES_PASSWORD and JWT_SECRET_KEY; generate them with secrets.token_urlsafe(48).
docker compose up -d --build --wait
docker compose exec -T api alembic upgrade head
# Create a private .env.demo (chmod 600) containing DEMO_OWNER_EMAIL and DEMO_OWNER_PASSWORD.
set -a
. ./.env.demo
set +a
make demo-seed
make demo-evaluate
make demo-inspect
```

The seed creates a deterministic UUID5 organization named **NexusFlow Demo**, reserved slug, owner membership, eight named agents plus the evaluation memory agent, one six-role enterprise team, internal tool grants, discovered HTTP MCP tools, three uploaded security documents, an Acme thread and pinned facts. It executes five agent runs and six team runs through the normal queue. Separate evaluation creates two genuine ten-case runs and marks the first baseline. The pending email remains pending; approved/rejected emails exercise real approval endpoints. Denied policy output is intentional.

Login with the private demo credentials at the local web origin. Select NexusFlow Demo if another workspace is active. Never publish owner credentials or expose this owner account as a public playground. Prefer a dedicated member account and temporary controlled access for public demonstrations.

## Ownership and reset

```sh
make demo-inspect
make demo-reset CONFIRM=<exact-organization-uuid-from-inspect>
make demo-seed
make demo-evaluate
```

Reset requires the exact UUID, reserved slug, original owner, sole owner membership, manifest and no active jobs. It refuses untracked rows added after the seed. It cascades only that marked organization and removes its upload directory; it retains the owner account and every ordinary workspace. The mode-600 manifest lives in the upload volume under `.demo-manifests`. Back it up with the documents. Do not edit demonstration data between seed and reset; use another workspace for manual experiments. Reset is destructive within the reserved workspace and has no in-product undo.

Seeding reuses named artifacts and matching run inputs. A PostgreSQL advisory lock prevents concurrent bootstrap/reset. Partial progress is recorded for recovery. Existing users retain their passwords. If pending approvals expire (default 24 hours), use the guarded reset and reseed to prepare a fresh presentation. Changing demo content intentionally requires reset; the seed does not silently overwrite normal data.

## Presentation route

Control Plane → Agents → Team topology → completed team run → pending approval → Knowledge documents → cited answer → Thread facts → trace waterfall → ten-case evaluation → baseline comparison. Explain that durable execution, tenant boundaries and policy gates are real while generated text and business actions are deterministic simulations.

## Production command variant (operator-run only)

After the approved production stack is migrated and healthy, export the private demo credentials and use its standalone Compose file explicitly:

```sh
docker compose --env-file .env.production -f docker-compose.prod.yml exec -T -e DEMO_OWNER_EMAIL -e DEMO_OWNER_PASSWORD api python -m app.demo.seed seed
docker compose --env-file .env.production -f docker-compose.prod.yml exec -T -e DEMO_OWNER_EMAIL -e DEMO_OWNER_PASSWORD api python -m app.demo.seed evaluate
docker compose --env-file .env.production -f docker-compose.prod.yml exec -T -e DEMO_OWNER_EMAIL api python -m app.demo.seed inspect
docker compose --env-file .env.production -f docker-compose.prod.yml exec -T -e DEMO_OWNER_EMAIL api python -m app.demo.seed reset --confirm <exact-demo-uuid>
```

Do not use development Make targets against a different production project by accident. These production commands were prepared, not executed.
