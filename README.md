# NexusFlow AI

A multi-tenant control plane for agent teams, MCP tools and human-governed workflows. NexusFlow makes execution inspectable: durable jobs, scoped memory, cited knowledge retrieval, policy decisions, traces and reproducible regression evaluations.

**Runtime truth:** text generation is deterministic and offline. Email/CRM actions are simulations. Optional OpenAI embeddings do not turn the text runtime into a live model. This project demonstrates orchestration infrastructure, not a benchmark of autonomous reasoning.

**Stack:** Next.js / React / TypeScript · FastAPI / Python · LangGraph · MCP · PostgreSQL / pgvector · Redis / Dramatiq.

[Quick start](#local-start) · [Demo](docs/demo-environment.md) · [Architecture](docs/architecture.md) · [Screenshots](docs/screenshots/README.md) · [Deployment](docs/deployment.md)

![Control Plane](docs/screenshots/01-control-plane.jpg)


## What works

| Capability | Implemented behavior |
|---|---|
| Agent runtime | Deterministic text runtime with explicit tool grants. |
| Agent teams | Supervisor-led specialists, ordered handoffs and validation. |
| MCP | HTTP discovery, validated schemas and exact host allowlisting. |
| Human approval | Review, approve or reject simulated high-risk actions. |
| Policy controls | Allow, require approval or deny before execution. |
| Durable jobs | PostgreSQL records, Redis/Dramatiq delivery, retry, cancellation and recovery. |
| Memory | Scoped thread/workspace context, provenance and expiration. |
| Knowledge / RAG | PDF, DOCX, Markdown and text ingestion; hybrid retrieval and citations. |
| Tracing | Tenant-scoped spans, timing and redacted summaries. |
| Evaluation | Deterministic cases, configuration snapshots and baseline comparisons. |
| Multi-tenancy | Tenant ownership constraints and owner/admin/member roles. |

## Architecture

```mermaid
flowchart LR
  Browser[Next.js browser UI] --> Proxy[Same-origin server proxy]
  Proxy --> API[FastAPI · auth and tenant roles]
  API --> DB[(PostgreSQL 17 + pgvector)]
  API --> Redis[(Redis · job IDs)]
  Redis --> Worker[Dramatiq worker]
  Worker --> DB
  Worker --> Graph[LangGraph agent / team runtime]
  Graph --> Tools[Internal tools + allowlisted MCP]
  Graph --> Policy[Policy → human approval]
  Graph --> Context[Scoped memory + cited retrieval]
  API --> Uploads[(Persistent knowledge files)]
  Worker --> Uploads
  Graph --> Traces[Redacted traces and spans]
  API --> Evaluation[Deterministic evaluation and baselines]
  Evaluation --> Worker
  Traces --> DB
```

PostgreSQL is execution truth; Redis is delivery transport. Readiness checks DB/Redis; worker heartbeat health is monitored separately. [Architecture details](docs/architecture.md) · [Stack rationale](docs/tech-stack.md).

## Local start

Prerequisites: Docker Engine/Desktop with Compose; Python 3.12 and Node 22 for host checks.

```sh
cp .env.example .env
# Fill POSTGRES_PASSWORD and JWT_SECRET_KEY with unique generated secrets.
# Generate each using: python3 -c 'import secrets; print(secrets.token_urlsafe(48))'
make up
make migrate
```

Open http://localhost:3000. API: http://localhost:8000/api/v1; development docs: http://localhost:8000/docs. If port 8000 is occupied, set `API_PORT=8002` and `NEXT_PUBLIC_API_URL=http://localhost:8002/api/v1` before building. Keep API_INTERNAL_URL server-only; Compose supplies its internal hostname. No secret belongs in a NEXT_PUBLIC variable.

Host development: `make api-install mcp-install web-install`; configure PostgreSQL/Redis host addresses in `.env`, then run `make api-dev`, `make worker-dev`, `make web-dev` in separate terminals. See [.env.example](.env.example) and the feature guides for settings. The Docker knowledge volume is distinct from host `.data/knowledge`.

## Reproducible demo

Create a private, ignored `.env.demo` containing `DEMO_OWNER_EMAIL` and a strong `DEMO_OWNER_PASSWORD`; `chmod 600 .env.demo`. Existing users retain their password.

```sh
set -a
. ./.env.demo
set +a
make demo-seed
make demo-evaluate
make demo-inspect
# Destructive only within the reserved demo workspace:
make demo-reset CONFIRM=<exact-demo-organization-uuid>
```

The bootstrap creates a marked synthetic workspace, nine agents, a specialist team, MCP server, memory thread, knowledge source, runs, approvals and an evaluation dataset through normal product APIs. Documents are ingested by the worker; runs, approvals, traces and evaluation outcomes are real persisted executions. Repeat seeding reuses artifacts. Reset refuses ordinary workspaces, unknown user rows, extra memberships and active jobs. [Full demo guide](docs/demo-environment.md).

## Portfolio walkthrough

![Team orchestration](docs/screenshots/03-team-orchestration.jpg)

The configured control rail shows each specialist's actual permissions. Execution order and handoffs are inspected on the team run.

![Grounded retrieval](docs/screenshots/06-knowledge-rag.jpg)

A cited security answer links retrieval evidence to its source document.

![Approval review](docs/screenshots/08-human-approval.jpg)

A simulated email remains paused for human review. Approval does not send a real email.

![Trace waterfall](docs/screenshots/10-trace-waterfall.jpg)

Span timing links runtime work, tool calls and queue delay.

![Evaluation](docs/screenshots/11-evaluation-run.jpg)

Ten deterministic cases check tools, memory, policies, approvals and retrieval. These are application regression checks, not an LLM judge.

[Portfolio story](docs/portfolio-story.md) · [Concise summary](docs/portfolio-summary.md) · [Screenshot captions](docs/screenshots/README.md).

## Validation

```sh
make api-test                 # SQLite fallback; PostgreSQL-only checks skip
make api-test-postgres        # isolated schemas in the configured local PostgreSQL
make worker-test mcp-test
make api-lint mcp-lint
make web-test web-lint web-typecheck web-build
```

Tests bind local MCP sockets and PostgreSQL checks need the running local DB. Migration validation: `docker compose exec -T api alembic current` and `docker compose exec -T api alembic check`. Current head is `0010_observability_evaluation`; M11 adds no schema migration. Final M11 validation on 2026-10-12 recorded PostgreSQL 487 passed; SQLite 482 passed / 5 skipped; worker 32 passed; MCP 15 passed; frontend 49 passed. These are dated results, not live badges. Counts and actual QA evidence are recorded in [M11 validation](docs/m11-validation.md).

## Deployment and security

[Single-VPS/Hostinger deployment](docs/deployment.md) prepares standalone production Compose, Nginx/TLS, one-time migrations, persistent storage and paired database/upload backups. [Release checklist](docs/production-checklist.md) separates local checks from operator deployment gates. No VPS or public DNS deployment has been performed.

Production fails closed on weak JWT/database secrets, insecure cookies, debug mode, inline execution, unsafe origins/hosts and remote plaintext data services. Production docs/OpenAPI are disabled. Tenant queries and database constraints protect resource ownership; role checks protect administrative configuration and approval decisions. Uploads validate types, filenames and size; MCP uses allowlisting and SSRF defenses. Traces redact credentials and bound summaries. These controls require continued review when integrating live providers or business systems.

## Documentation

| Area | Guide |
|---|---|
| Authentication | [Auth and tenancy](docs/authentication.md) |
| Tools | [MCP integration](docs/mcp-integration.md) |
| Execution | [Background jobs](docs/background-execution.md) |
| Context | [Memory and threads](docs/memory-context.md) |
| Retrieval | [Knowledge and RAG](docs/knowledge-rag.md) |
| Quality | [Observability and evaluation](docs/observability-evaluation.md) |
| Release evidence | [M11 validation](docs/m11-validation.md) |

## Status and limitations

Local implementation and M11 hardening are complete. Version remains 0.1.0. [Public repository readiness](docs/github-public-readiness.md) records publication gates and the proposed release.

The deployment target is a single VPS, without HA or measured load capacity. Offline embeddings demonstrate retrieval mechanics rather than production semantic quality. No node-level LangGraph checkpoint recovery, OCR, real token/cost accounting, automatic trace retention, zero-downtime deployment, external tracing exporter, live text provider, real email/CRM action, password recovery or public read-only playground is claimed. Backup procedures require an operator restore drill before production. No project-level license exists in this checkout; the owner must choose one before public distribution. Dependency licenses remain with their packages. This checkout has no Git metadata, so history scanning and release tagging could not be verified.
