import { RunDetail } from "@/components/agents/run-detail";

export const metadata = { title: "Run · NexusFlow AI" };

export default async function RunPage({
  params,
}: {
  params: Promise<{ runId: string }>;
}) {
  const { runId } = await params;
  return <RunDetail runId={runId} />;
}
