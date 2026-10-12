import { NexusFlowLogo } from "@/components/ui/nexusflow-brand";
import Link from "next/link";
import { FoundationStatus } from "@/components/foundation-status";

const capabilities = [
  [
    "01",
    "Multi-Agent Orchestration",
    "Coordinated agents with clear responsibilities.",
  ],
  [
    "02",
    "MCP Tool Integration",
    "Controlled access to tools and external systems.",
  ],
  [
    "03",
    "Human-in-the-Loop",
    "Human oversight at critical workflow decisions.",
  ],
  ["04", "Execution Observability", "Visibility into how workflows execute."],
];

export default function Home() {
  return (
    <div className="shell">
      <header>
        <Link className="brand" href="/" aria-label="NexusFlow AI home">
          <NexusFlowLogo/>
        </Link>
        <div className="landing-actions">
          <Link href="/login">Sign in</Link>
          <Link href="/register">Create workspace ↗</Link>
          <span className="milestone">AGENT INFRASTRUCTURE</span>
        </div>
      </header>
      <main>
        <section className="intro">
          <p className="eyebrow">INFRASTRUCTURE FIRST. INTELLIGENCE NEXT.</p>
          <h1>
            NexusFlow AI
            <span>
              Multi-Agent MCP &amp;
              <br className="desktop-break" /> LangGraph Platform
            </span>
          </h1>
          <p className="description">
            Production-oriented infrastructure for orchestrating AI agents,
            tools, approvals and observable workflows.
          </p>
          <div className="stage">
            <span aria-hidden="true" />
            LangGraph orchestration · MCP tools · Policy controls
          </div>
        </section>
        <FoundationStatus />
        <section className="capabilities" aria-labelledby="capabilities-title">
          <div className="section-heading">
            <h2 id="capabilities-title">Infrastructure for every agent workflow</h2>
            <span>PLATFORM CAPABILITIES</span>
          </div>
          <div className="capability-grid">
            {capabilities.map(([number, title, description]) => (
              <article key={number}>
                <span className="card-number">/{number}</span>
                <h3>{title}</h3>
                <p>{description}</p>
              </article>
            ))}
          </div>
        </section>
      </main>
      <footer>
        <span>
          NexusFlow AI <span className="footer-divider">/</span> Agent infrastructure
        </span>
        <span>
          v0.1.0 <span className="footer-divider">/</span> Agent orchestration platform
        </span>
      </footer>
    </div>
  );
}
