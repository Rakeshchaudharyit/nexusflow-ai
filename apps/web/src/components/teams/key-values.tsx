function render(value: unknown): string {
  if (value === null || value === undefined) return "—";
  if (Array.isArray(value))
    return value.length ? value.map((item) => render(item)).join("; ") : "none";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

/** Compact, read-only rendering of a structured agent output. */
export function KeyValues({
  value,
  hide = [],
}: {
  value: Record<string, unknown> | null;
  hide?: string[];
}) {
  if (!value) return <p className="muted-text">No output.</p>;
  const entries = Object.entries(value).filter(([key]) => !hide.includes(key));
  return (
    <dl className="details compact">
      {entries.map(([key, item]) => (
        <div key={key} className="contents">
          <dt>{key.replaceAll("_", " ")}</dt>
          <dd>{render(item)}</dd>
        </div>
      ))}
    </dl>
  );
}
