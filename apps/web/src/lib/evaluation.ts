import type { CaseChange, EvaluationCase } from "./api/evaluation";

/** Human-readable expectation lines for a case (only the expectations that are set). */
export function expectationLines(
  expected: Partial<EvaluationCase> | Record<string, unknown>,
): string[] {
  const source = expected as Record<string, unknown>;
  const read = (key: string) => source[key] ?? source[`expected_${key}`];
  const lines: string[] = [];
  const status = read("status");
  if (status) lines.push(`status = ${status}`);
  const intent = read("intent");
  if (intent) lines.push(`intent = ${intent}`);
  const tool = read("tool_key");
  if (tool) lines.push(tool === "none" ? "no tool call" : `tool ${tool}`);
  for (const phrase of (read("output_contains") as string[] | undefined) ?? [])
    lines.push(`contains "${phrase}"`);
  for (const phrase of (read("output_excludes") as string[] | undefined) ?? [])
    lines.push(`excludes "${phrase}"`);
  for (const [path, value] of Object.entries((read("values") as object | undefined) ?? {}))
    lines.push(`${path} = ${JSON.stringify(value)}`);
  const decision = read("policy_decision");
  if (decision) lines.push(`policy ${decision}`);
  const action = read("action_type");
  if (action) lines.push(`action ${action}`);
  const documents = (read("citation_documents") as string[] | undefined) ?? [];
  if (documents.length) lines.push(`cites ${documents.join(", ")} (top ${read("retrieval_k") ?? 5})`);
  if (read("no_match")) lines.push("no-match response");
  return lines;
}

export const CHANGE_LABELS: Record<CaseChange["change"], string> = {
  regression: "Regression",
  improvement: "Improvement",
  unchanged: "Unchanged",
  new: "New case",
  removed: "Removed",
};

/** Comma/newline separated phrases from a form field. */
export const phrases = (value: string) =>
  value
    .split(/[\n,]/)
    .map((item) => item.trim())
    .filter(Boolean);

/** "path=value" lines into a typed map (numbers and booleans parsed, else strings). */
export function parseValues(text: string): Record<string, unknown> {
  const values: Record<string, unknown> = {};
  for (const line of text.split("\n")) {
    const [path, ...rest] = line.split("=");
    if (!path?.trim() || !rest.length) continue;
    const raw = rest.join("=").trim();
    values[path.trim()] =
      raw === "true" ? true : raw === "false" ? false : raw !== "" && !Number.isNaN(Number(raw)) ? Number(raw) : raw;
  }
  return values;
}
