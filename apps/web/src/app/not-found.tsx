import Link from "next/link";

export const metadata = { title: "Page not found · NexusFlow AI" };

export default function NotFound() {
  return (
    <main className="auth-page">
      <section className="auth-card">
        <p className="eyebrow">404</p>
        <h1>Page not found</h1>
        <p className="auth-description">
          This address does not match a NexusFlow page.
        </p>
        <Link href="/app" className="primary-button">
          Go to workspace
        </Link>
      </section>
    </main>
  );
}
