# Background execution, durable jobs and recovery (M7)

Before M7, agent and team graphs ran inside the HTTP request that created them. M7 moves every execution into a separate **worker** service:
- An API request only validates the run, persists it with its job, and enqueues the job.
- The response returns in milliseconds with status `queued`.
- The browser polls the run until it settles.

```text
Browser ─► FastAPI ─► PostgreSQL (run + ExecutionJob, one transaction)
                 └──► Redis queue (job id only)
                            │
                            ▼
                         Worker ─► claim job in PostgreSQL ─► LangGraph runtime
                                                                     │
                       PostgreSQL ◄── events, result, run + job status (atomic)
```

## Queue technology: Dramatiq 2.2.1 (Redis broker)

The M7 brief preferred ARQ, allowing Dramatiq only for a concrete reason. There are two:

1. **Dependency compatibility.** ARQ's latest release (0.28.0) requires `redis<6`. NexusFlow pins `redis==6.4.0` for readiness checks, so ARQ would force a downgrade. Dramatiq 2.2.1 supports `redis>=4,<9` and adds no other runtime dependencies.
2. **Execution model.** The whole execution path is synchronous: sync FastAPI routes, SQLAlchemy sessions, `graph.stream(...)`, and the MCP client wrapper.
   - ARQ is asyncio-only. Every enqueue would need a loop bridge inside a sync route, and every job would need `asyncio.to_thread`.
   - Dramatiq actors are plain functions on worker threads, and `send()` is synchronous.

Celery was not considered necessary.

**Dramatiq's role is transport only.** Its own retries are disabled (`max_retries=0`), and the actor time limit is a generous 30-minute ceiling. Retry policy, attempts and recovery all live in PostgreSQL.

## PostgreSQL is the source of truth; Redis is transport

| Concern | Where it lives |
| --- | --- |
| Run status, result, error, events | `agent_runs` / `agent_team_runs`, `agent_run_events` (PostgreSQL) |
| Job status, attempts, owner, heartbeats, retry and recovery state | `execution_jobs` (PostgreSQL) |
| "Please look at job X" | A Redis message carrying **only the job id** |

The queue message contains no input text, prompt, JWT, refresh token, MCP credential or tenant data. The worker reloads everything from PostgreSQL. If Redis is wiped, nothing authoritative is lost: recovery re-sends every job that is still queued (see below). The Compose Redis runs without persistence, so this path is exercised in practice.

## Worker service

The Compose service `worker` uses the **same image** as `api`, with a different command:

```bash
dramatiq app.worker --processes 1 --threads 4
```

- `app/worker.py` builds one `JobExecutor` per process. It uses the same `AgentRuntime`, `TeamRuntime`, tool registry and MCP adapter as before; `app/jobs/runtimes.py` is shared with the API, so no runtime code is duplicated.
- A `Recovery` middleware runs a recovery pass at worker boot and then every `JOB_RECOVERY_SECONDS` on a background thread. No external cron is needed.
- Each pass touches `/tmp/nexusflow-worker-alive`, which the container healthcheck reads (healthy while it is younger than 90 s).
- API readiness does **not** depend on the worker. Runs can always be persisted; if no worker is up they wait as `queued`.
- Worker IDs look like `worker:<hostname>:<pid>:<random>`. They are stored on the job for debugging and are never used for authorization.

## Job model (`execution_jobs`, migration `0007_background_execution`)

| Column | Purpose |
| --- | --- |
| `id`, `organization_id` | Job identity and tenant |
| `job_type` | `single_agent_run`, `team_run` or `approval_action` |
| `agent_run_id` / `team_run_id` / `approval_request_id` | The resource. Composite FKs `(id, organization_id)` pin it to the job's tenant, and a CHECK requires exactly the columns that match `job_type` |
| `status` | `queued`, `running`, `retrying`, `completed`, `failed`, `cancelled` |
| `attempt`, `max_attempts` | Attempts started so far, and the limit |
| `queue_name`, `worker_id` | Transport queue; last claimant (debugging only) |
| `enqueued_at` | Last successful hand-off to Redis. `NULL` means delivery is pending |
| `started_at`, `heartbeat_at`, `completed_at` | Attempt timing and liveness |
| `next_retry_at` | When a retrying job becomes claimable again |
| `error_code`, `error_message` | Safe, persisted error (never a traceback) |
| `cancellation_requested_at` | Cooperative cancellation flag |

