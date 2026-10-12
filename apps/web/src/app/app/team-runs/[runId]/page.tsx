import { TeamRunDetail } from "@/components/teams/team-run-detail";

export const metadata = { title: "Team run · NexusFlow AI" };

export default async function TeamRunPage({ params }: { params: Promise<{ runId: string }> }) {
  const { runId } = await params;
  return <TeamRunDetail key={runId} runId={runId} />;
}
