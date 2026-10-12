import { AgentDetail } from "@/components/agents/agent-detail";

export const metadata = { title: "Agent · NexusFlow AI" };

export default async function AgentPage({
  params,
}: {
  params: Promise<{ agentId: string }>;
}) {
  const { agentId } = await params;
  return <AgentDetail key={agentId} agentId={agentId} />;
}
