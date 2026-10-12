# Technology stack

| Layer | Implementation | Reason |
|---|---|---|
| UI | Next.js 16.4, React 19.3, TypeScript 5.9, Tailwind 4.3 | Typed operational interface, same-origin API proxy |
| API | Python 3.12, FastAPI, Pydantic settings | Validated HTTP contracts and production configuration |
| Persistence | PostgreSQL 17, SQLAlchemy 2, Alembic | Tenant-owned durable runs, transactional approval gates |
| Retrieval | pgvector 0.8.6, lexical plus semantic scoring | Bounded citations and assigned-source retrieval |
| Queue | Redis 7, Dramatiq | Job ID delivery; PostgreSQL remains execution truth |
| MCP | Official Python MCP SDK, streamable HTTP | Discoverable, allowlisted external tools |
| Auth | Argon2 passwords, short-lived JWT, rotating refresh cookie | Workspace roles and session revocation |
| Operations | Docker Compose, Nginx, TLS | Single-VPS deployment with private data services |
| Validation | pytest (SQLite + PostgreSQL), Ruff, Node tests, ESLint, tsc | API/runtime boundaries plus frontend contracts |

Lock files carry exact dependency versions. Text generation is deterministic; optional OpenAI embeddings are separate from text generation. No claim of autonomous general reasoning, live email, live CRM, distributed tracing export or multi-region availability is made.
