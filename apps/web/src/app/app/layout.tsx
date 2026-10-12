import Link from "next/link";
import { headers } from "next/headers";
import { redirect } from "next/navigation";
import { WorkspaceShell } from "@/components/workspace-shell";
import { getServerUser } from "@/lib/api/server";
import { loginURL, PATH_HEADER, returnPath } from "@/lib/return-path";

export const dynamic = "force-dynamic";
export const metadata = { title: "Workspace · NexusFlow AI" };

export default async function AppLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const path = (await headers()).get(PATH_HEADER);
  let user;
  try {
    user = await getServerUser();
  } catch {
    return (
      <main className="auth-page">
        <section className="auth-card">
          <p className="eyebrow">CONNECTION REQUIRED</p>
          <h1>Workspace unavailable</h1>
          <p className="auth-description">
            We could not verify your session. Check API connectivity and retry.
          </p>
          <Link href={returnPath(path)} className="primary-button">
            Retry
          </Link>
        </section>
      </main>
    );
  }
  if (!user) redirect(loginURL(path));
  return <WorkspaceShell>{children}</WorkspaceShell>;
}