Constraints:
- One job per agent run (`uq_execution_jobs_agent_run`).
- One job per type per team run (`uq_execution_jobs_team_run_type`).
- One job per approval (`uq_execution_jobs_approval`).
- Retries reuse the row; they never add a job.

Indexes:
- `(organization_id, created_at)`
- `(status, heartbeat_at)`: stale scan
- `(status, next_retry_at)`: due-retry scan

Other 0007 changes:
- `agent_run_events.attempt` (nullable; the attempt that wrote each event).
- Event types `retry_scheduled`, `run_cancelled`, `team_run_cancelled`.
- Approval status `cancelled`.

0007 inserts no data. Its downgrade removes M7-only events, maps cancelled approvals to `expired`, and cancels queued or running runs that pre-M7 code would never execute.

## Lifecycles

Run status (unchanged values; `retrying` is shown in the UI when the job is retrying):

```text
queued ─► running ─► completed | failed | cancelled
              │    └► awaiting_approval ─(approve)► queued ─► running ─► completed | failed
              │                         └(reject / cancel / expire)► completed | cancelled
              └─ transient failure or lost worker ─► queued (job: retrying) ─► running …
```

Job status:

```text
queued ─claim─► running ─► completed | failed | cancelled
                   └─retryable / lost─► retrying ─(due)─claim─► running …
```

A team run that pauses for approval ends its `team_run` job as `completed`. The approval later creates a separate `approval_action` job.

## Atomic claiming and multi-worker safety

`claim()` is a single statement:

```sql
UPDATE execution_jobs SET status='running', attempt=attempt+1, worker_id=…, started_at=now(), heartbeat_at=now()
WHERE id=:id AND status IN ('queued','retrying') AND cancellation_requested_at IS NULL
  AND attempt < max_attempts AND (next_retry_at IS NULL OR next_retry_at <= now())
RETURNING …
```

Concurrent claimers serialise on the row lock, and PostgreSQL re-evaluates the `WHERE` for the second claimer, so exactly one gets a row. Whoever gets nothing exits quickly: a duplicate message, a redelivery, a cancelled job or a retry that is not due yet.

The runtime then moves the run `queued → running` under the run's row lock.

Every terminal write settles the run and the job **in the same transaction** (`JobControl.settle`). Settling re-checks ownership (`status = running AND worker_id AND attempt`), so a worker that lost its job writes nothing more. The event stream applies the same ownership guard before each event.

`test_two_workers_racing_for_one_job_execute_it_once` (PostgreSQL) runs two workers at the same moment on one job. It finds exactly one claim, one `team_run_started`, one action execution and one completion. It passed 3 times in a row.

## Heartbeat and stale detection

While an attempt runs, a daemon thread updates `heartbeat_at` every `WORKER_HEARTBEAT_SECONDS` (default 10). The update is conditional on ownership; if no row matches, the thread stops and the run stops at its next checkpoint.

A job is **stale** when `status = running` and `heartbeat_at` is older than `JOB_STALE_AFTER_SECONDS` (default 60). Configuration enforces stale ≥ 2 × heartbeat.

## Recovery

`app/jobs/service.py::recover()` runs in every worker (boot plus periodic) and is safe to run concurrently:

1. **Stale running jobs.** Lock approval → run → job, re-check staleness, then:
   - A cancellation was requested: cancel the job and run (and close a pending approval).
   - Attempts remain: job → `retrying` (`error_code = worker_lost`, due immediately). The run returns `running → queued`, and a `retry_scheduled` event is recorded.
   - Otherwise: job and run → `failed` with `worker_lost` ("The worker stopped responding and the retry limit was reached.").
2. **Lost or undelivered queued jobs.** These have `enqueued_at IS NULL` (Redis was down at submission) or are older than `JOB_REDELIVER_AFTER_SECONDS` (the message may have been lost). They are re-sent.
3. **Retrying jobs whose delayed message never arrived.** They are re-sent once due.

Duplicate sends are harmless because `claim()` admits one execution. No job can stay `running` after its worker dies.

## Retry policy

