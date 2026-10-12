"use client";
import { NexusFlowLogo, NexusFlowLoader } from "./ui/nexusflow-brand";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import {
  createContext,
  Fragment,
  useContext,
  useEffect,
  useRef,
  useState,
  type FormEvent,
  type ReactNode,
} from "react";
import { useAuth } from "./auth-provider";
import {
  APIError,
  createOrganization,
  getCurrentOrganization,
  getCurrentUser,
  type Organization,
} from "@/lib/api/auth";
import { Icon } from "./ui/design-system";
import { loginURL } from "@/lib/return-path";

const WorkspaceContext = createContext<Organization | null>(null);

// The membership-validated organization for the current /app route.
export function useWorkspace(): Organization {
  const organization = useContext(WorkspaceContext);
  if (!organization) throw new Error("WorkspaceShell is required.");
  return organization;
}

const navigation = [
  { href: "/app", label: "Dashboard", group: "Overview", icon: "overview" },
  { href: "/app/agents", label: "Agents", group: "Build", icon: "agent" },
  { href: "/app/teams", label: "Agent Teams", group: "Build", icon: "team" },
  { href: "/app/mcp", label: "MCP Servers", group: "Build", icon: "server" },
  { href: "/app/knowledge", label: "Knowledge", group: "Build", icon: "knowledge" },
  { href: "/app/memory", label: "Memory", group: "Build", icon: "memory" },
  { href: "/app/runs", label: "Agent Runs", group: "Operate", icon: "run" },
  { href: "/app/team-runs", label: "Team Runs", group: "Operate", icon: "trace" },
  { href: "/app/approvals", label: "Approvals", group: "Operate", icon: "shield" },
  { href: "/app/threads", label: "Threads", group: "Operate", icon: "thread" },
  { href: "/app/traces", label: "Traces", group: "Observe", icon: "waterfall" },
  { href: "/app/evaluations", label: "Evaluations", group: "Observe", icon: "evaluation" },
];
// Resource pages belong to one organization; leave them when the workspace changes.
const tenantResource =
  /^\/app\/(agents|runs|mcp|teams|team-runs|approvals|threads|memory|knowledge|traces|evaluations)\/(?!new$)[^/]+/;

