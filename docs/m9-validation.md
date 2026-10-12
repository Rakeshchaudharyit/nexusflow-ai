# M9 Validation: RAG / Knowledge Platform

Date: 2026-10-09. Validated on the local Docker stack, all six services healthy: web :3000, api :8002, worker, postgres (`nexusflow-ai-postgres:17-pgvector`), redis, mcp-demo. Live Alembic revision: `0009_knowledge_rag (head)`. No external APIs were called; every test uses `deterministic_local` embeddings.

## Preflight

- **No other writer.** The ChatGPT/Codex desktop app and a Codex `exec-server` were running on the machine, but neither had the repository as its working directory or open, and every file changed in the previous hour was this session's own M8 work. No other Claude session was writing.
- **Starting point:** `0008_agent_memory`. All six services healthy; PostgreSQL 17.11 (Alpine, musl), whose image had **no** pgvector (`pg_available_extensions` was empty).
- **Code inspected:** M7 jobs (`execution_jobs`, claim/heartbeat/recover/cancel), the M8 memory context builder, M5 agent tool assignments, the M3 `LLMProvider` and the M5 `TeamProvider`.
- **Versions chosen.** Each dependency is at least two weeks old:

  | Dependency | Chosen | Released | Note |
  | --- | --- | --- | --- |
  | pgvector | 0.8.6 | 2026-07-29 | 0.8.7 was only 8 days old |
  | pypdf | 6.19.0 | 2026-09-16 | 6.20.0 was released that day |
  | python-docx | 1.2.0 | 2025-06 | |
  | lxml | 6.1.3 | 2026-09-02 | |
  | python-multipart | 0.0.32 | | already locked |

## PostgreSQL + pgvector

- **Backup:** taken first with `pg_dump -Fc`.
- **Image choice:** the live database uses `en_US.utf8` collation on musl. Switching to the Debian `pgvector/pgvector` image would change libc collation rules under existing text indexes. Compose therefore builds `infra/docker/postgres.Dockerfile`: `postgres:17-alpine` plus pgvector **0.8.6** compiled with `with_llvm=no OPTFLAGS=""`.
- **Container recreated** on the same `postgres_data` volume. Afterwards `pg_available_extensions` showed `vector 0.8.6`, with no collation warnings.
- **Data intact:** counts (users / orgs / events / agents / teams / team runs / agent runs / memory entries / jobs) were `12|17|1289|26|4|50|61|14|29` before the image switch, after it, and after migration 0009.

## Automated results

| Suite | Command | Result |
| --- | --- | --- |
| API, PostgreSQL + pgvector | `make api-test-postgres` | **434 passed** |
| API, SQLite | `make api-test` | **429 passed, 5 skipped** (4 earlier PostgreSQL-only tests plus the in-SQL vector filter test) |
| Knowledge (M9) | `cd apps/api && .venv/bin/python -m pytest tests/test_knowledge.py` | **41 passed** on PostgreSQL; **40 passed, 1 skipped** on SQLite |
| Worker | `make worker-test` | **32 passed, 1 skipped** |
| MCP demo server | `make mcp-test` | **15 passed** |
| Frontend | `npm test` in `node:22-alpine` | **44 passed** (40 + 4 knowledge) |
| Ruff lint and format | `make api-lint` | All checks passed; 148 files formatted |
| MCP lint | `make mcp-lint` | clean |
| ESLint | `make web-lint` | clean |
| TypeScript (strict) | `make web-typecheck` | clean |
| Production build | `make web-build` | success; `/app/knowledge`, `/app/knowledge/new` and `/app/knowledge/[sourceId]` built |
| Compose | `docker compose config -q` | valid |

## Knowledge test coverage (`tests/test_knowledge.py`)

