import type { Span, SpanType } from "./api/observability";

export const SPAN_LABELS: Record<SpanType, string> = {
  worker: "Worker",
  graph_node: "Node",
  agent: "Agent",
  tool: "Tool",
  mcp: "MCP",
  knowledge_search: "Knowledge",
  memory_retrieval: "Memory",
  policy: "Policy",
  approval: "Approval",
  action: "Action",
  retry: "Retry",
};

/** Real measured durations; sub-millisecond steps are shown as such, never rounded up. */
export function formatMs(value: number | null | undefined): string {
  if (value === null || value === undefined) return "—";
  if (value < 0.1) return "<0.1 ms";
  if (value < 10) return `${value.toFixed(2)} ms`;
  if (value < 1000) return `${Math.round(value)} ms`;
  return `${(value / 1000).toFixed(2)} s`;
}

export type TreeRow = { span: Span; depth: number; hasChildren: boolean };

/** Depth-first rows (children in recording order) for the expandable trace tree. */
export function buildTree(spans: Span[]): TreeRow[] {
  const children = new Map<string | null, Span[]>();
  const known = new Set(spans.map((span) => span.id));
  for (const span of [...spans].sort((a, b) => a.sequence - b.sequence)) {
    const parent = span.parent_span_id && known.has(span.parent_span_id) ? span.parent_span_id : null;
    children.set(parent, [...(children.get(parent) ?? []), span]);
  }
  const rows: TreeRow[] = [];
  const visit = (parent: string | null, depth: number) => {
    for (const span of children.get(parent) ?? []) {
      rows.push({ span, depth, hasChildren: (children.get(span.id) ?? []).length > 0 });
      visit(span.id, depth + 1);
    }
  };
  visit(null, 0);
  return rows;
}

/** Rows hidden because an ancestor is collapsed. */
export function visibleRows(rows: TreeRow[], collapsed: Set<string>): TreeRow[] {
  const parentOf = new Map(rows.map((row) => [row.span.id, row.span.parent_span_id]));
  const hidden = (id: string | null): boolean => {
    let current = id ? parentOf.get(id) ?? null : null;
    while (current) {
      if (collapsed.has(current)) return true;
      current = parentOf.get(current) ?? null;
    }
    return false;
  };
  return rows.filter((row) => !hidden(row.span.id));
}

/** Waterfall bar geometry in percent of the trace window (a minimum width keeps tiny
 * spans visible; the label always shows the true duration). */
export function bar(span: Pick<Span, "offset_ms" | "duration_ms">, total: number) {
  const window = Math.max(total, 0.001);
  const left = Math.min(Math.max((span.offset_ms / window) * 100, 0), 99.4);
  const width = Math.max(((span.duration_ms ?? 0) / window) * 100, 0.6);
  return { left, width: Math.min(width, 100 - left) };
}

/** Scalar metadata worth showing, in a stable order, without nulls. */
export function metadataEntries(metadata: Record<string, unknown>): [string, string][] {
  return Object.entries(metadata)
    .filter(([, value]) => value !== null && value !== undefined && value !== "")
    .map(([key, value]): [string, string] => [
      key.replaceAll("_", " "),
      Array.isArray(value) ? value.join(", ") || "—" : String(value),
    ])
    .slice(0, 16);
}

export const percent = (value: number | null | undefined) =>
  value === null || value === undefined ? "—" : `${Math.round(value * 1000) / 10}%`;

export function signedPercent(value: number | null | undefined): string {
  if (value === null || value === undefined) return "—";
  const points = Math.round(value * 1000) / 10;
  return `${points > 0 ? "+" : ""}${points} pts`;
}

export function signedMs(value: number | null | undefined): string {
  if (value === null || value === undefined) return "—";
  return `${value > 0 ? "+" : ""}${value} ms`;
}
