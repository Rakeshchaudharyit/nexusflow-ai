export function NexusFlowMark({ className = "" }: { className?: string }) {
 return <svg className={`nexus-mark ${className}`} viewBox="0 0 48 48" fill="none" aria-hidden="true"><path className="mark-route" d="M9 37V11h8l14 26h8V11" stroke="currentColor" strokeWidth="3" strokeLinejoin="round"/><path d="M9 24h8M31 24h8" stroke="currentColor" strokeWidth="2"/><circle cx="9" cy="11" r="4" fill="currentColor"/><circle cx="39" cy="37" r="4" fill="currentColor"/></svg>;
}
export function NexusFlowLogo() { return <span className="nexus-logo"><NexusFlowMark/><span>NexusFlow<span className="logo-ai"> AI</span></span></span>; }
export function NexusFlowLoader({ label = "Initializing workspace…" }: { label?: string }) { return <div className="nexus-loader" role="status"><NexusFlowMark/><span>{label}</span><span className="loader-route" aria-hidden="true"><i/><i/><i/></span></div>; }
export function identityCode(name: string) { return name.replace(/([a-z])([A-Z])/g,"$1 $2").split(/[^a-zA-Z0-9]+/).filter(Boolean).map(word=>word[0]).join("").slice(0,2).toUpperCase() || "AG"; }