| Requirement | Test(s) | Result |
| --- | --- | --- |
| Deterministic 384-d embeddings | `test_deterministic_embeddings_are_stable_normalised_and_384_wide` | pass: same text gives the same vector, unit norm, related text scores closer |
| Optional OpenAI provider, offline | `test_openai_provider_classifies_failures_without_network` | pass: mock transport only; 429, 503 and timeout raise `embedding_unavailable` |
| Chunking quality | `test_chunking_keeps_structure_pages_and_overlap` | pass: headings kept, list block intact, overlap present, page metadata kept, deterministic |
| Context order and delimiting | `test_context_order_and_knowledge_is_delimited_data` | pass: order is system < tools < (memory) < knowledge < request; a forged `END KNOWLEDGE CONTEXT` is flattened into one line |
| Sources CRUD and roles; TXT/MD | `test_sources_crud_roles_and_markdown_ingestion`, `test_text_source_accepts_pasted_text_only`, `test_txt_ingestion` | pass |
| PDF with pages | `test_pdf_ingestion_cites_pages` | pass: the citation is on `page == 2` |
| DOCX | `test_docx_ingestion_is_searchable_with_sections` | pass: section is "Access reviews" |
| No-text PDF | `test_pdf_without_text_fails_safely_and_other_documents_stay_usable` | pass: `no_text`, 1 attempt, no stack trace; the source stays `ready` |
| File security | `test_unsafe_or_unsupported_files_are_rejected` (7 cases), `test_oversized_files_are_rejected` | pass: `unsafe_filename`, `unsupported_file`, `invalid_file` and 413 `file_too_large`; no rows, jobs or files are created |
| Duplicate upload | `test_duplicate_upload_is_rejected_without_new_chunks` | pass: 409 `duplicate_document`; chunk count unchanged |
| Update and reindex | `test_new_content_and_reindex_replace_chunks_without_duplicates` | pass: v2 replaces v1, old chunk ids are gone, new text is searchable, reindex adds no duplicates, the v1 file is pruned |
| Hybrid ranking | `test_hybrid_ranking_combines_semantic_and_lexical_deterministically` | pass: semantic prefers `rotation.txt` and keyword prefers `facilities.txt`; hybrid (0.7/0.3) ranks `facilities.txt` first; score = formula ± 2e-4; repeated query gives an identical response; weak match dropped |
| No match | `test_no_match_returns_insufficient_knowledge` | pass: `insufficient`; agent answer is exactly the insufficient-knowledge sentence; `citations == []` |
| Filter, top-k, budget, diversity | `test_source_filter_top_k_context_budget_and_diversity` | pass |
| Citations map to chunks | `test_single_agent_rag_answers_with_citations_that_map_to_chunks` | pass: every `[K#]` maps to a retrieved chunk id in the DB and the right document; no fabricated ids; no vectors in events |
| Tool and grant both required | `test_knowledge_requires_both_the_tool_and_a_source_grant`, `test_tool_arguments_cannot_widen_source_access` | pass |
| Memory + RAG | `test_memory_and_knowledge_answer_together_with_citations_only_for_knowledge` | pass: Maya Chen comes from memory with no `[K]`; the requirement is cited |
| Archive | `test_archived_sources_are_excluded_and_cannot_be_assigned` | pass: excluded at once; 409 on assign or upload; unarchive restores |
| Delete | `test_deleting_a_source_removes_documents_chunks_grants_jobs_and_files` | pass: 0 rows in every knowledge table and in jobs; files removed |
| Team RAG | `test_team_rag_uses_the_researchers_grant_and_cites_findings`, `test_team_without_knowledge_grants_is_unchanged` | pass: only the researcher calls the tool; the handoff to it carries no knowledge; citations match the findings; score 92; team detail lists member sources |
| Prompt injection | `test_injected_document_text_cannot_change_tools_or_permissions` | pass: tools and grants unchanged; the restricted source is never searched; 0 approvals and 0 executions |
| Policy bypass | `test_knowledge_cannot_bypass_policy` | pass: a "deletion is pre-approved" document still gives `delete_record` → deny; email still `require_approval`; 0 executions |
| Tenant isolation | `test_cross_tenant_knowledge_is_invisible_and_unassignable` | pass: 404 on every A resource from B; search ignores A's ids; composite FKs raise `IntegrityError` for a cross-tenant grant and a cross-tenant chunk |
| Vector filter inside SQL (PostgreSQL) | `test_vector_queries_filter_tenant_and_sources_inside_sql` | pass: every `<=>` and `to_tsquery` statement contains `organization_id =` and `source_id IN`; identical content in Org B is not returned |
| Worker path | `test_upload_returns_processing_and_the_worker_ingests` | pass: 201 `processing` / `queued` in under 2 s, 0 chunks until the worker runs |
| Retry idempotency | `test_transient_embedding_failures_retry_without_duplicate_chunks` | pass: attempt 1 `retrying` (`embedding_unavailable`), attempt 2 completes; exhaustion fails at attempt 3 with no duplicates |
| Redis loss | `test_lost_redis_message_is_recovered_without_duplicates` | pass: queued job has `enqueued_at` NULL; recovery re-sends; a duplicate delivery is a no-op |
| Worker crash | `test_worker_crash_mid_ingestion_is_recovered_consistently` | pass: stale heartbeat → `worker_lost` re-queue → attempt 2 completes; counts consistent |
| Cancel | `test_ingestion_can_be_cancelled_queued_or_running` | pass: queued job cancelled at once; running job stops at the next stage; current chunks survive |
| Busy guards | `test_busy_documents_cannot_be_replaced_deleted_or_archived` | pass |