export function WorkspaceShell({ children }: { children: ReactNode }) {
  const auth = useAuth();
  const router = useRouter();
  const pathname = usePathname();
  const [selected, setSelected] = useState<Organization | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [drawer, setDrawer] = useState(false);
  const signingOut = useRef(false);
  const sidebar = useRef<HTMLElement>(null);
  const menuButton = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    if (!drawer) return;
    const focusable = () => Array.from(sidebar.current?.querySelectorAll<HTMLElement>('a[href], button:not([disabled]), select:not([disabled])') ?? []);
    focusable()[0]?.focus();
    function onKey(event: KeyboardEvent) {
      if (event.key === "Escape") { setDrawer(false); menuButton.current?.focus(); }
      if (event.key === "Tab") {
        const items = focusable(); const first = items[0]; const last = items[items.length - 1];
        if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus(); }
        else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus(); }
      }
    }
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [drawer]);
  const user = auth.user;
  useEffect(() => {
    if (auth.status === "anonymous") {
      // An expired session returns here after signing in again; explicit logout does not.
      router.replace(
        signingOut.current
          ? "/login"
          : loginURL(window.location.pathname + window.location.search),
      );
      router.refresh();
    }
  }, [auth.status, router]);
  useEffect(() => {
    if (!user) return;
    let live = true;
    const saved = localStorage.getItem(`nexusflow-organization:${user.id}`);
    const candidate =
      user.organizations.find((org) => org.id === saved) ??
      user.organizations[0];
    if (candidate)
      getCurrentOrganization(candidate.id)
        .then((org) => {
          if (live) setSelected(org);
        })
        .catch((failure) => {
          if (live)
            setError(
              failure instanceof Error
                ? failure.message
                : "Workspace unavailable.",
            );
        });
    return () => {
      live = false;
    };
  }, [user]);
  function enterOrganization(organization: Organization, userId: string) {
    const resource = tenantResource.exec(pathname);
    if (resource) router.push(`/app/${resource[1]}`);
    setSelected(organization);
    localStorage.setItem(`nexusflow-organization:${userId}`, organization.id);
  }
  async function switchOrganization(id: string) {
    if (!user || busy) return;
    setBusy(true);
    setError(null);
    try {
      enterOrganization(await getCurrentOrganization(id), user.id);
    } catch (failure) {
      handleError(failure);
    } finally {
      setBusy(false);
    }
  }
  function handleError(failure: unknown) {
    if (failure instanceof APIError && failure.status === 401)
      void auth.reload();
    setError(
      failure instanceof Error
        ? failure.message
        : "Request failed. Please try again.",
    );
  }
  async function signOut() {
    setBusy(true);
    setError(null);
    signingOut.current = true;
    try {
      await auth.signOut();
      router.replace("/login");
      router.refresh();
    } catch (failure) {
      signingOut.current = false;
      handleError(failure);
    } finally {
      setBusy(false);
    }
  }
  async function addOrganization(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy) return;
    const data = new FormData(event.currentTarget);
    setBusy(true);
    setError(null);
    try {
      const organization = await createOrganization(
        String(data.get("name") ?? "").trim(),
      );
      const updated = await getCurrentUser();
      auth.updateUser(updated);
      enterOrganization(organization, updated.id);
      setCreating(false);
    } catch (failure) {
      handleError(failure);
    } finally {
      setBusy(false);
    }
  }
  if (auth.status === "unavailable")
    return (
      <main className="auth-page">
        <section className="auth-card">
          <h1>Connection interrupted</h1>
          <p className="auth-description">
            Your session could not be restored. Check the API and retry.
          </p>
          <button onClick={() => void auth.reload()} className="primary-button">
            Retry connection
          </button>
        </section>
      </main>
    );
  if (auth.status !== "authenticated" || !user)
    return (
      <main className="auth-page">
        <NexusFlowLoader label="Restoring your session…"/>
      </main>
    );
  return (
    <div className={`shell workspace${drawer ? " drawer-open" : ""}`}>
      {drawer && <button className="drawer-backdrop" aria-label="Close navigation" onClick={() => setDrawer(false)} />}
      <a className="skip-link" href="#main-content">Skip to content</a>
      <aside ref={sidebar} id="app-navigation" className="sidebar" aria-label="Application navigation">
      <header className="sidebar-brand">
        <Link className="brand" href="/">
          <NexusFlowLogo/>
        </Link>
      </header>
      <nav className="workspace-bar" aria-label="Workspace">
        <div>
          <p className="eyebrow">WORKSPACE</p>
          <label className="sr-only" htmlFor="organization">
            Organization
          </label>
          <select
            id="organization"
            value={selected?.id ?? ""}
            onChange={(event) => void switchOrganization(event.target.value)}
            disabled={busy || !selected}
          >
            <option value="" disabled>
              Select workspace
            </option>
            {user.organizations.map((org) => (
              <option key={org.id} value={org.id}>
                {org.name}
              </option>
            ))}
          </select>
        </div>
        <button onClick={() => setCreating(!creating)} disabled={busy}>
          {creating ? "Cancel" : "+ New workspace"}
        </button>
      </nav>
      <nav className="app-nav" aria-label="Sections">
        {["Overview", "Build", "Operate", "Observe"].map(group => <div className="nav-group" key={group}>
          <p className="nav-label">{group}</p>
          {navigation.filter(item => item.group === group).map(item => {
            const active = item.href === "/app" ? pathname === "/app" : pathname.startsWith(item.href);
            return <Link key={item.href} href={item.href} aria-current={active ? "page" : undefined} onClick={() => setDrawer(false)}>
              <span className="nav-coordinate">{String(navigation.indexOf(item)+1).padStart(2,"0")}</span>
              <span className="nav-main"><Icon name={item.icon} /><span>{item.href === "/app" ? "Control plane" : item.label}</span></span>
              <span className="nav-meta" aria-hidden="true">{active && <span className="nav-active-dot" />}</span>
            </Link>;
          })}
        </div>)}
      </nav>
      <div className="sidebar-profile">
        <span className="avatar">{user.first_name.slice(0, 1)}{user.last_name.slice(0, 1)}</span>
        <div><strong>{user.first_name} {user.last_name}</strong><span>{selected?.role ?? "Workspace member"}</span></div>
        <button onClick={signOut} disabled={busy} aria-label="Log out" title="Log out"><Icon name="logout" /></button>
      </div>
      </aside>
      <div className="app-stage">
      <div className="top-bar">
        <button ref={menuButton} className="mobile-menu" onClick={() => setDrawer(!drawer)} aria-expanded={drawer} aria-controls="app-navigation" aria-label="Toggle navigation"><Icon name="menu" /></button>
        <div className="breadcrumb"><span>Workspace</span><span>/</span><strong>{navigation.find(item => item.href !== "/app" && pathname.startsWith(item.href))?.label ?? "Control plane"}</strong></div>
        <span className="top-context"><Icon name="shield" /> Tenant-isolated workspace</span>
      </div>
      <main className="workspace-content" id="main-content">

        {error && (
          <p className="form-error" role="alert">
            {error}
          </p>
        )}
        {creating && (
          <section className="create-workspace">
            <h2>Create another workspace</h2>
            <form onSubmit={addOrganization}>
              <label>
                Workspace name
                <input name="name" required maxLength={120} pattern=".*\S.*" />
              </label>
              <button className="primary-button" disabled={busy}>
                {busy ? "Creating…" : "Create workspace"}
              </button>
            </form>
          </section>
        )}
        {selected ? (
          <WorkspaceContext.Provider value={selected}>
            <Fragment key={selected.id}>{children}</Fragment>
          </WorkspaceContext.Provider>
        ) : (
          <p className="eyebrow" role="status">
            Resolving workspace…
          </p>
        )}
      </main>
      <footer>
        <span>NexusFlow AI <span className="footer-divider">/</span> Agent infrastructure</span>
        <span>LangGraph · MCP · Human oversight</span>
      </footer>
      </div>
    </div>
  );
}
