import { NextRequest, NextResponse } from "next/server";
import { backendURL, cookieName } from "@/lib/api/server";

export const dynamic = "force-dynamic";
const uuid = "[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}";
const resourcePaths = [
  /^approvals$/,
  new RegExp(`^approvals/${uuid}(/(approve|reject))?$`, "i"),
  /^organizations$/,
  /^organizations\/current$/,
  new RegExp(`^organizations/${uuid}$`, "i"),
  /^agents$/,
  new RegExp(`^agents/${uuid}$`, "i"),
  new RegExp(`^agents/${uuid}/(runs|tools)$`, "i"),
  new RegExp(`^agents/${uuid}/tools/${uuid}$`, "i"),
  /^tools$/,
  /^agent-teams$/,
  new RegExp(`^agent-teams/${uuid}(/(members|runs))?$`, "i"),
  new RegExp(`^agent-teams/${uuid}/members/${uuid}$`, "i"),
  /^agent-team-runs$/,
  new RegExp(`^agent-team-runs/${uuid}(/cancel)?$`, "i"),
  /^agent-runs$/,
  new RegExp(`^agent-runs/${uuid}(/cancel)?$`, "i"),
  /^mcp-servers$/,
  new RegExp(`^mcp-servers/${uuid}(/(test|discover|tools))?$`, "i"),
  new RegExp(`^mcp-servers/${uuid}/tools/${uuid}$`, "i"),
  /^threads$/,
  new RegExp(`^threads/${uuid}$`, "i"),
  /^memory$/,
  new RegExp(`^memory/${uuid}$`, "i"),
  /^knowledge-sources$/,
  new RegExp(`^knowledge-sources/${uuid}(/(documents|reindex))?$`, "i"),
  new RegExp(`^knowledge-documents/${uuid}(/cancel)?$`, "i"),
  /^knowledge\/search$/,
  new RegExp(`^agents/${uuid}/knowledge(/${uuid})?$`, "i"),
  /^traces$/,
  new RegExp(`^traces/${uuid}$`, "i"),
  /^observability\/summary$/,
  /^evaluation-datasets(\/demo)?$/,
  new RegExp(`^evaluation-datasets/${uuid}(/(cases|runs))?$`, "i"),
  new RegExp(`^evaluation-cases/${uuid}$`, "i"),
  /^evaluation-runs$/,
  new RegExp(`^evaluation-runs/${uuid}(/cancel|/compare/${uuid})?$`, "i"),
];
// Document uploads (multipart) are forwarded as bytes with their own, larger limit; the API
// enforces KNOWLEDGE_MAX_FILE_MB itself.
const uploadPath = new RegExp(`^knowledge-sources/${uuid}/documents$`, "i");
const UPLOAD_LIMIT = 10 * 1024 * 1024 + 64 * 1024;
const forwardedQuery = new Set([
  "status",
  "agent_id",
  "team_id",
  "limit",
  "risk_level",
  "team_run_id",
  "memory_type",
  "scope",
  "thread_id",
  "active",
  "source_type",
  "run_type",
  "run_id",
  "error_code",
  "error_category",
  "origin",
  "since",
  "until",
  "offset",
  "hours",
  "dataset_id",
]);
const authPaths = new Set([
  "auth/register",
  "auth/login",
  "auth/refresh",
  "auth/logout",
  "auth/me",
]);

async function proxy(
  request: NextRequest,
  context: { params: Promise<{ path: string[] }> },
) {
  const path = (await context.params).path.join("/");
  const allowed =
    authPaths.has(path) || resourcePaths.some((pattern) => pattern.test(path));
  if (!allowed)
    return NextResponse.json(
      { error: { code: "not_found", message: "Route not found." } },
      { status: 404 },
    );
  const headers = new Headers();
  for (const name of [
    "content-type",
    "authorization",
    "origin",
    "x-organization-id",
    "user-agent",
  ]) {
    const value = request.headers.get(name);
    if (value) headers.set(name, value);
  }
  const cookie = request.cookies.get(cookieName());
  if (cookie) headers.set("cookie", `${cookie.name}=${cookie.value}`);
  try {
    const upload =
      request.method === "POST" &&
      uploadPath.test(path) &&
      (request.headers.get("content-type") ?? "").startsWith("multipart/form-data");
    if (upload) {
      const declared = Number(request.headers.get("content-length") ?? "0");
      if (declared > UPLOAD_LIMIT)
        return NextResponse.json(
          { error: { code: "file_too_large", message: "Files may be at most 10 MB." } },
          { status: 413 },
        );
    }
    // Enforce limits while streaming, including requests without Content-Length.
    const limit = upload ? UPLOAD_LIMIT : 16384;
    let body: ArrayBuffer | undefined;
    if (["POST", "PATCH", "DELETE"].includes(request.method) && request.body) {
      const reader = request.body.getReader();
      const chunks: Uint8Array[] = [];
      let size = 0;
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        size += value.byteLength;
        if (size > limit) {
          await reader.cancel();
          return NextResponse.json(
            { error: { code: upload ? "file_too_large" : "request_too_large", message: "Request is too large." } },
            { status: 413 },
          );
        }
        chunks.push(value);
      }
      const bytes = new Uint8Array(size);
      let offset = 0;
      for (const chunk of chunks) { bytes.set(chunk, offset); offset += chunk.byteLength; }
      body = bytes.buffer;
    }
    const query = new URLSearchParams();
    for (const [name, value] of request.nextUrl.searchParams)
      if (forwardedQuery.has(name)) query.append(name, value);
    const search = query.size ? `?${query}` : "";
    const upstream = await fetch(backendURL(`/${path}${search}`), {
      method: request.method,
      headers,
      body,
      cache: "no-store",
      redirect: "manual",
      signal: AbortSignal.timeout(upload ? 30000 : 8000),
    });
    const outgoing = new Headers({ "Cache-Control": "no-store" });
    const contentType = upstream.headers.get("content-type");
    if (contentType) outgoing.set("content-type", contentType);
    for (const setCookie of upstream.headers.getSetCookie())
      outgoing.append("set-cookie", setCookie);
    const authenticate = upstream.headers.get("www-authenticate");
    if (authenticate) outgoing.set("www-authenticate", authenticate);
    return new NextResponse(
      upstream.status === 204 ? null : await upstream.text(),
      { status: upstream.status, headers: outgoing },
    );
  } catch {
    return NextResponse.json(
      {
        error: {
          code: "unavailable",
          message: "The API is unavailable. Please try again.",
        },
      },
      { status: 502, headers: { "Cache-Control": "no-store" } },
    );
  }
}

export const GET = proxy;
export const POST = proxy;
export const PATCH = proxy;
export const DELETE = proxy;