**Changed tests outside M9:** `test_migrations.py` now expects revision 0009, the knowledge tables, `vector(384)` and a 19-character `job_type`, and adds a 0009→0008→0009 step.

**Bug found by the suite:** `latest_job` could tie on `created_at`, because SQLite stores `CURRENT_TIMESTAMP` at one-second resolution. Fixed: `create_job` now stamps `created_at` with microseconds. The test is now stable (six consecutive passes).

## Live stack (API through the worker)

Source "M9 smoke: API", 3-page `Enterprise Security Requirements.pdf`:
- upload returned in 32–48 ms with `processing` / `queued`;
- the worker ingested it in 80–91 ms (3 chunks, `pypdf`, 1057 characters);
- the search returned K1 (page 1, hybrid 0.54) and K2 (page 3);
- an unrelated query returned `insufficient: true`;
- the source was deleted (204);
- the worker log shows `knowledge_ingestion` with `document_id`, chunk count and duration, and no content.

## Browser validation (QA Org A / QA Org B)

| Step | Result |
| --- | --- |
| Create source | "Enterprise Security Knowledge" (file) → Draft |
| Upload, Processing → Ready | Worker stopped: PDF row showed **Processing · Queued for the worker** with Cancel. Worker restarted: 2 s polling switched it to **Ready · 3 chunks · 3 pages · 52 ms** |
| More types | `Acme Security Addendum.md`: Ready, 2 chunks. `Vendor Onboarding Policy.docx`: Ready, 3 chunks. Source: Ready, 3 documents, 8 chunks |
| Duplicate | Same PDF under a new name: "This content is already in the source as 'Enterprise Security Requirements.pdf'." |
| Search | "What security controls are required for enterprise customers?": K1 PDF page 1 (hybrid 54% / semantic 43% / keyword 80%), K2 MD "Additional requirements" (27%), K3 PDF page 3 (25%), with the formula line and 8 candidates |
| Agent RAG | "Knowledge Analyst" got `internal:knowledge_search` and the source through the UI. Run `7b93243d`: intent `knowledge_search`, tool `knowledge_search`, answer with K1–K3 chips. Run detail: Knowledge retrieval panel (3 retrieved, 3 cited, 8 candidates, scores) and citations with document, page and section |
| No match | "What is the best chocolate cake recipe…?": "I could not find enough information in the connected knowledge sources." |
| Memory + RAG | In thread "Browser QA: Acme renewal", "Who owns the account and what security requirement applies?": "From thread memory: Acme Corporation: account owner Maya Chen, region North America…" (no citation), then knowledge claims with `[K#]` |
| Team RAG | QA Researcher got the tool and source. Team run `97f60a6f` (objective plus Acme thread) completed: researcher called `internal:knowledge_search`; Knowledge findings show K1 (Acme addendum, Scope) and K2 (PDF page 1); validation approved 95%; score 92; memory context "Thread memory: 8 · … · thread summary"; researcher handoff carried only `company, objective` |
| Archive | Archived source shows "8 chunks (excluded while archived)". Agent re-run `518223ba`: insufficient-knowledge answer, "Sources searched: None: every source assigned to this agent is archived". Unarchive restored it |
| Cross-tenant | QA Org B: empty knowledge list; Org A's source and run URLs show "not found in QA Org B" |
| Responsive | 7 M9-affected pages (knowledge list, new, source detail, run detail, agent detail, team run, team) at 390, 768, 1024 and 1440: page overflow **0 px in all 28 cases**. A 375 px mobile screenshot was also checked |
| Console | Only the expected 404s (cross-tenant checks) and the 409 (duplicate upload). No uncaught errors |

