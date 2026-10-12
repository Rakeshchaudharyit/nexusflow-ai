import Link from "next/link";

/** Shown instead of a create form to members; the API refuses these writes anyway. */
export function ManagersOnly({
  action,
  backHref,
  backLabel,
}: {
  action: string;
  backHref: string;
  backLabel: string;
}) {
  return (
    <section className="panel narrow">
      <h1>Not available for your role</h1>
      <p className="muted-text">
        Only workspace owners and admins can {action}.
      </p>
      <Link href={backHref}>{backLabel}</Link>
    </section>
  );
}
