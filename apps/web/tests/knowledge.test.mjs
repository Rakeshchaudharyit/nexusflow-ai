import assert from "node:assert/strict";
import { test } from "node:test";
import { freshClients, json, loadModule, session } from "./client-loader.mjs";

const ORG = "77777777-7777-4777-8777-777777777777";
const knowledge = await loadModule("lib/knowledge.ts");

async function signedIn(context, respond = () => json({})) {
  const { auth, client } = await freshClients("knowledge");
  const calls = [];
  context.mock.method(globalThis, "fetch", async (path, init) => {
    if (path.endsWith("/login")) return session("token-1");
    calls.push({ path, init });
    return respond(path, init);
  });
  await auth.login("owner@example.com", "password");
  return { client, calls };
}

const documentOf = (overrides) => ({
  status: "ready",
  chunk_count: 4,
  extraction: { pages: 2 },
  ingestion_ms: 31,
  error_code: null,
  error_message: null,
  ingestion: null,
  ...overrides,
});

test("answers split into prose and [K#] citation chips; ids are never invented", () => {
  assert.deepEqual(knowledge.splitCitations("Use SSO [K1]. Encrypt data [K2] and [K1]."), [
    { text: "Use SSO " },
    { citation: "K1" },
    { text: ". Encrypt data " },
    { citation: "K2" },
    { text: " and " },
    { citation: "K1" },
    { text: "." },
  ]);
  assert.deepEqual(knowledge.splitCitations("No citations here"), [{ text: "No citations here" }]);
  assert.equal(
    knowledge.locator({ document_name: "Security.pdf", page: 4, section: "Identity" }),
    "Security.pdf · page 4 · Identity",
  );
  assert.equal(knowledge.locator({ document_name: "notes.md", page: null, section: null }), "notes.md");
});

test("files are checked before upload; the server repeats every check", () => {
  assert.equal(knowledge.fileProblem({ name: "policy.PDF", size: 2048 }), null);
  assert.match(knowledge.fileProblem({ name: "tool.exe", size: 10 }), /Unsupported/);
  assert.match(knowledge.fileProblem({ name: "README", size: 10 }), /Unsupported/);
  assert.match(knowledge.fileProblem({ name: "empty.md", size: 0 }), /empty/);
  assert.match(knowledge.fileProblem({ name: "big.docx", size: 11 * 1024 * 1024 }), /10 MB/);
  assert.equal(knowledge.formatBytes(1536), "1.5 KB");
});

test("ingestion states come from real backend fields and drive bounded polling", () => {
  assert.equal(knowledge.documentState(documentOf()), "4 chunks · 2 pages · 31 ms");
  assert.equal(
    knowledge.documentState(
      documentOf({
        status: "processing",
        chunk_count: 0,
        error_code: "embedding_unavailable",
        ingestion: { status: "retrying", attempt: 1, max_attempts: 3, cancellation_requested: false },
      }),
    ),
    "Retrying (attempt 1 of 3) · embedding_unavailable",
  );
  assert.equal(
    knowledge.documentState(
      documentOf({ status: "processing", chunk_count: 0, ingestion: { status: "queued" } }),
    ),
    "Queued for the worker",
  );
  assert.equal(
    knowledge.documentState(
      documentOf({ status: "failed", error_message: "No extractable text was found." }),
    ),
    "No extractable text was found.",
  );
  assert.equal(knowledge.sourceIsBusy({ status: "ready", documents: [documentOf()] }), false);
  assert.equal(
    knowledge.sourceIsBusy({ status: "ready", documents: [documentOf({ status: "processing" })] }),
    true,
  );
  assert.equal(knowledge.sourceIsBusy({ status: "processing" }), true);
  assert.equal(knowledge.assignable("archived"), false);
  assert.equal(knowledge.assignable("failed"), false);
  assert.equal(knowledge.assignable("processing"), true);
});

test("knowledge client scopes every request; uploads are multipart, not JSON", async (context) => {
  const { client, calls } = await signedIn(context, (path) =>
    json(path.includes("documents") ? { document: {}, outcome: "created" } : []),
  );
  await client.listSources(ORG);
  await client.uploadDocument(ORG, "s/1", new File(["# Policy"], "policy.md", { type: "text/markdown" }));
  await client.searchKnowledge(ORG, { query: "SSO?", source_ids: ["s1"] });
  await client.assignAgentKnowledge(ORG, "a1", "s1");
  await client.updateSource(ORG, "s1", { archived: true });
  assert.deepEqual(
    calls.map(({ path, init }) => [path, init.method]),
    [
      ["/api/backend/knowledge-sources", undefined],
      ["/api/backend/knowledge-sources/s%2F1/documents", "POST"],
      ["/api/backend/knowledge/search", "POST"],
      ["/api/backend/agents/a1/knowledge", "POST"],
      ["/api/backend/knowledge-sources/s1", "PATCH"],
    ],
  );
  for (const { init } of calls) assert.equal(init.headers["X-Organization-ID"], ORG);
  const upload = calls[1].init;
  assert.ok(upload.body instanceof FormData && upload.body.get("file").name === "policy.md");
  assert.equal(upload.headers["Content-Type"], undefined); // the browser adds the boundary
  assert.deepEqual(JSON.parse(calls[2].init.body), { query: "SSO?", source_ids: ["s1"] });
  assert.deepEqual(JSON.parse(calls[3].init.body), { source_id: "s1" });
  assert.deepEqual(JSON.parse(calls[4].init.body), { archived: true });
});