Classification is explicit (`app/jobs/retry.py`):

| Retryable (transient) | Permanent (one attempt) |
| --- | --- |
| `mcp_unavailable`, `mcp_timeout`, `provider_timeout` (reserved), `worker_lost`, `worker_error` | `policy_denied`, `invalid_action`, `invalid_tool_arguments`, `tool_not_permitted`, `unknown_tool`, `objective_not_supported`, `team_not_runnable`, `agent_not_active`, MCP tool/server disabled or not found, `mcp_url_rejected`, `mcp_tool_error`, `mcp_malformed_result`, generic execution failures |

- **Limit:** `JOB_MAX_ATTEMPTS = 3`.
- **Backoff:** bounded exponential, `base × 3^(attempt-1)`. With `JOB_RETRY_BASE_SECONDS = 5` the retries come after 5 s and then 15 s; the delay is capped at 300 s. Tests use a base of 0.
- **Persisted state:** `attempt`, `next_retry_at`, `error_code` and a safe `error_message`.
- **Retry delivery:** the retry message is sent with a delay. An early delivery cannot claim before `next_retry_at`.
- **Exhaustion:** the final failure marks the job and run `failed` with the last safe error (e.g. `mcp_unavailable` / "The MCP server could not be reached.").

## Graph restart safety and the checkpoint decision

**M7 provides durable job restart and recovery, not node-level resume.** A retried attempt restarts the graph from the beginning. This is safe because:
- **Read-only tools are idempotent.** The demo customer lookup, calculator, system status and MCP tools have no side effects.
- **Business actions are exactly-once across attempts.**
  - Approval requests: `TeamRunRecorder.request_approval` reuses the approval an earlier attempt persisted.
  - Allowed actions: `execute_action` returns the earlier attempt's `action_executions` row instead of executing again.
  - The unique constraints remain as a backstop.
  - `test_restarted_team_run_reuses_the_executed_action` kills the worker after an ALLOW action committed. After recovery, the restarted graph completes the run with one execution.
- **Events stay consistent.**
  - `EventStream.resume()` continues the run's sequence under the run lock.
  - Every event records its `attempt`.
  - Earlier attempts are never overwritten.
  - Team-run results and handoffs show the latest attempt, while the timeline shows all of them.

**LangGraph checkpointer review.** The installed `langgraph` 1.2.14 ships `langgraph-checkpoint` 4.2.0, which provides the base saver interface and an in-memory saver. A PostgreSQL saver requires the separate `langgraph-checkpoint-postgres` package. Adopting it would mean:
- persisting graph state per run thread (`organization:run` thread IDs);
- making every node's side effects resumable;
- reconciling checkpoints with the recorder's own persistence and the approval continuation.

The graphs here complete in milliseconds, so node-level resume would buy little and risk false durability claims. It was therefore **not** introduced in M7.

## Infrastructure versus business events

Queue mechanics (claims, heartbeats, deliveries) live on the `execution_jobs` row and in worker logs. They are not written to the business timeline. Only business-relevant transitions are `agent_run_events`:
- `retry_scheduled`: an attempt failed transiently or its worker was lost.
- `run_cancelled` / `team_run_cancelled`.
- The usual started, completed and failed events, each tagged with its attempt.

## Cancellation (cooperative)

- `POST /api/v1/agent-runs/{id}/cancel` and `POST /api/v1/agent-team-runs/{id}/cancel`.
- **Permissions:** owners and admins may cancel any run in the organization; members only runs they started. Another tenant's run returns 404.

| Run state | Effect |
| --- | --- |
| `queued` (including waiting out a retry) | Job and run cancelled immediately. A later message finds nothing to claim |
| `running` | `cancellation_requested_at` is set. The runtime checks it between graph stages and records `run_cancelled`. Workers are never killed |
| `awaiting_approval` | The pending approval becomes `cancelled` and the run `cancelled`; a later approve returns 409 `approval_not_pending` and executes nothing |
| `completed` / `failed` / `cancelled` | 409 `run_not_cancellable` |

Two refinements:
- A pending cancellation wins over a retry. Without that, a cancelled run hitting a transient failure would wait for a retry that can never be claimed.
- Once an ALLOW action has executed, a cancellation noticed afterwards does not relabel the run; it completes with that action.

