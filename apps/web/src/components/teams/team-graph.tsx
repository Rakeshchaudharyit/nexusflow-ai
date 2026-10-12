import Link from "next/link";
import type { TeamMember } from "@/lib/api/teams";
import { StatusPill } from "../agents/status-pill";
import { identityCode } from "../ui/nexusflow-brand";
import { roleLabel } from "./roles";
export function TeamGraph({ members }: { members: TeamMember[] }) {
 const ordered = [...members].sort((a,b) => a.position-b.position);
 const tiers = [ordered.filter(m=>m.role==='supervisor'), ordered.filter(m=>!['supervisor','writer','validator'].includes(m.role)), ...ordered.filter(m=>['writer','validator'].includes(m.role)).map(m=>[m])].filter(t=>t.length);
 const height = Math.max(220, tiers.length * 140);
 const points = tiers.map((tier,row)=>tier.map((member,column)=>({member,x:1000*(column+1)/(tier.length+1),y:65+row*140})));
 return <section className="panel graph-panel"><div className="section-heading"><h2>Orchestration fabric</h2><span>{members.length} CONFIGURED NODES</span></div><p className="muted-text">Control rail → specialist lanes → convergence. This is the configured topology; execution order is recorded per run.</p>
 <svg className="orchestration-map" viewBox={`0 0 1000 ${height}`} role="img" aria-label="Configured team orchestration topology">
 <defs><pattern id="fabric-grid" width="25" height="25" patternUnits="userSpaceOnUse"><path d="M25 0H0V25" fill="none" stroke="currentColor" strokeWidth=".35"/></pattern></defs><rect width="1000" height={height} fill="url(#fabric-grid)" className="fabric-grid"/>
 {points.slice(1).map((tier,index)=>{const previous=points[index]; const rail=(previous[0].y+tier[0].y)/2; return <g key={index} className="fabric-routes">{previous.map(({member,x,y})=><path key={member.id} d={`M${x} ${y+20}V${rail}H500`}/>)}{tier.map(({member,x,y})=><path key={member.id} d={`M500 ${rail}H${x}V${y-20}`}/>)}<circle cx="500" cy={rail} r="3"/></g>;})}
 {points.flat().map(({member,x,y})=><a key={member.id} href={`/app/agents/${member.agent_id}`} className={`fabric-node node-${member.role}`}><title>{member.agent_name} · {roleLabel(member.role)} · {member.agent_status}</title><path className="node-diamond" d={`M${x} ${y-22}l22 22-22 22-22-22Z`}/><text x={x} y={y+4} textAnchor="middle" className="fabric-code">{identityCode(roleLabel(member.role))}</text><text x={x} y={y-34} textAnchor="middle" className="fabric-role">{roleLabel(member.role).toUpperCase()}</text><text x={x} y={y+45} textAnchor="middle" className="fabric-name">{member.agent_name.length>32 ? member.agent_name.slice(0,29)+'…' : member.agent_name}</text><text x={x} y={y+63} textAnchor="middle" className="fabric-tools">{member.agent_status.toUpperCase()} · {member.tools.filter(t=>t.is_enabled).map(t=>`${t.tool_type.toUpperCase()} ${t.tool_key.split(":").at(-1)}`).join(" / ") || "NO TOOLS"}</text></a>)}
 </svg>
 <ol className="orchestration-mobile">{tiers.flat().map(member=><li key={member.id}><Link href={`/app/agents/${member.agent_id}`}><span className="agent-code">{identityCode(roleLabel(member.role))}</span><div><span className="eyebrow">{roleLabel(member.role)}</span><strong>{member.agent_name}</strong><span className="muted-text">{member.tools.filter(t=>t.is_enabled).length} enabled tools</span></div><StatusPill status={member.agent_status}/></Link></li>)}</ol>
 <div className="fabric-key mono"><span>◇ Configured agent</span><span>─ Routing relationship</span><span>Actual tool access shown per node</span></div>
 </section>;
}
