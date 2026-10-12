import { NexusFlowLoader } from "./nexusflow-brand";
import Link from "next/link";
import type { ReactNode } from "react";

const paths: Record<string, string> = {
  overview: "M3 3h7v7H3z M14 3h7v7h-7z M3 14h7v7H3z M14 14h7v7h-7z",
  agent: "M5 3v18 M19 3v18 M5 7h7l7 10 M5 17h7l7-10",
  team: "M9 3h6v6H9z M3 15h6v6H3z M15 15h6v6h-6z M12 9v3 M6 15v-3h12v3",
  server: "M4 3h16v7H4z M4 14h16v7H4z M7 6h1 M7 17h1 M11 6h6 M11 17h6",
  run: "m9 5 11 7-11 7z M4 5v14",
  trace: "M5 3v18 M5 6h9 M5 12h14 M5 18h9",
  shield: "m12 3 8 3v6c0 5-8 9-8 9s-8-4-8-9V6z m-4 9 3 3 5-6",
  logout: "M9 4H4v16h5 M10 12h11 m-4-4 4 4-4 4",
  menu: "M4 6h16 M4 12h16 M4 18h16",
  arrow: "M5 12h14 m-5-5 5 5-5 5",
  memory: "M6 4h12v16H6z M9 8h6 M9 12h6 M9 16h3",
  thread: "M4 5h16v10H9l-5 4z M8 9h8 M8 12h5",
  knowledge: "M4 4h6a2 2 0 0 1 2 2v14a2 2 0 0 0-2-2H4z M20 4h-6a2 2 0 0 0-2 2v14a2 2 0 0 1 2-2h6z",
  waterfall: "M3 5h8 M6 10h9 M9 15h6 M12 20h9",
  evaluation: "M4 4h16v16H4z m4 8 3 3 5-6",
};
export function Icon({ name }: { name: string }) {
  return <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d={paths[name] ?? paths.agent} /></svg>;
}
export function PageHeader({ eyebrow, title, description, actions }: { eyebrow: string; title: string; description?: string; actions?: ReactNode }) {
  return <div className="page-header"><div><p className="eyebrow">{eyebrow}</p><h1>{title}</h1>{description && <p className="page-description">{description}</p>}</div>{actions}</div>;
}
export function SectionCard({ title, children, className = "" }: { title?: string; children: ReactNode; className?: string }) {
  return <section className={`panel ${className}`}>{title && <h2>{title}</h2>}{children}</section>;
}
export function MetricCard({ label, value, href, icon }: { label: string; value: number; href: string; icon: string }) {
  return <Link className="metric-card" href={href}><div><span>{label}</span><Icon name={icon} /></div><strong>{value}</strong><span className="metric-link">View resources <Icon name="arrow" /></span></Link>;
}
export function RiskBadge({ risk }: { risk: string }) {
  return <span className={`risk-badge risk-${risk}`}>{risk} risk</span>;
}
export function EmptyState({ title, description, href, action }: { title: string; description: string; href: string; action: string }) {
  return <div className="empty-state"><Icon name="overview" /><h3>{title}</h3><p>{description}</p><Link href={href}>{action} →</Link></div>;
}
export function LoadingState() {
  return <div className="resource-loading"><NexusFlowLoader/><div className="loading-rail"/><div className="loading-rail short"/></div>;
}