## Approval continuation (now worker-executed)

```text
Owner clicks Approve ─► one transaction: approval=approved, approval_approved event,
                         run=queued, ExecutionJob(approval_action)  ─► commit ─► enqueue ─► 200
Worker ─► claim ─► lock approval → run → job ─► re-check status + policy ─► perform_action once
       ─► action_started/completed, team_run_completed, job completed (same transaction)
```

The approve response returns `status: approved`, `execution: null` and `team_run_status: queued`. The UI shows "Approved. The simulated action is queued for the worker." until the execution exists.

Rejection stays synchronous because it executes nothing.

Exactly-once holds across:
- a double click (the second request gets 409 `approval_not_pending`);
- redelivered or re-claimed jobs (the existing execution is reused, and the run is no longer runnable);
- two workers (the claim and the locks).

## Redis loss and outages

- **Redis down when a run is submitted.** The run and job are committed, the send fails fast (2 s connect timeout), and the API still returns 201. The response carries `execution.delivery_pending: true` and the UI explains the job will be delivered automatically. Recovery re-sends it on its next pass once Redis is back.
- **Redis restarted and lost queued messages.** The jobs remain `queued` in PostgreSQL and are re-sent once older than `JOB_REDELIVER_AFTER_SECONDS`.
- **The worker reconnects on its own.** Dramatiq's consumer logs connection errors and resumes.

## Frontend

- Creating a run shows **Queued** immediately. The agent test console and the team run panel poll the run every 2 s (`POLL_INTERVAL_MS`) while it is `queued` or `running`, through Running to the final state; nothing is shown as completed before the worker finishes.
- Polling stops on completion, failure, `awaiting_approval`, cancellation, unmount and workspace switch. Switching workspace remounts workspace pages, so another organization's run is never polled into view.
- Run and team-run detail pages show a **Background execution** panel: job status, attempt n of m, start, last heartbeat, next attempt, last safe error, and **Cancel run** where permitted.
- Lists and the Control Plane show **Retrying** for a queued run whose job is retrying. Lists poll only while a listed run is active.
- There are no WebSockets in M7.

## Configuration

| Variable | Default | Meaning |
| --- | --- | --- |
| `EXECUTION_MODE` | `queue` | `inline` runs the same executor inside the request; tests only, and refused in production |
| `QUEUE_NAME` | `nexusflow-runs` | Dramatiq queue |
| `WORKER_HEARTBEAT_SECONDS` | `10` | Heartbeat cadence |
| `JOB_STALE_AFTER_SECONDS` | `60` | Stale threshold (≥ 2 × heartbeat) |
| `JOB_MAX_ATTEMPTS` | `3` | Attempts per job |
| `JOB_RETRY_BASE_SECONDS` | `5` | Backoff base (5 s, 15 s) |
| `JOB_RECOVERY_SECONDS` | `15` | Recovery pass interval |
| `JOB_REDELIVER_AFTER_SECONDS` | `60` | Re-send queued messages older than this |

## Logging

Worker log lines carry `job_id`, `run_id`, `org_id`, `job_type`, `attempt` and status. They never include passwords, tokens, MCP secrets, inputs or action payloads.

## Known limitations

- **No node-level resume.** Restarts re-run the graph; read-only tools run again.
- **Heartbeat-based staleness.** A worker frozen longer than the stale threshold is treated as dead. Its later writes are rejected by the ownership checks, but a stale worker writing the very next event in the instant before recovery could hit a unique-sequence conflict. That conflict is rejected by the database and only aborts that stale attempt.
- **Recovery latency.** A run lost in Redis waits up to `JOB_REDELIVER_AFTER_SECONDS` + `JOB_RECOVERY_SECONDS` before re-delivery. A dead worker's job waits up to `JOB_STALE_AFTER_SECONDS` + `JOB_RECOVERY_SECONDS`.
- **Lazy expiry.** Approval expiry is still applied on access, not by the worker.
- **Bounded polling, not streaming.** The UI polls every 2 s; live streaming is out of scope.
- **No API-level worker health.** Worker liveness is exposed only through the container healthcheck, not an API endpoint.
- **Public MCP DNS pinning.** Still not implemented (an M4 caveat).
