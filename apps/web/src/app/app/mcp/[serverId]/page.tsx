import { McpServerDetail } from "@/components/mcp/server-detail";

export const metadata = { title: "MCP server · NexusFlow AI" };

export default async function McpServerPage({
  params,
}: {
  params: Promise<{ serverId: string }>;
}) {
  const { serverId } = await params;
  return <McpServerDetail key={serverId} serverId={serverId} />;
}
