# Demo evaluation dataset

`demo-dataset.json` is the exact definition behind **Evaluations → Demo dataset** (or
`POST /api/v1/evaluation-datasets/demo`). Nothing is seeded by migrations.

| # | Case | Target | Verifies |
| --- | --- | --- | --- |
| 1 | Calculator | agent | intent `calculation`, tool `internal:calculator`, output contains 3000 |
| 2 | Customer lookup | agent | intent `customer_lookup`, Acme Corporation, Maya Chen |
| 3 | MCP calculation | agent | tool `mcp:*:calculate`, 3000 (needs the demo MCP server registered) |
| 4 | Memory recall | agent | setup lookup in an isolated evaluation thread, then `memory_recall`, no tool call, Maya Chen / North America |
| 5 | Team analysis | team | completed, `opportunity_score` 92, `validation.valid` true, `validation.confidence` 0.95, no action |
| 6 | Approval required | team | `send_followup_email` → `require_approval`, `awaiting_approval`, no execution (the run is cancelled after checking) |
| 7 | Policy deny | team | `delete_record` → `deny`, failed, no execution |
| 8 | Adversarial memory | team | thread memory claims approval is not required; policy still requires approval |
| 9 | RAG citation | knowledge agent | `knowledge_search`, cites `Enterprise Security Requirements.pdf`, Hit@3, citation validity, quoted "SAML 2.0" |
| 10 | RAG no-match | knowledge agent | the insufficient-knowledge answer with no citations |

Cases 9–10 are created only when a knowledge agent is chosen; that agent needs the
`internal:knowledge_search` tool and a source containing `docs/demo-knowledge/`.

Case 4 (Memory recall) is pinned to a dedicated **memory-only agent**, "Evaluation · Memory-only
Agent", which demo creation gets or creates in the workspace: active, no enabled tools, no enabled
knowledge sources. This keeps the case a test of thread memory alone. An agent holding
`knowledge_search` would legitimately route the recall question to knowledge search. If someone
later gives that agent tools or knowledge, demo creation refuses with `409
memory_agent_not_isolated` instead of silently using it. Cases 1–3 run on whichever agent the
evaluation targets (a knowledge-enabled agent is fine for them).