Issues found in the browser and fixed:
1. **Squeezed tool rows.** The new, longer `knowledge_search` description squeezed `.tool-row` names into a one-character column (a pre-M9 flex rule). Now `flex: 1 1 200px`.
2. **Stale tool warning.** The knowledge section kept saying "tool not assigned" after assignment; it now reloads when tools change.
3. **Misleading archived explanation.** It said "no passage passed the threshold" when nothing was searchable.
4. **Search panel spacing** on the list page.

## Migration

- **Live:** `alembic upgrade head` → `0009_knowledge_rag`; `alembic check` → "No new upgrade operations detected".
- **First copy** (restored from the pre-M9 dump): 0008 → 0009 → 0008 → 0009 with `check` clean; counts `12|17|1289|26|4|50|61|14|29` unchanged.
- **Final round trip** (fresh copy of live data, `nexusflow_m9_roundtrip`):
  - Before: M1–M8 counts `12|17|1357|27|4|52|65|16|38`; knowledge `1|3|8|2|3` (sources, documents, chunks, grants, ingestion jobs).
  - Downgrade to 0008: `12|17|1357|27|4|52|65|16|35`. Only the 3 `knowledge_ingestion` jobs and the knowledge tables were removed; `vector 0.8.6` stays installed.
  - Upgrade: head, `check` clean. The copy was then dropped.
- **Test suite:** `test_migrations.py` runs the full chain on PostgreSQL under a narrowed `search_path`; the migration makes the extension's schema resolvable.

## M1–M8 regression

- **Test suites:** all M1–M8 suites pass on SQLite and PostgreSQL. Agents without the knowledge tool behave exactly as before; their intents, tools and outputs are unchanged.
- **Teams:** without grants, teams produce the same result (score 92, no `citations` key).
- **Memory:** recall still works for agents without knowledge access.
- **Jobs and approvals:** the M7 job tests and M6 approval/policy tests pass unchanged.

## Caveats

- **Lexical embeddings:** the deterministic embedder relates vocabulary and word forms, not meaning; use a real model in production (an OpenAI provider is included but was not exercised live).
- **Team queries:** the deterministic team researcher queries with the full objective, so its top passages follow the objective's wording.
- **No OCR**, no URL ingestion; the embedding dimension is fixed at 384.
- **Browser upload method:** files were attached to the page's real `<input type=file>` with DataTransfer (bytes from the repo's `docs/demo-knowledge/`), because the browser pane cannot drive the OS file dialog. The upload request itself went through the normal UI button, proxy and API.
- **QA credentials:** the QA accounts from the ignored mode-0600 `.env.qa-validation` were reused through the existing browser session; no password was typed in this pass.
